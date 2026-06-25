"""Tests for the regression CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from buildroot.cli.main import cli


def _make_eval_result(**overrides):
    from buildroot.agent.models import EvalResult
    defaults = dict(
        l1_parse=True,
        l2_build=True,
        l3_command=True,
        l4_match=True,
        l4_score=1.0,
        reward=1.0,
        level_reached=4,
        comparison_verdict="equivalent",
        error_summary="",
        diff_summary="",
        comparison_report=None,
    )
    defaults.update(overrides)
    return EvalResult(**defaults)


def _setup_golden(tmp_path):
    """Create a minimal golden directory with one golden package and one stub."""
    golden = tmp_path / "tests" / "regression" / "golden"
    golden.mkdir(parents=True)

    (golden / "canary-1.0.0.json").write_text(json.dumps({
        "coordinate": "org.example:canary:1.0.0",
        "baseline_reward": 1.0,
        "baseline_l4_score": 1.0,
        "build_system": "maven",
        "difficulty": "easy",
        "has_golden_containerfile": True,
        "notes": "Test canary.",
    }))
    (golden / "canary-1.0.0.Containerfile").write_text("FROM fedora:39\nRUN echo hello")

    (golden / "stub-2.0.0.json").write_text(json.dumps({
        "coordinate": "org.example:stub:2.0.0",
        "baseline_reward": 0.5,
        "baseline_l4_score": 0.0,
        "build_system": "gradle",
        "difficulty": "medium",
        "has_golden_containerfile": False,
        "notes": "Stub package.",
    }))

    return golden


_ROOT_PATCH = "buildroot.cli.commands.regression_cmd._get_project_root"
_EVAL_PATCH = "buildroot.agent.evaluator.Evaluator"


class TestDiscoverGoldenPackages:
    def test_discover_golden_packages(self, tmp_path):
        from buildroot.cli.commands.regression_cmd import _discover_packages

        golden = _setup_golden(tmp_path)
        packages = _discover_packages(golden)

        assert len(packages) == 2
        names = [n for n, _, _ in packages]
        assert "canary-1.0.0" in names
        assert "stub-2.0.0" in names

        canary = [(n, m, c) for n, m, c in packages if n == "canary-1.0.0"][0]
        assert canary[1]["has_golden_containerfile"] is True
        assert canary[2] is not None

        stub = [(n, m, c) for n, m, c in packages if n == "stub-2.0.0"][0]
        assert stub[1]["has_golden_containerfile"] is False
        assert stub[2] is None


class TestRegressionCmd:
    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_regression_detected(self, mock_root, MockEvaluator, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=0.5, l4_score=0.0, l4_match=False)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["regression"])
        assert result.exit_code == 1, f"Output: {result.output}"
        assert "REGRESSION" in result.output

    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_all_pass(self, mock_root, MockEvaluator, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=1.0, l4_score=1.0)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["regression"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "all clear" in result.output

    @patch("buildroot.cli.commands.regression_cmd.CANARY_PACKAGE", "canary")
    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_quick_flag(self, mock_root, MockEvaluator, tmp_path):
        golden = _setup_golden(tmp_path)
        # Add a second golden package
        (golden / "other-3.0.0.json").write_text(json.dumps({
            "coordinate": "org.example:other:3.0.0",
            "baseline_reward": 1.0,
            "baseline_l4_score": 1.0,
            "build_system": "maven",
            "difficulty": "easy",
            "has_golden_containerfile": True,
            "notes": "Another golden.",
        }))
        (golden / "other-3.0.0.Containerfile").write_text("FROM fedora:39\nRUN echo other")

        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=1.0, l4_score=1.0)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--quick"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "canary" in result.output
        # --quick filters to canary only; other should not appear as evaluated
        assert MockEvaluator.return_value.evaluate.call_count == 1

    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_package_filter(self, mock_root, MockEvaluator, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=1.0, l4_score=1.0)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--package", "canary"])
        assert result.exit_code == 0, f"Output: {result.output}"
        MockEvaluator.return_value.evaluate.assert_called_once()

    @patch(_ROOT_PATCH)
    def test_status_output(self, mock_root, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--status"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "REGRESSION SUITE STATUS" in result.output
        assert "GOLDEN" in result.output
        assert "STUB" in result.output

    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_report_writes_json(self, mock_root, MockEvaluator, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=1.0, l4_score=1.0)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--report"])
        assert result.exit_code == 0, f"Output: {result.output}"

        report_dirs = list((tmp_path / "results" / "regression").iterdir())
        assert len(report_dirs) == 1
        summary = json.loads((report_dirs[0] / "summary.json").read_text())
        assert summary["passed"] == 1
        assert summary["regressions"] == 0

    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_skip_stubs(self, mock_root, MockEvaluator, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=1.0, l4_score=1.0)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["regression"])
        assert result.exit_code == 0, f"Output: {result.output}"
        # Only the canary should be evaluated, not the stub
        MockEvaluator.return_value.evaluate.assert_called_once()
        assert "Skipped 1 stub" in result.output
