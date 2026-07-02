#!/usr/bin/env python3
"""Run the original deterministic reconstructor on a package list with full L1-L4 evaluation.

Builds run locally via podman.

Usage:
    python scripts/run_benchmark.py results/packages_benchmark.txt --output results/benchmark-full
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from buildroot.agent.evaluator import Evaluator
from buildroot.pipeline.gap_detector import GapDetector
from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("benchmark")


def run_single(coordinate: str, output_dir: Path, evaluator: Evaluator) -> dict:
    """Reconstruct + evaluate a single package. Returns a result dict."""
    group_id, artifact_id, version = parse_gav(coordinate)
    pkg_dir = output_dir / f"{artifact_id}-{version}"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "coordinate": coordinate,
        "reconstruct": None,
        "gap_report": None,
        "eval": None,
        "elapsed_seconds": 0.0,
    }
    start = time.time()

    # Stage 1: Reconstruct (deterministic pipeline)
    orchestrator = BuildrootOrchestrator(skip_deps=True)
    try:
        spec = orchestrator.reconstruct(
            group_id, artifact_id, version,
            output_dir=str(pkg_dir),
        )
        containerfile_path = pkg_dir / "Containerfile"
        if containerfile_path.exists():
            containerfile = containerfile_path.read_text()
            result["reconstruct"] = "success"
        else:
            result["reconstruct"] = "no_containerfile"
            result["elapsed_seconds"] = time.time() - start
            return result

        # Save gap report
        gap_detector = GapDetector()
        gap_report = gap_detector.format_machine_readable(spec.gaps)
        result["gap_report"] = gap_report
        (pkg_dir / "gap_report.json").write_text(json.dumps(gap_report, indent=2) + "\n")
        logger.info(
            "%s: reconstructed (confidence=%s, %d gaps)",
            coordinate, gap_report.get("overall_confidence", "?"), len(gap_report.get("entries", [])),
        )
    except Exception as e:
        logger.error("%s: reconstruction failed: %s", coordinate, e)
        result["reconstruct"] = f"error: {e}"
        result["elapsed_seconds"] = time.time() - start
        return result

    # Stage 2: Evaluate L1-L4 on remote host
    try:
        eval_result = evaluator.evaluate(containerfile, coordinate)
        eval_dict = {
            "l1_parse": eval_result.l1_parse,
            "l2_build": eval_result.l2_build,
            "l3_command": eval_result.l3_command,
            "l4_match": eval_result.l4_match,
            "reward": eval_result.reward,
            "level_reached": eval_result.level_reached,
            "error_summary": eval_result.error_summary[:500] if eval_result.error_summary else "",
            "diff_summary": eval_result.diff_summary[:500] if eval_result.diff_summary else "",
        }
        result["eval"] = eval_dict
        (pkg_dir / "eval_result.json").write_text(json.dumps(eval_dict, indent=2) + "\n")
        logger.info(
            "%s: L1=%s L2=%s L3=%s L4=%s reward=%.2f",
            coordinate,
            eval_result.l1_parse, eval_result.l2_build,
            eval_result.l3_command, eval_result.l4_match,
            eval_result.reward,
        )
    except Exception as e:
        logger.error("%s: evaluation failed: %s", coordinate, e)
        result["eval"] = f"error: {e}"

    result["elapsed_seconds"] = round(time.time() - start, 1)
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_benchmark.py <packages_file> [--output <dir>] [--host <host>]")
        sys.exit(1)

    packages_file = sys.argv[1]
    output_dir = Path("results/benchmark-full")
    host = None

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--output" and i + 1 < len(sys.argv):
            output_dir = Path(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    # Load packages
    packages = []
    with open(packages_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and ":" in line:
                packages.append(line)

    if not packages:
        logger.error("No packages found in %s", packages_file)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Benchmark: %d packages, host=%s, output=%s", len(packages), host or "local", output_dir)

    # Add file handler for the log
    fh = logging.FileHandler(str(output_dir / "benchmark.log"))
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)

    evaluator = Evaluator(host=host, timeout=1200)
    results = []
    start_time = time.time()

    for i, coordinate in enumerate(packages, 1):
        logger.info("=== Package %d/%d: %s ===", i, len(packages), coordinate)
        try:
            r = run_single(coordinate, output_dir, evaluator)
        except Exception as e:
            logger.error("%s: unexpected error: %s", coordinate, e, exc_info=True)
            r = {"coordinate": coordinate, "reconstruct": f"fatal: {e}", "eval": None, "elapsed_seconds": 0}
        results.append(r)

        # Write incremental summary after each package
        _write_summary(results, output_dir, time.time() - start_time)

    total_elapsed = time.time() - start_time
    _write_summary(results, output_dir, total_elapsed)
    _print_table(results)
    logger.info("Benchmark complete: %.0fs total", total_elapsed)


def _write_summary(results: list[dict], output_dir: Path, elapsed: float) -> None:
    total = len(results)
    reconstructed = sum(1 for r in results if r.get("reconstruct") == "success")
    l1 = sum(1 for r in results if r.get("eval", {}) and isinstance(r["eval"], dict) and r["eval"].get("l1_parse"))
    l2 = sum(1 for r in results if r.get("eval", {}) and isinstance(r["eval"], dict) and r["eval"].get("l2_build"))
    l3 = sum(1 for r in results if r.get("eval", {}) and isinstance(r["eval"], dict) and r["eval"].get("l3_command"))
    l4 = sum(1 for r in results if r.get("eval", {}) and isinstance(r["eval"], dict) and r["eval"].get("l4_match"))

    summary = {
        "total_packages": total,
        "reconstructed": reconstructed,
        "l1_parse": l1,
        "l2_build": l2,
        "l3_command": l3,
        "l4_match": l4,
        "total_elapsed_seconds": round(elapsed, 1),
        "packages": results,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def _print_table(results: list[dict]) -> None:
    print("\n" + "=" * 80)
    print(f"  {'Package':<50} {'L1':>3} {'L2':>3} {'L3':>3} {'L4':>3} {'Reward':>6}")
    print(f"  {'-'*50} {'-'*3} {'-'*3} {'-'*3} {'-'*3} {'-'*6}")
    for r in results:
        coord = r["coordinate"]
        if isinstance(r.get("eval"), dict):
            e = r["eval"]
            l1 = "Y" if e.get("l1_parse") else "N"
            l2 = "Y" if e.get("l2_build") else "N"
            l3 = "Y" if e.get("l3_command") else "N"
            l4 = "Y" if e.get("l4_match") else "N"
            reward = f"{e.get('reward', 0):.2f}"
        else:
            l1 = l2 = l3 = l4 = "-"
            reward = "-"
        print(f"  {coord:<50} {l1:>3} {l2:>3} {l3:>3} {l4:>3} {reward:>6}")
    print("=" * 80)


if __name__ == "__main__":
    main()
