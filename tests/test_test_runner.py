"""Tests for buildroot.eval.test_runner — framework detection and output parsing."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import subprocess

from buildroot.eval.test_runner import (
    build_test_command,
    detect_test_framework,
    parse_gradle_test_output,
    parse_maven_test_output,
    run_tests,
)


class TestDetectTestFramework:
    def test_maven_by_mvn(self):
        cf = "FROM openjdk:17\nRUN mvn install -B"
        assert detect_test_framework(cf) == "maven"

    def test_maven_by_pom(self):
        cf = "FROM openjdk:17\nCOPY pom.xml ."
        assert detect_test_framework(cf) == "maven"

    def test_gradle_by_gradlew(self):
        cf = "FROM openjdk:17\nRUN ./gradlew build"
        assert detect_test_framework(cf) == "gradle"

    def test_gradle_by_build_gradle(self):
        cf = "FROM openjdk:17\nCOPY build.gradle ."
        assert detect_test_framework(cf) == "gradle"

    def test_ant_by_ant(self):
        cf = "FROM openjdk:17\nRUN ant build"
        assert detect_test_framework(cf) == "ant"

    def test_ant_by_build_xml(self):
        cf = "FROM openjdk:17\nCOPY build.xml ."
        assert detect_test_framework(cf) == "ant"

    def test_none_for_unknown(self):
        cf = "FROM python:3.11\nRUN pip install ."
        assert detect_test_framework(cf) is None

    def test_gradle_not_maven_when_meta_inf_maven(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN ./gradlew build\n"
            "RUN jar xf app.jar META-INF/maven\n"
        )
        assert detect_test_framework(cf) == "gradle"

    def test_maven_substring_not_matched(self):
        cf = "FROM fedora:39\nRUN echo META-INF/maven/something"
        assert detect_test_framework(cf) is None

    def test_empty_containerfile(self):
        assert detect_test_framework("") is None


class TestBuildTestCommand:
    def test_maven_default(self):
        assert build_test_command("maven") == "mvn test -B"

    def test_maven_with_module(self):
        cmd = build_test_command("maven", "core")
        assert "mvn test -B -pl" in cmd
        assert "core" in cmd

    def test_gradle_default(self):
        assert build_test_command("gradle") == "./gradlew test"

    def test_gradle_with_module(self):
        assert build_test_command("gradle", "core") == "./gradlew :core:test"

    def test_ant(self):
        assert build_test_command("ant") == "ant test"

    def test_unknown_framework(self):
        assert build_test_command("unknown") == ""


class TestParseMavenTestOutput:
    def test_simple_output(self):
        output = """
[INFO] -------------------------------------------------------
[INFO]  T E S T S
[INFO] -------------------------------------------------------
[INFO] Running com.example.AppTest
Tests run: 10, Failures: 0, Errors: 0, Skipped: 2
[INFO] Tests run: 10, Failures: 0, Errors: 0, Skipped: 2
[INFO] BUILD SUCCESS
"""
        result = parse_maven_test_output(output)
        assert result["run"] == 20
        assert result["failed"] == 0
        assert result["skipped"] == 4
        assert result["tests_passed"] == 16

    def test_with_failures(self):
        output = """
Tests run: 5, Failures: 2, Errors: 1, Skipped: 0
"""
        result = parse_maven_test_output(output)
        assert result["run"] == 5
        assert result["failed"] == 3
        assert result["tests_passed"] == 2

    def test_multi_module(self):
        output = """
Tests run: 10, Failures: 0, Errors: 0, Skipped: 0
Tests run: 15, Failures: 1, Errors: 0, Skipped: 2
"""
        result = parse_maven_test_output(output)
        assert result["run"] == 25
        assert result["failed"] == 1
        assert result["skipped"] == 2
        assert result["tests_passed"] == 22

    def test_empty_output(self):
        result = parse_maven_test_output("")
        assert result["run"] == 0
        assert result["failed"] == 0
        assert result["tests_passed"] == 0

    def test_no_test_lines(self):
        result = parse_maven_test_output("BUILD SUCCESS\nDone.")
        assert result["run"] == 0


class TestParseGradleTestOutput:
    def test_simple_output(self):
        output = """
