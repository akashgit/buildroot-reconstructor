"""Tests for trust report generation."""

from pathlib import Path

import pytest

from buildroot.pipeline.models import (
    BuildrootSpec,
    GapEntry,
    GapReport,
    JdkSpec,
    PomData,
    Source,
)
from buildroot.trust.delta import DeltaReport, VariantResult
from buildroot.trust.report import generate_trust_report


def _make_spec(**overrides) -> BuildrootSpec:
    defaults = dict(
        pom_data=PomData(
            group_id="org.example",
            artifact_id="demo",
            version="1.0.0",
        ),
        jdk_spec=JdkSpec(version="17", distribution="temurin"),
        source_repo="https://github.com/example/demo",
        git_tag="v1.0.0",
        build_commands=["mvn clean install -B -DskipTests"],
        provenance_tier=1,
        provenance_provider="adoptium",
        provenance_verification=["gpg", "checksum", "sbom"],
        jdk_resolution_type="exact",
        jdk_requested_version="17",
    )
    defaults.update(overrides)
    return BuildrootSpec(**defaults)


def _make_delta(**overrides) -> DeltaReport:
    defaults = dict(
        coordinate="org.example:demo:1.0.0",
        exact=VariantResult(
            name="exact",
            base_image="docker.io/eclipse-temurin:17-jdk",
            jdk_version="17",
            jdk_source="ci_workflow",
        ),
        trusted=VariantResult(
            name="trusted",
            base_image="docker.io/eclipse-temurin:17-jdk",
            jdk_version="17",
            jdk_source="adoptium",
            provenance_tier=1,
        ),
        functional_equivalence="NOT_EVALUATED",
        recommendation="investigate",
    )
    defaults.update(overrides)
    return DeltaReport(**defaults)


