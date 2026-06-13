"""Failure Analyst — aggregate batch failures, classify error classes, detect stagnation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from buildroot.agent.analyzer import classify_error

logger = logging.getLogger(__name__)


@dataclass
class ErrorClassFrequency:
    """Frequency count for a single error class across packages."""

    error_class: str
    count: int = 0
    packages: list[str] = field(default_factory=list)
    exhausted_count: int = 0
    under_explored_count: int = 0

    def to_dict(self) -> dict:
        return {
            "error_class": self.error_class,
            "count": self.count,
            "packages": self.packages,
            "exhausted_count": self.exhausted_count,
            "under_explored_count": self.under_explored_count,
        }


@dataclass
class FailureAnalysis:
    """Aggregated failure analysis across a batch of packages."""

    total_packages: int = 0
    failed_packages: int = 0
    solved_packages: int = 0
    solve_rate: float = 0.0
    error_frequencies: list[ErrorClassFrequency] = field(default_factory=list)
    dominant_error_class: str = ""
    is_stagnant: bool = False
    stagnation_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "total_packages": self.total_packages,
            "failed_packages": self.failed_packages,
            "solved_packages": self.solved_packages,
            "solve_rate": self.solve_rate,
            "error_frequencies": [ef.to_dict() for ef in self.error_frequencies],
            "dominant_error_class": self.dominant_error_class,
            "is_stagnant": self.is_stagnant,
            "stagnation_reason": self.stagnation_reason,
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> FailureAnalysis:
        data = json.loads(path.read_text())
        analysis = cls(
            total_packages=data["total_packages"],
            failed_packages=data["failed_packages"],
            solved_packages=data["solved_packages"],
            solve_rate=data["solve_rate"],
            dominant_error_class=data.get("dominant_error_class", ""),
            is_stagnant=data.get("is_stagnant", False),
            stagnation_reason=data.get("stagnation_reason", ""),
        )
        for ef_data in data.get("error_frequencies", []):
            analysis.error_frequencies.append(ErrorClassFrequency(
                error_class=ef_data["error_class"],
                count=ef_data["count"],
                packages=ef_data.get("packages", []),
                exhausted_count=ef_data.get("exhausted_count", 0),
                under_explored_count=ef_data.get("under_explored_count", 0),
            ))
        return analysis


def analyze_batch(batch_results: list[dict], max_iterations: int = 15) -> FailureAnalysis:
    """Analyze a batch of inner-loop results and produce a FailureAnalysis.

    Each entry in batch_results should have:
      - coordinate: str
      - status: str ("success", "budget_exhausted", "fundamental_blocker", etc.)
      - best_reward: float
      - iterations: int (optional)
      - attempts: list[dict] with error_class fields (optional)
      - dead_ends: list[dict] (optional)
    """
    analysis = FailureAnalysis(total_packages=len(batch_results))

    error_counts: dict[str, ErrorClassFrequency] = {}

    for pkg in batch_results:
        coordinate = pkg.get("coordinate", "unknown")
        best_reward = pkg.get("best_reward", 0.0)

        if best_reward >= 0.98:
            analysis.solved_packages += 1
            continue

        analysis.failed_packages += 1

        error_class = _extract_dominant_error(pkg)
        if error_class not in error_counts:
            error_counts[error_class] = ErrorClassFrequency(error_class=error_class)

        freq = error_counts[error_class]
        freq.count += 1
        freq.packages.append(coordinate)

        iterations = pkg.get("iterations", 0)
        dead_ends = pkg.get("dead_ends", [])
        exhausted_approaches = sum(
            1 for de in dead_ends if de.get("is_exhausted", False)
        )

        if iterations >= max_iterations or exhausted_approaches >= 3:
            freq.exhausted_count += 1
        else:
            freq.under_explored_count += 1

    analysis.error_frequencies = sorted(
        error_counts.values(), key=lambda ef: ef.count, reverse=True
    )

    if analysis.error_frequencies:
        analysis.dominant_error_class = analysis.error_frequencies[0].error_class

    if analysis.total_packages > 0:
        analysis.solve_rate = analysis.solved_packages / analysis.total_packages

    _check_stagnation(analysis)

    logger.info(
        "Failure analysis: %d/%d solved (%.1f%%), dominant_error=%s, stagnant=%s",
        analysis.solved_packages, analysis.total_packages,
        analysis.solve_rate * 100, analysis.dominant_error_class,
        analysis.is_stagnant,
    )

    return analysis


def _extract_dominant_error(pkg: dict) -> str:
    """Extract the most common error class from a package's attempts."""
    attempts = pkg.get("attempts", [])
    if not attempts:
        error_summary = pkg.get("error_summary", "")
        if error_summary:
            return classify_error(error_summary)
        return "unknown"

    error_classes: dict[str, int] = {}
    for attempt in attempts:
        ec = attempt.get("error_class", "")
        if ec:
            error_classes[ec] = error_classes.get(ec, 0) + 1

    if not error_classes:
        return "unknown"

    return max(error_classes, key=lambda k: error_classes[k])


def _check_stagnation(analysis: FailureAnalysis) -> None:
    """AutoScientists stagnation trigger: >=8 failures concentrated in <=3 error classes."""
    if analysis.failed_packages < 8:
        return

    top_classes = analysis.error_frequencies[:3]
    top_count = sum(ef.count for ef in top_classes)

    if top_count >= 8 and len(analysis.error_frequencies) <= 3:
        analysis.is_stagnant = True
        class_names = [ef.error_class for ef in top_classes]
        analysis.stagnation_reason = (
            f"{top_count} failures concentrated in {len(top_classes)} classes: "
            + ", ".join(class_names)
        )
