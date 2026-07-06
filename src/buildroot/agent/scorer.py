"""Multi-signal fallback scoring for packages without original JARs on Maven Central."""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
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
    *,
    api_surface_match: float | None = None,
    dependency_graph_match: float | None = None,
    resource_completeness: float | None = None,
) -> float:
    """Compute fallback score with dynamic weight renormalization.

    Base weights (all 7 signals active):
      structural=0.15, bytecode=0.15, manifest=0.10, tests=0.10,
      api_surface=0.25, dependency_graph=0.15, resource=0.10

    When signals are None, their weight is excluded and the remaining
    weights renormalize. With only bytecode+manifest active this gives
    0.15/(0.15+0.10) = 0.60 and 0.10/(0.15+0.10) = 0.40, preserving
    PR #106 behavior.
    """
    signals: list[tuple[float, float]] = []

    if structural_match is not None:
        signals.append((structural_match, 0.15))
    if bytecode_version_match is not None:
        signals.append((float(bytecode_version_match), 0.15))
    if manifest_sanity is not None:
        signals.append((float(manifest_sanity), 0.10))
    if unit_tests_pass is not None:
        signals.append((float(unit_tests_pass), 0.10))
    if api_surface_match is not None:
        signals.append((api_surface_match, 0.25))
    if dependency_graph_match is not None:
        signals.append((dependency_graph_match, 0.15))
    if resource_completeness is not None:
        signals.append((resource_completeness, 0.10))

    total_weight = sum(w for _, w in signals)
    if total_weight == 0:
        return 0.0

    return sum(v * w for v, w in signals) / total_weight


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


def compute_api_surface_match(
    rebuilt_jar: Path,
    source_root: Path,
    container_tag: str,
    host: str | None = None,
) -> float | None:
    """Compute API surface match between rebuilt JAR and source .java files.

    Runs javap -protected -s inside the container to extract method descriptors,
    then parses source for public/protected method declarations.
    Returns Jaccard similarity or None if unavailable.
    """
    if not rebuilt_jar.exists() or not source_root.exists():
        return None

    jar_api = _extract_jar_api_javap(rebuilt_jar, container_tag, host)
    if not jar_api:
        return None

    source_api = _extract_source_api(source_root)
    if not source_api:
        return None

    intersection = jar_api & source_api
    union = jar_api | source_api
    if not union:
        return None

    return len(intersection) / len(union)


