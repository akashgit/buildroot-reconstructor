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
@click.option("--node-agents", "node_agents", is_flag=True, help="Enable node-scoped Claude Code reviewer agents at each pipeline step")
@click.option("--resume", type=click.Path(exists=True), help="Resume from prior results directory (seeds RecipeStore for warm-start)")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def agent_cmd(coordinate, host, max_iterations, model, node_agents, resume, verbose):
    """Run agentic reconstruction loop for a Maven COORDINATE.

    Single package: buildroot agent org.apache.commons:commons-lang3:3.14.0
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if resume:
        from pathlib import Path
        from buildroot.agent.models import seed_recipes_from_results
        count = seed_recipes_from_results(Path(resume))
        click.echo(f"Seeded {count} recipes from {resume}")

    if not coordinate:
        raise click.UsageError("Provide a COORDINATE")

    from buildroot.agent.loop import run_inner_loop

    initial_cf = None
    if resume:
        from buildroot.agent.models import RecipeStore
        store = RecipeStore()
        best = store.best_level(coordinate)
        if best >= 2:
            initial_cf = store.get_containerfile(coordinate, best)
            if initial_cf:
                click.echo(f"Warm-starting {coordinate} from L{best} recipe")

    result = run_inner_loop(
        coordinate,
        max_iterations=max_iterations,
        host=host,
        model=model,
        node_agents=node_agents,
        initial_containerfile=initial_cf,
    )
    click.echo(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.status == "success" else 1)
