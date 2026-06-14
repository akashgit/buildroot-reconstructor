"""Tests for the Outer Researcher agent."""

from pathlib import Path
from unittest.mock import patch

from buildroot.agent.claude_runner import AgentResult
from buildroot.agent.failure_analyst import ErrorClassFrequency, FailureAnalysis
from buildroot.agent.outer_researcher import research_failures


class TestResearchFailures:
    @patch("buildroot.agent.outer_researcher.spawn_claude_agent")
    def test_produces_report(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="## Research Report\nJDK mismatch is commonly caused by...",
            cost_usd=0.10,
        )
        analysis = FailureAnalysis(
            total_packages=3,
            failed_packages=2,
            solved_packages=1,
            solve_rate=0.333,
            dominant_error_class="compilation/jdk_mismatch",
            error_frequencies=[
                ErrorClassFrequency(
                    error_class="compilation/jdk_mismatch",
                    count=2,
                    packages=["org.foo:bar:1.0", "org.baz:qux:2.0"],
                ),
            ],
        )
        report = research_failures(analysis, kb_patterns="Use JDK 17")
        assert "JDK mismatch" in report
        assert mock_spawn.called

    @patch("buildroot.agent.outer_researcher.spawn_claude_agent")
    def test_writes_output_file(self, mock_spawn, tmp_path: Path):
        mock_spawn.return_value = AgentResult(
            text="Research findings here.",
            cost_usd=0.05,
        )
        analysis = FailureAnalysis(
            failed_packages=1,
            dominant_error_class="test",
            error_frequencies=[
                ErrorClassFrequency(error_class="test", count=1, packages=["g:a:1"]),
            ],
        )
        out = tmp_path / "report.md"
        report = research_failures(analysis, output_path=out)
        assert out.exists()
        assert out.read_text().strip() == "Research findings here."
        assert report == "Research findings here."

    @patch("buildroot.agent.outer_researcher.spawn_claude_agent")
    def test_returns_empty_on_error(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="", is_error=True, error_message="timeout",
        )
        analysis = FailureAnalysis(
            failed_packages=1,
            dominant_error_class="test",
            error_frequencies=[
                ErrorClassFrequency(error_class="test", count=1, packages=["g:a:1"]),
            ],
        )
        report = research_failures(analysis)
        assert report == ""

    @patch("buildroot.agent.outer_researcher.spawn_claude_agent")
    def test_failure_context_in_system_prompt(self, mock_spawn):
        mock_spawn.return_value = AgentResult(text="report", cost_usd=0.01)
        analysis = FailureAnalysis(
            total_packages=5,
            failed_packages=3,
            dominant_error_class="dependency_resolution/missing_artifact",
            error_frequencies=[
                ErrorClassFrequency(
                    error_class="dependency_resolution/missing_artifact",
                    count=3,
                    packages=["g:a:1", "g:b:2", "g:c:3"],
                ),
            ],
        )
        research_failures(analysis, kb_patterns="existing patterns")
        system_prompt = mock_spawn.call_args.kwargs.get(
            "system_prompt", mock_spawn.call_args[1].get("system_prompt", "")
        )
        assert "dependency_resolution/missing_artifact" in system_prompt
        assert "existing patterns" in system_prompt

    @patch("buildroot.agent.outer_researcher.spawn_claude_agent")
    def test_uses_web_search_tools(self, mock_spawn):
        mock_spawn.return_value = AgentResult(text="report", cost_usd=0.01)
        analysis = FailureAnalysis(
            failed_packages=1,
            dominant_error_class="test",
            error_frequencies=[
                ErrorClassFrequency(error_class="test", count=1, packages=["g:a:1"]),
            ],
        )
        research_failures(analysis)
        call_kwargs = mock_spawn.call_args.kwargs
        allowed_tools = call_kwargs.get("allowed_tools", [])
        assert "WebSearch" in allowed_tools
