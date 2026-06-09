"""Multi-layer JAR comparison pipeline for reproducibility verification."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

NON_DETERMINISTIC_MANIFEST_KEYS = frozenset({
    "Build-Jdk",
    "Build-Jdk-Spec",
    "Built-By",
    "Created-By",
    "Build-Timestamp",
    "Bnd-LastModified",
})

PROPERTIES_TIMESTAMP_RE = re.compile(r"^#.*\b\w{3}\s+\w{3}\s+\d{1,2}.*$", re.MULTILINE)


class Verdict:
    IDENTICAL = "IDENTICAL"
    EQUIVALENT = "EQUIVALENT"
    DIVERGENT = "DIVERGENT"
    FAILED = "FAILED"


@dataclass
class EntryDiff:
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    size_mismatches: list[dict[str, object]] = field(default_factory=list)
    crc_mismatches: list[dict[str, object]] = field(default_factory=list)


@dataclass
class StructuralResult:
    original_count: int = 0
    rebuilt_count: int = 0
    diff: EntryDiff = field(default_factory=EntryDiff)
    match: bool = False


@dataclass
class MetadataResult:
    manifest_match: bool = False
    manifest_diff_keys: list[str] = field(default_factory=list)
    resource_matches: int = 0
    resource_mismatches: list[str] = field(default_factory=list)
    match: bool = False


@dataclass
class BytecodeResult:
    tool_used: str = ""
    classes_compared: int = 0
    classes_identical: int = 0
    classes_divergent: list[str] = field(default_factory=list)
    match: bool = False


@dataclass
class ComparisonReport:
    coordinate: str = ""
    verdict: str = Verdict.FAILED
    sha256_original: str = ""
    sha256_rebuilt: str = ""
    structural: StructuralResult = field(default_factory=StructuralResult)
    metadata: MetadataResult = field(default_factory=MetadataResult)
    bytecode: BytecodeResult = field(default_factory=BytecodeResult)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "coordinate": self.coordinate,
            "verdict": self.verdict,
            "sha256_original": self.sha256_original,
            "sha256_rebuilt": self.sha256_rebuilt,
            "structural": {
                "original_count": self.structural.original_count,
                "rebuilt_count": self.structural.rebuilt_count,
                "missing_entries": self.structural.diff.missing,
                "extra_entries": self.structural.diff.extra,
                "size_mismatches": self.structural.diff.size_mismatches,
                "crc_mismatches": self.structural.diff.crc_mismatches,
                "match": self.structural.match,
            },
            "metadata": {
                "manifest_match": self.metadata.manifest_match,
                "manifest_diff_keys": self.metadata.manifest_diff_keys,
                "resource_matches": self.metadata.resource_matches,
                "resource_mismatches": self.metadata.resource_mismatches,
                "match": self.metadata.match,
            },
            "bytecode": {
                "tool_used": self.bytecode.tool_used,
                "classes_compared": self.bytecode.classes_compared,
                "classes_identical": self.bytecode.classes_identical,
                "classes_divergent": self.bytecode.classes_divergent,
                "match": self.bytecode.match,
            },
            "error": self.error,
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compare_jars(
    original_jar: Path,
    rebuilt_jar: Path,
    coordinate: str = "",
) -> ComparisonReport:
    report = ComparisonReport(coordinate=coordinate)

    if not original_jar.exists() or not rebuilt_jar.exists():
        report.error = f"JAR not found: original={original_jar.exists()}, rebuilt={rebuilt_jar.exists()}"
        return report

    try:
        report.sha256_original = _sha256(original_jar)
        report.sha256_rebuilt = _sha256(rebuilt_jar)
    except OSError as e:
        report.error = f"Cannot read JAR files: {e}"
        return report

    if report.sha256_original == report.sha256_rebuilt:
        report.verdict = Verdict.IDENTICAL
        report.structural.match = True
        report.metadata.match = True
        report.bytecode.match = True
        return report

    try:
        report.structural = _layer1_structural(original_jar, rebuilt_jar)
        report.metadata = _layer2_metadata(original_jar, rebuilt_jar)
        report.bytecode = _layer3_bytecode(original_jar, rebuilt_jar)
    except (zipfile.BadZipFile, OSError) as e:
        report.error = str(e)
        report.verdict = Verdict.FAILED
        return report

    has_missing_or_extra = (
        report.structural.diff.missing or report.structural.diff.extra
    )
    if has_missing_or_extra:
        report.verdict = Verdict.DIVERGENT
    elif not report.bytecode.match:
        report.verdict = Verdict.DIVERGENT
    elif not report.metadata.match:
        report.verdict = Verdict.DIVERGENT
    else:
        report.verdict = Verdict.EQUIVALENT

    return report


def _layer1_structural(original: Path, rebuilt: Path) -> StructuralResult:
    result = StructuralResult()
    with zipfile.ZipFile(original) as zf_orig, zipfile.ZipFile(rebuilt) as zf_rebu:
        orig_entries = {info.filename: info for info in zf_orig.infolist()}
        rebu_entries = {info.filename: info for info in zf_rebu.infolist()}

        result.original_count = len(orig_entries)
        result.rebuilt_count = len(rebu_entries)

        orig_names = set(orig_entries.keys())
        rebu_names = set(rebu_entries.keys())

        result.diff.missing = sorted(orig_names - rebu_names)
        result.diff.extra = sorted(rebu_names - orig_names)

        for name in sorted(orig_names & rebu_names):
            orig_info = orig_entries[name]
            rebu_info = rebu_entries[name]
            if orig_info.file_size != rebu_info.file_size:
                result.diff.size_mismatches.append({
                    "entry": name,
                    "original_size": orig_info.file_size,
                    "rebuilt_size": rebu_info.file_size,
                })
            if orig_info.CRC != rebu_info.CRC:
                result.diff.crc_mismatches.append({
                    "entry": name,
                    "original_crc": orig_info.CRC,
                    "rebuilt_crc": rebu_info.CRC,
                })

    result.match = (
        not result.diff.missing
        and not result.diff.extra
        and not result.diff.size_mismatches
        and not result.diff.crc_mismatches
    )
    return result


def _parse_manifest(raw: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    current_key: str | None = None
    current_val = ""
    for line in raw.splitlines():
        if line.startswith(" ") and current_key is not None:
            current_val += line[1:]
        else:
            if current_key is not None:
                entries[current_key] = current_val
            if ":" in line:
                current_key, current_val = line.split(":", 1)
                current_key = current_key.strip()
                current_val = current_val.strip()
            else:
                current_key = None
                current_val = ""
    if current_key is not None:
        entries[current_key] = current_val
    return entries


def _strip_properties_timestamps(content: str) -> str:
    return PROPERTIES_TIMESTAMP_RE.sub("", content).strip()


def _layer2_metadata(original: Path, rebuilt: Path) -> MetadataResult:
    result = MetadataResult()
    with zipfile.ZipFile(original) as zf_orig, zipfile.ZipFile(rebuilt) as zf_rebu:
        orig_names = set(zf_orig.namelist())
        rebu_names = set(zf_rebu.namelist())
        common = orig_names & rebu_names

        if "META-INF/MANIFEST.MF" in common:
            orig_manifest = _parse_manifest(
                zf_orig.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
            )
            rebu_manifest = _parse_manifest(
                zf_rebu.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
            )
            diff_keys = []
            all_keys = set(orig_manifest.keys()) | set(rebu_manifest.keys())
            for key in sorted(all_keys):
                if key in NON_DETERMINISTIC_MANIFEST_KEYS:
                    continue
                if orig_manifest.get(key) != rebu_manifest.get(key):
                    diff_keys.append(key)
            result.manifest_diff_keys = diff_keys
            result.manifest_match = len(diff_keys) == 0
        else:
            result.manifest_match = True

        resource_entries = [
            name for name in sorted(common)
            if not name.endswith(".class")
            and not name.endswith("/")
            and name != "META-INF/MANIFEST.MF"
        ]

        for name in resource_entries:
            orig_bytes = zf_orig.read(name)
            rebu_bytes = zf_rebu.read(name)
            if orig_bytes == rebu_bytes:
                result.resource_matches += 1
                continue
            if name.endswith(".properties"):
                orig_stripped = _strip_properties_timestamps(
                    orig_bytes.decode("utf-8", errors="replace")
                )
                rebu_stripped = _strip_properties_timestamps(
                    rebu_bytes.decode("utf-8", errors="replace")
                )
                if orig_stripped == rebu_stripped:
                    result.resource_matches += 1
                    continue
            result.resource_mismatches.append(name)

    result.match = result.manifest_match and len(result.resource_mismatches) == 0
    return result


def _find_cfr() -> str | None:
    cfr = shutil.which("cfr")
    if cfr:
        return cfr
    for candidate in ["/usr/local/lib/cfr.jar", "/opt/cfr/cfr.jar"]:
        if Path(candidate).exists():
            return candidate
    return None


def _decompile_class_cfr(cfr_path: str, class_file: Path, output_dir: Path) -> str | None:
    try:
        if cfr_path.endswith(".jar"):
            cmd = ["java", "-jar", cfr_path, str(class_file), "--outputdir", str(output_dir)]
        else:
            cmd = [cfr_path, str(class_file), "--outputdir", str(output_dir)]
        subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        java_files = list(output_dir.rglob("*.java"))
        if java_files:
            return java_files[0].read_text(encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _decompile_class_javap(class_file: Path) -> str | None:
    javap = shutil.which("javap")
    if not javap:
        return None
    try:
        result = subprocess.run(
            [javap, "-c", "-p", str(class_file)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            output = re.sub(r"#\d+", "#N", result.stdout)
            return output
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _layer3_bytecode(original: Path, rebuilt: Path) -> BytecodeResult:
    result = BytecodeResult()
    cfr_path = _find_cfr()
    result.tool_used = 'cfr' if cfr_path else ('javap' if shutil.which('javap') else 'none')

    with zipfile.ZipFile(original) as zf_orig, zipfile.ZipFile(rebuilt) as zf_rebu:
        orig_classes = {n for n in zf_orig.namelist() if n.endswith(".class")}
        rebu_classes = {n for n in zf_rebu.namelist() if n.endswith(".class")}
        common_classes = sorted(orig_classes & rebu_classes)

        if not common_classes:
            result.match = True
            return result

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            orig_dir = tmp / "original"
            rebu_dir = tmp / "rebuilt"

            for name in common_classes:
                result.classes_compared += 1

                orig_file = orig_dir / name
                rebu_file = rebu_dir / name

                resolved_orig = orig_file.resolve()
                resolved_rebu = rebu_file.resolve()
                if not resolved_orig.is_relative_to(orig_dir.resolve()) or not resolved_rebu.is_relative_to(rebu_dir.resolve()):
                    continue

                orig_file.parent.mkdir(parents=True, exist_ok=True)
                rebu_file.parent.mkdir(parents=True, exist_ok=True)

                orig_file.write_bytes(zf_orig.read(name))
                rebu_file.write_bytes(zf_rebu.read(name))

                if orig_file.read_bytes() == rebu_file.read_bytes():
                    result.classes_identical += 1
                    continue

                orig_src = None
                rebu_src = None

                if cfr_path:
                    orig_out = tmp / "cfr_orig"
                    rebu_out = tmp / "cfr_rebu"
                    shutil.rmtree(orig_out, ignore_errors=True)
                    shutil.rmtree(rebu_out, ignore_errors=True)
                    orig_out.mkdir()
                    rebu_out.mkdir()
                    orig_src = _decompile_class_cfr(cfr_path, orig_file, orig_out)
                    rebu_src = _decompile_class_cfr(cfr_path, rebu_file, rebu_out)
                    if orig_src is not None and rebu_src is not None:
                        if orig_src == rebu_src:
                            result.classes_identical += 1
                            continue

                if orig_src is None or rebu_src is None:
                    orig_src = _decompile_class_javap(orig_file)
                    rebu_src = _decompile_class_javap(rebu_file)
                    if orig_src is not None and rebu_src is not None:
                        if orig_src == rebu_src:
                            result.classes_identical += 1
                            continue

                result.classes_divergent.append(name)

    result.match = len(result.classes_divergent) == 0
    return result


def generate_summary(reports: list[ComparisonReport]) -> dict:
    total = len(reports)
    verdicts = {v: 0 for v in [Verdict.IDENTICAL, Verdict.EQUIVALENT, Verdict.DIVERGENT, Verdict.FAILED]}
    for r in reports:
        verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1

    reproducible = verdicts[Verdict.IDENTICAL] + verdicts[Verdict.EQUIVALENT]
    score = reproducible / total if total > 0 else 0.0

    return {
        "total_packages": total,
        "verdicts": verdicts,
        "reproducibility_score": round(score, 4),
        "packages": [
            {"coordinate": r.coordinate, "verdict": r.verdict}
            for r in reports
        ],
    }


def write_report(report: ComparisonReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    parts = report.coordinate.split(":")
    if len(parts) == 3:
        filename = f"{parts[1]}-{parts[2]}-comparison.json"
    else:
        filename = f"{report.coordinate.replace(':', '-')}-comparison.json"
    path = output_dir / filename
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote comparison report to %s", path)
    return path
