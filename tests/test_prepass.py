"""Tests for the deterministic pre-pass module."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from buildroot.agent.prepass import (
    JDK_BYTECODE_MAJOR,
    PrePassFinding,
    PrePassFindings,
    _detect_build_system_from_findings,
    _extract_jdk_major,
    _extract_minor_version,
    _parse_manifest,
    _pom_data_to_dict,
    run_prepass,
)
from buildroot.pipeline.models import PomData


class TestPrePassFinding:
    def test_basic_construction(self):
        f = PrePassFinding(value="17", source="manifest", confidence="high", evidence="Build-Jdk-Spec: 17")
        assert f.value == "17"
        assert f.source == "manifest"
        assert f.confidence == "high"
        assert f.evidence == "Build-Jdk-Spec: 17"


class TestPrePassFindings:
    def test_empty_findings(self):
        findings = PrePassFindings()
        assert findings.source_repo is None
        assert findings.jar_path is None
        assert findings.attempted_but_failed == []
        assert findings.env_vars == {}

    def test_to_prompt_with_findings(self):
        findings = PrePassFindings(
            source_repo=PrePassFinding("https://github.com/foo/bar.git", "pom_xml", "high", "SCM URL"),
            jdk_version=PrePassFinding("17", "manifest", "high", "Build-Jdk-Spec: 17"),
            build_system=PrePassFinding("maven", "pom_xml", "high", "POM present"),
            bytecode_major_version=61,
            jar_entry_count=150,
        )
        prompt = findings.to_prompt()
        assert "source_repo" in prompt
        assert "https://github.com/foo/bar.git" in prompt
        assert "jdk_version" in prompt
        assert "17" in prompt
        assert "Bytecode" in prompt
        assert "Major version: 61" in prompt
        assert "JDK 17" in prompt
        assert "150" in prompt

    def test_to_prompt_empty(self):
        findings = PrePassFindings()
        prompt = findings.to_prompt()
        assert "Pre-Pass Findings" in prompt

    def test_to_prompt_with_attempted_but_failed(self):
        findings = PrePassFindings()
        findings.attempted_but_failed.append("POM fetch: 404")
        prompt = findings.to_prompt()
        assert "Attempted But Failed" in prompt
        assert "POM fetch: 404" in prompt

    def test_to_prompt_with_pom_data(self):
        findings = PrePassFindings(
            pom_data={
                "group_id": "org.apache.commons",
                "artifact_id": "commons-lang3",
                "version": "3.14.0",
                "modules": ["sub-module"],
                "build_plugins": [{"artifactId": "maven-compiler-plugin"}],
            }
        )
        prompt = findings.to_prompt()
        assert "commons-lang3" in prompt
        assert "maven-compiler-plugin" in prompt

    def test_to_prompt_with_jar_paths(self):
        findings = PrePassFindings(
            jar_path=Path("/tmp/foo.jar"),
            jar_unpacked_dir=Path("/tmp/unpacked"),
        )
        prompt = findings.to_prompt()
        assert "Artifact Paths" in prompt
        assert "/tmp/foo.jar" in prompt

    def test_to_prompt_with_manifest(self):
        findings = PrePassFindings(
            jar_manifest={"Build-Jdk-Spec": "17", "Created-By": "Apache Maven"},
        )
        prompt = findings.to_prompt()
        assert "JAR Manifest" in prompt
        assert "Build-Jdk-Spec: 17" in prompt

    def test_to_dict(self):
        findings = PrePassFindings(
            source_repo=PrePassFinding("https://github.com/foo/bar.git", "pom_xml", "high", "SCM"),
            bytecode_major_version=61,
            jar_entry_count=100,
        )
        d = findings.to_dict()
        assert "source_repo" in d
        assert d["source_repo"]["value"] == "https://github.com/foo/bar.git"
        assert d["bytecode_major_version"] == 61
        assert d["jar_entry_count"] == 100

    def test_to_dict_empty(self):
        findings = PrePassFindings()
        d = findings.to_dict()
        assert "source_repo" not in d
        assert "bytecode_major_version" not in d

    def test_to_dict_with_attempted_but_failed(self):
        findings = PrePassFindings()
        findings.attempted_but_failed.append("JAR download: timeout")
        d = findings.to_dict()
        assert "attempted_but_failed" in d
        assert "JAR download: timeout" in d["attempted_but_failed"]


class TestHelpers:
    def test_parse_manifest(self):
        text = "Manifest-Version: 1.0\nBuild-Jdk-Spec: 17\nCreated-By: Maven\n"
        result = _parse_manifest(text)
        assert result["Manifest-Version"] == "1.0"
        assert result["Build-Jdk-Spec"] == "17"

    def test_parse_manifest_continuation(self):
        text = "Long-Key: start\n of value\n"
        result = _parse_manifest(text)
        assert result["Long-Key"] == "startof value"

    def test_extract_jdk_major_modern(self):
        assert _extract_jdk_major("17") == "17"
        assert _extract_jdk_major("17.0.9") == "17"
        assert _extract_jdk_major("21") == "21"

    def test_extract_jdk_major_legacy(self):
        assert _extract_jdk_major("1.8") == "8"
        assert _extract_jdk_major("1.7.0_80") == "7"

    def test_extract_minor_version(self):
        assert _extract_minor_version("17.0.9 (Eclipse Adoptium)") == "17.0.9"
        assert _extract_minor_version("11.0.20+8") == "11.0.20"
        assert _extract_minor_version("Apache Maven") is None

    def test_jdk_bytecode_major_map(self):
        assert JDK_BYTECODE_MAJOR[52] == "8"
        assert JDK_BYTECODE_MAJOR[55] == "11"
        assert JDK_BYTECODE_MAJOR[61] == "17"
        assert JDK_BYTECODE_MAJOR[65] == "21"


class TestDetectBuildSystem:
    def test_maven_default(self):
        findings = PrePassFindings()
        pom = PomData()
        _detect_build_system_from_findings(findings, pom)
        assert findings.build_system is not None
        assert findings.build_system.value == "maven"

    def test_gradle_from_ci(self):
        findings = PrePassFindings(
            build_command=PrePassFinding("./gradlew build", "ci_workflow", "high", "CI"),
        )
        _detect_build_system_from_findings(findings, PomData())
        assert findings.build_system.value == "gradle"

    def test_ant_from_ci(self):
        findings = PrePassFindings(
            build_command=PrePassFinding("ant jar", "ci_workflow", "high", "CI"),
        )
        _detect_build_system_from_findings(findings, PomData())
        assert findings.build_system.value == "ant"

    def test_maven_wrapper_detected(self):
        findings = PrePassFindings(
            build_command=PrePassFinding("./mvnw clean install", "ci_workflow", "high", "CI"),
        )
        _detect_build_system_from_findings(findings, PomData())
        assert findings.build_system.value == "maven"
        assert findings.use_maven_wrapper is not None
        assert findings.use_maven_wrapper.value is True


class TestPomDataToDict:
    def test_basic(self):
        pom = PomData(group_id="org.example", artifact_id="test", version="1.0")
        d = _pom_data_to_dict(pom)
        assert d["group_id"] == "org.example"
        assert d["artifact_id"] == "test"
        assert d["version"] == "1.0"
