"""Build report generation — JSON and markdown output."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from buildroot.agent.models import EvalResult
from buildroot.eval.audit import AuditLog

_REPORT_VERSION = "1.0"


@dataclass
class Report:
    """Comprehensive build report with L1-L4 breakdown, tests, audit, and recipe."""

    report_version: str = _REPORT_VERSION
    coordinate: str = ""
    timestamp: str = ""
    levels: dict = field(default_factory=dict)
    tests: dict | None = None
    reward: float = 0.0
    level_reached: int = 0
    audit_log: dict | None = None
    recipe: dict = field(default_factory=dict)
    comparison_report: dict | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def to_markdown(self) -> str:
        lines: list[str] = []

        lines.append(f"# Build Report: {self.coordinate}")
        lines.append("")
        lines.append(f"**Generated:** {self.timestamp}")
        lines.append(f"**Reward:** {self.reward:.4f}")
        lines.append(f"**Level Reached:** L{self.level_reached}")
        lines.append("")

        lines.append("## Level Results")
        lines.append("")
        lines.append("| Level | Pass | Details |")
        lines.append("|-------|------|---------|")
        for key in ("l1_parse", "l2_build", "l3_command", "l4_match"):
            level = self.levels.get(key, {})
            passed = level.get("pass", False)
            icon = "PASS" if passed else "FAIL"
            details = level.get("details", "")
            lines.append(f"| {key} | {icon} | {details} |")
        lines.append("")

        if self.tests is not None:
            lines.append("## Test Results")
            lines.append("")
            if not self.tests.get("available", False):
                lines.append("No test framework detected.")
            else:
                lines.append(f"- **Framework:** {self.tests.get('framework', 'unknown')}")
                lines.append(f"- **Command:** `{self.tests.get('command', '')}`")
                lines.append(f"- **Status:** {self.tests.get('status', 'unknown')}")
                lines.append(f"- **Run:** {self.tests.get('run', 0)}")
                lines.append(f"- **Passed:** {self.tests.get('tests_passed', 0)}")
                lines.append(f"- **Failed:** {self.tests.get('failed', 0)}")
                lines.append(f"- **Skipped:** {self.tests.get('skipped', 0)}")
                lines.append(f"- **Duration:** {self.tests.get('duration_seconds', 0)}s")

                failures = self.tests.get("failures", [])
                if failures:
                    lines.append("")
                    lines.append("### Failures")
                    lines.append("")
                    for f in failures[:5]:
                        lines.append(f"```\n{f}\n```")
            lines.append("")

        if self.comparison_report is not None:
            lines.append("## Comparison Details")
            lines.append("")
            cr = self.comparison_report
            lines.append(f"- **Verdict:** {cr.get('verdict', 'N/A')}")
            structural = cr.get("structural", {})
            lines.append(f"- **Original entries:** {structural.get('original_count', 'N/A')}")
            lines.append(f"- **Rebuilt entries:** {structural.get('rebuilt_count', 'N/A')}")
            lines.append(f"- **Structural match:** {structural.get('match', 'N/A')}")

            metadata = cr.get("metadata", {})
            lines.append(f"- **Metadata match:** {metadata.get('match', 'N/A')}")
            diff_keys = metadata.get("manifest_diff_keys", [])
            if diff_keys:
                lines.append(f"- **Manifest diff keys:** {', '.join(diff_keys[:10])}")

            bytecode = cr.get("bytecode", {})
            lines.append(f"- **Bytecode match:** {bytecode.get('match', 'N/A')}")
            compared = bytecode.get("classes_compared", 0)
            identical = bytecode.get("classes_identical", 0)
            lines.append(f"- **Classes:** {identical}/{compared} identical")

            divergent = bytecode.get("classes_divergent", [])
            if divergent:
                shown = divergent[:10]
                lines.append("")
                lines.append("**Divergent classes:**")
                for cls in shown:
                    lines.append(f"- `{cls}`")
                if len(divergent) > 10:
                    lines.append(f"- ... {len(divergent) - 10} more")
            lines.append("")

        if self.audit_log is not None:
            lines.append("## Supply Chain Audit")
            lines.append("")
            al = self.audit_log
            lines.append(f"**Total assets:** {al.get('total_assets', 0)}")
            lines.append(f"**Unique sources:** {', '.join(al.get('unique_sources', []))}")
            lines.append("")
            assets = al.get("assets", [])
            if assets:
                lines.append("| Type | Name | Source | Version |")
                lines.append("|------|------|--------|---------|")
                for a in assets:
                    version = a.get("version", "") or ""
                    lines.append(f"| {a.get('type', '')} | {a.get('name', '')} | {a.get('source', '')} | {version} |")
            lines.append("")

        lines.append("## Recipe")
        lines.append("")
        recipe = self.recipe
        if recipe.get("base_image"):
            lines.append(f"**Base image:** {recipe['base_image']}")
        if recipe.get("build_command"):
            lines.append(f"**Build command:** `{recipe['build_command']}`")
        if recipe.get("extract_command"):
            lines.append(f"**Extract command:** `{recipe['extract_command']}`")
        if recipe.get("reference_jar_url"):
            lines.append(f"**Reference JAR:** {recipe['reference_jar_url']}")
        lines.append("")
        if recipe.get("containerfile"):
            lines.append("### Containerfile")
            lines.append("")
            lines.append("```dockerfile")
            lines.append(recipe["containerfile"])
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


def build_report(
    eval_result: EvalResult,
    containerfile: str,
    coordinate: str,
    audit_log: AuditLog | None = None,
) -> Report:
    """Assemble a comprehensive build report from evaluation results."""
    report = Report(
        coordinate=coordinate,
        timestamp=datetime.now(timezone.utc).isoformat(),
        reward=round(eval_result.reward, 4),
        level_reached=eval_result.level_reached,
    )

    report.levels = _build_levels(eval_result)

    if eval_result.test_result is not None:
        report.tests = eval_result.test_result.to_dict()

    if eval_result.comparison_report is not None:
        cr = eval_result.comparison_report
        report.comparison_report = cr.to_dict() if hasattr(cr, "to_dict") else None

    if audit_log is not None:
        report.audit_log = audit_log.to_dict()

    report.recipe = _build_recipe(containerfile, coordinate)

    return report


def _build_levels(result: EvalResult) -> dict:
    """Build the levels section from eval result flags."""
    levels: dict = {}

    levels["l1_parse"] = {
        "pass": result.l1_parse,
        "details": "Dockerfile parsed successfully" if result.l1_parse else (result.error_summary or "Parse failed"),
    }

    levels["l2_build"] = {
        "pass": result.l2_build,
        "details": "Image built successfully" if result.l2_build else (result.error_summary or "Build failed"),
    }

    levels["l3_command"] = {
        "pass": result.l3_command,
        "details": "JAR found in build output" if result.l3_command else (result.error_summary or "JAR not found"),
    }

    l4_details = result.comparison_verdict or ("Match" if result.l4_match else "No match")
    if result.diff_summary:
        l4_details += f" ({result.diff_summary})"
    levels["l4_match"] = {
        "pass": result.l4_match,
        "details": l4_details,
        "score": round(result.l4_score, 4),
    }

    return levels


def _build_recipe(containerfile: str, coordinate: str) -> dict:
    """Build the recipe section from the containerfile."""
    recipe: dict = {
        "containerfile": containerfile,
        "coordinate": coordinate,
    }

    base_image = None
    build_command = None
    for line in containerfile.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("FROM ") and base_image is None:
            base_image = stripped.split()[1] if len(stripped.split()) > 1 else None
        if "mvn " in stripped and "install" in stripped.lower():
            build_command = stripped.lstrip("RUN").strip()
        elif "gradlew" in stripped and "build" in stripped.lower():
            build_command = stripped.lstrip("RUN").strip()

    if base_image:
        recipe["base_image"] = base_image
    if build_command:
        recipe["build_command"] = build_command

    from buildroot.utils.maven_central import MAVEN_CENTRAL_BASE

    group_id, artifact_id, version = coordinate.split(":")
    group_path = group_id.replace(".", "/")
    recipe["reference_jar_url"] = (
        f"{MAVEN_CENTRAL_BASE}/{group_path}/{artifact_id}/{version}/"
        f"{artifact_id}-{version}.jar"
    )

    return recipe
