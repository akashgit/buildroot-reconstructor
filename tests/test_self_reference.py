"""Tests for self-built reference JAR production."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from buildroot.eval.self_reference import (
    _normalize_scm_url,
    _parse_scm_from_pom,
    build_reference_jar,
    discover_source_repo,
    resolve_tag,
)


class TestNormalizeScmUrl:
    def test_github_https(self):
        assert _normalize_scm_url("https://github.com/apache/commons-lang") == ("apache", "commons-lang")

    def test_scm_git_prefix(self):
        assert _normalize_scm_url("scm:git:https://github.com/spring-projects/spring-boot.git") == ("spring-projects", "spring-boot")

    def test_ssh_url(self):
        assert _normalize_scm_url("scm:git:ssh://git@github.com/spring-projects/spring-boot.git") == ("spring-projects", "spring-boot")

    def test_gitbox_apache(self):
        assert _normalize_scm_url("https://gitbox.apache.org/repos/asf?p=commons-lang.git") == ("apache", "commons-lang")

    def test_non_github_returns_none(self):
        assert _normalize_scm_url("https://example.com/some/repo") is None


class TestDiscoverSourceRepoFromScmUrl:
    def test_pom_with_scm_url(self):
        pom_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>org.apache.commons</groupId>
  <artifactId>commons-lang3</artifactId>
  <version>3.14.0</version>
  <scm>
    <url>https://github.com/apache/commons-lang</url>
    <connection>scm:git:https://github.com/apache/commons-lang.git</connection>
  </scm>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom = Path(tmpdir) / "pom.xml"
            pom.write_text(pom_content)
            result = discover_source_repo("org.apache.commons", "commons-lang3", "3.14.0", pom)
        assert result == ("apache", "commons-lang")

    def test_scm_normalization_ssh_and_gitbox(self):
        pom_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <scm>
    <connection>scm:git:ssh://git@github.com/thymeleaf/thymeleaf.git</connection>
  </scm>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom = Path(tmpdir) / "pom.xml"
            pom.write_text(pom_content)
            result = discover_source_repo("org.thymeleaf", "thymeleaf", "3.0.15", pom)
        assert result == ("thymeleaf", "thymeleaf")

    def test_no_scm_returns_none_when_all_fallbacks_fail(self):
        pom_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <groupId>com.example</groupId>
  <artifactId>no-scm</artifactId>
</project>"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pom = Path(tmpdir) / "pom.xml"
            pom.write_text(pom_content)
            with patch("buildroot.eval.self_reference._query_deps_dev", return_value=None), \
                 patch("buildroot.eval.self_reference._search_github", return_value=None):
                result = discover_source_repo("com.example", "no-scm", "1.0", pom)
        assert result is None


class TestResolveTag:
    @patch("buildroot.eval.self_reference.subprocess.run")
    def test_v_prefix(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="v2.7.18\nv2.7.17\nv2.7.16\n",
        )
        tag = resolve_tag("spring-projects", "spring-boot", "spring-boot", "2.7.18")
        assert tag == "v2.7.18"

    @patch("buildroot.eval.self_reference.subprocess.run")
    def test_apache_pattern(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="rel/commons-lang-3.14.0\nrel/commons-lang-3.13.0\nrel/commons-lang-3.12.0\n",
        )
        tag = resolve_tag("apache", "commons-lang", "commons-lang", "3.14.0")
        assert tag == "rel/commons-lang-3.14.0"

    @patch("buildroot.eval.self_reference.subprocess.run")
    def test_no_match_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="release-1.0\nrelease-2.0\n",
        )
        tag = resolve_tag("example", "lib", "lib", "99.99.99")
        assert tag is None

    @patch("buildroot.eval.self_reference.subprocess.run")
    def test_fuzzy_substring_fallback(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="commons-lang-3.14.0\ncommons-lang-3.13.0\n",
        )
        tag = resolve_tag("apache", "commons-lang", "commons-lang", "3.14.0")
        assert tag == "commons-lang-3.14.0"

    @patch("buildroot.eval.self_reference.subprocess.run")
    def test_prefers_shorter_tag(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="release/module-1.0.0\nv1.0.0\nlong-prefix-v1.0.0-rc1\n",
        )
        tag = resolve_tag("org", "module", "module", "1.0.0")
        assert tag == "v1.0.0"


class TestBuildReferenceJar:
    @patch("buildroot.eval.self_reference.build_from_source")
    @patch("buildroot.eval.self_reference.resolve_tag")
    @patch("buildroot.eval.self_reference.discover_source_repo")
    def test_success(self, mock_discover, mock_tag, mock_build):
        mock_discover.return_value = ("apache", "commons-lang")
        mock_tag.return_value = "rel/commons-lang-3.14.0"
        fake_jar = Path("/tmp/fake.jar")
        mock_build.return_value = fake_jar

        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_reference_jar(
                "org.apache.commons", "commons-lang3", "3.14.0", "17", Path(tmpdir),
            )
        assert result == fake_jar

    @patch("buildroot.eval.self_reference.build_from_source")
    @patch("buildroot.eval.self_reference.resolve_tag")
    @patch("buildroot.eval.self_reference.discover_source_repo")
    def test_build_failure_returns_none(self, mock_discover, mock_tag, mock_build):
        mock_discover.return_value = ("apache", "commons-lang")
        mock_tag.return_value = "rel/commons-lang-3.14.0"
        mock_build.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_reference_jar(
                "org.apache.commons", "commons-lang3", "3.14.0", "17", Path(tmpdir),
            )
        assert result is None

    @patch("buildroot.eval.self_reference.discover_source_repo")
    def test_no_source_returns_none(self, mock_discover):
        mock_discover.return_value = None
        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_reference_jar(
                "com.unknown", "mystery", "1.0", "17", Path(tmpdir),
            )
        assert result is None