> Task :test
20 tests completed, 1 failed
2 tests skipped
"""
        result = parse_gradle_test_output(output)
        assert result["run"] == 20
        assert result["failed"] == 1
        assert result["skipped"] == 2
        assert result["tests_passed"] == 17

    def test_all_passing(self):
        output = "50 tests completed, 0 failed\n"
        result = parse_gradle_test_output(output)
        assert result["run"] == 50
        assert result["failed"] == 0
        assert result["tests_passed"] == 50

    def test_summary_only(self):
        output = "15 tests completed\n"
        result = parse_gradle_test_output(output)
        assert result["run"] == 15
        assert result["failed"] == 0
        assert result["tests_passed"] == 15

    def test_empty_output(self):
        result = parse_gradle_test_output("")
        assert result["run"] == 0
        assert result["failed"] == 0


class TestRunTests:
    def test_no_framework_returns_none(self):
        cf = "FROM python:3.11\nRUN pip install ."
        result = run_tests("tag", cf, host="host")
        assert result is None

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_maven_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Tests run: 10, Failures: 0, Errors: 0, Skipped: 0\nBUILD SUCCESS",
            stderr="",
        )
        cf = "FROM openjdk:17\nRUN mvn install -B"
        result = run_tests("tag", cf, host="host", timeout=60)

        assert result is not None
        assert result.available is True
        assert result.framework == "maven"
        assert result.passed is True
        assert result.run == 10
        assert result.status == "passed"

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_maven_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="Tests run: 5, Failures: 2, Errors: 0, Skipped: 0",
            stderr="",
        )
        cf = "FROM openjdk:17\nRUN mvn install -B"
        result = run_tests("tag", cf, host="host")

        assert result is not None
        assert result.passed is False
        assert result.failed == 2
        assert result.status == "failed"

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=300)
        cf = "FROM openjdk:17\nRUN mvn install -B"
        result = run_tests("tag", cf, host="host", timeout=300)

        assert result is not None
        assert result.status == "timeout"
        assert result.passed is False
        assert result.duration_seconds == 300.0

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_ssh_error(self, mock_run):
        mock_run.side_effect = OSError("Connection refused")
        cf = "FROM openjdk:17\nRUN mvn install -B"
        result = run_tests("tag", cf, host="host")

        assert result is not None
        assert result.status == "error"
        assert result.passed is False

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_gradle_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="20 tests completed, 0 failed\n",
            stderr="",
        )
        cf = "FROM openjdk:17\nRUN ./gradlew build"
        result = run_tests("tag", cf, host="host")

        assert result is not None
        assert result.framework == "gradle"
        assert result.passed is True
        assert result.run == 20

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_ant_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="BUILD SUCCESSFUL", stderr="",
        )
        cf = "FROM openjdk:17\nCOPY build.xml .\nRUN ant build"
        result = run_tests("tag", cf, host="host")

        assert result is not None
        assert result.framework == "ant"
        assert result.passed is True
        assert result.status == "passed"

    def test_to_dict(self):
        cf = "FROM python:3.11\nRUN pip install ."
        result = run_tests("tag", cf, host="host")
        assert result is None


class TestCdToProjectRoot:
    """Verify test_runner prepends build-file discovery to find the project root."""

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_maven_prepends_pom_discovery(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Tests run: 5, Failures: 0, Errors: 0, Skipped: 0\nBUILD SUCCESS",
            stderr="",
        )
        cf = "FROM openjdk:17\nRUN mvn install -B"
        result = run_tests("tag", cf)
        assert result is not None
        cmd = mock_run.call_args[0][0]
        shell_script = cmd[-1]
        assert "find . -maxdepth 5 -name pom.xml" in shell_script
        assert "cd \"$(dirname \"$POM\")\"" in shell_script
        assert shell_script.endswith("mvn test -B")

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_gradle_prepends_gradlew_discovery(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="10 tests completed, 0 failed\n",
            stderr="",
        )
        cf = "FROM openjdk:17\nRUN ./gradlew build"
        result = run_tests("tag", cf)
        assert result is not None
        cmd = mock_run.call_args[0][0]
        shell_script = cmd[-1]
        assert "find . -maxdepth 5 -name gradlew" in shell_script
        assert "cd \"$(dirname \"$GW\")\"" in shell_script
        assert shell_script.endswith("./gradlew test")

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_ant_no_cd_prefix(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="BUILD SUCCESSFUL", stderr="",
        )
        cf = "FROM openjdk:17\nCOPY build.xml .\nRUN ant build"
        result = run_tests("tag", cf)
        assert result is not None
        cmd = mock_run.call_args[0][0]
        shell_script = cmd[-1]
        assert "find ." not in shell_script
        assert shell_script == "ant test"

    @patch("buildroot.eval.test_runner.subprocess.run")
    def test_maven_cd_falls_back_to_workdir(self, mock_run):
        """When find returns nothing, the if-guard is a no-op and test runs from WORKDIR."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Tests run: 3, Failures: 0, Errors: 0, Skipped: 0",
            stderr="",
        )
        cf = "FROM openjdk:17\nRUN mvn install -B"
        result = run_tests("tag", cf)
        assert result is not None
        cmd = mock_run.call_args[0][0]
        shell_script = cmd[-1]
        assert "if [ -n \"$POM\" ]" in shell_script
        assert "|| true" in shell_script
