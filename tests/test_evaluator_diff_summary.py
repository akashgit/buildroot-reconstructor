"""Tests for evaluator diff_summary extraction after A1 bug fix."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from buildroot.agent.evaluator import Evaluator
from buildroot.utils.jar_comparator import (
    BytecodeResult,
    ComparisonReport,
    EntryDiff,
    MetadataResult,
    StructuralResult,
    Verdict,
)


def _make_report(
    *,
    verdict: str = Verdict.DIVERGENT,
    missing: list[str] | None = None,
    extra: list[str] | None = None,
    manifest_diff_keys: list[str] | None = None,
    classes_divergent: list[str] | None = None,
) -> ComparisonReport:
    structural = StructuralResult(
        original_count=10,
        rebuilt_count=10,
        diff=EntryDiff(
            missing=missing or [],
            extra=extra or [],
        ),
        match=not (missing or extra),
    )
    metadata = MetadataResult(
        manifest_match=not manifest_diff_keys,
        manifest_diff_keys=manifest_diff_keys or [],
        match=not manifest_diff_keys,
    )
    bytecode = BytecodeResult(
        classes_compared=5,
        classes_identical=5 - len(classes_divergent or []),
        classes_divergent=classes_divergent or [],
        match=not classes_divergent,
    )
    return ComparisonReport(
        verdict=verdict,
        structural=structural,
        metadata=metadata,
        bytecode=bytecode,
    )


class TestDiffSummaryExtraction:
    """Verify that evaluator._l4_match correctly extracts diff details after the A1 fix."""

    def _run_l4_with_report(self, report: ComparisonReport):
        evaluator = Evaluator(host="test-host")
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        result.l1_parse = True
        result.l2_build = True
        result.l3_command = True

        with (
            patch.object(evaluator, "_download_original_jar", return_value="/tmp/orig.jar"),
            patch.object(evaluator, "_extract_rebuilt_jar", return_value="/tmp/rebuilt.jar"),
            patch("buildroot.agent.evaluator.compare_jars", return_value=report),
        ):
            evaluator._l4_match("test-tag", "org.example:test:1.0", result)
        return result

    def test_missing_files_in_diff_summary(self):
        report = _make_report(missing=["com/example/Foo.class", "META-INF/extra.xml"])
        result = self._run_l4_with_report(report)
        assert "missing_files=" in result.diff_summary
        assert "com/example/Foo.class" in result.diff_summary

    def test_extra_files_in_diff_summary(self):
        report = _make_report(extra=["com/extra/Bar.class"])
        result = self._run_l4_with_report(report)
        assert "extra_files=" in result.diff_summary
        assert "com/extra/Bar.class" in result.diff_summary

    def test_metadata_diffs_in_diff_summary(self):
        report = _make_report(manifest_diff_keys=["Implementation-Version", "Bundle-Name"])
        result = self._run_l4_with_report(report)
        assert "metadata_diffs=" in result.diff_summary
        assert "Implementation-Version" in result.diff_summary

    def test_bytecode_diffs_in_diff_summary(self):
        report = _make_report(classes_divergent=["com/example/Main.class"])
        result = self._run_l4_with_report(report)
        assert "bytecode_diffs=" in result.diff_summary
        assert "com/example/Main.class" in result.diff_summary

    def test_all_diffs_combined(self):
        report = _make_report(
            missing=["A.class"],
            extra=["B.class"],
            manifest_diff_keys=["Key1"],
            classes_divergent=["C.class"],
        )
        result = self._run_l4_with_report(report)
        assert "missing_files=" in result.diff_summary
        assert "extra_files=" in result.diff_summary
        assert "metadata_diffs=" in result.diff_summary
        assert "bytecode_diffs=" in result.diff_summary

    def test_no_diffs_when_equivalent(self):
        report = _make_report(verdict=Verdict.EQUIVALENT)
        result = self._run_l4_with_report(report)
        assert result.l4_match is True  # EQUIVALENT treated as match
        assert "missing_files=" not in result.diff_summary

    def test_identical_sets_l4_match(self):
        report = ComparisonReport(
            verdict=Verdict.IDENTICAL,
            structural=StructuralResult(match=True),
            metadata=MetadataResult(match=True),
            bytecode=BytecodeResult(match=True),
        )
        result = self._run_l4_with_report(report)
        assert result.l4_match is True

    def test_diff_summary_truncates_long_lists(self):
        report = _make_report(
            missing=[f"file{i}.class" for i in range(20)],
        )
        result = self._run_l4_with_report(report)
        assert "missing_files=" in result.diff_summary
        # Only first 5 should appear
        parsed = result.diff_summary
        assert "file0.class" in parsed
        assert "file4.class" in parsed

    def test_structural_match_true_no_missing_files(self):
        report = _make_report(manifest_diff_keys=["SomeKey"])
        result = self._run_l4_with_report(report)
        assert "missing_files=" not in result.diff_summary
        assert "metadata_diffs=" in result.diff_summary

    def test_diff_summary_has_basic_fields(self):
        report = _make_report(missing=["x.class"])
        result = self._run_l4_with_report(report)
        assert "verdict=DIVERGENT" in result.diff_summary
        assert "structural_match=" in result.diff_summary
        assert "metadata_match=" in result.diff_summary
        assert "bytecode_match=" in result.diff_summary
