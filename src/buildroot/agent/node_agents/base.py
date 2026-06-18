"""NodeAgent base class — evidence-ranked candidate proposals via Claude Code subprocess."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from buildroot.agent.claude_runner import AgentResult, spawn_claude_agent
from buildroot.pipeline.models import BuildrootSpec, GapReport, Source

logger = logging.getLogger(__name__)

EVIDENCE_HIERARCHY = [
    "direct_observation",
    "ci_inference",
    "cross_reference",
    "historical_pattern",
    "ecosystem_heuristic",
    "default",
]

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "evidence_type": {
                        "type": "string",
                        "enum": EVIDENCE_HIERARCHY,
                    },
                    "evidence_citations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["value", "evidence_type", "reasoning"],
            },
        },
        "field_updated": {"type": "string"},
    },
    "required": ["candidates", "field_updated"],
}

NODE_MODEL = "claude-opus-4-6"
NODE_MAX_TURNS = 8
NODE_BUDGET_USD = 5.0
NODE_TIMEOUT = 600


@dataclass
class Candidate:
    """A ranked proposal for a spec field value."""

    value: str
    evidence_type: str
    evidence_citations: list[str] = field(default_factory=list)
    reasoning: str = ""

    @property
    def rank(self) -> int:
        try:
            return EVIDENCE_HIERARCHY.index(self.evidence_type)
        except ValueError:
            return len(EVIDENCE_HIERARCHY)


def _evidence_rank(evidence_type: str) -> int:
    try:
        return EVIDENCE_HIERARCHY.index(evidence_type)
    except ValueError:
        return len(EVIDENCE_HIERARCHY)


class NodeAgent:
    """Base class for pipeline node reviewer agents.

    Subclasses set node_name, field_name, and system_prompt, then implement
    _build_task() to compose the per-invocation task description and
    _apply_candidate() to write the winning candidate back into the spec.
    """

    node_name: str = ""
    field_name: str = ""
    system_prompt: str = ""
    allowed_tools: list[str] | tuple[str, ...] = ("Read", "Bash", "WebSearch")

    def should_activate(
        self, gap_report: GapReport, spec_overrides: dict[str, Any] | None = None,
    ) -> bool:
        if spec_overrides and self.field_name in spec_overrides:
            return True
        for entry in gap_report.entries:
            if entry.field == self.field_name or entry.field.startswith(self.field_name):
                if entry.source in (Source.DEFAULTED, Source.INFERRED):
                    return True
        return False

    _TURN_BUDGET_SUFFIX = (
        "\n\nIMPORTANT: You have a strict turn budget. Produce your structured JSON "
        "output (candidates array) within a few tool calls. Do NOT exhaustively search — "
        "return your best findings quickly. An empty candidates list is acceptable."
    )

    def review(self, spec: BuildrootSpec, context: dict[str, Any] | None = None) -> list[Candidate]:
        ctx = context or {}
        task = self._build_task(spec, ctx)
        build_error_ctx = ctx.get("build_error_context", "")
        if build_error_ctx:
            task += f"\n\n## Build Failure Context\n{build_error_ctx}"
        result = spawn_claude_agent(
            task=task,
            system_prompt=self.system_prompt + self._TURN_BUDGET_SUFFIX,
            model=NODE_MODEL,
            json_schema=CANDIDATE_SCHEMA,
            max_turns=NODE_MAX_TURNS,
            max_budget_usd=NODE_BUDGET_USD,
            timeout=NODE_TIMEOUT,
            allowed_tools=self.allowed_tools,
        )
        if result.is_error:
            logger.warning("Node agent %s failed: %s", self.node_name, result.error_message)
            return []
        return self._parse_candidates(result)

    def apply_best(self, spec: BuildrootSpec, candidates: list[Candidate]) -> bool:
        if not candidates:
            return False
        best = sorted(candidates, key=lambda c: c.rank)[0]
        logger.info(
            "Node %s applying candidate: value=%s evidence=%s",
            self.node_name, best.value[:80], best.evidence_type,
        )
        self._apply_candidate(spec, best)
        return True

    def apply_top_k(
        self, spec: BuildrootSpec, candidates: list[Candidate], k: int = 3,
    ) -> list[BuildrootSpec]:
        """Fork spec K times, one per top-K candidate. Returns K spec variants."""
        if not candidates:
            return []
        ranked = sorted(candidates, key=lambda c: c.rank)[:k]
        specs: list[BuildrootSpec] = []
        for candidate in ranked:
            forked = copy.deepcopy(spec)
            self._apply_candidate(forked, candidate)
            logger.info(
                "Node %s forked spec with candidate: value=%s evidence=%s",
                self.node_name, candidate.value[:80], candidate.evidence_type,
            )
            specs.append(forked)
        return specs

    def _build_task(self, spec: BuildrootSpec, context: dict[str, Any]) -> str:
        raise NotImplementedError

    def _apply_candidate(self, spec: BuildrootSpec, candidate: Candidate) -> None:
        raise NotImplementedError

    def _parse_candidates(self, result: AgentResult) -> list[Candidate]:
        output = result.structured_output
        if not output or "candidates" not in output:
            logger.warning("Node %s returned no structured candidates", self.node_name)
            return []
        candidates = []
        for item in output["candidates"]:
            candidates.append(Candidate(
                value=item.get("value", ""),
                evidence_type=item.get("evidence_type", "default"),
                evidence_citations=item.get("evidence_citations", []),
                reasoning=item.get("reasoning", ""),
            ))
        return sorted(candidates, key=lambda c: c.rank)

    def _spec_summary(self, spec: BuildrootSpec) -> str:
        parts = [
            f"Group ID: {spec.pom_data.group_id}",
            f"Artifact ID: {spec.pom_data.artifact_id}",
            f"Version: {spec.pom_data.version}",
            f"Source repo: {spec.source_repo}",
            f"Git tag: {spec.git_tag}",
            f"JDK version: {spec.jdk_spec.version}",
            f"JDK distribution: {spec.jdk_spec.distribution}",
            f"Base image: {spec.jdk_spec.base_image}",
            f"Maven version: {spec.maven_version}",
            f"Build commands: {spec.build_commands}",
        ]
        return "\n".join(parts)
