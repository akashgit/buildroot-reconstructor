"""Tests for agent data models — BuildAttempt, DeadEndEntry, EvalResult, AdvisoryFinding."""

from buildroot.agent.models import (
    AdvisoryFinding,
    BuildAttempt,
    DeadEndEntry,
    EvalResult,
    TestResult,
)


class TestDeadEndEntry:
    def test_not_exhausted_initially(self):
        de = DeadEndEntry(error_class="test", approach="try1")
        assert not de.is_exhausted

    def test_exhausted_after_threshold(self):
        de = DeadEndEntry(error_class="test", approach="try1", threshold=2)
        de.record_failure("error 1")
        assert not de.is_exhausted
        de.record_failure("error 2")
        assert de.is_exhausted

    def test_examples_capped_at_3(self):
        de = DeadEndEntry(error_class="test", approach="try1")
        for i in range(5):
            de.record_failure(f"error {i}")
        assert len(de.examples) == 3

    def test_to_dict(self):
        de = DeadEndEntry(error_class="jdk", approach="use jdk 11")
        de.record_failure("failed")
        d = de.to_dict()
        assert d["error_class"] == "jdk"
        assert d["failure_count"] == 1
        assert d["is_exhausted"] is False

    def test_custom_threshold(self):
        de = DeadEndEntry(error_class="test", approach="try1", threshold=5)
        for _ in range(4):
            de.record_failure("err")
        assert not de.is_exhausted
        de.record_failure("err")
        assert de.is_exhausted


def _passing_test_result():
    """Helper: a TestResult where tests actually ran and passed."""
    return TestResult(available=True, framework="maven", passed=True, run=10, tests_passed=10, status="passed")


class TestEvalResult:
    def test_all_levels_pass(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True, l4_match=True,
                        test_result=_passing_test_result())
        reward = er.compute_reward()
        assert reward == 1.0
        assert er.level_reached == 4

    def test_all_levels_pass_no_test_result_caps_reward(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True, l4_match=True)
        reward = er.compute_reward()
        assert abs(reward - 0.85) < 1e-9
        assert er.level_reached == 4  # l4_match is set, level is 4 despite lower reward

    def test_no_levels_pass(self):
        er = EvalResult()
        reward = er.compute_reward()
        assert reward == 0.0
        assert er.level_reached == 0

    def test_l1_only(self):
        er = EvalResult(l1_parse=True)
        reward = er.compute_reward()
        assert reward == 0.05
        assert er.level_reached == 1

    def test_l1_l2(self):
        er = EvalResult(l1_parse=True, l2_build=True)
        reward = er.compute_reward()
        assert abs(reward - 0.15) < 1e-9
        assert er.level_reached == 2

    def test_l1_l2_l3(self):
        er = EvalResult(l1_parse=True, l2_build=True, l3_command=True)
        reward = er.compute_reward()
        assert reward == 0.50
        assert er.level_reached == 3

    def test_l4prime_high_score_promotes_to_level_4(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=1.0, l4_signal_source="fallback_signals",
            test_result=_passing_test_result(),
        )
        er.compute_reward()
        assert er.reward == 1.0
        assert er.level_reached == 4

    def test_l4prime_low_score_stays_level_3(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.7, l4_signal_source="fallback_signals",
        )
        er.compute_reward()
        assert er.level_reached == 3

    def test_l4prime_at_threshold_promotes(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.98, l4_signal_source="fallback_signals",
            test_result=_passing_test_result(),
        )
        er.compute_reward()
        assert er.level_reached == 4

    def test_l4prime_just_below_threshold_stays_level_3(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.979, l4_signal_source="fallback_signals",
        )
        er.compute_reward()
        assert er.level_reached == 3

    def test_to_dict(self):
        er = EvalResult(l1_parse=True, l2_build=True)
        er.compute_reward()
        d = er.to_dict()
        assert abs(d["reward"] - 0.15) < 1e-9
        assert d["level_reached"] == 2


