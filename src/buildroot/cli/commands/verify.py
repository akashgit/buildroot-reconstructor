"""Verify command — check generated buildroot against published artifacts."""

import json

import click

from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav


@click.command()
@click.argument("coordinate")
@click.option("--rebuild", is_flag=True, help="Attempt full rebuild and artifact comparison.")
@click.option(
    "--runtime",
    type=click.Choice(["podman", "docker"], case_sensitive=False),
    default="podman",
    help="Container runtime for rebuild.",
)
@click.option("--output-dir", default=".", help="Directory containing generated buildroot files.")
def verify(coordinate, rebuild, runtime, output_dir):
    """Verify buildroot for a Maven COORDINATE (groupId:artifactId:version)."""
    try:
        group_id, artifact_id, version = parse_gav(coordinate)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="COORDINATE") from e

    orchestrator = BuildrootOrchestrator(runtime=runtime)

    try:
        result = orchestrator.verify(
            group_id, artifact_id, version,
            rebuild=rebuild,
            output_dir=output_dir,
        )
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    click.echo(json.dumps(result, indent=2))