def _extract_jar_api_javap(
    rebuilt_jar: Path, container_tag: str, host: str | None = None,
) -> set[str] | None:
    """Extract public/protected method signatures from a JAR using javap in the container."""
    try:
        class_names: list[str] = []
        with zipfile.ZipFile(rebuilt_jar) as zf:
            for name in zf.namelist():
                if name.endswith(".class") and not name.startswith("META-INF/"):
                    cls = name[:-6].replace("/", ".")
                    class_names.append(cls)

        if not class_names:
            return None

        sample = class_names[:100]
        class_list = " ".join(shlex.quote(c) for c in sample)

        javap_cmd = (
            f"cd /tmp && jar xf /output/rebuilt.jar && "
            f"javap -protected -s -classpath /tmp {class_list} 2>/dev/null || true"
        )
        cmd: list[str]
        if host:
            cmd = [
                "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                host,
                f"podman run --rm -v {rebuilt_jar}:/output/rebuilt.jar:ro {shlex.quote(container_tag)} sh -c {shlex.quote(javap_cmd)}",
            ]
        else:
            cmd = [
                "podman", "run", "--rm",
                "-v", f"{rebuilt_jar}:/output/rebuilt.jar:ro",
                container_tag, "sh", "-c", javap_cmd,
            ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 and not proc.stdout.strip():
            return None

        return _parse_javap_output(proc.stdout)
    except (zipfile.BadZipFile, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("API surface extraction failed: %s", e)
        return None


def _parse_javap_output(output: str) -> set[str]:
    """Parse javap -protected -s output into a set of method signature strings."""
    methods: set[str] = set()
    current_class = ""
    pending_method = ""

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Compiled from"):
            continue
        if stripped.startswith("public class ") or stripped.startswith("public abstract class ") or \
           stripped.startswith("public interface ") or stripped.startswith("public final class ") or \
           stripped.startswith("class "):
            parts = stripped.split()
            for p in parts:
                if "." in p and not p.startswith("extends") and not p.startswith("implements"):
                    current_class = p.rstrip("{").strip()
                    break
            continue
        if "descriptor:" in stripped:
            descriptor = stripped.split("descriptor:")[-1].strip()
            if pending_method:
                methods.add(f"{current_class}.{pending_method}{descriptor}")
            pending_method = ""
            continue

        if ("public " in stripped or "protected " in stripped) and "(" in stripped and ")" in stripped:
            sig_part = stripped.rstrip(";").strip()
            name_match = re.search(r"(\w+)\(", sig_part)
            if name_match:
                pending_method = name_match.group(1)

    return methods


def _extract_source_api(source_root: Path) -> set[str]:
    """Extract public/protected method declarations from .java source files."""
    methods: set[str] = set()
    method_re = re.compile(
        r"(?:public|protected)\s+(?:static\s+)?(?:final\s+)?(?:abstract\s+)?(?:synchronized\s+)?"
        r"(?:<[^>]+>\s+)?(\S+)\s+(\w+)\s*\(",
    )

    for java_file in source_root.rglob("*.java"):
        try:
            text = java_file.read_text(errors="ignore")
        except OSError:
            continue

        rel = java_file.relative_to(source_root)
        parts = rel.parts
        src_idx = -1
        for i, p in enumerate(parts):
            if p in ("java", "src"):
                src_idx = i
        if src_idx >= 0 and src_idx + 1 < len(parts):
            qualified = ".".join(parts[src_idx + 1:])
        else:
            qualified = ".".join(rel.parts)
        qualified = qualified.replace(".java", "")

        for m in method_re.finditer(text):
            method_name = m.group(2)
            if method_name in ("if", "for", "while", "switch", "return", "catch"):
                continue
            methods.add(f"{qualified}.{method_name}")

    return methods


def compute_dependency_match(
    rebuilt_jar: Path,
    source_root: Path,
    container_tag: str,
    host: str | None = None,
) -> float | None:
    """Compute dependency graph match between rebuilt JAR and source imports.

    Runs jdeps -verbose:package inside the container, then parses source
    import statements. Returns Jaccard similarity or None if unavailable.
    """
    if not rebuilt_jar.exists() or not source_root.exists():
        return None

    jar_deps = _extract_jar_deps_jdeps(rebuilt_jar, container_tag, host)
    if jar_deps is None:
        return None

    source_deps = _extract_source_imports(source_root)
    if not jar_deps and not source_deps:
        return 1.0
    if not jar_deps or not source_deps:
        return 0.0

    intersection = jar_deps & source_deps
    union = jar_deps | source_deps
    return len(intersection) / len(union) if union else 0.0


def _extract_jar_deps_jdeps(
    rebuilt_jar: Path, container_tag: str, host: str | None = None,
) -> set[str] | None:
    """Extract package dependencies using jdeps in the container."""
    try:
        jdeps_cmd = f"jdeps -verbose:package /output/rebuilt.jar 2>/dev/null || true"

        cmd: list[str]
        if host:
            cmd = [
                "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                host,
                f"podman run --rm -v {rebuilt_jar}:/output/rebuilt.jar:ro {shlex.quote(container_tag)} sh -c {shlex.quote(jdeps_cmd)}",
            ]
        else:
            cmd = [
                "podman", "run", "--rm",
                "-v", f"{rebuilt_jar}:/output/rebuilt.jar:ro",
                container_tag, "sh", "-c", jdeps_cmd,
            ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 and not proc.stdout.strip():
            return None

        return _parse_jdeps_output(proc.stdout)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Dependency extraction failed: %s", e)
        return None


def _parse_jdeps_output(output: str) -> set[str]:
    """Parse jdeps -verbose:package output for package dependency names."""
    deps: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("-> "):
            pkg = stripped[3:].strip().split()[0]
            if pkg and not pkg.startswith("<"):
                deps.add(pkg)
    return deps


def _extract_source_imports(source_root: Path) -> set[str]:
    """Extract package names from import statements in .java files."""
    imports: set[str] = set()
    for java_file in source_root.rglob("*.java"):
        try:
            text = java_file.read_text(errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("import ") and not line.startswith("import static"):
                parts = line.replace("import ", "").replace(";", "").strip().split(".")
                if len(parts) > 1:
                    imports.add(".".join(parts[:-1]))
    return imports


def compute_resource_completeness(
    rebuilt_jar: Path,
    source_root: Path,
    pom_path: Path | None = None,
) -> float | None:
    """Compute fraction of expected resources present in the rebuilt JAR.

    Returns None for Gradle projects or when shade/bundle plugins are detected.
    """
    if not rebuilt_jar.exists() or not source_root.exists():
        return None

    effective_pom = pom_path or (source_root / "pom.xml")
    if not effective_pom.exists():
        if (source_root / "build.gradle").exists() or (source_root / "build.gradle.kts").exists():
            return None
        default_resource_dir = source_root / "src" / "main" / "resources"
        if not default_resource_dir.exists():
            return None
        resource_decls = [{"directory": "src/main/resources", "targetPath": None}]
    else:
        try:
            pom_text = effective_pom.read_text()
        except OSError:
            return None

        if "maven-shade-plugin" in pom_text or "maven-bundle-plugin" in pom_text or "bnd-maven-plugin" in pom_text:
            return None

        resource_decls = _parse_resource_declarations(effective_pom)

    expected = _discover_expected_resources(source_root, resource_decls)
    if not expected:
        return 1.0

    actual = _extract_jar_resources(rebuilt_jar)
    if actual is None:
        return None

    present = expected & actual
    return len(present) / len(expected)


def _parse_resource_declarations(pom_path: Path) -> list[dict]:
    """Parse pom.xml for <build><resources><resource> declarations."""
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
    except (ET.ParseError, OSError):
        return [{"directory": "src/main/resources", "targetPath": None}]

    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    resources = []

    for resource in root.findall(".//m:build/m:resources/m:resource", ns):
        directory = resource.find("m:directory", ns)
        target_path = resource.find("m:targetPath", ns)
        resources.append({
            "directory": directory.text if directory is not None else "src/main/resources",
            "targetPath": target_path.text if target_path is not None else None,
        })

    if not resources:
        for resource in root.findall(".//build/resources/resource"):
            directory = resource.find("directory")
            target_path = resource.find("targetPath")
            resources.append({
                "directory": directory.text if directory is not None else "src/main/resources",
                "targetPath": target_path.text if target_path is not None else None,
            })

    if not resources:
        resources.append({"directory": "src/main/resources", "targetPath": None})

    return resources


def _discover_expected_resources(
    source_root: Path, resource_declarations: list[dict],
) -> set[str]:
    """Walk resource directories to build the expected set of JAR entry paths."""
    expected: set[str] = set()
    for decl in resource_declarations:
        resource_dir = source_root / decl["directory"]
        if not resource_dir.exists():
            continue
        target_prefix = decl.get("targetPath") or ""
        for file_path in resource_dir.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(resource_dir)
                jar_path = f"{target_prefix}/{rel}" if target_prefix else str(rel)
                jar_path = jar_path.replace("\\", "/")
                expected.add(jar_path)
    return expected


def _extract_jar_resources(rebuilt_jar: Path) -> set[str] | None:
    """List non-.class entries from the JAR."""
    try:
        with zipfile.ZipFile(rebuilt_jar) as zf:
            return {
                name for name in zf.namelist()
                if not name.endswith(".class") and not name.endswith("/")
            }
    except (zipfile.BadZipFile, OSError):
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
