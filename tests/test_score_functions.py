"""Tests that exercise eval.score functions for coverage."""

from __future__ import annotations

from eval.score import (
    eval_capability_surface,
    eval_observability,
    eval_research_grounding,
    eval_syntax_check,
    eval_test_coverage,
)


class TestEvalSyntaxCheck:
    def test_returns_scored_result(self) -> None:
        result = eval_syntax_check()
        assert "name" in result
        assert result["name"] == "syntax_check"
        assert "score" in result
        assert 0.0 <= result["score"] <= 1.0
        assert "weight" in result
        assert "passed" in result
        assert "details" in result


class TestEvalResearchGrounding:
    def test_returns_scored_result(self) -> None:
        result = eval_research_grounding()
        assert result["name"] == "research_grounding"
        assert 0.0 <= result["score"] <= 1.0
        assert isinstance(result["passed"], bool)


class TestEvalObservability:
    def test_returns_scored_result(self) -> None:
        result = eval_observability()
        assert result["name"] == "observability"
        assert 0.0 <= result["score"] <= 1.0


class TestEvalCapabilitySurface:
    def test_returns_scored_result(self) -> None:
        result = eval_capability_surface()
        assert result["name"] == "capability_surface"
        assert 0.0 <= result["score"] <= 1.0


class TestEvalTestCoverage:
    def test_returns_scored_result(self) -> None:
        result = eval_test_coverage()
        assert result["name"] == "test_coverage"
        assert 0.0 <= result["score"] <= 1.0
        assert result["passed"] is True
