"""Tests validating research documentation quality."""

from __future__ import annotations

from pathlib import Path

RESEARCH_PATH = Path(__file__).resolve().parent.parent / ".factory" / "cve" / "research.md"
FIX_PLAN_PATH = Path(__file__).resolve().parent.parent / ".factory" / "cve" / "fix-plan.md"


class TestResearchQuality:
    def test_research_has_cwe_classification(self) -> None:
        assert RESEARCH_PATH.exists(), f"research.md not found at {RESEARCH_PATH}"
        content = RESEARCH_PATH.read_text(encoding="utf-8")
        assert "CWE-400" in content, "Research must include CWE-400 classification"

    def test_research_has_upstream_comparison(self) -> None:
        content = RESEARCH_PATH.read_text(encoding="utf-8")
        assert "upstream" in content.lower(), "Research must include upstream comparison"
        assert "Spring Framework" in content, "Research must reference upstream Spring Framework"

    def test_research_has_exploit_mechanism(self) -> None:
        content = RESEARCH_PATH.read_text(encoding="utf-8")
        assert "exploit" in content.lower(), "Research must document exploit mechanism"
        assert "connection pool" in content.lower(), "Research must describe connection pool exhaustion"

    def test_research_has_root_cause(self) -> None:
        content = RESEARCH_PATH.read_text(encoding="utf-8")
        assert "disconnect()" in content, "Research must identify disconnect() as root cause"


class TestFixPlanQuality:
    def test_fix_plan_has_affected_files(self) -> None:
        assert FIX_PLAN_PATH.exists(), f"fix-plan.md not found at {FIX_PLAN_PATH}"
        content = FIX_PLAN_PATH.read_text(encoding="utf-8")
        assert "SpringSessionSynchronization.java" in content, "Fix plan must list affected files"

    def test_fix_plan_has_technique(self) -> None:
        content = FIX_PLAN_PATH.read_text(encoding="utf-8")
        assert "sed" in content.lower() or "restore" in content.lower(), "Fix plan must describe fix technique"

    def test_fix_plan_has_conservativeness(self) -> None:
        content = FIX_PLAN_PATH.read_text(encoding="utf-8")
        lower = content.lower()
        assert "conservative" in lower or "minimal" in lower, "Fix plan must assess conservativeness"
