"""Tests for accuracy scorer with synthetic buildroot data."""

from __future__ import annotations

from buildroot.parsers.pnc_containerfile import PNCGroundTruth
from buildroot.utils.accuracy_scorer import (
    AccuracyReport,
    score_accuracy,
    _normalize_jdk_version,
    _normalize_vendor,
    _normalize_scm_url,
)


def _j8_maven_truth() -> PNCGroundTruth:
    return PNCGroundTruth(
        jdk_major_version="8",
        jdk_vendor="openjdk",
        build_tool="maven",
        build_tool_version="3.3.9",
        os_family="rhel",
        os_version="7",
        image_name="builder-rhel-7-j8-mvn3.3.9",
    )


def _j11_maven_truth() -> PNCGroundTruth:
    return PNCGroundTruth(
        jdk_major_version="11",
        jdk_vendor="openjdk",
        build_tool="maven",
        build_tool_version="3.6.3",
        os_family="rhel",
        os_version="7",
        image_name="builder-rhel-7-j11-mvn3.6.3",
    )


def _perfect_buildroot_j8() -> dict:
    return {
        "source_repo": "https://github.com/apache/commons-lang",
        "jdk_version": {"value": "8", "source": "observed"},
        "jdk_distribution": {"value": "temurin", "source": "observed"},
        "maven_version": {"value": "3.3.9", "source": "observed"},
        "build_command": {"value": "mvn clean install -B", "source": "defaulted"},
        "base_image": {"value": "eclipse-temurin:8-jdk", "source": "observed"},
    }


def _partial_buildroot_j11() -> dict:
    return {
        "source_repo": "https://github.com/FasterXML/jackson-core",
        "jdk_version": {"value": "11", "source": "observed"},
        "jdk_distribution": {"value": "temurin", "source": "inferred"},
        "maven_version": {"value": "system-default", "source": "defaulted"},
        "build_command": {"value": "mvn clean install -B -DskipTests", "source": "defaulted"},
        "base_image": {"value": "eclipse-temurin:11-jdk", "source": "observed"},
    }


class TestNormalization:
    def test_jdk_version_1_8(self):
        assert _normalize_jdk_version("1.8") == "8"

    def test_jdk_version_11(self):
        assert _normalize_jdk_version("11") == "11"

    def test_jdk_version_17_0_2(self):
        assert _normalize_jdk_version("17.0.2") == "17"

    def test_vendor_temurin_is_openjdk(self):
        assert _normalize_vendor("temurin") == "openjdk"

    def test_vendor_openjdk(self):
        assert _normalize_vendor("openjdk") == "openjdk"

    def test_vendor_oracle(self):
        assert _normalize_vendor("Oracle") == "oracle"

    def test_vendor_corretto(self):
        assert _normalize_vendor("corretto") == "openjdk"

    def test_scm_url_normalization(self):
        assert _normalize_scm_url("https://github.com/apache/commons-lang.git") == \
               _normalize_scm_url("https://github.com/apache/commons-lang")

    def test_scm_url_trailing_slash(self):
        assert _normalize_scm_url("https://github.com/apache/commons-lang/") == \
               _normalize_scm_url("https://github.com/apache/commons-lang")


class TestScoringDimensions:
    def test_perfect_jdk_match(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        jdk_dim = next(d for d in report.dimensions if d.dimension == "jdk_major_version")
        assert jdk_dim.score == 1.0

    def test_jdk_mismatch(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        buildroot["jdk_version"]["value"] = "11"
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        jdk_dim = next(d for d in report.dimensions if d.dimension == "jdk_major_version")
        assert jdk_dim.score == 0.0

    def test_vendor_match_normalized(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        vendor_dim = next(d for d in report.dimensions if d.dimension == "jdk_vendor")
        assert vendor_dim.score == 1.0

    def test_build_tool_match(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        tool_dim = next(d for d in report.dimensions if d.dimension == "build_tool")
        assert tool_dim.score == 1.0

    def test_build_tool_version_exact(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        ver_dim = next(d for d in report.dimensions if d.dimension == "build_tool_version")
        assert ver_dim.score == 1.0

    def test_build_tool_version_major_only(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        buildroot["maven_version"]["value"] = "3.9.6"
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        ver_dim = next(d for d in report.dimensions if d.dimension == "build_tool_version")
        assert ver_dim.score == 0.5

    def test_build_tool_version_system_default(self):
        truth = _j11_maven_truth()
        buildroot = _partial_buildroot_j11()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        ver_dim = next(d for d in report.dimensions if d.dimension == "build_tool_version")
        assert ver_dim.score == 0.0

    def test_os_family_mismatch(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        os_dim = next(d for d in report.dimensions if d.dimension == "os_family")
        assert os_dim.score == 0.0
        assert os_dim.actual == "unknown"

    def test_scm_no_ground_truth(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        scm_dim = next(d for d in report.dimensions if d.dimension == "scm_url")
        assert scm_dim.score == 0.5


class TestAggregateScore:
    def test_perfect_score_structure(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "org.example:test:1.0")

        assert isinstance(report, AccuracyReport)
        assert report.coordinate == "org.example:test:1.0"
        assert len(report.dimensions) == 6
        assert 0.0 <= report.aggregate_score <= 1.0

    def test_aggregate_is_weighted_sum(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        manual_sum = sum(d.score * d.weight for d in report.dimensions)
        assert abs(report.aggregate_score - manual_sum) < 1e-6

    def test_to_dict_roundtrip(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        d = report.to_dict()
        assert "coordinate" in d
        assert "aggregate_score" in d
        assert "dimensions" in d
        assert len(d["dimensions"]) == 6
        for dim in d["dimensions"]:
            assert "dimension" in dim
            assert "weight" in dim
            assert "score" in dim
            assert "weighted_score" in dim
            assert "expected" in dim
            assert "actual" in dim

    def test_weights_sum_to_one(self):
        truth = _j8_maven_truth()
        buildroot = _perfect_buildroot_j8()
        report = score_accuracy(truth, buildroot, "test:test:1.0")

        total_weight = sum(d.weight for d in report.dimensions)
        assert abs(total_weight - 1.0) < 1e-6
