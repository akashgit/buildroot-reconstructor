"""Reconstruct command for Python packages — pre-pass to Containerfile."""

import click
from pathlib import Path


@click.command("reconstruct-python")
@click.argument("coordinate")
@click.option(
    "--output-dir", "-o", default=".", type=click.Path(), help="Output directory for Containerfile"
)
@click.option("--no-cache", is_flag=True, help="Skip PyPI cache")
def reconstruct_python(coordinate, output_dir, no_cache):
    """Reconstruct build environment for a Python COORDINATE (e.g., requests==2.31.0)."""
    from buildroot.agent.prepass_python import run_python_prepass, parse_python_coordinate
    from buildroot.generators.containerfile import ContainerfileGenerator
    from buildroot.pipeline.models_python import PyBuildrootSpec, PythonSpec

    click.echo(f"Reconstructing: {coordinate}")

    # Validate coordinate early with a user-friendly error
    try:
        pkg, ver = parse_python_coordinate(coordinate)
    except ValueError as e:
        raise click.ClickException(str(e))

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    workspace = output_path / ".workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Run prepass
    click.echo("Running pre-pass analysis...")
    findings = run_python_prepass(coordinate, workspace, no_cache=no_cache)

    if not findings.source_repo:
        raise click.ClickException(
            f"Could not discover a source repository for {coordinate}. "
            "PyPI metadata did not contain a GitHub URL."
        )

    spec = PyBuildrootSpec(
        pyproject_data=findings.pyproject_data,
        source_repo=findings.source_repo.value if findings.source_repo else "",
        git_tag=findings.git_tag.value if findings.git_tag else "",
        build_backend=findings.build_backend.value if findings.build_backend else "setuptools",
        build_command=findings.build_command.value if findings.build_command else "python -m build --sdist",
        system_packages=findings.system_packages,
    )
    spec.pyproject_data.name = pkg
    spec.pyproject_data.version = ver

    # Set python spec
    if findings.python_version:
        spec.python_spec = PythonSpec(
            version=findings.python_version.value,
            base_image=(
                findings.base_image.value
                if findings.base_image
                else f"docker.io/library/python:{findings.python_version.value}-slim"
            ),
        )

    # Generate Containerfile
    click.echo("Generating Containerfile...")
    gen = ContainerfileGenerator()
    cf_path, prov_path = gen.generate_python(spec, output_path)

    click.echo(f"Containerfile written to: {cf_path}")
    click.echo(f"Provenance written to: {prov_path}")
