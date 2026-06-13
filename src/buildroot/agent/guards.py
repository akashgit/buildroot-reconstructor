"""Guards & Gates — real enforcement for outer loop safety."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MUTABLE_SURFACES = frozenset({
    "src/buildroot/agent/builder.py",
    "src/buildroot/agent/analyzer.py",
    "src/buildroot/agent/loop.py",
    "src/buildroot/agent/observer.py",
    "src/buildroot/agent/outer_loop.py",
    "src/buildroot/agent/models.py",
    "src/buildroot/agent/failure_analyst.py",
    "src/buildroot/agent/guards.py",
    "src/buildroot/agent/outer_strategist.py",
    "src/buildroot/agent/knowledge/knowledge_base.py",
    "src/buildroot/agent/knowledge/__init__.py",
    "src/buildroot/agent/__init__.py",
    "src/buildroot/cli/commands/agent_cmd.py",
})

MUTABLE_GLOBS = (
    "src/buildroot/agent/knowledge/",
    "src/buildroot/templates/",
    "tests/",
    "results/",
)

FIXED_SURFACES = frozenset({
    "src/buildroot/agent/evaluator.py",
    "src/buildroot/utils/jar_comparator.py",
    "eval/score.py",
    "packages_smoke.txt",
})


@dataclass
class GuardResult:
    """Result of a guard check."""

    passed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.passed


def check_surfaces(diff_output: str) -> GuardResult:
    """Check that only mutable surfaces were modified.

    Args:
        diff_output: Output from `git diff --name-only` (newline-separated file paths).
    """
    changed_files = [
        f.strip() for f in diff_output.strip().splitlines() if f.strip()
    ]

    if not changed_files:
        return GuardResult(passed=True, reason="No files changed")

    violations = []
    for f in changed_files:
        if f in FIXED_SURFACES:
            violations.append(f"FIXED surface modified: {f}")
            continue

        if f in MUTABLE_SURFACES:
            continue

        if any(f.startswith(g) for g in MUTABLE_GLOBS):
            continue

        violations.append(f"Out-of-scope file modified: {f}")

    if violations:
        return GuardResult(
            passed=False,
            reason="Surface violations:\n" + "\n".join(violations),
        )

    return GuardResult(passed=True, reason=f"{len(changed_files)} files changed, all within scope")


def run_test_gate(test_pattern: str = "tests/test_agent*.py") -> GuardResult:
    """Run pytest and ruff to verify code quality.

    Executes real subprocess calls — no stubs.
    """
    try:
        pytest_proc = subprocess.run(
            ["python", "-m", "pytest", test_pattern, "-x", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        return GuardResult(passed=False, reason="pytest not found")
    except subprocess.TimeoutExpired:
        return GuardResult(passed=False, reason="pytest timed out after 300s")

    if pytest_proc.returncode != 0:
        output = (pytest_proc.stdout + pytest_proc.stderr)[-2000:]
        return GuardResult(
            passed=False,
            reason=f"pytest failed (exit {pytest_proc.returncode}):\n{output}",
        )

    try:
        ruff_proc = subprocess.run(
            ["python", "-m", "ruff", "check", "src/"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return GuardResult(passed=False, reason="ruff not found")
    except subprocess.TimeoutExpired:
        return GuardResult(passed=False, reason="ruff timed out after 60s")

    if ruff_proc.returncode != 0:
        output = (ruff_proc.stdout + ruff_proc.stderr)[-2000:]
        return GuardResult(
            passed=False,
            reason=f"ruff check failed:\n{output}",
        )

    return GuardResult(passed=True, reason="pytest and ruff passed")


def check_monotonic(
    solve_rate_after: float,
    solve_rate_before: float,
    historical_best: float,
) -> GuardResult:
    """Reject if solve_rate regressed from before or below historical best."""
    if solve_rate_after < solve_rate_before:
        return GuardResult(
            passed=False,
            reason=(
                f"Regression: solve_rate dropped from {solve_rate_before:.4f} "
                f"to {solve_rate_after:.4f}"
            ),
        )

    if solve_rate_after < historical_best:
        return GuardResult(
            passed=False,
            reason=(
                f"Below historical best: {solve_rate_after:.4f} < {historical_best:.4f}"
            ),
        )

    return GuardResult(
        passed=True,
        reason=f"Monotonic: {solve_rate_before:.4f} → {solve_rate_after:.4f} (best: {historical_best:.4f})",
    )


def scan_leakage(
    diff_output: str,
    test_coordinates: list[str] | None = None,
) -> GuardResult:
    """Scan a diff for ground-truth leakage patterns.

    Checks for:
    - Maven coordinate strings from the test suite embedded in code
    - Hardcoded version numbers matching test packages
    - Package-specific conditional logic (if "package-name" in ...)
    """
    if not diff_output.strip():
        return GuardResult(passed=True, reason="Empty diff, no leakage possible")

    violations = []

    if test_coordinates:
        for coord in test_coordinates:
            parts = coord.split(":")
            if len(parts) >= 2:
                artifact_id = parts[1]
                group_id = parts[0]
                if re.search(
                    rf'["\'].*{re.escape(artifact_id)}.*["\']',
                    diff_output,
                ):
                    violations.append(
                        f"Test artifact name '{artifact_id}' found in diff"
                    )
                if re.search(
                    rf'["\'].*{re.escape(group_id)}.*["\']',
                    diff_output,
                ):
                    violations.append(
                        f"Test group ID '{group_id}' found in diff"
                    )

    leakage_patterns = [
        (r'if\s+["\'][\w.-]+["\']\s+in\s+', "Package-specific conditional"),
        (r'==\s*["\'][\d]+\.[\d]+\.[\d]+["\']', "Hardcoded version comparison"),
        (r'coordinate\s*==\s*["\']', "Coordinate equality check"),
    ]

    for pattern, description in leakage_patterns:
        added_lines = [
            line for line in diff_output.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        for line in added_lines:
            if re.search(pattern, line):
                violations.append(f"{description}: {line.strip()[:100]}")

    if violations:
        return GuardResult(
            passed=False,
            reason="Leakage detected:\n" + "\n".join(violations[:10]),
        )

    return GuardResult(passed=True, reason="No leakage patterns detected")


def check_all(
    diff_output: str,
    solve_rate_before: float,
    solve_rate_after: float,
    historical_best: float,
    test_coordinates: list[str] | None = None,
    run_tests: bool = True,
) -> GuardResult:
    """Run all guards and return the first failure, or pass if all succeed."""
    surface = check_surfaces(diff_output)
    if not surface:
        return surface

    leakage = scan_leakage(diff_output, test_coordinates)
    if not leakage:
        return leakage

    monotonic = check_monotonic(solve_rate_after, solve_rate_before, historical_best)
    if not monotonic:
        return monotonic

    if run_tests:
        test_gate = run_test_gate()
        if not test_gate:
            return test_gate

    return GuardResult(passed=True, reason="All guards passed")
