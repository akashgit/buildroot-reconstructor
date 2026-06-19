"""Tests for Containerfile reverse-parse (warm-start)."""


from buildroot.agent.pipeline_v3 import reverse_parse_containerfile


class TestReverseParseContainerfile:
    def test_from_image_extracted(self):
        cf = "FROM eclipse-temurin:17-jdk\nRUN mvn clean install"
        values = reverse_parse_containerfile(cf)
        assert values["base_image"] == "eclipse-temurin:17-jdk"
        assert values["jdk_version"] == "17"
        assert values["jdk_distribution"] == "temurin"

    def test_minor_jdk_version(self):
        cf = "FROM eclipse-temurin:17.0.9-jdk\nRUN mvn clean install"
        values = reverse_parse_containerfile(cf)
        assert values["jdk_version"] == "17"
        assert values["jdk_minor_version"] == "17.0.9"

    def test_openjdk_distribution(self):
        cf = "FROM openjdk:11-jdk\nRUN mvn clean install"
        values = reverse_parse_containerfile(cf)
        assert values["jdk_distribution"] == "openjdk"
        assert values["jdk_version"] == "11"

    def test_corretto_distribution(self):
        cf = "FROM amazoncorretto:21-jdk\nRUN mvn clean install"
        values = reverse_parse_containerfile(cf)
        assert values["jdk_distribution"] == "corretto"

    def test_git_clone_extracted(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN git clone --depth 1 --branch 'v2.9.0' 'https://github.com/json-path/JsonPath.git' /build\n"
            "RUN mvn clean install"
        )
        values = reverse_parse_containerfile(cf)
        assert values["source_repo"] == "https://github.com/json-path/JsonPath.git"
        assert values["git_tag"] == "v2.9.0"

    def test_env_vars_extracted(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "ENV SOURCE_DATE_EPOCH=0\n"
            "ENV MAVEN_OPTS=-Xmx512m\n"
            "RUN mvn clean install"
        )
        values = reverse_parse_containerfile(cf)
        assert values["env_vars"]["SOURCE_DATE_EPOCH"] == "0"
        assert values["env_vars"]["MAVEN_OPTS"] == "-Xmx512m"

    def test_maven_version_extracted(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN wget https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz\n"
            "RUN mvn clean install"
        )
        values = reverse_parse_containerfile(cf)
        assert values["maven_version"] == "3.9.6"

    def test_build_command_maven(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN apt-get update && apt-get install -y maven\n"
            "RUN mvn clean install -B -DskipTests -Dgpg.skip=true"
        )
        values = reverse_parse_containerfile(cf)
        assert "mvn clean install" in values["build_command"]
        assert values["build_system"] == "maven"

    def test_build_command_gradle(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN ./gradlew build -x test"
        )
        values = reverse_parse_containerfile(cf)
        assert "./gradlew" in values["build_command"]
        assert values["build_system"] == "gradle"

    def test_build_command_ant(self):
        cf = "FROM eclipse-temurin:8-jdk\nRUN ant jar"
        values = reverse_parse_containerfile(cf)
        assert "ant jar" in values["build_command"]
        assert values["build_system"] == "ant"

    def test_maven_wrapper(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN ./mvnw clean install -B -DskipTests"
        )
        values = reverse_parse_containerfile(cf)
        assert values["use_maven_wrapper"] is True
        assert values["build_system"] == "maven"

    def test_module_path_from_pl_flag(self):
        cf = (
            "FROM eclipse-temurin:17-jdk\n"
            "RUN mvn clean install -pl submodule -am -B -DskipTests"
        )
        values = reverse_parse_containerfile(cf)
        assert values["module_path"] == "submodule"

    def test_empty_containerfile(self):
        values = reverse_parse_containerfile("")
        assert values["source_repo"] == ""
        assert values["build_command"] == ""
        assert values["jdk_version"] == ""

    def test_confidence_notes_set(self):
        values = reverse_parse_containerfile("FROM eclipse-temurin:17-jdk")
        assert "Reverse-parsed" in values["confidence_notes"]

    def test_defaults_present(self):
        values = reverse_parse_containerfile("FROM eclipse-temurin:17-jdk")
        assert values["system_packages"] == []
        assert values["pre_build_commands"] == []
        assert values["post_build_commands"] == []
        assert values["config_files"] == []
        assert isinstance(values["env_vars"], dict)

    def test_full_containerfile(self):
        cf = """# Buildroot Containerfile
FROM eclipse-temurin:17.0.9-jdk
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN wget -q https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz -O /tmp/maven.tar.gz
ENV MAVEN_HOME=/opt/apache-maven-3.9.6
ENV SOURCE_DATE_EPOCH=0
RUN git clone --depth 1 --branch 'json-path-2.9.0' 'https://github.com/json-path/JsonPath.git' /build
WORKDIR /build
RUN mvn clean install -B -DskipTests -Dgpg.skip=true -Dproject.build.outputTimestamp=2000-01-01T00:00:00Z
"""
        values = reverse_parse_containerfile(cf)
        assert values["jdk_version"] == "17"
        assert values["jdk_minor_version"] == "17.0.9"
        assert values["jdk_distribution"] == "temurin"
        assert values["source_repo"] == "https://github.com/json-path/JsonPath.git"
        assert values["git_tag"] == "json-path-2.9.0"
        assert values["maven_version"] == "3.9.6"
        assert values["env_vars"]["SOURCE_DATE_EPOCH"] == "0"
        assert values["build_system"] == "maven"
        assert "mvn clean install" in values["build_command"]
