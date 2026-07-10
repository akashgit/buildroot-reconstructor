"""Tests validating Containerfile structure and CVE fix presence."""

from __future__ import annotations

import json
from pathlib import Path

INTAKE_PATH = Path(__file__).resolve().parent.parent / ".factory" / "cve" / "intake.json"


def _load_containerfile() -> str:
    data = json.loads(INTAKE_PATH.read_text(encoding="utf-8"))
    containerfile: str = data["containerfile"]
    return containerfile


class TestContainerfileStructure:
    def test_containerfile_exists_in_intake(self) -> None:
        assert INTAKE_PATH.exists(), f"intake.json not found at {INTAKE_PATH}"
        data = json.loads(INTAKE_PATH.read_text(encoding="utf-8"))
        assert "containerfile" in data, "intake.json missing 'containerfile' field"

    def test_has_from_directive(self) -> None:
        content = _load_containerfile()
        lines = [line.strip() for line in content.splitlines() if line.strip().startswith("FROM")]
        assert len(lines) >= 1, "Containerfile must have at least one FROM directive"

    def test_has_run_directive(self) -> None:
        content = _load_containerfile()
        lines = [line.strip() for line in content.splitlines() if line.strip().startswith("RUN")]
        assert len(lines) >= 1, "Containerfile must have at least one RUN directive"

    def test_has_workdir_directive(self) -> None:
        content = _load_containerfile()
        lines = [line.strip() for line in content.splitlines() if line.strip().startswith("WORKDIR")]
        assert len(lines) >= 1, "Containerfile must have at least one WORKDIR directive"

    def test_has_file_operations(self) -> None:
        content = _load_containerfile()
        has_copy = any(line.strip().startswith("COPY") for line in content.splitlines())
        has_cp = "cp " in content
        has_curl = "curl " in content
        assert has_copy or has_cp or has_curl, "Containerfile must have file transfer operations (COPY, cp, or curl)"

    def test_targets_correct_java_files(self) -> None:
        content = _load_containerfile()
        assert "SessionFactoryUtils.java" in content, "Must reference SessionFactoryUtils.java"
        assert "SpringSessionSynchronization.java" in content, "Must reference SpringSessionSynchronization.java"

    def test_disconnect_fix_referenced(self) -> None:
        content = _load_containerfile()
        assert "disconnect" in content, "Containerfile should reference disconnect() for the CVE fix"

    def test_sed_commands_present(self) -> None:
        content = _load_containerfile()
        assert "sed -i" in content, "Containerfile should use sed for patching"
