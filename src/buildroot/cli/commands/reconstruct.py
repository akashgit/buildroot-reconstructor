"""Reconstruct command — full pipeline from Maven coordinate to Containerfile."""

import click


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
    click.echo("Not yet implemented")
