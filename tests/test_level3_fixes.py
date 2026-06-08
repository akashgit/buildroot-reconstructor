"""Tests for all 6 Level 3 fixes."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from buildroot.pipeline.models import (
    Annotated,
    BuildrootSpec,
    CIData,
    JdkSpec,
    PomData,
    Source,
)
from buildroot.pipeline.orchestrator import (
    BuildrootOrchestrator,
    _parse_maven_wrapper_version,
)
from buildroot.resolvers.jdk import JdkResolver
from buildroot.utils.github_api import (
    _normalize_scm_url,
    discover_git_tag,
    discover_repo_from_pom,
)


# ==========================================================================
# Fix 1: SCM extraction from POM XML
# ==========================================================================


class TestSCMExtraction:
    def test_scm_url_github(self):
        pom = PomData(
            group_id="org.example",
            artifact_id="my-lib",
            scm={"url": "https://github.com/example/my-lib"},
        )
        result = discover_repo_from_pom(pom)
        assert result == ("example", "my-lib")

    def test_scm_connection_with_prefix(self):
        pom = PomData(
            group_id="org.example",
            artifact_id="my-lib",
            scm={"connection": "scm:git:https://github.com/example/my-lib.git"},
        )
        result = discover_repo_from_pom(pom)
        assert result == ("example", "my-lib")

    def test_scm_developer_connection_git_at(self):
        pom = PomData(
            group_id="org.example",
            artifact_id="my-lib",
            scm={
                "developerConnection": "scm:git:git@github.com:example/my-lib.git"
            },
        )
        result = discover_repo_from_pom(pom)
        assert result == ("example", "my-lib")

    def test_scm_git_protocol(self):
        pom = PomData(
            group_id="org.example",
            artifact_id="my-lib",
            scm={"connection": "scm:git:git://github.com/example/my-lib.git"},
        )
        result = discover_repo_from_pom(pom)
        assert result == ("example", "my-lib")

    def test_scm_gitbox_apache(self):
        pom = PomData(
            group_id="org.apache.commons",
            artifact_id="commons-lang3",
            scm={
                "connection": "scm:git:https://gitbox.apache.org/repos/asf/commons-lang.git"
            },
        )
        result = discover_repo_from_pom(pom)
        assert result == ("apache", "commons-lang")

    def test_project_url_fallback(self):
        pom = PomData(
            group_id="org.example",
            artifact_id="my-lib",
            url="https://github.com/example/my-lib",
        )
        result = discover_repo_from_pom(pom)
        assert result == ("example", "my-lib")

    def test_spring_fallback_still_works(self):
        pom = PomData(
            group_id="org.springframework.boot",
            artifact_id="spring-boot",
        )
        result = discover_repo_from_pom(pom)
        assert result == ("spring-projects", "spring-boot")

    def test_no_scm_no_spring_returns_none(self):
        pom = PomData(
            group_id="com.example",
            artifact_id="unknown-lib",
        )
        result = discover_repo_from_pom(pom)
        assert result is None


class TestNormalizeSCMUrl:
    def test_strip_scm_git_prefix(self):
        assert _normalize_scm_url("scm:git:https://github.com/a/b.git") == "https://github.com/a/b.git"

    def test_git_protocol_to_https(self):
        assert _normalize_scm_url("git://github.com/a/b.git") == "https://github.com/a/b.git"

    def test_git_at_to_https(self):
        result = _normalize_scm_url("git@github.com:a/b.git")
        assert result == "https://github.com/a/b.git"

    def test_plain_https_unchanged(self):
        assert _normalize_scm_url("https://github.com/a/b") == "https://github.com/a/b"


# ==========================================================================
# Fix 2: Git tag format discovery
# ==========================================================================


class TestDiscoverGitTag:
    @patch("buildroot.utils.github_api._get")
    def test_v_prefix_match(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = [
            {"name": "v1.0.0"},
            {"name": "v0.9.0"},
        ]
        resp.headers = {"Link": ""}
        mock_get.return_value = resp

        tag = discover_git_tag("owner", "repo", "my-lib", "1.0.0")
        assert tag == "v1.0.0"

    @patch("buildroot.utils.github_api._get")
    def test_artifact_version_match(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = [
            {"name": "commons-lang3-3.14.0"},
            {"name": "commons-lang3-3.13.0"},
        ]
        resp.headers = {"Link": ""}
        mock_get.return_value = resp

        tag = discover_git_tag("owner", "repo", "commons-lang3", "3.14.0")
        assert tag == "commons-lang3-3.14.0"

    @patch("buildroot.utils.github_api._get")
    def test_rel_prefix_match(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = [
            {"name": "rel/commons-lang3-3.14.0"},
        ]
        resp.headers = {"Link": ""}
        mock_get.return_value = resp

        tag = discover_git_tag("owner", "repo", "commons-lang3", "3.14.0")
        assert tag == "rel/commons-lang3-3.14.0"

    @patch("buildroot.utils.github_api._get")
    def test_bare_version_match(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = [
            {"name": "3.14.0"},
        ]
        resp.headers = {"Link": ""}
        mock_get.return_value = resp

        tag = discover_git_tag("owner", "repo", "commons-lang3", "3.14.0")
        assert tag == "3.14.0"

    @patch("buildroot.utils.github_api._get")
    def test_fallback_to_v_prefix(self, mock_get):
        mock_get.return_value = None

        tag = discover_git_tag("owner", "repo", "my-lib", "1.0.0")
        assert tag == "v1.0.0"

    @patch("buildroot.utils.github_api._get")
    def test_fuzzy_match_suffix(self, mock_get):
        resp = MagicMock()
        resp.json.return_value = [
            {"name": "thymeleaf-3.1.2.RELEASE"},
        ]
        resp.headers = {"Link": ""}
        mock_get.return_value = resp

        tag = discover_git_tag("owner", "repo", "thymeleaf", "3.1.2.RELEASE")
        assert tag == "thymeleaf-3.1.2.RELEASE"


# ==========================================================================
# Fix 3: Template source acquisition
# ==========================================================================


class TestTemplateSrcAcquisition:
    def test_containerfile_has_git_clone_when_source_repo(self):
        from buildroot.generators.containerfile import ContainerfileGenerator

        spec = BuildrootSpec(
            source_repo="https://github.com/example/repo",
            git_tag="v1.0.0",
            jdk_spec=JdkSpec(
                version="17",
                distribution="temurin",
                base_image="eclipse-temurin:17",
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = ContainerfileGenerator()
            gen.generate(spec, Path(tmpdir))
            content = (Path(tmpdir) / "Containerfile").read_text()

        assert "git clone" in content
        assert "--branch 'v1.0.0'" in content
        assert "'https://github.com/example/repo'" in content
        assert "COPY . ." not in content

    def test_containerfile_has_copy_fallback_when_no_source(self):
        from buildroot.generators.containerfile import ContainerfileGenerator

        spec = BuildrootSpec(
            source_repo="",
            git_tag="",
            jdk_spec=JdkSpec(
                version="17",
                distribution="temurin",
                base_image="eclipse-temurin:17",
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            gen = ContainerfileGenerator()
            gen.generate(spec, Path(tmpdir))
            content = (Path(tmpdir) / "Containerfile").read_text()

        assert "COPY . ." in content
        assert "git clone" not in content


# ==========================================================================
# Fix 4: JDK from JAR manifest
# ==========================================================================


class TestJDKFromJARManifest:
    @patch("buildroot.resolvers.jdk.fetch_jar_manifest_jdk")
    def test_jar_manifest_overrides_pom(self, mock_fetch):
        mock_fetch.return_value = "21"

        pom = PomData()
        props = {"maven.compiler.source": "11"}

        resolver = JdkResolver()
        spec = resolver.resolve(
            pom, None, props,
            group_id="org.example", artifact_id="lib", version="1.0",
        )

        assert spec.version == "21"
        assert spec.confidence.level == Source.OBSERVED
        assert "JAR manifest" in spec.source_description

    @patch("buildroot.resolvers.jdk.fetch_jar_manifest_jdk")
    def test_jar_manifest_overrides_ci(self, mock_fetch):
        mock_fetch.return_value = "21"

        ci = CIData(
            java_version=Annotated(value="17", source=Source.OBSERVED),
            ci_type="github",
        )
        pom = PomData()

        resolver = JdkResolver()
        spec = resolver.resolve(
            pom, ci, {},
            group_id="org.example", artifact_id="lib", version="1.0",
        )

        assert spec.version == "21"

    @patch("buildroot.resolvers.jdk.fetch_jar_manifest_jdk")
    def test_no_manifest_falls_through(self, mock_fetch):
        mock_fetch.return_value = ""

        pom = PomData()
        props = {"maven.compiler.source": "11"}

        resolver = JdkResolver()
        spec = resolver.resolve(
            pom, None, props,
            group_id="org.example", artifact_id="lib", version="1.0",
        )

        assert spec.version == "11"

    def test_no_gav_skips_manifest_check(self):
        pom = PomData()
        props = {"maven.compiler.source": "11"}

        resolver = JdkResolver()
        spec = resolver.resolve(pom, None, props)

        assert spec.version == "11"


# ==========================================================================
# Fix 5: Build command enrichment
# ==========================================================================


class TestBuildCommandEnrichment:
    def test_default_command_with_gpg_and_rat(self):
        pom = PomData(
            group_id="org.apache.commons",
            artifact_id="commons-lang3",
            build_plugins=[
                {"artifactId": "maven-gpg-plugin"},
                {"artifactId": "apache-rat-plugin"},
            ],
        )
        spec = BuildrootSpec(pom_data=pom, maven_version="3.9.6")
        orch = BuildrootOrchestrator(skip_deps=True)
        orch._enrich_build_commands(spec, pom)

        cmd = spec.build_commands[0]
        assert "./mvnw" in cmd
        assert "-Dgpg.skip=true" in cmd
        assert "-Drat.skip=true" in cmd
        assert "-DskipTests" in cmd
        assert "-Papache-release" in cmd

    def test_enrich_existing_ci_command(self):
        pom = PomData(
            group_id="org.apache.commons",
            artifact_id="commons-lang3",
            build_plugins=[
                {"artifactId": "maven-gpg-plugin"},
            ],
        )
        spec = BuildrootSpec(
            pom_data=pom,
            build_commands=["mvn clean install -B"],
            maven_version="3.9.6",
        )
        orch = BuildrootOrchestrator(skip_deps=True)
        orch._enrich_build_commands(spec, pom)

        cmd = spec.build_commands[0]
        assert cmd.startswith("./mvnw ")
        assert "-DskipTests" in cmd
        assert "-Dgpg.skip=true" in cmd
        assert "-Papache-release" in cmd

    def test_no_wrapper_uses_mvn(self):
        pom = PomData(
            group_id="com.example",
            artifact_id="lib",
        )
        spec = BuildrootSpec(pom_data=pom)
        orch = BuildrootOrchestrator(skip_deps=True)
        orch._enrich_build_commands(spec, pom)

        cmd = spec.build_commands[0]
        assert cmd.startswith("mvn ")
        assert "./mvnw" not in cmd

    def test_skip_tests_not_duplicated(self):
        pom = PomData(group_id="com.example", artifact_id="lib")
        spec = BuildrootSpec(
            pom_data=pom,
            build_commands=["mvn clean install -DskipTests"],
        )
        orch = BuildrootOrchestrator(skip_deps=True)
        orch._enrich_build_commands(spec, pom)

        cmd = spec.build_commands[0]
        assert cmd.count("-DskipTests") == 1


# ==========================================================================
# Fix 6: Maven version from wrapper
# ==========================================================================


class TestMavenVersionFromWrapper:
    def test_parse_distribution_url(self):
        content = """distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.6/apache-maven-3.9.6-bin.zip
