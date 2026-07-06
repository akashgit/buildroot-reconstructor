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
@click.option("--output", "output_dir", type=click.Path(), help="Output directory for batch results")
@click.option("--resume", type=click.Path(exists=True), help="Resume from prior results directory (seeds RecipeStore for warm-start)")
@click.option("--v3-only", is_flag=True, help="Use v3 template pipeline only (no orchestrator)")
@click.option("--interactive", is_flag=True, help="Launch interactive Claude session with orchestrator context")
@click.option("--max-budget", default=0, type=float, help="Max budget in USD (0 = unlimited)")
@click.option("--max-turns", default=0, type=int, help="Max agent turns (0 = unlimited)")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("--enable-google-mirror", is_flag=True, help="Use Google Cloud Storage as fallback on Maven Central 429 rate limits")
@click.option("--no-isolate-podman", is_flag=True, default=False, help="Disable podman storage isolation (not recommended for parallel runs)")
def agent_cmd(coordinate, host, max_iterations, batch_file, output_dir, resume, v3_only, interactive, max_budget, max_turns, verbose, enable_google_mirror, no_isolate_podman):
    """Run agentic reconstruction loop for a Maven COORDINATE.

    Default mode uses the v4 orchestrator agent. Use --v3-only for the template pipeline.
    Builds run locally via podman by default; pass --host to use a remote SSH host.

    \b
    Single package (orchestrator): buildroot agent org.apache.commons:commons-lang3:3.14.0
    Single package (v3 only):      buildroot agent org.apache.commons:commons-lang3:3.14.0 --v3-only
    Batch (v3 only):               buildroot agent --batch packages.txt --v3-only
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if enable_google_mirror:
        from buildroot.utils.maven_central import enable_google_mirror as _enable_mirror
        _enable_mirror()

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

    if v3_only:
        result = _run_v3(coordinate, host, max_iterations, resume, isolate_podman)
        click.echo(json.dumps(result.to_dict(), indent=2))
        sys.exit(0 if result.status == "success" else 1)
    else:
        result = _run_orchestrator(coordinate, host, max_budget, max_turns, isolate_podman)
        click.echo(json.dumps(result.to_dict(), indent=2))
        sys.exit(0 if result.status == "success" else 1)


def _run_v3(coordinate, host, max_iterations, resume, isolate_podman=True):
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
    )


def _run_interactive(coordinate, host, isolate_podman=True):
    """Launch an interactive Claude session with orchestrator context."""
    from buildroot.agent.meta_agent import launch_interactive_orchestrator

    rc = launch_interactive_orchestrator(coordinate, host=host, isolate_podman=isolate_podman)
    sys.exit(rc)


def _run_orchestrator(coordinate, host, max_budget, max_turns, isolate_podman=True):
    """Run a single coordinate through the v4 orchestrator."""
    from buildroot.agent.meta_agent import run_orchestrator

    return run_orchestrator(
        coordinate,
        host=host,
        max_budget_usd=max_budget,
        max_agent_turns=max_turns,
        isolate_podman=isolate_podman,
    )
