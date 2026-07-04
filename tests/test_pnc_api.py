"""Unit tests for PNC API client."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from buildroot.utils.pnc_api import (
    PncBuildInfo,
    PncClient,
    extract_builder_image,
    extract_scm_info,
    parse_image_name_versions,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pnc"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


class TestParseImageNameVersions:
    def test_maven_image(self):
        result = parse_image_name_versions(
            "quay.io/rh-newcastle/builder-rhel-7-j8-mvn3.6.3@sha256:abc123"
        )
        assert result["jdk"] == "8"
        assert result["maven"] == "3.6.3"
        assert result["gradle"] is None
        assert result["rhel"] == "7"

    def test_gradle_image(self):
        result = parse_image_name_versions(
            "quay.io/rh-newcastle/builder-rhel-8-j11-gradle7.4.2@sha256:def456"
        )
        assert result["jdk"] == "11"
        assert result["maven"] is None
        assert result["gradle"] == "7.4.2"
        assert result["rhel"] == "8"

    def test_no_match(self):
        result = parse_image_name_versions("ubuntu:22.04")
        assert result["jdk"] is None
        assert result["maven"] is None

    def test_rhel9(self):
        result = parse_image_name_versions(
            "builder-rhel-9-j17-mvn3.8.6"
        )
        assert result["rhel"] == "9"
        assert result["jdk"] == "17"
        assert result["maven"] == "3.8.6"


class TestExtractBuilderImage:
    def test_extracts_from_fixture(self):
        data = _load_fixture("pnc_response_sha256_commons_lang3.json")
        image = extract_builder_image(data)
        assert image is not None
        assert "quay.io/rh-newcastle" in image
        assert "builder-rhel-7-j8-mvn3.6.3" in image
        assert "sha256:" in image

    def test_missing_fields(self):
        data = {
            "content": [
                {
                    "build": {
                        "environment": {
                            "systemImageRepositoryUrl": "",
                            "attributes": {},
                        }
                    }
                }
            ]
        }
        assert extract_builder_image(data) is None

    def test_empty_content(self):
        data = _load_fixture("pnc_response_empty.json")
        assert extract_builder_image(data) is None


class TestExtractScmInfo:
    def test_extracts_upstream(self):
        data = _load_fixture("pnc_response_sha256_commons_lang3.json")
        scm = extract_scm_info(data)
        assert scm is not None
        assert scm["scm_external_url"] == "https://github.com/apache/commons-lang.git"
        assert scm["scm_revision"] == "rel/commons-lang-3.12.0"
        assert scm["scm_url"] == "git+ssh://code.engineering.redhat.com/commons-lang.git"
        assert scm["scm_tag"] == "commons-lang-3.12.0.redhat-00001"

    def test_no_build(self):
        data = {"content": [{"id": "1"}]}
        assert extract_scm_info(data) is None


class TestPncClient:
    def test_query_by_sha256_success(self, tmp_path):
        fixture = _load_fixture("pnc_response_sha256_commons_lang3.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fixture

        client = PncClient(cache_dir=tmp_path / "cache")

        with patch.object(client._session, "get", return_value=mock_resp):
            info = client.query_by_sha256("abc123def456")

        assert info is not None
        assert info.build_id == "12345"
        assert info.jdk_version == "8"
        assert info.maven_version == "3.6.3"
        assert info.rhel_version == "7"
        assert "quay.io/rh-newcastle" in info.builder_image

    def test_query_by_gav_success(self, tmp_path):
        fixture = _load_fixture("pnc_response_gav_jackson_core.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fixture

        client = PncClient(cache_dir=tmp_path / "cache")

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            info = client.query_by_gav(
                "com.fasterxml.jackson.core", "jackson-annotations", "2.9.9.redhat-00001"
            )
            call_args = mock_get.call_args
            assert "maven:com.fasterxml.jackson.core:jackson-annotations:2.9.9.redhat-00001" in str(
                call_args
            )

        assert info is not None
        assert info.build_id == "67890"
        assert info.scm_external_url == "https://github.com/FasterXML/jackson-annotations.git"

    def test_query_by_sha256_not_found(self, tmp_path):
        fixture = _load_fixture("pnc_response_empty.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fixture

        client = PncClient(cache_dir=tmp_path / "cache")

        with patch.object(client._session, "get", return_value=mock_resp):
            info = client.query_by_sha256("nonexistent_hash")

        assert info is None

    def test_connection_error_returns_none(self, tmp_path):
        client = PncClient(cache_dir=tmp_path / "cache")

        with patch.object(
            client._session, "get", side_effect=requests.ConnectionError("no VPN")
        ):
            info = client.query_by_sha256("abc123")

        assert info is None

    def test_http_400_returns_none(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 400

        client = PncClient(cache_dir=tmp_path / "cache")

        with patch.object(client._session, "get", return_value=mock_resp):
            info = client.query_by_sha256("bad_request")

        assert info is None

    def test_tls_verify_disabled(self, tmp_path):
        client = PncClient(tls_verify=False, cache_dir=tmp_path / "cache")
        assert client._verify is False

        fixture = _load_fixture("pnc_response_sha256_commons_lang3.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fixture

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.query_by_sha256("abc123")
            _, kwargs = mock_get.call_args
            assert kwargs["verify"] is False

    def test_cache_hit(self, tmp_path):
        fixture = _load_fixture("pnc_response_sha256_commons_lang3.json")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        cache_file = cache_dir / "sha256-abc123.json"
        cache_file.write_text(json.dumps(fixture))

        client = PncClient(cache_dir=cache_dir)

        with patch.object(client._session, "get") as mock_get:
            info = client.query_by_sha256("abc123")
            mock_get.assert_not_called()

        assert info is not None
        assert info.build_id == "12345"

    def test_cache_expired(self, tmp_path):
        fixture = _load_fixture("pnc_response_sha256_commons_lang3.json")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        cache_file = cache_dir / "sha256-abc123.json"
        cache_file.write_text(json.dumps(fixture))
        old_time = time.time() - (8 * 24 * 3600)
        os.utime(cache_file, (old_time, old_time))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fixture

        client = PncClient(cache_dir=cache_dir)

        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            info = client.query_by_sha256("abc123")
            mock_get.assert_called_once()

        assert info is not None