wrapperUrl=https://repo.maven.apache.org/maven2/org/apache/maven/wrapper/maven-wrapper/3.2.0/maven-wrapper-3.2.0.jar"""
        version = _parse_maven_wrapper_version(content)
        assert version == "3.9.6"

    def test_parse_old_format(self):
        content = """distributionUrl=https\\://archive.apache.org/dist/maven/maven-3/3.8.8/binaries/apache-maven-3.8.8-bin.zip"""
        version = _parse_maven_wrapper_version(content)
        assert version == "3.8.8"

    def test_empty_content(self):
        assert _parse_maven_wrapper_version("") == ""

    def test_no_distribution_url(self):
        content = "# just a comment\nsome_key=some_value"
        assert _parse_maven_wrapper_version(content) == ""

    @patch("buildroot.pipeline.orchestrator.fetch_maven_wrapper_properties")
    def test_orchestrator_detects_version(self, mock_fetch):
        mock_fetch.return_value = "distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.6/apache-maven-3.9.6-bin.zip"
        orch = BuildrootOrchestrator(skip_deps=True)
        version = orch._detect_maven_wrapper_version("owner", "repo")
        assert version == "3.9.6"

    @patch("buildroot.pipeline.orchestrator.fetch_maven_wrapper_properties")
    def test_orchestrator_no_wrapper(self, mock_fetch):
        mock_fetch.return_value = None
        orch = BuildrootOrchestrator(skip_deps=True)
        version = orch._detect_maven_wrapper_version("owner", "repo")
        assert version == ""


