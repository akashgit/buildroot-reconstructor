"""Tests for meta_agent — unit tests for _parse_agent_output, _build_task_prompt, and cascade."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from buildroot.agent.meta_agent import (
    OrchestratorResult,
    _build_task_prompt,
    _generate_delta_report,
    _generate_trust_report,
    _parse_agent_output,
    _restructure_output,
    _run_trusted_phase,
)
from buildroot.agent.meta_prompt import (
    build_trusted_orchestrator_prompt,
    _build_trusted_task_prompt,
)


class TestParseAgentOutput:
    def test_parses_success_line(self):
        result = OrchestratorResult()
        text = "some output\nRESULT: SUCCESS coordinate=g:a:1.0 reward=0.9988 level=4 path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0")
        assert result.status == "success"
        assert result.best_reward == 0.9988
        assert result.best_level == 4
        assert result.path == "v3"

    def test_parses_stagnation_line(self):
        result = OrchestratorResult()
        text = "RESULT: STAGNATION coordinate=g:a:1.0 reward=0.15 level=2 path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0")
        assert result.status == "stagnation"
        assert result.best_reward == 0.15
        assert result.best_level == 2

    def test_parses_budget_exhausted(self):
        result = OrchestratorResult()
        text = "RESULT: BUDGET_EXHAUSTED coordinate=g:a:1.0 reward=0.50 level=3 path=takeover"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0")
        assert result.status == "budget_exhausted"
        assert result.path == "takeover"

    def test_finds_result_on_last_line(self):
        result = OrchestratorResult()
        text = "line1\nline2\nRESULT: SUCCESS coordinate=g:a:1.0 reward=1.0 level=4 path=v3\n"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0")
        assert result.status == "success"
        assert result.best_reward == 1.0

    def test_no_result_line_leaves_defaults(self):
        result = OrchestratorResult()
        _parse_agent_output("no result here\njust logs", result, Path("/tmp"), "g:a:1.0")
        assert result.status == "budget_exhausted"
        assert result.best_reward == 0.0

    def test_handles_invalid_reward(self):
        result = OrchestratorResult()
        text = "RESULT: SUCCESS coordinate=g:a:1.0 reward=notanumber level=4 path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0")
        assert result.best_reward == 0.0

    def test_handles_invalid_level(self):
        result = OrchestratorResult()
        text = "RESULT: SUCCESS coordinate=g:a:1.0 reward=0.5 level=xyz path=v3"
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0")
        assert result.best_level == 0

    def test_handles_empty_text(self):
        result = OrchestratorResult()
        _parse_agent_output("", result, Path("/tmp"), "g:a:1.0")
        assert result.status == "budget_exhausted"

    def test_parses_result_with_extra_whitespace(self):
        result = OrchestratorResult()
        text = "   RESULT: SUCCESS coordinate=g:a:1.0 reward=0.75 level=3 path=takeover   "
        _parse_agent_output(text, result, Path("/tmp"), "g:a:1.0")
        assert result.status == "success"
        assert result.best_reward == 0.75


class TestBuildTaskPrompt:
    def test_contains_coordinate(self):
        prompt = _build_task_prompt("org.example:lib:1.0", None, Path("/ws"), 0.98)
        assert "org.example:lib:1.0" in prompt

    def test_contains_host_when_specified(self):
        prompt = _build_task_prompt("g:a:1.0", "myhost", Path("/ws"), 0.98)
        assert "myhost" in prompt
        assert "--host myhost" in prompt

    def test_local_when_no_host(self):
        prompt = _build_task_prompt("g:a:1.0", None, Path("/ws"), 0.98)
        assert "--host" not in prompt
        assert "locally" in prompt

    def test_contains_workspace(self):
        prompt = _build_task_prompt("g:a:1.0", None, Path("/my/workspace"), 0.98)
        assert "/my/workspace" in prompt

    def test_contains_target_score(self):
        prompt = _build_task_prompt("g:a:1.0", None, Path("/ws"), 0.95)
        assert "0.95" in prompt

    def test_contains_v3_command(self):
        prompt = _build_task_prompt("g:a:1.0", None, Path("/ws"), 0.98)
        assert "--v3-only" in prompt
        assert "buildroot agent" in prompt

    def test_contains_eval_command(self):
        prompt = _build_task_prompt("g:a:1.0", None, Path("/ws"), 0.98)
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

    def test_to_dict_with_trusted_fields(self):
        r = OrchestratorResult(
            coordinate="g:a:1.0",
            trusted_reward=0.95,
            trusted_level=4,
            trusted_containerfile="FROM eclipse-temurin:17-jdk",
            trusted_containerfile_path="/ws/trusted/Containerfile",
        )
        d = r.to_dict()
        assert "trusted" in d
        assert d["trusted"]["reward"] == 0.95
        assert d["trusted"]["level"] == 4


class TestCascadePipeline:
    """Integration tests for the Phase 3 cascade pipeline."""

    def _make_phase2_result(self, **kwargs):
        defaults = dict(
            coordinate="g:a:1.0",
            status="success",
            best_reward=0.9988,
            best_level=4,
            best_containerfile="FROM amazoncorretto:17\nRUN mvn clean install",
            best_containerfile_path="/ws/Containerfile.best",
            path="takeover",
            cost_usd=1.50,
        )
        defaults.update(kwargs)
        return OrchestratorResult(**defaults)

    @patch("buildroot.agent.meta_agent.spawn_claude_agent")
    @patch("buildroot.agent.meta_agent._scan_workspace_for_best")
    def test_cascade_phase3_spawned(self, mock_scan, mock_spawn, tmp_path):
        """Phase 3 spawns a second Claude agent when Phase 2 produces a Containerfile."""
        mock_spawn.return_value = MagicMock(
            is_error=False,
            text="RESULT: SUCCESS coordinate=g:a:1.0 reward=0.85 level=3 path=trusted",
            cost_usd=0.50,
        )

        result = self._make_phase2_result()
        _run_trusted_phase(
            coordinate="g:a:1.0",
            workspace=tmp_path,
            phase2_result=result,
            prepass_summary="JDK 17",
            kb_context="",
            host="rh-h100-01",
            max_budget_usd=5.0,
            max_agent_turns=30,
            agent_timeout=600,
            target_score=0.98,
        )

        mock_spawn.assert_called_once()
        call_kwargs = mock_spawn.call_args
        assert call_kwargs.kwargs["cwd"] == str(tmp_path / "trusted")

    @patch("buildroot.agent.meta_agent.spawn_claude_agent")
    @patch("buildroot.agent.meta_agent._scan_workspace_for_best")
    def test_phase3_prompt_contains_phase2_findings(self, mock_scan, mock_spawn, tmp_path):
        """Phase 3 system prompt includes Phase 2's Containerfile and reward."""
        mock_spawn.return_value = MagicMock(
            is_error=False,
            text="RESULT: STAGNATION coordinate=g:a:1.0 reward=0.50 level=2 path=trusted",
            cost_usd=0.30,
        )

        result = self._make_phase2_result()
        _run_trusted_phase(
            coordinate="g:a:1.0",
            workspace=tmp_path,
            phase2_result=result,
            prepass_summary="",
            kb_context="",
            host="rh-h100-01",
            max_budget_usd=5.0,
            max_agent_turns=30,
            agent_timeout=600,
            target_score=0.98,
        )

        call_kwargs = mock_spawn.call_args
        system_prompt = call_kwargs.kwargs["system_prompt"]
        assert "amazoncorretto:17" in system_prompt
        assert "0.9988" in system_prompt

    @patch("buildroot.agent.meta_agent.spawn_claude_agent")
    @patch("buildroot.agent.meta_agent._scan_workspace_for_best")
    def test_phase3_task_uses_trusted_flag(self, mock_scan, mock_spawn, tmp_path):
        """Phase 3 task prompt contains --trusted flag."""
        mock_spawn.return_value = MagicMock(
            is_error=False,
            text="RESULT: SUCCESS coordinate=g:a:1.0 reward=0.90 level=4 path=trusted",
            cost_usd=0.40,
        )

        result = self._make_phase2_result()
        _run_trusted_phase(
            coordinate="g:a:1.0",
            workspace=tmp_path,
            phase2_result=result,
            prepass_summary="",
            kb_context="",
            host="rh-h100-01",
            max_budget_usd=5.0,
            max_agent_turns=30,
            agent_timeout=600,
            target_score=0.98,
        )

        call_kwargs = mock_spawn.call_args
        task = call_kwargs.kwargs["task"]
        assert "--trusted" in task

    @patch("buildroot.agent.meta_agent.spawn_claude_agent")
    @patch("buildroot.agent.meta_agent._scan_workspace_for_best")
    def test_orchestrator_result_has_trusted_fields(self, mock_scan, mock_spawn, tmp_path):
        """After cascade, trusted_reward and trusted_level are populated."""
        def populate_scan(res, ws, coord, host):
            res.best_reward = 0.85
            res.best_level = 3
            res.best_containerfile = "FROM eclipse-temurin:17-jdk\nRUN mvn install"
            res.best_containerfile_path = str(ws / "Containerfile.best")

        mock_scan.side_effect = populate_scan
        mock_spawn.return_value = MagicMock(
            is_error=False,
            text="RESULT: SUCCESS coordinate=g:a:1.0 reward=0.85 level=3 path=trusted",
            cost_usd=0.50,
        )

        result = self._make_phase2_result()
        _run_trusted_phase(
            coordinate="g:a:1.0",
            workspace=tmp_path,
            phase2_result=result,
            prepass_summary="",
            kb_context="",
            host="rh-h100-01",
            max_budget_usd=5.0,
            max_agent_turns=30,
            agent_timeout=600,
            target_score=0.98,
        )

        assert result.trusted_reward == 0.85
        assert result.trusted_level == 3
        assert result.trusted_containerfile == "FROM eclipse-temurin:17-jdk\nRUN mvn install"

    def test_output_structure(self, tmp_path):
        """Verify exact/ and trusted/ dirs, delta_report.json, trust_report.md exist."""
        result = self._make_phase2_result(
            trusted_reward=0.90,
            trusted_level=3,
            trusted_containerfile="FROM eclipse-temurin:17-jdk\nRUN mvn install",
            trusted_containerfile_path=str(tmp_path / "trusted" / "Containerfile"),
        )

        _restructure_output(tmp_path, result)
        _generate_trust_report(tmp_path, result, "g:a:1.0")

        assert (tmp_path / "exact" / "Containerfile").exists()
        assert (tmp_path / "exact" / "buildroot.json").exists()
        assert (tmp_path / "trusted" / "Containerfile").exists()
        assert (tmp_path / "trusted" / "buildroot.json").exists()
        assert (tmp_path / "trust_report.md").exists()

        trust_report = (tmp_path / "trust_report.md").read_text()
        assert "g:a:1.0" in trust_report
        assert "0.9988" in trust_report
        assert "0.9000" in trust_report

    @patch("buildroot.agent.meta_agent.Evaluator")
    def test_delta_report_real_verdict(self, MockEvaluator, tmp_path):
        """delta_report.json contains functional_equivalence != NOT_EVALUATED."""
        result = self._make_phase2_result(
            trusted_reward=0.90,
            trusted_level=4,
            trusted_containerfile="FROM eclipse-temurin:17-jdk\nRUN mvn install",
        )

        _restructure_output(tmp_path, result)

        mock_report = MagicMock()
        mock_report.equivalence_score.return_value = 0.98
        mock_report.structural.match = True
        mock_report.metadata.match = True
        mock_report.bytecode.match = False

        mock_eval_result = MagicMock()
        mock_eval_result.comparison_report = mock_report

        MockEvaluator.return_value.evaluate.return_value = mock_eval_result

        _generate_delta_report(tmp_path, result, "g:a:1.0", "rh-h100-01")

        delta = json.loads((tmp_path / "delta_report.json").read_text())
        assert delta["functional_equivalence"] != "NOT_EVALUATED"
        assert delta["functional_equivalence"] in ("IDENTICAL", "EQUIVALENT", "DIVERGENT")

    def test_v3_iterations_default_1(self):
        """Task prompt has --max-iterations 1."""
        prompt = _build_task_prompt("g:a:1.0", "host", Path("/ws"), 0.98)
        assert "--max-iterations 1" in prompt

    @patch("buildroot.agent.meta_agent.spawn_claude_agent")
    @patch("buildroot.agent.meta_agent._scan_workspace_for_best")
    def test_phase3_always_runs(self, mock_scan, mock_spawn, tmp_path):
        """Phase 3 runs even when Phase 2 reward is low (no threshold gate)."""
        mock_spawn.return_value = MagicMock(
            is_error=False,
            text="RESULT: STAGNATION coordinate=g:a:1.0 reward=0.0 level=0 path=trusted",
            cost_usd=0.10,
        )

        result = self._make_phase2_result(best_reward=0.15, best_level=2)
        _run_trusted_phase(
            coordinate="g:a:1.0",
            workspace=tmp_path,
            phase2_result=result,
            prepass_summary="",
            kb_context="",
            host="rh-h100-01",
            max_budget_usd=5.0,
            max_agent_turns=30,
            agent_timeout=600,
            target_score=0.98,
        )

        mock_spawn.assert_called_once()
