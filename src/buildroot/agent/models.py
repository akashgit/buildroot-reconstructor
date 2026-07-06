"""Data models for the agentic reconstruction loop."""

from __future__ import annotations

import json
import logging
import uuid
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Result from running a project's built-in test suite."""

    available: bool = False
    framework: str = ""
    command: str = ""
    passed: bool = False
    run: int = 0
    tests_passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    failures: list[str] = field(default_factory=list)
    status: str = ""

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "framework": self.framework,
            "command": self.command,
            "passed": self.passed,
            "run": self.run,
            "tests_passed": self.tests_passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "failures": self.failures,
            "status": self.status,
        }


@dataclass
class BuildAttempt:
    """A single iteration's build attempt and its evaluation result."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_id: str | None = None
    containerfile: str = ""
    reward: float = 0.0
    level_reached: int = 0
    error_class: str = ""
    build_log_summary: str = ""
    diff_summary: str = ""
    fix_applied: str = ""
    q_value: float = 0.0
    n_expansions: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "reward": self.reward,
            "level_reached": self.level_reached,
            "error_class": self.error_class,
            "build_log_summary": self.build_log_summary,
            "diff_summary": self.diff_summary,
            "fix_applied": self.fix_applied,
            "timestamp": self.timestamp,
        }


@dataclass
class FailedApproach:
    """A specific template-value change that was tried and failed."""

    what_changed: str
    from_value: str
    to_value: str
    result: str
    why_it_failed: str
    iteration: int = 0

    def to_dict(self) -> dict:
        return {
            "what_changed": self.what_changed,
            "from_value": self.from_value,
            "to_value": self.to_value,
            "result": self.result,
            "why_it_failed": self.why_it_failed,
            "iteration": self.iteration,
        }


@dataclass
class DeadEndEntry:
    """An approach that has been tried and failed enough times to be marked exhausted."""

    error_class: str
    approach: str
    failure_count: int = 0
    threshold: int = 2
    examples: list[str] = field(default_factory=list)

    @property
    def is_exhausted(self) -> bool:
        return self.failure_count >= self.threshold

    def record_failure(self, log_summary: str) -> None:
        self.failure_count += 1
        if len(self.examples) < 3:
            self.examples.append(log_summary[:200])

    def to_dict(self) -> dict:
        return {
            "error_class": self.error_class,
            "approach": self.approach,
            "failure_count": self.failure_count,
            "threshold": self.threshold,
            "is_exhausted": self.is_exhausted,
            "examples": self.examples,
        }


@dataclass
class EvalResult:
    """Result from the 4-level evaluation pipeline."""

    l1_parse: bool = False
    l2_build: bool = False
    l3_command: bool = False
    l4_match: bool = False
    l4_score: float = 0.0
    reward: float = 0.0
    build_log: str = ""
    error_summary: str = ""
    comparison_verdict: str = ""
    diff_summary: str = ""
    comparison_report: Any | None = None
    level_reached: int = 0
    trust_check: bool = False
    trust_violations: list[str] = field(default_factory=list)
    test_result: TestResult | None = None
    bytecode_version_match: bool | None = None
    manifest_sanity: bool | None = None
    unit_tests_pass: bool | None = None
    structural_match: float | None = None
    api_surface_match: float | None = None
    dependency_graph_match: float | None = None
    resource_completeness: float | None = None
    l4_signal_source: str = ""
    cf_validation_passed: bool | None = None
    cf_violations: list[str] = field(default_factory=list)
    build_log_check_passed: bool | None = None
    rebuilt_jar_bytes: bytes | None = None

    def compute_reward(self) -> float:
        if self.l4_match:
            self.l4_score = 1.0
        self.reward = (
            0.05 * float(self.l1_parse)
            + 0.10 * float(self.l2_build)
            + 0.35 * float(self.l3_command)
            + self.l4_score * 0.50
        )
        l4_passed = self.l4_match or (
            self.l4_signal_source == "fallback_signals" and self.l4_score >= 0.98
        )
        self.level_reached = (
            4 if l4_passed
            else 3 if self.l3_command
            else 2 if self.l2_build
            else 1 if self.l1_parse
            else 0
        )
        return self.reward

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "l1_parse": self.l1_parse,
            "l2_build": self.l2_build,
            "l3_command": self.l3_command,
            "l4_match": self.l4_match,
            "l4_score": round(self.l4_score, 4),
            "reward": self.reward,
            "level_reached": self.level_reached,
            "error_summary": self.error_summary,
            "comparison_verdict": self.comparison_verdict,
        }
        if self.trust_check or self.trust_violations:
            d["trust_check"] = self.trust_check
            d["trust_violations"] = self.trust_violations
        if self.test_result is not None:
            d["test_result"] = self.test_result.to_dict()
        if self.trust_violations:
            d["trust_violations"] = self.trust_violations
        if self.cf_validation_passed is not None:
            d["cf_validation_passed"] = self.cf_validation_passed
        if self.cf_violations:
            d["cf_violations"] = self.cf_violations
        if self.build_log_check_passed is not None:
            d["build_log_check_passed"] = self.build_log_check_passed
        if self.l4_signal_source:
            d["l4_signal_source"] = self.l4_signal_source
        if self.l4_signal_source == "fallback_signals":
            d["fallback_signals"] = {
                "bytecode_version_match": self.bytecode_version_match,
                "manifest_sanity": self.manifest_sanity,
                "unit_tests_pass": self.unit_tests_pass,
                "structural_match": self.structural_match,
                "api_surface_match": self.api_surface_match,
                "dependency_graph_match": self.dependency_graph_match,
                "resource_completeness": self.resource_completeness,
            }
        if self.l4_signal_source == "self_built_reference" and self.comparison_report is not None:
            d["comparison_report"] = (
                self.comparison_report.to_dict()
                if hasattr(self.comparison_report, "to_dict")
                else self.comparison_report
            )
        return d


RECIPE_DIR = Path(".factory/recipes")


class RecipeStore:
    """Tiered recipe store — saves recipes at each successful level."""

    def __init__(self, recipe_dir: Path | None = None) -> None:
        self._dir = recipe_dir or RECIPE_DIR

    def _coordinate_path(self, coordinate: str) -> Path:
        safe = coordinate.replace(":", "_").replace(".", "_").replace("/", "_")
        return self._dir / f"{safe}.json"

    def load(self, coordinate: str) -> dict | None:
        path = self._coordinate_path(coordinate)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def save(
        self,
        coordinate: str,
        level: int,
        containerfile: str,
        reward: float,
    ) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._coordinate_path(coordinate)

        existing = self.load(coordinate) or {"coordinate": coordinate, "levels": {}}
        level_key = f"l{level}"

        if level_key not in existing["levels"] or existing["levels"][level_key].get("reward", 0) < reward:
            existing["levels"][level_key] = {
                "containerfile": containerfile,
                "reward": reward,
                "timestamp": time.time(),
            }
            path.write_text(json.dumps(existing, indent=2) + "\n")
            logger.info("Recipe saved for %s at L%d (reward=%.2f)", coordinate, level, reward)

    def best_level(self, coordinate: str) -> int:
        recipe = self.load(coordinate)
        if not recipe:
            return 0
        levels = recipe.get("levels", {})
        best = 0
        for key, data in levels.items():
            try:
                lvl = int(key[1:])
                if lvl > best and data.get("reward", 0) > 0.05:
                    best = lvl
            except (ValueError, IndexError):
                pass
        return best

    def get_containerfile(self, coordinate: str, level: int) -> str | None:
        recipe = self.load(coordinate)
        if not recipe:
            return None
        level_data = recipe.get("levels", {}).get(f"l{level}")
        if level_data:
            return level_data.get("containerfile")
        return None

    def get_group_hints(self, coordinate: str) -> list[dict]:
        """Query solved recipes for same-group artifacts (cross-package transfer)."""
        group_id = coordinate.split(":")[0]
        hints: list[dict] = []
        if not self._dir.exists():
            return hints
        for recipe_file in self._dir.glob("*.json"):
            try:
                recipe = json.loads(recipe_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            recipe_coord = recipe.get("coordinate", "")
            if recipe_coord == coordinate:
                continue
            if recipe_coord.startswith(group_id + ":"):
                levels = recipe.get("levels", {})
                best_level_key = max(
                    (k for k in levels if k.startswith("l") and k[1:].isdigit()),
                    key=lambda k: int(k[1:]),
                    default=None,
                )
                if best_level_key:
                    level_data = levels[best_level_key]
                    hints.append({
                        "coordinate": recipe_coord,
                        "template_id": None,
                        "build_system": None,
                        "containerfile": level_data.get("containerfile", ""),
                        "reward": level_data.get("reward", 0),
                    })
        return hints


def seed_recipes_from_results(results_dir: Path) -> int:
    """Populate RecipeStore from saved benchmark results for warm-start."""
    recipe_store = RecipeStore()
    count = 0
    for pkg_dir in sorted(results_dir.iterdir()):
        if not pkg_dir.is_dir():
            continue
        cf_best = pkg_dir / "Containerfile.best"
        attempts = pkg_dir / "attempts.json"
        if cf_best.exists() and attempts.exists():
            try:
                data = json.loads(attempts.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            coordinate = data.get("coordinate", "")
            best_reward = data.get("best_reward", 0)
            level = (
                4 if best_reward >= 0.98
                else 3 if best_reward >= 0.5
                else 2 if best_reward >= 0.15
                else 1
            )
            if coordinate and level >= 2:
                recipe_store.save(coordinate, level, cf_best.read_text(), best_reward)
                count += 1
                logger.info("Seeded recipe: %s at L%d (reward=%.2f)", coordinate, level, best_reward)
    return count
