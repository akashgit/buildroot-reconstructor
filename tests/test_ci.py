"""Tests for CI workflow parsing (GitHub Actions + CircleCI)."""

from __future__ import annotations

from buildroot.parsers.ci import CIParser
from buildroot.pipeline.models import Source

GITHUB_ACTIONS_SETUP_JAVA = """\
name: Build
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      - run: mvn -B verify
"""

GITHUB_ACTIONS_MATRIX = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        java-version: [11, 17, 21]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: ${{ matrix.java-version }}
          distribution: 'temurin'
      - run: mvn -B verify
"""

GITHUB_ACTIONS_APT_GET = """\
name: Build
on: [push]
jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get install -y libxml2-dev libxslt-dev
      - uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      - run: mvn -B verify
"""

GITHUB_ACTIONS_CONTAINER = """\
name: Build
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    container:
      image: maven:3.9-eclipse-temurin-17
    steps:
      - uses: actions/checkout@v4
      - run: mvn -B verify
"""

GITHUB_ACTIONS_GRADLE = """\
name: Build
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      - run: ./gradlew build
"""

GITHUB_ACTIONS_ENV_VARS = """\
name: Build
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      MAVEN_OPTS: "-Xmx512m"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
        env:
          JAVA_HOME_17_X64: /opt/hostedtoolcache/Java_Temurin-Hotspot_jdk/17
      - run: mvn -B verify
"""

CIRCLECI_DOCKER = """\
version: 2.1
orbs:
  maven: circleci/maven@1.4
jobs:
  build:
    docker:
      - image: cimg/openjdk:17.0
    environment:
      MAVEN_OPTS: "-Xmx256m"
    steps:
      - checkout
      - run:
          command: mvn -B verify
"""

GITHUB_ACTIONS_NESTED_MATRIX = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        java:
          - version: 17
            distribution: temurin
          - version: 21
            distribution: corretto
    steps:
      - uses: actions/setup-java@v4
        with:
          java-version: ${{ matrix.java.version }}
          distribution: ${{ matrix.java.distribution }}
"""


class TestParseGitHubActionsSetupJava:
    def test_extracts_java_version_and_distribution(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_SETUP_JAVA)
        assert ci.java_version is not None
        assert ci.java_version.value == "17"
        assert ci.java_version.source == Source.OBSERVED
        assert ci.distribution is not None
        assert ci.distribution.value == "temurin"
        assert ci.ci_type == "github"

    def test_extracts_runner_os(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_SETUP_JAVA)
        assert ci.runner_os == "ubuntu-latest"

    def test_extracts_build_command(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_SETUP_JAVA)
        assert any("mvn" in cmd for cmd in ci.build_commands)


class TestParseGitHubActionsMatrix:
    def test_resolves_matrix_java_version(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_MATRIX)
        assert ci.java_version is not None
        assert ci.java_version.value == "11"

    def test_nested_matrix_object(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_NESTED_MATRIX)
        assert ci.java_version is not None
        assert ci.java_version.value == "17"
        assert ci.distribution is not None
        assert ci.distribution.value == "temurin"


class TestParseGitHubActionsAptGet:
    def test_detects_apt_get_packages(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_APT_GET)
        assert "libxml2-dev" in ci.system_packages
        assert "libxslt-dev" in ci.system_packages

    def test_runner_os_pinned(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_APT_GET)
        assert ci.runner_os == "ubuntu-22.04"


class TestParseGitHubActionsContainer:
    def test_detects_container_image(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_CONTAINER)
        assert "maven:3.9-eclipse-temurin-17" in ci.container_images


class TestParseGitHubActionsGradle:
    def test_detects_gradlew(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_GRADLE)
        assert any("gradlew" in cmd or "gradle" in cmd for cmd in ci.build_commands)


class TestParseEnvVars:
    def test_extracts_job_and_step_env_vars(self):
        parser = CIParser()
        ci = parser.parse_github_actions(GITHUB_ACTIONS_ENV_VARS)
        assert "MAVEN_OPTS" in ci.env_vars
        assert ci.env_vars["MAVEN_OPTS"] == "-Xmx512m"
        assert "JAVA_HOME_17_X64" in ci.env_vars


class TestParseCircleCIDocker:
    def test_extracts_docker_image(self):
        parser = CIParser()
        ci = parser.parse_circleci(CIRCLECI_DOCKER)
        assert "cimg/openjdk:17.0" in ci.container_images
        assert ci.ci_type == "circleci"

    def test_extracts_environment_vars(self):
        parser = CIParser()
        ci = parser.parse_circleci(CIRCLECI_DOCKER)
        assert "MAVEN_OPTS" in ci.env_vars

    def test_extracts_build_commands(self):
        parser = CIParser()
        ci = parser.parse_circleci(CIRCLECI_DOCKER)
        assert any("mvn" in cmd for cmd in ci.build_commands)
