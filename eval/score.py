"""Evaluation script for CVE NV-001052 remediation project."""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FACTORY_DIR = PROJECT_ROOT / ".factory"
LOG_PATH = FACTORY_DIR / "eval.log"


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("eval.score")
    logger.setLevel(logging.DEBUG)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            log_entry: dict[str, Any] = {
                "timestamp": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0] is not None:
                log_entry["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_entry)

    json_fmt = JsonFormatter()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(json_fmt)
    stderr_handler.setLevel(logging.INFO)
    logger.addHandler(stderr_handler)

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(LOG_PATH), mode="a", encoding="utf-8")
        file_handler.setFormatter(json_fmt)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("Could not create file log handler at %s", LOG_PATH)

    return logger


logger = _setup_logging()


def _load_containerfile() -> str | None:
    intake_path = FACTORY_DIR / "cve" / "intake.json"
    if not intake_path.exists():
        logger.error("intake.json not found at %s", intake_path)
        return None
    try:
        data = json.loads(intake_path.read_text(encoding="utf-8"))
        containerfile: str = data["containerfile"]
        logger.info("Loaded Containerfile from intake.json (%d chars)", len(containerfile))
        return containerfile
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse intake.json: %s", exc)
        return None


def eval_syntax_check() -> dict[str, Any]:
    """Validate Containerfile has required directives. Weight: 0.20."""
    logger.info("Running syntax_check evaluation")
    containerfile = _load_containerfile()
    if containerfile is None:
        return {
            "name": "syntax_check", "score": 0.0, "weight": 0.20,
            "passed": False, "details": "Containerfile not found",
        }

    required_directives = ["FROM", "RUN", "WORKDIR"]
    found = []
    missing = []
    for directive in required_directives:
        pattern = rf"^\s*{directive}\s"
        if re.search(pattern, containerfile, re.MULTILINE):
            found.append(directive)
        else:
            missing.append(directive)

    has_file_ops = bool(
        re.search(r"^\s*COPY\s", containerfile, re.MULTILINE)
        or re.search(r"^\s*ADD\s", containerfile, re.MULTILINE)
        or "cp " in containerfile
        or "curl " in containerfile
    )
    if has_file_ops:
        found.append("file_operations")
    else:
        missing.append("file_operations")

    has_java_targets = (
        "SessionFactoryUtils.java" in containerfile and "SpringSessionSynchronization.java" in containerfile
    )
    if has_java_targets:
        found.append("java_targets")
    else:
        missing.append("java_targets")

    has_sed = "sed -i" in containerfile
    if has_sed:
        found.append("sed_patching")
    else:
        missing.append("sed_patching")

    total_checks = len(found) + len(missing)
    score = len(found) / total_checks if total_checks > 0 else 0.0
    passed = score >= 0.8

    logger.info("syntax_check: found=%s missing=%s score=%.2f", found, missing, score)
    return {
        "name": "syntax_check",
        "score": round(score, 4),
        "weight": 0.20,
        "passed": passed,
        "details": f"Found {len(found)}/{total_checks} structural checks: {', '.join(found)}",
    }


def eval_research_grounding() -> dict[str, Any]:
    """Check research.md and fix-plan.md for quality indicators. Weight: 0.20."""
    logger.info("Running research_grounding evaluation")
    research_path = FACTORY_DIR / "cve" / "research.md"
    fix_plan_path = FACTORY_DIR / "cve" / "fix-plan.md"

    indicators_found = []
    indicators_missing = []

    quality_checks: list[tuple[str, Path, str]] = [
        ("cwe_classification", research_path, "CWE-400"),
        ("root_cause", research_path, "disconnect()"),
        ("upstream_comparison", research_path, "upstream"),
        ("exploit_mechanism", research_path, "connection pool"),
        ("affected_files", fix_plan_path, "SpringSessionSynchronization"),
        ("fix_technique", fix_plan_path, "sed"),
        ("conservativeness", fix_plan_path, "conservative"),
        ("references", research_path, "https://"),
    ]

    for name, path, keyword in quality_checks:
        if not path.exists():
            indicators_missing.append(name)
            continue
        content = path.read_text(encoding="utf-8").lower()
        if keyword.lower() in content:
            indicators_found.append(name)
        else:
            indicators_missing.append(name)

    total = len(indicators_found) + len(indicators_missing)
    score = len(indicators_found) / total if total > 0 else 0.0
    passed = score >= 0.6

    logger.info("research_grounding: found=%s missing=%s score=%.2f", indicators_found, indicators_missing, score)
    return {
        "name": "research_grounding",
        "score": round(score, 4),
        "weight": 0.20,
        "passed": passed,
        "details": f"Found {len(indicators_found)}/{total} quality indicators: {', '.join(indicators_found)}",
    }


