"""Tests for PyPI client metadata fetching and caching."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from buildroot.utils.pypi_client import (
    download_sdist,
    extract_classifiers,
    extract_project_urls,
    extract_python_requires,
    fetch_package_metadata,
)

SAMPLE_METADATA = {
    "info": {
        "name": "requests",
        "version": "2.31.0",
        "requires_python": ">=3.7",
        "home_page": "https://requests.readthedocs.io",
        "project_urls": {
            "Source": "https://github.com/psf/requests",
            "Documentation": "https://requests.readthedocs.io",
        },
        "classifiers": [
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.11",
        ],
    },
    "urls": [
        {
            "packagetype": "sdist",
            "url": "https://files.pythonhosted.org/packages/requests-2.31.0.tar.gz",
            "digests": {"sha256": "abc123"},
        },
        {
            "packagetype": "bdist_wheel",
            "url": "https://files.pythonhosted.org/packages/requests-2.31.0-py3-none-any.whl",
            "digests": {"sha256": "def456"},
        },
    ],
}


class TestFetchPackageMetadata:
    @patch("buildroot.utils.pypi_client._fetch_with_retry")
    def test_returns_parsed_json(self, mock_fetch):
        mock_fetch.return_value = json.dumps(SAMPLE_METADATA)
        result = fetch_package_metadata("requests", "2.31.0", no_cache=True)
        assert result["info"]["name"] == "requests"
        assert result["info"]["version"] == "2.31.0"

    @patch("buildroot.utils.pypi_client._fetch_with_retry")
    def test_calls_correct_url(self, mock_fetch):
        mock_fetch.return_value = json.dumps(SAMPLE_METADATA)
        fetch_package_metadata("requests", "2.31.0", no_cache=True)
        mock_fetch.assert_called_once_with(
            "https://pypi.org/pypi/requests/2.31.0/json"
        )


class TestDownloadSdist:
    @patch("buildroot.utils.pypi_client.fetch_package_metadata")
    @patch("buildroot.utils.pypi_client.requests.get")
    def test_download_with_checksum(self, mock_get, mock_meta, tmp_path):
        import hashlib

        content = b"fake tarball content"
        expected_sha = hashlib.sha256(content).hexdigest()

        mock_meta.return_value = {
            "urls": [{
                "packagetype": "sdist",
                "url": "https://example.com/pkg.tar.gz",
                "digests": {"sha256": expected_sha},
            }],
        }

        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.iter_content.return_value = [content]
        mock_get.return_value = mock_response

        dest = tmp_path / "pkg.tar.gz"
        result = download_sdist("pkg", "1.0.0", dest)
        assert result == dest
        assert dest.read_bytes() == content

    @patch("buildroot.utils.pypi_client.fetch_package_metadata")
    def test_no_sdist_raises(self, mock_meta):
        mock_meta.return_value = {"urls": []}
        with pytest.raises(ValueError, match="No sdist found"):
            download_sdist("pkg", "1.0.0", Path("/tmp/out.tar.gz"))


class TestExtractProjectUrls:
    def test_extracts_urls(self):
        urls = extract_project_urls(SAMPLE_METADATA)
        assert urls["Source"] == "https://github.com/psf/requests"
        assert urls["Homepage"] == "https://requests.readthedocs.io"

    def test_empty_metadata(self):
        assert extract_project_urls({}) == {}


class TestCaching:
    @patch("buildroot.utils.pypi_client._fetch_with_retry")
    def test_cache_write_and_read(self, mock_fetch, tmp_path):
        mock_fetch.return_value = json.dumps(SAMPLE_METADATA)

        result1 = fetch_package_metadata(
            "requests", "2.31.0", cache_dir=tmp_path
        )
        assert mock_fetch.call_count == 1

        result2 = fetch_package_metadata(
            "requests", "2.31.0", cache_dir=tmp_path
        )
        assert mock_fetch.call_count == 1
        assert result1 == result2

    @patch("buildroot.utils.pypi_client._fetch_with_retry")
    def test_no_cache_bypasses(self, mock_fetch, tmp_path):
        mock_fetch.return_value = json.dumps(SAMPLE_METADATA)

        fetch_package_metadata(
            "requests", "2.31.0", no_cache=True, cache_dir=tmp_path
        )
        fetch_package_metadata(
            "requests", "2.31.0", no_cache=True, cache_dir=tmp_path
        )
        assert mock_fetch.call_count == 2


class TestExtractHelpers:
    def test_python_requires(self):
        assert extract_python_requires(SAMPLE_METADATA) == ">=3.7"

    def test_classifiers(self):
        classifiers = extract_classifiers(SAMPLE_METADATA)
        assert len(classifiers) == 3
        assert "Programming Language :: Python :: 3.11" in classifiers
