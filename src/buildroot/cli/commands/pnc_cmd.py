"""CLI commands for PNC build environment lookups and submissions."""

from __future__ import annotations

import json
import logging
import os
import sys

import click


@click.command("pnc-lookup")
@click.argument("coordinate")
@click.option("--output", "output_path", type=click.Path(), help="Write full PNC API JSON response to file")
@click.option("--json", "json_output", is_flag=True, help="Output structured JSON instead of human-readable format")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def pnc_lookup_cmd(coordinate: str, output_path: str | None, json_output: bool, verbose: bool) -> None:
    """Look up PNC build information for a Maven COORDINATE (group:artifact:version).

    Queries the PNC API by SHA-256 (downloads JAR from Maven Central first),
    falling back to GAV identifier lookup.

    \b
    Example: buildroot pnc-lookup com.fasterxml.jackson.core:jackson-annotations:2.9.9.redhat-00001
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from buildroot.pipeline.orchestrator import parse_gav
    from buildroot.utils.pnc_api import PncClient

    group_id, artifact_id, version = parse_gav(coordinate)
    client = PncClient()

    # Try SHA-256 lookup first (download JAR, compute hash)
    info = None
    try:
        from buildroot.utils.maven_central import get_jar_path
        import hashlib

        jar_path = get_jar_path(group_id, artifact_id, version)
        sha256 = hashlib.sha256(jar_path.read_bytes()).hexdigest()
        info = client.query_by_sha256(sha256)
    except Exception as e:
        logging.getLogger(__name__).debug("SHA-256 lookup failed: %s", e)

    # Fall back to GAV lookup
    if info is None:
        info = client.query_by_gav(group_id, artifact_id, version)

    if info is None:
        click.echo(f"No PNC build found for {coordinate}", err=True)
        sys.exit(1)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(info.raw_response, f, indent=2)
        click.echo(f"Raw PNC response written to {output_path}")

    if json_output:
        result = {
            "coordinate": coordinate,
            "build_id": info.build_id,
            "builder_image": info.builder_image,
            "jdk_version": info.jdk_version,
            "maven_version": info.maven_version,
            "gradle_version": info.gradle_version,
            "rhel_version": info.rhel_version,
            "scm_external_url": info.scm_external_url,
            "scm_revision": info.scm_revision,
            "scm_url": info.scm_url,
            "scm_tag": info.scm_tag,
            "environment_id": info.environment_id,
        }
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"PNC Build Info for {coordinate}")
        click.echo(f"  Build ID:        {info.build_id}")
        click.echo(f"  Builder Image:   {info.builder_image}")
        click.echo(f"  JDK Version:     {info.jdk_version or 'N/A'}")
        click.echo(f"  Maven Version:   {info.maven_version or 'N/A'}")
        click.echo(f"  Gradle Version:  {info.gradle_version or 'N/A'}")
        click.echo(f"  RHEL Version:    {info.rhel_version or 'N/A'}")
        click.echo(f"  Upstream SCM:    {info.scm_external_url or 'N/A'}")
        click.echo(f"  Upstream Rev:    {info.scm_revision or 'N/A'}")
        click.echo(f"  Downstream SCM:  {info.scm_url or 'N/A'}")
        click.echo(f"  Downstream Tag:  {info.scm_tag or 'N/A'}")
        click.echo(f"  Environment ID:  {info.environment_id or 'N/A'}")


@click.command("pnc-submit")
@click.argument("coordinate")
@click.option("--profile", default="stage", help="PNC profile (stage or prod)")
@click.option("--project-id", default="4249", help="PNC project ID")
@click.option("--timeout", default=20, type=int, help="Build timeout in minutes")
@click.option(
    "--containerfile",
    type=click.Path(exists=True),
    help="Path to Containerfile (overrides DB lookup)",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def pnc_submit(
    coordinate: str,
    profile: str,
    project_id: str,
    timeout: int,
    containerfile: str | None,
    verbose: bool,
) -> None:
    """Submit a PNC build for a Maven COORDINATE (group:artifact:version).

    Parses the Containerfile (from --containerfile or the builds DB) to extract
    build parameters, then submits to PNC staging via bacon.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from buildroot.utils.pnc_submit import parse_containerfile_for_pnc, submit_pnc_build

    if containerfile:
        with open(containerfile) as f:
            containerfile_text = f.read()
    else:
        containerfile_text = _fetch_containerfile_from_db(coordinate)

    params = parse_containerfile_for_pnc(containerfile_text)
    click.echo(f"Parsed build params for {coordinate}:")
    click.echo(f"  Git URL:       {params.git_url}")
    click.echo(f"  Git Tag:       {params.git_tag}")
    click.echo(f"  Build Command: {params.build_command}")
    click.echo(f"  Build Type:    {params.build_type}")
    click.echo(f"  JDK Version:   {params.jdk_version}")

    click.echo(f"\nSubmitting to PNC ({profile})...")
    result = submit_pnc_build(
        params, profile=profile, project_id=project_id, timeout=timeout
    )

    click.echo(f"\nBuild Result:")
    click.echo(f"  Build ID: {result.build_id}")
    click.echo(f"  Status:   {result.status}")
    if result.artifacts:
        click.echo(f"  Artifacts ({len(result.artifacts)}):")
        for art in result.artifacts:
            click.echo(f"    - {art.get('identifier', 'unknown')}")


def _fetch_containerfile_from_db(coordinate: str) -> str:
    parts = coordinate.split(":")
    if len(parts) < 3:
        raise click.ClickException(
            f"Invalid coordinate format: {coordinate} (expected group:artifact:version)"
        )
    group_id, artifact_id, version = parts[0], parts[1], parts[2]

    try:
        import psycopg2

        url = os.environ.get("DATABASE_URL", "postgresql:///postgres")
        conn = psycopg2.connect(url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT containerfile FROM builds "
                    "WHERE group_id = %s AND artifact_id = %s AND version = %s",
                    (group_id, artifact_id, version),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    raise click.ClickException(
                        f"No Containerfile found in DB for {coordinate}. "
                        "Use --containerfile to provide one directly."
                    )
                return row[0]
        finally:
            conn.close()
    except ImportError:
        raise click.ClickException(
            "psycopg2 not installed — cannot query builds DB. "
            "Use --containerfile to provide a Containerfile directly."
        )
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"DB lookup failed: {e}")
