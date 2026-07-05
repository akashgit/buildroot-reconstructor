"""Postgres build store for sibling warm-start lookups."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql:///postgres"


def _get_connection():
    """Get a Postgres connection via Unix socket. Returns None if unavailable."""
    try:
        import psycopg2
    except ImportError:
        logger.debug("psycopg2 not installed — build store disabled")
        return None

    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    try:
        return psycopg2.connect(url)
    except Exception as e:
        logger.debug("Cannot connect to build store: %s", e)
        return None


def init_table() -> bool:
    """Create the builds table if it doesn't exist. Returns True on success."""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS builds (
                    id SERIAL PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    containerfile TEXT NOT NULL,
                    reward FLOAT NOT NULL,
                    level INTEGER NOT NULL,
                    method TEXT,
                    cost_usd FLOAT DEFAULT 0,
                    elapsed_seconds FLOAT DEFAULT 0,
                    trusted_containerfile TEXT DEFAULT '',
                    trusted_reward FLOAT DEFAULT 0,
                    trusted_level INTEGER DEFAULT 0,
                    delta_report JSONB DEFAULT NULL,
                    trust_report TEXT DEFAULT '',
                    prepass_findings JSONB DEFAULT NULL,
                    exact_comparison JSONB DEFAULT NULL,
                    trusted_comparison JSONB DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(group_id, artifact_id, version)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_builds_sibling
                ON builds(group_id, artifact_id)
            """)
            cur.execute("ALTER TABLE builds ADD COLUMN IF NOT EXISTS exact_comparison JSONB DEFAULT NULL")
            cur.execute("ALTER TABLE builds ADD COLUMN IF NOT EXISTS trusted_comparison JSONB DEFAULT NULL")
            cur.execute("ALTER TABLE builds ADD COLUMN IF NOT EXISTS eval_result JSONB DEFAULT NULL")
            cur.execute("ALTER TABLE builds ADD COLUMN IF NOT EXISTS trusted_eval_result JSONB DEFAULT NULL")
            cur.execute("ALTER TABLE builds ADD COLUMN IF NOT EXISTS rebuilt_jar BYTEA DEFAULT NULL")
        conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to initialize builds table: %s", e)
        return False
    finally:
        conn.close()


def get_sibling_build(
    group_id: str,
    artifact_id: str,
    exclude_version: str,
) -> dict[str, Any] | None:
    """Find the best successful build of a different version of the same artifact."""
    conn = _get_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT group_id, artifact_id, version, containerfile, reward, level, method
                FROM builds
                WHERE group_id = %s AND artifact_id = %s
                  AND version != %s AND reward >= 0.98
                ORDER BY reward DESC, created_at DESC
                LIMIT 1
                """,
                (group_id, artifact_id, exclude_version),
            )
            row = cur.fetchone()
            if row:
                return {
                    "group_id": row[0],
                    "artifact_id": row[1],
                    "version": row[2],
                    "containerfile": row[3],
                    "reward": row[4],
                    "level": row[5],
                    "method": row[6],
                }
        return None
    except Exception as e:
        logger.debug("Sibling build lookup failed: %s", e)
        return None
    finally:
        conn.close()


def save_build(
    coordinate: str,
    containerfile: str,
    reward: float,
    level: int,
    method: str = "",
    cost_usd: float = 0,
    elapsed_seconds: float = 0,
    trusted_containerfile: str = "",
    trusted_reward: float = 0,
    trusted_level: int = 0,
    delta_report: dict | None = None,
    trust_report: str = "",
    prepass_findings: dict | None = None,
    exact_comparison: dict | None = None,
    trusted_comparison: dict | None = None,
    eval_result: dict | None = None,
    trusted_eval_result: dict | None = None,
    rebuilt_jar: bytes | None = None,
) -> bool:
    """Save a successful build to the store. Upserts on (group_id, artifact_id, version)."""
    parts = coordinate.split(":")
    if len(parts) < 3:
        return False
    group_id, artifact_id, version = parts[0], parts[1], parts[2]

    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO builds (group_id, artifact_id, version, containerfile, reward, level,
                                    method, cost_usd, elapsed_seconds,
                                    trusted_containerfile, trusted_reward, trusted_level,
                                    delta_report, trust_report, prepass_findings,
                                    exact_comparison, trusted_comparison,
                                    eval_result, trusted_eval_result, rebuilt_jar)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (group_id, artifact_id, version)
                DO UPDATE SET containerfile = EXCLUDED.containerfile,
                              reward = EXCLUDED.reward,
                              level = EXCLUDED.level,
                              method = EXCLUDED.method,
                              cost_usd = EXCLUDED.cost_usd,
                              elapsed_seconds = EXCLUDED.elapsed_seconds,
                              trusted_containerfile = EXCLUDED.trusted_containerfile,
                              trusted_reward = EXCLUDED.trusted_reward,
                              trusted_level = EXCLUDED.trusted_level,
                              delta_report = EXCLUDED.delta_report,
                              trust_report = EXCLUDED.trust_report,
                              prepass_findings = EXCLUDED.prepass_findings,
                              exact_comparison = EXCLUDED.exact_comparison,
                              trusted_comparison = EXCLUDED.trusted_comparison,
                              eval_result = EXCLUDED.eval_result,
                              trusted_eval_result = EXCLUDED.trusted_eval_result,
                              rebuilt_jar = EXCLUDED.rebuilt_jar,
                              created_at = NOW()
                WHERE EXCLUDED.reward >= builds.reward
                """,
                (group_id, artifact_id, version, containerfile, reward, level, method,
                 cost_usd, elapsed_seconds, trusted_containerfile, trusted_reward, trusted_level,
                 json.dumps(delta_report) if delta_report else None,
                 trust_report,
                 json.dumps(prepass_findings) if prepass_findings else None,
                 json.dumps(exact_comparison) if exact_comparison else None,
                 json.dumps(trusted_comparison) if trusted_comparison else None,
                 json.dumps(eval_result) if eval_result else None,
                 json.dumps(trusted_eval_result) if trusted_eval_result else None,
                 rebuilt_jar),
            )
        conn.commit()
        logger.info("Saved build: %s (reward=%.4f, level=L%d, trusted_reward=%.4f)",
                     coordinate, reward, level, trusted_reward)
        return True
    except Exception as e:
        logger.warning("Failed to save build: %s", e)
        return False
    finally:
        conn.close()
