"""Shared DB test helpers (Mark IX).

Two isolation patterns (spec §5 conventions):
  - rollback: one transaction per test, rolled back in tearDown. Safe on any database,
    as long as every assertion is scoped to the test's own scratch rows.
  - scratch-source + commit: rows that must be committed. Those classes are decorated
    with @requires_test_db, so they only ever run against a database whose name ends in
    `_test`. run-tests.sh gives each run a database of its own, named so (issue 0071).
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


def clear_tables(cur, tables, *, cascade: bool = False) -> None:
    """Empty these tables, as `TRUNCATE a, b, ...` would (v10.17), by DELETE.

    A TRUNCATE gives every table and index a new file, and Postgres syncs each new index to disk at once
    (an empty btree's build ends in an immediate fsync): a setUp truncating ~60 Mark X tables issued ~150 syncs,
    1-3 minutes a test while other agents' copies kept the disk busy (measured; test_entity_originals had seen
    ~25 s). A DELETE of a test's few rows writes no new file. Foreign keys are not checked while it runs
    (session_replication_role = replica, as TRUNCATE of the whole set checks none among them), so the order of
    `tables` is free; a role that may not set it (not a superuser) falls back to the TRUNCATE.
    `tables`: names, or one comma-separated string of them. `cascade`: as TRUNCATE ... CASCADE, every table whose
    foreign keys reach these (at any depth) is emptied too."""
    names = [t.strip() for t in (tables.split(",") if isinstance(tables, str) else tables) if t.strip()]
    if not names:
        return
    cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    row = cur.fetchone()
    if not (row and row[0]):
        cur.execute("TRUNCATE " + ", ".join(names) + (" CASCADE" if cascade else ""))
        return
    if cascade:
        cur.execute("""WITH RECURSIVE reach(rel) AS (
                         SELECT unnest(%s::regclass[])
                         UNION SELECT c.conrelid FROM pg_constraint c JOIN reach r ON c.confrelid = r.rel AND c.contype = 'f')
                       SELECT rel::regclass::text FROM reach""", (names,))
        names = list(dict.fromkeys(names + [r[0] for r in cur.fetchall()]))
    cur.execute("SET session_replication_role = replica")
    try:
        for name in names:
            cur.execute(f"DELETE FROM {name}")
    finally:
        try:
            cur.execute("SET session_replication_role = DEFAULT")
        except psycopg.Error:   # a failed DELETE's transaction: its rollback undoes the SET too
            pass


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
    """Remove leftovers of earlier runs (posts and fetch state cascade, and their removals)."""
    cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s", (SCRATCH_PREFIX + "%",))
    cur.execute("DELETE FROM removed_sources WHERE handle_or_url LIKE %s", (SCRATCH_PREFIX + "%",))
