"""Unit tests for the multi-layer sdist/wheel comparison pipeline."""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

from buildroot.utils.sdist_comparator import (
    SdistComparisonReport,
    Verdict,
    _layer1_structural,
    _layer2_metadata,
    _layer3_source,
    _normalize_sdist_entries,
    _normalize_wheel_entries,
    compare_sdists,
    compare_wheels,
    generate_summary,
    write_report,
)


def _create_test_sdist(
    path: Path, name: str, version: str, files: dict[str, str]
) -> Path:
    """Create a .tar.gz sdist with given files.

    Files are placed under {name}-{version}/ prefix.
    Always includes PKG-INFO with standard fields.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"{name}-{version}"
    pkg_info = (
        f"Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"Summary: Test package\n"
    )

    with tarfile.open(path, "w:gz") as tf:
        # Add PKG-INFO
        data = pkg_info.encode("utf-8")
        info = tarfile.TarInfo(name=f"{prefix}/PKG-INFO")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

        # Add user-provided files
        for fname, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"{prefix}/{fname}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

    return path


def _create_test_wheel(
    path: Path, name: str, version: str, files: dict[str, str]
) -> Path:
    """Create a .whl (ZIP) with given files.

    Includes METADATA and WHEEL files in {name}-{version}.dist-info/.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    dist_info = f"{name}-{version}.dist-info"
    metadata = (
        f"Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"Summary: Test package\n"
    )
    wheel_info = (
        "Wheel-Version: 1.0\n"
        "Generator: test\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{dist_info}/METADATA", metadata)
        zf.writestr(f"{dist_info}/WHEEL", wheel_info)
        zf.writestr(f"{dist_info}/RECORD", "")
        for fname, content in files.items():
            zf.writestr(fname, content)

    return path


class TestNormalizeSdistEntries:
    def test_strips_top_level_prefix(self, tmp_path):
        sdist = _create_test_sdist(
            tmp_path / "pkg-1.0.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        with tarfile.open(sdist, "r:gz") as tf:
            entries = _normalize_sdist_entries(tf)
        assert "src/main.py" in entries
        assert "PKG-INFO" in entries
        # Should not have the prefix
        assert not any(k.startswith("pkg-1.0/") for k in entries)

    def test_filters_generated_files(self, tmp_path):
        sdist_path = tmp_path / "pkg-1.0.tar.gz"
        with tarfile.open(sdist_path, "w:gz") as tf:
            for fname in [
                "pkg-1.0/src/main.py",
                "pkg-1.0/src/__pycache__/main.cpython-311.pyc",
                "pkg-1.0/pkg.egg-info/PKG-INFO",
            ]:
                data = b"content"
                info = tarfile.TarInfo(name=fname)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

        with tarfile.open(sdist_path, "r:gz") as tf:
            entries = _normalize_sdist_entries(tf)
        assert "src/main.py" in entries
        assert len(entries) == 1  # __pycache__ and .egg-info filtered out


class TestNormalizeWheelEntries:
    def test_keeps_dist_info_prefix(self, tmp_path):
        wheel = _create_test_wheel(
            tmp_path / "pkg-1.0-py3-none-any.whl",
            "pkg",
            "1.0",
            {"pkg/main.py": "pass"},
        )
        with zipfile.ZipFile(wheel) as zf:
            entries = _normalize_wheel_entries(zf)
        assert "pkg-1.0.dist-info/METADATA" in entries
        assert "pkg/main.py" in entries

    def test_filters_generated_files(self, tmp_path):
        wheel_path = tmp_path / "pkg-1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel_path, "w") as zf:
            zf.writestr("pkg/main.py", "pass")
            zf.writestr("pkg/__pycache__/main.cpython-311.pyc", "bytecode")
        with zipfile.ZipFile(wheel_path) as zf:
            entries = _normalize_wheel_entries(zf)
        assert "pkg/main.py" in entries
        assert len(entries) == 1


class TestStructural:
    def test_identical_entries(self, tmp_path):
        sdist = _create_test_sdist(
            tmp_path / "orig.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        with tarfile.open(sdist, "r:gz") as tf:
            entries = _normalize_sdist_entries(tf)
        result = _layer1_structural(entries, entries)
        assert result.match
        assert result.original_count == result.rebuilt_count

    def test_missing_file(self, tmp_path):
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "pass", "src/util.py": "pass"},
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        with tarfile.open(orig, "r:gz") as tf_o, tarfile.open(rebu, "r:gz") as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
        result = _layer1_structural(orig_entries, rebu_entries)
        assert not result.match
        assert "src/util.py" in result.diff.missing

    def test_extra_file(self, tmp_path):
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "pass", "src/extra.py": "pass"},
        )
        with tarfile.open(orig, "r:gz") as tf_o, tarfile.open(rebu, "r:gz") as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
        result = _layer1_structural(orig_entries, rebu_entries)
        assert not result.match
        assert "src/extra.py" in result.diff.extra

    def test_size_mismatch(self, tmp_path):
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz", "pkg", "1.0", {"data.txt": "short"}
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz",
            "pkg",
            "1.0",
            {"data.txt": "much longer content here"},
        )
        with tarfile.open(orig, "r:gz") as tf_o, tarfile.open(rebu, "r:gz") as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
        result = _layer1_structural(orig_entries, rebu_entries)
        assert not result.match
        assert len(result.diff.size_mismatches) >= 1
        mismatch_entries = [m["entry"] for m in result.diff.size_mismatches]
        assert "data.txt" in mismatch_entries


