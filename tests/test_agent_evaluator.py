"""Tests for agent evaluator — L1-L4 scoring logic with mocked SSH."""

from unittest.mock import MagicMock, patch

from buildroot.agent.evaluator import Evaluator, _extract_error_lines


VALID_CONTAINERFILE = """\
FROM docker.io/library/maven:3.9-eclipse-temurin-17
WORKDIR /build
RUN echo hello
"""

INVALID_CONTAINERFILE = "INVALID not a containerfile @@@ {"


class TestL1Parse:
    def test_valid_containerfile_passes_l1(self):
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l1_parse(VALID_CONTAINERFILE, result) is True
        assert result.l1_parse is True

    def test_invalid_containerfile_still_parsed(self):
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        evaluator._l1_parse(INVALID_CONTAINERFILE, result)


class TestExtractErrorLines:
    def test_extracts_error_lines(self):
        log = (
            "Step 1: OK\n"
            "[ERROR] Failed to compile\n"
            "  at SomeClass.java:42\n"
            "Step 2: OK\n"
            "fatal: repo not found\n"
        )
        result = _extract_error_lines(log)
        assert "[ERROR]" in result or "fatal:" in result

    def test_fallback_to_tail_when_no_errors(self):
        log = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        result = _extract_error_lines(log, max_lines=3)
        assert result

    def test_deduplicates_lines(self):
        log = "[ERROR] same error\n[ERROR] same error\n[ERROR] same error\n"
        result = _extract_error_lines(log)
        assert result.count("[ERROR] same error") == 1

    def test_empty_log(self):
        result = _extract_error_lines("")
        assert result == ""


class TestEvaluatorWithMocks:
    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l2_build_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="STEP 1: FROM maven\nCOMMIT", stderr=""
        )
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l2_build(VALID_CONTAINERFILE, "test-tag", result) is True
        assert result.l2_build is True

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l2_build_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: could not build"
        )
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l2_build(VALID_CONTAINERFILE, "test-tag", result) is False
        assert result.error_summary

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l3_command_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="target/foo-1.0.jar\nBUILD_SUCCESS",
            stderr="",
        )
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l3_command("test-tag", result) is True
        assert result.l3_command is True

    @patch("buildroot.agent.evaluator.subprocess.run")
    def test_l3_command_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="BUILD_FAILED",
            stderr="",
        )
        evaluator = Evaluator()
        from buildroot.agent.models import EvalResult
        result = EvalResult()
        assert evaluator._l3_command("test-tag", result) is False
