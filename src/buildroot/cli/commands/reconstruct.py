"""Reconstruct command — full pipeline from Maven coordinate to Containerfile."""

import sys

import click

from buildroot.pipeline.gap_detector import GapDetector
from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav


@click.command()
@click.argument("coordinate")
@click.option("--repo-url", default=None, help="Override source repository URL.")
@click.option(
    "--ci-type",
    type=click.Choice(["github", "circleci"], case_sensitive=False),
    default=None,
    help="Hint CI system type.",
)
@click.option("--no-cache", is_flag=True, help="Skip POM cache.")
@click.option("--skip-deps", is_flag=True, help="Skip transitive dependency resolution.")
@click.option("--output-dir", default=".", help="Output directory for generated files.")
@click.option(
    "--runtime",
    type=click.Choice(["podman", "docker"], case_sensitive=False),
    default="podman",
    help="Container runtime for build steps.",
)
def reconstruct(coordinate, repo_url, ci_type, no_cache, skip_deps, output_dir, runtime):
    """Reconstruct build environment for a Maven COORDINATE (groupId:artifactId:version)."""
    try:
        group_id, artifact_id, version = parse_gav(coordinate)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="COORDINATE") from e

    orchestrator = BuildrootOrchestrator(
        no_cache=no_cache, skip_deps=skip_deps, runtime=runtime,
    )

    try:
        spec = orchestrator.reconstruct(
            group_id, artifact_id, version,
            repo_url=repo_url,
            ci_type=ci_type,
            output_dir=output_dir,
        )
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    gap_detector = GapDetector()
    click.echo(gap_detector.format_human_readable(spec.gaps), err=True)

    click.echo(f"Containerfile: {output_dir}/Containerfile")
    click.echo(f"buildroot.json: {output_dir}/buildroot.json")
