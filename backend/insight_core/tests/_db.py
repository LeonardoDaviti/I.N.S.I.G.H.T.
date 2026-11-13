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
    """Empty these tables, as `TRUNCATE a, b, ...` would (v10.17): a TRUNCATE where files are not synced, else DELETEs.

    A TRUNCATE gives every table and index a new file, and Postgres syncs each new index to disk at once
    (an empty btree's build ends in an immediate fsync): a setUp truncating ~60 Mark X tables issued ~150 syncs,
    11-48 s a test while other agents' copies kept the disk busy (measured; test_entity_originals had seen ~25 s).
    A DELETE of a test's few rows writes no new file. The tables are emptied children first (their foreign keys among
    the set, read from pg_constraint), with every trigger firing as it does in the product: the kept counts of 0132
    follow a DELETE as they follow a TRUNCATE (a delete with triggers off left them wrong). Tables in a cycle of keys,
    and the tables with an HNSW index (a DELETE leaves its rows in the graph until a vacuum, and an index scan that
    meets them returns fewer live neighbours: test_markx_storage's nearest lost one), are truncated.
    `tables`: names, or one comma-separated string of them. `cascade`: as TRUNCATE ... CASCADE, every table whose
    foreign keys reach these (at any depth) is emptied too."""
    names = [t.strip() for t in (tables.split(",") if isinstance(tables, str) else tables) if t.strip()]
    if not names:
        return
    # Where Postgres does not sync files (the scratch server: fsync off) a TRUNCATE costs what a DELETE does (56 Mark X
    # tables: 0.09 s, measured) and is exactly what the tests were written against: a DELETE leaves the dead rows'
    # space, and where later rows land changes the order a scan returns them in (test_markx_units' NeverAVoice
    # compared News rows built over two worlds and differed after test_markx_pairing ran before it).
    cur.execute("SELECT current_setting('fsync') = 'off'")
    if cur.fetchone()[0]:
        cur.execute("TRUNCATE " + ", ".join(names) + (" CASCADE" if cascade else ""))
        return
    cur.execute("SELECT unnest(%s::regclass[])::text", (names,))
    names = list(dict.fromkeys(r[0] for r in cur.fetchall()))
    if cascade:
        cur.execute("""WITH RECURSIVE reach(rel) AS (
                         SELECT unnest(%s::regclass[])
                         UNION SELECT c.conrelid FROM pg_constraint c JOIN reach r ON c.confrelid = r.rel AND c.contype = 'f')
                       SELECT rel::regclass::text FROM reach""", (names,))
        names = list(dict.fromkeys(names + [r[0] for r in cur.fetchall()]))
    cur.execute("""SELECT DISTINCT i.indrelid::regclass::text FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
                     JOIN pg_am a ON a.oid = c.relam
                    WHERE a.amname = 'hnsw' AND i.indrelid = ANY(%s::regclass[])""", (names,))
    truncate = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint
                    WHERE contype = 'f' AND conrelid = ANY(%s::regclass[]) AND confrelid = ANY(%s::regclass[])
                      AND conrelid <> confrelid""", (names, names))
    children = {n: set() for n in names}     # parent -> the tables whose keys point at it
    for child, parent in cur.fetchall():
        children[parent].add(child)
    order, done = [], set()
    left = [n for n in names if n not in truncate]
    while left:
        ready = [n for n in left if not (children[n] - done - truncate)]
        if not ready:             # a cycle of keys: all of them truncated together, as before
            cur.execute("TRUNCATE " + ", ".join(names))
            return
        for n in ready:
            order.append(n)
            done.add(n)
        left = [n for n in left if n not in done]
    if truncate:
        cur.execute("TRUNCATE " + ", ".join(sorted(truncate)))
    for name in order:
        cur.execute(f"DELETE FROM {name}")


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
