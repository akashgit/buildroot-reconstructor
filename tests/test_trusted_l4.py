"""Tests for trusted L4 hardening — TRUSTED_EQUIVALENT verdict, digest pinning, checksum verification."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from buildroot.utils.jar_comparator import (
    BytecodeResult,
    ComparisonReport,
    EntryDiff,
    MetadataResult,
    StructuralResult,
    Verdict,
    _is_trusted_metadata_divergence,
    compare_jars,
    generate_summary,
)
from buildroot.trust.registry import MAVEN_CHECKSUMS, TrustedSourceRegistry
from buildroot.agent.evaluator import _find_unverified_downloads


def _create_jar(path: Path, entries: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


class TestTrustedEquivalentVerdict:
    def test_trusted_equivalent_when_bytecode_matches_metadata_diverges(self, tmp_path):
        """trusted=True with good bytecode + resource mismatch → TRUSTED_EQUIVALENT."""
        class_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\xaa" * 40
        orig_manifest = b"Manifest-Version: 1.0\nTool: ant-1.9\n"
        rebu_manifest = b"Manifest-Version: 1.0\nTool: ant-1.10\n"
        common_entries = {f"com/pkg/Class{i}.class": class_bytes for i in range(10)}
        orig_entries = {
            "META-INF/MANIFEST.MF": orig_manifest,
            "META-INF/maven/g/a/pom.xml": b"<pom>v1</pom>",
            **common_entries,
        }
        rebu_entries = {
            "META-INF/MANIFEST.MF": rebu_manifest,
            "META-INF/maven/g/a/pom.xml": b"<pom>v2</pom>",
            **common_entries,
        }
        orig = _create_jar(tmp_path / "orig.jar", orig_entries)
        rebu = _create_jar(tmp_path / "rebu.jar", rebu_entries)
        report = compare_jars(orig, rebu, coordinate="g:a:1.0", trusted=True)
        assert report.verdict == Verdict.TRUSTED_EQUIVALENT

    def test_trusted_wrong_bytecode_still_divergent(self, tmp_path):
        """Low bytecode ratio stays DIVERGENT even with trusted=True."""
        orig_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\x01" * 40
        rebu_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\x02" * 40
        orig_manifest = b"Manifest-Version: 1.0\nBuild-Jdk: 1.8.0_181\n"
        rebu_manifest = b"Manifest-Version: 1.0\nBuild-Jdk: 1.8.0_412\n"
        orig = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": orig_manifest,
            "com/Example.class": orig_bytes,
        })
        rebu = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": rebu_manifest,
            "com/Example.class": rebu_bytes,
        })
        report = compare_jars(orig, rebu, coordinate="g:a:1.0", trusted=True)
        assert report.verdict == Verdict.DIVERGENT

    def test_trusted_non_allowed_key_divergence(self, tmp_path):
        """Non-allowed key divergence stays DIVERGENT even with trusted=True."""
        class_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\xaa" * 40
        orig_manifest = b"Manifest-Version: 1.0\nBundle-Version: 1.0\n"
        rebu_manifest = b"Manifest-Version: 1.0\nBundle-Version: 2.0\n"
        orig = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": orig_manifest,
            "com/Example.class": class_bytes,
        })
        rebu = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": rebu_manifest,
            "com/Example.class": class_bytes,
        })
        report = compare_jars(orig, rebu, coordinate="g:a:1.0", trusted=True)
        assert report.verdict == Verdict.DIVERGENT

    def test_exact_build_no_relaxation(self, tmp_path):
        """trusted=False with resource mismatch stays DIVERGENT (regression guard)."""
        class_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\xaa" * 40
        orig_manifest = b"Manifest-Version: 1.0\nTool: ant-1.9\n"
        rebu_manifest = b"Manifest-Version: 1.0\nTool: ant-1.10\n"
        orig = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": orig_manifest,
            "com/Example.class": class_bytes,
            "META-INF/maven/g/a/pom.xml": b"<pom>v1</pom>",
        })
        rebu = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": rebu_manifest,
            "com/Example.class": class_bytes,
            "META-INF/maven/g/a/pom.xml": b"<pom>v2</pom>",
        })
        report = compare_jars(orig, rebu, coordinate="g:a:1.0", trusted=False)
        assert report.verdict == Verdict.DIVERGENT


class TestTrustedEquivalenceScoreWeights:
    def test_trusted_uses_85_10_5_weights(self):
        """Verify trusted=True uses 85/10/5 vs trusted=False uses 70/15/15."""
        report = ComparisonReport(
            verdict=Verdict.DIVERGENT,
            structural=StructuralResult(original_count=10, rebuilt_count=10, match=True),
            metadata=MetadataResult(
                manifest_match=False,
                manifest_diff_keys=["Build-Jdk"],
                resource_matches=5,
                match=False,
            ),
            bytecode=BytecodeResult(classes_compared=10, classes_identical=10, match=True),
        )
        score_default = report.equivalence_score(trusted=False)
        score_trusted = report.equivalence_score(trusted=True)
        assert score_trusted > score_default
        assert score_trusted > 0.90


class TestL4GateAcceptsTrustedEquivalent:
    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l4_gate_accepts_trusted_equivalent(self, mock_run, tmp_path):
        """Evaluator accepts TRUSTED_EQUIVALENT verdict and sets l4_match=True."""
        from buildroot.agent.evaluator import Evaluator
        from buildroot.agent.models import EvalResult

        class_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\xaa" * 40
        orig_manifest = b"Manifest-Version: 1.0\nTool: ant-1.9\n"
        rebu_manifest = b"Manifest-Version: 1.0\nTool: ant-1.10\n"
        common_entries = {f"com/pkg/Class{i}.class": class_bytes for i in range(10)}
        orig_jar = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": orig_manifest,
            "META-INF/maven/g/a/pom.xml": b"<pom>v1</pom>",
            **common_entries,
        })
        rebu_jar = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": rebu_manifest,
            "META-INF/maven/g/a/pom.xml": b"<pom>v2</pom>",
            **common_entries,
        })

        evaluator = Evaluator()
        result = EvalResult()

        with patch.object(evaluator, "_download_original_jar", return_value=orig_jar), \
             patch.object(evaluator, "_extract_rebuilt_jar", return_value=rebu_jar):
            evaluator._l4_match("test-tag", "g:a:1.0", result, jdk_version="8", trusted=True)

        assert result.l4_match is True
        assert result.comparison_verdict == Verdict.TRUSTED_EQUIVALENT


class TestNormalizeImageRefStripsDigest:
    def test_strips_sha256_digest(self):
        reg = TrustedSourceRegistry()
        normalized = reg._normalize_image_ref(
            "docker.io/eclipse-temurin:8-jdk@sha256:abc123def456"
        )
        assert "@sha256:" not in normalized
        assert normalized == "docker.io/eclipse-temurin:8-jdk"

    def test_digest_pinned_image_passes_trust_check(self):
        reg = TrustedSourceRegistry()
        trusted, source = reg.is_trusted_image(
            "docker.io/eclipse-temurin:8-jdk@sha256:abc123def456"
        )
        assert trusted is True
        assert source is not None
        assert source.provider == "adoptium"


class TestDownloadChecksumWarning:
    def test_download_without_checksum_flagged(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN wget -q https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz -O /tmp/maven.tar.gz && \\\n"
            "    tar xzf /tmp/maven.tar.gz -C /opt\n"
        )
        results = _find_unverified_downloads(cf)
        assert len(results) == 1

    def test_download_with_checksum_passes(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN wget -q https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz -O /tmp/maven.tar.gz && \\\n"
            '    echo "6eedd2cae3626d6ad3a5c9ee324bd265853d64297f07f033430755bd0e0c3a4b  /tmp/maven.tar.gz" | sha256sum -c - && \\\n'
            "    tar xzf /tmp/maven.tar.gz -C /opt\n"
        )
        results = _find_unverified_downloads(cf)
        assert len(results) == 0


class TestGenerateSummaryIncludesTrustedEquivalent:
    def test_trusted_equivalent_counted_as_reproducible(self):
        reports = [
            ComparisonReport(coordinate="g:a:1", verdict=Verdict.IDENTICAL),
            ComparisonReport(coordinate="g:b:1", verdict=Verdict.TRUSTED_EQUIVALENT),
            ComparisonReport(coordinate="g:c:1", verdict=Verdict.DIVERGENT),
        ]
        summary = generate_summary(reports)
        assert summary["total_packages"] == 3
        assert summary["verdicts"]["TRUSTED_EQUIVALENT"] == 1
        assert summary["reproducibility_score"] > 0.6