class TestEvalResultNewFields:
    def test_new_fields_serialization(self):
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.75, l4_signal_source="fallback_signals",
            bytecode_version_match=True,
            manifest_sanity=True,
            api_surface_match=0.9,
            dependency_graph_match=0.85,
            resource_completeness=1.0,
        )
        d = er.to_dict()
        assert d["l4_signal_source"] == "fallback_signals"
        assert "fallback_signals" in d
        fs = d["fallback_signals"]
        assert fs["api_surface_match"] == 0.9
        assert fs["dependency_graph_match"] == 0.85
        assert fs["resource_completeness"] == 1.0

    def test_self_built_reference_to_dict(self):
        from unittest.mock import MagicMock
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {
            "verdict": "EQUIVALENT",
            "structural": {"match": True},
        }
        er = EvalResult(
            l1_parse=True, l2_build=True, l3_command=True,
            l4_score=0.85, l4_signal_source="self_built_reference",
            comparison_report=mock_report,
            comparison_verdict="EQUIVALENT",
        )
        d = er.to_dict()
        assert d["l4_signal_source"] == "self_built_reference"
        assert "comparison_report" in d
        assert d["comparison_report"]["verdict"] == "EQUIVALENT"
        assert "fallback_signals" not in d


class TestBuildAttempt:
    def test_default_id(self):
        ba = BuildAttempt()
        assert ba.id
        assert len(ba.id) == 36  # uuid4

    def test_to_dict(self):
        ba = BuildAttempt(reward=0.5, level_reached=3, error_class="test")
        d = ba.to_dict()
        assert d["reward"] == 0.5
        assert d["level_reached"] == 3
        assert d["error_class"] == "test"


class TestAdvisoryFindingsInEvalDict:
    def test_advisory_findings_in_eval_dict(self):
        er = EvalResult(l1_parse=True, l2_build=True)
        er.advisory_findings = [
            AdvisoryFinding(
                category="checksum_verification",
                severity="error",
                message="sha256 mismatch",
                location="build.log:42",
                evidence={"raw_line": "sha256sum: FAILED"},
            ),
            AdvisoryFinding(
                category="digest_pinning",
                severity="info",
                message="Unpinned base image",
                location="Containerfile:1",
            ),
        ]
        er.compute_reward()
        d = er.to_dict()
        assert "advisory_findings" in d
        assert len(d["advisory_findings"]) == 2
        assert d["advisory_findings"][0]["category"] == "checksum_verification"
        assert "pinning_status" in d
        assert d["pinning_status"]["has_findings"] is True

    def test_no_findings_not_in_dict(self):
        er = EvalResult(l1_parse=True)
        er.compute_reward()
        d = er.to_dict()
        assert "advisory_findings" not in d
        assert "pinning_status" not in d


class TestPinningStatusDerivation:
    def test_pinning_status_counts(self):
        er = EvalResult()
        er.advisory_findings = [
            AdvisoryFinding(category="checksum_verification", severity="error", message="a"),
            AdvisoryFinding(category="checksum_verification", severity="error", message="b"),
            AdvisoryFinding(category="download_verification", severity="warning", message="c"),
            AdvisoryFinding(category="digest_pinning", severity="info", message="d"),
        ]
        status = er.pinning_status
        assert status["has_findings"] is True
        assert status["counts"]["error"] == 2
        assert status["counts"]["warning"] == 1
        assert status["counts"]["info"] == 1
        assert "checksum_verification" in status["categories"]
        assert "download_verification" in status["categories"]
        assert "digest_pinning" in status["categories"]

    def test_empty_findings_status(self):
        er = EvalResult()
        status = er.pinning_status
        assert status["has_findings"] is False
        assert status["counts"] == {"error": 0, "warning": 0, "info": 0}
        assert status["categories"] == []


class TestRewardUnaffectedByFindings:
    def test_reward_unaffected_by_findings(self):
        er_clean = EvalResult(l1_parse=True, l2_build=True, l3_command=True, l4_match=True)
        reward_clean = er_clean.compute_reward()

        er_with_findings = EvalResult(l1_parse=True, l2_build=True, l3_command=True, l4_match=True)
        er_with_findings.advisory_findings = [
            AdvisoryFinding(category="checksum_verification", severity="error", message="fail"),
            AdvisoryFinding(category="digest_pinning", severity="info", message="unpinned"),
            AdvisoryFinding(category="download_verification", severity="warning", message="no checksum"),
        ]
        reward_with = er_with_findings.compute_reward()

        assert reward_clean == reward_with
        assert er_clean.level_reached == er_with_findings.level_reached