class TestMetadata:
    def test_matching_pkg_info(self, tmp_path):
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        with tarfile.open(orig, "r:gz") as tf_o, tarfile.open(rebu, "r:gz") as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
            result = _layer2_metadata(tf_o, tf_r, orig_entries, rebu_entries)
        assert result.metadata_match
        assert result.match

    def test_differing_pkg_info(self, tmp_path):
        # Build sdists with different PKG-INFO by manually constructing them
        orig_path = tmp_path / "orig.tar.gz"
        rebu_path = tmp_path / "rebu.tar.gz"

        pkg_info_orig = (
            "Metadata-Version: 2.1\nName: pkg\nVersion: 1.0\nSummary: Original\n"
        )
        pkg_info_rebu = (
            "Metadata-Version: 2.1\nName: pkg\nVersion: 1.0\nSummary: Rebuilt\n"
        )

        for p, content in [(orig_path, pkg_info_orig), (rebu_path, pkg_info_rebu)]:
            with tarfile.open(p, "w:gz") as tf:
                data = content.encode("utf-8")
                info = tarfile.TarInfo(name="pkg-1.0/PKG-INFO")
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

        with tarfile.open(orig_path, "r:gz") as tf_o, tarfile.open(
            rebu_path, "r:gz"
        ) as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
            result = _layer2_metadata(tf_o, tf_r, orig_entries, rebu_entries)
        assert not result.metadata_match
        assert "Summary" in result.metadata_diff_fields

    def test_resource_comparison(self, tmp_path):
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz",
            "pkg",
            "1.0",
            {"data/config.json": '{"key": "value"}'},
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz",
            "pkg",
            "1.0",
            {"data/config.json": '{"key": "value"}'},
        )
        with tarfile.open(orig, "r:gz") as tf_o, tarfile.open(rebu, "r:gz") as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
            result = _layer2_metadata(tf_o, tf_r, orig_entries, rebu_entries)
        assert result.resource_matches == 1
        assert len(result.resource_mismatches) == 0
        assert result.match


class TestSource:
    def test_identical_py_files(self, tmp_path):
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "def hello(): pass", "src/util.py": "x = 1"},
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "def hello(): pass", "src/util.py": "x = 1"},
        )
        with tarfile.open(orig, "r:gz") as tf_o, tarfile.open(rebu, "r:gz") as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
            result = _layer3_source(tf_o, tf_r, orig_entries, rebu_entries)
        assert result.match
        assert result.files_compared == 2
        assert result.files_identical == 2

    def test_divergent_py_files(self, tmp_path):
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "def hello(): pass"},
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "def hello(): return 42"},
        )
        with tarfile.open(orig, "r:gz") as tf_o, tarfile.open(rebu, "r:gz") as tf_r:
            orig_entries = _normalize_sdist_entries(tf_o)
            rebu_entries = _normalize_sdist_entries(tf_r)
            result = _layer3_source(tf_o, tf_r, orig_entries, rebu_entries)
        assert not result.match
        assert result.files_compared == 1
        assert "src/main.py" in result.files_divergent


