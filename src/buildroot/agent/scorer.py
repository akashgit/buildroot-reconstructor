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
    structural_match: float | None = None

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
            "structural_match": self.structural_match,
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

    if eval_result.l4_signal_source == "full_comparison":
        breakdown.jar_available = True
        breakdown.l4_score = eval_result.l4_score
        breakdown.signal_source = "full_comparison"
    elif eval_result.l4_signal_source == "fallback_signals":
        breakdown.jar_available = False
        breakdown.signal_source = "fallback_signals"
        breakdown.l4_score = eval_result.l4_score
        breakdown.bytecode_version_match = eval_result.bytecode_version_match
        breakdown.manifest_sanity = eval_result.manifest_sanity
        breakdown.unit_tests_pass = eval_result.unit_tests_pass
        breakdown.structural_match = getattr(eval_result, "structural_match", None)
        if eval_result.test_result:
            breakdown.tests_run = eval_result.test_result.run
            breakdown.tests_passed = eval_result.test_result.tests_passed
            breakdown.tests_failed = eval_result.test_result.failed
    elif eval_result.l3_command:
        breakdown.jar_available = False
        breakdown.signal_source = "fallback_signals"
    else:
        breakdown.signal_source = "l3_ceiling"

    return breakdown


def compute_fallback_score(
    bytecode_version_match: bool | None,
    manifest_sanity: bool | None,
    unit_tests_pass: bool | None = None,
    structural_match: float | None = None,
) -> float:
    """Compute fallback score from the 2 signals that reliably fire.

    Active signals:
      - bytecode_version_match (0.60): built .class major version matches expected JDK
      - manifest_sanity (0.40): MANIFEST.MF + pom.properties GAV correct

    structural_match and unit_tests_pass are accepted for forward compatibility
    but not scored — source extraction and test runner don't produce reliable
    results in the current pipeline.
    """
    score = 0.0
    if bytecode_version_match:
        score += 0.60
    if manifest_sanity:
        score += 0.40
    return score


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


def check_structural_match(
    rebuilt_jar: Path,
    source_root: Path,
) -> float | None:
    """Check structural correspondence between rebuilt JAR classes and source .java files.

    Returns Jaccard similarity (0.0-1.0) between the set of class files in the JAR
    and the set of .java source files. Returns None if either set is empty or
    if the project uses shade/bundle plugins (which add third-party classes).
    """
    if not rebuilt_jar.exists() or not source_root.exists():
        return None

    pom_path = source_root / "pom.xml"
    if pom_path.exists():
        try:
            xml_text = pom_path.read_text()
            if "maven-shade-plugin" in xml_text or "maven-bundle-plugin" in xml_text or "bnd-maven-plugin" in xml_text:
                return None
        except OSError:
            pass

    try:
        with zipfile.ZipFile(rebuilt_jar) as zf:
            class_names = set()
            for name in zf.namelist():
                if not name.endswith(".class"):
                    continue
                if name.startswith("META-INF/"):
                    continue
                if name == "module-info.class" or name.endswith("/module-info.class"):
                    continue
                outer = _class_to_outer_source(name)
                if outer:
                    class_names.add(outer)

        if not class_names:
            return None

        source_names = set()
        for java_file in source_root.rglob("*.java"):
            rel = java_file.relative_to(source_root)
            parts = rel.parts
            src_idx = -1
            for i, p in enumerate(parts):
                if p in ("java", "src"):
                    src_idx = i
            if src_idx >= 0 and src_idx + 1 < len(parts):
                qualified = "/".join(parts[src_idx + 1:])
            else:
                qualified = str(rel)
            qualified = qualified.replace(".java", "")
            source_names.add(qualified)

        if not source_names:
            return None

        intersection = class_names & source_names
        union = class_names | source_names
        if not union:
            return None

        return len(intersection) / len(union)

    except (zipfile.BadZipFile, OSError):
        return None


def _class_to_outer_source(class_path: str) -> str | None:
    """Map a .class file path to its outer source file path (without extension)."""
    name = class_path[:-6]  # strip .class
    if "$" in name:
        name = name.split("$")[0]
    return name if name else None


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
