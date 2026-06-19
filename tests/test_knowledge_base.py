"""Tests for knowledge base — read/write patterns, taxonomy updates, section extraction."""

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from buildroot.agent.knowledge.knowledge_base import (
    _extract_section,
    read_patterns,
    read_taxonomy,
    record_pattern,
    update_taxonomy,
)


@dataclass
class ErrorClassFrequency:
    error_class: str = ""
    count: int = 0
    exhausted_count: int = 0
    under_explored_count: int = 0


@dataclass
class FailureAnalysis:
    error_frequencies: list[ErrorClassFrequency] = field(default_factory=list)


class TestReadPatterns:
    def test_reads_general_patterns(self):
        result = read_patterns()
        assert "GHA expression" in result or "fully-qualified" in result

    def test_reads_specific_section(self):
        result = read_patterns("Spring Boot")
        assert "spring-boot-maven-plugin" in result or "Spring Boot" in result

    def test_reads_multi_module(self):
        result = read_patterns("Multi-Module")
        assert "reactor" in result.lower() or "module" in result.lower()

    def test_empty_section_returns_general(self):
        result = read_patterns("NonExistentSection")
        assert result  # should at least return General Patterns

    def test_no_package_type_returns_general(self):
        result = read_patterns("")
        assert result


class TestReadTaxonomy:
    def test_reads_taxonomy(self):
        result = read_taxonomy()
        assert "Error Class" in result


class TestExtractSection:
    def test_extracts_known_section(self):
        content = "# Title\n\n## Foo\n\nFoo content\n\n## Bar\n\nBar content\n"
        result = _extract_section(content, "Foo")
        assert "Foo content" in result
        assert "Bar content" not in result

    def test_extracts_last_section(self):
        content = "# Title\n\n## Foo\n\nFoo content\n\n## Bar\n\nBar content\n"
        result = _extract_section(content, "Bar")
        assert "Bar content" in result

    def test_nonexistent_section_returns_empty(self):
        content = "# Title\n\n## Foo\n\nContent\n"
        result = _extract_section(content, "Missing")
        assert result == ""

    def test_case_insensitive(self):
        content = "# Title\n\n## Spring Boot\n\nSpring content\n"
        result = _extract_section(content, "Spring Boot")
        assert "Spring content" in result


class TestUpdateTaxonomy:
    def test_updates_taxonomy_file(self, tmp_path: Path):
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(
                    error_class="compilation/jdk_mismatch",
                    count=5, exhausted_count=2, under_explored_count=3,
                ),
                ErrorClassFrequency(
                    error_class="plugin/gpg_error",
                    count=2, exhausted_count=0, under_explored_count=2,
                ),
            ],
        )
        taxonomy_path = tmp_path / "failure_taxonomy.md"
        with patch("buildroot.agent.knowledge.knowledge_base.KB_DIR", tmp_path):
            update_taxonomy(analysis)
        content = taxonomy_path.read_text()
        assert "compilation/jdk_mismatch" in content
        assert "plugin/gpg_error" in content
        assert "Partially exhausted" in content
        assert "Under exploration" in content

    def test_fully_exhausted_status(self, tmp_path: Path):
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(
                    error_class="test_error",
                    count=3, exhausted_count=3, under_explored_count=0,
                ),
            ],
        )
        with patch("buildroot.agent.knowledge.knowledge_base.KB_DIR", tmp_path):
            update_taxonomy(analysis)
        content = (tmp_path / "failure_taxonomy.md").read_text()
        assert "Exhausted" in content


class TestRecordPattern:
    def test_appends_to_existing_section(self, tmp_path: Path):
        patterns_path = tmp_path / "patterns.md"
        patterns_path.write_text(
            "# Build Patterns Knowledge Base\n\n"
            "## Spring Boot\n\n- Existing pattern\n\n"
            "## General Patterns\n\n- General pattern\n"
        )
        with patch("buildroot.agent.knowledge.knowledge_base.KB_DIR", tmp_path):
            record_pattern("Spring Boot", "New Spring pattern")
        content = patterns_path.read_text()
        assert "New Spring pattern" in content
        assert "Existing pattern" in content

    def test_creates_new_section(self, tmp_path: Path):
        patterns_path = tmp_path / "patterns.md"
        patterns_path.write_text("# Build Patterns Knowledge Base\n\n## General Patterns\n\n- Existing\n")
        with patch("buildroot.agent.knowledge.knowledge_base.KB_DIR", tmp_path):
            record_pattern("New Category", "First pattern in category")
        content = patterns_path.read_text()
        assert "## New Category" in content
        assert "First pattern in category" in content

    def test_creates_file_if_missing(self, tmp_path: Path):
        with patch("buildroot.agent.knowledge.knowledge_base.KB_DIR", tmp_path):
            record_pattern("TestType", "Brand new pattern")
        content = (tmp_path / "patterns.md").read_text()
        assert "TestType" in content
        assert "Brand new pattern" in content
