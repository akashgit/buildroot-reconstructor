"""CLI command for L4 evaluation — spawns the L4-eval agent."""

from __future__ import annotations

import json
import sys

import click


@click.command("qa")
@click.argument("containerfile", type=click.Path(exists=True))
@click.argument("coordinate")
@click.option("--host", default=None, help="SSH host for remote builds")
@click.option("--timeout", default=900, type=int, help="Agent timeout in seconds")
@click.option("--pretty/--no-pretty", default=True, help="Pretty-print JSON output")
@click.option("--no-isolate-podman", is_flag=True, default=False, help="Disable podman storage isolation")
def qa_cmd(containerfile, coordinate, host, timeout, pretty, no_isolate_podman):
    """Run L4-eval agent — full evaluation with test recovery.

    Spawns a single L4-eval Claude agent that handles:
    - L1-L4 JAR comparison (via buildroot eval)
    - Unit test recovery (probe, -pl targeting, best-effort)
    - Final scoring (70% JAR + 30% tests)
    - Failure feedback with suggestions

    The orchestrator invokes this instead of buildroot eval directly.

    \b
    Examples:
        buildroot qa Containerfile org.apache.commons:commons-lang3:3.14.0
        buildroot qa my.Containerfile com.example:lib:1.0 --host myserver
    """
    from pathlib import Path
    from buildroot.qa.workflow import run_l4_eval

    cf_text = Path(containerfile).read_text()

    result = run_l4_eval(
        containerfile_path=containerfile,
        containerfile_text=cf_text,
        coordinate=coordinate,
        host=host,
        timeout=timeout,
    )

    indent = 2 if pretty else None
    json.dump(result, sys.stdout, indent=indent)
    print()

    reward = result.get("reward", 0)
    test_status = result.get("test_status", "unknown")
    tests_run = result.get("tests_run", 0)

    if reward >= 0.98:
        click.echo(f"L4 EVAL PASSED: reward={reward}, tests={tests_run} ({test_status})", err=True)
    else:
        reason = result.get("failure_reason", "unknown")
        click.echo(f"L4 EVAL: reward={reward}, tests={tests_run} ({test_status})", err=True)
        click.echo(f"  Reason: {reason}", err=True)
        suggestion = result.get("suggestion", "")
        if suggestion:
            click.echo(f"  Suggestion: {suggestion}", err=True)
        sys.exit(1)
