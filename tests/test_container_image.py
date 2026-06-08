"""Tests for container image resolution and Dockerfile parsing."""

from __future__ import annotations

from buildroot.resolvers.container_image import ContainerImageResolver

SIMPLE_DOCKERFILE = """\
FROM eclipse-temurin:17-jdk
RUN apt-get update && apt-get install -y git curl
COPY . /app
WORKDIR /app
RUN mvn package
"""

DOCKERFILE_WITH_ENV = """\
FROM ubuntu:22.04
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV MAVEN_HOME=/opt/maven
ENV PATH=$JAVA_HOME/bin:$MAVEN_HOME/bin:$PATH
RUN apt-get update && apt-get install -y openjdk-17-jdk maven git
COPY . /app
"""

MULTISTAGE_DOCKERFILE = """\
FROM eclipse-temurin:17-jdk AS builder
RUN apt-get update && apt-get install -y git
COPY . /app
WORKDIR /app
RUN mvn package -DskipTests

FROM eclipse-temurin:17-jre
COPY --from=builder /app/target/*.jar /app/app.jar
EXPOSE 8080
CMD ["java", "-jar", "/app/app.jar"]
"""

DOCKERFILE_WITH_YUM = """\
FROM centos:7
RUN yum install -y java-17-openjdk-devel wget unzip
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk
"""

MINIMAL_DOCKERFILE = """\
FROM alpine:3.18
"""


class TestParseDockerfileExtractsFrom:
    def test_simple_from(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(SIMPLE_DOCKERFILE)
        assert result["base_image"] == "eclipse-temurin:17-jdk"

    def test_minimal_from(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(MINIMAL_DOCKERFILE)
        assert result["base_image"] == "alpine:3.18"


class TestParseDockerfileExtractsPackages:
    def test_apt_get_packages(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(SIMPLE_DOCKERFILE)
        assert "git" in result["installed_packages"]
        assert "curl" in result["installed_packages"]

    def test_yum_packages(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(DOCKERFILE_WITH_YUM)
        assert "java-17-openjdk-devel" in result["installed_packages"]
        assert "wget" in result["installed_packages"]
        assert "unzip" in result["installed_packages"]

    def test_env_dockerfile_packages(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(DOCKERFILE_WITH_ENV)
        assert "openjdk-17-jdk" in result["installed_packages"]
        assert "maven" in result["installed_packages"]
        assert "git" in result["installed_packages"]


class TestParseDockerfileExtractsEnv:
    def test_java_home(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(DOCKERFILE_WITH_ENV)
        assert result["java_home"] == "/usr/lib/jvm/java-17-openjdk-amd64"

    def test_other_env_vars(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(DOCKERFILE_WITH_ENV)
        assert result["env_vars"]["MAVEN_HOME"] == "/opt/maven"

    def test_no_java_home(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(SIMPLE_DOCKERFILE)
        assert result["java_home"] == ""

    def test_yum_java_home(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(DOCKERFILE_WITH_YUM)
        assert result["java_home"] == "/usr/lib/jvm/java-17-openjdk"


class TestParseMultistageDockerfile:
    def test_takes_last_from(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(MULTISTAGE_DOCKERFILE)
        assert result["base_image"] == "eclipse-temurin:17-jre"

    def test_extracts_packages_from_all_stages(self):
        resolver = ContainerImageResolver()
        result = resolver.parse_dockerfile(MULTISTAGE_DOCKERFILE)
        assert "git" in result["installed_packages"]
