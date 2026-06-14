"""Outer loop orchestrator — intelligent self-improving cycle.

Replaces the dumb for-loop with: batch → analyze → research → strategize →
implement → guards → re-batch → verdict → update KB → loop.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from ruamel.yaml import YAML

from buildroot.agent.claude_runner import spawn_claude_agent
from buildroot.agent.failure_analyst import analyze_batch
from buildroot.agent.guards import check_all, check_surfaces
from buildroot.agent.knowledge.knowledge_base import (
    read_patterns,
    record_pattern,
    update_taxonomy,
)
from buildroot.agent.loop import LoopResult, run_inner_loop
from buildroot.agent.outer_researcher import research_failures
from buildroot.agent.outer_strategist import (
    CodeChangeHypothesis,
    StrategyArchive,
    StrategyScore,
    compute_j_score,
    propose_hypothesis,
)

logger = logging.getLogger(__name__)

OUTER_BUILDER_MODEL = "claude-opus-4-6"

OUTER_BUILDER_SYSTEM = """\
You are an expert Python developer optimizing a Maven build environment reconstructor.

Your task: given a hypothesis about what to change and the current source code of a target \
file, produce the COMPLETE modified file content that implements the proposed change.

Rules:
- Output ONLY the complete modified Python file content
- Do NOT include markdown code fences
- Do NOT introduce package-specific conditionals (no `if "package-name" in ...`)
- Do NOT hardcode Maven coordinates or version numbers for specific packages
- Preserve all existing functionality — only add/modify what the hypothesis requires
- Keep the code clean, well-typed, and consistent with the existing style
"""


def run_outer_loop(
    packages_file: str,
    *,
    host: str = "rh-h100-01",
    model: str = "claude-opus-4-6",
    max_iterations: int = 15,
    output_dir: str = "results/agent-smoke",
) -> dict:
    """Run the batch inner loop for each package and aggregate results (legacy API)."""
    return run_batch(
        packages_file,
        host=host,
        model=model,
        max_iterations=max_iterations,
        output_dir=output_dir,
    )


def run_batch(
    packages_file: str,
    *,
    host: str = "rh-h100-01",
    model: str = "claude-opus-4-6",
    max_iterations: int = 15,
    output_dir: str = "results/agent-smoke",
    meta_guidance: str | None = None,
) -> dict:
    """Run the inner loop for each package in the list and aggregate results."""
    packages = _load_packages(packages_file)
    if not packages:
        logger.error("No packages found in %s", packages_file)
        return {"error": "no packages"}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    yaml = YAML()

    results: list[dict] = []
    start_time = time.time()

    for i, coordinate in enumerate(packages, 1):
        logger.info("=== Batch: package %d/%d: %s ===", i, len(packages), coordinate)

        try:
            loop_result = run_inner_loop(
                coordinate,
                max_iterations=max_iterations,
                host=host,
                model=model,
                meta_guidance=meta_guidance,
            )
        except Exception as e:
            logger.error("Inner loop failed for %s: %s", coordinate, e)
            loop_result = LoopResult(
                coordinate=coordinate,
                status="error",
                best_reward=0.0,
                elapsed_seconds=0.0,
            )

        _save_package_results(out, coordinate, loop_result, yaml)

        results.append({
            "coordinate": coordinate,
            "status": loop_result.status,
            "best_reward": loop_result.best_reward,
            "iterations": loop_result.iterations,
            "elapsed_seconds": round(loop_result.elapsed_seconds, 1),
            "attempts": [a.to_dict() for a in loop_result.attempts],
            "dead_ends": [d.to_dict() for d in loop_result.dead_ends],
        })

    elapsed = time.time() - start_time
    total = len(results)
    solved = sum(1 for r in results if r["best_reward"] >= 0.98)
    solve_rate = round(solved / total, 4) if total > 0 else 0.0

    summary: dict = {
        "total_packages": total,
        "solved": solved,
        "solve_rate": solve_rate,
        "total_elapsed_seconds": round(elapsed, 1),
        "packages": results,
    }

    summary_path = out / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    logger.info(
        "Batch complete: %d/%d solved (%.1f%%) in %.0fs",
        solved, total, solve_rate * 100, elapsed,
    )
    return summary


def run_intelligent_outer_loop(
    packages_file: str,
    *,
    host: str = "rh-h100-01",
    model: str = "claude-opus-4-6",
    max_iterations: int = 15,
    output_dir: str = "results/outer-loop",
    target_solve_rate: float = 1.0,
    max_cycles: int = 5,
) -> dict:
    """Run the full intelligent outer loop cycle.

    Cycle: batch → analyze → research → strategize → implement → guards →
           re-batch → verdict → update KB → loop until target or max_cycles.
    """
    packages = _load_packages(packages_file)
    if not packages:
        logger.error("No packages found in %s", packages_file)
        return {"error": "no packages"}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    archive_path = out / "strategy_archive.json"
    archive = StrategyArchive.load(archive_path)

    cycle_results: list[dict] = []
    current_solve_rate = 0.0

    for cycle in range(1, max_cycles + 1):
        logger.info("=== Outer loop cycle %d/%d ===", cycle, max_cycles)
        cycle_dir = out / f"cycle_{cycle:03d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Run batch
        kb_patterns = read_patterns()
        batch_summary = run_batch(
            packages_file,
            host=host,
            model=model,
            max_iterations=max_iterations,
            output_dir=str(cycle_dir / "batch_before"),
            meta_guidance=kb_patterns if kb_patterns else None,
        )

        if "error" in batch_summary:
            logger.error("Batch failed in cycle %d: %s", cycle, batch_summary["error"])
            break

        current_solve_rate = batch_summary["solve_rate"]
        logger.info("Cycle %d baseline solve_rate: %.4f", cycle, current_solve_rate)

        if current_solve_rate >= target_solve_rate:
            logger.info("Target solve_rate %.4f reached!", target_solve_rate)
            cycle_results.append({
                "cycle": cycle,
                "solve_rate": current_solve_rate,
                "verdict": "target_reached",
            })
            break

        # Step 2: Analyze failures
        analysis = analyze_batch(
            batch_summary.get("packages", []),
            max_iterations=max_iterations,
        )
        analysis.save(cycle_dir / "failure_analysis.json")
        update_taxonomy(analysis)

        # Step 2.5: Research dominant failure patterns
        research_report = ""
        if analysis.failed_packages > 0:
            research_report = research_failures(
                analysis,
                kb_patterns=kb_patterns or "",
                output_path=cycle_dir / "research_report.md",
            )

        # Step 3: Strategize
        hypothesis = propose_hypothesis(
            analysis, archive, kb_patterns, research_report=research_report,
        )
        (cycle_dir / "hypothesis.json").write_text(
            json.dumps(hypothesis.to_dict(), indent=2) + "\n"
        )
        logger.info(
            "Hypothesis: target=%s, files=%s",
            hypothesis.target_error_class,
            hypothesis.files_to_modify,
        )

        # Step 4: Implement (OuterBuilder)
        changes = _outer_builder_implement(hypothesis)
        if not changes:
            logger.warning("OuterBuilder produced no changes for cycle %d", cycle)
            j_score = compute_j_score(current_solve_rate, current_solve_rate)
            archive.add(StrategyScore(
                cycle=cycle,
                solve_rate_before=current_solve_rate,
                solve_rate_after=current_solve_rate,
                j_score=j_score,
                hypothesis=hypothesis,
                verdict="no_changes",
            ))
            archive.save(archive_path)
            cycle_results.append({
                "cycle": cycle,
                "solve_rate": current_solve_rate,
                "verdict": "no_changes",
                "j_score": j_score,
            })
            continue

        # Step 5: Surface guard before applying
        changed_files = "\n".join(changes.keys())
        surface_check = check_surfaces(changed_files)
        if not surface_check:
            logger.warning("Surface guard failed: %s", surface_check.reason)
            j_score = compute_j_score(current_solve_rate, current_solve_rate)
            archive.add(StrategyScore(
                cycle=cycle,
                solve_rate_before=current_solve_rate,
                solve_rate_after=current_solve_rate,
                j_score=j_score,
                hypothesis=hypothesis,
                verdict="surface_violation",
            ))
            archive.save(archive_path)
            cycle_results.append({
                "cycle": cycle,
                "solve_rate": current_solve_rate,
                "verdict": "surface_violation",
                "j_score": j_score,
            })
            continue

        # Step 6: Apply changes and get diff
        originals = _apply_changes(changes)
        try:
            diff_output = _get_git_diff(list(changes.keys()))

            # Step 7: Re-run batch
            batch_after = run_batch(
                packages_file,
                host=host,
                model=model,
                max_iterations=max_iterations,
                output_dir=str(cycle_dir / "batch_after"),
                meta_guidance=kb_patterns if kb_patterns else None,
            )

            solve_rate_after = batch_after.get("solve_rate", 0.0)

            # Step 8: Guards check
            guard_result = check_all(
                diff_output,
                solve_rate_before=current_solve_rate,
                solve_rate_after=solve_rate_after,
                historical_best=archive.historical_best_solve_rate,
                test_coordinates=_load_packages(packages_file),
                run_tests=False,
                file_names=list(changes.keys()),
            )

            # Step 9: Verdict
            j_score = compute_j_score(current_solve_rate, solve_rate_after)

            if guard_result.passed and solve_rate_after >= current_solve_rate:
                verdict = "keep"
                logger.info(
                    "Cycle %d KEEP: %.4f → %.4f (J=%.4f)",
                    cycle, current_solve_rate, solve_rate_after, j_score,
                )
                record_pattern(
                    "General Patterns",
                    f"Cycle {cycle}: {hypothesis.target_error_class} fix improved "
                    f"solve_rate {current_solve_rate:.2f} → {solve_rate_after:.2f}",
                )
                current_solve_rate = solve_rate_after
            else:
                verdict = "revert"
                logger.info(
                    "Cycle %d REVERT: %.4f → %.4f (J=%.4f, guard=%s)",
                    cycle, current_solve_rate, solve_rate_after, j_score,
                    guard_result.reason[:100],
                )
                _revert_changes(originals)
        except Exception:
            logger.error("Cycle %d crashed after applying changes — reverting", cycle)
            _revert_changes(originals)
            raise

        archive.add(StrategyScore(
            cycle=cycle,
            solve_rate_before=current_solve_rate if verdict == "revert" else batch_summary["solve_rate"],
            solve_rate_after=solve_rate_after,
            j_score=j_score,
            hypothesis=hypothesis,
            verdict=verdict,
        ))
        archive.save(archive_path)

        cycle_results.append({
            "cycle": cycle,
            "solve_rate_before": batch_summary["solve_rate"],
            "solve_rate_after": solve_rate_after,
            "verdict": verdict,
            "j_score": j_score,
            "hypothesis": hypothesis.to_dict(),
        })

        if current_solve_rate >= target_solve_rate:
            logger.info("Target solve_rate %.4f reached!", target_solve_rate)
            break

        if archive.is_stagnant:
            logger.warning("Strategy stagnation detected after %d cycles", cycle)

    final_summary: dict = {
        "final_solve_rate": current_solve_rate,
        "total_cycles": len(cycle_results),
        "target_solve_rate": target_solve_rate,
        "cycles": cycle_results,
    }

    (out / "outer_loop_summary.json").write_text(
        json.dumps(final_summary, indent=2) + "\n"
    )
    logger.info(
        "Outer loop complete: %d cycles, final solve_rate=%.4f",
        len(cycle_results), current_solve_rate,
    )
    return final_summary


def _outer_builder_implement(
    hypothesis: CodeChangeHypothesis,
) -> dict[str, str]:
    """Use a Claude Code subprocess to implement code changes for the hypothesis.

    The agent edits files directly using the Edit tool.  We snapshot originals
    beforehand and diff afterward to capture what changed.

    Returns a dict of {file_path: new_content}.
    """
    originals: dict[str, str] = {}
    target_files_list: list[str] = []

    for file_path in hypothesis.files_to_modify:
        path = Path(file_path)
        if not path.exists():
            logger.warning("Target file does not exist: %s", file_path)
            continue
        originals[file_path] = path.read_text()
        target_files_list.append(file_path)

    if not target_files_list:
        return {}

    system_prompt = f"""\
{OUTER_BUILDER_SYSTEM}

