"""Tests for regression_cmd --solve flag and helper functions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from buildroot.cli.commands.regression_cmd import _discover_packages, _print_status
from buildroot.cli.main import cli


def _setup_golden(tmp_path):
    golden = tmp_path / "tests" / "regression" / "golden"
    golden.mkdir(parents=True)

    (golden / "pkg-a-1.0.json").write_text(json.dumps({
        "coordinate": "org.example:pkg-a:1.0",
        "baseline_reward": 1.0,
        "baseline_l4_score": 1.0,
        "build_system": "maven",
        "difficulty": "easy",
        "has_golden_containerfile": True,
        "notes": "Test package A.",
    }))
    (golden / "pkg-a-1.0.Containerfile").write_text("FROM fedora:39\nRUN mvn install -B")

    (golden / "pkg-b-2.0.json").write_text(json.dumps({
        "coordinate": "org.example:pkg-b:2.0",
        "baseline_reward": 0.5,
        "baseline_l4_score": 0.0,
        "build_system": "gradle",
        "difficulty": "medium",
        "has_golden_containerfile": True,
        "notes": "Test package B.",
    }))
    (golden / "pkg-b-2.0.Containerfile").write_text("FROM fedora:39\nRUN ./gradlew build")

    return golden


class TestDiscoverPackages:
    def test_finds_all_packages(self, tmp_path):
        golden = _setup_golden(tmp_path)
        packages = _discover_packages(golden)

        assert len(packages) == 2
        names = [n for n, _, _ in packages]
        assert "pkg-a-1.0" in names
        assert "pkg-b-2.0" in names

    def test_containerfile_paths_populated(self, tmp_path):
        golden = _setup_golden(tmp_path)
        packages = _discover_packages(golden)

        for _, _, cf_path in packages:
            assert cf_path is not None
            assert cf_path.exists()

    def test_missing_containerfile_returns_none(self, tmp_path):
        golden = _setup_golden(tmp_path)
        (golden / "pkg-b-2.0.Containerfile").unlink()
        packages = _discover_packages(golden)

        cf_map = {n: c for n, _, c in packages}
        assert cf_map["pkg-a-1.0"] is not None
        assert cf_map["pkg-b-2.0"] is None


class TestPrintStatus:
    def test_prints_all_packages(self, tmp_path):
        golden = _setup_golden(tmp_path)
        _discover_packages(golden)

        runner = CliRunner()
        with runner.isolated_filesystem():
            _result = runner.invoke(cli, ["regression", "--status"], catch_exceptions=False,
                                   obj=None)

    def test_print_status_with_mock_packages(self, capsys):
        packages = [
            ("pkg-a-1.0", {
                "baseline_reward": 1.0,
                "baseline_l4_score": 1.0,
                "build_system": "maven",
                "difficulty": "easy",
            }, Path("/fake/pkg-a-1.0.Containerfile")),
            ("pkg-b-2.0", {
                "baseline_reward": 0.5,
                "baseline_l4_score": 0.0,
                "build_system": "gradle",
                "difficulty": "medium",
            }, None),
        ]
        _print_status(packages)
        captured = capsys.readouterr()
        assert "pkg-a-1.0" in captured.out
        assert "pkg-b-2.0" in captured.out
        assert "READY" in captured.out
        assert "MISSING" in captured.out


_ROOT_PATCH = "buildroot.cli.commands.regression_cmd._get_project_root"


class TestSolveFlag:
    def test_solve_flag_accepted(self, tmp_path):
        """--solve flag is recognized by the CLI without errors."""
        _setup_golden(tmp_path)

        runner = CliRunner()
        with patch(_ROOT_PATCH, return_value=tmp_path), \
             patch("buildroot.cli.commands.regression_cmd._run_solve", return_value=0) as mock_solve:
            result = runner.invoke(cli, ["regression", "--solve"])
            assert result.exit_code == 0, f"Output: {result.output}"
            mock_solve.assert_called_once()

    def test_solve_with_package_filter(self, tmp_path):
        _setup_golden(tmp_path)

        runner = CliRunner()
        with patch(_ROOT_PATCH, return_value=tmp_path), \
             patch("buildroot.cli.commands.regression_cmd._run_solve", return_value=0) as mock_solve:
            result = runner.invoke(cli, ["regression", "--solve", "--package", "pkg-a"])
            assert result.exit_code == 0, f"Output: {result.output}"
            args = mock_solve.call_args
            runnable = args[0][0]
            assert len(runnable) == 1
            assert runnable[0][0] == "pkg-a-1.0"

    def test_solve_timeout_and_iterations_passed(self, tmp_path):
        _setup_golden(tmp_path)

        runner = CliRunner()
        with patch(_ROOT_PATCH, return_value=tmp_path), \
             patch("buildroot.cli.commands.regression_cmd._run_solve", return_value=0) as mock_solve:
            result = runner.invoke(cli, [
                "regression", "--solve",
                "--solve-timeout", "3600",
                "--max-iterations", "20",
            ])
            assert result.exit_code == 0, f"Output: {result.output}"
            args = mock_solve.call_args
            assert args[0][2] == 3600  # solve_timeout
            assert args[0][3] == 20    # max_iterations
