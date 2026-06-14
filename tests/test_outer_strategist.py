"""Tests for outer strategist — J(S) scoring, hypothesis generation, stagnation detection."""

import math
from pathlib import Path
from unittest.mock import patch

from buildroot.agent.claude_runner import AgentResult
from buildroot.agent.failure_analyst import ErrorClassFrequency, FailureAnalysis
from buildroot.agent.outer_strategist import (
    CodeChangeHypothesis,
    StrategyArchive,
    StrategyScore,
    _fallback_hypothesis,
    compute_j_score,
    propose_hypothesis,
)


class TestComputeJScore:
    def test_zero_improvement(self):
        j = compute_j_score(0.5, 0.5)
        assert j == 0.0

    def test_positive_improvement(self):
        j = compute_j_score(0.3, 0.5)
        assert j > 0

    def test_regression_negative(self):
        j = compute_j_score(0.5, 0.3)
        assert j < 0

    def test_log_upweights_higher_baseline(self):
        j_low = compute_j_score(0.1, 0.3)
        j_high = compute_j_score(0.5, 0.7)
        # Same delta (0.2), but higher baseline gets more credit
        assert j_high > j_low

    def test_window_size_reduces_score(self):
        j1 = compute_j_score(0.3, 0.5, window_size=1)
        j4 = compute_j_score(0.3, 0.5, window_size=4)
        assert j1 > j4

    def test_zero_baseline(self):
        j = compute_j_score(0.0, 0.5)
        expected = 0.5 * math.log(1 + 0.01)
        assert abs(j - expected) < 1e-10

    def test_window_size_zero_treated_as_one(self):
        j = compute_j_score(0.3, 0.5, window_size=0)
        assert j == compute_j_score(0.3, 0.5, window_size=1)

    def test_formula_correctness(self):
        s_start, s_end, w = 0.3, 0.6, 2
        expected = (s_end - s_start) * math.log(1 + s_start + 0.01) / math.sqrt(w)
        actual = compute_j_score(s_start, s_end, window_size=w)
        assert abs(actual - expected) < 1e-10


class TestStrategyArchive:
    def test_empty_archive(self):
        archive = StrategyArchive()
        assert len(archive.scores) == 0
        assert not archive.is_stagnant
        assert archive.historical_best_solve_rate == 0.0

    def test_add_score(self):
        archive = StrategyArchive()
        score = StrategyScore(cycle=1, solve_rate_before=0.0, solve_rate_after=0.5, j_score=0.1)
        archive.add(score)
        assert len(archive.scores) == 1
        assert archive.historical_best_solve_rate == 0.5

    def test_stagnation_after_3_low_scores(self):
        archive = StrategyArchive(j_threshold=0.01)
        for i in range(3):
            archive.add(StrategyScore(
                cycle=i + 1, solve_rate_before=0.3,
                solve_rate_after=0.3, j_score=0.005,
            ))
        assert archive.is_stagnant

    def test_no_stagnation_with_improvement(self):
        archive = StrategyArchive(j_threshold=0.01)
        archive.add(StrategyScore(cycle=1, solve_rate_before=0.3, solve_rate_after=0.3, j_score=0.005))
        archive.add(StrategyScore(cycle=2, solve_rate_before=0.3, solve_rate_after=0.3, j_score=0.005))
        archive.add(StrategyScore(cycle=3, solve_rate_before=0.3, solve_rate_after=0.5, j_score=0.05))
        assert not archive.is_stagnant

    def test_last_n(self):
        archive = StrategyArchive()
        for i in range(10):
            archive.add(StrategyScore(
                cycle=i, solve_rate_before=0.0, solve_rate_after=0.1 * i, j_score=0.01,
            ))
        last_3 = archive.last_n(3)
        assert len(last_3) == 3
        assert last_3[0].cycle == 7

    def test_save_and_load(self, tmp_path: Path):
        archive = StrategyArchive()
        hyp = CodeChangeHypothesis(
            target_error_class="test", files_to_modify=["a.py"],
            expected_impact="fix", rationale="because",
        )
        archive.add(StrategyScore(
            cycle=1, solve_rate_before=0.3, solve_rate_after=0.5,
            j_score=0.1, hypothesis=hyp, verdict="keep",
        ))
        path = tmp_path / "archive.json"
        archive.save(path)
        loaded = StrategyArchive.load(path)
        assert len(loaded.scores) == 1
        assert loaded.scores[0].hypothesis is not None
        assert loaded.scores[0].hypothesis.target_error_class == "test"
        assert loaded.scores[0].verdict == "keep"

    def test_load_nonexistent_returns_empty(self, tmp_path: Path):
        archive = StrategyArchive.load(tmp_path / "missing.json")
        assert len(archive.scores) == 0


