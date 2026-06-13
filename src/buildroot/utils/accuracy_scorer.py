"""Score reconstruction accuracy against PNC ground truth."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from buildroot.parsers.pnc_containerfile import PNCGroundTruth

logger = logging.getLogger(__name__)

DIMENSION_WEIGHTS = {
    "jdk_major_version": 0.25,
    "jdk_vendor": 0.10,
    "build_tool": 0.25,
    "build_tool_version": 0.15,
    "os_family": 0.10,
    "scm_url": 0.15,
}


@dataclass
class DimensionScore:
    """Score for a single comparison dimension."""

    dimension: str
    weight: float
    score: float
    expected: str
    actual: str
    detail: str = ""


@dataclass
class AccuracyReport:
    """Full accuracy comparison report."""

    coordinate: str = ""
    image_name: str = ""
    dimensions: list[DimensionScore] = field(default_factory=list)
    aggregate_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "image_name": self.image_name,
            "aggregate_score": round(self.aggregate_score, 4),
            "dimensions": [
                {
                    "dimension": d.dimension,
                    "weight": d.weight,
                    "score": round(d.score, 4),
                    "weighted_score": round(d.score * d.weight, 4),
                    "expected": d.expected,
                    "actual": d.actual,
                    "detail": d.detail,
                }
                for d in self.dimensions
            ],
        }


def _normalize_jdk_version(version: str) -> str:
    """Normalize JDK version to major number only."""
    v = version.strip()
    if v.startswith("1."):
        return v.split(".")[1]
    return v.split(".")[0]


def _normalize_vendor(vendor: str) -> str:
    """Normalize JDK vendor/distribution name."""
    v = vendor.lower().strip()
    openjdk_aliases = {"openjdk", "temurin", "adoptopenjdk", "adopt", "zulu", "corretto", "liberica"}
    if v in openjdk_aliases:
        return "openjdk"
    if "oracle" in v:
        return "oracle"
    return v


def _score_jdk_major(truth: PNCGroundTruth, buildroot: dict) -> DimensionScore:
    expected = truth.jdk_major_version
    raw = buildroot.get("jdk_version", {})
    actual_raw = raw.get("value", "") if isinstance(raw, dict) else str(raw)
    actual = _normalize_jdk_version(actual_raw)

    match = expected == actual if (expected and actual) else False
    return DimensionScore(
        dimension="jdk_major_version",
        weight=DIMENSION_WEIGHTS["jdk_major_version"],
        score=1.0 if match else 0.0,
        expected=expected,
        actual=actual,
        detail="exact match" if match else "mismatch",
    )


def _score_jdk_vendor(truth: PNCGroundTruth, buildroot: dict) -> DimensionScore:
    expected = _normalize_vendor(truth.jdk_vendor)
    raw = buildroot.get("jdk_distribution", {})
    actual_raw = raw.get("value", "") if isinstance(raw, dict) else str(raw)
    actual = _normalize_vendor(actual_raw)

    match = expected == actual if (expected and actual) else False
    return DimensionScore(
        dimension="jdk_vendor",
        weight=DIMENSION_WEIGHTS["jdk_vendor"],
        score=1.0 if match else 0.0,
        expected=expected,
        actual=actual,
        detail="exact match (normalized)" if match else "mismatch",
    )


def _score_build_tool(truth: PNCGroundTruth, buildroot: dict) -> DimensionScore:
    expected = truth.build_tool.lower()
    raw_cmd = buildroot.get("build_command", {})
    cmd = raw_cmd.get("value", "") if isinstance(raw_cmd, dict) else str(raw_cmd)

    if expected == "maven":
        match = "mvn" in cmd.lower() or "maven" in cmd.lower()
    elif expected == "gradle":
        match = "gradle" in cmd.lower()
    else:
        match = False

    actual = "maven" if ("mvn" in cmd.lower() or "maven" in cmd.lower()) else (
        "gradle" if "gradle" in cmd.lower() else "unknown"
    )

    return DimensionScore(
        dimension="build_tool",
        weight=DIMENSION_WEIGHTS["build_tool"],
        score=1.0 if match else 0.0,
        expected=expected,
        actual=actual,
        detail="tool match" if match else "tool mismatch",
    )


def _score_build_tool_version(truth: PNCGroundTruth, buildroot: dict) -> DimensionScore:
    expected = truth.build_tool_version

    version_key = "gradle_version" if truth.build_tool.lower() == "gradle" else "maven_version"
    raw_version = buildroot.get(version_key, {})
    actual = raw_version.get("value", "") if isinstance(raw_version, dict) else str(raw_version)
    if actual == "system-default":
        actual = ""

    if not expected or not actual:
        return DimensionScore(
            dimension="build_tool_version",
            weight=DIMENSION_WEIGHTS["build_tool_version"],
            score=0.0,
            expected=expected,
            actual=actual,
            detail="version not available for comparison",
        )

    if expected == actual:
        score = 1.0
        detail = "exact version match"
    elif expected.split(".")[0] == actual.split(".")[0]:
        score = 0.5
        detail = "major version match only"
    else:
        score = 0.0
        detail = "version mismatch"

    return DimensionScore(
        dimension="build_tool_version",
        weight=DIMENSION_WEIGHTS["build_tool_version"],
        score=score,
        expected=expected,
        actual=actual,
        detail=detail,
    )


def _score_os_family(truth: PNCGroundTruth, buildroot: dict) -> DimensionScore:
    expected = truth.os_family.lower()

    raw_image = buildroot.get("base_image", {})
    image = raw_image.get("value", "") if isinstance(raw_image, dict) else str(raw_image)
    image_lower = image.lower()

    if "rhel" in image_lower or "ubi" in image_lower or "redhat" in image_lower:
        actual = "rhel"
    elif "ubuntu" in image_lower or "debian" in image_lower:
        actual = "debian"
    elif "centos" in image_lower:
        actual = "rhel"
    elif "fedora" in image_lower:
        actual = "fedora"
    elif "alpine" in image_lower:
        actual = "alpine"
    else:
        actual = "unknown"

    match = expected == actual if (expected and actual != "unknown") else False
    return DimensionScore(
        dimension="os_family",
        weight=DIMENSION_WEIGHTS["os_family"],
        score=1.0 if match else 0.0,
        expected=expected,
        actual=actual,
        detail="OS family match" if match else "OS family mismatch",
    )


def _normalize_scm_url(url: str) -> str:
    """Normalize SCM URLs for comparison."""
    url = url.strip().rstrip("/")
    url = re.sub(r"\.git$", "", url)
    url = re.sub(r"^scm:git:", "", url)
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^git@github\.com:", "github.com/", url)
    return url.lower()


def _score_scm_url(truth: PNCGroundTruth, buildroot: dict) -> DimensionScore:
    expected = _normalize_scm_url(truth.scm_url) if truth.scm_url else ""
    actual_raw = buildroot.get("source_repo", "")
    actual = _normalize_scm_url(actual_raw) if actual_raw else ""

    if not expected:
        return DimensionScore(
            dimension="scm_url",
            weight=DIMENSION_WEIGHTS["scm_url"],
            score=0.5,
            expected=truth.scm_url,
            actual=actual_raw,
            detail="no ground truth SCM URL to compare",
        )

    if not actual:
        return DimensionScore(
            dimension="scm_url",
            weight=DIMENSION_WEIGHTS["scm_url"],
            score=0.0,
            expected=truth.scm_url,
            actual=actual_raw,
            detail="no reconstructed SCM URL",
        )

    match = expected == actual
    return DimensionScore(
        dimension="scm_url",
        weight=DIMENSION_WEIGHTS["scm_url"],
        score=1.0 if match else 0.0,
        expected=truth.scm_url,
        actual=actual_raw,
        detail="SCM URL match" if match else "SCM URL mismatch",
    )


def score_accuracy(
    truth: PNCGroundTruth,
    buildroot_json: dict,
    coordinate: str = "",
) -> AccuracyReport:
    """Compare buildroot.json against PNC ground truth across 6 weighted dimensions."""
    dimensions = [
        _score_jdk_major(truth, buildroot_json),
        _score_jdk_vendor(truth, buildroot_json),
        _score_build_tool(truth, buildroot_json),
        _score_build_tool_version(truth, buildroot_json),
        _score_os_family(truth, buildroot_json),
        _score_scm_url(truth, buildroot_json),
    ]

    aggregate = sum(d.score * d.weight for d in dimensions)

    return AccuracyReport(
        coordinate=coordinate,
        image_name=truth.image_name,
        dimensions=dimensions,
        aggregate_score=aggregate,
    )
