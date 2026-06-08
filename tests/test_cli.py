"""Tests for CLI commands."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from buildroot.cli.main import cli


class TestCLIHelp:
    def test_reconstruct_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["reconstruct", "--help"])
        assert result.exit_code == 0
        assert "COORDINATE" in result.output
        assert "--repo-url" in result.output
        assert "--no-cache" in result.output
        assert "--skip-deps" in result.output
        assert "--output-dir" in result.output
        assert "--runtime" in result.output

    def test_inspect_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "--help"])
        assert result.exit_code == 0
        assert "COORDINATE" in result.output
        assert "--no-cache" in result.output

    def test_verify_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "--help"])
        assert result.exit_code == 0
        assert "COORDINATE" in result.output
        assert "--rebuild" in result.output
        assert "--runtime" in result.output
        assert "--output-dir" in result.output

    def test_main_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "reconstruct" in result.output
        assert "verify" in result.output
        assert "inspect" in result.output


class TestCLIReconstructCommand:
    @patch("buildroot.cli.commands.reconstruct.BuildrootOrchestrator")
    def test_reconstruct_spring_boot(self, MockOrchestrator):
        from buildroot.pipeline.models import BuildrootSpec, GapReport, JdkSpec, PomData

        mock_spec = BuildrootSpec(
            pom_data=PomData(
                group_id="org.springframework.boot",
                artifact_id="spring-boot",
                version="2.7.18",
            ),
            jdk_spec=JdkSpec(version="17"),
            gaps=GapReport(),
        )
        mock_instance = MockOrchestrator.return_value
        mock_instance.reconstruct.return_value = mock_spec

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, [
                "reconstruct",
                "org.springframework.boot:spring-boot:2.7.18",
                "--skip-deps",
                "--output-dir", ".",
            ])
            assert result.exit_code == 0
            assert "Containerfile" in result.output

    def test_reconstruct_invalid_coordinate(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["reconstruct", "invalid"])
        assert result.exit_code != 0


class TestCLIInspectCommand:
    @patch("buildroot.cli.commands.inspect_cmd.BuildrootOrchestrator")
    def test_inspect_outputs_json(self, MockOrchestrator):
        mock_instance = MockOrchestrator.return_value
        mock_instance.inspect.return_value = {
            "coordinate": "com.example:test:1.0",
            "pom_data": {"groupId": "com.example"},
            "jdk_spec": {"version": "17"},
        }

        runner = CliRunner()
        result = runner.invoke(cli, [
            "inspect",
            "com.example:test:1.0",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["coordinate"] == "com.example:test:1.0"


class TestCLIVerifyCommand:
    @patch("buildroot.cli.commands.verify.BuildrootOrchestrator")
    def test_verify_outputs_json(self, MockOrchestrator):
        mock_instance = MockOrchestrator.return_value
        mock_instance.verify.return_value = {
            "coordinate": "com.example:test:1.0",
            "checks": [
                {"name": "jdk_version", "status": "MATCH"},
            ],
        }

        runner = CliRunner()
        result = runner.invoke(cli, [
            "verify",
            "com.example:test:1.0",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["checks"][0]["status"] == "MATCH"