## Target Files
{chr(10).join(f"- {f}" for f in target_files_list)}

## Hypothesis
Target error class: {hypothesis.target_error_class}
Expected impact: {hypothesis.expected_impact}
Rationale: {hypothesis.rationale}

You MUST only modify the listed target files. Use the Edit tool for surgical changes — \
do NOT rewrite entire files. Read each file first, then make the minimal edits needed \
to implement the hypothesis.
"""

    task = (
        f"Implement this code change hypothesis: {hypothesis.rationale}\n\n"
        f"Target error class: {hypothesis.target_error_class}\n"
        f"Files to modify: {', '.join(target_files_list)}\n\n"
        f"Read each target file, then use Edit to make the necessary changes."
    )

    agent_result = spawn_claude_agent(
        task=task,
        system_prompt=system_prompt,
        model=OUTER_BUILDER_MODEL,
        max_turns=30,
        max_budget_usd=5.0,
        timeout=600,
    )

    if agent_result.is_error:
        logger.error("OuterBuilder agent failed: %s", agent_result.error_message)
        for fp, orig in originals.items():
            Path(fp).write_text(orig)
        return {}

    changes: dict[str, str] = {}
    for file_path, original in originals.items():
        current = Path(file_path).read_text()
        if current != original:
            changes[file_path] = current
            Path(file_path).write_text(original)

    return changes


def _apply_changes(changes: dict[str, str]) -> dict[str, str]:
    """Apply code changes and return originals for revert."""
    originals: dict[str, str] = {}
    for file_path, new_content in changes.items():
        path = Path(file_path)
        originals[file_path] = path.read_text()
        path.write_text(new_content)
        logger.info("Applied change to %s", file_path)
    return originals


def _revert_changes(originals: dict[str, str]) -> None:
    """Revert code changes using saved originals."""
    for file_path, original_content in originals.items():
        Path(file_path).write_text(original_content)
        logger.info("Reverted %s", file_path)


def _get_git_diff(changed_files: list[str] | None = None) -> str:
    """Get the current git diff output for specific files."""
    try:
        cmd = ["git", "diff"]
        if changed_files:
            cmd.append("--")
            cmd.extend(changed_files)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout
    except Exception:
        logger.warning("git diff failed — guards will see an empty diff", exc_info=True)
        return ""


def _load_packages(packages_file: str) -> list[str]:
    path = Path(packages_file)
    if not path.exists():
        return []
    lines = path.read_text().strip().splitlines()
    packages = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            parts = line.split(",")
            for part in parts:
                part = part.strip()
                if part and ":" in part:
                    packages.append(part)
    return packages


def _save_package_results(
    output_dir: Path,
    coordinate: str,
    loop_result: LoopResult,
    yaml: YAML,
) -> None:
    safe_name = coordinate.replace(":", "_").replace(".", "_")
    pkg_dir = output_dir / safe_name
    pkg_dir.mkdir(parents=True, exist_ok=True)

    attempts_path = pkg_dir / "attempts.json"
    attempts_path.write_text(
        json.dumps(loop_result.to_dict(), indent=2) + "\n"
    )

    if loop_result.dead_ends:
        dead_ends_path = pkg_dir / "dead_ends.yaml"
        dead_end_data = [de.to_dict() for de in loop_result.dead_ends]
        with open(dead_ends_path, "w") as f:
            yaml.dump(dead_end_data, f)

    if loop_result.best_attempt and loop_result.best_attempt.containerfile:
        containerfile_path = pkg_dir / "Containerfile.best"
        containerfile_path.write_text(loop_result.best_attempt.containerfile)

    logger.info("Saved results for %s to %s", coordinate, pkg_dir)
