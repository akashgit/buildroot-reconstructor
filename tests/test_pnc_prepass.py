"""Unit tests for PNC integration in the prepass module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from buildroot.agent.prepass import PrePassFinding, PrePassFindings, run_prepass
from buildroot.utils.pnc_api import PncBuildInfo

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pnc"


def _make_pnc_info(**kwargs) -> PncBuildInfo:
    defaults = {
        "build_id": "12345",
        "builder_image": "quay.io/rh-newcastle/builder-rhel-7-j8-mvn3.6.3@sha256:abc",
        "jdk_version": "8",
        "maven_version": "3.6.3",
        "rhel_version": "7",
        "scm_external_url": "https://github.com/apache/commons-lang.git",
        "scm_revision": "rel/commons-lang-3.12.0",
        "scm_url": "git+ssh://code.engineering.redhat.com/commons-lang.git",
        "scm_tag": "commons-lang-3.12.0.redhat-00001",
        "environment_id": "200",
        "raw_response": {},
    }
    defaults.update(kwargs)
    return PncBuildInfo(**defaults)


@patch("buildroot.agent.prepass._discover_repo_from_parent_chain", return_value=None)
@patch("buildroot.agent.prepass.get_jar_path")
@patch("buildroot.agent.prepass.fetch_pom")
@patch("buildroot.agent.prepass.discover_repo_from_pom", return_value=None)
def test_prepass_pnc_enabled_sha256_hit(mock_repo, mock_pom, mock_jar, mock_parent, tmp_path):
    mock_pom.return_value = "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"

    jar_path = tmp_path / "test.jar"
    import zipfile
    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    mock_jar.return_value = jar_path

    pnc_info = _make_pnc_info()

    with patch("buildroot.utils.pnc_api.PncClient") as MockClient:
        instance = MockClient.return_value
        instance.query_by_sha256.return_value = pnc_info
        instance.query_by_gav.return_value = None

        findings = run_prepass("g:a:1.0", tmp_path / "ws", enable_pnc=True)

    assert findings.pnc_build_id == "12345"
    assert findings.pnc_builder_image is not None
    assert findings.pnc_builder_image.source == "pnc_api"
    assert findings.pnc_builder_image.confidence == "high"
    assert findings.jdk_version is not None
    assert findings.jdk_version.value == "8"
    assert findings.jdk_version.source == "pnc_api"


@patch("buildroot.agent.prepass._discover_repo_from_parent_chain", return_value=None)
@patch("buildroot.agent.prepass.get_jar_path")
@patch("buildroot.agent.prepass.fetch_pom")
@patch("buildroot.agent.prepass.discover_repo_from_pom", return_value=None)
def test_prepass_pnc_enabled_sha256_miss_gav_hit(mock_repo, mock_pom, mock_jar, mock_parent, tmp_path):
    mock_pom.return_value = "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"

    jar_path = tmp_path / "test.jar"
    import zipfile
    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    mock_jar.return_value = jar_path

    pnc_info = _make_pnc_info(build_id="99999")

    with patch("buildroot.utils.pnc_api.PncClient") as MockClient:
        instance = MockClient.return_value
        instance.query_by_sha256.return_value = None
        instance.query_by_gav.return_value = pnc_info

        findings = run_prepass("g:a:1.0", tmp_path / "ws", enable_pnc=True)

    assert findings.pnc_build_id == "99999"


@patch("buildroot.agent.prepass._discover_repo_from_parent_chain", return_value=None)
@patch("buildroot.agent.prepass.get_jar_path")
@patch("buildroot.agent.prepass.fetch_pom")
@patch("buildroot.agent.prepass.discover_repo_from_pom", return_value=None)
def test_prepass_pnc_disabled_no_lookup(mock_repo, mock_pom, mock_jar, mock_parent, tmp_path):
    mock_pom.return_value = "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"

    jar_path = tmp_path / "test.jar"
    import zipfile
    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nBuild-Jdk-Spec: 11\n")
    mock_jar.return_value = jar_path

    with patch("buildroot.utils.pnc_api.PncClient") as MockClient:
        findings = run_prepass("g:a:1.0", tmp_path / "ws", enable_pnc=False)
        MockClient.assert_not_called()

    assert findings.pnc_build_id is None
    assert findings.pnc_builder_image is None


@patch("buildroot.agent.prepass._discover_repo_from_parent_chain", return_value=None)
@patch("buildroot.agent.prepass.get_jar_path")
@patch("buildroot.agent.prepass.fetch_pom")
@patch("buildroot.agent.prepass.discover_repo_from_pom", return_value=None)
def test_prepass_pnc_overrides_jdk_version(mock_repo, mock_pom, mock_jar, mock_parent, tmp_path):
    mock_pom.return_value = "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"

    jar_path = tmp_path / "test.jar"
    import zipfile
    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nBuild-Jdk-Spec: 11\n")
    mock_jar.return_value = jar_path

    pnc_info = _make_pnc_info(jdk_version="8")

    with patch("buildroot.utils.pnc_api.PncClient") as MockClient:
        instance = MockClient.return_value
        instance.query_by_sha256.return_value = pnc_info

        findings = run_prepass("g:a:1.0", tmp_path / "ws", enable_pnc=True)

    assert findings.jdk_version.value == "8"
    assert findings.jdk_version.source == "pnc_api"


@patch("buildroot.agent.prepass._discover_repo_from_parent_chain", return_value=None)
@patch("buildroot.agent.prepass.get_jar_path")
@patch("buildroot.agent.prepass.fetch_pom")
@patch("buildroot.agent.prepass.discover_repo_from_pom", return_value=None)
def test_prepass_pnc_overrides_maven_version(mock_repo, mock_pom, mock_jar, mock_parent, tmp_path):
    mock_pom.return_value = "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"

    jar_path = tmp_path / "test.jar"
    import zipfile
    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    mock_jar.return_value = jar_path

    pnc_info = _make_pnc_info(maven_version="3.6.3")

    with patch("buildroot.utils.pnc_api.PncClient") as MockClient:
        instance = MockClient.return_value
        instance.query_by_sha256.return_value = pnc_info

        findings = run_prepass("g:a:1.0", tmp_path / "ws", enable_pnc=True)

    assert findings.maven_version is not None
    assert findings.maven_version.value == "3.6.3"
    assert findings.maven_version.source == "pnc_api"


@patch("buildroot.agent.prepass._discover_repo_from_parent_chain", return_value=None)
@patch("buildroot.agent.prepass.get_jar_path")
@patch("buildroot.agent.prepass.fetch_pom")
@patch("buildroot.agent.prepass.discover_repo_from_pom", return_value=None)
def test_prepass_pnc_connection_failure_graceful(mock_repo, mock_pom, mock_jar, mock_parent, tmp_path):
    mock_pom.return_value = "<project><groupId>g</groupId><artifactId>a</artifactId><version>1.0</version></project>"

    jar_path = tmp_path / "test.jar"
    import zipfile
    with zipfile.ZipFile(jar_path, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nBuild-Jdk-Spec: 11\n")
    mock_jar.return_value = jar_path

    import requests as req

    with patch("buildroot.utils.pnc_api.PncClient") as MockClient:
        instance = MockClient.return_value
        instance.query_by_sha256.side_effect = req.ConnectionError("no VPN")

        findings = run_prepass("g:a:1.0", tmp_path / "ws", enable_pnc=True)

    assert findings.pnc_build_id is None
    assert any("PNC lookup" in f for f in findings.attempted_but_failed)
    assert findings.jdk_version is not None
    assert findings.jdk_version.value == "11"
