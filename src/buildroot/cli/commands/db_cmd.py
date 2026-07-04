"""CLI commands for the build store database."""

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
