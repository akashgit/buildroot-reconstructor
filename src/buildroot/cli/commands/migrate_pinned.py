"""CLI command to migrate existing trusted Containerfiles to pinned dependencies."""

from __future__ import annotations

import logging
import re

import click

logger = logging.getLogger(__name__)

DEFAULT_MAVEN_VERSION = "3.9.6"

PINNED_MAVEN_TEMPLATE = """\
ENV MAVEN_VERSION={version}
RUN cd /tmp && \\
    wget -q https://maven-central.storage.googleapis.com/maven2/org/apache/maven/apache-maven/${{MAVEN_VERSION}}/apache-maven-${{MAVEN_VERSION}}-bin.tar.gz && \\
    echo "{checksum}  apache-maven-${{MAVEN_VERSION}}-bin.tar.gz" | sha256sum -c - && \\
    tar xzf apache-maven-${{MAVEN_VERSION}}-bin.tar.gz -C /opt && \\
    ln -s /opt/apache-maven-${{MAVEN_VERSION}}/bin/mvn /usr/local/bin/mvn && \\
    rm apache-maven-${{MAVEN_VERSION}}-bin.tar.gz"""


def _get_connection():
    """Get a Postgres connection. Returns None if unavailable."""
    try:
        import psycopg2
    except ImportError:
        return None

    import os
    url = os.environ.get("DATABASE_URL", "postgresql:///postgres")
    try:
        return psycopg2.connect(url)
    except Exception:
        return None


def _query_candidates(conn, limit: int | None = None) -> list[dict]:
    """Query L3+ trusted builds that need pinning migration."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, group_id, artifact_id, version, trusted_containerfile
            FROM builds
            WHERE trusted_level >= 3
              AND trusted_containerfile IS NOT NULL
              AND trusted_containerfile != ''
              AND (
                trusted_containerfile ~* 'apt-get\\s+install.*maven'
                OR trusted_containerfile !~ '@sha256:'
              )
              AND (level < 4 OR eval_result IS NOT NULL)
            ORDER BY id
            """
            + (" LIMIT %s" % int(limit) if limit else ""),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "group_id": r[1],
            "artifact_id": r[2],
            "version": r[3],
            "trusted_containerfile": r[4],
        }
        for r in rows
    ]


def _extract_maven_version_from_cf(containerfile: str) -> str | None:
    """Extract Maven version from an existing apache-maven-X.Y.Z pattern."""
    m = re.search(r"apache-maven-(\d+\.\d+\.\d+)", containerfile)
    if m:
        return m.group(1)
    return None


def _pin_from_line(line: str, registry) -> tuple[str, bool]:
    """Rewrite a FROM line to include @sha256: digest if missing.

    Returns (rewritten_line, changed).
    """
    if "@sha256:" in line:
        return line, False

    m = re.match(r"^(FROM\s+)(\S+)(.*)", line, re.IGNORECASE)
    if not m:
        return line, False

    prefix, image_ref, suffix = m.group(1), m.group(2), m.group(3)
    digest = registry.resolve_image_digest(image_ref)
    if not digest:
        return line, False

    pinned = f"{image_ref}@{digest}"
    return f"{prefix}{pinned}{suffix}", True


def _remove_maven_ensure_wget(line: str) -> str:
    """Remove 'maven' from an apt-get install line and ensure 'wget' is present."""
    m = re.search(r"apt-get\s+install\s+", line, re.IGNORECASE)
    if not m:
        return line

    prefix = line[: m.end()]
    rest = line[m.end() :]

    token_re = re.compile(r"[-\w][-\w.]*")
    tokens = []
    last_end = 0
    for tok_match in token_re.finditer(rest):
        between = rest[last_end : tok_match.start()]
        if between.strip():
            break
        tokens.append(tok_match.group())
        last_end = tok_match.end()

    suffix = rest[last_end:]

    flags = [t for t in tokens if t.startswith("-")]
    packages = [t for t in tokens if not t.startswith("-")]
    packages = [p for p in packages if p.lower() != "maven"]
    if "wget" not in packages:
        packages.append("wget")

    new_args = " ".join(flags + packages)
    return prefix + new_args + suffix


def _replace_apt_maven(containerfile: str, registry) -> tuple[str, bool, str | None]:
    """Replace apt-get install maven with pinned tarball block.

    Keeps the apt-get line with remaining packages (removing only maven,
    ensuring wget is present) and appends the pinned Maven tarball block.

    Returns (new_containerfile, changed, reason_if_skipped).
    """
    if not re.search(r"apt-get\s+install.*maven", containerfile, re.IGNORECASE):
        return containerfile, False, None

    version = _extract_maven_version_from_cf(containerfile) or DEFAULT_MAVEN_VERSION
    checksum = registry.get_maven_checksum(version)
    if not checksum:
        return containerfile, False, f"no checksum for Maven {version}"

    replacement = PINNED_MAVEN_TEMPLATE.format(version=version, checksum=checksum)

    lines = containerfile.split("\n")
    blocks: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        start = i
        while i < len(lines) - 1 and lines[i].rstrip().endswith("\\"):
            i += 1
        blocks.append((start, i))
        i += 1

    result_lines: list[str] = []
    changed = False
    for start, end in blocks:
        if any(
            re.search(r"apt-get\s+install.*maven", lines[j], re.IGNORECASE)
            for j in range(start, end + 1)
        ):
            for j in range(start, end + 1):
                if re.search(r"apt-get\s+install", lines[j], re.IGNORECASE):
                    result_lines.append(_remove_maven_ensure_wget(lines[j]))
                else:
                    result_lines.append(lines[j])
            result_lines.append(replacement)
            changed = True
        else:
            result_lines.extend(lines[start : end + 1])

    new_cf = "\n".join(result_lines)
    return new_cf, changed, None


