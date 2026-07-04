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

    @patch("buildroot.agent.build_store._get_connection")
    def test_save_passes_eval_result(self, mock_conn):
        mock_cursor = MagicMock()
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        from buildroot.agent.build_store import save_build

        eval_dict = {
            "l1_parse": True, "l2_build": True, "l3_command": True,
            "l4_match": False, "l4_score": 0.4, "reward": 0.7,
            "level_reached": 3, "l4_signal_source": "fallback_signals",
            "fallback_signals": {
                "bytecode_version_match": True,
                "manifest_sanity": True,
                "structural_match": 0.5,
                "unit_tests_pass": False,
            },
        }
        result = save_build(
            "com.example:lib:1.0.0", "FROM jdk:17", 0.7, 3, "v4-agent",
            eval_result=eval_dict,
            trusted_eval_result={"l4_signal_source": "full_comparison", "reward": 0.99},
        )
        assert result is True
        args = mock_cursor.execute.call_args[0][1]
        # eval_result is the 18th arg (index 17), trusted_eval_result is 19th (index 18)
        import json
        assert json.loads(args[17])["l4_signal_source"] == "fallback_signals"
        assert json.loads(args[18])["l4_signal_source"] == "full_comparison"
