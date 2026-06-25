"""Tests for buildroot.eval.report — report generation."""

from __future__ import annotations

import json

from buildroot.agent.models import EvalResult, TestResult
from buildroot.eval.audit import AuditEntry, AuditLog
from buildroot.eval.report import build_report


def _make_eval_result(**overrides) -> EvalResult:
    defaults = {
        "l1_parse": True,
        "l2_build": True,
        "l3_command": True,
        "l4_match": True,
        "l4_score": 1.0,
        "reward": 1.0,
        "level_reached": 4,
        "comparison_verdict": "IDENTICAL",
    }
    defaults.update(overrides)
    r = EvalResult(**defaults)
    return r


def _make_test_result(**overrides) -> TestResult:
    defaults = {
        "available": True,
        "framework": "maven",
        "command": "mvn test -B",
        "passed": True,
        "run": 42,
        "tests_passed": 40,
        "failed": 0,
        "skipped": 2,
        "duration_seconds": 15.3,
        "status": "passed",
    }
    defaults.update(overrides)
    return TestResult(**defaults)


SAMPLE_CF = "FROM openjdk:17\nRUN mvn install -B\n"
SAMPLE_COORD = "org.example:foo:1.0"


class TestBuildReport:
    def test_basic_report(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)

        assert report.report_version == "1.0"
        assert report.coordinate == SAMPLE_COORD
        assert report.reward == 1.0
        assert report.level_reached == 4
        assert report.levels["l1_parse"]["pass"] is True
        assert report.levels["l4_match"]["pass"] is True

    def test_report_with_tests(self):
        tr = _make_test_result()
        result = _make_eval_result(test_result=tr)
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)

        assert report.tests is not None
        assert report.tests["available"] is True
        assert report.tests["run"] == 42
        assert report.tests["framework"] == "maven"

    def test_report_without_tests(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        assert report.tests is None

    def test_report_with_audit_log(self):
        result = _make_eval_result()
        audit = AuditLog(assets=[
            AuditEntry(type="base_image", name="openjdk", source="docker.io", tag="17"),
        ])
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD, audit_log=audit)

        assert report.audit_log is not None
        assert report.audit_log["total_assets"] == 1

    def test_report_without_audit_log(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        assert report.audit_log is None

    def test_report_recipe(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)

        assert report.recipe["containerfile"] == SAMPLE_CF
        assert report.recipe["coordinate"] == SAMPLE_COORD
        assert "reference_jar_url" in report.recipe

    def test_failed_levels(self):
        result = _make_eval_result(
            l1_parse=True, l2_build=False, l3_command=False, l4_match=False,
            l4_score=0.0, reward=0.05, level_reached=1,
            error_summary="L2 build timed out",
        )
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)

        assert report.levels["l1_parse"]["pass"] is True
        assert report.levels["l2_build"]["pass"] is False
        assert "timed out" in report.levels["l2_build"]["details"]

    def test_timestamp_present(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        assert len(report.timestamp) > 0


class TestReportToJson:
    def test_valid_json(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        raw = report.to_json()
        parsed = json.loads(raw)

        assert parsed["report_version"] == "1.0"
        assert parsed["coordinate"] == SAMPLE_COORD
        assert "levels" in parsed
        assert "recipe" in parsed

    def test_json_structure_with_all_fields(self):
        tr = _make_test_result()
        result = _make_eval_result(test_result=tr)
        audit = AuditLog(assets=[
            AuditEntry(type="base_image", name="openjdk", source="docker.io"),
        ])
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD, audit_log=audit)
        parsed = json.loads(report.to_json())

        assert "tests" in parsed
        assert parsed["tests"]["run"] == 42
        assert "audit_log" in parsed
        assert parsed["audit_log"]["total_assets"] == 1

    def test_json_none_tests(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        parsed = json.loads(report.to_json())
        assert parsed["tests"] is None


class TestReportToMarkdown:
    def test_contains_header(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        md = report.to_markdown()

        assert f"# Build Report: {SAMPLE_COORD}" in md
        assert "Reward:" in md
        assert "Level Reached:" in md

    def test_contains_level_table(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        md = report.to_markdown()

        assert "## Level Results" in md
        assert "l1_parse" in md
        assert "l4_match" in md
        assert "PASS" in md

    def test_contains_test_section(self):
        tr = _make_test_result()
        result = _make_eval_result(test_result=tr)
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        md = report.to_markdown()

        assert "## Test Results" in md
        assert "maven" in md
        assert "mvn test -B" in md

    def test_no_test_section_when_none(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        md = report.to_markdown()
        assert "## Test Results" not in md

    def test_contains_audit_section(self):
        result = _make_eval_result()
        audit = AuditLog(assets=[
            AuditEntry(type="base_image", name="openjdk", source="docker.io"),
        ])
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD, audit_log=audit)
        md = report.to_markdown()

        assert "## Supply Chain Audit" in md
        assert "openjdk" in md
        assert "docker.io" in md

    def test_contains_recipe_section(self):
        result = _make_eval_result()
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        md = report.to_markdown()

        assert "## Recipe" in md
        assert "```dockerfile" in md
        assert "FROM openjdk:17" in md

    def test_failed_levels_show_fail(self):
        result = _make_eval_result(
            l2_build=False, l3_command=False, l4_match=False,
            l4_score=0.0, reward=0.05, level_reached=1,
        )
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        md = report.to_markdown()
        assert "FAIL" in md

    def test_divergent_classes_capped(self):
        """Divergent classes in comparison report should be capped at 10."""

        class MockComparison:
            def __init__(self):
                self.verdict = "DIVERGENT"

            def to_dict(self):
                return {
                    "verdict": "DIVERGENT",
                    "structural": {"original_count": 100, "rebuilt_count": 100, "match": True},
                    "metadata": {"match": True, "manifest_diff_keys": []},
                    "bytecode": {
                        "match": False,
                        "classes_compared": 100,
                        "classes_identical": 80,
                        "classes_divergent": [f"com.example.Class{i}" for i in range(20)],
                    },
                }

            def equivalence_score(self):
                return 0.8

        result = _make_eval_result(comparison_report=MockComparison())
        report = build_report(result, SAMPLE_CF, SAMPLE_COORD)
        md = report.to_markdown()
        assert "... 10 more" in md
