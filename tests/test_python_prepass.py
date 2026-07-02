"""Tests for the Python pre-pass pipeline."""

from __future__ import annotations

import io
import tarfile
from unittest.mock import patch

import pytest

from buildroot.agent.prepass import PrePassFinding
from buildroot.agent.prepass_python import (
    PyPrePassFindings,
    _build_command_for_backend,
    _discover_repo_from_pypi,
    _extract_pyproject_from_sdist,
    parse_python_coordinate,
    run_python_prepass,
)


# ---------------------------------------------------------------------------
# TestParseCoordinate
# ---------------------------------------------------------------------------

class TestParseCoordinate:
    def test_double_equals(self):
        assert parse_python_coordinate("requests==2.31.0") == ("requests", "2.31.0")

    def test_single_equals(self):
        assert parse_python_coordinate("click=8.1.7") == ("click", "8.1.7")

    def test_colon_separator(self):
        assert parse_python_coordinate("six:1.16.0") == ("six", "1.16.0")

    def test_whitespace(self):
        assert parse_python_coordinate("  requests == 2.31.0 ") == ("requests", "2.31.0")

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_python_coordinate("requests")

    def test_empty_version(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_python_coordinate("requests==")

    def test_empty_package(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_python_coordinate("==2.31.0")


# ---------------------------------------------------------------------------
# TestDiscoverRepoFromPyPI
# ---------------------------------------------------------------------------

class TestDiscoverRepoFromPyPI:
    def test_with_source_url(self):
        metadata = {
            "info": {
                "project_urls": {
                    "Source": "https://github.com/psf/requests",
                }
            }
        }
        assert _discover_repo_from_pypi(metadata) == ("psf", "requests")

    def test_with_homepage(self):
        metadata = {
            "info": {
                "project_urls": None,
                "home_page": "https://github.com/pallets/click",
            }
        }
        assert _discover_repo_from_pypi(metadata) == ("pallets", "click")

    def test_with_git_plus_url(self):
        metadata = {
            "info": {
                "project_urls": {
                    "Repository": "git+https://github.com/owner/repo.git",
                }
            }
        }
        assert _discover_repo_from_pypi(metadata) == ("owner", "repo")

    def test_no_url(self):
        metadata = {"info": {"project_urls": None, "home_page": ""}}
        assert _discover_repo_from_pypi(metadata) is None

    def test_non_github_url(self):
        metadata = {
            "info": {
                "project_urls": {
                    "Source": "https://gitlab.com/owner/repo",
                },
                "home_page": "",
            }
        }
        assert _discover_repo_from_pypi(metadata) is None

    def test_github_url_with_tree_path(self):
        metadata = {
            "info": {
                "project_urls": {
                    "Source": "https://github.com/owner/repo/tree/main",
                }
            }
        }
        assert _discover_repo_from_pypi(metadata) == ("owner", "repo")

    def test_source_code_key(self):
        metadata = {
            "info": {
                "project_urls": {
                    "Source Code": "https://github.com/org/project",
                }
            }
        }
        assert _discover_repo_from_pypi(metadata) == ("org", "project")


# ---------------------------------------------------------------------------
# TestBuildCommandForBackend
# ---------------------------------------------------------------------------

class TestBuildCommandForBackend:
    def test_setuptools(self):
        assert _build_command_for_backend("setuptools") == "python -m build --sdist"

    def test_poetry(self):
        assert _build_command_for_backend("poetry") == "poetry build --format sdist"

    def test_flit(self):
        assert _build_command_for_backend("flit") == "python -m build --sdist"

    def test_hatch(self):
        assert _build_command_for_backend("hatch") == "python -m build --sdist"

    def test_maturin(self):
        assert _build_command_for_backend("maturin") == "python -m build --sdist"

    def test_unknown_defaults(self):
        assert _build_command_for_backend("weird-backend") == "python -m build --sdist"


# ---------------------------------------------------------------------------
# TestPyPrePassFindings
# ---------------------------------------------------------------------------

class TestPyPrePassFindings:
    def test_to_prompt_format(self):
        findings = PyPrePassFindings()
        findings.pyproject_data.name = "requests"
        findings.pyproject_data.version = "2.31.0"
        findings.build_backend = PrePassFinding(
            value="setuptools", source="pyproject_toml",
            confidence="high", evidence="build-backend field",
        )
        findings.python_version = PrePassFinding(
            value="3.11", source="resolver",
            confidence="medium", evidence="from requires-python",
        )
        findings.attempted_but_failed.append("CI workflow fetch: no workflows found")

        prompt = findings.to_prompt()
        assert "## Pre-Pass Findings (Python)" in prompt
        assert "requests==2.31.0" in prompt
        assert "setuptools" in prompt
        assert "3.11" in prompt
        assert "Attempted But Failed" in prompt
        assert "CI workflow fetch" in prompt

    def test_to_prompt_with_dependencies(self):
        findings = PyPrePassFindings()
        findings.pyproject_data.dependencies = ["click>=8.0", "rich>=10.0"]
        prompt = findings.to_prompt()
        assert "### Dependencies" in prompt
        assert "click>=8.0" in prompt

    def test_to_dict_serialization(self):
        findings = PyPrePassFindings()
        findings.pyproject_data.name = "mypackage"
        findings.pyproject_data.version = "1.0.0"
        findings.build_backend = PrePassFinding(
            value="setuptools", source="pyproject_toml",
            confidence="high", evidence="build-backend",
        )
        findings.sdist_entry_count = 42
        findings.env_vars = {"FOO": "bar"}
        findings.attempted_but_failed.append("test failure")

        d = findings.to_dict()
        assert d["build_backend"]["value"] == "setuptools"
        assert d["sdist_entry_count"] == 42
        assert d["env_vars"] == {"FOO": "bar"}
        assert "test failure" in d["attempted_but_failed"]
        assert d["pyproject_data"]["name"] == "mypackage"

    def test_to_dict_empty(self):
        findings = PyPrePassFindings()
        d = findings.to_dict()
        # No findings, so dict should be empty except possibly empty lists
        assert "build_backend" not in d
        assert "python_version" not in d


# ---------------------------------------------------------------------------
# TestExtractPyprojectFromSdist
# ---------------------------------------------------------------------------

class TestExtractPyprojectFromSdist:
    def test_extract_pyproject_toml(self, tmp_path):
        """Create a test sdist with pyproject.toml and verify extraction."""
        sdist_path = tmp_path / "test-1.0.0.tar.gz"
        pyproject_content = '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n'

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            data = pyproject_content.encode("utf-8")
            info = tarfile.TarInfo(name="test-1.0.0/pyproject.toml")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        sdist_path.write_bytes(buf.getvalue())

        result = _extract_pyproject_from_sdist(sdist_path)
        assert result is not None
        assert "setuptools" in result
        assert "build-backend" in result

    def test_extract_missing_file(self, tmp_path):
        """sdist without pyproject.toml returns None."""
        sdist_path = tmp_path / "test-1.0.0.tar.gz"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="test-1.0.0/setup.py")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        sdist_path.write_bytes(buf.getvalue())

        result = _extract_pyproject_from_sdist(sdist_path)
        assert result is None

    def test_extract_nonexistent_path(self, tmp_path):
        result = _extract_pyproject_from_sdist(tmp_path / "doesnotexist.tar.gz")
        assert result is None


# ---------------------------------------------------------------------------
# TestRunPythonPrepass
# ---------------------------------------------------------------------------

class TestRunPythonPrepass:
    """Test the full pipeline with mocked external calls."""

    @patch("buildroot.agent.prepass_python.pypi_client")
    def test_full_pipeline(self, mock_pypi, tmp_path):
        """Mock everything and verify the pipeline runs end-to-end."""
        # Set up PyPI metadata
        mock_pypi.fetch_package_metadata.return_value = {
            "info": {
                "project_urls": {
                    "Source": "https://github.com/psf/requests",
                },
                "classifiers": [
                    "Programming Language :: Python :: 3.11",
                    "Programming Language :: Python :: 3.12",
                ],
                "requires_python": ">=3.8",
                "home_page": "",
            },
            "urls": [],
        }
        mock_pypi.extract_classifiers.return_value = [
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
        ]
        mock_pypi.extract_python_requires.return_value = ">=3.8"

        # Make download_sdist create a minimal tarball
        def fake_download_sdist(pkg, ver, dest, **kwargs):
            pyproject = (
                '[build-system]\nrequires = ["setuptools>=64"]\n'
                'build-backend = "setuptools.build_meta"\n\n'
                '[project]\nname = "requests"\nversion = "2.31.0"\n'
                'requires-python = ">=3.8"\n'
            )
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                data = pyproject.encode()
                info = tarfile.TarInfo(name="requests-2.31.0/pyproject.toml")
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))

                pkg_info = b"Name: requests\nVersion: 2.31.0\nSummary: HTTP library\n"
                info2 = tarfile.TarInfo(name="requests-2.31.0/PKG-INFO")
                info2.size = len(pkg_info)
                tf.addfile(info2, io.BytesIO(pkg_info))

            dest.write_bytes(buf.getvalue())
            return dest

        mock_pypi.download_sdist.side_effect = fake_download_sdist

        workspace = tmp_path / "workspace"

        with patch("buildroot.agent.prepass_python.discover_git_tag", return_value="v2.31.0"):
            with patch("buildroot.utils.github_api.list_directory", return_value=None):
                findings = run_python_prepass("requests==2.31.0", workspace)

        assert findings.pyproject_data.name == "requests"
        assert findings.source_repo is not None
        assert findings.source_repo.value == "https://github.com/psf/requests"
        assert findings.git_tag is not None
        assert findings.git_tag.value == "v2.31.0"
        assert findings.build_backend is not None
        assert findings.build_backend.value == "setuptools"
        assert findings.build_command is not None
        assert "build --sdist" in findings.build_command.value
        assert findings.python_version is not None
        assert findings.base_image is not None
        assert findings.sdist_path is not None
        assert findings.sdist_entry_count is not None
        assert findings.pkg_info.get("Name") == "requests"

    @patch("buildroot.agent.prepass_python.pypi_client")
    def test_pipeline_with_pypi_failure(self, mock_pypi, tmp_path):
        """Pipeline should handle PyPI failure gracefully."""
        mock_pypi.fetch_package_metadata.side_effect = Exception("network error")

        workspace = tmp_path / "workspace"
        findings = run_python_prepass("badpkg==0.0.1", workspace)

        assert "PyPI metadata fetch" in findings.attempted_but_failed[0]
        assert findings.source_repo is None
        assert findings.build_backend is None

    def test_invalid_coordinate(self, tmp_path):
        with pytest.raises(ValueError, match="Cannot parse"):
            run_python_prepass("badcoordinate", tmp_path / "workspace")

    @patch("buildroot.agent.prepass_python.pypi_client")
    def test_pipeline_no_sdist(self, mock_pypi, tmp_path):
        """Pipeline should handle missing sdist gracefully."""
        mock_pypi.fetch_package_metadata.return_value = {
            "info": {
                "project_urls": None,
                "classifiers": [],
                "requires_python": "",
                "home_page": "",
            },
            "urls": [],
        }
        mock_pypi.extract_classifiers.return_value = []
        mock_pypi.extract_python_requires.return_value = ""
        mock_pypi.download_sdist.side_effect = ValueError("No sdist found")

        workspace = tmp_path / "workspace"
        findings = run_python_prepass("nosrc==1.0.0", workspace)

        assert any("sdist download" in f for f in findings.attempted_but_failed)
        # Should still have build_backend (defaulted) and python_version
        assert findings.build_backend is not None
        assert findings.python_version is not None
