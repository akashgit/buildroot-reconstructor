"""Tests for PNC build submission utilities."""

import pytest

from buildroot.utils.pnc_submit import parse_containerfile_for_pnc

AIRCOMPRESSOR_CONTAINERFILE = """\
FROM docker.io/library/eclipse-temurin:8-jdk
ENV SOURCE_DATE_EPOCH=0
ENV TZ=UTC
ENV LC_ALL=en_US.UTF-8
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends git maven && rm -rf /var/lib/apt/lists/*
RUN curl -sL "https://api.adoptium.net/v3/binary/latest/11/ga/linux/x64/jdk/hotspot/normal/eclipse?project=jdk" -o /tmp/jdk11.tar.gz && mkdir -p /opt/jdk-11 && tar xzf /tmp/jdk11.tar.gz -C /opt/jdk-11 --strip-components=1 && rm /tmp/jdk11.tar.gz
ENV JAVA_HOME=/opt/jdk-11
ENV PATH=/opt/jdk-11/bin:$PATH
RUN mkdir -p /root/.m2 && printf '<settings>...</settings>' > /root/.m2/settings.xml
RUN git clone --branch 0.21 https://github.com/airlift/aircompressor.git . && git checkout 0.21
RUN mvn install -B -V -DskipTests -Dair.check.skip-all -Dgpg.skip=true -Dgit.build.time="2021-08-31T10:57:21-0700"
RUN mkdir -p /output && cp target/aircompressor-0.21.jar /output/rebuilt.jar
"""

GRADLE_CONTAINERFILE = """\
FROM eclipse-temurin:17-jdk
RUN git clone --branch v2.0.0 https://github.com/example/project.git .
RUN ./gradlew build -x test
"""

NO_GIT_CONTAINERFILE = """\
FROM eclipse-temurin:17-jdk
RUN mvn install -B
"""


class TestParseContainerfileForPnc:
    def test_aircompressor(self):
        params = parse_containerfile_for_pnc(AIRCOMPRESSOR_CONTAINERFILE)
        assert params.git_url == "https://github.com/airlift/aircompressor.git"
        assert params.git_tag == "0.21"
        assert "deploy" in params.build_command
        assert "install" not in params.build_command
        assert params.build_type == "MVN"
        assert params.jdk_version == "11"

    def test_gradle(self):
        params = parse_containerfile_for_pnc(GRADLE_CONTAINERFILE)
        assert params.build_type == "GRADLE"
        assert params.jdk_version == "17"
        assert params.git_url == "https://github.com/example/project.git"
        assert params.git_tag == "v2.0.0"

    def test_no_git_clone_raises(self):
        with pytest.raises(ValueError, match="No git clone"):
            parse_containerfile_for_pnc(NO_GIT_CONTAINERFILE)
