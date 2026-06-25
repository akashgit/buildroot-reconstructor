"""Tests for the regression CLI command."""

from __future__ import annotations

import json
from pathlib import Path
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


def _setup_golden(tmp_path, all_have_containerfiles=True):
    """Create a minimal golden directory with packages."""
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

    (golden / "other-2.0.0.json").write_text(json.dumps({
        "coordinate": "org.example:other:2.0.0",
        "baseline_reward": 0.5,
        "baseline_l4_score": 0.0,
        "build_system": "gradle",
        "difficulty": "medium",
        "has_golden_containerfile": True,
        "notes": "Second test package.",
    }))
    if all_have_containerfiles:
        (golden / "other-2.0.0.Containerfile").write_text("FROM fedora:39\nRUN echo other")

    return golden


_ROOT_PATCH = "buildroot.cli.commands.regression_cmd._get_project_root"
_EVAL_PATCH = "buildroot.agent.evaluator.Evaluator"


GOLDEN_DIR = Path(__file__).resolve().parent / "regression" / "golden"


class TestDiscoverGoldenPackages:
    def test_discover_packages(self, tmp_path):
        from buildroot.cli.commands.regression_cmd import _discover_packages

        golden = _setup_golden(tmp_path)
        packages = _discover_packages(golden)

        assert len(packages) == 2
        names = [n for n, _, _ in packages]
        assert "canary-1.0.0" in names
        assert "other-2.0.0" in names

        for _, _, cf_path in packages:
            assert cf_path is not None


class TestRegressionCmd:
    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_regression_detected(self, mock_root, MockEvaluator, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=0.3, l4_score=0.0, l4_match=False)
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
        assert MockEvaluator.return_value.evaluate.call_count == 2

    @patch("buildroot.cli.commands.regression_cmd.CANARY_PACKAGE", "canary")
    @patch(_EVAL_PATCH)
    @patch(_ROOT_PATCH)
    def test_quick_flag(self, mock_root, MockEvaluator, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_result = _make_eval_result(reward=1.0, l4_score=1.0)
        MockEvaluator.return_value.evaluate.return_value = mock_result

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--quick"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "canary" in result.output
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
        assert "READY" in result.output

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
        assert summary["passed"] == 2
        assert summary["regressions"] == 0

    @patch(_ROOT_PATCH)
    def test_missing_containerfile_is_error(self, mock_root, tmp_path):
        _setup_golden(tmp_path, all_have_containerfiles=False)
        mock_root.return_value = tmp_path

        runner = CliRunner()
        result = runner.invoke(cli, ["regression"])
        assert result.exit_code == 1, f"Output: {result.output}"
        assert "missing Containerfiles" in result.output


class TestE2eFlag:
    @patch("buildroot.cli.commands.regression_cmd.subprocess.run")
    @patch(_ROOT_PATCH)
    def test_e2e_calls_buildroot_agent(self, mock_root, mock_subprocess, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_subprocess.return_value.returncode = 0

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--e2e"])
        assert result.exit_code == 0, f"Output: {result.output}"
        assert "E2E PIPELINE TEST" in result.output
        assert "completed successfully" in result.output

        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        cmd = call_args[0][0] if call_args[0] else call_args[1].get("cmd")
        assert "org.apache.commons:commons-lang3:3.14.0" in cmd
        assert "--v3-only" in cmd
        assert "--max-iterations" in cmd

    @patch("buildroot.cli.commands.regression_cmd.subprocess.run")
    @patch(_ROOT_PATCH)
    def test_e2e_failure(self, mock_root, mock_subprocess, tmp_path):
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stderr = "something broke"

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--e2e"])
        assert result.exit_code == 1, f"Output: {result.output}"
        assert "FAILED" in result.output

    @patch("buildroot.cli.commands.regression_cmd.subprocess.run")
    @patch(_ROOT_PATCH)
    def test_e2e_timeout(self, mock_root, mock_subprocess, tmp_path):
        import subprocess as sp
        _setup_golden(tmp_path)
        mock_root.return_value = tmp_path
        mock_subprocess.side_effect = sp.TimeoutExpired(cmd="test", timeout=900)

        runner = CliRunner()
        result = runner.invoke(cli, ["regression", "--e2e"])
        assert result.exit_code == 1, f"Output: {result.output}"
        assert "TIMED OUT" in result.output


class TestGoldenSuiteCompleteness:
    def test_all_packages_have_containerfiles(self):
        """Verify all 5 packages in the real golden directory have Containerfiles."""
        assert GOLDEN_DIR.exists(), f"Golden dir not found: {GOLDEN_DIR}"
        json_files = sorted(GOLDEN_DIR.glob("*.json"))
        assert len(json_files) == 5, f"Expected 5 packages, found {len(json_files)}"

        for meta_path in json_files:
            cf_path = meta_path.with_suffix(".Containerfile")
            assert cf_path.exists(), f"Missing Containerfile for {meta_path.name}"

    def test_no_stubs_in_suite(self):
        """Verify no package has has_golden_containerfile=false."""
        assert GOLDEN_DIR.exists(), f"Golden dir not found: {GOLDEN_DIR}"
        for meta_path in sorted(GOLDEN_DIR.glob("*.json")):
            with open(meta_path) as f:
                metadata = json.load(f)
            assert metadata.get("has_golden_containerfile") is True, (
                f"{meta_path.name} has has_golden_containerfile={metadata.get('has_golden_containerfile')}"
            )
