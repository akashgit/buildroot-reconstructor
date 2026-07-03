"""CLI command for regression testing against golden Containerfiles."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import click


GOLDEN_DIR_REL = "tests/regression/golden"
CANARY_PACKAGE = "commons-lang3"


def _get_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _discover_packages(golden_dir):
    """Scan golden dir for *.json metadata files, return list of (name, metadata, containerfile_path|None)."""
    packages = []
    for meta_path in sorted(golden_dir.glob("*.json")):
        name = meta_path.stem
        with open(meta_path) as f:
            metadata = json.load(f)
        cf_path = golden_dir / f"{name}.Containerfile"
        if not cf_path.exists():
            cf_path = None
        packages.append((name, metadata, cf_path))
    return packages


@click.command("regression")
@click.option("--quick", is_flag=True, help="Run only the canary package (commons-lang3)")
@click.option("--package", "pkg_name", default=None, help="Run a single package by short name")
@click.option("--host", default=None, help="SSH host for remote builds (default: run locally)")
@click.option("--report", is_flag=True, help="Write detailed results to results/regression/<timestamp>/")
@click.option("--status", "show_status", is_flag=True, help="Show suite status and baselines")
@click.option("--timeout", default=900, type=int, help="Eval timeout per package in seconds")
@click.option("--e2e", "run_e2e", is_flag=True, help="Run end-to-end pipeline test on the canary (commons-lang3)")
@click.option("--solve", is_flag=True, help="Run full agent pipeline with warm-start from golden Containerfile to close L4 gap")
@click.option("--solve-timeout", default=5400, type=int, help="Timeout per package for --solve mode in seconds (default: 90 min)")
@click.option("--max-iterations", default=15, type=int, help="Max inner loop iterations for --solve mode")
def regression_cmd(quick, pkg_name, host, report, show_status, timeout, run_e2e, solve, solve_timeout, max_iterations):
    """Run regression tests against golden Containerfiles.

    Validates that pipeline changes don't degrade evaluation scores
    below established baselines. Builds run locally via podman by default;
    pass --host to use a remote SSH host.

    \b
    Examples:
        buildroot regression --quick
        buildroot regression --package commons-lang3
        buildroot regression --status
        buildroot regression --report
        buildroot regression --e2e
        buildroot regression --solve
        buildroot regression --solve --package protobuf-java --host myserver
    """
    project_root = _get_project_root()
    golden_dir = project_root / GOLDEN_DIR_REL

    if not golden_dir.exists():
        click.echo(f"ERROR: Golden directory not found: {golden_dir}", err=True)
        sys.exit(1)

    packages = _discover_packages(golden_dir)
    if not packages:
        click.echo("ERROR: No metadata files found in golden directory", err=True)
        sys.exit(1)

    if show_status:
        _print_status(packages)
        sys.exit(0)

    if run_e2e:
        success, elapsed = _run_e2e(host, timeout)
        if not success:
            sys.exit(1)
        if not quick and not pkg_name and not report:
            sys.exit(0)

    if solve:
        if quick:
            packages = [(n, m, c) for n, m, c in packages if CANARY_PACKAGE in n]
        if pkg_name:
            packages = [(n, m, c) for n, m, c in packages if pkg_name in n]
        runnable = [(n, m, c) for n, m, c in packages if c]
        if not runnable:
            click.echo("ERROR: No packages with Containerfiles to solve", err=True)
            sys.exit(1)
        failures = _run_solve(runnable, host, solve_timeout, max_iterations, golden_dir)
        sys.exit(1 if failures > 0 else 0)

    from buildroot.agent.evaluator import Evaluator

    if quick:
        packages = [(n, m, c) for n, m, c in packages if CANARY_PACKAGE in n]
        if not packages:
            click.echo(f"ERROR: Canary package '{CANARY_PACKAGE}' not found", err=True)
            sys.exit(1)

    if pkg_name:
        packages = [(n, m, c) for n, m, c in packages if pkg_name in n]
        if not packages:
            click.echo(f"ERROR: Package '{pkg_name}' not found", err=True)
            sys.exit(1)

    runnable = [(n, m, c) for n, m, c in packages if c]
    missing = [(n, m) for n, m, c in packages if not c]

    if missing:
        click.echo("ERROR: The following packages are missing Containerfiles:", err=True)
        for name, metadata in missing:
            click.echo(f"  - {name}", err=True)
        sys.exit(1)

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    click.echo(f"REGRESSION SUITE — {ts}")
    click.echo(f"Running {len(runnable)} package(s)\n")

    evaluator = Evaluator(host=host, timeout=timeout)
    results = []
    passed = 0
    regressions = 0

    for name, metadata, cf_path in runnable:
        coordinate = metadata["coordinate"]
        baseline = metadata["baseline_reward"]
        click.echo(f"  Evaluating {name} ({coordinate})...")

        t0 = time.time()
        cf_text = cf_path.read_text()
        result = evaluator.evaluate(cf_text, coordinate)
        elapsed = time.time() - t0

        is_regression = result.reward < baseline - 0.01
        status_char = "✗" if is_regression else "✓"

        if is_regression:
            regressions += 1
        else:
            passed += 1

        click.echo(
            f"  {status_char} {name}: L4={result.l4_score:.4f} "
            f"reward={result.reward:.4f} baseline={baseline:.4f} "
            f"({elapsed:.1f}s)"
        )

        results.append({
            "name": name,
            "coordinate": coordinate,
            "baseline_reward": baseline,
            "actual_reward": round(result.reward, 4),
            "l4_score": round(result.l4_score, 4),
            "regression": is_regression,
            "elapsed_seconds": round(elapsed, 1),
        })

    total = passed + regressions
    click.echo()
    if regressions > 0:
        click.echo(f"RESULT: {passed}/{total} passed, {regressions} REGRESSION(S)")
    else:
        click.echo(f"RESULT: {passed}/{total} passed, all clear")

    if report:
        _write_report(results, ts)

    sys.exit(1 if regressions > 0 else 0)


def _run_solve(packages, host, solve_timeout, max_iterations, golden_dir):
    """Run full agent pipeline with warm-start from golden Containerfiles."""
    from buildroot.agent.models import RecipeStore
    from buildroot.agent.meta_agent import run_orchestrator

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    click.echo(f"SOLVE MODE — {ts}")
    click.echo(f"Running {len(packages)} package(s) through full v4 orchestrator\n")

    passed = 0
    failed = 0

    for name, metadata, cf_path in packages:
        coordinate = metadata["coordinate"]
        baseline_reward = metadata["baseline_reward"]
        baseline_l4 = metadata["baseline_l4_score"]
        cf_text = cf_path.read_text()

        click.echo(f"  Solving {name} ({coordinate})...")
        click.echo(f"    Baseline: reward={baseline_reward:.4f} L4={baseline_l4:.4f}")

        store = RecipeStore()
        level = (
            4 if baseline_l4 >= 0.98
            else 3 if baseline_reward >= 0.5
            else 2 if baseline_reward >= 0.15
            else 1
        )
        store.save(coordinate, level, cf_text, baseline_reward)
        click.echo(f"    Seeded RecipeStore at L{level}")

        t0 = time.time()
        try:
            result = run_orchestrator(
                coordinate,
                host=host,
                max_budget_usd=0,
                max_agent_turns=max_iterations,
                agent_timeout=solve_timeout,
            )
            elapsed = time.time() - t0

            is_pass = result.best_reward >= 0.98
            status_char = "✓" if is_pass else "✗"

            if is_pass:
                passed += 1
            else:
                failed += 1

            click.echo(
                f"    {status_char} Result: reward={result.best_reward:.4f} "
                f"L{result.best_level} status={result.status} ({elapsed:.0f}s)"
            )

            if result.best_reward > baseline_reward:
                meta_path = golden_dir / f"{name}.json"
                metadata["baseline_reward"] = round(result.best_reward, 4)
                if result.best_reward >= 0.98:
                    metadata["baseline_l4_score"] = round(result.best_reward, 4)
                meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
                click.echo(f"    Updated golden metadata: reward={result.best_reward:.4f}")

        except Exception as e:
            elapsed = time.time() - t0
            failed += 1
            click.echo(f"    ✗ Error: {e} ({elapsed:.0f}s)")

        click.echo()

    total = passed + failed
    click.echo(f"SOLVE RESULT: {passed}/{total} achieved L4>=0.98")
    if failed > 0:
        click.echo(f"  {failed} package(s) still below threshold")

    return failed


def _run_e2e(host, timeout):
    """Run end-to-end pipeline test on the canary package."""
    click.echo("E2E PIPELINE TEST — commons-lang3:3.14.0")
    click.echo("  Running full agent pipeline (v3)...")

    cmd = [
        sys.executable, "-m", "buildroot", "agent",
        "org.apache.commons:commons-lang3:3.14.0",
        "--v3-only", "--max-iterations", "5",
    ]
    if host:
        cmd.extend(["--host", host])

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - t0

        if proc.returncode == 0:
            click.echo(f"  Pipeline completed successfully ({elapsed:.0f}s)")
            return True, elapsed
        else:
            click.echo(f"  Pipeline FAILED (exit code {proc.returncode}, {elapsed:.0f}s)")
            if proc.stderr:
                click.echo(f"  Error: {proc.stderr[:500]}")
            return False, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        click.echo(f"  Pipeline TIMED OUT ({elapsed:.0f}s)")
        return False, elapsed


def _print_status(packages):
    """Print suite status showing all packages and their baselines."""
    click.echo("REGRESSION SUITE STATUS\n")
    for name, metadata, cf_path in packages:
        has_cf = cf_path is not None
        status = "READY" if has_cf else "MISSING"
        click.echo(
            f"  [{status:7s}] {name}: "
            f"baseline={metadata['baseline_reward']:.2f} "
            f"L4={metadata['baseline_l4_score']:.2f} "
            f"({metadata['build_system']}, {metadata['difficulty']})"
        )
    ready_count = sum(1 for _, _, c in packages if c)
    click.echo(f"\n{ready_count}/{len(packages)} packages ready")


def _write_report(results, ts):
    """Write detailed results to results/regression/<timestamp>/."""
    project_root = _get_project_root()
    report_dir = project_root / "results" / "regression" / ts.replace(":", "-")
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "timestamp": ts,
        "total": len(results),
        "passed": sum(1 for r in results if not r["regression"]),
        "regressions": sum(1 for r in results if r["regression"]),
        "results": results,
    }
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    for r in results:
        fname = r["name"].replace(".", "_").replace("-", "_") + ".json"
        (report_dir / fname).write_text(json.dumps(r, indent=2) + "\n")

    click.echo(f"\nReport written to {report_dir}")
