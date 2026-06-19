"""CLI entry point for the agentic reconstruction loop."""

from __future__ import annotations

import json
import logging
import sys

import click


@click.command("agent")
@click.argument("coordinate", required=False)
@click.option("--host", default="rh-h100-01", help="SSH host for remote builds")
@click.option("--max-iterations", default=15, type=int, help="Max inner loop iterations")
@click.option("--batch", "batch_file", type=click.Path(exists=True), help="File with one coordinate per line for batch processing")
@click.option("--output", "output_dir", type=click.Path(), help="Output directory for batch results")
@click.option("--resume", type=click.Path(exists=True), help="Resume from prior results directory (seeds RecipeStore for warm-start)")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def agent_cmd(coordinate, host, max_iterations, batch_file, output_dir, resume, verbose):
    """Run agentic reconstruction loop for a Maven COORDINATE.

    Single package: buildroot agent org.apache.commons:commons-lang3:3.14.0
    Batch: buildroot agent --batch packages.txt
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if resume:
        from pathlib import Path
        from buildroot.agent.models import seed_recipes_from_results
        count = seed_recipes_from_results(Path(resume))
        click.echo(f"Seeded {count} recipes from {resume}")

    # Batch mode
    if batch_file:
        from pathlib import Path
        coordinates = [
            line.strip() for line in Path(batch_file).read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not coordinates:
            raise click.UsageError("Batch file is empty")

        out_dir = Path(output_dir) if output_dir else Path("results/batch-v3")
        out_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for coord in coordinates:
            click.echo(f"\n{'='*60}\nProcessing: {coord}\n{'='*60}")
            r = _run_single(coord, host, max_iterations, resume)
            results.append({"coordinate": coord, **r.to_dict()})

            safe_name = coord.replace(":", "_").replace(".", "_")
            (out_dir / f"{safe_name}.json").write_text(json.dumps(r.to_dict(), indent=2) + "\n")

        summary = {
            "total": len(results),
            "success": sum(1 for r in results if r.get("status") == "success"),
            "results": results,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        click.echo(f"\nBatch complete: {summary['success']}/{summary['total']} succeeded")
        click.echo(f"Results: {out_dir}")
        sys.exit(0 if summary["success"] == summary["total"] else 1)

    if not coordinate:
        raise click.UsageError("Provide a COORDINATE or --batch FILE")

    result = _run_single(coordinate, host, max_iterations, resume)
    click.echo(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.status == "success" else 1)


def _run_single(coordinate, host, max_iterations, resume):
    """Run a single coordinate through the v3 pipeline."""
    from buildroot.agent.pipeline_v3 import run_v3_pipeline

    warm_cf = None
    if resume:
        from buildroot.agent.models import RecipeStore
        store = RecipeStore()
        best = store.best_level(coordinate)
        if best >= 2:
            warm_cf = store.get_containerfile(coordinate, best)

    return run_v3_pipeline(
        coordinate,
        max_iterations=max_iterations,
        host=host,
        warm_start_containerfile=warm_cf,
    )
