"""Unit tests for the multi-layer JAR comparison pipeline."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from buildroot.utils.jar_comparator import (
    ComparisonReport,
    Verdict,
    _layer1_structural,
    _layer2_metadata,
    _layer3_bytecode,
    _parse_manifest,
    _strip_properties_timestamps,
    compare_jars,
    generate_summary,
    write_report,
)


def _create_jar(path: Path, entries: dict[str, bytes]) -> Path:
    """Create a synthetic JAR (ZIP) with the given entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


class TestParseManifest:
    def test_basic_parsing(self):
        raw = "Manifest-Version: 1.0\nBuilt-By: ci\nBuild-Jdk: 11.0.2\n"
        result = _parse_manifest(raw)
        assert result["Manifest-Version"] == "1.0"
        assert result["Built-By"] == "ci"
        assert result["Build-Jdk"] == "11.0.2"

    def test_continuation_lines(self):
        raw = "Implementation-Title: My Very Long\n Title Here\nOther-Key: val\n"
        result = _parse_manifest(raw)
        assert result["Implementation-Title"] == "My Very LongTitle Here"
        assert result["Other-Key"] == "val"

    def test_empty_manifest(self):
        assert _parse_manifest("") == {}


class TestStripPropertiesTimestamps:
    def test_strips_timestamp_comments(self):
        content = "#Mon Jan 01 00:00:00 UTC 2024\nkey=value\n"
        assert _strip_properties_timestamps(content) == "key=value"

    def test_preserves_non_timestamp_comments(self):
        content = "# Simple comment\nkey=value\n"
        result = _strip_properties_timestamps(content)
        assert "key=value" in result


class TestLayer1Structural:
    def test_identical_entries(self, tmp_path):
        entries = {"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n", "com/Example.class": b"\xca\xfe\xba\xbe"}
        orig = _create_jar(tmp_path / "orig.jar", entries)
        rebu = _create_jar(tmp_path / "rebu.jar", entries)
        result = _layer1_structural(orig, rebu)
        assert result.match
        assert result.original_count == 2
        assert result.rebuilt_count == 2

    def test_missing_entry(self, tmp_path):
        orig = _create_jar(tmp_path / "orig.jar", {"a.class": b"A", "b.class": b"B"})
        rebu = _create_jar(tmp_path / "rebu.jar", {"a.class": b"A"})
        result = _layer1_structural(orig, rebu)
        assert not result.match
        assert "b.class" in result.diff.missing

    def test_extra_entry(self, tmp_path):
        orig = _create_jar(tmp_path / "orig.jar", {"a.class": b"A"})
        rebu = _create_jar(tmp_path / "rebu.jar", {"a.class": b"A", "c.class": b"C"})
        result = _layer1_structural(orig, rebu)
        assert not result.match
        assert "c.class" in result.diff.extra

    def test_size_mismatch(self, tmp_path):
        orig = _create_jar(tmp_path / "orig.jar", {"a.txt": b"short"})
        rebu = _create_jar(tmp_path / "rebu.jar", {"a.txt": b"much longer content"})
        result = _layer1_structural(orig, rebu)
        assert not result.match
        assert len(result.diff.size_mismatches) == 1

    def test_crc_mismatch(self, tmp_path):
        orig = _create_jar(tmp_path / "orig.jar", {"a.txt": b"content-a"})
        rebu = _create_jar(tmp_path / "rebu.jar", {"a.txt": b"content-b"})
        result = _layer1_structural(orig, rebu)
        assert not result.match
        assert len(result.diff.crc_mismatches) == 1


class TestLayer2Metadata:
    def test_manifest_non_deterministic_keys_ignored(self, tmp_path):
        orig_manifest = "Manifest-Version: 1.0\nBuilt-By: ci-user\nBuild-Jdk: 11.0.1\nImpl: foo\n"
        rebu_manifest = "Manifest-Version: 1.0\nBuilt-By: local-user\nBuild-Jdk: 17.0.1\nImpl: foo\n"
        orig = _create_jar(tmp_path / "orig.jar", {"META-INF/MANIFEST.MF": orig_manifest.encode()})
        rebu = _create_jar(tmp_path / "rebu.jar", {"META-INF/MANIFEST.MF": rebu_manifest.encode()})
        result = _layer2_metadata(orig, rebu)
        assert result.manifest_match
        assert result.match

    def test_manifest_meaningful_diff(self, tmp_path):
        orig_manifest = "Manifest-Version: 1.0\nBundle-Version: 1.0\n"
        rebu_manifest = "Manifest-Version: 1.0\nBundle-Version: 2.0\n"
        orig = _create_jar(tmp_path / "orig.jar", {"META-INF/MANIFEST.MF": orig_manifest.encode()})
        rebu = _create_jar(tmp_path / "rebu.jar", {"META-INF/MANIFEST.MF": rebu_manifest.encode()})
        result = _layer2_metadata(orig, rebu)
        assert not result.manifest_match
        assert "Bundle-Version" in result.manifest_diff_keys

    def test_resource_match(self, tmp_path):
        entries = {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "config.xml": b"<config/>",
        }
        orig = _create_jar(tmp_path / "orig.jar", entries)
        rebu = _create_jar(tmp_path / "rebu.jar", entries)
        result = _layer2_metadata(orig, rebu)
        assert result.match
        assert result.resource_matches == 1

    def test_properties_timestamp_stripped(self, tmp_path):
        orig_props = b"#Mon Jan 01 00:00:00 UTC 2024\nkey=value\n"
        rebu_props = b"#Tue Feb 02 12:00:00 UTC 2025\nkey=value\n"
        orig = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "app.properties": orig_props,
        })
        rebu = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "app.properties": rebu_props,
        })
        result = _layer2_metadata(orig, rebu)
        assert result.match
        assert result.resource_matches == 1


