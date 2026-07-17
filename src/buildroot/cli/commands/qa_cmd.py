"""CLI command for QA workflow — test recovery + verification agents."""

from __future__ import annotations

import json
import sys

import click


@click.command("qa")
@click.argument("containerfile", type=click.Path(exists=True))
@click.argument("coordinate")
@click.option("--host", default=None, help="SSH host for remote builds")
@click.option("--timeout", default=600, type=int, help="Agent timeout in seconds")
@click.option("--pretty/--no-pretty", default=True, help="Pretty-print JSON output")
def qa_cmd(containerfile, coordinate, host, timeout, pretty):
    """Run QA agents (test recovery + verification) against a built container.

    Spawns two Claude agents in sequence:
    1. Test recovery agent — finds, recovers, and runs unit tests
    2. Verification agent — runs programmatic JAR checks

    \b
    Examples:
        buildroot qa Containerfile org.apache.commons:commons-lang3:3.14.0
        buildroot qa my.Containerfile com.example:lib:1.0 --host myserver
    """
    from pathlib import Path

    cf_text = Path(containerfile).read_text()

    # Build the container image first
    import subprocess
    import uuid

    tag = f"buildroot-qa-{uuid.uuid4().hex[:8]}"
    click.echo(f"Building container image {tag}...", err=True)

    build_result = subprocess.run(
        ["podman", "build", "--pull=missing", "-t", tag, "-f", containerfile, "."],
        capture_output=True, text=True, timeout=900,
    )
    if build_result.returncode != 0:
        click.echo(f"Container build failed:\n{build_result.stderr[-500:]}", err=True)
        sys.exit(1)

    # Run test recovery agent
    click.echo("Running test recovery agent...", err=True)
    from buildroot.qa.workflow import run_test_recovery, run_verification

    test_result = run_test_recovery(
        tag, cf_text, coordinate,
        host=host, timeout=timeout,
    )

    # Run verification agent
    click.echo("Running verification agent...", err=True)
    verification = run_verification(
        tag, cf_text, coordinate,
        host=host, timeout=timeout,
    )

    # Clean up
    subprocess.run(["podman", "rmi", "-f", tag], capture_output=True, timeout=30)

    # Output results
    output = {
        "coordinate": coordinate,
        "test_result": test_result.to_dict(),
        "verification": verification,
    }

    indent = 2 if pretty else None
    json.dump(output, sys.stdout, indent=indent)
    print()

    # Exit code based on test status
    if test_result.status == "passed":
        click.echo(f"QA PASSED: {test_result.run} tests passed", err=True)
    elif test_result.status == "no_tests":
        click.echo("QA: no test sources found", err=True)
    else:
        click.echo(f"QA FAILED: status={test_result.status}, "
                    f"run={test_result.run}, failed={test_result.failed}", err=True)
        sys.exit(1)
