"""Tests for PNC Containerfile parser with synthetic fixtures."""

from __future__ import annotations

from pathlib import Path

from buildroot.parsers.pnc_containerfile import (
    parse_pnc_containerfile_chain,
    _extract_jdk_from_rpms,
    _extract_build_tool_from_env,
    _extract_build_tool_from_urls,
    _extract_rhel_version,
    _infer_from_image_name,
)

FIXTURE_BASE_RHEL7 = """\
FROM registry.access.redhat.com/rhel7/rhel:7.9

RUN yum install -y \\
    java-1.8.0-openjdk-devel \\
    git \\
    && yum clean all

ENV JAVA_HOME=/usr/lib/jvm/java-1.8.0-openjdk
"""

FIXTURE_TOOL_J8_MVN339 = """\
FROM builder-rhel-7-base-j8

ENV MAVEN_VERSION=3.3.9
ENV MAVEN_HOME=/opt/maven

RUN curl -fsSL https://archive.apache.org/dist/maven/maven-3/3.3.9/binaries/apache-maven-3.3.9-bin.tar.gz \\
    | tar xz -C /opt && \\
    ln -s /opt/apache-maven-3.3.9 /opt/maven && \\
    ln -s /opt/maven/bin/mvn /usr/bin/mvn

WORKDIR /build
"""

FIXTURE_BASE_RHEL7_J11 = """\
FROM registry.access.redhat.com/ubi7/ubi:7.9

RUN yum install -y \\
    java-11-openjdk-devel \\
    git \\
    && yum clean all

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk
"""

FIXTURE_TOOL_J11_MVN363 = """\
FROM builder-rhel-7-base-j11

ENV MAVEN_VERSION=3.6.3
ENV MAVEN_HOME=/opt/maven

RUN curl -fsSL https://archive.apache.org/dist/maven/maven-3/3.6.3/binaries/apache-maven-3.6.3-bin.tar.gz \\
    | tar xz -C /opt && \\
    ln -s /opt/apache-maven-3.6.3 /opt/maven && \\
    ln -s /opt/maven/bin/mvn /usr/bin/mvn

WORKDIR /build
"""


def _setup_fixtures(tmp_path: Path) -> Path:
    """Create synthetic PNC builders-image directory structure."""
    builders = tmp_path / "builders-image"

    base_j8 = builders / "builder-rhel-7-base-j8"
    base_j8.mkdir(parents=True)
    (base_j8 / "Containerfile").write_text(FIXTURE_BASE_RHEL7)

    tool_j8 = builders / "builder-rhel-7-j8-mvn3.3.9"
    tool_j8.mkdir(parents=True)
    (tool_j8 / "Containerfile").write_text(FIXTURE_TOOL_J8_MVN339)

    base_j11 = builders / "builder-rhel-7-base-j11"
    base_j11.mkdir(parents=True)
    (base_j11 / "Containerfile").write_text(FIXTURE_BASE_RHEL7_J11)

    tool_j11 = builders / "builder-rhel-7-j11-mvn3.6.3"
    tool_j11.mkdir(parents=True)
    (tool_j11 / "Containerfile").write_text(FIXTURE_TOOL_J11_MVN363)

    return builders


class TestJdkExtraction:
    def test_jdk8_from_rpm(self):
        major, vendor = _extract_jdk_from_rpms("java-1.8.0-openjdk-devel")
        assert major == "8"
        assert vendor == "openjdk"

    def test_jdk11_from_rpm(self):
        major, vendor = _extract_jdk_from_rpms("java-11-openjdk-devel")
        assert major == "11"
        assert vendor == "openjdk"

    def test_jdk17_from_rpm(self):
        major, vendor = _extract_jdk_from_rpms("java-17-openjdk-devel")
        assert major == "17"
        assert vendor == "openjdk"

    def test_no_jdk_in_content(self):
        major, vendor = _extract_jdk_from_rpms("RUN yum install -y git curl")
        assert major == ""
        assert vendor == ""


