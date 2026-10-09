"""Shared DB test helpers (Mark IX).

Two isolation patterns (spec §5 conventions):
  - rollback: one transaction per test, rolled back in tearDown. Safe on any database,
    as long as every assertion is scoped to the test's own scratch rows.
  - scratch-source + commit: rows that must be committed. Those classes are decorated
    with @requires_test_db, so they only ever run against a database whose name ends in
    `_test` - run-tests.sh defaults to the live `insight` DB.
"""
from __future__ import annotations

import os
import unittest
import uuid

import psycopg
from psycopg.conninfo import conninfo_to_dict

SCRATCH_PREFIX = "https://test.invalid/mark-ix/"


def db_url() -> str | None:
    return os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


def is_test_database(url: str | None) -> bool:
    if not url:
        return False
    try:
        return str(conninfo_to_dict(url).get("dbname") or "").endswith("_test")
    except Exception:
        return False


def database_reachable() -> bool:
    url = db_url()
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=5):
            return True
    except Exception:
        return False


requires_db = unittest.skipUnless(database_reachable(), "database not reachable")

requires_test_db = unittest.skipUnless(
    is_test_database(db_url()),
    "commits rows: only runs against a database whose name ends in _test (set TEST_DATABASE_URL)",
)


def scratch_handle() -> str:
    return f"{SCRATCH_PREFIX}{uuid.uuid4().hex}"


def insert_scratch_source(cur, *, platform: str = "rss", settings_json: str = "{}",
                          enabled: bool = False, in_main_digest: bool = False) -> str:
    """A source no tick or feed can pick up by accident (disabled, out of the main digest)."""
    cur.execute(
        """
        INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings)
        VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id
        """,
        (platform, scratch_handle(), enabled, in_main_digest, settings_json),
    )
    return str(cur.fetchone()[0])


def delete_scratch_sources(cur) -> None:
    """Remove leftovers of earlier runs (posts and fetch state cascade)."""
    cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s", (SCRATCH_PREFIX + "%",))
