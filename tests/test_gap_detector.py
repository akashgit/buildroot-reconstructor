"""Tests for gap detection and confidence reporting."""

from __future__ import annotations

from buildroot.pipeline.gap_detector import GapDetector
from buildroot.pipeline.models import (
    BuildrootSpec,
    CIData,
    Confidence,
    JdkSpec,
    PomData,
    Source,
)


def _spec_all_observed() -> BuildrootSpec:
    return BuildrootSpec(
        pom_data=PomData(
            group_id="org.example",
            artifact_id="demo",
            version="1.0.0",
        ),
        ci_data=CIData(
            runner_os="ubuntu-22.04",
            ci_type="github",
        ),
        jdk_spec=JdkSpec(
            version="17",
            distribution="temurin",
            base_image="eclipse-temurin:17",
            confidence=Confidence(
                level=Source.OBSERVED,
                reason="CI setup-java action",
            ),
        ),
        maven_version="3.9.6",
        build_commands=["mvn clean install -B"],
        source_repo="https://github.com/example/demo",
        git_tag="v1.0.0",
    )


def _spec_mixed() -> BuildrootSpec:
    return BuildrootSpec(
        pom_data=PomData(
            group_id="org.example",
            artifact_id="demo",
            version="1.0.0",
        ),
        ci_data=CIData(
            runner_os="ubuntu-latest",
            ci_type="github",
        ),
        jdk_spec=JdkSpec(
            version="17",
            distribution="temurin",
            base_image="eclipse-temurin:17",
            confidence=Confidence(
                level=Source.INFERRED,
                reason="JDK version from maven.compiler.release property",
            ),
        ),
        maven_version="3.9.6",
        build_commands=["mvn clean install"],
        source_repo="https://github.com/example/demo",
        git_tag="v1.0.0",
    )


def _spec_mostly_defaulted() -> BuildrootSpec:
    return BuildrootSpec(
        pom_data=PomData(
            group_id="org.example",
            artifact_id="demo",
            version="1.0.0",
            properties={"some.prop": "${unresolved.ref}"},
        ),
        jdk_spec=JdkSpec(
            version="17",
            distribution="temurin",
            base_image="eclipse-temurin:17",
            confidence=Confidence(
                level=Source.DEFAULTED,
                reason="No JDK version signal found; defaulting to JDK 17",
            ),
        ),
        source_repo="https://github.com/example/demo",
        git_tag="v1.0.0",
    )


class TestAllObservedHighConfidence:
    def test_no_gaps_when_all_observed(self):
        """Everything OBSERVED -> HIGH confidence, no gap entries."""
        spec = _spec_all_observed()
        detector = GapDetector()
        report = detector.analyze(spec)

        assert len(report.entries) == 0
        assert detector.compute_overall_confidence(report) == "HIGH"


class TestMixedSourcesMedium:
    def test_inferred_jdk_produces_medium(self):
        """Mix of OBSERVED and INFERRED -> MEDIUM confidence."""
        spec = _spec_mixed()
        detector = GapDetector()
        report = detector.analyze(spec)

        assert detector.compute_overall_confidence(report) == "MEDIUM"
        fields = [e.field for e in report.entries]
        assert "jdk_version" in fields

    def test_ubuntu_latest_flagged(self):
        """ubuntu-latest in runner_os should produce a gap entry."""
        spec = _spec_mixed()
        detector = GapDetector()
        report = detector.analyze(spec)

        fields = [e.field for e in report.entries]
        assert "runner_os" in fields
        runner_entry = next(e for e in report.entries if e.field == "runner_os")
        assert "ubuntu-latest" in runner_entry.reason


class TestMostlyDefaultedLow:
    def test_mostly_defaulted_is_low(self):
        """Mostly DEFAULTED -> LOW confidence."""
        spec = _spec_mostly_defaulted()
        detector = GapDetector()
        report = detector.analyze(spec)

        assert detector.compute_overall_confidence(report) == "LOW"

    def test_missing_maven_version_flagged(self):
        spec = _spec_mostly_defaulted()
        detector = GapDetector()
        report = detector.analyze(spec)

        fields = [e.field for e in report.entries]
        assert "maven_version" in fields

    def test_missing_build_command_flagged(self):
        spec = _spec_mostly_defaulted()
        detector = GapDetector()
        report = detector.analyze(spec)

        fields = [e.field for e in report.entries]
        assert "build_command" in fields


class TestUbuntuLatestGap:
    def test_flags_ubuntu_latest_mapping(self):
        spec = BuildrootSpec(
            pom_data=PomData(),
            ci_data=CIData(runner_os="ubuntu-latest", ci_type="github"),
            jdk_spec=JdkSpec(
                version="17",
                confidence=Confidence(
                    level=Source.OBSERVED,
                    reason="CI setup-java",
                ),
            ),
            maven_version="3.9.6",
            build_commands=["mvn clean install"],
        )
        detector = GapDetector()
        report = detector.analyze(spec)

        runner_entries = [e for e in report.entries if e.field == "runner_os"]
        assert len(runner_entries) == 1
        assert "stale" in runner_entries[0].reason

    def test_pinned_ubuntu_no_gap(self):
        spec = BuildrootSpec(
            pom_data=PomData(),
            ci_data=CIData(runner_os="ubuntu-22.04", ci_type="github"),
            jdk_spec=JdkSpec(
                version="17",
                confidence=Confidence(
                    level=Source.OBSERVED,
                    reason="CI setup-java",
                ),
            ),
            maven_version="3.9.6",
            build_commands=["mvn clean install"],
        )
        detector = GapDetector()
        report = detector.analyze(spec)

        runner_entries = [e for e in report.entries if e.field == "runner_os"]
        assert len(runner_entries) == 0


class TestUnresolvedPropertiesGap:
    def test_flags_unresolved_props(self):
        spec = BuildrootSpec(
            pom_data=PomData(
                properties={
                    "resolved.prop": "1.0.0",
                    "broken.prop": "${some.missing.ref}",
                }
            ),
            ci_data=CIData(ci_type="github"),
            jdk_spec=JdkSpec(
                version="17",
                confidence=Confidence(
                    level=Source.OBSERVED,
                    reason="CI setup-java",
                ),
            ),
            maven_version="3.9.6",
            build_commands=["mvn clean install"],
        )
        detector = GapDetector()
        report = detector.analyze(spec)

        prop_entries = [
            e for e in report.entries if e.field.startswith("property:")
        ]
        assert len(prop_entries) == 1
        assert "broken.prop" in prop_entries[0].field
        assert "${some.missing.ref}" in prop_entries[0].reason


class TestHumanReadableFormat:
    def test_format_contains_table_structure(self):
        spec = _spec_mixed()
        detector = GapDetector()
        report = detector.analyze(spec)
        output = detector.format_human_readable(report)

        assert "GAP REPORT" in output
        assert "Field" in output
        assert "Status" in output
        assert "Confidence:" in output

    def test_empty_report_output(self):
        spec = _spec_all_observed()
        detector = GapDetector()
        report = detector.analyze(spec)
        output = detector.format_human_readable(report)

        assert "No gaps detected" in output

    def test_machine_readable_has_required_fields(self):
        spec = _spec_mixed()
        detector = GapDetector()
        report = detector.analyze(spec)
        result = detector.format_machine_readable(report)

        assert "entries" in result
        assert "overall_confidence" in result
        assert "summary" in result
        assert isinstance(result["entries"], list)
