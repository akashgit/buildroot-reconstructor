"""AgentAugmentedObserver — wraps Observer with node-scoped Claude Code agents."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

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

    def observe(
        self,
        coordinate: str,
        spec_overrides: dict[str, Any] | None = None,
    ) -> tuple[BuildrootSpec, str]:
        spec, draft_containerfile = super().observe(coordinate)
        if not draft_containerfile:
            return spec, draft_containerfile

        if spec_overrides:
            self._apply_spec_overrides(spec, spec_overrides)

        gap_report = self._gap_detector.analyze(spec)
        spec.gaps = gap_report

        logger.info(
            "GapDetector found %d gaps for %s — running node agents",
            len(gap_report.entries), coordinate,
        )

        activated = 0
        for agent in self._node_agents:
            if agent.should_activate(gap_report, spec_overrides):
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

    def observe_top_k(
        self,
        coordinate: str,
        k: int = 3,
        spec_overrides: dict[str, Any] | None = None,
    ) -> list[tuple[BuildrootSpec, str]]:
        """Produce up to K (spec, containerfile) variants via top-K candidate forking."""
        spec, draft_containerfile = super().observe(coordinate)
        if not draft_containerfile:
            return [(spec, draft_containerfile)]

        if spec_overrides:
            self._apply_spec_overrides(spec, spec_overrides)

        gap_report = self._gap_detector.analyze(spec)
        spec.gaps = gap_report

        forked_specs: list[BuildrootSpec] = []
        for agent in self._node_agents:
            if agent.should_activate(gap_report, spec_overrides):
                try:
                    candidates = agent.review(
                        spec, context={"containerfile": draft_containerfile},
                    )
                    variants = agent.apply_top_k(spec, candidates, k=k)
                    if variants:
                        forked_specs.extend(variants)
                except Exception:
                    logger.exception("Node agent %s failed in top-K", agent.node_name)

        if not forked_specs:
            for agent in self._node_agents:
                if agent.should_activate(gap_report, spec_overrides):
                    try:
                        candidates = agent.review(
                            spec, context={"containerfile": draft_containerfile},
                        )
                        agent.apply_best(spec, candidates)
                    except Exception:
                        logger.exception("Node agent %s failed", agent.node_name)
            cf = self._re_render(spec)
            cf = self._apply_subdir(spec, cf)
            return [(spec, cf)]

        results: list[tuple[BuildrootSpec, str]] = []
        for variant_spec in forked_specs[:k]:
            cf = self._re_render(variant_spec)
            cf = self._apply_subdir(variant_spec, cf)
            results.append((variant_spec, cf))

        return results

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
        replaced = False
        for line in lines:
            if not replaced and line.strip() == "WORKDIR /build":
                result.append(f"WORKDIR /build/{subdir}")
                replaced = True
            else:
                result.append(line)

        return "\n".join(result) + "\n"

    _SILENTLY_SKIPPED_FIELDS = frozenset({
        "build_tool", "workdir", "artifact_path", "maven_profile",
        "extra_maven_args", "env", "env_vars",
    })

    @staticmethod
    def _apply_spec_overrides(spec: BuildrootSpec, overrides: dict[str, Any]) -> None:
        """Apply spec_overrides dict to the spec, mapping field names to values."""
        for field_name, value in overrides.items():
            if field_name in ("base_image", "image"):
                spec.jdk_spec.base_image = value
            elif field_name == "jdk_version":
                spec.jdk_spec.version = value
            elif field_name == "jdk_distribution":
                spec.jdk_spec.distribution = value
            elif field_name in ("build_command", "build_cmd"):
                spec.build_commands = [value] if isinstance(value, str) else value
            elif field_name == "maven_version":
                spec.maven_version = value
            elif field_name in ("git_tag", "tag", "source_tag"):
                spec.git_tag = value
            elif field_name == "source_repo":
                spec.source_repo = value
            elif field_name == "system_package":
                spec.system_packages = value.split() if isinstance(value, str) else list(value)
            elif field_name in ("extra_packages", "apt_packages"):
                extras = value.split() if isinstance(value, str) else list(value)
                spec.system_packages.extend(extras)
            elif field_name in ("image_setup_cmds", "pre_build_cmds"):
                cmds = [value] if isinstance(value, str) else list(value)
                spec.build_commands = cmds + spec.build_commands
            elif field_name == "pre_build_cmd":
                spec.build_commands = [value] + spec.build_commands
            elif field_name in AgentAugmentedObserver._SILENTLY_SKIPPED_FIELDS:
                pass
            elif field_name.startswith("dockerfile_"):
                pass
            else:
                logger.warning("Unknown spec_override field: %s", field_name)

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
            l2_agent = L2FailureAgent()
            diagnosis = l2_agent.diagnose(spec, containerfile, build_log)
            if diagnosis:
                l2_agent.apply_fixes(spec, diagnosis)
        elif level_reached < 3:
            l3_agent = L3FailureAgent()
            diagnosis = l3_agent.diagnose(spec, containerfile, build_log)
            if diagnosis:
                l3_agent.apply_fixes(spec, diagnosis)
        elif level_reached < 4:
            l4_agent = L4FailureAgent()
            diagnosis = l4_agent.diagnose(
                spec, containerfile, build_log,
                diff_summary=diff_summary,
                comparison_verdict=comparison_verdict,
            )
            if diagnosis:
                l4_agent.apply_fixes(spec, diagnosis)

        if diagnosis and diagnosis.fixes:
            new_containerfile = self._re_render(spec)
            new_containerfile = self._apply_subdir(spec, new_containerfile)
            logger.info(
                "Failure agent produced %d fixes for level %d",
                len(diagnosis.fixes), level_reached,
            )
            return spec, new_containerfile

        return None
