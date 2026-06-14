"""Knowledge base reader/writer for cross-package learning."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

KB_DIR = Path(__file__).parent


def read_patterns(package_type: str = "") -> str:
    """Read relevant patterns from the knowledge base.

    If package_type is provided, returns only the matching section from patterns.md.
    Otherwise returns the full General Patterns section.
    """
    patterns_path = KB_DIR / "patterns.md"
    if not patterns_path.exists():
        return ""

    content = patterns_path.read_text()

    if not package_type:
        return _extract_section(content, "General Patterns")

    section = _extract_section(content, package_type)
    general = _extract_section(content, "General Patterns")

    parts = []
    if section:
        parts.append(section)
    if general:
        parts.append(general)
    return "\n\n".join(parts) if parts else ""


def read_taxonomy() -> str:
    """Read the current failure taxonomy."""
    taxonomy_path = KB_DIR / "failure_taxonomy.md"
    if not taxonomy_path.exists():
        return ""
    return taxonomy_path.read_text()


def read_clusters() -> str:
    """Read the package clusters file."""
    clusters_path = KB_DIR / "package_clusters.md"
    if not clusters_path.exists():
        return ""
    return clusters_path.read_text()


def update_taxonomy(analysis: object) -> None:
    """Update failure_taxonomy.md with data from a FailureAnalysis.

    Accepts any object with an error_frequencies attribute (list of objects
    with error_class, count, and packages attributes).
    """
    taxonomy_path = KB_DIR / "failure_taxonomy.md"

    lines = ["# Failure Taxonomy", "", "| Error Class | Frequency | Resolution Status |"]
    lines.append("|---|---|---|")

    error_freqs = getattr(analysis, "error_frequencies", [])
    for ef in error_freqs:
        error_class = getattr(ef, "error_class", "unknown")
        count = getattr(ef, "count", 0)
        exhausted = getattr(ef, "exhausted_count", 0)
        under_explored = getattr(ef, "under_explored_count", 0)

        if exhausted > 0 and under_explored == 0:
            status = "Exhausted"
        elif exhausted > 0:
            status = "Partially exhausted"
        else:
            status = "Under exploration"

        lines.append(f"| {error_class} | {count} | {status} |")

    taxonomy_path.write_text("\n".join(lines) + "\n")
    logger.info("Updated failure taxonomy with %d error classes", len(error_freqs))


def record_pattern(package_type: str, pattern: str) -> None:
    """Append a learned pattern to the appropriate section in patterns.md."""
    patterns_path = KB_DIR / "patterns.md"
    if not patterns_path.exists():
        patterns_path.write_text(f"# Build Patterns Knowledge Base\n\n## {package_type}\n\n- {pattern}\n")
        return

    content = patterns_path.read_text()
    section_header = f"## {package_type}"

    if section_header in content:
        insert_point = content.index(section_header) + len(section_header)
        next_section = content.find("\n## ", insert_point)
        if next_section == -1:
            content = content.rstrip() + f"\n- {pattern}\n"
        else:
            content = (
                content[:next_section].rstrip()
                + f"\n- {pattern}\n\n"
                + content[next_section:]
            )
    else:
        content = content.rstrip() + f"\n\n## {package_type}\n\n- {pattern}\n"

    patterns_path.write_text(content)
    logger.info("Recorded pattern for %s: %s", package_type, pattern[:80])


def _extract_section(content: str, section_name: str) -> str:
    """Extract a markdown section by heading name."""
    pattern = re.compile(
        rf"^##\s+{re.escape(section_name)}\s*$",
        re.MULTILINE | re.IGNORECASE,
    )
    match = pattern.search(content)
    if not match:
        return ""

    start = match.end()
    next_section = re.search(r"^## ", content[start:], re.MULTILINE)
    if next_section:
        section = content[start:start + next_section.start()]
    else:
        section = content[start:]

    return section.strip()
