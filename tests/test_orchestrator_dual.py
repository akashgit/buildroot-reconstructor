"""Tests for BuildrootOrchestrator after dual-build removal."""

from __future__ import annotations

from unittest.mock import patch

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


class TestReconstructExactOnly:
    def test_creates_containerfile(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(skip_deps=True)
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        assert (tmp_path / "Containerfile").exists()

    def test_no_dual_subdirs(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(skip_deps=True)
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        assert not (tmp_path / "exact").exists()
        assert not (tmp_path / "trusted").exists()
        assert not (tmp_path / "delta_report.json").exists()

    def test_primary_containerfile_always_exists(self, tmp_path):
        patches = _mock_reconstruct_deps()
        with (
            patches["fetch_pom"],
            patches["discover_repo"],
            patches["discover_tag"],
        ):
            orch = BuildrootOrchestrator(skip_deps=True)
            orch.reconstruct(
                "org.example", "test", "1.0",
                output_dir=str(tmp_path),
            )

        assert (tmp_path / "Containerfile").exists()
        assert (tmp_path / "buildroot.json").exists()