class TestLayer3Bytecode:
    def test_identical_class_bytes(self, tmp_path):
        """Identical .class bytes should be counted as identical without decompilation."""
        class_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x0a" + b"\x00" * 50
        orig = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "com/example/Foo.class": class_bytes,
        })
        rebu = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "com/example/Foo.class": class_bytes,
        })
        result = _layer3_bytecode(orig, rebu)
        assert result.match
        assert result.classes_compared == 1
        assert result.classes_identical == 1
        assert result.classes_divergent == []

    def test_divergent_class_bytes(self, tmp_path):
        """Different .class bytes with no decompiler should be marked divergent."""
        orig_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x0a" + b"\x01" * 50
        rebu_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x0a" + b"\x02" * 50
        orig = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "com/example/Bar.class": orig_bytes,
        })
        rebu = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "com/example/Bar.class": rebu_bytes,
        })
        result = _layer3_bytecode(orig, rebu)
        assert not result.match
        assert result.classes_compared == 1
        assert "com/example/Bar.class" in result.classes_divergent

    def test_multiple_classes_mixed(self, tmp_path):
        """Mix of identical and divergent .class files."""
        same_bytes = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\xaa" * 40
        diff_a = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\xbb" * 40
        diff_b = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\xcc" * 40
        orig = _create_jar(tmp_path / "orig.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "com/Same.class": same_bytes,
            "com/Diff.class": diff_a,
        })
        rebu = _create_jar(tmp_path / "rebu.jar", {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "com/Same.class": same_bytes,
            "com/Diff.class": diff_b,
        })
        result = _layer3_bytecode(orig, rebu)
        assert not result.match
        assert result.classes_compared == 2
        assert result.classes_identical == 1
        assert "com/Diff.class" in result.classes_divergent


class TestCompareJars:
    def test_identical_jars(self, tmp_path):
        entries = {"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n", "data.txt": b"hello"}
        orig = _create_jar(tmp_path / "orig.jar", entries)
        rebu = _create_jar(tmp_path / "rebu.jar", entries)
        report = compare_jars(orig, rebu, coordinate="g:a:1.0")
        assert report.verdict == Verdict.IDENTICAL
        assert report.sha256_original == report.sha256_rebuilt

    def test_missing_jar(self, tmp_path):
        orig = _create_jar(tmp_path / "orig.jar", {"a.txt": b"a"})
        report = compare_jars(orig, tmp_path / "nonexistent.jar")
        assert report.verdict == Verdict.FAILED
        assert report.error is not None

    def test_divergent_entries(self, tmp_path):
        orig = _create_jar(tmp_path / "orig.jar", {"a.class": b"A", "b.class": b"B"})
        rebu = _create_jar(tmp_path / "rebu.jar", {"a.class": b"A"})
        report = compare_jars(orig, rebu, coordinate="g:a:1.0")
        assert report.verdict == Verdict.DIVERGENT

    def test_equivalent_metadata_only_diff(self, tmp_path):
        orig_manifest = b"Manifest-Version: 1.0\nBuilt-By: ci\n"
        rebu_manifest = b"Manifest-Version: 1.0\nBuilt-By: local\n"
        orig = _create_jar(tmp_path / "orig.jar", {"META-INF/MANIFEST.MF": orig_manifest})
        rebu = _create_jar(tmp_path / "rebu.jar", {"META-INF/MANIFEST.MF": rebu_manifest})
        report = compare_jars(orig, rebu, coordinate="g:a:1.0")
        assert report.verdict == Verdict.EQUIVALENT


