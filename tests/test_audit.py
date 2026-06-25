"""Tests for buildroot.eval.audit — supply chain audit log extraction."""

from __future__ import annotations

from buildroot.eval.audit import (
    AuditEntry,
    build_audit_log,
    extract_dynamic_assets,
    extract_static_assets,
)


class TestExtractStaticAssets:
    def test_from_instruction(self):
        cf = "FROM openjdk:17-slim\nRUN echo hello"
        entries = extract_static_assets(cf)
        base = [e for e in entries if e.type == "base_image"]
        assert len(base) == 1
        assert base[0].name == "openjdk"
        assert base[0].tag == "17-slim"
        assert base[0].source == "docker.io"

    def test_from_with_registry(self):
        cf = "FROM registry.access.redhat.com/ubi9/openjdk-17:latest"
        entries = extract_static_assets(cf)
        base = [e for e in entries if e.type == "base_image"]
        assert len(base) == 1
        assert base[0].source == "registry.access.redhat.com"
        assert base[0].tag == "latest"

    def test_from_with_digest(self):
        cf = "FROM openjdk@sha256:abc123"
        entries = extract_static_assets(cf)
        base = [e for e in entries if e.type == "base_image"]
        assert len(base) == 1
        assert base[0].digest == "sha256:abc123"

    def test_from_scratch(self):
        cf = "FROM scratch"
        entries = extract_static_assets(cf)
        base = [e for e in entries if e.type == "base_image"]
        assert len(base) == 0

    def test_multistage_from(self):
        cf = "FROM openjdk:17 AS builder\nRUN mvn install\nFROM openjdk:17-jre\nCOPY --from=builder /app ."
        entries = extract_static_assets(cf)
        base = [e for e in entries if e.type == "base_image"]
        assert len(base) == 2

    def test_apt_get_install(self):
        cf = "FROM ubuntu:22.04\nRUN apt-get update && apt-get install -y git curl wget"
        entries = extract_static_assets(cf)
        pkgs = [e for e in entries if e.type == "os_package"]
        names = {e.name for e in pkgs}
        assert "git" in names
        assert "curl" in names
        assert "wget" in names
        for p in pkgs:
            assert p.source == "apt"

    def test_yum_install(self):
        cf = "FROM centos:7\nRUN yum install -y java-17-openjdk-devel git"
        entries = extract_static_assets(cf)
        pkgs = [e for e in entries if e.type == "os_package"]
        names = {e.name for e in pkgs}
        assert "java-17-openjdk-devel" in names
        assert "git" in names

    def test_git_clone(self):
        cf = "FROM openjdk:17\nRUN git clone --depth 1 --branch v2.0 https://github.com/example/repo.git /build"
        entries = extract_static_assets(cf)
        repos = [e for e in entries if e.type == "git_repo"]
        assert len(repos) == 1
        assert repos[0].name == "repo"
        assert repos[0].url == "https://github.com/example/repo.git"
        assert repos[0].depth == 1

    def test_curl_download(self):
        cf = "FROM openjdk:17\nRUN curl -L https://example.com/file.tar.gz -o /tmp/file.tar.gz"
        entries = extract_static_assets(cf)
        downloads = [e for e in entries if e.type == "direct_download"]
        assert len(downloads) == 1
        assert downloads[0].url == "https://example.com/file.tar.gz"
        assert downloads[0].source == "example.com"

    def test_add_url(self):
        cf = "FROM openjdk:17\nADD https://example.com/tool.jar /opt/"
        entries = extract_static_assets(cf)
        downloads = [e for e in entries if e.type == "direct_download"]
        assert len(downloads) == 1
        assert downloads[0].name == "tool.jar"

    def test_empty_containerfile(self):
        entries = extract_static_assets("")
        assert entries == []

    def test_package_version_stripping(self):
        cf = "FROM ubuntu\nRUN apt-get install -y git=1:2.34.1-1ubuntu1"
        entries = extract_static_assets(cf)
        pkgs = [e for e in entries if e.type == "os_package"]
        assert any(p.name == "git" for p in pkgs)


