"""Tests that exercise scripts.verify_patch functions for coverage."""

from __future__ import annotations

from pathlib import Path

from scripts.verify_patch import (
    analyze_containerfile,
    check_disconnect_restored,
    extract_patched_files,
    load_containerfile_from_intake,
)

SAMPLE_CONTAINERFILE = """\
FROM registry.access.redhat.com/ubi8/openjdk-11:latest AS builder
WORKDIR /build
COPY patches/ /build/patches/
RUN jar xf /build/spring-orm-5.3.33.LIFERAY-PATCHED-1.jar
RUN sed -i 's/removed_disconnect/getCurrentSession().disconnect()/' SpringSessionSynchronization.java
RUN sed -i 's/old_util/new_util/' SessionFactoryUtils.java
RUN jar cf /build/spring-orm-5.3.33.LIFERAY-PATCHED-1.jar org/
"""


class TestCheckDisconnectRestored:
    def test_finds_disconnect_comment(self, tmp_path: Path) -> None:
        f = tmp_path / "source.java"
        f.write_text("// Eagerly disconnect the Session here\n", encoding="utf-8")
        assert check_disconnect_restored(f) is True

    def test_finds_disconnect_call(self, tmp_path: Path) -> None:
        f = tmp_path / "source.java"
        f.write_text("getCurrentSession().disconnect();\n", encoding="utf-8")
        assert check_disconnect_restored(f) is True

    def test_returns_false_when_missing(self, tmp_path: Path) -> None:
        f = tmp_path / "source.java"
        f.write_text("// nothing relevant here\n", encoding="utf-8")
        assert check_disconnect_restored(f) is False


class TestAnalyzeContainerfile:
    def test_basic_analysis(self, tmp_path: Path) -> None:
        f = tmp_path / "Containerfile"
        f.write_text(SAMPLE_CONTAINERFILE, encoding="utf-8")
        result = analyze_containerfile(f)
        assert result["has_from"] is True
        assert result["has_run"] is True
        assert result["has_workdir"] is True
        assert result["has_copy"] is True
        assert result["total_lines"] > 0
        assert "SessionFactoryUtils.java" in result["patched_files"]
        assert "SpringSessionSynchronization.java" in result["patched_files"]

    def test_empty_containerfile(self, tmp_path: Path) -> None:
        f = tmp_path / "Containerfile"
        f.write_text("# just a comment\n", encoding="utf-8")
        result = analyze_containerfile(f)
        assert result["has_from"] is False
        assert result["has_run"] is False


class TestExtractPatchedFiles:
    def test_extracts_java_files(self) -> None:
        content = "sed -i 's/foo/bar/' MyClass.java\nsed -i 's/x/y/' Other.java"
        result = extract_patched_files(content)
        assert "MyClass.java" in result
        assert "Other.java" in result

    def test_deduplicates(self) -> None:
        content = "sed -i 's/a/b/' File.java\nsed -i 's/c/d/' File.java"
        result = extract_patched_files(content)
        assert result == ["File.java"]

    def test_no_matches(self) -> None:
        result = extract_patched_files("COPY files/ /dest/")
        assert result == []


class TestLoadContainerfileFromIntake:
    def test_loads_containerfile(self, tmp_path: Path) -> None:
        import json

        intake = tmp_path / "intake.json"
        intake.write_text(
            json.dumps({"containerfile": "FROM ubuntu:22.04\nRUN echo hi"}),
            encoding="utf-8",
        )
        result = load_containerfile_from_intake(intake)
        assert "FROM ubuntu:22.04" in result
