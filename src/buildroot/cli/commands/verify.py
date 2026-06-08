"""Verify command — check generated buildroot against published artifacts."""

import click


@click.command()
@click.argument("coordinate")
@click.option("--rebuild", is_flag=True, help="Attempt full rebuild and artifact comparison.")
@click.option(
    "--runtime",
    type=click.Choice(["podman", "docker"], case_sensitive=False),
    default="podman",
    help="Container runtime for rebuild.",
)
def verify(coordinate, rebuild, runtime):
    """Verify buildroot for a Maven COORDINATE (groupId:artifactId:version)."""
    click.echo("Not yet implemented")
