"""Tests for the pnc-deps CLI command and supporting functions."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from buildroot.cli.commands.pnc_deps import flatten_dependency_tree, pnc_deps_cmd
from buildroot.pipeline.models import DependencyNode
from buildroot.utils.pnc_api import PncBuildInfo, find_closest_pnc_version


class TestFlattenDependencyTree:
    def test_empty_tree(self):
        assert flatten_dependency_tree([]) == []

    def test_single_node(self):
        node = DependencyNode(group_id="g", artifact_id="a", version="1.0")
        result = flatten_dependency_tree([node])
        assert result == [("g", "a", "1.0")]

    def test_nested_tree(self):
        child = DependencyNode(group_id="g2", artifact_id="a2", version="2.0")
        root = DependencyNode(
            group_id="g1", artifact_id="a1", version="1.0", children=[child]
        )
        result = flatten_dependency_tree([root])
        assert ("g1", "a1", "1.0") in result
        assert ("g2", "a2", "2.0") in result
        assert len(result) == 2

    def test_dedup(self):
        root1 = DependencyNode(
            group_id="r1", artifact_id="a1", version="1.0",
            children=[DependencyNode(group_id="g", artifact_id="a", version="1.0")],
        )
        root2 = DependencyNode(
            group_id="r2", artifact_id="a2", version="2.0",
            children=[DependencyNode(group_id="g", artifact_id="a", version="1.0")],
        )
        result = flatten_dependency_tree([root1, root2])
        count = sum(1 for t in result if t == ("g", "a", "1.0"))
        assert count == 1

    def test_deep_tree(self):
        leaf = DependencyNode(group_id="leaf", artifact_id="l", version="1.0")
        mid = DependencyNode(
            group_id="mid", artifact_id="m", version="1.0", children=[leaf]
        )
        root = DependencyNode(
            group_id="root", artifact_id="r", version="1.0", children=[mid]
        )
        result = flatten_dependency_tree([root])
        assert len(result) == 3


class TestFindClosestPncVersion:
    def test_returns_none_when_no_match(self):
        client = MagicMock()
        client.query_by_gav.return_value = None
        result = find_closest_pnc_version("g", "a", "1.0", client=client)
        assert result is None
        assert client.query_by_gav.call_count == 7

    def test_returns_first_match(self):
        info = PncBuildInfo(build_id="123")
        client = MagicMock()
        client.query_by_gav.side_effect = [None, info]
        result = find_closest_pnc_version("g", "a", "1.0", client=client)
        assert result is not None
        version_str, build_info = result
        assert version_str == "1.0.redhat-00002"
        assert build_info.build_id == "123"
        assert client.query_by_gav.call_count == 2

    def test_tries_redhat_suffixes_in_order(self):
        client = MagicMock()
        client.query_by_gav.return_value = None
        find_closest_pnc_version("g", "a", "2.5", client=client)
        calls = [c.args for c in client.query_by_gav.call_args_list]
        assert calls[0] == ("g", "a", "2.5.redhat-00001")
        assert calls[-1] == ("g", "a", "2.5-redhat-00001")


def _make_cli_patches():
    """Return patch objects for the CLI command's deferred imports."""
    return {
        "resolver": patch("buildroot.resolvers.dependencies.DependencyResolver"),
        "pnc_client": patch("buildroot.utils.pnc_api.PncClient"),
        "find_closest": patch("buildroot.utils.pnc_api.find_closest_pnc_version"),
        "store": patch("buildroot.agent.build_store.fetch_build"),
    }


