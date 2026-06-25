"""CLI command for regression testing against golden Containerfiles."""

from __future__ import annotations

import json
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
@click.option("--host", default="rh-h100-01", help="SSH host for remote builds")
@click.option("--report", is_flag=True, help="Write detailed results to results/regression/<timestamp>/")
@click.option("--status", "show_status", is_flag=True, help="Show suite status — golden vs stub packages")
@click.option("--timeout", default=900, type=int, help="Eval timeout per package in seconds")
def regression_cmd(quick, pkg_name, host, report, show_status, timeout):
    """Run regression tests against golden Containerfiles.

    Validates that pipeline changes don't degrade evaluation scores
    below established baselines.

    \b
    Examples:
        buildroot regression --quick
        buildroot regression --package commons-lang3
        buildroot regression --status
        buildroot regression --report
    """
    from buildroot.agent.evaluator import Evaluator

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

    runnable = [(n, m, c) for n, m, c in packages if m.get("has_golden_containerfile") and c]
    skipped = [(n, m) for n, m, c in packages if not m.get("has_golden_containerfile") or not c]

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    click.echo(f"REGRESSION SUITE — {ts}")
    click.echo(f"Running {len(runnable)} package(s), skipping {len(skipped)} stub(s)\n")

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

    if skipped:
        click.echo(f"\nSkipped {len(skipped)} stub(s) without golden Containerfiles:")
        for name, metadata in skipped:
            click.echo(f"  - {name} ({metadata['difficulty']})")

    if report:
        _write_report(results, skipped, ts)

    sys.exit(1 if regressions > 0 else 0)


def _print_status(packages):
    """Print suite status showing golden vs stub packages."""
    click.echo("REGRESSION SUITE STATUS\n")
    for name, metadata, cf_path in packages:
        has_golden = metadata.get("has_golden_containerfile", False) and cf_path is not None
        status = "GOLDEN" if has_golden else "STUB"
        click.echo(
            f"  [{status:6s}] {name}: "
            f"baseline={metadata['baseline_reward']:.2f} "
            f"L4={metadata['baseline_l4_score']:.2f} "
            f"({metadata['build_system']}, {metadata['difficulty']})"
        )
    golden_count = sum(1 for _, m, c in packages if m.get("has_golden_containerfile") and c)
    click.echo(f"\n{golden_count}/{len(packages)} packages have golden Containerfiles")


def _write_report(results, skipped, ts):
    """Write detailed results to results/regression/<timestamp>/."""
    project_root = _get_project_root()
    report_dir = project_root / "results" / "regression" / ts.replace(":", "-")
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "timestamp": ts,
        "total": len(results),
        "passed": sum(1 for r in results if not r["regression"]),
        "regressions": sum(1 for r in results if r["regression"]),
        "skipped_stubs": len(skipped),
        "results": results,
    }
    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    for r in results:
        fname = r["name"].replace(".", "_").replace("-", "_") + ".json"
        (report_dir / fname).write_text(json.dumps(r, indent=2) + "\n")

    click.echo(f"\nReport written to {report_dir}")
