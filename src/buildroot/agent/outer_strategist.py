"""Outer Strategist — hypothesis generation with J(S) scoring and stagnation detection."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

from buildroot.agent.claude_runner import spawn_claude_agent
from buildroot.agent.failure_analyst import FailureAnalysis
from buildroot.agent.guards import MUTABLE_SURFACES

logger = logging.getLogger(__name__)


@dataclass
class CodeChangeHypothesis:
    """A proposed code change to improve the inner loop."""

    target_error_class: str
    files_to_modify: list[str]
    expected_impact: str
    rationale: str
    priority: int = 0

    def to_dict(self) -> dict:
        return {
            "target_error_class": self.target_error_class,
            "files_to_modify": self.files_to_modify,
            "expected_impact": self.expected_impact,
            "rationale": self.rationale,
            "priority": self.priority,
        }


@dataclass
class StrategyScore:
    """J(S) score for a strategy across a cycle."""

    cycle: int
    solve_rate_before: float
    solve_rate_after: float
    j_score: float
    hypothesis: CodeChangeHypothesis | None = None
    verdict: str = ""

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "solve_rate_before": self.solve_rate_before,
            "solve_rate_after": self.solve_rate_after,
            "j_score": self.j_score,
            "hypothesis": self.hypothesis.to_dict() if self.hypothesis else None,
            "verdict": self.verdict,
        }


@dataclass
class StrategyArchive:
    """Archive of strategy scores across outer loop cycles."""

    scores: list[StrategyScore] = field(default_factory=list)
    stagnation_count: int = 0
    j_threshold: float = 0.01

    def add(self, score: StrategyScore) -> None:
        self.scores.append(score)
        if score.j_score < self.j_threshold:
            self.stagnation_count += 1
        else:
            self.stagnation_count = 0

    @property
    def is_stagnant(self) -> bool:
        return self.stagnation_count >= 3

    @property
    def historical_best_solve_rate(self) -> float:
        if not self.scores:
            return 0.0
        return max(s.solve_rate_after for s in self.scores)

    def last_n(self, n: int = 5) -> list[StrategyScore]:
        return self.scores[-n:]

    def save(self, path: Path) -> None:
        data = {
            "scores": [s.to_dict() for s in self.scores],
            "stagnation_count": self.stagnation_count,
            "j_threshold": self.j_threshold,
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> StrategyArchive:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        archive = cls(
            stagnation_count=data.get("stagnation_count", 0),
            j_threshold=data.get("j_threshold", 0.01),
        )
        for s_data in data.get("scores", []):
            hyp_data = s_data.get("hypothesis")
            hypothesis = None
            if hyp_data:
                hypothesis = CodeChangeHypothesis(
                    target_error_class=hyp_data.get("target_error_class", ""),
                    files_to_modify=hyp_data.get("files_to_modify", []),
                    expected_impact=hyp_data.get("expected_impact", ""),
                    rationale=hyp_data.get("rationale", ""),
                    priority=hyp_data.get("priority", 0),
                )
            archive.scores.append(StrategyScore(
                cycle=s_data.get("cycle", 0),
                solve_rate_before=s_data.get("solve_rate_before", 0.0),
                solve_rate_after=s_data.get("solve_rate_after", 0.0),
                j_score=s_data.get("j_score", 0.0),
                hypothesis=hypothesis,
                verdict=s_data.get("verdict", ""),
            ))
        return archive


def compute_j_score(
    solve_rate_start: float,
    solve_rate_end: float,
    window_size: int = 1,
    epsilon: float = 0.01,
) -> float:
    """Compute J(S) = (s_end - s_start) * log(1 + s_start + epsilon) / sqrt(W).

    The log term upweights improvements from higher baselines.
    W is the window size (number of cycles the strategy spans).
    Epsilon prevents J=0 when solve_rate_start=0.
    """
    if window_size <= 0:
        window_size = 1

    delta = solve_rate_end - solve_rate_start
    log_term = math.log(1 + solve_rate_start + epsilon)
    sqrt_w = math.sqrt(window_size)

    return delta * log_term / sqrt_w


STRATEGIST_MODEL = "claude-opus-4-6"

HYPOTHESIS_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "target_error_class": {"type": "string"},
        "files_to_modify": {"type": "array", "items": {"type": "string"}},
        "expected_impact": {"type": "string"},
        "rationale": {"type": "string"},
        "priority": {"type": "integer"},
    },
    "required": [
        "target_error_class",
        "files_to_modify",
        "expected_impact",
        "rationale",
    ],
}

STRATEGIST_SYSTEM_PROMPT = """\
You are a strategy agent for a build-environment reconstruction system.

Your job: analyze failure patterns from a batch of Maven package builds and propose \
a single CodeChangeHypothesis — a targeted code change that will improve the solve rate.

