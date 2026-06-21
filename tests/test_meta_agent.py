"""Tests for meta_agent — unit tests for _parse_agent_output and _build_task_prompt."""

from __future__ import annotations

from pathlib import Path

from buildroot.agent.meta_agent import (
    OrchestratorResult,
    _build_task_prompt,
    _parse_agent_output,
)


class TestParseAgentOutput:
    def test_parses_success_line(self):
        result = OrchestratorResult()
        text = "some output\nRESULT: SUCCESS coordinate=g:a:1.0 reward=0.9988 level=4 path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0", "host")
        assert result.status == "success"
        assert result.best_reward == 0.9988
        assert result.best_level == 4
        assert result.path == "v3"

    def test_parses_stagnation_line(self):
        result = OrchestratorResult()
        text = "RESULT: STAGNATION coordinate=g:a:1.0 reward=0.15 level=2 path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0", "host")
        assert result.status == "stagnation"
        assert result.best_reward == 0.15
        assert result.best_level == 2

    def test_parses_budget_exhausted(self):
        result = OrchestratorResult()
        text = "RESULT: BUDGET_EXHAUSTED coordinate=g:a:1.0 reward=0.50 level=3 path=takeover"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0", "host")
        assert result.status == "budget_exhausted"
        assert result.path == "takeover"

    def test_finds_result_on_last_line(self):
        result = OrchestratorResult()
        text = "line1\nline2\nRESULT: SUCCESS coordinate=g:a:1.0 reward=1.0 level=4 path=v3\n"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0", "host")
        assert result.status == "success"
        assert result.best_reward == 1.0

    def test_no_result_line_leaves_defaults(self):
        result = OrchestratorResult()
        _parse_agent_output("no result here\njust logs", result, Path("/tmp"), "g:a:1.0", "host")
        assert result.status == "budget_exhausted"
        assert result.best_reward == 0.0

    def test_handles_invalid_reward(self):
        result = OrchestratorResult()
        text = "RESULT: SUCCESS coordinate=g:a:1.0 reward=notanumber level=4 path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0", "host")
        assert result.best_reward == 0.0

    def test_handles_invalid_level(self):
        result = OrchestratorResult()
        text = "RESULT: SUCCESS coordinate=g:a:1.0 reward=0.5 level=xyz path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0", "host")
        assert result.best_level == 0

    def test_handles_empty_text(self):
        result = OrchestratorResult()
        _parse_agent_output("", result, Path("/tmp"), "g:a:1.0", "host")
        assert result.status == "budget_exhausted"

    def test_parses_result_with_extra_whitespace(self):
        result = OrchestratorResult()
        text = "   RESULT: SUCCESS coordinate=g:a:1.0 reward=0.75 level=3 path=takeover   "
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0", "host")
        assert result.status == "success"
        assert result.best_reward == 0.75


class TestBuildTaskPrompt:
    def test_contains_coordinate(self):
        prompt = _build_task_prompt("org.example:lib:1.0", "host1", Path("/ws"), 0.98)
        assert "org.example:lib:1.0" in prompt

    def test_contains_host(self):
        prompt = _build_task_prompt("g:a:1.0", "rh-h100-01", Path("/ws"), 0.98)
        assert "rh-h100-01" in prompt

    def test_contains_workspace(self):
        prompt = _build_task_prompt("g:a:1.0", "host", Path("/my/workspace"), 0.98)
        assert "/my/workspace" in prompt

    def test_contains_target_score(self):
        prompt = _build_task_prompt("g:a:1.0", "host", Path("/ws"), 0.95)
        assert "0.95" in prompt

    def test_contains_v3_command(self):
        prompt = _build_task_prompt("g:a:1.0", "host", Path("/ws"), 0.98)
        assert "--v3-only" in prompt
        assert "buildroot agent" in prompt

    def test_contains_eval_command(self):
        prompt = _build_task_prompt("g:a:1.0", "host", Path("/ws"), 0.98)
        assert "buildroot eval" in prompt


class TestOrchestratorResult:
    def test_default_values(self):
        r = OrchestratorResult()
        assert r.status == "budget_exhausted"
        assert r.best_reward == 0.0
        assert r.iterations == 0

    def test_to_dict(self):
        r = OrchestratorResult(
            coordinate="g:a:1.0",
            status="success",
            best_reward=0.9988,
            best_level=4,
            iterations=3,
            path="v3",
            elapsed_seconds=120.5,
            cost_usd=2.50,
        )
        d = r.to_dict()
        assert d["coordinate"] == "g:a:1.0"
        assert d["status"] == "success"
        assert d["best_reward"] == 0.9988
        assert d["best_level"] == 4
        assert d["elapsed_seconds"] == 120.5
        assert d["cost_usd"] == 2.5
