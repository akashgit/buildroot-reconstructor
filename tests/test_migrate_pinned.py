"""Tests for the migrate_pinned CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from buildroot.cli.commands.migrate_pinned import (
    _add_checksum_verification,
    _extract_maven_version_from_cf,
    _pin_from_line,
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


class TestReplaceAptMaven:
    def test_replaces_apt_install_maven(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "FROM eclipse-temurin:17-jdk\nRUN apt-get install -y maven\nRUN mvn clean install"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
        assert skip is None
        assert "apt-get install" not in new_cf
        assert "sha256sum -c" in new_cf
        assert "archive.apache.org" in new_cf
        registry.get_maven_checksum.assert_called()

    def test_replaces_with_no_install_recommends(self):
        registry = MagicMock()
        registry.get_maven_checksum.return_value = "abc123checksum"
        cf = "RUN apt-get install -y --no-install-recommends maven"
        new_cf, changed, skip = _replace_apt_maven(cf, registry)
        assert changed is True
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
