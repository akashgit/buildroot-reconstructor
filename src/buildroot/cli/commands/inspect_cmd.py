"""Inspect command — diagnostic view of resolved build environment."""

import json

import click

from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav


@click.command("inspect")
@click.argument("coordinate")
@click.option("--no-cache", is_flag=True, help="Skip POM cache.")
def inspect_cmd(coordinate, no_cache):
    """Inspect resolved build environment for a Maven COORDINATE (groupId:artifactId:version)."""
    try:
        group_id, artifact_id, version = parse_gav(coordinate)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="COORDINATE") from e

    orchestrator = BuildrootOrchestrator(no_cache=no_cache)

    try:
        result = orchestrator.inspect(group_id, artifact_id, version)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    click.echo(json.dumps(result, indent=2))
