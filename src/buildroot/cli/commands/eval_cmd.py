"""CLI command for standalone Containerfile evaluation."""

from __future__ import annotations

import json
import sys

import click


@click.command("eval")
@click.argument("containerfile", type=click.Path(exists=True))
@click.argument("coordinate")
@click.option("--host", default="rh-h100-01", help="SSH host for remote builds")
@click.option("--timeout", default=900, type=int, help="Build timeout in seconds")
@click.option("--pretty/--no-pretty", default=True, help="Pretty-print JSON output")
def eval_cmd(containerfile, coordinate, host, timeout, pretty):
    """Evaluate a Containerfile against a Maven Central artifact.

    Returns JSON with L1-L4 scores, comparison report, and reward.

    \b
    Examples:
        buildroot eval Containerfile org.apache.commons:commons-lang3:3.14.0
        buildroot eval my.Containerfile com.fasterxml.jackson.core:jackson-core:2.16.1 --host rh-h100-01
    """
    from pathlib import Path

    from buildroot.agent.evaluator import Evaluator

    cf_text = Path(containerfile).read_text()
    evaluator = Evaluator(host=host, timeout=timeout)
    result = evaluator.evaluate(cf_text, coordinate)

    output = {
        "l1_parse": result.l1_parse,
        "l2_build": result.l2_build,
        "l3_command": result.l3_command,
        "l4_match": result.l4_match,
        "l4_score": round(result.l4_score, 4),
        "reward": round(result.reward, 4),
        "level_reached": result.level_reached,
        "comparison_verdict": result.comparison_verdict,
        "error_summary": result.error_summary or None,
        "diff_summary": result.diff_summary if hasattr(result, "diff_summary") else None,
    }

    if result.comparison_report:
        report = result.comparison_report
        output["comparison_report"] = {
            "verdict": report.verdict,
            "equivalence_score": round(report.equivalence_score(), 4),
            "structural_match": report.structural.match,
            "metadata_match": report.metadata.match,
            "bytecode_match": report.bytecode.match,
        }

    indent = 2 if pretty else None
    click.echo(json.dumps(output, indent=indent))
    sys.exit(0 if result.reward >= 0.98 else 1)
