"""CLI commands for the build store database."""

import json
from pathlib import Path

import click


@click.group("db")
def db_cmd():
    """Manage the build store database."""


@db_cmd.command("init")
def db_init():
    """Create the builds table if it doesn't exist."""
    from buildroot.agent.build_store import init_table

    if init_table():
        click.echo("Build store initialized.")
    else:
        click.echo("Failed to initialize build store — check database connection.", err=True)
        raise SystemExit(1)


@db_cmd.command("stats")
def db_stats():
    """Show build store statistics."""
    from buildroot.agent.build_store import _get_connection

    conn = _get_connection()
    if not conn:
        click.echo("Cannot connect to build store.", err=True)
        raise SystemExit(1)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM builds")
            total = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM builds WHERE reward >= 0.98")
            l4 = cur.fetchone()[0]
            cur.execute("SELECT count(DISTINCT group_id || ':' || artifact_id) FROM builds")
            artifacts = cur.fetchone()[0]
            click.echo(f"Total builds: {total}")
            click.echo(f"L4 builds (reward >= 0.98): {l4}")
            click.echo(f"Unique artifacts: {artifacts}")
    finally:
        conn.close()


@db_cmd.command("fetch")
@click.argument("gav")
@click.option("--output-dir", "-o", type=click.Path(), default=None,
              help="Directory to save Containerfile and metadata. Defaults to stdout JSON.")
def db_fetch(gav: str, output_dir: str | None):
    """Fetch build details from the DB for a GAV coordinate.

    GAV format: groupId:artifactId:version

    Returns the trusted Containerfile (preferred) or regular Containerfile,
    along with build metadata. Exits with code 1 if no build found.

    Examples:\n
        buildroot db fetch net.minidev:json-smart:2.4.8\n
        buildroot db fetch com.fasterxml.jackson.core:jackson-databind:2.13.4.1 -o /tmp/build
    """
    from buildroot.agent.build_store import _get_connection

    parts = gav.split(":")
    if len(parts) != 3:
        click.echo(f"Invalid GAV format: {gav!r} — expected groupId:artifactId:version", err=True)
        raise SystemExit(1)

    group_id, artifact_id, version = parts

    conn = _get_connection()
    if not conn:
        click.echo("Cannot connect to build store.", err=True)
        raise SystemExit(1)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    containerfile,
                    reward,
                    level,
                    trusted_containerfile,
                    trusted_reward,
                    trusted_level,
                    method,
                    CASE WHEN rebuilt_jar IS NOT NULL THEN length(rebuilt_jar) ELSE 0 END,
                    created_at
                FROM builds
                WHERE group_id = %s AND artifact_id = %s AND version = %s
            """, (group_id, artifact_id, version))

            row = cur.fetchone()
            if not row:
                click.echo(json.dumps({"status": "not_found", "gav": gav}))
                raise SystemExit(1)

            (build_id, containerfile, reward, level,
             trusted_cf, trusted_reward, trusted_level,
             method, jar_size, created_at) = row

            use_trusted = bool(trusted_cf and trusted_cf.strip())
            cf = trusted_cf if use_trusted else containerfile
            cf_reward = trusted_reward if use_trusted else reward
            cf_level = trusted_level if use_trusted else level

            result = {
                "status": "found",
                "gav": gav,
                "group_id": group_id,
                "artifact_id": artifact_id,
                "version": version,
                "build_id": build_id,
                "source": "trusted" if use_trusted else "regular",
                "level": cf_level,
                "reward": cf_reward,
                "method": method,
                "rebuilt_jar_bytes": jar_size,
                "created_at": str(created_at),
                "containerfile": cf,
            }

            if output_dir:
                out = Path(output_dir)
                out.mkdir(parents=True, exist_ok=True)
                (out / "Containerfile").write_text(cf)
                meta = {k: v for k, v in result.items() if k != "containerfile"}
                (out / "build-metadata.json").write_text(json.dumps(meta, indent=2))
                click.echo(f"Saved to {out}/")
                click.echo(json.dumps(meta, indent=2))
            else:
                click.echo(json.dumps(result, indent=2))

    finally:
        conn.close()
