"""Outer loop skeleton — runs inner loop on package list, aggregates results."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ruamel.yaml import YAML

from buildroot.agent.loop import LoopResult, run_inner_loop

logger = logging.getLogger(__name__)


def run_outer_loop(
    packages_file: str,
    *,
    host: str = "rh-h100-01",
    model: str = "claude-opus-4-6",
    max_iterations: int = 15,
    output_dir: str = "results/agent-smoke",
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
        logger.info("=== Outer loop: package %d/%d: %s ===", i, len(packages), coordinate)

        try:
            loop_result = run_inner_loop(
                coordinate,
                max_iterations=max_iterations,
                host=host,
                model=model,
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
        })

    elapsed = time.time() - start_time
    total = len(results)
    solved = sum(1 for r in results if r["best_reward"] >= 0.98)

    summary = {
        "total_packages": total,
        "solved": solved,
        "solve_rate": round(solved / total, 4) if total > 0 else 0.0,
        "total_elapsed_seconds": round(elapsed, 1),
        "packages": results,
    }

    summary_path = out / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    logger.info(
        "Outer loop complete: %d/%d solved (%.1f%%) in %.0fs",
        solved, total, summary["solve_rate"] * 100, elapsed,
    )
    return summary


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
