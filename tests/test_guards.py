"""Tests for guards & gates — surface checks, leakage scan, monotonic enforcement."""

from unittest.mock import MagicMock, patch

from buildroot.agent.guards import (
    FIXED_SURFACES,
    MUTABLE_SURFACES,
    GuardResult,
    check_all,
    check_monotonic,
    check_surfaces,
    run_test_gate,
    scan_leakage,
)


class TestGuardResult:
    def test_bool_true(self):
        gr = GuardResult(passed=True, reason="ok")
        assert bool(gr) is True

    def test_bool_false(self):
        gr = GuardResult(passed=False, reason="bad")
        assert bool(gr) is False


class TestCheckSurfaces:
    def test_empty_diff_passes(self):
        result = check_surfaces("")
        assert result.passed

    def test_mutable_file_passes(self):
        result = check_surfaces("src/buildroot/agent/builder.py\n")
        assert result.passed

    def test_fixed_surface_fails(self):
        result = check_surfaces("src/buildroot/agent/evaluator.py\n")
        assert not result.passed
        assert "FIXED" in result.reason

    def test_eval_score_fails(self):
        result = check_surfaces("eval/score.py\n")
        assert not result.passed

    def test_jar_comparator_fails(self):
        result = check_surfaces("src/buildroot/utils/jar_comparator.py\n")
        assert not result.passed

    def test_out_of_scope_fails(self):
        result = check_surfaces("setup.py\n")
        assert not result.passed
        assert "Out-of-scope" in result.reason

    def test_template_files_pass(self):
        result = check_surfaces("src/buildroot/templates/Containerfile.j2\n")
        assert result.passed

    def test_test_files_pass(self):
        result = check_surfaces("tests/test_new_module.py\n")
        assert result.passed

    def test_knowledge_files_pass(self):
        result = check_surfaces("src/buildroot/agent/knowledge/patterns.md\n")
        assert result.passed

    def test_multiple_files_mixed(self):
        diff = "src/buildroot/agent/builder.py\nsrc/buildroot/agent/evaluator.py\n"
        result = check_surfaces(diff)
        assert not result.passed

    def test_results_dir_passes(self):
        result = check_surfaces("results/output.json\n")
        assert result.passed


class TestCheckMonotonic:
    def test_improvement_passes(self):
        result = check_monotonic(0.5, 0.3, 0.3)
        assert result.passed

    def test_same_rate_passes(self):
        result = check_monotonic(0.5, 0.5, 0.3)
        assert result.passed

    def test_regression_fails(self):
        result = check_monotonic(0.3, 0.5, 0.5)
        assert not result.passed
        assert "Regression" in result.reason

    def test_below_historical_best_fails(self):
        result = check_monotonic(0.4, 0.3, 0.5)
        assert not result.passed
        assert "historical best" in result.reason

    def test_zero_rates_pass(self):
        result = check_monotonic(0.0, 0.0, 0.0)
        assert result.passed


class TestScanLeakage:
    def test_empty_diff_passes(self):
        result = scan_leakage("")
        assert result.passed

    def test_clean_diff_passes(self):
        diff = """\
+    def improve_builder(self):
+        pass
"""
        result = scan_leakage(diff)
        assert result.passed

    def test_coordinate_in_diff_detected(self):
        diff = '+if "commons-lang3" in coordinate:\n'
        result = scan_leakage(diff, ["org.apache.commons:commons-lang3:3.14.0"])
        assert not result.passed
        assert "commons-lang3" in result.reason

    def test_group_id_in_diff_detected(self):
        diff = '+if "org.apache.commons" in group:\n'
        result = scan_leakage(diff, ["org.apache.commons:commons-lang3:3.14.0"])
        assert not result.passed

    def test_package_conditional_detected(self):
        diff = '+if "micrometer" in coordinate:\n'
        result = scan_leakage(diff, ["io.micrometer:micrometer-core:1.12.0"])
        assert not result.passed

    def test_hardcoded_version_detected(self):
        diff = '+    if version == "3.14.0":\n'
        result = scan_leakage(diff)
        assert not result.passed
        assert "Hardcoded version" in result.reason

    def test_no_test_coordinates_still_checks_patterns(self):
        diff = '+if "some-package" in coordinate:\n'
        result = scan_leakage(diff)
        assert not result.passed

    def test_context_lines_not_flagged(self):
        diff = ' if "existing" in coordinate:\n'
        result = scan_leakage(diff)
        assert result.passed


class TestRunTestGate:
    @patch("buildroot.agent.guards.subprocess.run")
    def test_both_pass(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        result = run_test_gate()
        assert result.passed

    @patch("buildroot.agent.guards.subprocess.run")
    def test_pytest_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="FAILED", stderr="error")
        result = run_test_gate()
        assert not result.passed
        assert "pytest failed" in result.reason

    @patch("buildroot.agent.guards.subprocess.run")
    def test_ruff_fails(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "pytest" in cmd:
                return MagicMock(returncode=0, stdout="passed", stderr="")
            return MagicMock(returncode=1, stdout="F401 unused", stderr="")
        mock_run.side_effect = side_effect
        result = run_test_gate()
        assert not result.passed
        assert "ruff" in result.reason


class TestCheckAll:
    def test_all_pass(self):
        result = check_all(
            diff_output="src/buildroot/agent/builder.py\n",
            solve_rate_before=0.3,
            solve_rate_after=0.5,
            historical_best=0.3,
            run_tests=False,
        )
        assert result.passed

    def test_surface_violation_stops_early(self):
        result = check_all(
            diff_output="src/buildroot/agent/evaluator.py\n",
            solve_rate_before=0.3,
            solve_rate_after=0.5,
            historical_best=0.3,
            run_tests=False,
        )
        assert not result.passed
        assert "FIXED" in result.reason

    def test_regression_stops(self):
        result = check_all(
            diff_output="src/buildroot/agent/builder.py\n",
            solve_rate_before=0.5,
            solve_rate_after=0.3,
            historical_best=0.5,
            run_tests=False,
        )
        assert not result.passed
        assert "Regression" in result.reason


class TestSurfaceConstants:
    def test_evaluator_is_fixed(self):
        assert "src/buildroot/agent/evaluator.py" in FIXED_SURFACES

    def test_jar_comparator_is_fixed(self):
        assert "src/buildroot/utils/jar_comparator.py" in FIXED_SURFACES

    def test_builder_is_mutable(self):
        assert "src/buildroot/agent/builder.py" in MUTABLE_SURFACES

    def test_analyzer_is_mutable(self):
        assert "src/buildroot/agent/analyzer.py" in MUTABLE_SURFACES