def eval_observability() -> dict[str, Any]:
    """Scan eval/ and scripts/ for logging infrastructure. Weight: 0.15."""
    logger.info("Running observability evaluation")
    scan_dirs = [PROJECT_ROOT / "eval", PROJECT_ROOT / "scripts"]
    total_files = 0
    files_with_logging = 0
    structured_logging = False

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for py_file in scan_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            total_files += 1
            content = py_file.read_text(encoding="utf-8")
            if "import logging" in content or "from logging" in content:
                files_with_logging += 1
            if "json.dumps" in content and "logging" in content:
                structured_logging = True

    if total_files == 0:
        score = 0.0
    else:
        coverage_score = files_with_logging / total_files
        structured_bonus = 0.2 if structured_logging else 0.0
        score = min(1.0, coverage_score + structured_bonus)

    passed = score >= 0.5

    logger.info(
        "observability: files=%d with_logging=%d structured=%s score=%.2f",
        total_files,
        files_with_logging,
        structured_logging,
        score,
    )
    return {
        "name": "observability",
        "score": round(score, 4),
        "weight": 0.15,
        "passed": passed,
        "details": f"{files_with_logging}/{total_files} files have logging, structured={structured_logging}",
    }


def eval_capability_surface() -> dict[str, Any]:
    """Count executable scripts in eval/ and scripts/. Weight: 0.15."""
    logger.info("Running capability_surface evaluation")
    scan_dirs = [PROJECT_ROOT / "eval", PROJECT_ROOT / "scripts"]
    scripts_found: list[str] = []

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for py_file in scan_dir.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
                if "def " in content:
                    scripts_found.append(str(py_file.relative_to(PROJECT_ROOT)))
            except OSError:
                continue

        for sh_file in scan_dir.glob("*.sh"):
            scripts_found.append(str(sh_file.relative_to(PROJECT_ROOT)))

    target = 3
    score = min(1.0, len(scripts_found) / target)
    passed = len(scripts_found) >= target

    logger.info("capability_surface: found=%s score=%.2f", scripts_found, score)
    return {
        "name": "capability_surface",
        "score": round(score, 4),
        "weight": 0.15,
        "passed": passed,
        "details": f"Found {len(scripts_found)}/{target} target scripts: {', '.join(scripts_found)}",
    }


def eval_test_coverage() -> dict[str, Any]:
    """Check for test files and pytest configuration. Weight: 0.10."""
    logger.info("Running test_coverage evaluation")
    tests_dir = PROJECT_ROOT / "tests"
    pyproject = PROJECT_ROOT / "pyproject.toml"

    checks_found = []
    checks_missing = []

    if tests_dir.exists():
        test_files = list(tests_dir.glob("test_*.py"))
        if test_files:
            checks_found.append(f"test_files({len(test_files)})")
        else:
            checks_missing.append("test_files")
    else:
        checks_missing.append("tests_dir")

    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        if "[tool.pytest.ini_options]" in content:
            checks_found.append("pytest_config")
        else:
            checks_missing.append("pytest_config")
        if "pytest-cov" in content or "--cov" in content:
            checks_found.append("coverage_config")
        else:
            checks_missing.append("coverage_config")
    else:
        checks_missing.extend(["pytest_config", "coverage_config"])

    total = len(checks_found) + len(checks_missing)
    score = len(checks_found) / total if total > 0 else 0.0
    passed = score >= 0.6

    logger.info("test_coverage: found=%s missing=%s score=%.2f", checks_found, checks_missing, score)
    return {
        "name": "test_coverage",
        "score": round(score, 4),
        "weight": 0.10,
        "passed": passed,
        "details": f"Found {len(checks_found)}/{total} checks: {', '.join(checks_found)}",
    }


