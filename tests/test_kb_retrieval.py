"""Tests for KB retrieval — query_kb with different filters, scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from buildroot.agent.knowledge.retrieval import query_kb, query_kb_for_prompt
from buildroot.agent.knowledge.schema import (
    TemplateEntry,
    TipEntry,
    TrickEntry,
    save_entry,
)


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    d = tmp_path / "kb"
    d.mkdir()
    return d


@pytest.fixture
def populated_kb(kb_dir: Path) -> Path:
    save_entry(TipEntry(
        name="maven-encoding",

        description="Set UTF-8 encoding for Maven builds",
        tags=["maven", "encoding", "utf8"],
        build_systems=["maven"],
        trigger="unmappable character",
        solution="add encoding=UTF-8",
    ), kb_dir)
    save_entry(TrickEntry(
        name="osgi-bundle-fix",

        description="Fix OSGI bundle headers",
        tags=["osgi", "manifest", "bundle"],
        build_systems=["maven", "ant"],
        error_pattern="missing bundle headers",
        fix="use bnd tool",
    ), kb_dir)
    save_entry(TemplateEntry(
        name="commons-lang-tpl",

        description="Template for commons-lang3",
        tags=["maven", "reproducibility"],
        build_systems=["maven"],
        containerfile="FROM fedora:39\nRUN mvn package",
        coordinate="org.apache.commons:commons-lang3:3.14.0",
        l4_score=0.99,
    ), kb_dir)
    save_entry(TipEntry(
        name="gradle-daemon",

        description="Disable Gradle daemon for reproducible builds",
        tags=["gradle", "daemon"],
        build_systems=["gradle"],
        trigger="inconsistent outputs",
        solution="org.gradle.daemon=false",
    ), kb_dir)
    return kb_dir


class TestQueryKB:
    def test_query_all_with_no_filters(self, populated_kb: Path):
        results = query_kb(kb_dir=populated_kb)
        assert len(results) == 4
        for entry, score in results:
            assert score > 0

    def test_query_by_build_system(self, populated_kb: Path):
        results = query_kb(build_system="maven", kb_dir=populated_kb)
        names = {e.name for e, _ in results}
        assert "maven-encoding" in names
        assert "commons-lang-tpl" in names
        assert "osgi-bundle-fix" in names
        assert "gradle-daemon" not in names

    def test_query_by_tags(self, populated_kb: Path):
        results = query_kb(tags=["osgi"], kb_dir=populated_kb)
        names = {e.name for e, _ in results}
        assert "osgi-bundle-fix" in names

    def test_query_by_error_pattern(self, populated_kb: Path):
        results = query_kb(error_pattern="missing bundle headers in manifest", kb_dir=populated_kb)
        assert any(e.name == "osgi-bundle-fix" for e, _ in results)

    def test_query_by_group_id(self, populated_kb: Path):
        results = query_kb(group_id="org.apache.commons", kb_dir=populated_kb)
        assert any(e.name == "commons-lang-tpl" for e, _ in results)

    def test_query_by_text(self, populated_kb: Path):
        results = query_kb(query="encoding UTF-8", kb_dir=populated_kb)
        assert results[0][0].name == "maven-encoding"

    def test_query_limit(self, populated_kb: Path):
        results = query_kb(kb_dir=populated_kb, limit=2)
        assert len(results) <= 2

    def test_query_empty_kb(self, tmp_path: Path):
        results = query_kb(kb_dir=tmp_path / "empty-kb")
        assert results == []

    def test_query_nonexistent_dir(self, tmp_path: Path):
        results = query_kb(kb_dir=tmp_path / "does-not-exist")
        assert results == []

    def test_build_system_boosts_score(self, populated_kb: Path):
        results_with = query_kb(build_system="maven", query="encoding", kb_dir=populated_kb)
        results_without = query_kb(query="encoding", kb_dir=populated_kb)
        score_with = next(s for e, s in results_with if e.name == "maven-encoding")
        score_without = next(s for e, s in results_without if e.name == "maven-encoding")
        assert score_with > score_without

    def test_success_rate_boosts_score(self, kb_dir: Path):
        save_entry(TipEntry(
            name="popular-tip",
    
            description="A well-used tip about builds",
            tags=["maven"],
            build_systems=["maven"],
            times_used=10,
            success_rate=0.9,
        ), kb_dir)
        save_entry(TipEntry(
            name="new-tip",
    
            description="A fresh tip about builds",
            tags=["maven"],
            build_systems=["maven"],
            times_used=0,
            success_rate=0.0,
        ), kb_dir)
        results = query_kb(build_system="maven", kb_dir=kb_dir)
        scores = {e.name: s for e, s in results}
        assert scores["popular-tip"] > scores["new-tip"]


class TestQueryKBForPrompt:
    def test_returns_formatted_string(self, populated_kb: Path):
        text = query_kb_for_prompt(build_system="maven", kb_dir=populated_kb)
        assert "## Knowledge Base Entries" in text
        assert "maven-encoding" in text

    def test_returns_empty_for_no_results(self, tmp_path: Path):
        text = query_kb_for_prompt(build_system="cobol", kb_dir=tmp_path / "empty")
        assert text == ""

    def test_includes_tip_fields(self, populated_kb: Path):
        text = query_kb_for_prompt(tags=["maven", "encoding"], kb_dir=populated_kb)
        assert "Trigger:" in text
        assert "Solution:" in text

    def test_includes_trick_fields(self, populated_kb: Path):
        text = query_kb_for_prompt(tags=["osgi"], kb_dir=populated_kb)
        assert "Error pattern:" in text
        assert "Fix:" in text
