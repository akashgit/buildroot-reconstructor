"""Tests for Maven property placeholder resolution."""

from __future__ import annotations

import pytest

from buildroot.parsers.pom import PomParser
from buildroot.parsers.properties import PropertyResolver
from buildroot.pipeline.models import PomData, Source
from buildroot.utils.maven_central import fetch_pom


class TestSimpleResolution:
    def test_project_version(self):
        pom = PomData(
            group_id="com.example",
            artifact_id="my-app",
            version="1.0.0",
            properties={"my.ver": "${project.version}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["my.ver"] == "1.0.0"
        assert not gaps

    def test_project_group_id(self):
        pom = PomData(
            group_id="com.example",
            artifact_id="my-app",
            version="1.0.0",
            properties={"my.group": "${project.groupId}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["my.group"] == "com.example"

    def test_project_artifact_id(self):
        pom = PomData(
            group_id="com.example",
            artifact_id="my-app",
            version="1.0.0",
            properties={"my.aid": "${project.artifactId}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["my.aid"] == "my-app"

    def test_pom_prefix_aliases(self):
        pom = PomData(
            group_id="com.example",
            artifact_id="my-app",
            version="1.0.0",
            properties={"old.ref": "${pom.version}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["old.ref"] == "1.0.0"

    def test_plain_property(self):
        pom = PomData(
            properties={"base": "hello", "ref": "${base}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["ref"] == "hello"
        assert resolved["base"] == "hello"


class TestRecursiveResolution:
    def test_two_level(self):
        pom = PomData(
            properties={"a": "${b}", "b": "value"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["a"] == "value"
        assert not gaps

    def test_three_level(self):
        pom = PomData(
            properties={"a": "${b}", "b": "${c}", "c": "deep-value"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["a"] == "deep-value"

    def test_embedded_placeholder(self):
        pom = PomData(
            version="1.0.0",
            properties={"label": "ver-${project.version}-final"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert resolved["label"] == "ver-1.0.0-final"


class TestCycleDetection:
    def test_direct_cycle(self):
        pom = PomData(
            properties={"a": "${b}", "b": "${a}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        cycle_gaps = [g for g in gaps if "Cycle" in g.reason]
        assert len(cycle_gaps) > 0

    def test_longer_cycle(self):
        pom = PomData(
            properties={"a": "${b}", "b": "${c}", "c": "${a}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        cycle_gaps = [g for g in gaps if "Cycle" in g.reason]
        assert len(cycle_gaps) > 0


class TestCIFriendlyVersions:
    def test_revision(self):
        pom = PomData(
            properties={"my.version": "${revision}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert "${revision}" in resolved["my.version"]
        rev_gaps = [g for g in gaps if g.field == "revision"]
        assert len(rev_gaps) == 1
        assert rev_gaps[0].source == Source.DEFAULTED
        assert "CI-friendly" in rev_gaps[0].reason

    def test_sha1(self):
        pom = PomData(
            properties={"build.hash": "${sha1}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        sha_gaps = [g for g in gaps if g.field == "sha1"]
        assert len(sha_gaps) == 1

    def test_changelist(self):
        pom = PomData(
            properties={"suffix": "${changelist}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        cl_gaps = [g for g in gaps if g.field == "changelist"]
        assert len(cl_gaps) == 1


class TestEnvAndSettings:
    def test_env_property(self):
        pom = PomData(
            properties={"home": "${env.JAVA_HOME}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert "${env.JAVA_HOME}" in resolved["home"]
        env_gaps = [g for g in gaps if g.field == "env.JAVA_HOME"]
        assert len(env_gaps) == 1

    def test_settings_property(self):
        pom = PomData(
            properties={"repo": "${settings.localRepository}"},
        )
        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(pom)

        assert "${settings.localRepository}" in resolved["repo"]
        settings_gaps = [g for g in gaps if g.field == "settings.localRepository"]
        assert len(settings_gaps) == 1


class TestSpringBootProperties:
    @pytest.mark.integration
    def test_resolve_spring_boot_properties(self):
        """Integration: resolve properties for spring-boot-starter-parent 2.7.18."""
        parser = PomParser()
        xml_text = fetch_pom(
            "org.springframework.boot", "spring-boot-starter-parent", "2.7.18"
        )
        pom = parser.parse(xml_text)
        chain = parser.resolve_parent_chain(pom)
        merged = parser.merge_poms(chain)

        resolver = PropertyResolver()
        resolved, gaps = resolver.resolve(merged)

        assert len(resolved) > 0
        assert "java.version" in resolved
        assert resolved["java.version"] == "1.8"

        assert resolved.get("maven.compiler.source") == "1.8"
        assert resolved.get("maven.compiler.target") == "1.8"
