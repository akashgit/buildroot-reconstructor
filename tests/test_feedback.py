"""Tests for the v3 feedback module."""

from __future__ import annotations

import tempfile
from pathlib import Path


from buildroot.agent.feedback import (
    build_feedback_context,
    compute_template_value_diff,
    hash_template_values,
    _format_value,
)
from buildroot.agent.models import EvalResult, FailedApproach


def _make_eval(reward: float = 0.5, level: int = 3, error: str = "", diff: str = "") -> EvalResult:
    r = EvalResult()
    r.reward = reward
    r.level_reached = level
    r.error_summary = error
    r.diff_summary = diff
    return r


class TestBuildFeedbackContext:
    def test_basic_feedback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "build_iter1.log").write_text("build log content")

            ctx = build_feedback_context(
                current_values={"jdk_version": "17", "build_system": "maven"},
                best_values={"jdk_version": "17", "build_system": "maven"},
                eval_result=_make_eval(0.5, 3),
                comparison_report=None,
                score_history=[{"iteration": 1, "reward": 0.5, "level": 3, "delta": 0.0}],
                failed_approaches=[],
                containerfile="FROM eclipse-temurin:17-jdk\nRUN mvn clean install",
                workspace=ws,
                iteration=1,
            )
            assert "Iteration 1/10" in ctx
            assert "L3" in ctx
            assert "0.5000" in ctx
            assert "FROM eclipse-temurin" in ctx

    def test_regression_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "build_iter2.log").write_text("")

            ctx = build_feedback_context(
                current_values={"jdk_version": "11"},
                best_values={"jdk_version": "17"},
                eval_result=_make_eval(0.3, 2),
                comparison_report=None,
                score_history=[
                    {"iteration": 1, "reward": 0.5, "level": 3, "delta": 0.0},
                    {"iteration": 2, "reward": 0.3, "level": 2, "delta": -0.2},
                ],
                failed_approaches=[],
                containerfile="FROM jdk:11",
                workspace=ws,
                iteration=2,
            )
            assert "REGRESSION" in ctx

    def test_build_error_at_l1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            ctx = build_feedback_context(
                current_values={},
                best_values={},
                eval_result=_make_eval(0.0, 0, error="Parse error: missing FROM"),
                comparison_report=None,
                score_history=[{"iteration": 1, "reward": 0.0, "level": 0, "delta": 0.0}],
                failed_approaches=[],
                containerfile="INVALID",
                workspace=ws,
                iteration=1,
            )
            assert "Parse error" in ctx
            assert "Containerfile failed to parse" in ctx

    def test_l3_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            ctx = build_feedback_context(
                current_values={},
                best_values={},
                eval_result=_make_eval(0.5, 3, diff="bytecode_match=False"),
                comparison_report=None,
                score_history=[{"iteration": 1, "reward": 0.5, "level": 3, "delta": 0.0}],
                failed_approaches=[],
                containerfile="FROM jdk",
                workspace=ws,
                iteration=1,
            )
            assert "JDK version mismatch" in ctx

    def test_failed_approaches_included(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            fas = [
                FailedApproach(
                    what_changed="jdk_version",
                    from_value="17",
                    to_value="11",
                    result="reward 0.50 → 0.30",
                    why_it_failed="JDK mismatch",
                    iteration=1,
                ),
            ]
            ctx = build_feedback_context(
                current_values={},
                best_values={},
                eval_result=_make_eval(0.3, 2),
                comparison_report=None,
                score_history=[{"iteration": 1, "reward": 0.3, "level": 2, "delta": 0.0}],
                failed_approaches=fas,
                containerfile="FROM jdk",
                workspace=ws,
                iteration=2,
            )
            assert "Failed Approaches" in ctx
            assert "jdk_version" in ctx
            assert "17" in ctx
            assert "11" in ctx

    def test_score_history_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            history = [
                {"iteration": 1, "reward": 0.15, "level": 2, "delta": 0.0},
                {"iteration": 2, "reward": 0.50, "level": 3, "delta": 0.35},
                {"iteration": 3, "reward": 0.50, "level": 3, "delta": 0.0},
            ]
            ctx = build_feedback_context(
                current_values={},
                best_values={},
                eval_result=_make_eval(0.5, 3),
                comparison_report=None,
                score_history=history,
                failed_approaches=[],
                containerfile="FROM jdk",
                workspace=ws,
                iteration=3,
            )
            assert "Score History" in ctx
            assert "Iter" in ctx
            assert "0.1500" in ctx

    def test_containerfile_included(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            cf = "FROM eclipse-temurin:17-jdk\nWORKDIR /build\nRUN mvn clean install"
            ctx = build_feedback_context(
                current_values={},
                best_values={},
                eval_result=_make_eval(0.5, 3),
                comparison_report=None,
                score_history=[],
                failed_approaches=[],
                containerfile=cf,
                workspace=ws,
                iteration=1,
            )
            assert "Rendered Containerfile" in ctx
            assert "FROM eclipse-temurin:17-jdk" in ctx

    def test_build_log_path_referenced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            log_path = ws / "build_iter1.log"
            log_path.write_text("some log content")
            ctx = build_feedback_context(
                current_values={},
                best_values={},
                eval_result=_make_eval(0.15, 2),
                comparison_report=None,
                score_history=[],
                failed_approaches=[],
                containerfile="FROM jdk",
                workspace=ws,
                iteration=1,
            )
            assert "build_iter1.log" in ctx
            assert "Read this file" in ctx

    def test_l4_jar_comparison_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "prepass" / "original_jar").mkdir(parents=True)
            eval_r = _make_eval(0.8, 3)
            eval_r.l4_score = 0.6
            ctx = build_feedback_context(
                current_values={},
                best_values={},
                eval_result=eval_r,
                comparison_report=None,
                score_history=[],
                failed_approaches=[],
                containerfile="FROM jdk",
                workspace=ws,
                iteration=1,
            )
            assert "original_jar" in ctx
            assert "diff -r" in ctx


class TestComputeTemplateValueDiff:
    def test_no_changes(self):
        prev = {"jdk_version": "17", "build_system": "maven"}
        curr = {"jdk_version": "17", "build_system": "maven"}
        diff = compute_template_value_diff(prev, curr)
        assert "No changes" in diff

    def test_single_change(self):
        prev = {"jdk_version": "17"}
        curr = {"jdk_version": "11"}
        diff = compute_template_value_diff(prev, curr)
        assert "jdk_version" in diff
        assert "17" in diff
        assert "11" in diff

    def test_multiple_changes(self):
        prev = {"jdk_version": "17", "build_system": "maven", "maven_version": "3.9.6"}
        curr = {"jdk_version": "11", "build_system": "gradle", "maven_version": "3.9.6"}
        diff = compute_template_value_diff(prev, curr)
        assert "jdk_version" in diff
        assert "build_system" in diff
        assert "maven_version" not in diff

    def test_new_field_added(self):
        prev = {"jdk_version": "17"}
        curr = {"jdk_version": "17", "module_path": "core"}
        diff = compute_template_value_diff(prev, curr)
        assert "module_path" in diff

    def test_empty_inputs(self):
        assert compute_template_value_diff({}, {}) == ""
        assert compute_template_value_diff(None, None) == ""

    def test_confidence_notes_excluded(self):
        prev = {"jdk_version": "17", "confidence_notes": "old note"}
        curr = {"jdk_version": "17", "confidence_notes": "new note"}
        diff = compute_template_value_diff(prev, curr)
        assert "No changes" in diff

    def test_list_change(self):
        prev = {"system_packages": ["git"]}
        curr = {"system_packages": ["git", "curl"]}
        diff = compute_template_value_diff(prev, curr)
        assert "system_packages" in diff


class TestHashTemplateValues:
    def test_same_values_same_hash(self):
        v1 = {"jdk_version": "17", "build_system": "maven"}
        v2 = {"build_system": "maven", "jdk_version": "17"}
        assert hash_template_values(v1) == hash_template_values(v2)

    def test_different_values_different_hash(self):
        v1 = {"jdk_version": "17"}
        v2 = {"jdk_version": "11"}
        assert hash_template_values(v1) != hash_template_values(v2)

    def test_confidence_notes_ignored(self):
        v1 = {"jdk_version": "17", "confidence_notes": "high"}
        v2 = {"jdk_version": "17", "confidence_notes": "low"}
        assert hash_template_values(v1) == hash_template_values(v2)

    def test_hash_is_deterministic(self):
        v = {"a": "1", "b": [1, 2], "c": {"x": "y"}}
        h1 = hash_template_values(v)
        h2 = hash_template_values(v)
        assert h1 == h2

    def test_hash_length(self):
        h = hash_template_values({"a": "1"})
        assert len(h) == 16


class TestFormatValue:
    def test_none(self):
        assert _format_value(None) == "null"

    def test_string(self):
        assert _format_value("hello") == "hello"

    def test_empty_list(self):
        assert _format_value([]) == "[]"

    def test_empty_dict(self):
        assert _format_value({}) == "{}"

    def test_list_with_values(self):
        result = _format_value(["a", "b"])
        assert "a" in result
        assert "b" in result