class TestCodeChangeHypothesis:
    def test_to_dict(self):
        hyp = CodeChangeHypothesis(
            target_error_class="compilation/jdk_mismatch",
            files_to_modify=["builder.py"],
            expected_impact="Fix JDK",
            rationale="JDK mismatch common",
            priority=1,
        )
        d = hyp.to_dict()
        assert d["target_error_class"] == "compilation/jdk_mismatch"
        assert d["files_to_modify"] == ["builder.py"]
        assert d["priority"] == 1


class TestProposeHypothesis:
    @patch("buildroot.agent.outer_strategist.spawn_claude_agent")
    def test_proposes_from_agent(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="",
            structured_output={
                "target_error_class": "compilation/jdk_mismatch",
                "files_to_modify": ["src/buildroot/agent/builder.py"],
                "expected_impact": "Fix JDK selection",
                "rationale": "JDK mismatch is dominant",
                "priority": 1,
            },
        )
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(error_class="compilation/jdk_mismatch", count=5),
            ],
        )
        archive = StrategyArchive()
        hyp = propose_hypothesis(analysis, archive)
        assert hyp.target_error_class == "compilation/jdk_mismatch"
        assert mock_spawn.called

    @patch("buildroot.agent.outer_strategist.spawn_claude_agent")
    def test_falls_back_on_agent_error(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="", is_error=True, error_message="timeout",
        )
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(error_class="compilation/jdk_mismatch", count=5),
            ],
        )
        archive = StrategyArchive()
        hyp = propose_hypothesis(analysis, archive)
        assert hyp.target_error_class == "compilation/jdk_mismatch"

    @patch("buildroot.agent.outer_strategist.spawn_claude_agent")
    def test_research_report_in_prompt(self, mock_spawn):
        mock_spawn.return_value = AgentResult(
            text="",
            structured_output={
                "target_error_class": "test",
                "files_to_modify": ["src/buildroot/agent/builder.py"],
                "expected_impact": "test",
                "rationale": "test",
            },
        )
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(error_class="test", count=1),
            ],
        )
        propose_hypothesis(
            analysis, StrategyArchive(),
            research_report="JDK 17 fixes this issue",
        )
        system_prompt = mock_spawn.call_args.kwargs.get(
            "system_prompt", mock_spawn.call_args[1].get("system_prompt", "")
        )
        assert "JDK 17 fixes this issue" in system_prompt


class TestFallbackHypothesis:
    def test_proposes_for_dominant_error(self):
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(error_class="compilation/jdk_mismatch", count=5),
            ],
        )
        hyp = _fallback_hypothesis(analysis, set())
        assert hyp.target_error_class == "compilation/jdk_mismatch"

    def test_skips_previously_reverted(self):
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(error_class="compilation/jdk_mismatch", count=5),
                ErrorClassFrequency(error_class="plugin/configuration_error", count=3),
            ],
        )
        hyp = _fallback_hypothesis(analysis, {"compilation/jdk_mismatch"})
        assert hyp.target_error_class == "plugin/configuration_error"

    def test_empty_analysis_proposes_builder(self):
        analysis = FailureAnalysis()
        hyp = _fallback_hypothesis(analysis, set())
        assert "builder.py" in hyp.files_to_modify[0]

    def test_skips_exhausted_error_class(self):
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(
                    error_class="compilation/jdk_mismatch", count=5,
                    exhausted_count=5, under_explored_count=0,
                ),
                ErrorClassFrequency(
                    error_class="plugin/configuration_error", count=3,
                    exhausted_count=0, under_explored_count=3,
                ),
            ],
        )
        hyp = _fallback_hypothesis(analysis, set())
        assert hyp.target_error_class == "plugin/configuration_error"

    def test_architectural_when_all_exhausted(self):
        analysis = FailureAnalysis(
            error_frequencies=[
                ErrorClassFrequency(
                    error_class="compilation/jdk_mismatch", count=5,
                    exhausted_count=5, under_explored_count=0,
                ),
            ],
        )
        hyp = _fallback_hypothesis(analysis, set())
        assert hyp.target_error_class == "architectural"
