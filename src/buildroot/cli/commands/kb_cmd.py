"""CLI commands for the buildroot knowledge base."""

from __future__ import annotations

import json
import sys

import click

from buildroot.agent.knowledge.retrieval import DEFAULT_KB_DIR


@click.group("kb")
def kb_cmd():
    """Manage the buildroot knowledge base (templates, tips, tricks)."""


@kb_cmd.command("list")
@click.option("--type", "entry_type", type=click.Choice(["template", "tip", "trick"]),
              help="Filter by entry type")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def kb_list(entry_type, json_output):
    """List all knowledge base entries."""
    from buildroot.agent.knowledge.schema import EntryType, load_all_entries

    entries = load_all_entries(DEFAULT_KB_DIR)
    if entry_type:
        entries = [e for e in entries if e.entry_type == EntryType(entry_type)]

    if json_output:
        click.echo(json.dumps([e.to_dict() for e in entries], indent=2))
        return

    if not entries:
        click.echo("No KB entries found.")
        click.echo(f"KB directory: {DEFAULT_KB_DIR}")
        return

    click.echo(f"Knowledge Base ({len(entries)} entries) — {DEFAULT_KB_DIR}\n")
    for entry in entries:
        tags = ", ".join(entry.tags[:5]) if entry.tags else "none"
        click.echo(f"  [{entry.entry_type.value:8s}] {entry.name}")
        click.echo(f"            {entry.description[:80]}")
        click.echo(f"            tags: {tags}  |  used: {entry.times_used}  |  success: {entry.success_rate:.0%}")
        click.echo()


@kb_cmd.command("search")
@click.argument("query")
@click.option("--build-system", help="Filter by build system (maven, gradle, ant)")
@click.option("--limit", default=10, type=int, help="Max results")
@click.option("--json-output", is_flag=True, help="Output as JSON")
def kb_search(query, build_system, limit, json_output):
    """Search the knowledge base by query string."""
    from buildroot.agent.knowledge.retrieval import query_kb

    results = query_kb(
        query=query,
        build_system=build_system,
        limit=limit,
    )

    if json_output:
        click.echo(json.dumps(
            [{"entry": e.to_dict(), "score": round(s, 2)} for e, s in results],
            indent=2,
        ))
        return

    if not results:
        click.echo(f"No results for '{query}'")
        return

    click.echo(f"Search results for '{query}' ({len(results)} matches):\n")
    for entry, score in results:
        click.echo(f"  [{entry.entry_type.value:8s}] {entry.name} (relevance={score:.1f})")
        click.echo(f"            {entry.description[:80]}")
        click.echo()


@kb_cmd.command("add")
@click.argument("yaml_file", type=click.Path(exists=True))
def kb_add(yaml_file):
    """Add a KB entry from a YAML file."""
    from pathlib import Path

    from buildroot.agent.knowledge.schema import load_entry, save_entry

    source = Path(yaml_file)
    entry = load_entry(source)
    if not entry:
        click.echo(f"Error: could not parse {yaml_file}", err=True)
        sys.exit(1)

    dest = save_entry(entry, DEFAULT_KB_DIR)
    click.echo(f"Added {entry.entry_type.value} '{entry.name}' → {dest}")


@kb_cmd.command("seed")
def kb_seed():
    """Seed the KB with Bouncy Castle entries (10 entries)."""
    from buildroot.agent.knowledge.seed import seed_bouncy_castle_entries

    count = seed_bouncy_castle_entries(DEFAULT_KB_DIR)
    click.echo(f"Seeded {count} Bouncy Castle entries in {DEFAULT_KB_DIR}")