# ==========================================================================
# Integration: Full mock pipeline with all fixes
# ==========================================================================


class TestReconstructWithAllFixes:
    @patch("buildroot.pipeline.orchestrator.fetch_pom")
    @patch("buildroot.pipeline.orchestrator.discover_repo_from_pom")
    @patch("buildroot.pipeline.orchestrator.discover_git_tag")
    @patch("buildroot.pipeline.orchestrator.fetch_maven_wrapper_properties")
    @patch("buildroot.resolvers.jdk.fetch_jar_manifest_jdk")
    def test_full_pipeline(
        self, mock_jar_jdk, mock_wrapper, mock_tag, mock_discover, mock_fetch
    ):
        mock_fetch.return_value = """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>org.apache.commons</groupId>
    <artifactId>commons-lang3</artifactId>
    <version>3.14.0</version>
    <scm>
        <connection>scm:git:https://github.com/apache/commons-lang.git</connection>
    </scm>
    <build>
        <plugins>
            <plugin>
                <artifactId>maven-gpg-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>"""
        mock_discover.return_value = ("apache", "commons-lang")
        mock_tag.return_value = "rel/commons-lang-3.14.0"
        mock_wrapper.return_value = "distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.6/apache-maven-3.9.6-bin.zip"
        mock_jar_jdk.return_value = "21"

        with tempfile.TemporaryDirectory() as tmpdir:
            orch = BuildrootOrchestrator(skip_deps=True)
            spec = orch.reconstruct(
                "org.apache.commons", "commons-lang3", "3.14.0",
                output_dir=tmpdir,
            )

            assert spec.git_tag == "rel/commons-lang-3.14.0"
            assert spec.maven_version == "3.9.6"
            assert spec.jdk_spec.version == "21"

            cmd = spec.build_commands[0]
            assert "-Dgpg.skip=true" in cmd

            content = (Path(tmpdir) / "Containerfile").read_text()
            assert "git clone" in content
            assert "rel/commons-lang-3.14.0" in content

            data = json.loads((Path(tmpdir) / "buildroot.json").read_text())
            assert data["maven_version"]["value"] == "3.9.6"
