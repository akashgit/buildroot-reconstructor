"""Multi-layer comparison pipeline for Python sdist and wheel reproducibility verification."""

from __future__ import annotations

import email.parser
import hashlib
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()


class Verdict:
    IDENTICAL = "IDENTICAL"
    EQUIVALENT = "EQUIVALENT"
    DIVERGENT = "DIVERGENT"
    FAILED = "FAILED"


GENERATED_FILE_PATTERNS = [
    re.compile(r"\.egg-info/"),
    re.compile(r"__pycache__/"),
    re.compile(r"\.pyc$"),
]


@dataclass
class EntryDiff:
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    size_mismatches: list[dict] = field(default_factory=list)


@dataclass
class StructuralResult:
    original_count: int = 0
    rebuilt_count: int = 0
    diff: EntryDiff = field(default_factory=EntryDiff)
    match: bool = False


@dataclass
class MetadataResult:
    metadata_match: bool = False
    metadata_diff_fields: list[str] = field(default_factory=list)
    resource_matches: int = 0
    resource_mismatches: list[str] = field(default_factory=list)
    match: bool = False


@dataclass
class SourceResult:
    files_compared: int = 0
    files_identical: int = 0
    files_divergent: list[str] = field(default_factory=list)
    match: bool = False


@dataclass
class SdistComparisonReport:
    coordinate: str = ""
    verdict: str = Verdict.FAILED
    sha256_original: str = ""
    sha256_rebuilt: str = ""
    structural: StructuralResult = field(default_factory=StructuralResult)
    metadata: MetadataResult = field(default_factory=MetadataResult)
    source: SourceResult = field(default_factory=SourceResult)
    error: str | None = None

    def equivalence_score(self) -> float:
        """Continuous 0.0-1.0 equivalence score.

        Scoring: 0.50 * source_match_ratio + 0.25 * resource_ratio + 0.25 * entry_score.
        """
        if self.verdict == Verdict.IDENTICAL:
            return 1.0
        if self.verdict == Verdict.FAILED:
            return 0.0

        # Source match ratio
        if self.source.files_compared > 0:
            source_ratio = self.source.files_identical / self.source.files_compared
        else:
            source_ratio = 1.0

        # Resource match ratio
        total_resources = self.metadata.resource_matches + len(
            self.metadata.resource_mismatches
        )
        if total_resources > 0:
            resource_ratio = self.metadata.resource_matches / total_resources
        else:
            resource_ratio = 1.0

        # Entry score
        total_entries = self.structural.original_count
        if total_entries > 0:
            missing_extra = len(self.structural.diff.missing) + len(
                self.structural.diff.extra
            )
            entry_score = max(0.0, 1.0 - missing_extra / total_entries)
        else:
            entry_score = 1.0

        return 0.50 * source_ratio + 0.25 * resource_ratio + 0.25 * entry_score

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output."""
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
                "match": self.structural.match,
            },
            "metadata": {
                "metadata_match": self.metadata.metadata_match,
                "metadata_diff_fields": self.metadata.metadata_diff_fields,
                "resource_matches": self.metadata.resource_matches,
                "resource_mismatches": self.metadata.resource_mismatches,
                "match": self.metadata.match,
            },
            "source": {
                "files_compared": self.source.files_compared,
                "files_identical": self.source.files_identical,
                "files_divergent": self.source.files_divergent,
                "match": self.source.match,
            },
            "error": self.error,
        }


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_generated(name: str) -> bool:
    """Check if an entry path matches a generated file pattern."""
    for pattern in GENERATED_FILE_PATTERNS:
        if pattern.search(name):
            return True
    return False


def _normalize_sdist_entries(tf: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    """Extract entries from tar, normalizing paths by stripping the top-level directory.

    Sdists contain a {name}-{version}/ prefix. Strip it.
    Skip directories (only compare files).
    Filter out GENERATED_FILE_PATTERNS.
    """
    entries: dict[str, tarfile.TarInfo] = {}
    for member in tf.getmembers():
        if member.isdir():
            continue
        # Strip the top-level directory prefix
        parts = member.name.split("/", 1)
        if len(parts) < 2:
            normalized = member.name
        else:
            normalized = parts[1]
        if not normalized:
            continue
        if _is_generated(normalized):
            continue
        entries[normalized] = member
    return entries


def _normalize_wheel_entries(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Extract entries from zip, normalize paths.

    Wheels contain {name}-{version}.dist-info/ prefix -- keep it.
    Skip directories.
    Filter out GENERATED_FILE_PATTERNS.
    """
    entries: dict[str, zipfile.ZipInfo] = {}
    for info in zf.infolist():
        if info.filename.endswith("/"):
            continue
        if _is_generated(info.filename):
            continue
        entries[info.filename] = info
    return entries


