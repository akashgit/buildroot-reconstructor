"""Inspect command — diagnostic view of resolved build environment."""

import click


@click.command("inspect")
@click.argument("coordinate")
def inspect_cmd(coordinate):
    """Inspect resolved build environment for a Maven COORDINATE (groupId:artifactId:version)."""
    click.echo("Not yet implemented")
