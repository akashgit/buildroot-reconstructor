"""Tests for Containerfile generation from BuildrootSpec."""

from __future__ import annotations

import json
from pathlib import Path

from buildroot.generators.containerfile import ContainerfileGenerator, RUNNER_IMAGE_MAP
from buildroot.pipeline.models import (
    BuildrootSpec,
    CIData,
    Confidence,
    JdkSpec,
    PomData,
    Source,
)


def _minimal_spec(**overrides) -> BuildrootSpec:
    defaults = {
        "pom_data": PomData(
            group_id="org.example",
            artifact_id="demo",
            version="1.0.0",
        ),
        "jdk_spec": JdkSpec(
            version="17",
            distribution="temurin",
            base_image="eclipse-temurin:17-jdk",
            confidence=Confidence(
                level=Source.OBSERVED,
                reason="CI setup-java action",
            ),
            source_description="CI setup-java",
        ),
        "source_repo": "https://github.com/example/demo",
        "git_tag": "v1.0.0",
    }
    defaults.update(overrides)
    return BuildrootSpec(**defaults)


class TestJdkBaseTemplate:
    def test_jdk_base_from_instruction(self, tmp_path: Path):
        """Simple project -> Containerfile with FROM eclipse-temurin:17."""
        spec = _minimal_spec()
        gen = ContainerfileGenerator()

        cf_path, json_path = gen.generate(spec, tmp_path)

        content = cf_path.read_text()
        assert "FROM eclipse-temurin:17-jdk" in content
        assert "WORKDIR /build" in content
        assert "git clone" in content
        assert "mvn clean install" in content

    def test_uses_jdk_base_template(self, tmp_path: Path):
        """No system packages, no custom image -> jdk_base template."""
        spec = _minimal_spec()
        gen = ContainerfileGenerator()
        template = gen._select_template(spec)
        assert template == "jdk_base.j2"


class TestJdkOnUbuntuTemplate:
    def test_ubuntu_base_with_system_packages(self, tmp_path: Path):
        """Project with system packages -> FROM ubuntu:24.04."""
        spec = _minimal_spec(
            system_packages=["libxml2-dev", "libcurl4-openssl-dev"],
            ci_data=CIData(runner_os="ubuntu-22.04", ci_type="github"),
        )
        gen = ContainerfileGenerator()

        cf_path, _ = gen.generate(spec, tmp_path)

        content = cf_path.read_text()
        assert "FROM ubuntu:22.04" in content
        assert "libxml2-dev" in content
        assert "libcurl4-openssl-dev" in content

    def test_uses_jdk_on_ubuntu_template(self):
        spec = _minimal_spec(system_packages=["git"])
        gen = ContainerfileGenerator()
        template = gen._select_template(spec)
        assert template == "jdk_on_ubuntu.j2"


class TestCustomBaseTemplate:
    def test_custom_image_from_ci(self, tmp_path: Path):
        """Project with container image -> FROM springcloud/pipeline-base."""
        spec = _minimal_spec(
            base_image="springcloud/pipeline-base:latest",
        )
        gen = ContainerfileGenerator()

        cf_path, _ = gen.generate(spec, tmp_path)

        content = cf_path.read_text()
        assert "FROM springcloud/pipeline-base:latest" in content

    def test_uses_custom_base_template(self):
        spec = _minimal_spec(base_image="myorg/build-image:1.0")
        gen = ContainerfileGenerator()
        template = gen._select_template(spec)
        assert template == "custom_base.j2"


class TestBuildrootJsonOutput:
    def test_json_has_all_required_fields(self, tmp_path: Path):
        spec = _minimal_spec(maven_version="3.9.6")
        gen = ContainerfileGenerator()

        _, json_path = gen.generate(spec, tmp_path)
        data = json.loads(json_path.read_text())

        assert "source_repo" in data
        assert "git_tag" in data
        assert "jdk_version" in data
        assert "jdk_distribution" in data
        assert "maven_version" in data
        assert "build_command" in data
        assert "base_image" in data
        assert "system_packages" in data
        assert "dependencies" in data
        assert "gap_report" in data

        assert data["source_repo"] == "https://github.com/example/demo"
        assert data["jdk_version"]["value"] == "17"
        assert data["maven_version"]["value"] == "3.9.6"

    def test_json_build_command_defaulted(self, tmp_path: Path):
        spec = _minimal_spec()
        gen = ContainerfileGenerator()
        result = gen.generate_buildroot_json(spec)

        assert result["build_command"]["value"] == "mvn clean install -B -Dproject.build.outputTimestamp=2000-01-01T00:00:00Z"
        assert result["build_command"]["source"] == "defaulted"


class TestUbuntuLatestMapping:
    def test_ubuntu_latest_maps_to_24_04(self):
        assert RUNNER_IMAGE_MAP["ubuntu-latest"] == "24.04"

    def test_map_runner_to_ubuntu(self):
        assert ContainerfileGenerator.map_runner_to_ubuntu("ubuntu-latest") == "24.04"
        assert ContainerfileGenerator.map_runner_to_ubuntu("ubuntu-22.04") == "22.04"
        assert ContainerfileGenerator.map_runner_to_ubuntu("unknown") == ""

    def test_containerfile_uses_mapped_version(self, tmp_path: Path):
        spec = _minimal_spec(
            system_packages=["curl"],
            ci_data=CIData(runner_os="ubuntu-latest", ci_type="github"),
        )
        gen = ContainerfileGenerator()
        cf_path, _ = gen.generate(spec, tmp_path)

        content = cf_path.read_text()
        assert "FROM ubuntu:24.04" in content


class TestSourceAnnotationsInComments:
    def test_jdk_source_in_comments(self, tmp_path: Path):
        spec = _minimal_spec()
        gen = ContainerfileGenerator()
        cf_path, _ = gen.generate(spec, tmp_path)

        content = cf_path.read_text()
        assert "# JDK version: 17" in content
        assert "source:" in content.lower() or "Source:" in content
        assert "confidence:" in content.lower() or "Confidence:" in content

    def test_build_command_source_in_comments(self, tmp_path: Path):
        spec = _minimal_spec(
            build_commands=["mvn clean package -DskipTests"],
        )
        gen = ContainerfileGenerator()
        cf_path, _ = gen.generate(spec, tmp_path)

        content = cf_path.read_text()
        assert "mvn clean package -DskipTests" in content
        assert "# Build command:" in content

    def test_maven_version_source_in_comments(self, tmp_path: Path):
        spec = _minimal_spec(maven_version="3.9.6")
        gen = ContainerfileGenerator()
        cf_path, _ = gen.generate(spec, tmp_path)

        content = cf_path.read_text()
        assert "# Maven version: 3.9.6" in content