def _layer1_structural(
    original_entries: dict, rebuilt_entries: dict
) -> StructuralResult:
    """Compare entry sets: missing, extra, size mismatches."""
    result = StructuralResult()
    result.original_count = len(original_entries)
    result.rebuilt_count = len(rebuilt_entries)

    orig_names = set(original_entries.keys())
    rebu_names = set(rebuilt_entries.keys())

    result.diff.missing = sorted(orig_names - rebu_names)
    result.diff.extra = sorted(rebu_names - orig_names)

    for name in sorted(orig_names & rebu_names):
        orig_entry = original_entries[name]
        rebu_entry = rebuilt_entries[name]
        # tarfile.TarInfo uses .size, zipfile.ZipInfo uses .file_size
        orig_size = (
            orig_entry.size
            if isinstance(orig_entry, tarfile.TarInfo)
            else orig_entry.file_size
        )
        rebu_size = (
            rebu_entry.size
            if isinstance(rebu_entry, tarfile.TarInfo)
            else rebu_entry.file_size
        )
        if orig_size != rebu_size:
            result.diff.size_mismatches.append(
                {
                    "entry": name,
                    "original_size": orig_size,
                    "rebuilt_size": rebu_size,
                }
            )

    result.match = (
        not result.diff.missing
        and not result.diff.extra
        and not result.diff.size_mismatches
    )
    return result


