"""Tests for CycloneDX SBOM generation."""

from __future__ import annotations

import json
from pathlib import Path

from buildroot.pipeline.models import BuildrootSpec, JdkSpec
from buildroot.trust.sbom import CYCLONEDX_SPEC_VERSION, TOOL_NAME, TOOL_VERSION, generate_sbom


def _make_spec(
    jdk_version: str = "17",
    base_image: str = "docker.io/eclipse-temurin:17-jdk",
    maven_version: str = "3.9.6",
    provenance_tier: int | None = 1,
    provenance_provider: str = "adoptium",
) -> BuildrootSpec:
    return BuildrootSpec(
        jdk_spec=JdkSpec(version=jdk_version, base_image=base_image),
        maven_version=maven_version,
        provenance_tier=provenance_tier,
        provenance_provider=provenance_provider,
    )


class TestSbomGenerated:
    def test_sbom_file_created(self, tmp_path):
        spec = _make_spec()
        result = generate_sbom(spec, "exact", tmp_path)
        assert result.exists()
        assert result.name == "sbom.cdx.json"

    def test_sbom_valid_json(self, tmp_path):
        spec = _make_spec()
        result = generate_sbom(spec, "exact", tmp_path)
        data = json.loads(result.read_text())
        assert data["bomFormat"] == "CycloneDX"
        assert data["specVersion"] == CYCLONEDX_SPEC_VERSION
        assert data["version"] == 1

    def test_sbom_creates_output_dir(self, tmp_path):
        spec = _make_spec()
        nested = tmp_path / "a" / "b"
        result = generate_sbom(spec, "exact", nested)
        assert result.exists()


class TestSbomContainsJdkComponent:
    def test_jdk_component_present(self, tmp_path):
        spec = _make_spec(jdk_version="21")
        result = generate_sbom(spec, "exact", tmp_path)
        data = json.loads(result.read_text())
        jdk_components = [
            c for c in data["components"]
            if c["name"].startswith("openjdk-")
        ]
        assert len(jdk_components) == 1
        assert jdk_components[0]["version"] == "21"
        assert jdk_components[0]["type"] == "library"


class TestSbomContainsBaseImage:
    def test_base_image_component(self, tmp_path):
        spec = _make_spec(base_image="docker.io/eclipse-temurin:17-jdk")
        result = generate_sbom(spec, "exact", tmp_path)
        data = json.loads(result.read_text())
        container_components = [
            c for c in data["components"] if c["type"] == "container"
        ]
        assert len(container_components) == 1
        assert container_components[0]["name"] == "docker.io/eclipse-temurin:17-jdk"


class TestSbomContainsMaven:
    def test_maven_component_present(self, tmp_path):
        spec = _make_spec(maven_version="3.9.6")
        result = generate_sbom(spec, "exact", tmp_path)
        data = json.loads(result.read_text())
        maven_components = [
            c for c in data["components"] if c["name"] == "apache-maven"
        ]
        assert len(maven_components) == 1
        assert maven_components[0]["version"] == "3.9.6"

    def test_no_maven_when_empty(self, tmp_path):
        spec = _make_spec(maven_version="")
        result = generate_sbom(spec, "exact", tmp_path)
        data = json.loads(result.read_text())
        maven_components = [
            c for c in data["components"] if c["name"] == "apache-maven"
        ]
        assert len(maven_components) == 0


class TestSbomProvenanceProperties:
    def test_tier_and_provider_in_properties(self, tmp_path):
        spec = _make_spec(provenance_tier=1, provenance_provider="adoptium")
        result = generate_sbom(spec, "trusted", tmp_path)
        data = json.loads(result.read_text())
        jdk_component = [
            c for c in data["components"] if c["name"].startswith("openjdk-")
        ][0]
        props = {p["name"]: p["value"] for p in jdk_component["properties"]}
        assert props["provenance_tier"] == "1"
        assert props["provenance_provider"] == "adoptium"

    def test_no_provenance_when_none(self, tmp_path):
        spec = _make_spec(provenance_tier=None, provenance_provider="")
        result = generate_sbom(spec, "exact", tmp_path)
        data = json.loads(result.read_text())
        jdk_component = [
            c for c in data["components"] if c["name"].startswith("openjdk-")
        ][0]
        assert jdk_component["properties"] == []


class TestSbomMetadata:
    def test_tool_metadata(self, tmp_path):
        spec = _make_spec()
        result = generate_sbom(spec, "exact", tmp_path)
        data = json.loads(result.read_text())
        tools = data["metadata"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == TOOL_NAME
        assert tools[0]["version"] == TOOL_VERSION

    def test_component_metadata(self, tmp_path):
        spec = _make_spec()
        result = generate_sbom(spec, "trusted", tmp_path)
        data = json.loads(result.read_text())
        assert data["metadata"]["component"]["name"] == "buildroot-trusted"

    def test_serial_number_unique(self, tmp_path):
        spec = _make_spec()
        r1 = generate_sbom(spec, "exact", tmp_path / "a")
        r2 = generate_sbom(spec, "exact", tmp_path / "b")
        d1 = json.loads(r1.read_text())
        d2 = json.loads(r2.read_text())
        assert d1["serialNumber"] != d2["serialNumber"]
