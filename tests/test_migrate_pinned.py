"""Tests for the migrate_pinned CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from buildroot.cli.commands.migrate_pinned import (
    _add_checksum_verification,
    _extract_maven_version_from_cf,
    _pin_from_line,
    _query_candidates,
    _remove_maven,
    _replace_apt_maven,
)


class TestExtractMavenVersionFromCF:
    def test_extracts_version(self):
        cf = "RUN wget apache-maven-3.8.6-bin.tar.gz"
        assert _extract_maven_version_from_cf(cf) == "3.8.6"

    def test_no_version(self):
        cf = "RUN apt-get install maven"
        assert _extract_maven_version_from_cf(cf) is None

    def test_extracts_from_path(self):
        cf = "RUN tar xzf /tmp/apache-maven-3.9.6-bin.tar.gz -C /opt"
        assert _extract_maven_version_from_cf(cf) == "3.9.6"


class TestPinFromLine:
    def test_already_pinned(self):
        registry = MagicMock()
        line = "FROM eclipse-temurin:17-jdk@sha256:abc123"
        result, changed = _pin_from_line(line, registry)
        assert result == line
        assert changed is False
        registry.resolve_image_digest.assert_not_called()

    def test_pins_floating_tag(self):
        registry = MagicMock()
        registry.resolve_image_digest.return_value = "sha256:deadbeef1234"
        line = "FROM eclipse-temurin:17-jdk"
        result, changed = _pin_from_line(line, registry)
        assert changed is True
        assert "@sha256:deadbeef1234" in result
        assert result == "FROM eclipse-temurin:17-jdk@sha256:deadbeef1234"

    def test_no_digest_available(self):
        registry = MagicMock()
        registry.resolve_image_digest.return_value = None
        line = "FROM eclipse-temurin:17-jdk"
        result, changed = _pin_from_line(line, registry)
        assert changed is False
        assert result == line

    def test_non_from_line(self):
        registry = MagicMock()
        line = "RUN apt-get update"
        result, changed = _pin_from_line(line, registry)
        assert changed is False
        assert result == line

    def test_from_with_as_suffix(self):
        registry = MagicMock()
        registry.resolve_image_digest.return_value = "sha256:abc123"
        line = "FROM eclipse-temurin:17-jdk AS builder"
        result, changed = _pin_from_line(line, registry)
        assert changed is True
        assert result == "FROM eclipse-temurin:17-jdk@sha256:abc123 AS builder"


class TestRemoveMaven:
    def test_removes_maven(self):
        line = "    apt-get install -y maven && \\"
        result = _remove_maven(line)
        assert "maven" not in result
        assert result == "    apt-get install -y && \\"

    def test_preserves_other_packages(self):
        line = "RUN apt-get install -y maven git"
        result = _remove_maven(line)
        assert "maven" not in result
        assert "git" in result

    def test_preserves_curl(self):
        line = "RUN apt-get install -y maven git curl unzip"
        result = _remove_maven(line)
        assert "maven" not in result
        assert "curl" in result
        assert "git" in result
        assert "unzip" in result

    def test_preserves_flags(self):
        line = "RUN apt-get install -y -qq --no-install-recommends maven git"
        result = _remove_maven(line)
        assert "-y" in result
        assert "-qq" in result
        assert "--no-install-recommends" in result
        assert "maven" not in result

    def test_preserves_redirection_suffix(self):
        line = "RUN apt-get install -y -qq maven git > /dev/null 2>&1"
        result = _remove_maven(line)
        assert "maven" not in result
        assert "> /dev/null 2>&1" in result
        assert "git" in result

    def test_no_apt_install_returns_unchanged(self):
        line = "RUN apt-get update && \\"
        result = _remove_maven(line)
        assert result == line


class TestReplaceAptMaven:
    def test_replaces_apt_maven_with_curl_tarball(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "FROM eclipse-temurin:17-jdk\nRUN apt-get install -y maven\nRUN mvn clean install"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        assert skip is None
        assert "maven" not in new_cf.split("maven-central.storage.googleapis.com")[0]
        assert "sha256sum -c" in new_cf
        assert "curl" in new_cf
        assert "maven-central.storage.googleapis.com" in new_cf
        assert "FROM eclipse-temurin:17-jdk" in new_cf
        assert "RUN mvn clean install" in new_cf
        registry.get_maven_checksum.assert_called()

    def test_preserves_other_packages(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "RUN apt-get update -qq && apt-get install -y -qq maven git > /dev/null 2>&1"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        assert "git" in new_cf
        assert "> /dev/null 2>&1" in new_cf
        assert "sha256sum -c" in new_cf
        assert "curl" in new_cf
        apt_line = new_cf.split("\n")[0]
        assert "maven" not in apt_line

    def test_preserves_existing_packages(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "RUN apt-get update -qq && apt-get install -y -qq maven git curl unzip > /dev/null 2>&1"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        apt_line = new_cf.split("\n")[0]
        assert "curl" in apt_line
        assert "git" in apt_line
        assert "unzip" in apt_line
        assert "maven" not in apt_line

    def test_replaces_with_no_install_recommends(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "RUN apt-get install -y --no-install-recommends maven"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        assert "apt-get install" in new_cf
        assert "--no-install-recommends" in new_cf
        assert "curl" in new_cf
        assert "sha256sum -c" in new_cf

    def test_no_apt_maven(self):
        registry = MagicMock()
        cf = "RUN mvn clean install"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is False
        assert skip is None
        assert new_cf == cf

    def test_no_checksum_available(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = None
        cf = "RUN apt-get install -y maven"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is False
        assert skip is not None
        assert "no checksum" in skip

    def test_uses_existing_version_from_cf(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "checksum_for_386"
        cf = "RUN wget apache-maven-3.8.6-bin.tar.gz\nRUN apt-get install -y maven"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        registry.get_maven_checksum.assert_called_with("3.8.6")

    def test_replaces_with_reversed_flag_order(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "RUN apt-get install --no-install-recommends -y maven"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        assert "apt-get install" in new_cf
        assert "curl" in new_cf
        assert "sha256sum -c" in new_cf

    def test_preserves_multiline_run_block(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN apt-get update && \\\n"
            "    apt-get install -y maven && \\\n"
            "    rm -rf /var/lib/apt/lists/*\n"
            "RUN mvn clean install"
        )
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        assert skip is None
        assert "apt-get update" in new_cf
        assert "apt-get install" in new_cf
        assert "rm -rf /var/lib/apt/lists/*" in new_cf
        assert "curl" in new_cf
        assert "sha256sum -c" in new_cf
        assert "maven-central.storage.googleapis.com" in new_cf
        assert "FROM eclipse-temurin:17-jdk" in new_cf
        assert "RUN mvn clean install" in new_cf
        install_line = [l for l in new_cf.split("\n") if "apt-get install" in l][0]
        assert "maven" not in install_line

    def test_preserves_cleanup_in_chained_command(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "RUN apt-get update && apt-get install -y git maven && rm -rf /var/lib/apt/lists/*"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        apt_line = new_cf.split("\n")[0]
        assert "apt-get update" in apt_line
        assert "git" in apt_line
        assert "rm -rf /var/lib/apt/lists/*" in apt_line
        assert "maven" not in apt_line


class TestAddChecksumVerification:
    def test_adds_checksum_to_tarball(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123"
        cf = "RUN wget apache-maven-3.9.6-bin.tar.gz && \\\n    tar xzf apache-maven-3.9.6-bin.tar.gz"
        new_cf, changed = _add_checksum_verification(cf, registry)
        assert changed is True
        assert "sha256sum -c" in new_cf

    def test_skips_if_already_has_checksum(self):
        registry = MagicMock()
        cf = 'RUN echo "abc  file" | sha256sum -c - && tar xzf apache-maven-3.9.6-bin.tar.gz'
        new_cf, changed = _add_checksum_verification(cf, registry)
        assert changed is False
        assert new_cf == cf

    def test_skips_no_maven_tarball(self):
        registry = MagicMock()
        cf = "RUN apt-get install -y curl"
        new_cf, changed = _add_checksum_verification(cf, registry)
        assert changed is False

    def test_skips_no_checksum_for_version(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = None
        cf = "RUN tar xzf apache-maven-99.99.99-bin.tar.gz"
        new_cf, changed = _add_checksum_verification(cf, registry)
        assert changed is False


class TestQueryCandidates:
    def test_excludes_l4_without_eval_result(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__ = lambda self: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        _query_candidates(mock_conn)

        sql = mock_cursor.execute.call_args[0][0]
        assert "level < 4 OR eval_result IS NOT NULL" in sql