class TestReportCreation:
    def test_report_file_is_created(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta()
        result = generate_trust_report(spec, delta, tmp_path)
        assert result.exists()
        assert result.name == "trust_report.md"

    def test_report_returns_correct_path(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta()
        result = generate_trust_report(spec, delta, tmp_path)
        assert result == tmp_path / "trust_report.md"


class TestReportSections:
    @pytest.fixture()
    def report_text(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        return (tmp_path / "trust_report.md").read_text()

    def test_has_header(self, report_text):
        assert "# Trust Report: org.example:demo:1.0.0" in report_text

    def test_header_has_timestamp(self, report_text):
        assert "**Generated**:" in report_text

    def test_header_has_version(self, report_text):
        assert "**buildroot-reconstructor**:" in report_text

    def test_has_executive_summary(self, report_text):
        assert "## Executive Summary" in report_text

    def test_has_how_to_use(self, report_text):
        assert "## How to Use These Outputs" in report_text

    def test_has_trust_assessment(self, report_text):
        assert "## Trust Assessment" in report_text

    def test_has_variant_comparison(self, report_text):
        assert "## Variant Comparison" in report_text

    def test_has_gaps_and_risks(self, report_text):
        assert "## Gaps & Risks" in report_text

    def test_has_security_checklist(self, report_text):
        assert "## Security Review Checklist" in report_text

    def test_has_next_steps(self, report_text):
        assert "## Next Steps" in report_text

    def test_all_eight_sections_present(self, report_text):
        sections = [
            "# Trust Report:",
            "## Executive Summary",
            "## How to Use These Outputs",
            "## Trust Assessment",
            "## Variant Comparison",
            "## Gaps & Risks",
            "## Security Review Checklist",
            "## Next Steps",
        ]
        for s in sections:
            assert s in report_text, f"Missing section: {s}"


class TestFileTable:
    def test_file_table_present(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()

        expected_files = [
            "Containerfile",
            "buildroot.json",
            "exact/Containerfile",
            "exact/buildroot.json",
            "exact/sbom.cdx.json",
            "trusted/Containerfile",
            "trusted/buildroot.json",
            "trusted/sbom.cdx.json",
            "delta_report.json",
        ]
        for f in expected_files:
            assert f"`{f}`" in text, f"Missing file in table: {f}"


class TestGapEntries:
    def test_gaps_displayed_when_present(self, tmp_path):
        spec = _make_spec(
            gaps=GapReport(entries=[
                GapEntry(
                    field="java_version",
                    status="inferred",
                    reason="No CI workflow found",
                    source=Source.INFERRED,
                ),
                GapEntry(
                    field="maven_version",
                    status="defaulted",
                    reason="No maven-wrapper.properties",
                    source=Source.DEFAULTED,
                ),
            ])
        )
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()

        assert "java_version" in text
        assert "maven_version" in text
        assert "No CI workflow found" in text
        assert "Risk Assessment" in text

    def test_no_gaps_message(self, tmp_path):
        spec = _make_spec(gaps=GapReport(entries=[]))
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "No gaps detected" in text


class TestSecurityChecklist:
    def test_checklist_items_present(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()

        checklist_items = [
            "Verify base image digest matches expected",
            "Review provenance tier and verification methods",
            "Check SBOM components against known CVE databases",
            "Verify source repository URL is legitimate",
            "Review build commands for injection risks",
            "Compare exact vs trusted variants for unexpected divergence",
            "Validate CycloneDX SBOM schema compliance",
        ]
        for item in checklist_items:
            assert item in text, f"Missing checklist item: {item}"

    def test_auto_satisfied_for_tier1_gpg(self, tmp_path):
        spec = _make_spec(
            provenance_tier=1,
            provenance_verification=["gpg", "checksum", "sbom"],
        )
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "Automatically satisfied" in text
        assert "GPG verification is already in place" in text


class TestFunctionalEquivalenceCases:
    def test_not_evaluated(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta(functional_equivalence="NOT_EVALUATED", recommendation="investigate")
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "NOT_EVALUATED" in text
        assert "buildroot agent" in text

    def test_identical(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta(
            functional_equivalence="IDENTICAL",
            recommendation="use_trusted",
        )
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "IDENTICAL" in text
        assert "use_trusted" in text
        assert "trusted variant is functionally equivalent" in text

    def test_equivalent(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta(
            functional_equivalence="EQUIVALENT",
            recommendation="use_trusted",
        )
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "EQUIVALENT" in text

    def test_divergent(self, tmp_path):
        spec = _make_spec()
        delta = _make_delta(
            functional_equivalence="DIVERGENT",
            recommendation="use_exact",
            classes_divergent=["com.example.Main", "com.example.Utils"],
        )
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "DIVERGENT" in text
        assert "use_exact" in text
        assert "divergent" in text.lower()
        assert "com.example.Main" in text


class TestTierDescriptions:
    def test_tier_1_description(self, tmp_path):
        spec = _make_spec(provenance_tier=1)
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "SLSA L3" in text

    def test_tier_2_description(self, tmp_path):
        spec = _make_spec(provenance_tier=2, provenance_provider="corretto")
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "Tier 2" in text
        assert "Signed" in text

    def test_tier_3_description(self, tmp_path):
        spec = _make_spec(
            provenance_tier=3,
            provenance_provider="jdk_archive",
            provenance_verification=[],
        )
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "Tier 3" in text
        assert "unverified" in text.lower()

    def test_no_tier_assigned(self, tmp_path):
        spec = _make_spec(provenance_tier=None)
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "No tier assigned" in text


class TestJdkSubstitution:
    def test_substitution_risks_shown(self, tmp_path):
        spec = _make_spec(
            jdk_resolution_type="substituted",
            jdk_requested_version="9",
            jdk_spec=JdkSpec(version="11", distribution="temurin"),
        )
        delta = _make_delta()
        generate_trust_report(spec, delta, tmp_path)
        text = (tmp_path / "trust_report.md").read_text()
        assert "JDK Substitution Risks" in text
        assert "API compatibility risk" in text
        assert "substituted" in text