class TestCompareSdists:
    def test_identical_sha256(self, tmp_path):
        """Byte-identical sdists should short-circuit to IDENTICAL."""
        sdist = _create_test_sdist(
            tmp_path / "pkg.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        report = compare_sdists(sdist, sdist, coordinate="pkg==1.0")
        assert report.verdict == Verdict.IDENTICAL
        assert report.sha256_original == report.sha256_rebuilt

    def test_equivalent(self, tmp_path):
        """Same content but different tar compression should be EQUIVALENT."""
        files = {"src/main.py": "pass", "data.txt": "hello"}
        orig = _create_test_sdist(tmp_path / "orig.tar.gz", "pkg", "1.0", files)
        rebu = _create_test_sdist(tmp_path / "rebu.tar.gz", "pkg", "1.0", files)
        report = compare_sdists(orig, rebu, coordinate="pkg==1.0")
        assert report.verdict == Verdict.EQUIVALENT

    def test_divergent(self, tmp_path):
        """Different source should be DIVERGENT."""
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "original_code()"},
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "different_code()"},
        )
        report = compare_sdists(orig, rebu, coordinate="pkg==1.0")
        assert report.verdict == Verdict.DIVERGENT

    def test_missing_file(self, tmp_path):
        """Missing file should return FAILED verdict."""
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        report = compare_sdists(orig, tmp_path / "nonexistent.tar.gz")
        assert report.verdict == Verdict.FAILED
        assert report.error is not None

    def test_divergent_missing_entry(self, tmp_path):
        """Missing entries between archives should be DIVERGENT."""
        orig = _create_test_sdist(
            tmp_path / "orig.tar.gz",
            "pkg",
            "1.0",
            {"src/main.py": "pass", "src/util.py": "pass"},
        )
        rebu = _create_test_sdist(
            tmp_path / "rebu.tar.gz", "pkg", "1.0", {"src/main.py": "pass"}
        )
        report = compare_sdists(orig, rebu, coordinate="pkg==1.0")
        assert report.verdict == Verdict.DIVERGENT


