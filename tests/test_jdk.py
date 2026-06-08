"""Tests for JDK version inference with priority heuristic."""

from __future__ import annotations

from buildroot.pipeline.models import Annotated, CIData, PomData, Source
from buildroot.resolvers.jdk import JdkResolver


def _ci_with_java(version: str, distribution: str = "temurin") -> CIData:
    return CIData(
        java_version=Annotated(
            value=version,
            source=Source.OBSERVED,
            description="CI setup-java",
        ),
        distribution=Annotated(
            value=distribution,
            source=Source.OBSERVED,
            description="CI setup-java",
        ),
        ci_type="github",
    )


class TestCITakesPriorityOverPOM:
    def test_ci_java_21_overrides_pom_source_11(self):
        """CI says JDK 21, POM says source=11 -> JDK 21."""
        ci = _ci_with_java("21")
        pom = PomData()
        props = {"maven.compiler.source": "11"}

        resolver = JdkResolver()
        spec = resolver.resolve(pom, ci, props)

        assert spec.version == "21"
        assert spec.confidence.level == Source.OBSERVED


class TestPOMCompilerRelease:
    def test_no_ci_pom_has_compiler_release(self):
        """No CI, POM has maven.compiler.release=17 -> JDK 17."""
        pom = PomData()
        props = {"maven.compiler.release": "17"}

        resolver = JdkResolver()
        spec = resolver.resolve(pom, None, props)

        assert spec.version == "17"
        assert spec.confidence.level == Source.INFERRED


class TestPOMSourceTarget:
    def test_no_ci_pom_has_source_11(self):
        """No CI, POM has source=11 -> JDK 11."""
        pom = PomData()
        props = {"maven.compiler.source": "11"}

        resolver = JdkResolver()
        spec = resolver.resolve(pom, None, props)

        assert spec.version == "11"
        assert spec.confidence.level == Source.INFERRED


class TestSpringBootJavaVersion:
    def test_spring_boot_java_version_property(self):
        """Spring Boot project with java.version=17."""
        pom = PomData()
        props = {"java.version": "17"}

        resolver = JdkResolver()
        spec = resolver.resolve(pom, None, props)

        assert spec.version == "17"
        assert spec.confidence.level == Source.INFERRED
        assert "java.version" in spec.source_description


class TestDefaultJDK:
    def test_no_signals_defaults_to_17(self):
        """No signals at all -> JDK 17 with DEFAULTED source."""
        pom = PomData()
        props = {}

        resolver = JdkResolver()
        spec = resolver.resolve(pom, None, props)

        assert spec.version == "17"
        assert spec.confidence.level == Source.DEFAULTED


class TestConflictDetection:
    def test_ci_21_pom_source_11_has_conflict(self):
        """CI says 21, POM source says 11 -> JDK 21 with conflict logged."""
        ci = _ci_with_java("21")
        pom = PomData()
        props = {"maven.compiler.source": "11"}

        resolver = JdkResolver()
        spec = resolver.resolve(pom, ci, props)

        assert spec.version == "21"
        assert len(spec.conflicts) > 0
        versions_in_conflicts = [c["version"] for c in spec.conflicts]
        assert "21" in versions_in_conflicts
        assert "11" in versions_in_conflicts


class TestDistributionToImageMapping:
    def test_temurin(self):
        resolver = JdkResolver()
        spec = resolver.resolve(PomData(), _ci_with_java("17", "temurin"), {})
        assert spec.base_image == "eclipse-temurin:17"

    def test_corretto(self):
        resolver = JdkResolver()
        spec = resolver.resolve(PomData(), _ci_with_java("17", "corretto"), {})
        assert spec.base_image == "amazoncorretto:17"

    def test_zulu(self):
        resolver = JdkResolver()
        spec = resolver.resolve(PomData(), _ci_with_java("17", "zulu"), {})
        assert spec.base_image == "azul/zulu-openjdk:17"

    def test_liberica(self):
        resolver = JdkResolver()
        spec = resolver.resolve(PomData(), _ci_with_java("17", "liberica"), {})
        assert spec.base_image == "bellsoft/liberica-openjdk-debian:17"

    def test_unknown_distribution_defaults_to_temurin(self):
        resolver = JdkResolver()
        spec = resolver.resolve(PomData(), _ci_with_java("17", "unknown-jdk"), {})
        assert spec.base_image == "eclipse-temurin:17"

    def test_default_distribution_when_none_specified(self):
        """When no CI and no distribution hint, defaults to temurin."""
        resolver = JdkResolver()
        spec = resolver.resolve(PomData(), None, {"maven.compiler.release": "17"})
        assert spec.distribution == "temurin"
        assert spec.base_image == "eclipse-temurin:17"


class TestCompilerPluginResolution:
    def test_compiler_plugin_release(self):
        """maven-compiler-plugin <release>17</release> -> JDK 17."""
        pom = PomData(
            build_plugins=[{
                "groupId": "org.apache.maven.plugins",
                "artifactId": "maven-compiler-plugin",
                "configuration": {"release": "17"},
            }]
        )
        resolver = JdkResolver()
        spec = resolver.resolve(pom, None, {})
        assert spec.version == "17"

    def test_compiler_plugin_source(self):
        """maven-compiler-plugin <source>11</source> -> JDK 11."""
        pom = PomData(
            build_plugins=[{
                "groupId": "org.apache.maven.plugins",
                "artifactId": "maven-compiler-plugin",
                "configuration": {"source": "11"},
            }]
        )
        resolver = JdkResolver()
        spec = resolver.resolve(pom, None, {})
        assert spec.version == "11"