class TestExtractDynamicAssets:
    def test_maven_download(self):
        log = """
Downloading from central: https://repo1.maven.org/maven2/org/apache/commons/commons-lang3/3.14.0/commons-lang3-3.14.0.jar
Downloaded from central: https://repo1.maven.org/maven2/org/apache/commons/commons-lang3/3.14.0/commons-lang3-3.14.0.jar
"""
        entries = extract_dynamic_assets(log)
        assert len(entries) == 1
        assert entries[0].type == "build_dependency"
        assert entries[0].name == "commons-lang3"
        assert entries[0].version == "3.14.0"
        assert entries[0].framework == "maven"

    def test_maven_plugin_detection(self):
        log = "Downloading from central: https://repo1.maven.org/maven2/org/apache/maven/plugins/maven-compiler-plugin/3.11.0/maven-compiler-plugin-3.11.0.jar\n"
        entries = extract_dynamic_assets(log)
        assert len(entries) == 1
        assert entries[0].type == "build_plugin"

    def test_gradle_download(self):
        log = "Download https://services.gradle.org/distributions/gradle-8.4-bin.zip\n"
        entries = extract_dynamic_assets(log)
        assert len(entries) == 1
        assert entries[0].framework == "gradle"

    def test_dedup_urls(self):
        log = """
Downloading from central: https://repo1.maven.org/maven2/a/b/1.0/b-1.0.jar
Downloading from central: https://repo1.maven.org/maven2/a/b/1.0/b-1.0.jar
"""
        entries = extract_dynamic_assets(log)
        assert len(entries) == 1

    def test_empty_log(self):
        entries = extract_dynamic_assets("")
        assert entries == []

    def test_no_download_lines(self):
        entries = extract_dynamic_assets("BUILD SUCCESS\nDone.\n")
        assert entries == []


class TestBuildAuditLog:
    def test_merge(self):
        static = [AuditEntry(type="base_image", name="openjdk", source="docker.io")]
        dynamic = [AuditEntry(type="build_dependency", name="commons", source="repo1.maven.org")]
        log = build_audit_log(static, dynamic)
        assert log.total_assets == 2
        assert len(log.unique_sources) == 2

    def test_dedup(self):
        entries = [
            AuditEntry(type="os_package", name="git", source="apt"),
            AuditEntry(type="os_package", name="git", source="apt"),
        ]
        log = build_audit_log(entries, [])
        assert log.total_assets == 1

    def test_reference_jar(self):
        log = build_audit_log([], [], reference_jar_url="https://repo1.maven.org/maven2/a/b/1.0/b-1.0.jar")
        assert log.total_assets == 1
        assert log.assets[0].type == "reference_jar"
        assert log.assets[0].source == "repo1.maven.org"

    def test_empty(self):
        log = build_audit_log([], [])
        assert log.total_assets == 0
        assert log.unique_sources == []

    def test_to_dict(self):
        static = [AuditEntry(type="base_image", name="openjdk", source="docker.io", tag="17")]
        log = build_audit_log(static, [])
        d = log.to_dict()
        assert d["total_assets"] == 1
        assert "docker.io" in d["unique_sources"]
        assert d["assets"][0]["tag"] == "17"


class TestAuditEntry:
    def test_to_dict_minimal(self):
        e = AuditEntry(type="os_package", name="git", source="apt")
        d = e.to_dict()
        assert d == {"type": "os_package", "name": "git", "source": "apt"}
        assert "version" not in d

    def test_to_dict_with_optional_fields(self):
        e = AuditEntry(type="base_image", name="openjdk", source="docker.io", tag="17", digest="sha256:abc")
        d = e.to_dict()
        assert d["tag"] == "17"
        assert d["digest"] == "sha256:abc"