def eval_qa_compliance() -> dict[str, Any]:
    """Check archive for 5 QA sections with PASS verdicts. Weight: 0.10."""
    logger.info("Running qa_compliance evaluation")
    archive_path = FACTORY_DIR / "archive" / "cve-remediation.md"

    if not archive_path.exists():
        logger.warning("Archive not found at %s", archive_path)
        return {
            "name": "qa_compliance",
            "score": 0.0,
            "weight": 0.10,
            "passed": False,
            "details": "Archive file not found",
        }

    content = archive_path.read_text(encoding="utf-8")

    qa_sections = [
        "Health Check",
        "Scope Check",
        "Exploit Verification",
        "Conservativeness",
        "Leak Check",
    ]

    passed_sections: list[str] = []
    failed_sections: list[str] = []

    has_global_pass = "CLEAN" in content or "All 5 QA sections pass" in content

    for section in qa_sections:
        if section not in content:
            failed_sections.append(section)
            continue
        section_idx = content.index(section)
        section_context = content[section_idx:section_idx + 500]
        if "PASS" in section_context or has_global_pass:
            passed_sections.append(section)
        else:
            failed_sections.append(section)

    score = len(passed_sections) / len(qa_sections)
    passed = score >= 0.8

    logger.info("qa_compliance: passed=%s failed=%s score=%.2f", passed_sections, failed_sections, score)
    return {
        "name": "qa_compliance",
        "score": round(score, 4),
        "weight": 0.10,
        "passed": passed,
        "details": f"{len(passed_sections)}/{len(qa_sections)} QA sections passed: {', '.join(passed_sections)}",
    }


def eval_experiment_diversity() -> dict[str, Any]:
    """Check fix-plan.md for technique diversity. Weight: 0.10."""
    logger.info("Running experiment_diversity evaluation")
    fix_plan_path = FACTORY_DIR / "cve" / "fix-plan.md"

    if not fix_plan_path.exists():
        logger.warning("fix-plan.md not found at %s", fix_plan_path)
        return {
            "name": "experiment_diversity",
            "score": 0.0,
            "weight": 0.10,
            "passed": False,
            "details": "fix-plan.md not found",
        }

    content = fix_plan_path.read_text(encoding="utf-8").lower()

    categories: dict[str, list[str]] = {
        "sed_patch": ["sed"],
        "source_replacement": ["restore", "replace"],
        "alternative_approaches": ["alternative", "preferred"],
        "upstream_comparison": ["upstream"],
        "minimal_change": ["minimal", "conservative"],
    }

    found_categories: list[str] = []
    missing_categories: list[str] = []

    for category, keywords in categories.items():
        if any(kw in content for kw in keywords):
            found_categories.append(category)
        else:
            missing_categories.append(category)

    score = len(found_categories) / len(categories)
    passed = score >= 0.6

    logger.info(
        "experiment_diversity: found=%s missing=%s score=%.2f",
        found_categories,
        missing_categories,
        score,
    )
    return {
        "name": "experiment_diversity",
        "score": round(score, 4),
        "weight": 0.10,
        "passed": passed,
        "details": f"{len(found_categories)}/{len(categories)} technique categories: {', '.join(found_categories)}",
    }


def main() -> None:
    """Run all eval dimensions and output results as JSON."""
    logger.info("Starting evaluation for NV-001052")

    results = [
        eval_syntax_check(),
        eval_research_grounding(),
        eval_observability(),
        eval_capability_surface(),
        eval_test_coverage(),
        eval_qa_compliance(),
        eval_experiment_diversity(),
    ]

    total_weight = sum(r["weight"] for r in results)
    total_score = sum(r["score"] * r["weight"] for r in results) / total_weight if total_weight > 0 else 0.0

    output: dict[str, Any] = {
        "total": round(total_score, 4),
        "results": results,
    }

    logger.info("Evaluation complete: total=%.4f", total_score)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
