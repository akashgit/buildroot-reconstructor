"""Tests for failure analyst — batch analysis, error aggregation, stagnation detection."""

from pathlib import Path

from buildroot.agent.failure_analyst import (
    ErrorClassFrequency,
    FailureAnalysis,
    analyze_batch,
)


class TestAnalyzeBatch:
    def test_empty_batch(self):
        result = analyze_batch([])
        assert result.total_packages == 0
        assert result.failed_packages == 0
        assert result.solved_packages == 0
        assert result.solve_rate == 0.0

    def test_all_solved(self):
        batch = [
            {"coordinate": "g:a:1.0", "best_reward": 1.0, "status": "success"},
            {"coordinate": "g:b:1.0", "best_reward": 0.98, "status": "success"},
        ]
        result = analyze_batch(batch)
        assert result.total_packages == 2
        assert result.solved_packages == 2
        assert result.failed_packages == 0
        assert result.solve_rate == 1.0

    def test_mixed_results(self):
        batch = [
            {"coordinate": "g:a:1.0", "best_reward": 1.0, "status": "success"},
            {"coordinate": "g:b:1.0", "best_reward": 0.15, "status": "budget_exhausted",
             "attempts": [{"error_class": "compilation/jdk_mismatch"}]},
            {"coordinate": "g:c:1.0", "best_reward": 0.05, "status": "budget_exhausted",
             "attempts": [{"error_class": "compilation/jdk_mismatch"}]},
        ]
        result = analyze_batch(batch)
        assert result.total_packages == 3
        assert result.solved_packages == 1
        assert result.failed_packages == 2
        assert abs(result.solve_rate - 1 / 3) < 0.01

    def test_dominant_error_class(self):
        batch = [
            {"coordinate": f"g:pkg{i}:1.0", "best_reward": 0.1,
             "attempts": [{"error_class": "compilation/jdk_mismatch"}]}
            for i in range(5)
        ]
        result = analyze_batch(batch)
        assert result.dominant_error_class == "compilation/jdk_mismatch"

    def test_multiple_error_classes_sorted_by_frequency(self):
        batch = [
            {"coordinate": "g:a:1.0", "best_reward": 0.1,
             "attempts": [{"error_class": "compilation/jdk_mismatch"},
                          {"error_class": "compilation/jdk_mismatch"}]},
            {"coordinate": "g:b:1.0", "best_reward": 0.1,
             "attempts": [{"error_class": "compilation/jdk_mismatch"}]},
            {"coordinate": "g:c:1.0", "best_reward": 0.1,
             "attempts": [{"error_class": "plugin/configuration_error"}]},
        ]
        result = analyze_batch(batch)
        assert len(result.error_frequencies) == 2
        assert result.error_frequencies[0].error_class == "compilation/jdk_mismatch"
        assert result.error_frequencies[0].count == 2

    def test_exhausted_classification(self):
        batch = [
            {"coordinate": "g:a:1.0", "best_reward": 0.1, "iterations": 15,
             "attempts": [{"error_class": "compilation/jdk_mismatch"}],
             "dead_ends": [{"is_exhausted": True}, {"is_exhausted": True}, {"is_exhausted": True}]},
        ]
        result = analyze_batch(batch, max_iterations=15)
        assert result.error_frequencies[0].exhausted_count == 1

    def test_under_explored_classification(self):
        batch = [
            {"coordinate": "g:a:1.0", "best_reward": 0.1, "iterations": 3,
             "attempts": [{"error_class": "compilation/jdk_mismatch"}],
             "dead_ends": []},
        ]
        result = analyze_batch(batch, max_iterations=15)
        assert result.error_frequencies[0].under_explored_count == 1

    def test_no_attempts_uses_error_summary(self):
        batch = [
            {"coordinate": "g:a:1.0", "best_reward": 0.1,
             "error_summary": "Could not resolve artifact foo:bar:1.0"},
        ]
        result = analyze_batch(batch)
        assert result.dominant_error_class == "dependency_resolution/missing_artifact"


class TestStagnationDetection:
    def test_no_stagnation_with_few_failures(self):
        batch = [
            {"coordinate": f"g:pkg{i}:1.0", "best_reward": 0.1,
             "attempts": [{"error_class": "compilation/jdk_mismatch"}]}
            for i in range(5)
        ]
        result = analyze_batch(batch)
        assert not result.is_stagnant

    def test_stagnation_triggered(self):
        batch = [
            {"coordinate": f"g:pkg{i}:1.0", "best_reward": 0.1,
             "attempts": [{"error_class": "compilation/jdk_mismatch"}]}
            for i in range(10)
        ]
        result = analyze_batch(batch)
        assert result.is_stagnant
        assert "compilation/jdk_mismatch" in result.stagnation_reason

    def test_stagnation_not_triggered_with_diverse_errors(self):
        classes = [
            "compilation/jdk_mismatch",
            "dependency_resolution/missing_artifact",
            "plugin/configuration_error",
            "source/wrong_tag",
            "build_tool/multi_module",
        ]
        batch = [
            {"coordinate": f"g:pkg{i}:1.0", "best_reward": 0.1,
             "attempts": [{"error_class": classes[i % len(classes)]}]}
            for i in range(10)
        ]
        result = analyze_batch(batch)
        assert not result.is_stagnant


class TestFailureAnalysisSerialization:
    def test_save_and_load(self, tmp_path: Path):
        analysis = FailureAnalysis(
            total_packages=10,
            failed_packages=7,
            solved_packages=3,
            solve_rate=0.3,
            dominant_error_class="compilation/jdk_mismatch",
            error_frequencies=[
                ErrorClassFrequency(
                    error_class="compilation/jdk_mismatch",
                    count=5,
                    packages=["g:a:1.0", "g:b:1.0"],
                    exhausted_count=2,
                    under_explored_count=3,
                ),
            ],
        )
        path = tmp_path / "analysis.json"
        analysis.save(path)
        loaded = FailureAnalysis.load(path)
        assert loaded.total_packages == 10
        assert loaded.solve_rate == 0.3
        assert len(loaded.error_frequencies) == 1
        assert loaded.error_frequencies[0].count == 5

    def test_to_dict(self):
        analysis = FailureAnalysis(total_packages=5, solved_packages=2, solve_rate=0.4)
        d = analysis.to_dict()
        assert d["total_packages"] == 5
        assert d["solve_rate"] == 0.4


class TestErrorClassFrequency:
    def test_to_dict(self):
        ef = ErrorClassFrequency(
            error_class="test", count=3, packages=["a", "b"],
        )
        d = ef.to_dict()
        assert d["error_class"] == "test"
        assert d["count"] == 3
        assert len(d["packages"]) == 2