def _read_tar_entry(tf: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    """Read bytes from a tar entry."""
    f = tf.extractfile(member)
    if f is None:
        return b""
    return f.read()


def _parse_pkg_info(raw: str) -> dict[str, str]:
    """Parse PKG-INFO or METADATA (RFC 822 format) into a dict of fields."""
    parser = email.parser.Parser()
    msg = parser.parsestr(raw)
    result: dict[str, str] = {}
    for key in msg.keys():
        result[key] = msg[key]
    return result


# Fields that commonly vary between builds and should be ignored
NON_DETERMINISTIC_METADATA_FIELDS: frozenset[str] = frozenset()


def _layer2_metadata(
    original_archive,
    rebuilt_archive,
    original_entries: dict,
    rebuilt_entries: dict,
    is_wheel: bool = False,
) -> MetadataResult:
    """Compare metadata files.

    - Sdist: PKG-INFO (parse as email headers, compare field by field)
    - Wheel: METADATA, WHEEL files
    Compare non-.py resource files byte-by-byte.
    """
    result = MetadataResult()
    common = set(original_entries.keys()) & set(rebuilt_entries.keys())

    # Determine metadata file names to compare
    if is_wheel:
        metadata_files = [
            n for n in common if n.endswith("/METADATA") or n.endswith("/WHEEL")
        ]
    else:
        metadata_files = [n for n in common if n == "PKG-INFO"]

    # Compare metadata files field by field
    all_diff_fields: list[str] = []
    metadata_found = False
    for mf_name in metadata_files:
        metadata_found = True
        if isinstance(original_archive, tarfile.TarFile):
            orig_bytes = _read_tar_entry(original_archive, original_entries[mf_name])
            rebu_bytes = _read_tar_entry(rebuilt_archive, rebuilt_entries[mf_name])
        else:
            orig_bytes = original_archive.read(mf_name)
            rebu_bytes = rebuilt_archive.read(mf_name)

        orig_parsed = _parse_pkg_info(
            orig_bytes.decode("utf-8", errors="replace")
        )
        rebu_parsed = _parse_pkg_info(
            rebu_bytes.decode("utf-8", errors="replace")
        )

        all_keys = set(orig_parsed.keys()) | set(rebu_parsed.keys())
        for key in sorted(all_keys):
            if key in NON_DETERMINISTIC_METADATA_FIELDS:
                continue
            if orig_parsed.get(key) != rebu_parsed.get(key):
                qualified = f"{mf_name}:{key}" if is_wheel else key
                all_diff_fields.append(qualified)

    result.metadata_diff_fields = all_diff_fields
    if metadata_found:
        result.metadata_match = len(all_diff_fields) == 0
    else:
        result.metadata_match = True

    # Compare non-.py, non-metadata resource files byte-by-byte
    metadata_names = set(metadata_files)
    # Also exclude RECORD in wheels (it's a hash manifest that always differs)
    if is_wheel:
        metadata_names |= {n for n in common if n.endswith("/RECORD")}

    resource_entries = [
        name
        for name in sorted(common)
        if not name.endswith(".py")
        and name not in metadata_names
    ]

    for name in resource_entries:
        if isinstance(original_archive, tarfile.TarFile):
            orig_bytes = _read_tar_entry(original_archive, original_entries[name])
            rebu_bytes = _read_tar_entry(rebuilt_archive, rebuilt_entries[name])
        else:
            orig_bytes = original_archive.read(name)
            rebu_bytes = rebuilt_archive.read(name)

        if orig_bytes == rebu_bytes:
            result.resource_matches += 1
        else:
            result.resource_mismatches.append(name)

    result.match = result.metadata_match and len(result.resource_mismatches) == 0
    return result


def _layer3_source(
    original_archive,
    rebuilt_archive,
    original_entries: dict,
    rebuilt_entries: dict,
) -> SourceResult:
    """Compare .py source files byte-by-byte.

    Files that exist in both archives and are .py files.
    """
    result = SourceResult()
    common = set(original_entries.keys()) & set(rebuilt_entries.keys())
    py_files = sorted(n for n in common if n.endswith(".py"))

    for name in py_files:
        result.files_compared += 1
        if isinstance(original_archive, tarfile.TarFile):
            orig_bytes = _read_tar_entry(original_archive, original_entries[name])
            rebu_bytes = _read_tar_entry(rebuilt_archive, rebuilt_entries[name])
        else:
            orig_bytes = original_archive.read(name)
            rebu_bytes = rebuilt_archive.read(name)

        if orig_bytes == rebu_bytes:
            result.files_identical += 1
        else:
            result.files_divergent.append(name)

    result.match = len(result.files_divergent) == 0
    return result


def compare_sdists(
    original_sdist: Path,
    rebuilt_sdist: Path,
    coordinate: str = "",
) -> SdistComparisonReport:
    """Compare two sdist (.tar.gz) archives.

    1. SHA-256 identity check (short-circuit to IDENTICAL)
    2. Layer 1: structural (tar entry lists)
    3. Layer 2: metadata (PKG-INFO comparison, resource files)
    4. Layer 3: source (.py file comparison)
    Determine verdict: IDENTICAL, EQUIVALENT, or DIVERGENT.
    """
    report = SdistComparisonReport(coordinate=coordinate)

    if not original_sdist.exists() or not rebuilt_sdist.exists():
        report.error = (
            f"Sdist not found: original={original_sdist.exists()}, "
            f"rebuilt={rebuilt_sdist.exists()}"
        )
        return report

    try:
        report.sha256_original = _file_sha256(original_sdist)
        report.sha256_rebuilt = _file_sha256(rebuilt_sdist)
    except OSError as e:
        report.error = f"Cannot read sdist files: {e}"
        return report

    if report.sha256_original == report.sha256_rebuilt:
        report.verdict = Verdict.IDENTICAL
        report.structural.match = True
        report.metadata.match = True
        report.source.match = True
        return report

    try:
        with tarfile.open(original_sdist, "r:gz") as tf_orig, tarfile.open(
            rebuilt_sdist, "r:gz"
        ) as tf_rebu:
            orig_entries = _normalize_sdist_entries(tf_orig)
            rebu_entries = _normalize_sdist_entries(tf_rebu)

            report.structural = _layer1_structural(orig_entries, rebu_entries)
            report.metadata = _layer2_metadata(
                tf_orig, tf_rebu, orig_entries, rebu_entries, is_wheel=False
            )
            report.source = _layer3_source(
                tf_orig, tf_rebu, orig_entries, rebu_entries
            )
    except (tarfile.TarError, OSError) as e:
        report.error = str(e)
        report.verdict = Verdict.FAILED
        return report

    _determine_verdict(report)
    return report


def compare_wheels(
    original_wheel: Path,
    rebuilt_wheel: Path,
    coordinate: str = "",
) -> SdistComparisonReport:
    """Compare two wheel (.whl) archives (ZIP format).

    Same 3 layers but using zipfile instead of tarfile.
    Compare METADATA, WHEEL, RECORD files.
    """
    report = SdistComparisonReport(coordinate=coordinate)

    if not original_wheel.exists() or not rebuilt_wheel.exists():
        report.error = (
            f"Wheel not found: original={original_wheel.exists()}, "
            f"rebuilt={rebuilt_wheel.exists()}"
        )
        return report

    try:
        report.sha256_original = _file_sha256(original_wheel)
        report.sha256_rebuilt = _file_sha256(rebuilt_wheel)
    except OSError as e:
        report.error = f"Cannot read wheel files: {e}"
        return report

    if report.sha256_original == report.sha256_rebuilt:
        report.verdict = Verdict.IDENTICAL
        report.structural.match = True
        report.metadata.match = True
        report.source.match = True
        return report

    try:
        with zipfile.ZipFile(original_wheel) as zf_orig, zipfile.ZipFile(
            rebuilt_wheel
        ) as zf_rebu:
            orig_entries = _normalize_wheel_entries(zf_orig)
            rebu_entries = _normalize_wheel_entries(zf_rebu)

            report.structural = _layer1_structural(orig_entries, rebu_entries)
            report.metadata = _layer2_metadata(
                zf_orig, zf_rebu, orig_entries, rebu_entries, is_wheel=True
            )
            report.source = _layer3_source(
                zf_orig, zf_rebu, orig_entries, rebu_entries
            )
    except (zipfile.BadZipFile, OSError) as e:
        report.error = str(e)
        report.verdict = Verdict.FAILED
        return report

    _determine_verdict(report)
    return report


def _determine_verdict(report: SdistComparisonReport) -> None:
    """Set the verdict based on layer results."""
    has_missing_or_extra = (
        report.structural.diff.missing or report.structural.diff.extra
    )
    if has_missing_or_extra:
        report.verdict = Verdict.DIVERGENT
    elif not report.source.match:
        report.verdict = Verdict.DIVERGENT
    elif not report.metadata.match:
        report.verdict = Verdict.DIVERGENT
    else:
        report.verdict = Verdict.EQUIVALENT


def generate_summary(reports: list[SdistComparisonReport]) -> dict:
    """Aggregate stats for batch runs."""
    total = len(reports)
    verdicts = {
        v: 0
        for v in [
            Verdict.IDENTICAL,
            Verdict.EQUIVALENT,
            Verdict.DIVERGENT,
            Verdict.FAILED,
        ]
    }
    for r in reports:
        verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1

    reproducible = verdicts[Verdict.IDENTICAL] + verdicts[Verdict.EQUIVALENT]
    score = reproducible / total if total > 0 else 0.0

    return {
        "total_packages": total,
        "verdicts": verdicts,
        "reproducibility_score": round(score, 4),
        "packages": [
            {"coordinate": r.coordinate, "verdict": r.verdict} for r in reports
        ],
    }


def write_report(report: SdistComparisonReport, output_dir: Path) -> Path:
    """Serialize report to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = report.coordinate.replace("/", "-").replace(":", "-")
    if not safe_name:
        safe_name = "unknown"
    filename = f"{safe_name}-comparison.json"
    path = output_dir / filename
    path.write_text(
        json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Wrote comparison report", path=str(path))
    return path
