"""Tests for the BuildrootOrchestrator pipeline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from buildroot.pipeline.models import (
    Annotated,
    BuildrootSpec,
    CIData,
    Confidence,
    DependencyNode,
    GapReport,
    JdkSpec,
    PomData,
    Source,
)
from buildroot.pipeline.orchestrator import BuildrootOrchestrator, parse_gav


class TestParseGAV:
    def test_valid_coordinate(self):
        g, a, v = parse_gav("org.springframework.boot:spring-boot:2.7.18")
        assert g == "org.springframework.boot"
        assert a == "spring-boot"
        assert v == "2.7.18"

    def test_invalid_coordinate_too_few_parts(self):
        with pytest.raises(ValueError, match="Invalid coordinate"):
            parse_gav("org.springframework.boot:spring-boot")

    def test_invalid_coordinate_too_many_parts(self):
        with pytest.raises(ValueError, match="Invalid coordinate"):
            parse_gav("org.springframework.boot:spring-boot:2.7.18:jar")

    def test_empty_coordinate(self):
        with pytest.raises(ValueError, match="Invalid coordinate"):
            parse_gav("")


class TestReconstructMockPipeline:
    @patch("buildroot.pipeline.orchestrator.fetch_pom")
    @patch("buildroot.pipeline.orchestrator.discover_repo_from_pom")
    def test_reconstruct_mock_pipeline(self, mock_discover, mock_fetch):
        mock_fetch.return_value = """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>test-app</artifactId>
    <version>1.0.0</version>
    <properties>
        <maven.compiler.source>11</maven.compiler.source>
        <maven.compiler.target>11</maven.compiler.target>
    </properties>
</project>"""
        mock_discover.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = BuildrootOrchestrator(skip_deps=True)
            spec = orchestrator.reconstruct(
                "com.example", "test-app", "1.0.0",
                output_dir=tmpdir,
            )

            assert spec.pom_data.group_id == "com.example"
            assert spec.pom_data.artifact_id == "test-app"
            assert spec.pom_data.version == "1.0.0"
            assert spec.jdk_spec.version
            assert spec.git_tag == "v1.0.0"

            containerfile = Path(tmpdir) / "Containerfile"
            assert containerfile.exists()

            buildroot_json = Path(tmpdir) / "buildroot.json"
            assert buildroot_json.exists()
            data = json.loads(buildroot_json.read_text())
            assert "jdk_version" in data
            assert "gap_report" in data

    @patch("buildroot.pipeline.orchestrator.fetch_pom")
    @patch("buildroot.pipeline.orchestrator.discover_repo_from_pom")
    def test_reconstruct_with_repo_url(self, mock_discover, mock_fetch):
        mock_fetch.return_value = """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>test-app</artifactId>
    <version>1.0.0</version>
</project>"""
        mock_discover.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = BuildrootOrchestrator(skip_deps=True)
            spec = orchestrator.reconstruct(
                "com.example", "test-app", "1.0.0",
                repo_url="https://github.com/example/test-app",
                output_dir=tmpdir,
            )
            assert spec.source_repo == "https://github.com/example/test-app"


class TestInspect:
    @patch("buildroot.pipeline.orchestrator.fetch_pom")
    @patch("buildroot.pipeline.orchestrator.discover_repo_from_pom")
    def test_inspect_returns_all_data(self, mock_discover, mock_fetch):
        mock_fetch.return_value = """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>test-app</artifactId>
    <version>1.0.0</version>
    <properties>
        <maven.compiler.source>17</maven.compiler.source>
    </properties>
</project>"""
        mock_discover.return_value = None

        orchestrator = BuildrootOrchestrator()
        result = orchestrator.inspect("com.example", "test-app", "1.0.0")

        assert "pom_data" in result
        assert "properties" in result
        assert "jdk_spec" in result
        assert "parent_chain" in result
        assert "coordinate" in result

        assert result["pom_data"]["groupId"] == "com.example"
        assert result["jdk_spec"]["version"] == "17"


class TestVerify:
    def test_verify_jdk_match(self):
        orchestrator = BuildrootOrchestrator()

        with tempfile.TemporaryDirectory() as tmpdir:
            buildroot_data = {
                "jdk_version": {"value": "17", "source": "inferred"},
            }
            json_path = Path(tmpdir) / "buildroot.json"
            json_path.write_text(json.dumps(buildroot_data))

            with patch.object(orchestrator, "_read_jar_build_jdk", return_value="17"):
                result = orchestrator.verify(
                    "com.example", "test-app", "1.0.0",
                    output_dir=tmpdir,
                )

            jdk_check = next(c for c in result["checks"] if c["name"] == "jdk_version")
            assert jdk_check["status"] == "MATCH"
            assert jdk_check["inferred"] == "17"
            assert jdk_check["manifest"] == "17"

    def test_verify_jdk_mismatch(self):
        orchestrator = BuildrootOrchestrator()

        with tempfile.TemporaryDirectory() as tmpdir:
            buildroot_data = {
                "jdk_version": {"value": "11", "source": "inferred"},
            }
            json_path = Path(tmpdir) / "buildroot.json"
            json_path.write_text(json.dumps(buildroot_data))

            with patch.object(orchestrator, "_read_jar_build_jdk", return_value="17"):
                result = orchestrator.verify(
                    "com.example", "test-app", "1.0.0",
                    output_dir=tmpdir,
                )

            jdk_check = next(c for c in result["checks"] if c["name"] == "jdk_version")
            assert jdk_check["status"] == "MISMATCH"

    def test_verify_no_buildroot_json(self):
        orchestrator = BuildrootOrchestrator()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(orchestrator, "_read_jar_build_jdk", return_value="17"):
                result = orchestrator.verify(
                    "com.example", "test-app", "1.0.0",
                    output_dir=tmpdir,
                )
            jdk_check = next(c for c in result["checks"] if c["name"] == "jdk_version")
            assert jdk_check["status"] == "SKIP"


class TestJdkVersionMatch:
    def test_exact_match(self):
        o = BuildrootOrchestrator()
        assert o._jdk_versions_match("17", "17") is True

    def test_major_match(self):
        o = BuildrootOrchestrator()
        assert o._jdk_versions_match("17", "17.0.2") is True

    def test_legacy_format(self):
        o = BuildrootOrchestrator()
        assert o._jdk_versions_match("8", "1.8") is True

    def test_mismatch(self):
        o = BuildrootOrchestrator()
        assert o._jdk_versions_match("11", "17") is False


@pytest.mark.integration
class TestReconstructIntegration:
    def test_reconstruct_spring_boot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = BuildrootOrchestrator(skip_deps=True)
            spec = orchestrator.reconstruct(
                "org.springframework.boot", "spring-boot", "2.7.18",
                output_dir=tmpdir,
            )

            assert spec.pom_data.group_id == "org.springframework.boot"
            assert spec.pom_data.artifact_id == "spring-boot"
            assert spec.jdk_spec.version

            containerfile = Path(tmpdir) / "Containerfile"
            assert containerfile.exists()

            buildroot_json = Path(tmpdir) / "buildroot.json"
            assert buildroot_json.exists()
