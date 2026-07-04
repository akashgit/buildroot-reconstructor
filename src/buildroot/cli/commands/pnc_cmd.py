"""CLI command for standalone PNC build environment lookups."""

from __future__ import annotations

import json
import logging
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
