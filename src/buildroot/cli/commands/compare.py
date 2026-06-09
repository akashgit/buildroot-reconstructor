"""Compare command — multi-layer JAR comparison pipeline."""

import json
from pathlib import Path

import click

from buildroot.pipeline.orchestrator import parse_gav
from buildroot.utils.jar_comparator import compare_jars, write_report
from buildroot.utils.maven_central import download_jar


@click.command()
@click.argument("coordinate")
@click.option(
    "--rebuilt-jar",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the rebuilt JAR file.",
)
@click.option(
    "--output-dir",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for comparison report.",
)
@click.option(
    "--original-jar",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to original JAR (downloads from Maven Central if not provided).",
)
def compare(coordinate: str, rebuilt_jar: Path, output_dir: Path, original_jar: Path | None) -> None:
    """Compare a rebuilt JAR against the original Maven Central artifact.

    COORDINATE is groupId:artifactId:version (e.g. org.apache.commons:commons-lang3:3.14.0)
    """
    try:
        group_id, artifact_id, version = parse_gav(coordinate)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="COORDINATE") from e

    if original_jar is None:
        output_dir.mkdir(parents=True, exist_ok=True)
        original_jar = output_dir / f"{artifact_id}-{version}-original.jar"
        click.echo("Downloading original JAR from Maven Central...")
        try:
            download_jar(group_id, artifact_id, version, original_jar)
        except Exception as e:
            click.echo(f"Error downloading JAR: {e}", err=True)
            raise SystemExit(1) from e

    click.echo("Comparing JARs...")
    report = compare_jars(original_jar, rebuilt_jar, coordinate=coordinate)
    report_path = write_report(report, output_dir)

    click.echo(json.dumps(report.to_dict(), indent=2))
    click.echo(f"\nVerdict: {report.verdict}")
    click.echo(f"Report written to: {report_path}")