def _add_checksum_verification(containerfile: str, registry) -> tuple[str, bool]:
    """Add sha256sum verification to existing maven tarball downloads that lack it."""
    if "sha256sum" in containerfile:
        return containerfile, False

    m = re.search(r"apache-maven-(\d+\.\d+\.\d+)-bin\.tar\.gz", containerfile)
    if not m:
        return containerfile, False

    version = m.group(1)
    checksum = registry.get_maven_checksum(version)
    if not checksum:
        return containerfile, False

    verify_line = f'    echo "{checksum}  apache-maven-{version}-bin.tar.gz" | sha256sum -c - && \\\n'

    tar_pattern = re.compile(
        r"^(.*tar\s+(?:xzf|xf|zxf)\s+apache-maven-.*$)",
        re.MULTILINE,
    )
    tar_match = tar_pattern.search(containerfile)
    if not tar_match:
        return containerfile, False

    insert_pos = tar_match.start()
    new_cf = containerfile[:insert_pos] + verify_line + containerfile[insert_pos:]
    return new_cf, True


def _update_trusted_containerfile(conn, build_id: int, new_cf: str) -> bool:
    """Update only the trusted_containerfile column via direct SQL."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE builds SET trusted_containerfile = %s WHERE id = %s",
                (new_cf, build_id),
            )
        conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to update build %d: %s", build_id, e)
        conn.rollback()
        return False


def migrate_builds(
    dry_run: bool = False,
    limit: int | None = None,
    verbose: bool = False,
) -> dict:
    """Run the migration. Returns a summary dict."""
    from buildroot.trust.registry import TrustedSourceRegistry

    registry = TrustedSourceRegistry()
    conn = _get_connection()
    if not conn:
        return {"error": "Cannot connect to database", "total": 0, "migrated": 0, "skipped": 0}

    try:
        candidates = _query_candidates(conn, limit)
        total = len(candidates)
        migrated = 0
        skipped = 0
        skip_reasons: list[str] = []

        for row in candidates:
            build_id = row["id"]
            gav = f"{row['group_id']}:{row['artifact_id']}:{row['version']}"
            cf = row["trusted_containerfile"]
            changes_made = False

            lines = cf.split("\n")
            new_lines = []
            for line in lines:
                new_line, changed = _pin_from_line(line, registry)
                new_lines.append(new_line)
                if changed:
                    changes_made = True
                    if verbose:
                        click.echo(f"  [{gav}] Pinned FROM: {line.strip()} -> {new_line.strip()}")

            cf = "\n".join(new_lines)

            cf, apt_changed, skip_reason = _replace_apt_maven(cf, registry)
            if apt_changed:
                changes_made = True
                if verbose:
                    click.echo(f"  [{gav}] Replaced apt-get install maven with pinned tarball")
            elif skip_reason:
                if verbose:
                    click.echo(f"  [{gav}] Skipped apt-get replacement: {skip_reason}")

            cf, checksum_changed = _add_checksum_verification(cf, registry)
            if checksum_changed:
                changes_made = True
                if verbose:
                    click.echo(f"  [{gav}] Added checksum verification to maven tarball")

            if not changes_made:
                skipped += 1
                reason = f"{gav}: no changes needed"
                skip_reasons.append(reason)
                if verbose:
                    click.echo(f"  [{gav}] Skipped: no changes needed")
                continue

            if dry_run:
                click.echo(f"[DRY RUN] Would migrate {gav}")
                if verbose:
                    click.echo(f"  New Containerfile:\n{cf}")
                migrated += 1
            else:
                if _update_trusted_containerfile(conn, build_id, cf):
                    migrated += 1
                    if verbose:
                        click.echo(f"  [{gav}] Updated in DB")
                else:
                    skipped += 1
                    skip_reasons.append(f"{gav}: DB update failed")

        return {
            "total": total,
            "migrated": migrated,
            "skipped": skipped,
            "skip_reasons": skip_reasons,
        }
    finally:
        conn.close()


@click.command("migrate-pinned")
@click.option("--dry-run", is_flag=True, help="Print what would change without writing to DB")
@click.option("--limit", type=int, default=None, help="Process at most N builds")
@click.option("--verbose", is_flag=True, help="Show per-build details")
def migrate_pinned_cmd(dry_run: bool, limit: int | None, verbose: bool):
    """Migrate existing trusted Containerfiles to use pinned dependencies.

    Rewrites FROM lines with @sha256: digests, replaces apt-get install maven
    with checksummed tarball installs, and adds checksum verification to
    existing tarball downloads.
    """
    click.echo("Migrating trusted Containerfiles to pinned dependencies...")
    if dry_run:
        click.echo("(dry-run mode — no changes will be written)")

    result = migrate_builds(dry_run=dry_run, limit=limit, verbose=verbose)

    if "error" in result:
        click.echo(f"Error: {result['error']}")
        raise SystemExit(1)

    click.echo(f"\nSummary:")
    click.echo(f"  Total candidates: {result['total']}")
    click.echo(f"  Migrated: {result['migrated']}")
    click.echo(f"  Skipped: {result['skipped']}")
    if result.get("skip_reasons"):
        click.echo(f"  Skip reasons:")
        for reason in result["skip_reasons"]:
            click.echo(f"    - {reason}")
