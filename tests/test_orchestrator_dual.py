"""Tests for dual-variant orchestration in BuildrootOrchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from buildroot.pipeline.orchestrator import BuildrootOrchestrator


def _mock_reconstruct_deps():
    """Patch all network calls used by reconstruct()."""
    patches = {}

    mock_pom_xml = """<?xml version="1.0"?>
    <project>
        <groupId>org.example</groupId>
        <artifactId>test</artifactId>
        <version>1.0</version>
    </project>"""

    patches["fetch_pom"] = patch(
        "buildroot.pipeline.orchestrator.fetch_pom",
        return_value=mock_pom_xml,
    )
    patches["discover_repo"] = patch(
        "buildroot.pipeline.orchestrator.discover_repo_from_pom",
        return_value=None,
    )
    patches["discover_tag"] = patch(
        "buildroot.pipeline.orchestrator.discover_git_tag",
        return_value="v1.0",
    )
    return patches


class TestDualBuildTrue:
    def test_creates_subdirs(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(
                skip_deps=True, dual_build=True,
            )
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        assert (tmp_path / "Containerfile").exists()
        assert (tmp_path / "exact" / "Containerfile").exists()
        assert (tmp_path / "trusted" / "Containerfile").exists()

    def test_delta_report_created(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(
                skip_deps=True, dual_build=True,
            )
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        delta_path = tmp_path / "delta_report.json"
        assert delta_path.exists()
        data = json.loads(delta_path.read_text())
        assert "coordinate" in data
        assert data["coordinate"] == "org.example:test:1.0"
        assert "exact" in data
        assert "trusted" in data
        assert "functional_equivalence" in data
        assert "recommendation" in data

    def test_sbom_generated_for_both_variants(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(
                skip_deps=True, dual_build=True,
            )
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        assert (tmp_path / "exact" / "sbom.cdx.json").exists()
        assert (tmp_path / "trusted" / "sbom.cdx.json").exists()


class TestDualBuildFalse:
    def test_no_subdirs(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(
                skip_deps=True, dual_build=False,
            )
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        assert (tmp_path / "Containerfile").exists()
        assert not (tmp_path / "exact").exists()
        assert not (tmp_path / "trusted").exists()
        assert not (tmp_path / "delta_report.json").exists()


class TestBackwardCompatibility:
    def test_primary_containerfile_always_exists(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(
                skip_deps=True, dual_build=True,
            )
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        assert (tmp_path / "Containerfile").exists()
        assert (tmp_path / "buildroot.json").exists()
