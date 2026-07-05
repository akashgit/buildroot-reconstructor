"""Tests for canonical coordinate resolution in maven_central.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestResolveCanonicalCoordinate:
    @patch("buildroot.utils.maven_central.requests.get")
    def test_resolves_different_group_id(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": {
                "numFound": 1,
                "docs": [
                    {"g": "com.fasterxml.jackson.core", "a": "jackson-core", "v": "2.13.4"}
                ],
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from buildroot.utils.maven_central import resolve_canonical_coordinate

        result = resolve_canonical_coordinate("tools.jackson.core", "jackson-core", "2.13.4")
        assert result == ("com.fasterxml.jackson.core", "jackson-core")

    @patch("buildroot.utils.maven_central.requests.get")
    def test_returns_none_when_same_group(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": {
                "numFound": 1,
                "docs": [
                    {"g": "org.example", "a": "lib", "v": "1.0"}
                ],
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from buildroot.utils.maven_central import resolve_canonical_coordinate

        result = resolve_canonical_coordinate("org.example", "lib", "1.0")
        assert result is None

    @patch("buildroot.utils.maven_central.requests.get")
    def test_returns_none_when_no_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": {"numFound": 0, "docs": []}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from buildroot.utils.maven_central import resolve_canonical_coordinate

        result = resolve_canonical_coordinate("com.nonexistent", "fake-lib", "1.0")
        assert result is None

    @patch("buildroot.utils.maven_central.requests.get")
    def test_returns_none_on_network_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.ConnectionError("timeout")

        from buildroot.utils.maven_central import resolve_canonical_coordinate

        result = resolve_canonical_coordinate("org.example", "lib", "1.0")
        assert result is None

    @patch("buildroot.utils.maven_central.requests.get")
    @patch("buildroot.utils.maven_central.requests.head")
    def test_version_probe_fallback(self, mock_head, mock_get):
        """When exact version search returns nothing, search by artifactId only
        and probe whether the version exists under the candidate groupId."""
        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"response": {"numFound": 0, "docs": []}}
        empty_resp.raise_for_status = MagicMock()

        candidates_resp = MagicMock()
        candidates_resp.status_code = 200
        candidates_resp.json.return_value = {
            "response": {
                "numFound": 1,
                "docs": [{"g": "org.glassfish.jaxb", "a": "jaxb-runtime", "v": "4.0.0"}],
            }
        }
        candidates_resp.raise_for_status = MagicMock()

        mock_get.side_effect = [empty_resp, candidates_resp]

        head_resp = MagicMock()
        head_resp.status_code = 200
        mock_head.return_value = head_resp

        from buildroot.utils.maven_central import resolve_canonical_coordinate

        result = resolve_canonical_coordinate("cn.lzgabel.jaxb", "jaxb-runtime", "4.0.5")
        assert result == ("org.glassfish.jaxb", "jaxb-runtime")


class TestGetJarPathResolution:
    @patch("buildroot.utils.maven_central.resolve_canonical_coordinate")
    @patch("buildroot.utils.maven_central.requests.get")
    def test_404_triggers_resolution(self, mock_get, mock_resolve):
        """On 404, get_jar_path should try coordinate resolution."""
        import requests as req
        from pathlib import Path
        import tempfile

        resp_404 = MagicMock()
        resp_404.status_code = 404
        resp_404.raise_for_status.side_effect = req.HTTPError(response=resp_404)
        resp_404.__enter__ = lambda s: s
        resp_404.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = resp_404

        mock_resolve.return_value = None

        from buildroot.utils.maven_central import get_jar_path

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(req.HTTPError):
                get_jar_path("fake.group", "fake-lib", "1.0", cache_dir=Path(tmpdir))

        mock_resolve.assert_called_once_with("fake.group", "fake-lib", "1.0")

    @patch("buildroot.utils.maven_central.resolve_canonical_coordinate")
    @patch("buildroot.utils.maven_central.requests.get")
    def test_non_404_does_not_trigger_resolution(self, mock_get, mock_resolve):
        """On non-404 errors (e.g. 500), resolution should NOT be attempted."""
        import requests as req
        from pathlib import Path
        import tempfile

        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.raise_for_status.side_effect = req.HTTPError(response=resp_500)
        resp_500.__enter__ = lambda s: s
        resp_500.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = resp_500

        from buildroot.utils.maven_central import get_jar_path

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(req.HTTPError):
                get_jar_path("fake.group", "fake-lib", "1.0", cache_dir=Path(tmpdir))

        mock_resolve.assert_not_called()
