"""Outer Strategist — hypothesis generation with J(S) scoring and stagnation detection."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

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


def propose_hypothesis(
    analysis: FailureAnalysis,
    archive: StrategyArchive,
    kb_patterns: str = "",
) -> CodeChangeHypothesis:
    """Generate a code change hypothesis based on failure analysis and archive state.

    If the archive shows stagnation (J < threshold for 3 consecutive cycles),
    shifts from error-class fixes to architectural changes.
    """
    previously_tried = set()
    for score in archive.scores:
        if score.hypothesis and score.verdict == "revert":
            previously_tried.add(score.hypothesis.target_error_class)

    if archive.is_stagnant:
        logger.info("Strategy stagnation detected — shifting to architectural changes")
        return _propose_architectural_change(analysis, previously_tried)

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

        return _propose_for_error_class(ef.error_class, ef, kb_patterns)

    return _propose_architectural_change(analysis, previously_tried)


def _propose_for_error_class(
    error_class: str,
    freq: object,
    kb_patterns: str,
) -> CodeChangeHypothesis:
    """Propose a targeted fix for a specific error class."""
    strategies: dict[str, CodeChangeHypothesis] = {
        "compilation/jdk_mismatch": CodeChangeHypothesis(
            target_error_class="compilation/jdk_mismatch",
            files_to_modify=["src/buildroot/agent/builder.py"],
            expected_impact="Fix JDK version selection in Builder prompts",
            rationale="JDK mismatch is the most common compilation error. "
            "Improve Builder's JDK version inference from POM metadata.",
            priority=1,
        ),
        "dependency_resolution/missing_artifact": CodeChangeHypothesis(
            target_error_class="dependency_resolution/missing_artifact",
            files_to_modify=["src/buildroot/agent/builder.py"],
            expected_impact="Improve dependency resolution handling",
            rationale="Missing artifacts need better Maven repository configuration "
            "and dependency management in Containerfile.",
            priority=2,
        ),
        "build_tool/multi_module": CodeChangeHypothesis(
            target_error_class="build_tool/multi_module",
            files_to_modify=[
                "src/buildroot/agent/builder.py",
                "src/buildroot/agent/analyzer.py",
            ],
            expected_impact="Better multi-module Maven project handling",
            rationale="Multi-module builds need reactor-aware build ordering "
            "and parent POM installation.",
            priority=2,
        ),
        "plugin/configuration_error": CodeChangeHypothesis(
            target_error_class="plugin/configuration_error",
            files_to_modify=["src/buildroot/agent/builder.py"],
            expected_impact="Better Maven plugin error recovery",
            rationale="Plugin configuration errors can often be resolved by "
            "skipping non-essential plugins.",
            priority=3,
        ),
    }

    if error_class in strategies:
        return strategies[error_class]

    mutable = sorted(MUTABLE_SURFACES)[:3]
    return CodeChangeHypothesis(
        target_error_class=error_class,
        files_to_modify=list(mutable[:1]),
        expected_impact=f"Address {error_class} failures",
        rationale=f"Target the {error_class} error class "
        f"with count={getattr(freq, 'count', '?')}",
        priority=5,
    )


def _propose_architectural_change(
    analysis: FailureAnalysis,
    previously_tried: set[str],
) -> CodeChangeHypothesis:
    """Propose an architectural change when error-class fixes have stagnated."""
    return CodeChangeHypothesis(
        target_error_class="architectural",
        files_to_modify=[
            "src/buildroot/agent/builder.py",
            "src/buildroot/agent/analyzer.py",
        ],
        expected_impact="Architectural improvement to escape local optimum",
        rationale=(
            "Error-class fixes have stagnated. Shifting to structural changes: "
            "improve error pattern matching, add new fix strategies, or "
            "enhance the Builder's prompt template. "
            f"Previously tried: {', '.join(sorted(previously_tried)) or 'none'}"
        ),
        priority=0,
    )
