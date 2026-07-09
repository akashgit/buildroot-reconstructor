"""CLI command for transitive dependency PNC coverage analysis."""

from __future__ import annotations

import json
import logging

import click

from buildroot.pipeline.models import DependencyNode


def flatten_dependency_tree(nodes: list[DependencyNode]) -> list[tuple[str, str, str]]:
    """Flatten a DependencyNode tree into deduplicated (group_id, artifact_id, version) tuples."""
    seen: set[tuple[str, str, str]] = set()
    result: list[tuple[str, str, str]] = []

    def _walk(node: DependencyNode) -> None:
        key = (node.group_id, node.artifact_id, node.version)
        if key not in seen:
            seen.add(key)
            result.append(key)
        for child in node.children:
            _walk(child)

    for node in nodes:
        _walk(node)
    return result


@click.command("pnc-deps")
@click.argument("coordinate")
@click.option("--json", "json_output", is_flag=True, help="Output structured JSON")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def pnc_deps_cmd(coordinate: str, json_output: bool, verbose: bool) -> None:
    """Analyze transitive dependency PNC coverage for a Maven COORDINATE (group:artifact:version)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from buildroot.agent import build_store
    from buildroot.pipeline.orchestrator import parse_gav
    from buildroot.resolvers.dependencies import DependencyResolver
    from buildroot.utils.pnc_api import PncClient, find_closest_pnc_version

    try:
        group_id, artifact_id, version = parse_gav(coordinate)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="COORDINATE") from e

    resolver = DependencyResolver()
    tree = resolver.resolve(group_id, artifact_id, version)
    deps = flatten_dependency_tree(tree)

    client = PncClient()
    results: list[dict] = []

    for g, a, v in deps:
        info = client.query_by_gav(g, a, v)
        closest = None
        closest_version = None
        if info is None:
            match = find_closest_pnc_version(g, a, v, client=client)
            if match is not None:
                closest_version, closest = match

        store_record = build_store.fetch_build(g, a, v)

        results.append({
            "group_id": g,
            "artifact_id": a,
            "version": v,
            "pnc_available": info is not None,
            "pnc_build_id": info.build_id if info else None,
            "closest_pnc_version": closest_version,
            "in_build_store": store_record is not None,
        })

    total = len(results)
    pnc_count = sum(1 for r in results if r["pnc_available"])
    store_count = sum(1 for r in results if r["in_build_store"])
    missing_count = total - pnc_count

    if json_output:
        output = {
            "coordinate": coordinate,
            "total": total,
            "pnc_available": pnc_count,
            "missing": missing_count,
            "build_store_available": store_count,
            "dependencies": results,
        }
        click.echo(json.dumps(output, indent=2))
        return

    pnc_pct = (pnc_count / total * 100) if total else 0
    store_pct = (store_count / total * 100) if total else 0
    missing_pct = (missing_count / total * 100) if total else 0

    click.echo(f"PNC Dependency Coverage for {coordinate}")
    click.echo(f"  Total dependencies:    {total}")
    click.echo(f"  Available in PNC:      {pnc_count} ({pnc_pct:.0f}%)")
    click.echo(f"  In build store:        {store_count} ({store_pct:.0f}%)")
    click.echo(f"  Missing from PNC:      {missing_count} ({missing_pct:.0f}%)")

    missing_deps = [r for r in results if not r["pnc_available"]]
    if missing_deps:
        click.echo("")
        click.echo("Missing Dependencies:")
        click.echo(f"  {'GAV':<60} {'Closest PNC Version':<35} {'In Store'}")
        click.echo(f"  {'-'*60} {'-'*35} {'-'*8}")
        for dep in missing_deps:
            gav = f"{dep['group_id']}:{dep['artifact_id']}:{dep['version']}"
            closest = dep["closest_pnc_version"] or "-"
            in_store = "Yes" if dep["in_build_store"] else "No"
            click.echo(f"  {gav:<60} {closest:<35} {in_store}")
