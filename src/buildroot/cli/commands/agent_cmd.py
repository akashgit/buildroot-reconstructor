"""CLI entry point for the agentic reconstruction loop."""

from __future__ import annotations

import json
import logging
import sys

import click


@click.command("agent")
@click.argument("coordinate", required=False)
@click.option("--host", default=None, help="SSH host for remote builds (default: run locally)")
@click.option("--max-iterations", default=1, type=int, help="Max inner loop iterations (default: 1)")
@click.option("--batch", "batch_file", type=click.Path(exists=True), help="File with one coordinate per line for batch processing")
@click.option("--output", "-o", "output_dir", type=click.Path(), help="Output directory for results")
@click.option("--resume", type=click.Path(exists=True), help="Resume from prior results directory (seeds RecipeStore for warm-start)")
@click.option("--v3-only", is_flag=True, help="Use v3 template pipeline only (no orchestrator)")
@click.option("--interactive", is_flag=True, help="Launch interactive Claude session with orchestrator context")
@click.option("--max-budget", default=0, type=float, help="Max budget in USD (0 = unlimited)")
@click.option("--max-turns", default=0, type=int, help="Max agent turns (0 = unlimited)")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("--enable-google-mirror", is_flag=True, hidden=True, help="Deprecated: Google mirror is now the default.")
@click.option("--no-isolate-podman", is_flag=True, default=False, help="Disable podman storage isolation (not recommended for parallel runs)")
@click.option("--force", is_flag=True, help="Rebuild even if a successful build exists in the DB")
def agent_cmd(coordinate, host, max_iterations, batch_file, output_dir, resume, v3_only, interactive, max_budget, max_turns, verbose, enable_google_mirror, no_isolate_podman, force):
    """Run agentic reconstruction loop for a Maven COORDINATE.

    Default mode uses the v4 orchestrator agent. Use --v3-only for the template pipeline.
    Builds run locally via podman by default; pass --host to use a remote SSH host.

    \b
    Single package (orchestrator): buildroot agent org.apache.commons:commons-lang3:3.14.0
    Single package (v3 only):      buildroot agent org.apache.commons:commons-lang3:3.14.0 --v3-only
    Batch (v3 only):               buildroot agent --batch packages.txt --v3-only
    """
    if enable_google_mirror:
        click.echo("Warning: --enable-google-mirror is deprecated (Google mirror is now the default)", err=True)

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if interactive and v3_only:
        raise click.UsageError("--interactive cannot be combined with --v3-only")
    if interactive and batch_file:
        raise click.UsageError("--interactive cannot be combined with --batch")

    if resume:
        from pathlib import Path
        from buildroot.agent.models import seed_recipes_from_results
        count = seed_recipes_from_results(Path(resume))
        click.echo(f"Seeded {count} recipes from {resume}")

    isolate_podman = not no_isolate_podman
    if isolate_podman:
        from buildroot.utils.podman_isolation import save_base_images
        click.echo("Pre-warming base images for isolated podman storage...")
        save_base_images()

    # Batch mode (always v3)
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
            r = _run_v3(coord, host, max_iterations, resume, isolate_podman)
            results.append({"coordinate": coord, **r.to_dict()})

            safe_name = coord.replace(":", "_").replace(".", "_")
            (out_dir / f"{safe_name}.json").write_text(json.dumps(r.to_dict(), indent=2) + "\n")

        summary = {
            "total": len(results),
            "success": sum(1 for r in results if r.get("status") in ("success", "recipe_skip")),
            "results": results,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        click.echo(f"\nBatch complete: {summary['success']}/{summary['total']} succeeded")
        click.echo(f"Results: {out_dir}")
        sys.exit(0 if summary["success"] == summary["total"] else 1)

    if not coordinate:
        raise click.UsageError("Provide a COORDINATE or --batch FILE")

    if interactive:
        _run_interactive(coordinate, host, isolate_podman)

    from pathlib import Path
    from buildroot.agent.build_store import fetch_build
    from buildroot.pipeline.orchestrator import parse_gav
    group_id, artifact_id, version = parse_gav(coordinate)

    # DB check before running the pipeline
    if not force:
        db_record = fetch_build(group_id, artifact_id, version, min_reward=0.98)
        if db_record:
            _output_record(db_record, output_dir)
            sys.exit(0)

    # No DB hit (or --force) — run the full pipeline
    if v3_only:
        result = _run_v3(coordinate, host, max_iterations, resume, isolate_podman, force)
    else:
        result = _run_orchestrator(coordinate, host, max_budget, max_turns, isolate_podman, force)

    if result.status not in ("success", "recipe_skip"):
        click.echo(json.dumps(result.to_dict(), indent=2))
        sys.exit(1)

    # Build succeeded — re-query DB for the saved record and output in db fetch format
    db_record = fetch_build(group_id, artifact_id, version)
    if db_record:
        _output_record(db_record, output_dir)
        sys.exit(0)

    # Fallback: build succeeded but wasn't saved to DB (reward < 0.9)
    click.echo(json.dumps(result.to_dict(), indent=2))
    sys.exit(0)


def _output_record(record: dict, output_dir: str | None) -> None:
    """Output a DB record as JSON, optionally saving Containerfile + metadata to a directory."""
    from pathlib import Path
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "Containerfile").write_text(record["containerfile"])
        meta = {k: val for k, val in record.items() if k != "containerfile"}
        (out / "build-metadata.json").write_text(json.dumps(meta, indent=2))
        click.echo(f"Saved to {out}/")
        click.echo(json.dumps(meta, indent=2))
    else:
        click.echo(json.dumps(record, indent=2))


def _run_v3(coordinate, host, max_iterations, resume, isolate_podman=True, force=False):
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
        isolate_podman=isolate_podman,
        force=force,
    )


def _run_interactive(coordinate, host, isolate_podman=True):
    """Launch an interactive Claude session with orchestrator context."""
    from buildroot.agent.meta_agent import launch_interactive_orchestrator

    rc = launch_interactive_orchestrator(coordinate, host=host, isolate_podman=isolate_podman)
    sys.exit(rc)


def _run_orchestrator(coordinate, host, max_budget, max_turns, isolate_podman=True, force=False):
    """Run a single coordinate through the v4 orchestrator."""
    from buildroot.agent.meta_agent import run_orchestrator

    return run_orchestrator(
        coordinate,
        host=host,
        max_budget_usd=max_budget,
        max_agent_turns=max_turns,
        isolate_podman=isolate_podman,
        force=force,
    )
