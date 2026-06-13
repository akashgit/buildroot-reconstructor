"""Tests for the outer loop orchestrator — batch runs, intelligent cycle, OuterBuilder."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from buildroot.agent.outer_loop import (
    _apply_changes,
    _get_git_diff,
    _load_packages,
    _revert_changes,
    _save_package_results,
    run_batch,
    run_outer_loop,
)
from buildroot.agent.outer_strategist import CodeChangeHypothesis


class TestLoadPackages:
    def test_loads_simple_list(self, tmp_path: Path):
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("org.apache.commons:commons-lang3:3.14.0\nio.micrometer:micrometer-core:1.12.0\n")
        result = _load_packages(str(pkg_file))
        assert len(result) == 2
        assert "org.apache.commons:commons-lang3:3.14.0" in result

    def test_skips_comments(self, tmp_path: Path):
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("# comment\norg.apache.commons:commons-lang3:3.14.0\n")
        result = _load_packages(str(pkg_file))
        assert len(result) == 1

    def test_handles_csv_format(self, tmp_path: Path):
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("org.apache.commons:commons-lang3:3.14.0, io.micrometer:micrometer-core:1.12.0\n")
        result = _load_packages(str(pkg_file))
        assert len(result) == 2

    def test_empty_file(self, tmp_path: Path):
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("")
        result = _load_packages(str(pkg_file))
        assert len(result) == 0

    def test_nonexistent_file(self):
        result = _load_packages("/nonexistent/path.txt")
        assert len(result) == 0

    def test_skips_lines_without_colon(self, tmp_path: Path):
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("not-a-coordinate\norg.foo:bar:1.0\n")
        result = _load_packages(str(pkg_file))
        assert len(result) == 1


class TestApplyAndRevertChanges:
    def test_apply_and_revert(self, tmp_path: Path):
        test_file = tmp_path / "test.py"
        test_file.write_text("original content")

        originals = _apply_changes({str(test_file): "new content"})
        assert test_file.read_text() == "new content"
        assert originals[str(test_file)] == "original content"

        _revert_changes(originals)
        assert test_file.read_text() == "original content"


class TestGetGitDiff:
    @patch("buildroot.agent.outer_loop.subprocess.run")
    def test_returns_diff_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout="file1.py\nfile2.py\n")
        result = _get_git_diff()
        assert "file1.py" in result

    @patch("buildroot.agent.outer_loop.subprocess.run", side_effect=Exception("git not found"))
    def test_returns_empty_on_error(self, mock_run):
        result = _get_git_diff()
        assert result == ""


class TestSavePackageResults:
    def test_saves_results(self, tmp_path: Path):
        from ruamel.yaml import YAML
        from buildroot.agent.loop import LoopResult
        from buildroot.agent.models import BuildAttempt

        loop_result = LoopResult(
            coordinate="org.foo:bar:1.0",
            status="success",
            best_reward=1.0,
            best_attempt=BuildAttempt(containerfile="FROM maven:3.9\n"),
            iterations=3,
        )
        yaml = YAML()
        _save_package_results(tmp_path, "org.foo:bar:1.0", loop_result, yaml)

        pkg_dir = tmp_path / "org_foo_bar_1_0"
        assert pkg_dir.exists()
        assert (pkg_dir / "attempts.json").exists()
        assert (pkg_dir / "Containerfile.best").exists()


class TestRunOuterLoopLegacy:
    @patch("buildroot.agent.outer_loop.run_inner_loop")
    def test_legacy_api_works(self, mock_inner, tmp_path: Path):
        from buildroot.agent.loop import LoopResult
        mock_inner.return_value = LoopResult(
            coordinate="org.foo:bar:1.0", status="success",
            best_reward=1.0, iterations=1,
        )
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("org.foo:bar:1.0\n")

        result = run_outer_loop(
            str(pkg_file), output_dir=str(tmp_path / "output"),
        )
        assert result["total_packages"] == 1
        assert result["solved"] == 1


class TestRunBatch:
    @patch("buildroot.agent.outer_loop.run_inner_loop")
    def test_batch_with_meta_guidance(self, mock_inner, tmp_path: Path):
        from buildroot.agent.loop import LoopResult
        mock_inner.return_value = LoopResult(
            coordinate="org.foo:bar:1.0", status="budget_exhausted",
            best_reward=0.15, iterations=15,
        )
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("org.foo:bar:1.0\n")

        result = run_batch(
            str(pkg_file),
            output_dir=str(tmp_path / "output"),
            meta_guidance="Use JDK 17",
        )
        assert result["total_packages"] == 1
        mock_inner.assert_called_once()
        assert mock_inner.call_args.kwargs["meta_guidance"] == "Use JDK 17"

    @patch("buildroot.agent.outer_loop.run_inner_loop")
    def test_batch_empty_packages(self, mock_inner, tmp_path: Path):
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("")
        result = run_batch(str(pkg_file), output_dir=str(tmp_path / "output"))
        assert result == {"error": "no packages"}

    @patch("buildroot.agent.outer_loop.run_inner_loop")
    def test_batch_solve_rate_calculation(self, mock_inner, tmp_path: Path):
        from buildroot.agent.loop import LoopResult
        mock_inner.side_effect = [
            LoopResult(coordinate="g:a:1.0", status="success", best_reward=1.0, iterations=1),
            LoopResult(coordinate="g:b:1.0", status="budget_exhausted", best_reward=0.15, iterations=15),
            LoopResult(coordinate="g:c:1.0", status="success", best_reward=0.98, iterations=5),
        ]
        pkg_file = tmp_path / "packages.txt"
        pkg_file.write_text("g:a:1.0\ng:b:1.0\ng:c:1.0\n")

        result = run_batch(str(pkg_file), output_dir=str(tmp_path / "output"))
        assert result["total_packages"] == 3
        assert result["solved"] == 2
        assert abs(result["solve_rate"] - 2 / 3) < 0.01


class TestCodeChangeHypothesisForOuterBuilder:
    def test_hypothesis_serialization(self):
        hyp = CodeChangeHypothesis(
            target_error_class="compilation/jdk_mismatch",
            files_to_modify=["src/buildroot/agent/builder.py"],
            expected_impact="Fix JDK selection",
            rationale="Most common error",
        )
        d = hyp.to_dict()
        assert d["target_error_class"] == "compilation/jdk_mismatch"
        assert len(d["files_to_modify"]) == 1
