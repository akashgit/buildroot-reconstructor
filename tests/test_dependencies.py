"""Tests for transitive dependency tree resolution."""

from __future__ import annotations

import shutil

import pytest

from buildroot.pipeline.models import DependencyNode
from buildroot.resolvers.dependencies import DependencyResolver

SIMPLE_TREE_OUTPUT = """\
[INFO] Scanning for projects...
[INFO]
[INFO] --- maven-dependency-plugin:3.6.0:tree (default-cli) @ temp-resolver ---
[INFO] com.buildroot:temp-resolver:jar:1.0
[INFO] +- org.springframework.boot:spring-boot:jar:2.7.18:compile
[INFO] +- org.yaml:snakeyaml:jar:1.30:compile
[INFO] \\- org.slf4j:slf4j-api:jar:1.7.36:compile
[INFO] ------------------------------------------------------------------------
[INFO] BUILD SUCCESS
"""

NESTED_TREE_OUTPUT = """\
[INFO] Scanning for projects...
[INFO]
[INFO] --- maven-dependency-plugin:3.6.0:tree (default-cli) @ temp-resolver ---
[INFO] com.buildroot:temp-resolver:jar:1.0
[INFO] +- org.springframework.boot:spring-boot:jar:2.7.18:compile
[INFO] |  +- org.springframework:spring-core:jar:5.3.31:compile
[INFO] |  |  \\- org.springframework:spring-jcl:jar:5.3.31:compile
[INFO] |  \\- org.springframework:spring-context:jar:5.3.31:compile
[INFO] \\- org.yaml:snakeyaml:jar:1.30:compile
[INFO] ------------------------------------------------------------------------
[INFO] BUILD SUCCESS
"""

TREE_WITH_SCOPES = """\
[INFO] com.buildroot:temp-resolver:jar:1.0
[INFO] +- org.springframework:spring-core:jar:5.3.31:compile
[INFO] +- junit:junit:jar:4.13.2:test
[INFO] \\- org.slf4j:slf4j-api:jar:1.7.36:runtime
"""


class TestParseTreeTextSimple:
    def test_parses_direct_dependencies(self):
        resolver = DependencyResolver()
        nodes = resolver._parse_tree_text(SIMPLE_TREE_OUTPUT)
        assert len(nodes) == 3

        assert nodes[0].group_id == "org.springframework.boot"
        assert nodes[0].artifact_id == "spring-boot"
        assert nodes[0].version == "2.7.18"
        assert nodes[0].scope == "compile"

        assert nodes[1].group_id == "org.yaml"
        assert nodes[1].artifact_id == "snakeyaml"
        assert nodes[1].version == "1.30"

        assert nodes[2].group_id == "org.slf4j"
        assert nodes[2].artifact_id == "slf4j-api"
        assert nodes[2].version == "1.7.36"

    def test_no_children_for_flat_deps(self):
        resolver = DependencyResolver()
        nodes = resolver._parse_tree_text(SIMPLE_TREE_OUTPUT)
        for node in nodes:
            assert node.children == []


class TestParseTreeTextNested:
    def test_nested_structure(self):
        resolver = DependencyResolver()
        nodes = resolver._parse_tree_text(NESTED_TREE_OUTPUT)
        assert len(nodes) == 2

        spring_boot = nodes[0]
        assert spring_boot.artifact_id == "spring-boot"
        assert len(spring_boot.children) == 2

        spring_core = spring_boot.children[0]
        assert spring_core.artifact_id == "spring-core"
        assert len(spring_core.children) == 1
        assert spring_core.children[0].artifact_id == "spring-jcl"

        spring_context = spring_boot.children[1]
        assert spring_context.artifact_id == "spring-context"
        assert spring_context.children == []

        snakeyaml = nodes[1]
        assert snakeyaml.artifact_id == "snakeyaml"
        assert snakeyaml.children == []

    def test_scopes_preserved(self):
        resolver = DependencyResolver()
        nodes = resolver._parse_tree_text(TREE_WITH_SCOPES)
        assert nodes[0].scope == "compile"
        assert nodes[1].scope == "test"
        assert nodes[2].scope == "runtime"


class TestSkipDeps:
    def test_skip_deps_returns_empty(self):
        resolver = DependencyResolver()
        result = resolver.resolve(
            "org.springframework", "spring-core", "5.3.31",
            skip_deps=True,
        )
        assert result == []


class TestResolveSpringBootStarterWeb:
    @pytest.mark.integration
    def test_resolve_produces_nodes(self):
        if not shutil.which("mvn"):
            pytest.skip("Maven not available")

        resolver = DependencyResolver()
        nodes = resolver.resolve(
            "org.springframework.boot",
            "spring-boot-starter-web",
            "2.7.18",
        )
        assert len(nodes) > 0

        artifact_ids = []
        _collect_artifacts(nodes, artifact_ids)
        assert "spring-boot-starter-web" in artifact_ids
        assert "spring-webmvc" in artifact_ids or "spring-web" in artifact_ids


def _collect_artifacts(nodes: list[DependencyNode], out: list[str]) -> None:
    for node in nodes:
        out.append(node.artifact_id)
        _collect_artifacts(node.children, out)