class TestCompareWheels:
    def test_identical_sha256(self, tmp_path):
        wheel = _create_test_wheel(
            tmp_path / "pkg-1.0-py3-none-any.whl",
            "pkg",
            "1.0",
            {"pkg/main.py": "pass"},
        )
        report = compare_wheels(wheel, wheel, coordinate="pkg==1.0")
        assert report.verdict == Verdict.IDENTICAL

    def test_equivalent(self, tmp_path):
        """Same source and metadata but different RECORD (excluded from comparison)."""
        files = {"pkg/main.py": "pass"}
        orig = _create_test_wheel(
            tmp_path / "orig.whl", "pkg", "1.0", files
        )
        # Create rebuilt wheel with a different RECORD to ensure different SHA-256
        rebu_path = tmp_path / "rebu.whl"
        dist_info = "pkg-1.0.dist-info"
        metadata = (
            "Metadata-Version: 2.1\n"
            "Name: pkg\n"
            "Version: 1.0\n"
            "Summary: Test package\n"
        )
        wheel_info = (
            "Wheel-Version: 1.0\n"
            "Generator: test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        )
        with zipfile.ZipFile(rebu_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{dist_info}/METADATA", metadata)
            zf.writestr(f"{dist_info}/WHEEL", wheel_info)
            zf.writestr(f"{dist_info}/RECORD", "different-record-content\n")
            zf.writestr("pkg/main.py", "pass")
        report = compare_wheels(orig, rebu_path, coordinate="pkg==1.0")
        assert report.verdict == Verdict.EQUIVALENT

    def test_divergent_source(self, tmp_path):
        orig = _create_test_wheel(
            tmp_path / "orig.whl", "pkg", "1.0", {"pkg/main.py": "original()"}
        )
        rebu = _create_test_wheel(
            tmp_path / "rebu.whl", "pkg", "1.0", {"pkg/main.py": "different()"}
        )
        report = compare_wheels(orig, rebu, coordinate="pkg==1.0")
        assert report.verdict == Verdict.DIVERGENT

    def test_missing_wheel(self, tmp_path):
        orig = _create_test_wheel(
            tmp_path / "orig.whl", "pkg", "1.0", {"pkg/main.py": "pass"}
        )
        report = compare_wheels(orig, tmp_path / "nonexistent.whl")
        assert report.verdict == Verdict.FAILED
        assert report.error is not None


class TestEquivalenceScore:
    def test_identical_is_1(self):
        report = SdistComparisonReport(verdict=Verdict.IDENTICAL)
        assert report.equivalence_score() == 1.0

    def test_failed_is_0(self):
        report = SdistComparisonReport(verdict=Verdict.FAILED)
        assert report.equivalence_score() == 0.0

    def test_perfect_equivalent(self):
        """All sources match, all resources match, all entries match -> 1.0."""
        from buildroot.utils.sdist_comparator import (
            MetadataResult,
            SourceResult,
            StructuralResult,
        )

        report = SdistComparisonReport(
            verdict=Verdict.EQUIVALENT,
            structural=StructuralResult(
                original_count=5, rebuilt_count=5, match=True
            ),
            metadata=MetadataResult(
                metadata_match=True, resource_matches=2, match=True
            ),
            source=SourceResult(
                files_compared=3, files_identical=3, match=True
            ),
        )
        assert report.equivalence_score() == 1.0

    def test_partial_source_divergence(self):
        """Half the source files diverge."""
        from buildroot.utils.sdist_comparator import (
            MetadataResult,
            SourceResult,
            StructuralResult,
        )

        report = SdistComparisonReport(
            verdict=Verdict.DIVERGENT,
            structural=StructuralResult(
                original_count=4, rebuilt_count=4, match=True
            ),
            metadata=MetadataResult(
                metadata_match=True, resource_matches=1, match=True
            ),
            source=SourceResult(
                files_compared=2,
                files_identical=1,
                files_divergent=["a.py"],
                match=False,
            ),
        )
        score = report.equivalence_score()
        # source: 0.5 * 0.50 = 0.25
        # resource: 1.0 * 0.25 = 0.25
        # entry: 1.0 * 0.25 = 0.25
        assert abs(score - 0.75) < 0.001

    def test_scoring_weights(self):
        """Verify the 50/25/25 weighting formula."""
        from buildroot.utils.sdist_comparator import (
            EntryDiff,
            MetadataResult,
            SourceResult,
            StructuralResult,
        )

        report = SdistComparisonReport(
            verdict=Verdict.DIVERGENT,
            structural=StructuralResult(
                original_count=10,
                rebuilt_count=8,
                diff=EntryDiff(missing=["a.py", "b.py"]),
                match=False,
            ),
            metadata=MetadataResult(
                metadata_match=True,
                resource_matches=1,
                resource_mismatches=["c.txt"],
                match=False,
            ),
            source=SourceResult(
                files_compared=4,
                files_identical=3,
                files_divergent=["d.py"],
                match=False,
            ),
        )
        score = report.equivalence_score()
        # source_ratio = 3/4 = 0.75 -> 0.50 * 0.75 = 0.375
        # resource_ratio = 1/2 = 0.50 -> 0.25 * 0.50 = 0.125
        # entry_score = 1 - 2/10 = 0.80 -> 0.25 * 0.80 = 0.200
        expected = 0.375 + 0.125 + 0.200
        assert abs(score - expected) < 0.001


class TestReportSerialization:
    def test_to_dict(self):
        report = SdistComparisonReport(
            coordinate="pkg==1.0", verdict=Verdict.IDENTICAL
        )
        d = report.to_dict()
        assert d["coordinate"] == "pkg==1.0"
        assert d["verdict"] == "IDENTICAL"
        assert "structural" in d
        assert "metadata" in d
        assert "source" in d

    def test_to_dict_fields(self):
        report = SdistComparisonReport(
            coordinate="pkg==2.0", verdict=Verdict.EQUIVALENT
        )
        d = report.to_dict()
        assert "original_count" in d["structural"]
        assert "rebuilt_count" in d["structural"]
        assert "missing_entries" in d["structural"]
        assert "metadata_match" in d["metadata"]
        assert "files_compared" in d["source"]

    def test_write_report(self, tmp_path):
        report = SdistComparisonReport(
            coordinate="my-pkg==2.0", verdict=Verdict.EQUIVALENT
        )
        path = write_report(report, tmp_path / "output")
        assert path.exists()
        assert path.name == "my-pkg==2.0-comparison.json"
        data = json.loads(path.read_text())
        assert data["verdict"] == "EQUIVALENT"

    def test_write_report_creates_directory(self, tmp_path):
        report = SdistComparisonReport(
            coordinate="pkg==1.0", verdict=Verdict.IDENTICAL
        )
        output_dir = tmp_path / "nested" / "output"
        path = write_report(report, output_dir)
        assert path.exists()
        assert output_dir.exists()


class TestGenerateSummary:
    def test_summary_with_mixed_verdicts(self):
        reports = [
            SdistComparisonReport(coordinate="a==1", verdict=Verdict.IDENTICAL),
            SdistComparisonReport(coordinate="b==1", verdict=Verdict.EQUIVALENT),
            SdistComparisonReport(coordinate="c==1", verdict=Verdict.DIVERGENT),
            SdistComparisonReport(coordinate="d==1", verdict=Verdict.FAILED),
        ]
        summary = generate_summary(reports)
        assert summary["total_packages"] == 4
        assert summary["reproducibility_score"] == 0.5
        assert summary["verdicts"]["IDENTICAL"] == 1
        assert summary["verdicts"]["EQUIVALENT"] == 1

    def test_summary_all_identical(self):
        reports = [
            SdistComparisonReport(coordinate=f"pkg=={i}", verdict=Verdict.IDENTICAL)
            for i in range(3)
        ]
        summary = generate_summary(reports)
        assert summary["reproducibility_score"] == 1.0

    def test_summary_empty(self):
        summary = generate_summary([])
        assert summary["total_packages"] == 0
        assert summary["reproducibility_score"] == 0.0