class TestBuildToolExtraction:
    def test_maven_from_env(self):
        tool, version = _extract_build_tool_from_env({"MAVEN_VERSION": "3.3.9"})
        assert tool == "maven"
        assert version == "3.3.9"

    def test_gradle_from_env(self):
        tool, version = _extract_build_tool_from_env({"GRADLE_VERSION": "7.6"})
        assert tool == "gradle"
        assert version == "7.6"

    def test_maven_from_url(self):
        tool, version = _extract_build_tool_from_urls(
            "curl https://archive.apache.org/dist/maven/apache-maven-3.6.3-bin.tar.gz"
        )
        assert tool == "maven"
        assert version == "3.6.3"

    def test_gradle_from_url(self):
        tool, version = _extract_build_tool_from_urls(
            "curl https://services.gradle.org/distributions/gradle-7.6-bin.zip"
        )
        assert tool == "gradle"
        assert version == "7.6"

    def test_no_build_tool(self):
        tool, version = _extract_build_tool_from_env({})
        assert tool == ""
        assert version == ""


class TestRhelExtraction:
    def test_rhel7_from_image(self):
        family, ver = _extract_rhel_version(["registry.access.redhat.com/rhel7/rhel:7.9"])
        assert family == "rhel"
        assert ver == "7"

    def test_ubi8_from_image(self):
        family, ver = _extract_rhel_version(["registry.access.redhat.com/ubi8/ubi:8.6"])
        assert family == "rhel"
        assert ver == "8"

    def test_no_rhel(self):
        family, ver = _extract_rhel_version(["ubuntu:22.04"])
        assert family == ""
        assert ver == ""


class TestImageNameFallback:
    def test_j8_from_name(self):
        major, vendor = _infer_from_image_name("builder-rhel-7-j8-mvn3.3.9")
        assert major == "8"
        assert vendor == "openjdk"

    def test_j11_from_name(self):
        major, vendor = _infer_from_image_name("builder-rhel-7-j11-mvn3.6.3")
        assert major == "11"

    def test_no_match(self):
        major, vendor = _infer_from_image_name("some-random-image")
        assert major == ""


class TestPNCContainerfileChain:
    def test_j8_mvn339_chain(self, tmp_path: Path):
        builders = _setup_fixtures(tmp_path)
        truth = parse_pnc_containerfile_chain(builders, "builder-rhel-7-j8-mvn3.3.9")

        assert truth.jdk_major_version == "8"
        assert truth.jdk_vendor == "openjdk"
        assert truth.build_tool == "maven"
        assert truth.build_tool_version == "3.3.9"
        assert truth.os_family == "rhel"
        assert truth.os_version == "7"
        assert truth.image_name == "builder-rhel-7-j8-mvn3.3.9"

    def test_j11_mvn363_chain(self, tmp_path: Path):
        builders = _setup_fixtures(tmp_path)
        truth = parse_pnc_containerfile_chain(builders, "builder-rhel-7-j11-mvn3.6.3")

        assert truth.jdk_major_version == "11"
        assert truth.jdk_vendor == "openjdk"
        assert truth.build_tool == "maven"
        assert truth.build_tool_version == "3.6.3"
        assert truth.os_family == "rhel"
        assert truth.os_version == "7"
        assert truth.image_name == "builder-rhel-7-j11-mvn3.6.3"

    def test_missing_image_dir(self, tmp_path: Path):
        truth = parse_pnc_containerfile_chain(tmp_path, "nonexistent-image")
        assert truth.image_name == "nonexistent-image"
        assert truth.jdk_major_version == ""

    def test_env_vars_collected(self, tmp_path: Path):
        builders = _setup_fixtures(tmp_path)
        truth = parse_pnc_containerfile_chain(builders, "builder-rhel-7-j8-mvn3.3.9")
        assert "MAVEN_VERSION" in truth.raw_env
        assert truth.raw_env["MAVEN_VERSION"] == "3.3.9"
