"""Tests for the eval CLI command (mock the Evaluator)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from buildroot.cli.main import cli


def _make_eval_result(**overrides):
    """Create a mock EvalResult with sensible defaults."""
    from buildroot.agent.models import EvalResult
    defaults = dict(
        l1_parse=True,
        l2_build=True,
        l3_command=True,
        l4_match=True,
        l4_score=0.9988,
        reward=0.9994,
        level_reached=4,
        comparison_verdict="equivalent",
        error_summary="",
        diff_summary="",
        comparison_report=None,
    )
    defaults.update(overrides)
    return EvalResult(**defaults)


class TestEvalCmd:
    @patch("buildroot.agent.evaluator.Evaluator")
    def test_basic_eval_success(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39\nRUN echo hello")

        mock_result = _make_eval_result()
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["l1_parse"] is True
        assert output["l4_match"] is True
        assert output["reward"] == 0.9994

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_failure_exits_nonzero(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39")

        mock_result = _make_eval_result(
            l4_match=False, l4_score=0.5, reward=0.50,
            level_reached=3, comparison_verdict="mismatch",
        )
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0"])
        assert result.exit_code == 1
        output = json.loads(result.output)
        assert output["reward"] == 0.50

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_with_comparison_report(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39")

        mock_report = MagicMock()
        mock_report.verdict = "equivalent"
        mock_report.equivalence_score.return_value = 0.95
        mock_report.structural.match = True
        mock_report.metadata.match = True
        mock_report.bytecode.match = False

        mock_result = _make_eval_result(comparison_report=mock_report)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert "comparison_report" in output
        assert output["comparison_report"]["verdict"] == "equivalent"
        assert output["comparison_report"]["structural_match"] is True
        assert output["comparison_report"]["bytecode_match"] is False

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_no_comparison_report(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39")

        mock_result = _make_eval_result(
            l4_match=False, l4_score=0.0, reward=0.15,
            level_reached=2, comparison_report=None,
        )
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0"])
        output = json.loads(result.output)
        assert "comparison_report" not in output

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_no_pretty(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39")

        mock_result = _make_eval_result()
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0", "--no-pretty"])
        assert result.exit_code == 0
        assert "\n" not in result.output.strip()

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_passes_host_and_timeout(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39")

        mock_result = _make_eval_result()
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        runner.invoke(cli, ["eval", str(cf), "g:a:1.0", "--host", "myhost", "--timeout", "300"])
        MockEvaluator.assert_called_once_with(host="myhost", timeout=300)

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_includes_diff_summary(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39")

        mock_result = _make_eval_result(diff_summary="bytecode differs in 3 classes")
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0"])
        output = json.loads(result.output)
        assert output["diff_summary"] == "bytecode differs in 3 classes"

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_hasattr_consistency(self, MockEvaluator, tmp_path):
        """Both diff_summary and comparison_report use safe attribute access."""
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM fedora:39")

        mock_result = MagicMock()
        mock_result.l1_parse = True
        mock_result.l2_build = True
        mock_result.l3_command = True
        mock_result.l4_match = True
        mock_result.l4_score = 1.0
        mock_result.reward = 1.0
        mock_result.level_reached = 4
        mock_result.comparison_verdict = "equivalent"
        mock_result.error_summary = ""
        mock_result.trust_check = False
        mock_result.trust_violations = []
        del mock_result.diff_summary
        del mock_result.comparison_report
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["diff_summary"] is None
        assert "comparison_report" not in output

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_trusted_flag_passed(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM eclipse-temurin:17-jdk")

        mock_result = _make_eval_result(trust_check=True, trust_violations=[])
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        runner.invoke(cli, ["eval", str(cf), "g:a:1.0", "--trusted"])
        MockEvaluator.return_value.evaluate.assert_called_once_with(
            cf.read_text(), "g:a:1.0", trusted=True
        )

    @patch("buildroot.agent.evaluator.Evaluator")
    def test_eval_trust_violations_in_output(self, MockEvaluator, tmp_path):
        cf = tmp_path / "Containerfile"
        cf.write_text("FROM amazoncorretto:17")

        mock_result = _make_eval_result(
            l2_build=False, l3_command=False, l4_match=False,
            l4_score=0.0, reward=0.05, level_reached=1,
            trust_check=False,
            trust_violations=["FROM amazoncorretto:17 — not in trusted allowlist"],
        )
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", str(cf), "g:a:1.0", "--trusted"])
        output = json.loads(result.output)
        assert output["trust_check"] is False
        assert len(output["trust_violations"]) == 1
        assert "amazoncorretto" in output["trust_violations"][0]

    def test_eval_missing_file(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "/nonexistent/Containerfile", "g:a:1.0"])
        assert result.exit_code != 0
