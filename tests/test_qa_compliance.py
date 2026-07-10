"""Tests for qa_compliance and experiment_diversity eval dimensions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from eval.score import eval_experiment_diversity, eval_qa_compliance


class TestQaCompliance:
    def test_returns_correct_score_for_existing_archive(self) -> None:
        result = eval_qa_compliance()
        assert result["name"] == "qa_compliance"
        assert result["score"] == 1.0
        assert result["weight"] == 0.10
        assert result["passed"] is True
        assert "5/5" in result["details"]

    def test_handles_missing_archive(self, tmp_path: Path) -> None:
        fake_factory = tmp_path / ".factory" / "archive"
        fake_factory.mkdir(parents=True)
        with patch("eval.score.FACTORY_DIR", tmp_path / ".factory"):
            result = eval_qa_compliance()
        assert result["score"] == 0.0
        assert result["passed"] is False
        assert "not found" in result["details"]

    def test_handles_archive_without_sections(self, tmp_path: Path) -> None:
        fake_factory = tmp_path / ".factory"
        archive_dir = fake_factory / "archive"
        archive_dir.mkdir(parents=True)
        (archive_dir / "cve-remediation.md").write_text("No QA sections here.")
        with patch("eval.score.FACTORY_DIR", fake_factory):
            result = eval_qa_compliance()
        assert result["score"] == 0.0
        assert result["passed"] is False

    def test_partial_sections(self, tmp_path: Path) -> None:
        fake_factory = tmp_path / ".factory"
        archive_dir = fake_factory / "archive"
        archive_dir.mkdir(parents=True)
        content = "- **Health Check**: PASS\n- **Scope Check**: PASS\n"
        (archive_dir / "cve-remediation.md").write_text(content)
        with patch("eval.score.FACTORY_DIR", fake_factory):
            result = eval_qa_compliance()
        assert result["score"] == 0.4
        assert result["passed"] is False


class TestExperimentDiversity:
    def test_returns_correct_score_for_existing_fix_plan(self) -> None:
        result = eval_experiment_diversity()
        assert result["name"] == "experiment_diversity"
        assert result["score"] >= 0.6
        assert result["weight"] == 0.10
        assert result["passed"] is True

    def test_handles_missing_fix_plan(self, tmp_path: Path) -> None:
        fake_factory = tmp_path / ".factory" / "cve"
        fake_factory.mkdir(parents=True)
        with patch("eval.score.FACTORY_DIR", tmp_path / ".factory"):
            result = eval_experiment_diversity()
        assert result["score"] == 0.0
        assert result["passed"] is False
        assert "not found" in result["details"]

    def test_handles_empty_fix_plan(self, tmp_path: Path) -> None:
        fake_factory = tmp_path / ".factory"
        cve_dir = fake_factory / "cve"
        cve_dir.mkdir(parents=True)
        (cve_dir / "fix-plan.md").write_text("Empty plan with no keywords.")
        with patch("eval.score.FACTORY_DIR", fake_factory):
            result = eval_experiment_diversity()
        assert result["score"] == 0.0
        assert result["passed"] is False
