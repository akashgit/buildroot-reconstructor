"""Tests for the shared Claude Code subprocess runner."""

import json
from unittest.mock import MagicMock, patch

from buildroot.agent.claude_runner import AgentResult, spawn_claude_agent


class TestAgentResult:
    def test_ok_when_no_error(self):
        r = AgentResult(text="hello")
        assert r.ok

    def test_not_ok_on_error(self):
        r = AgentResult(text="", is_error=True, error_message="fail")
        assert not r.ok


class TestSpawnClaudeAgent:
    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_basic_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "FROM maven:3.9\nRUN mvn install",
                "is_error": False,
                "total_cost_usd": 0.05,
                "num_turns": 3,
            }),
            stderr="",
        )
        result = spawn_claude_agent(
            task="Fix this Containerfile",
            system_prompt="You are an expert.",
        )
        assert result.ok
        assert "maven" in result.text
        assert result.cost_usd == 0.05
        assert result.num_turns == 3

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_passes_correct_flags(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "ok"}),
        )
        spawn_claude_agent(
            task="do it",
            system_prompt="prompt",
            model="claude-opus-4-6",
            max_turns=15,
            max_budget_usd=3.0,
        )
        cmd = mock_run.call_args[0][0]
        assert "claude" in cmd[0]
        assert "--bare" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "--model" in cmd
        assert "claude-opus-4-6" in cmd
        assert "--max-turns" in cmd
        assert "15" in cmd
        assert "--dangerously-skip-permissions" in cmd

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_json_schema_passed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "",
                "structured_output": {"key": "value"},
            }),
        )
        schema = {"type": "object", "properties": {"key": {"type": "string"}}}
        result = spawn_claude_agent(
            task="do it",
            system_prompt="prompt",
            json_schema=schema,
        )
        cmd = mock_run.call_args[0][0]
        assert "--json-schema" in cmd
        assert result.structured_output == {"key": "value"}

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_nonzero_exit_returns_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="auth failed",
        )
        result = spawn_claude_agent(task="t", system_prompt="p")
        assert result.is_error
        assert "auth failed" in result.error_message

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_timeout_returns_error(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=60)
        result = spawn_claude_agent(task="t", system_prompt="p", timeout=60)
        assert result.is_error
        assert "timed out" in result.error_message

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_claude_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = spawn_claude_agent(task="t", system_prompt="p")
        assert result.is_error
        assert "not found" in result.error_message

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_invalid_json_returns_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not json",
        )
        result = spawn_claude_agent(task="t", system_prompt="p")
        assert result.is_error
        assert "JSON" in result.error_message

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_allowed_tools_passed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "ok"}),
        )
        spawn_claude_agent(
            task="t",
            system_prompt="p",
            allowed_tools=["Read", "Edit", "Bash"],
        )
        cmd = mock_run.call_args[0][0]
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Read,Edit,Bash"

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_cwd_passed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "ok"}),
        )
        spawn_claude_agent(task="t", system_prompt="p", cwd="/tmp/project")
        assert mock_run.call_args[1]["cwd"] == "/tmp/project"

    @patch("buildroot.agent.claude_runner.subprocess.run")
    def test_agent_reports_error_in_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "",
                "is_error": True,
                "error": "budget exceeded",
            }),
        )
        result = spawn_claude_agent(task="t", system_prompt="p")
        assert result.is_error
        assert result.error_message == "budget exceeded"