class TestPncDepsCommand:
    @patch("buildroot.agent.build_store.fetch_build")
    @patch("buildroot.utils.pnc_api.find_closest_pnc_version")
    @patch("buildroot.utils.pnc_api.PncClient")
    @patch("buildroot.resolvers.dependencies.DependencyResolver")
    def test_basic_output(self, mock_resolver_cls, mock_client_cls, mock_find, mock_store):
        node = DependencyNode(group_id="g", artifact_id="a", version="1.0")
        mock_resolver_cls.return_value.resolve.return_value = [node]
        mock_client_cls.return_value.query_by_gav.return_value = PncBuildInfo(build_id="b1")
        mock_store.return_value = None
        mock_find.return_value = None

        runner = CliRunner()
        result = runner.invoke(pnc_deps_cmd, ["g:a:1.0"])
        assert result.exit_code == 0
        assert "Total dependencies:" in result.output
        assert "Available in PNC:" in result.output

    @patch("buildroot.agent.build_store.fetch_build")
    @patch("buildroot.utils.pnc_api.find_closest_pnc_version")
    @patch("buildroot.utils.pnc_api.PncClient")
    @patch("buildroot.resolvers.dependencies.DependencyResolver")
    def test_json_output(self, mock_resolver_cls, mock_client_cls, mock_find, mock_store):
        node = DependencyNode(group_id="g", artifact_id="a", version="1.0")
        mock_resolver_cls.return_value.resolve.return_value = [node]
        mock_client_cls.return_value.query_by_gav.return_value = PncBuildInfo(build_id="b1")
        mock_store.return_value = {"status": "found"}
        mock_find.return_value = None

        runner = CliRunner()
        result = runner.invoke(pnc_deps_cmd, ["g:a:1.0", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 1
        assert data["pnc_available"] == 1
        assert data["missing"] == 0
        assert data["build_store_available"] == 1
        assert "dependencies" in data
        assert len(data["dependencies"]) == 1

    @patch("buildroot.agent.build_store.fetch_build")
    @patch("buildroot.utils.pnc_api.find_closest_pnc_version")
    @patch("buildroot.utils.pnc_api.PncClient")
    @patch("buildroot.resolvers.dependencies.DependencyResolver")
    def test_empty_tree(self, mock_resolver_cls, mock_client_cls, mock_find, mock_store):
        mock_resolver_cls.return_value.resolve.return_value = []

        runner = CliRunner()
        result = runner.invoke(pnc_deps_cmd, ["g:a:1.0"])
        assert result.exit_code == 0
        assert "Total dependencies:    0" in result.output

    @patch("buildroot.agent.build_store.fetch_build")
    @patch("buildroot.utils.pnc_api.find_closest_pnc_version")
    @patch("buildroot.utils.pnc_api.PncClient")
    @patch("buildroot.resolvers.dependencies.DependencyResolver")
    def test_missing_deps_with_closest(self, mock_resolver_cls, mock_client_cls, mock_find, mock_store):
        node = DependencyNode(group_id="g", artifact_id="a", version="1.0")
        mock_resolver_cls.return_value.resolve.return_value = [node]
        mock_client_cls.return_value.query_by_gav.return_value = None
        mock_find.return_value = ("1.0.redhat-00001", PncBuildInfo(build_id="rh1"))
        mock_store.return_value = None

        runner = CliRunner()
        result = runner.invoke(pnc_deps_cmd, ["g:a:1.0"])
        assert result.exit_code == 0
        assert "Missing Dependencies:" in result.output
        assert "1.0.redhat-00001" in result.output

    @patch("buildroot.agent.build_store.fetch_build")
    @patch("buildroot.utils.pnc_api.find_closest_pnc_version")
    @patch("buildroot.utils.pnc_api.PncClient")
    @patch("buildroot.resolvers.dependencies.DependencyResolver")
    def test_dedup_in_tree(self, mock_resolver_cls, mock_client_cls, mock_find, mock_store):
        root1 = DependencyNode(
            group_id="r1", artifact_id="a1", version="1.0",
            children=[DependencyNode(group_id="s", artifact_id="s", version="1.0")],
        )
        root2 = DependencyNode(
            group_id="r2", artifact_id="a2", version="2.0",
            children=[DependencyNode(group_id="s", artifact_id="s", version="1.0")],
        )
        mock_resolver_cls.return_value.resolve.return_value = [root1, root2]
        mock_client_cls.return_value.query_by_gav.return_value = PncBuildInfo(build_id="x")
        mock_find.return_value = None
        mock_store.return_value = None

        runner = CliRunner()
        result = runner.invoke(pnc_deps_cmd, ["g:a:1.0", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 3

    def test_invalid_coordinate(self):
        runner = CliRunner()
        result = runner.invoke(pnc_deps_cmd, ["bad-coordinate"])
        assert result.exit_code == 2
        assert "COORDINATE" in result.output

    @patch("buildroot.agent.build_store.fetch_build")
    @patch("buildroot.utils.pnc_api.find_closest_pnc_version")
    @patch("buildroot.utils.pnc_api.PncClient")
    @patch("buildroot.resolvers.dependencies.DependencyResolver")
    def test_json_keys(self, mock_resolver_cls, mock_client_cls, mock_find, mock_store):
        mock_resolver_cls.return_value.resolve.return_value = []
        runner = CliRunner()
        result = runner.invoke(pnc_deps_cmd, ["g:a:1.0", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert set(data.keys()) == {
            "coordinate", "total", "pnc_available", "missing",
            "build_store_available", "dependencies",
        }
