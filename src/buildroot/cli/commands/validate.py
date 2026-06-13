"""Validate command — compare reconstruction against PNC ground truth."""

import json
from pathlib import Path

import click

from buildroot.parsers.pnc_containerfile import parse_pnc_containerfile_chain
from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav
from buildroot.utils.accuracy_scorer import score_accuracy


@click.command()
@click.argument("coordinate")
@click.option(
    "--builders-image-dir",
    required=True,
    type=click.Path(exists=True),
    help="Path to PNC builders-image repository checkout.",
)
@click.option(
    "--pnc-image",
    required=True,
    help="PNC builder image name (e.g. builder-rhel-7-j8-mvn3.3.9).",
)
@click.option("--output-dir", default="results/pnc-validation", help="Output directory for results.")
@click.option("--skip-deps", is_flag=True, default=False, help="Skip transitive dependency resolution.")
def validate(coordinate, builders_image_dir, pnc_image, output_dir, skip_deps):
    """Validate buildroot reconstruction against PNC ground truth for a Maven COORDINATE."""
    try:
        group_id, artifact_id, version = parse_gav(coordinate)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="COORDINATE") from e

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    pkg_dir = out / f"{artifact_id}-{version}"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Reconstructing buildroot for {coordinate}...")
    orchestrator = BuildrootOrchestrator(skip_deps=skip_deps)
    try:
        orchestrator.reconstruct(
            group_id, artifact_id, version,
            output_dir=str(pkg_dir),
        )
    except Exception as e:
        click.echo(f"Error during reconstruction: {e}", err=True)
        raise SystemExit(1) from e

    buildroot_path = pkg_dir / "buildroot.json"
    if not buildroot_path.exists():
        click.echo(f"Error: buildroot.json not generated at {buildroot_path}", err=True)
        raise SystemExit(1)

    buildroot_json = json.loads(buildroot_path.read_text())

    click.echo(f"Parsing PNC ground truth from {pnc_image}...")
    truth = parse_pnc_containerfile_chain(builders_image_dir, pnc_image)

    click.echo("Scoring accuracy...")
    report = score_accuracy(truth, buildroot_json, coordinate=coordinate)

    result_path = pkg_dir / "accuracy.json"
    result_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    click.echo(f"Accuracy report: {result_path}")
    click.echo(f"Aggregate score: {report.aggregate_score:.4f}")

    for dim in report.dimensions:
        status = "MATCH" if dim.score >= 1.0 else ("PARTIAL" if dim.score > 0 else "MISS")
        click.echo(f"  {dim.dimension}: {status} (score={dim.score:.2f}, expected={dim.expected}, actual={dim.actual})")

    _update_summary_report(out, report)

    click.echo(json.dumps(report.to_dict(), indent=2))


def _update_summary_report(output_dir: Path, report) -> None:
    """Append to or create the aggregate report.json."""
    report_path = output_dir / "report.json"

    if report_path.exists():
        summary = json.loads(report_path.read_text())
    else:
        summary = {"packages": [], "aggregate": {}}

    existing = [
        i for i, p in enumerate(summary["packages"])
        if p.get("coordinate") == report.coordinate
    ]
    entry = report.to_dict()
    if existing:
        summary["packages"][existing[0]] = entry
    else:
        summary["packages"].append(entry)

    scores = [p["aggregate_score"] for p in summary["packages"]]
    summary["aggregate"] = {
        "total_packages": len(scores),
        "mean_accuracy": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "min_accuracy": round(min(scores), 4) if scores else 0.0,
        "max_accuracy": round(max(scores), 4) if scores else 0.0,
    }

    report_path.write_text(json.dumps(summary, indent=2) + "\n")
