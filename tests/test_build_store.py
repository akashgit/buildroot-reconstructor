"""Tests for build_store — Postgres sibling warm-start lookups."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetSiblingBuild:
    @patch("buildroot.agent.build_store._get_connection")
    def test_returns_sibling_when_found(self, mock_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            "com.example", "lib", "1.0.0",
            "FROM eclipse-temurin:17-jdk\nRUN mvn install",
            1.0, 4, "v4-agent",
        )
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        from buildroot.agent.build_store import get_sibling_build

        result = get_sibling_build("com.example", "lib", "2.0.0")
        assert result is not None
        assert result["version"] == "1.0.0"
        assert result["reward"] == 1.0
        assert "eclipse-temurin" in result["containerfile"]

    @patch("buildroot.agent.build_store._get_connection")
    def test_returns_none_when_no_sibling(self, mock_conn):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        from buildroot.agent.build_store import get_sibling_build

        result = get_sibling_build("com.example", "lib", "1.0.0")
        assert result is None

    @patch("buildroot.agent.build_store._get_connection")
    def test_returns_none_when_db_unavailable(self, mock_conn):
        mock_conn.return_value = None

        from buildroot.agent.build_store import get_sibling_build

        result = get_sibling_build("com.example", "lib", "1.0.0")
        assert result is None


class TestSaveBuild:
    @patch("buildroot.agent.build_store._get_connection")
    def test_save_parses_coordinate(self, mock_conn):
        mock_cursor = MagicMock()
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        from buildroot.agent.build_store import save_build

        result = save_build(
            "com.example:lib:1.0.0", "FROM jdk:17", 0.99, 4, "v4-agent"
        )
        assert result is True
        mock_cursor.execute.assert_called_once()
        args = mock_cursor.execute.call_args[0][1]
        assert args[0] == "com.example"
        assert args[1] == "lib"
        assert args[2] == "1.0.0"

    def test_save_rejects_bad_coordinate(self):
        from buildroot.agent.build_store import save_build

        result = save_build("bad-coord", "FROM jdk:17", 0.99, 4)
        assert result is False

    @patch("buildroot.agent.build_store._get_connection")
    def test_save_handles_db_error(self, mock_conn):
        mock_conn.return_value = None

        from buildroot.agent.build_store import save_build

        result = save_build("g:a:1.0", "FROM jdk:17", 0.99, 4)
        assert result is False
