"""Multi-signal fallback scoring for packages without original JARs on Maven Central."""

from __future__ import annotations

import logging
import shlex
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from buildroot.agent.models import EvalResult

logger = logging.getLogger(__name__)

JDK_MAJOR_TO_VERSION = {
    45: 1, 46: 2, 47: 3, 48: 4, 49: 5, 50: 6, 51: 7, 52: 8,
    53: 9, 54: 10, 55: 11, 56: 12, 57: 13, 58: 14, 59: 15,
    60: 16, 61: 17, 62: 18, 63: 19, 64: 20, 65: 21, 66: 22,
    67: 23, 68: 24,
}

VERSION_TO_MAJOR = {v: k for k, v in JDK_MAJOR_TO_VERSION.items()}


@dataclass
class ScoreBreakdown:
    """Complete scoring breakdown with primary and fallback signals."""

    l1_parse: bool = False
    l2_build: bool = False
    l3_command: bool = False

    jar_available: bool = False
    l4_score: float = 0.0
    comparison_report: Any | None = None

    bytecode_version_match: bool | None = None
    manifest_sanity: bool | None = None
    unit_tests_pass: bool | None = None

    tests_run: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    tests_skipped: int | None = None
    test_duration_seconds: float | None = None

    signal_source: str = ""  # "full_comparison" | "fallback_signals" | "l3_ceiling"
    reward: float = 0.0
    level_reached: int = 0

    def to_dict(self) -> dict:
        d: dict = {
            "l1_parse": self.l1_parse,
            "l2_build": self.l2_build,
            "l3_command": self.l3_command,
            "jar_available": self.jar_available,
            "l4_score": round(self.l4_score, 4),
            "bytecode_version_match": self.bytecode_version_match,
            "manifest_sanity": self.manifest_sanity,
            "unit_tests_pass": self.unit_tests_pass,
            "signal_source": self.signal_source,
            "reward": round(self.reward, 4),
            "level_reached": self.level_reached,
        }
        if self.tests_run is not None:
            d["tests_run"] = self.tests_run
            d["tests_passed"] = self.tests_passed
            d["tests_failed"] = self.tests_failed
            d["tests_skipped"] = self.tests_skipped
            d["test_duration_seconds"] = self.test_duration_seconds
        return d


def build_score_breakdown(eval_result: EvalResult, coordinate: str) -> ScoreBreakdown:
    """Build a ScoreBreakdown from an EvalResult, routing to full comparison or fallback."""
    breakdown = ScoreBreakdown(
        l1_parse=eval_result.l1_parse,
        l2_build=eval_result.l2_build,
        l3_command=eval_result.l3_command,
        reward=eval_result.reward,
        level_reached=eval_result.level_reached,
    )

    if eval_result.l4_score > 0 or eval_result.l4_match:
        breakdown.jar_available = True
        breakdown.l4_score = eval_result.l4_score
        breakdown.signal_source = "full_comparison"
    elif eval_result.l3_command:
        breakdown.jar_available = False
        breakdown.signal_source = "fallback_signals"
    else:
        breakdown.signal_source = "l3_ceiling"

    return breakdown


def compute_fallback_score(
    bytecode_version_match: bool | None,
    manifest_sanity: bool | None,
    unit_tests_pass: bool | None,
) -> float:
    """Compute weighted fallback score from available signals.

    Weights: bytecode_version_match (0.40) + manifest_sanity (0.30) + unit_tests_pass (0.30)
    Only scores on available (non-None) signals, re-normalizing weights.
    """
    signals = [
        (bytecode_version_match, 0.40),
        (manifest_sanity, 0.30),
        (unit_tests_pass, 0.30),
    ]

    total_weight = 0.0
    score = 0.0

    for value, weight in signals:
        if value is not None:
            total_weight += weight
            if value:
                score += weight

    if total_weight == 0:
        return 0.0

    return score / total_weight


def check_bytecode_version_match(
    rebuilt_jar: Path, expected_jdk_version: str,
) -> bool | None:
    """Check if the rebuilt JAR's bytecode version matches the expected JDK.

    Reads the first .class file from the rebuilt JAR, extracts bytes 6-7
    (major version), and compares against the expected JDK version.
    """
    if not rebuilt_jar.exists():
        return None

    try:
        expected_major = _jdk_version_to_bytecode_major(expected_jdk_version)
        if expected_major is None:
            return None

        with zipfile.ZipFile(rebuilt_jar) as zf:
            class_files = [n for n in zf.namelist() if n.endswith(".class") and not n.startswith("META-INF/")]
            if not class_files:
                return None

            class_data = zf.read(class_files[0])
            if len(class_data) < 8:
                return None

            actual_major = int.from_bytes(class_data[6:8], "big")
            return actual_major == expected_major
    except (zipfile.BadZipFile, OSError, ValueError):
        return None


def check_manifest_sanity(
    rebuilt_jar: Path, group_id: str, artifact_id: str,
) -> bool | None:
    """Check if the rebuilt JAR has a sane MANIFEST.MF and correct pom.properties.

    Checks:
    1. META-INF/MANIFEST.MF exists and has Manifest-Version
    2. META-INF/maven/{group_id}/{artifact_id}/pom.properties has correct GAV
    """
    if not rebuilt_jar.exists():
        return None

    try:
        with zipfile.ZipFile(rebuilt_jar) as zf:
            names = zf.namelist()

            if "META-INF/MANIFEST.MF" not in names:
                return False

            manifest = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
            if "Manifest-Version" not in manifest:
                return False

            pom_props_path = f"META-INF/maven/{group_id}/{artifact_id}/pom.properties"
            if pom_props_path in names:
                props = zf.read(pom_props_path).decode("utf-8", errors="replace")
                if group_id not in props or artifact_id not in props:
                    return False

            return True
    except (zipfile.BadZipFile, OSError):
        return None


def check_unit_tests_pass(
    tag: str, host: str, module_path: str | None = None,
) -> bool | None:
    """Run unit tests inside the same container that built the JAR.

    Returns True if tests pass, False if they fail, None if unable to run.
    """
    test_cmd = "mvn test -B"
    if module_path:
        test_cmd = f"mvn test -B -pl {shlex.quote(module_path)}"

    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
             host, f"podman run --rm {shlex.quote(tag)} sh -c {shlex.quote(test_cmd)}"],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode == 0 and "BUILD SUCCESS" in proc.stdout:
            return True
        return False
    except (subprocess.TimeoutExpired, OSError):
        return None


def _jdk_version_to_bytecode_major(jdk_version: str) -> int | None:
    """Convert a JDK version string to bytecode major version number."""
    try:
        version_str = jdk_version.strip()
        if version_str.startswith("1."):
            parts = version_str.split(".")
            if len(parts) >= 2:
                major = int(parts[1])
            else:
                return None
        else:
            major = int(version_str.split(".")[0])

        return VERSION_TO_MAJOR.get(major)
    except (ValueError, IndexError):
        return None
