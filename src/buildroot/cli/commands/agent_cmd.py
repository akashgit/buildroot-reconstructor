"""CLI entry point for the agentic reconstruction loop."""

from __future__ import annotations

import json
import logging
import sys

import click


@click.command("agent")
@click.argument("coordinate", required=False)
@click.option("--host", default="rh-h100-01", help="SSH host for remote builds")
@click.option("--max-iterations", default=15, type=int, help="Max inner loop iterations")
@click.option("--model", default="claude-opus-4-6", help="LLM model for Containerfile mutation")
@click.option("--batch", type=click.Path(exists=True), help="File with package coordinates (one per line)")
@click.option("--output", default="results/agent-smoke", help="Output directory for batch results")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def agent_cmd(coordinate, host, max_iterations, model, batch, output, verbose):
    """Run agentic reconstruction loop for a Maven COORDINATE.

    Single package: buildroot agent org.apache.commons:commons-lang3:3.14.0
    Batch mode:     buildroot agent --batch packages.txt --output results/
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if batch:
        from buildroot.agent.outer_loop import run_outer_loop

        summary = run_outer_loop(
            batch,
            host=host,
            model=model,
            max_iterations=max_iterations,
            output_dir=output,
        )
        click.echo(json.dumps(summary, indent=2))
        sys.exit(0 if summary.get("solve_rate", 0) > 0 else 1)

    if not coordinate:
        raise click.UsageError("Provide a COORDINATE or --batch file")

    from buildroot.agent.loop import run_inner_loop

    result = run_inner_loop(
        coordinate,
        max_iterations=max_iterations,
        host=host,
        model=model,
    )
    click.echo(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.status == "success" else 1)
