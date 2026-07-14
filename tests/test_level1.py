"""Level 1: Inference Correctness — verify the reconstruct pipeline produces valid specs."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import requests

from buildroot.pipeline.orchestrator import BuildrootOrchestrator

_SPEC_CACHE: dict[str, tuple] = {}

TEST_PACKAGES = [
    pytest.param(
        "org.springframework.boot", "spring-boot", "2.7.18",
        {"17", "8", "11"},
        False,  # Gradle-published flat POM on Maven Central, no parent
        id="spring-boot-2.7.18",
    ),
    pytest.param(
        "org.springframework.boot", "spring-boot-starter-web", "2.7.18",
        {"17", "8", "11"},
        False,  # Gradle-published flat POM
        id="spring-boot-starter-web-2.7.18",
    ),
    pytest.param(
        "org.springframework", "spring-core", "5.3.31",
        {"17", "8", "11"},
        False,  # Gradle-published flat POM
        id="spring-core-5.3.31",
    ),
    pytest.param(
        "org.springframework", "spring-context", "5.3.31",
        {"17", "8", "11"},
        False,  # Gradle-published flat POM
        id="spring-context-5.3.31",
    ),
    pytest.param(
        "org.springframework.cloud", "spring-cloud-config-server", "3.1.8",
        {"17", "8", "11"},
        True,  # Maven-built, has parent chain
        id="spring-cloud-config-server-3.1.8",
    ),
    pytest.param(
        "org.springframework.security", "spring-security-core", "5.8.9",
        {"17", "8", "11", "21", "25"},
        False,  # Gradle-published flat POM
        id="spring-security-core-5.8.9",
    ),
    pytest.param(
        "org.springframework.data", "spring-data-jpa", "2.7.18",
        {"17", "8", "11"},
        True,  # Maven-built, has parent chain
        id="spring-data-jpa-2.7.18",
    ),
    pytest.param(
        "org.thymeleaf", "thymeleaf-spring5", "3.0.15.RELEASE",
        {"8", "11", "17"},
        False,
        id="thymeleaf-spring5-3.0.15.RELEASE",
    ),
    pytest.param(
        "io.micrometer", "micrometer-core", "1.10.13",
        {"8", "11", "17", "21", "25"},
        False,  # Gradle-published flat POM
        id="micrometer-core-1.10.13",
    ),
    pytest.param(
        "org.apache.commons", "commons-lang3", "3.14.0",
        {"8", "11", "17", "21"},
        True,  # Maven-built, has parent chain
        id="commons-lang3-3.14.0",
    ),
]


@pytest.mark.integration
@pytest.mark.level1
@pytest.mark.parametrize(
    "group_id,artifact_id,version,valid_jdks,expect_parent_chain",
    TEST_PACKAGES,
)
class TestLevel1InferenceCorrectness:
    """Verify the full reconstruct pipeline produces correct BuildrootSpecs."""

    def _run_pipeline(self, group_id, artifact_id, version):
        cache_key = f"{group_id}:{artifact_id}:{version}"
        if cache_key in _SPEC_CACHE:
            return _SPEC_CACHE[cache_key]
        try:
            out = Path(tempfile.mkdtemp(prefix="buildroot-l1-"))
            orchestrator = BuildrootOrchestrator(skip_deps=True)
            spec = orchestrator.reconstruct(
                group_id,
                artifact_id,
                version,
                output_dir=str(out),
            )
            _SPEC_CACHE[cache_key] = (spec, out)
            return (spec, out)
        except requests.ConnectionError:
            pytest.skip("Maven Central unreachable")
        except requests.Timeout:
            pytest.skip("Maven Central request timed out")

    def test_jdk_version(
        self, group_id, artifact_id, version, valid_jdks, expect_parent_chain
    ):
        spec, _out = self._run_pipeline(group_id, artifact_id, version)
        jdk_ver = spec.jdk_spec.version
        assert jdk_ver, f"JDK version not set for {group_id}:{artifact_id}:{version}"
        normalized = jdk_ver.split(".")[0]
        if normalized.startswith("1"):
            normalized = jdk_ver.split(".")[1] if "." in jdk_ver else normalized
        assert normalized in valid_jdks, (
            f"JDK {jdk_ver} (normalized: {normalized}) not in expected set {valid_jdks} "
            f"for {group_id}:{artifact_id}:{version}"
        )

    def test_containerfile_generated(
        self, group_id, artifact_id, version, valid_jdks, expect_parent_chain
    ):
        _spec, out = self._run_pipeline(group_id, artifact_id, version)
        containerfile = out / "Containerfile"
        assert containerfile.exists(), "Containerfile was not generated"
        content = containerfile.read_text()
        assert len(content) > 0, "Containerfile is empty"
        assert "FROM" in content, "Containerfile missing FROM instruction"

    def test_buildroot_json_generated(
        self, group_id, artifact_id, version, valid_jdks, expect_parent_chain
    ):
        _spec, out = self._run_pipeline(group_id, artifact_id, version)
        json_path = out / "buildroot.json"
        assert json_path.exists(), "buildroot.json was not generated"
        data = json.loads(json_path.read_text())
        assert isinstance(data, dict), "buildroot.json is not a valid JSON object"
        assert "jdk_version" in data or "jdk_spec" in data or "base_image" in data, (
            "buildroot.json missing expected fields"
        )

    def test_parent_chain_resolved(
        self, group_id, artifact_id, version, valid_jdks, expect_parent_chain
    ):
        spec, _out = self._run_pipeline(group_id, artifact_id, version)
        if expect_parent_chain:
            assert len(spec.pom_data.parent_chain) >= 1, (
                f"Expected parent chain for {group_id}:{artifact_id}:{version} "
                f"but got {len(spec.pom_data.parent_chain)} entries"
            )

    def test_properties_resolved(
        self, group_id, artifact_id, version, valid_jdks, expect_parent_chain
    ):
        spec, _out = self._run_pipeline(group_id, artifact_id, version)
        assert len(spec.pom_data.properties) > 0, (
            f"No resolved properties for {group_id}:{artifact_id}:{version}"
        )

    def test_gap_report(
        self, group_id, artifact_id, version, valid_jdks, expect_parent_chain
    ):
        spec, _out = self._run_pipeline(group_id, artifact_id, version)
        assert spec.gaps is not None, "Gap report was not generated"

    def test_build_command_present(
        self, group_id, artifact_id, version, valid_jdks, expect_parent_chain
    ):
        spec, out = self._run_pipeline(group_id, artifact_id, version)
        containerfile = out / "Containerfile"
        content = containerfile.read_text()
        has_build_cmd = spec.build_commands or "mvn" in content or "gradle" in content
        assert has_build_cmd, (
            f"No build command found for {group_id}:{artifact_id}:{version}"
        )
