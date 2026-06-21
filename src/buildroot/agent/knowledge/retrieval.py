"""Knowledge base retrieval — ranked query over templates, tips, and tricks."""

from __future__ import annotations

import logging
from pathlib import Path

from buildroot.agent.knowledge.schema import (
    EntryType,
    KBEntry,
    TemplateEntry,
    TipEntry,
    TrickEntry,
    load_all_entries,
)

logger = logging.getLogger(__name__)

DEFAULT_KB_DIR = Path.home() / ".buildroot" / "kb"


def query_kb(
    *,
    build_system: str | None = None,
    tags: list[str] | None = None,
    error_pattern: str | None = None,
    group_id: str | None = None,
    query: str | None = None,
    kb_dir: Path | None = None,
    limit: int = 10,
) -> list[tuple[KBEntry, float]]:
    """Query the knowledge base with ranked retrieval.

    Returns (entry, relevance_score) pairs sorted by descending relevance.
    """
    kb_dir = kb_dir or DEFAULT_KB_DIR
    entries = load_all_entries(kb_dir)
    if not entries:
        return []

    scored: list[tuple[KBEntry, float]] = []
    for entry in entries:
        score = _score_entry(
            entry,
            build_system=build_system,
            tags=tags,
            error_pattern=error_pattern,
            group_id=group_id,
            query=query,
        )
        if score > 0:
            scored.append((entry, score))

    scored.sort(key=lambda x: (-x[1], x[0].name))
    return scored[:limit]


def query_kb_for_prompt(
    *,
    build_system: str | None = None,
    tags: list[str] | None = None,
    error_pattern: str | None = None,
    group_id: str | None = None,
    kb_dir: Path | None = None,
    limit: int = 10,
) -> str:
    """Query KB and format results for injection into an agent prompt."""
    results = query_kb(
        build_system=build_system,
        tags=tags,
        error_pattern=error_pattern,
        group_id=group_id,
        kb_dir=kb_dir,
        limit=limit,
    )
    if not results:
        return ""

    sections = ["## Knowledge Base Entries\n"]
    for entry, score in results:
        sections.append(f"### {entry.name} ({entry.entry_type.value}, relevance={score:.1f})")
        sections.append(f"**Description:** {entry.description}")
        if entry.tags:
            sections.append(f"**Tags:** {', '.join(entry.tags)}")

        if isinstance(entry, TemplateEntry) and entry.containerfile:
            cf_preview = entry.containerfile[:500]
            if len(entry.containerfile) > 500:
                cf_preview += "\n... (truncated)"
            sections.append(f"**Containerfile (L4={entry.l4_score}):**\n```\n{cf_preview}\n```")
        elif isinstance(entry, TipEntry):
            sections.append(f"**Trigger:** {entry.trigger}")
            sections.append(f"**Solution:** {entry.solution}")
            if entry.caveats:
                sections.append(f"**Caveats:** {entry.caveats}")
        elif isinstance(entry, TrickEntry):
            sections.append(f"**Error pattern:** {entry.error_pattern}")
            sections.append(f"**Fix:** {entry.fix}")

        sections.append("")

    return "\n".join(sections)


def _score_entry(
    entry: KBEntry,
    *,
    build_system: str | None = None,
    tags: list[str] | None = None,
    error_pattern: str | None = None,
    group_id: str | None = None,
    query: str | None = None,
) -> float:
    """Score an entry's relevance to the query parameters."""
    score = 0.0

    if build_system and entry.build_systems:
        if build_system.lower() in [bs.lower() for bs in entry.build_systems]:
            score += 3.0

    if tags:
        entry_tags_lower = {t.lower() for t in entry.tags}
        matching = sum(1 for t in tags if t.lower() in entry_tags_lower)
        if matching:
            score += 2.0 * matching

    if error_pattern and isinstance(entry, TrickEntry):
        pattern_lower = error_pattern.lower()
        if entry.error_pattern and entry.error_pattern.lower() in pattern_lower:
            score += 5.0
        elif any(word in pattern_lower for word in entry.error_pattern.lower().split() if len(word) > 3):
            score += 2.0

    if group_id and isinstance(entry, TemplateEntry):
        if entry.coordinate and entry.coordinate.startswith(group_id):
            score += 4.0

    if query:
        query_lower = query.lower()
        searchable = f"{entry.name} {entry.description} {' '.join(entry.tags)}".lower()
        if isinstance(entry, TipEntry):
            searchable += f" {entry.trigger} {entry.solution}".lower()
        elif isinstance(entry, TrickEntry):
            searchable += f" {entry.error_pattern} {entry.fix}".lower()

        query_words = [w for w in query_lower.split() if len(w) > 2]
        matching_words = sum(1 for w in query_words if w in searchable)
        if matching_words:
            score += 1.0 * matching_words

    if score == 0 and not (build_system or tags or error_pattern or group_id or query):
        score = 0.1

    if entry.times_used > 0 and entry.success_rate > 0:
        score *= (1.0 + 0.1 * min(entry.success_rate, 1.0))

    return score
