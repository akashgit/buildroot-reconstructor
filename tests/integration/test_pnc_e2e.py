"""End-to-end integration test for the PNC pipeline.

Tests the full prepass → spec assembly → Containerfile generation path
with NO mocks, hitting real Maven Central and real PNC staging.
"""

from __future__ import annotations

import json

import pytest

from buildroot.agent.prepass import run_prepass
from buildroot.generators.containerfile import ContainerfileGenerator
from buildroot.pipeline.models import BuildrootSpec, Confidence, JdkSpec, Source


@pytest.mark.vpn_required
class TestPncPipelineE2E:
    """Full pipeline test: prepass with PNC enabled → spec → Containerfile."""

    def test_pnc_miss_falls_back_to_manifest(self, tmp_path):
        """PNC staging has no build data for commons-lang3:3.14.0;
        pipeline should degrade gracefully and produce a standard Containerfile."""
        findings = run_prepass(
            "org.apache.commons:commons-lang3:3.14.0",
            tmp_path / "ws",
            enable_pnc=True,
        )

        # PNC returned nothing
        assert findings.pnc_build_id is None
        assert findings.pnc_builder_image is None
        assert any("PNC lookup" in msg for msg in findings.attempted_but_failed)

        # Fell back to JAR manifest signals
        assert findings.jdk_version is not None
        assert findings.jdk_version.source == "manifest"
        assert findings.jar_path is not None

        # Assemble spec (mirrors meta_agent.py logic for non-PNC path)
        spec = BuildrootSpec(
            source_repo=findings.source_repo.value if findings.source_repo else "",
            git_tag=findings.git_tag.value if findings.git_tag else "",
            jdk_spec=JdkSpec(
                version=findings.jdk_version.value,
                distribution=(
                    findings.jdk_distribution.value
                    if findings.jdk_distribution
                    else "temurin"
                ),
                confidence=Confidence(
                    level=Source.OBSERVED, reason="manifest"
                ),
            ),
            maven_version=(
                findings.maven_version.value if findings.maven_version else ""
            ),
            build_commands=["mvn clean install -B -DskipTests"],
            build_system="maven",
        )

        # Generate Containerfile via real template selection + rendering
        gen = ContainerfileGenerator()
        cf_path, json_path = gen.generate(spec, tmp_path / "output")
        containerfile = cf_path.read_text()

        # Standard (non-PNC) Containerfile
        assert "FROM" in containerfile
        assert "quay.io/rh-newcastle" not in containerfile
        assert "mvn clean install" in containerfile

        # buildroot.json present and has no PNC provenance
        assert json_path.exists()
        buildroot_json = json.loads(json_path.read_text())
        prov = buildroot_json.get("provenance", {})
        assert prov.get("provider") != "pnc"


class TestPncHitPath:
    """Verify that when PNC data IS available, spec assembly
    selects the PNC template and produces the correct Containerfile."""

    def test_pnc_hit_produces_pnc_containerfile(self, tmp_path):
        """When PNC data is available, pipeline selects pnc_base.j2 template."""
        from buildroot.utils.pnc_api import PncBuildInfo

        pnc_info = PncBuildInfo(
            build_id="12345",
            builder_image="quay.io/rh-newcastle/builder-rhel-7-j8-mvn3.6.3@sha256:abc123",
            jdk_version="8",
            maven_version="3.6.3",
            rhel_version="7",
            scm_external_url="https://github.com/apache/commons-lang.git",
            scm_revision="rel/commons-lang-3.12.0",
        )

        spec = BuildrootSpec(
            source_repo=pnc_info.scm_external_url,
            git_tag=pnc_info.scm_revision,
            jdk_spec=JdkSpec(
                version="8",
                confidence=Confidence(
                    level=Source.OBSERVED, reason="pnc_api"
                ),
            ),
            build_commands=["mvn clean install -B -DskipTests"],
            build_system="maven",
            provenance_provider="pnc",
            pnc_builder_image=pnc_info.builder_image,
            pnc_build_id=pnc_info.build_id,
            rhel_version=pnc_info.rhel_version,
        )

        gen = ContainerfileGenerator()
        cf_path, json_path = gen.generate(spec, tmp_path / "output")
        containerfile = cf_path.read_text()

        assert "FROM quay.io/rh-newcastle/" in containerfile
        assert "yum install" in containerfile
        assert "apt-get" not in containerfile
        assert "12345" in containerfile
        assert json_path.exists()
