"""AgentAugmentedObserver — wraps Observer with node-scoped Claude Code agents."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from buildroot.agent.node_agents import ALL_NODE_AGENTS
from buildroot.agent.node_agents.failure_agents import (
    FailureDiagnosis,
    L2FailureAgent,
    L3FailureAgent,
    L4FailureAgent,
)
from buildroot.agent.observer import Observer
from buildroot.generators.containerfile import ContainerfileGenerator
from buildroot.pipeline.gap_detector import GapDetector
from buildroot.pipeline.models import BuildrootSpec

logger = logging.getLogger(__name__)


class AgentAugmentedObserver(Observer):
    """Observer + node-scoped agent review layer.

    Flow:
    1. Run deterministic pipeline via Observer.observe()
    2. Run GapDetector.analyze() on the draft spec
    3. Fire node agents for fields with DEFAULTED or INFERRED gaps
    4. Re-render Containerfile from the updated spec
    """

    def __init__(self, *, skip_deps: bool = False) -> None:
        super().__init__(skip_deps=skip_deps)
        self._gap_detector = GapDetector()
        self._generator = ContainerfileGenerator()
        self._node_agents = [AgentCls() for AgentCls in ALL_NODE_AGENTS]

    def observe(self, coordinate: str) -> tuple[BuildrootSpec, str]:
        spec, draft_containerfile = super().observe(coordinate)
        if not draft_containerfile:
            return spec, draft_containerfile

        gap_report = self._gap_detector.analyze(spec)
        spec.gaps = gap_report

        logger.info(
            "GapDetector found %d gaps for %s — running node agents",
            len(gap_report.entries), coordinate,
        )

        activated = 0
        for agent in self._node_agents:
            if agent.should_activate(gap_report):
                logger.info("  Activating %s for field=%s", agent.node_name, agent.field_name)
                try:
                    candidates = agent.review(
                        spec,
                        context={"containerfile": draft_containerfile},
                    )
                    if agent.apply_best(spec, candidates):
                        activated += 1
                except Exception:
                    logger.exception("Node agent %s failed", agent.node_name)

        logger.info("Node agents: %d/%d activated for %s", activated, len(self._node_agents), coordinate)

        containerfile = self._re_render(spec)
        containerfile = self._apply_subdir(spec, containerfile)

        return spec, containerfile

    def _re_render(self, spec: BuildrootSpec) -> str:
        with tempfile.TemporaryDirectory(prefix="buildroot-rerender-") as tmpdir:
            out = Path(tmpdir)
            self._generator.generate(spec, out)
            containerfile_path = out / "Containerfile"
            if containerfile_path.exists():
                return containerfile_path.read_text()
        return ""

    def _apply_subdir(self, spec: BuildrootSpec, containerfile: str) -> str:
        subdir = spec.pom_data.properties.get("_buildroot_subdir", "")
        if not subdir:
            return containerfile

        lines = containerfile.splitlines()
        result = []
        for line in lines:
            result.append(line)
            if line.strip() == "WORKDIR /build":
                result.append(f"WORKDIR /build/{subdir}")

        return "\n".join(result) + "\n"

    def run_failure_agents(
        self,
        spec: BuildrootSpec,
        containerfile: str,
        level_reached: int,
        build_log: str,
        diff_summary: str = "",
        comparison_verdict: str = "",
    ) -> tuple[BuildrootSpec, str] | None:
        """Run post-build failure agents based on the evaluation level reached."""
        diagnosis: FailureDiagnosis | None = None

        if level_reached < 2:
            agent = L2FailureAgent()
            diagnosis = agent.diagnose(spec, containerfile, build_log)
            if diagnosis:
                agent.apply_fixes(spec, diagnosis)
        elif level_reached < 3:
            agent = L3FailureAgent()
            diagnosis = agent.diagnose(spec, containerfile, build_log)
            if diagnosis:
                agent.apply_fixes(spec, diagnosis)
        elif level_reached < 4:
            agent = L4FailureAgent()
            diagnosis = agent.diagnose(
                spec, containerfile, build_log,
                diff_summary=diff_summary,
                comparison_verdict=comparison_verdict,
            )
            if diagnosis:
                agent.apply_fixes(spec, diagnosis)

        if diagnosis and diagnosis.fixes:
            new_containerfile = self._re_render(spec)
            new_containerfile = self._apply_subdir(spec, new_containerfile)
            logger.info(
                "Failure agent produced %d fixes for level %d",
                len(diagnosis.fixes), level_reached,
            )
            return spec, new_containerfile

        return None
