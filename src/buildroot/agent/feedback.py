"""Structured feedback builder for the v3 pipeline Analysis Agent."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from buildroot.agent.models import EvalResult, FailedApproach

logger = logging.getLogger(__name__)


def build_feedback_context(
    *,
    current_values: dict,
    best_values: dict,
    eval_result: EvalResult,
    comparison_report: Any | None,
    score_history: list[dict],
    failed_approaches: list[FailedApproach],
    containerfile: str,
    workspace: Path,
    iteration: int,
    max_iterations: int = 10,
    prepass_findings: Any | None = None,
) -> str:
    """Build structured feedback for the Analysis Agent.

    Provides a concise summary in the prompt plus file paths
    with explicit Read instructions for full artifacts.
    """
    sections: list[str] = []

    if prepass_findings is not None and hasattr(prepass_findings, "to_prompt"):
        sections.append(prepass_findings.to_prompt())
        sections.append("")

    reward = eval_result.reward
    level = eval_result.level_reached
    best_reward = max((h.get("reward", 0) for h in score_history), default=0)
    delta = reward - best_reward if best_reward > 0 else 0.0

    # Score section
    sections.append(f"## Iteration {iteration}/{max_iterations} — Feedback\n")
    sections.append("### Score")
    sections.append(
        f"Level: L{level} | Reward: {reward:.4f} | "
        f"Delta: {delta:+.4f} from best ({best_reward:.4f})"
    )

    if eval_result.cf_validation_passed is False or eval_result.build_log_check_passed is False:
        sections.append("\n### Anti-Cheat Violation Detected\n")
        sections.append(
            "Your Containerfile was rejected because it violates source-only build requirements:"
        )
        if eval_result.cf_violations:
            for v in eval_result.cf_violations:
                sections.append(f"- {v}")
        if eval_result.build_log_check_passed is False:
            sections.append(f"- Build log check failed: target artifact JAR was downloaded during build")
        sections.append(
            "\nL4: FAIL — This violates build provenance rules. "
            "Do not attempt to circumvent source-only build requirements. "
            "Re-read your Sacred Rules on source-only builds and rewrite the "
            "Containerfile to compile from source.\n"
            "\nThe ONLY acceptable pattern: git clone <repo> → mvn/gradle/ant build → output JAR"
        )

    if reward < best_reward and best_reward > 0:
        sections.append(
            "**REGRESSION**: Your last attempt scored lower than the best. "
            "Values have been reverted to the best known configuration. "
            "Try a DIFFERENT approach — do not repeat what you just tried."
        )

    # Template-value diff
    if score_history and len(score_history) >= 2:
        diff_text = compute_template_value_diff(best_values, current_values)
        if diff_text:
            sections.append("\n### What Changed")
            sections.append(diff_text)

    # Build result
    sections.append("\n### Build Result")
    if level <= 2 and eval_result.error_summary:
        sections.append(f"**Build Error (L{level}):**")
        sections.append(f"```\n{eval_result.error_summary[:1500]}\n```")
    elif level >= 3:
        if eval_result.comparison_verdict:
            sections.append(f"Comparison verdict: {eval_result.comparison_verdict}")
        if eval_result.diff_summary:
            sections.append(f"Diff summary: {eval_result.diff_summary}")
        if comparison_report is not None and hasattr(comparison_report, 'to_dict'):
            report_dict = comparison_report.to_dict()
            structural = report_dict.get('structural', {})
            if structural.get('missing_entries'):
                sections.append(f'Missing entries in rebuilt JAR: {structural["missing_entries"]}')
            if structural.get('extra_entries'):
                sections.append(f'Extra entries in rebuilt JAR: {structural["extra_entries"]}')
            if structural.get('size_mismatches'):
                sections.append(f'Size mismatches: {structural["size_mismatches"][:10]}')
            if structural.get('crc_mismatches'):
                sections.append(f'CRC mismatches: {structural["crc_mismatches"][:10]}')
            bytecode = report_dict.get('bytecode', {})
            if bytecode.get('classes_compared', 0) > 0:
                sections.append(f'Bytecode: {bytecode.get("classes_identical", 0)}/{bytecode.get("classes_compared", 0)} classes identical')
            if bytecode.get('classes_divergent'):
                sections.append(f'Divergent classes: {bytecode["classes_divergent"][:15]}')
            metadata = report_dict.get('metadata', {})
            if metadata.get('manifest_diff_keys'):
                sections.append(f'Manifest diff keys: {metadata["manifest_diff_keys"]}')
            if metadata.get('resource_mismatches'):
                sections.append(f'Resource mismatches: {metadata["resource_mismatches"][:10]}')
            equiv = comparison_report.equivalence_score()
            sections.append(f'\nEquivalence score breakdown: {equiv:.4f}')
            if bytecode.get('classes_compared', 0) > 0:
                br = bytecode['classes_identical'] / bytecode['classes_compared']
                sections.append(f'  bytecode_ratio: {br:.4f} (weight: 0.70)')
            total_res = metadata.get('resource_matches', 0) + len(metadata.get('resource_mismatches', []))
            if total_res > 0:
                rr = metadata['resource_matches'] / total_res
                sections.append(f'  resource_ratio: {rr:.4f} (weight: 0.15)')
            sections.append('  entry_set completeness: (weight: 0.15)')

    # Build log path
    build_log_path = workspace / f"build_iter{iteration}.log"
    if build_log_path.exists():
        sections.append(
            f"\nFull build log: `{build_log_path}`\n"
            f"**Read this file** to find the root cause of any failures."
        )

    # Comparison report path (if exists)
    comp_path = workspace / f"comparison_iter{iteration}.json"
    if comparison_report is not None:
        try:
            comp_path.write_text(json.dumps(
                comparison_report.to_dict() if hasattr(comparison_report, 'to_dict') else str(comparison_report),
                indent=2
            ))
            sections.append(
                f"\nFull comparison report: `{comp_path}`\n"
                f"**Read this file** to see exact divergences."
            )
        except Exception:
            pass

    # Unpacked JARs at L4
    if level >= 4 or (level >= 3 and eval_result.l4_score > 0):
        original_dir = workspace / "prepass" / "original_jar"
        rebuilt_dir = workspace / f"rebuilt_jar_iter{iteration}"
        if original_dir.exists():
            sections.append(
                f"\n### JAR Comparison\n"
                f"Original JAR unpacked: `{original_dir}/`\n"
                f"Rebuilt JAR unpacked: `{rebuilt_dir}/` (if available)\n"
                f"Use `diff -r` or `javap -v` to investigate divergences."
            )

    # Rendered Containerfile
    sections.append("\n### Rendered Containerfile")
    sections.append(f"```\n{containerfile}\n```")

    # Failed approaches
    if failed_approaches:
        sections.append("\n### Failed Approaches (do NOT retry these)")
        for fa in failed_approaches[-15:]:
            sections.append(
                f"- **{fa.what_changed}**: `{fa.from_value}` → `{fa.to_value}` "
                f"| {fa.result} | {fa.why_it_failed} (iter {fa.iteration})"
            )

    # Score history
    if score_history:
        sections.append("\n### Score History")
        sections.append("| Iter | Reward | Level | Delta |")
        sections.append("|------|--------|-------|-------|")
        for entry in score_history:
            sections.append(
                f"| {entry.get('iteration', '?')} | "
                f"{entry.get('reward', 0):.4f} | "
                f"L{entry.get('level', 0)} | "
                f"{entry.get('delta', 0):+.4f} |"
            )

    # Diagnosis guide
    sections.append("\n### Diagnosis Guide")
    if level == 0:
        sections.append(
            "The Containerfile failed to parse. Check for syntax errors, "
            "missing FROM instruction, or invalid directives."
        )
    elif level == 1:
        sections.append(
            "The Containerfile parsed but the container failed to build. "
            "Read the build log for dependency resolution errors, missing packages, "
            "or incorrect base image."
        )
    elif level == 2:
        sections.append(
            "The container built but the build command failed (no JAR produced). "
            "Read the build log for compilation errors, plugin failures, or "
            "wrong build system/command."
        )
    elif level == 3:
        sections.append(
            "A JAR was produced but doesn't match the original. "
            "Focus on: JDK version mismatch (check bytecode), "
            "metadata normalization (SOURCE_DATE_EPOCH, timestamps), "
            "and build flag differences."
        )
    elif level >= 4:
        sections.append(
            "Near-match achieved. Fine-tune JDK minor version, "
            "metadata stripping patterns, and reproducibility env vars."
        )

    return "\n".join(sections)


def compute_template_value_diff(prev_values: dict, current_values: dict) -> str:
    """Compute a human-readable diff between two template value dicts."""
    if not prev_values or not current_values:
        return ""

    changes: list[str] = []
    all_keys = sorted(set(list(prev_values.keys()) + list(current_values.keys())))

    for key in all_keys:
        if key == "confidence_notes":
            continue
        old = prev_values.get(key)
        new = current_values.get(key)
        if old != new:
            old_str = _format_value(old)
            new_str = _format_value(new)
            changes.append(f"- **{key}**: `{old_str}` → `{new_str}`")

    if not changes:
        return "No changes from previous iteration."
    return "\n".join(changes)


def hash_template_values(values: dict) -> str:
    """Hash template values for stagnation/oscillation detection.

    Excludes confidence_notes since they don't affect the build.
    """
    serializable = {k: v for k, v in sorted(values.items()) if k != "confidence_notes"}
    return hashlib.sha256(
        json.dumps(serializable, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _format_value(v: Any) -> str:
    """Format a template value for display."""
    if v is None:
        return "null"
    if isinstance(v, list):
        if not v:
            return "[]"
        return json.dumps(v, default=str)
    if isinstance(v, dict):
        if not v:
            return "{}"
        return json.dumps(v, default=str)
    return str(v)
