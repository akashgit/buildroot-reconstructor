"""Tests for delta report generation."""

from __future__ import annotations

from pathlib import Path

from buildroot.trust.delta import VariantResult, build_delta_report
from buildroot.utils.jar_comparator import (
    BytecodeResult,
    ComparisonReport,
    MetadataResult,
    StructuralResult,
    Verdict,
)


def _make_variant(
    name: str,
    jdk_version: str = "17",
    base_image: str = "docker.io/eclipse-temurin:17-jdk",
    jdk_source: str = "adoptium",
    provenance_tier: int | None = 1,
) -> VariantResult:
    return VariantResult(
        name=name,
        containerfile_path=Path(f"/out/{name}/Containerfile"),
        buildroot_json_path=Path(f"/out/{name}/buildroot.json"),
        base_image=base_image,
        jdk_version=jdk_version,
        jdk_source=jdk_source,
        provenance_tier=provenance_tier,
    )


def _make_comparison(verdict: str) -> ComparisonReport:
    report = ComparisonReport(coordinate="test:test:1.0", verdict=verdict)
    report.structural = StructuralResult(match=(verdict != Verdict.DIVERGENT))
    report.metadata = MetadataResult(match=(verdict != Verdict.DIVERGENT))
    report.bytecode = BytecodeResult(match=(verdict != Verdict.DIVERGENT))
    if verdict == Verdict.DIVERGENT:
        report.bytecode.classes_divergent = ["com/example/Foo.class"]
        report.metadata.manifest_diff_keys = ["Implementation-Version"]
    return report


class TestIdenticalVariants:
    def test_identical_no_comparison(self):
        exact = _make_variant("exact")
        trusted = _make_variant("trusted")
        report = build_delta_report(exact, trusted)
        assert report.functional_equivalence == "NOT_EVALUATED"
        assert report.recommendation == "investigate"
        assert report.version_diff == {}

    def test_identical_with_comparison(self):
        exact = _make_variant("exact")
        trusted = _make_variant("trusted")
        comparison = _make_comparison(Verdict.IDENTICAL)
        report = build_delta_report(exact, trusted, comparison)
        assert report.functional_equivalence == "IDENTICAL"
        assert report.recommendation == "use_trusted"

    def test_identical_no_provenance(self):
        exact = _make_variant("exact", provenance_tier=None)
        trusted = _make_variant("trusted", provenance_tier=None)
        comparison = _make_comparison(Verdict.IDENTICAL)
        report = build_delta_report(exact, trusted, comparison)
        assert report.functional_equivalence == "IDENTICAL"
        assert report.recommendation == "either"


class TestSubstitutedEquivalent:
    def test_jdk9_to_11_equivalent(self):
        exact = _make_variant(
            "exact", jdk_version="9", base_image="jdk9-image", jdk_source="archive",
            provenance_tier=None,
        )
        trusted = _make_variant(
            "trusted", jdk_version="11", base_image="docker.io/eclipse-temurin:11-jdk",
            jdk_source="adoptium", provenance_tier=1,
        )
        comparison = _make_comparison(Verdict.EQUIVALENT)
        report = build_delta_report(exact, trusted, comparison)
        assert report.functional_equivalence == "EQUIVALENT"
        assert report.recommendation == "use_trusted"
        assert "jdk_version" in report.version_diff
        assert report.version_diff["jdk_version"] == ("9", "11")
        assert "base_image" in report.version_diff


class TestDivergentVariants:
    def test_divergent_recommends_exact(self):
        exact = _make_variant("exact", jdk_version="9", provenance_tier=None)
        trusted = _make_variant("trusted", jdk_version="11", provenance_tier=1)
        comparison = _make_comparison(Verdict.DIVERGENT)
        report = build_delta_report(exact, trusted, comparison)
        assert report.functional_equivalence == "DIVERGENT"
        assert report.recommendation == "use_exact"
        assert report.structural_match is False
        assert len(report.classes_divergent) > 0


class TestNoComparison:
    def test_no_comparison_recommends_investigate(self):
        exact = _make_variant("exact")
        trusted = _make_variant("trusted")
        report = build_delta_report(exact, trusted)
        assert report.functional_equivalence == "NOT_EVALUATED"
        assert report.recommendation == "investigate"


class TestFailedComparison:
    def test_failed_recommends_investigate(self):
        exact = _make_variant("exact")
        trusted = _make_variant("trusted")
        comparison = _make_comparison(Verdict.FAILED)
        report = build_delta_report(exact, trusted, comparison)
        assert report.functional_equivalence == "FAILED"
        assert report.recommendation == "investigate"


class TestToDict:
    def test_serialization(self):
        exact = _make_variant("exact", jdk_version="9")
        trusted = _make_variant("trusted", jdk_version="11")
        report = build_delta_report(exact, trusted)
        d = report.to_dict()
        assert d["exact"]["name"] == "exact"
        assert d["trusted"]["name"] == "trusted"
        assert d["exact"]["jdk_version"] == "9"
        assert d["trusted"]["jdk_version"] == "11"
        assert "version_diff" in d
        assert "functional_equivalence" in d
        assert "recommendation" in d

    def test_version_diff_serialized_as_lists(self):
        exact = _make_variant("exact", jdk_version="9")
        trusted = _make_variant("trusted", jdk_version="11")
        report = build_delta_report(exact, trusted)
        d = report.to_dict()
        assert isinstance(d["version_diff"]["jdk_version"], list)
        assert d["version_diff"]["jdk_version"] == ["9", "11"]


class TestBaseImageNormalization:
    def test_library_prefix_not_false_diff(self):
        exact = _make_variant('exact', base_image='docker.io/library/eclipse-temurin:17-jdk')
        trusted = _make_variant('trusted', base_image='docker.io/eclipse-temurin:17-jdk')
        report = build_delta_report(exact, trusted)
        assert 'base_image' not in report.version_diff

    def test_real_diff_still_detected(self):
        exact = _make_variant('exact', base_image='docker.io/eclipse-temurin:17-jdk')
        trusted = _make_variant('trusted', base_image='registry.access.redhat.com/ubi9/openjdk-17')
        report = build_delta_report(exact, trusted)
        assert 'base_image' in report.version_diff


class TestToMarkdown:
    def test_markdown_contains_key_sections(self):
        exact = _make_variant("exact", jdk_version="9")
        trusted = _make_variant("trusted", jdk_version="11", provenance_tier=1)
        comparison = _make_comparison(Verdict.EQUIVALENT)
        report = build_delta_report(exact, trusted, comparison)
        report.coordinate = "org.example:test:1.0"
        md = report.to_markdown()
        assert "# Delta Report: org.example:test:1.0" in md
        assert "Variant Comparison" in md
        assert "Functional Equivalence" in md
        assert "Recommendation" in md
        assert "EQUIVALENT" in md