Rules:
- Only propose changes to files in the MUTABLE SURFACES list
- Do NOT propose changes to evaluator.py, eval/score.py, or test fixtures
- Do NOT hardcode package-specific fixes
- Focus on the dominant error class unless it has been previously tried and reverted
- If stagnation is detected (3+ consecutive low-J cycles), propose architectural changes
- Your output MUST be a JSON object matching the CodeChangeHypothesis schema
"""


def propose_hypothesis(
    analysis: FailureAnalysis,
    archive: StrategyArchive,
    kb_patterns: str = "",
    research_report: str = "",
) -> CodeChangeHypothesis:
    """Generate a code change hypothesis using a Claude Code subprocess.

    Falls back to a simple heuristic if the agent fails.
    """
    previously_tried = set()
    for score in archive.scores:
        if score.hypothesis and score.verdict == "revert":
            previously_tried.add(score.hypothesis.target_error_class)

    mutable_list = sorted(MUTABLE_SURFACES)

    archive_context = ""
    for score in archive.last_n(5):
        hyp_target = score.hypothesis.target_error_class if score.hypothesis else "?"
        archive_context += (
            f"- Cycle {score.cycle}: target={hyp_target}, "
            f"verdict={score.verdict}, J={score.j_score:.4f}\n"
        )

    error_freq_text = ""
    for ef in analysis.error_frequencies:
        status = ""
        if ef.error_class in previously_tried:
            status = " [PREVIOUSLY REVERTED]"
        if ef.exhausted_count > 0 and ef.under_explored_count == 0:
            status += " [EXHAUSTED]"
        error_freq_text += (
            f"- {ef.error_class}: count={ef.count}, "
            f"exhausted={ef.exhausted_count}, "
            f"under_explored={ef.under_explored_count}{status}\n"
        )

    research_section = ""
    if research_report:
        research_section = f"\n## Research Report\n{research_report}\n"

    system_prompt = f"""\
{STRATEGIST_SYSTEM_PROMPT}

## Failure Analysis
Total packages: {analysis.total_packages}
Failed: {analysis.failed_packages}
Solved: {analysis.solved_packages}
Solve rate: {analysis.solve_rate:.4f}
Dominant error class: {analysis.dominant_error_class}
Is stagnant: {analysis.is_stagnant}

## Error Frequencies
{error_freq_text or "No errors recorded."}

## Strategy Archive (recent cycles)
{archive_context or "No prior cycles."}

## Previously Tried & Reverted
{', '.join(sorted(previously_tried)) or 'None'}

## Knowledge Base Patterns
{kb_patterns or "No KB patterns available."}
{research_section}
## Mutable Surfaces
{chr(10).join(f"- {s}" for s in mutable_list)}
"""

    task = (
        "Analyze the failure patterns and propose a CodeChangeHypothesis. "
        "Return a JSON object with: target_error_class, files_to_modify, "
        "expected_impact, rationale, and priority (integer)."
    )

    agent_result = spawn_claude_agent(
        task=task,
        system_prompt=system_prompt,
        model=STRATEGIST_MODEL,
        json_schema=HYPOTHESIS_JSON_SCHEMA,
        max_turns=10,
        max_budget_usd=2.0,
        timeout=300,
    )

    if agent_result.ok and agent_result.structured_output:
        data = agent_result.structured_output
        return CodeChangeHypothesis(
            target_error_class=data.get("target_error_class", "unknown"),
            files_to_modify=data.get("files_to_modify", ["src/buildroot/agent/builder.py"]),
            expected_impact=data.get("expected_impact", ""),
            rationale=data.get("rationale", ""),
            priority=data.get("priority", 0),
        )

    logger.warning("Strategist agent failed, using fallback: %s", agent_result.error_message)
    return _fallback_hypothesis(analysis, previously_tried)


def _fallback_hypothesis(
    analysis: FailureAnalysis,
    previously_tried: set[str],
) -> CodeChangeHypothesis:
    """Simple heuristic fallback when the Claude Code strategist fails."""
    if not analysis.error_frequencies:
        return CodeChangeHypothesis(
            target_error_class="unknown",
            files_to_modify=["src/buildroot/agent/builder.py"],
            expected_impact="Improve general build success rate",
            rationale="No specific error class dominant — improve Builder prompts",
        )

    for ef in analysis.error_frequencies:
        if ef.error_class in previously_tried:
            continue
        if ef.exhausted_count > 0 and ef.under_explored_count == 0:
            continue

        return CodeChangeHypothesis(
            target_error_class=ef.error_class,
            files_to_modify=["src/buildroot/agent/builder.py"],
            expected_impact=f"Address {ef.error_class} failures",
            rationale=f"Target dominant error class {ef.error_class} with count={ef.count}",
            priority=1,
        )

    return CodeChangeHypothesis(
        target_error_class="architectural",
        files_to_modify=[
            "src/buildroot/agent/builder.py",
            "src/buildroot/agent/analyzer.py",
        ],
        expected_impact="Architectural improvement to escape local optimum",
        rationale=(
            "Error-class fixes have stagnated. Shifting to structural changes. "
            f"Previously tried: {', '.join(sorted(previously_tried)) or 'none'}"
        ),
        priority=0,
    )
