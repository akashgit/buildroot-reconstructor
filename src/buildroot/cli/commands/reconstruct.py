"""Reconstruct command — full pipeline from Maven coordinate to Containerfile."""


import click

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
@click.option("--skip-trusted", is_flag=True, default=False, help="Skip trusted-source variant generation.")
def reconstruct(coordinate, repo_url, ci_type, no_cache, skip_deps, output_dir, runtime, skip_trusted):
    """Reconstruct build environment for a Maven COORDINATE (groupId:artifactId:version)."""
    try:
        group_id, artifact_id, version = parse_gav(coordinate)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="COORDINATE") from e

    orchestrator = BuildrootOrchestrator(
        no_cache=no_cache, skip_deps=skip_deps, runtime=runtime,
        dual_build=not skip_trusted,
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

    if spec.gaps.entries:
        click.echo(f"Gaps detected: {len(spec.gaps.entries)}", err=True)
        for entry in spec.gaps.entries:
            click.echo(f"  [{entry.status}] {entry.field}: {entry.reason}", err=True)

    click.echo(f"Containerfile: {output_dir}/Containerfile")
    click.echo(f"buildroot.json: {output_dir}/buildroot.json")

    if not skip_trusted:
        from pathlib import Path

        out_path = Path(output_dir)
        if (out_path / "exact" / "Containerfile").exists():
            click.echo(f"Exact variant: {output_dir}/exact/")
        if (out_path / "trusted" / "Containerfile").exists():
            click.echo(f"Trusted variant: {output_dir}/trusted/")
        if (out_path / "delta_report.json").exists():
            click.echo(f"Delta report: {output_dir}/delta_report.json")