class TestEquivalenceScore:
    def test_identical_returns_1(self):
        report = ComparisonReport(verdict=Verdict.IDENTICAL)
        assert report.equivalence_score() == 1.0

    def test_no_classes_no_resources_scores_low(self):
        report = ComparisonReport(verdict=Verdict.DIVERGENT)
        score = report.equivalence_score()
        assert score < 0.20, "empty DIVERGENT report should score low"

    def test_bytecode_match_manifest_mismatch(self):
        """The kie-api pattern: bytecode matches, manifest doesn't, CRC mismatches exist."""
        from buildroot.utils.jar_comparator import (
            BytecodeResult,
            MetadataResult,
            StructuralResult,
            EntryDiff,
        )
        report = ComparisonReport(
            verdict=Verdict.DIVERGENT,
            structural=StructuralResult(
                original_count=100,
                rebuilt_count=100,
                diff=EntryDiff(
                    crc_mismatches=[{"entry": f"e{i}"} for i in range(20)],
                ),
                match=False,
            ),
            metadata=MetadataResult(
                manifest_match=False,
                manifest_diff_keys=["Bundle-Version"],
                resource_matches=10,
                resource_mismatches=[],
                match=False,
            ),
            bytecode=BytecodeResult(
                classes_compared=80,
                classes_identical=80,
                match=True,
            ),
        )
        score = report.equivalence_score()
        assert score < 1.0, "DIVERGENT build must not score 1.0"
        assert score > 0.7, "bytecode-matching build should still score high"

    def test_manifest_mismatch_penalized(self):
        """Manifest mismatch must reduce the score vs manifest match."""
        from buildroot.utils.jar_comparator import (
            BytecodeResult,
            MetadataResult,
            StructuralResult,
        )
        base_kwargs = dict(
            verdict=Verdict.DIVERGENT,
            structural=StructuralResult(original_count=10, rebuilt_count=10, match=True),
            bytecode=BytecodeResult(classes_compared=10, classes_identical=10, match=True),
        )
        with_match = ComparisonReport(
            **base_kwargs,
            metadata=MetadataResult(manifest_match=True, resource_matches=5, match=True),
        )
        without_match = ComparisonReport(
            **base_kwargs,
            metadata=MetadataResult(
                manifest_match=False, manifest_diff_keys=["X"], resource_matches=5, match=False,
            ),
        )
        assert without_match.equivalence_score() < with_match.equivalence_score()

    def test_crc_mismatches_penalized(self):
        """CRC mismatches must reduce the score vs no mismatches."""
        from buildroot.utils.jar_comparator import (
            BytecodeResult,
            MetadataResult,
            StructuralResult,
            EntryDiff,
        )
        base_kwargs = dict(
            verdict=Verdict.DIVERGENT,
            metadata=MetadataResult(manifest_match=True, resource_matches=5, match=True),
            bytecode=BytecodeResult(classes_compared=10, classes_identical=10, match=True),
        )
        no_crc = ComparisonReport(
            **base_kwargs,
            structural=StructuralResult(original_count=50, rebuilt_count=50, match=True),
        )
        with_crc = ComparisonReport(
            **base_kwargs,
            structural=StructuralResult(
                original_count=50, rebuilt_count=50,
                diff=EntryDiff(crc_mismatches=[{"entry": f"e{i}"} for i in range(10)]),
                match=False,
            ),
        )
        assert with_crc.equivalence_score() < no_crc.equivalence_score()


class TestReportSerialization:
    def test_to_dict(self):
        report = ComparisonReport(coordinate="g:a:1.0", verdict=Verdict.IDENTICAL)
        d = report.to_dict()
        assert d["coordinate"] == "g:a:1.0"
        assert d["verdict"] == "IDENTICAL"
        assert "structural" in d
        assert "metadata" in d
        assert "bytecode" in d

    def test_write_report(self, tmp_path):
        report = ComparisonReport(coordinate="org.example:mylib:2.0", verdict=Verdict.EQUIVALENT)
        path = write_report(report, tmp_path / "output")
        assert path.exists()
        assert path.name == "mylib-2.0-comparison.json"
        data = json.loads(path.read_text())
        assert data["verdict"] == "EQUIVALENT"


class TestGenerateSummary:
    def test_summary_with_mixed_verdicts(self):
        reports = [
            ComparisonReport(coordinate="g:a:1", verdict=Verdict.IDENTICAL),
            ComparisonReport(coordinate="g:b:1", verdict=Verdict.EQUIVALENT),
            ComparisonReport(coordinate="g:c:1", verdict=Verdict.DIVERGENT),
            ComparisonReport(coordinate="g:d:1", verdict=Verdict.FAILED),
        ]
        summary = generate_summary(reports)
        assert summary["total_packages"] == 4
        assert summary["reproducibility_score"] == 0.5
        assert summary["verdicts"]["IDENTICAL"] == 1
        assert summary["verdicts"]["EQUIVALENT"] == 1

    def test_summary_all_identical(self):
        reports = [ComparisonReport(coordinate=f"g:a:{i}", verdict=Verdict.IDENTICAL) for i in range(3)]
        summary = generate_summary(reports)
        assert summary["reproducibility_score"] == 1.0

    def test_summary_empty(self):
        summary = generate_summary([])
        assert summary["total_packages"] == 0
        assert summary["reproducibility_score"] == 0.0
