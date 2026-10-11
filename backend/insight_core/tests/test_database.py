"""The database module: pooled connections, a statement timeout, the transaction scope.

Each test builds its own small Database on the test database and closes it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db import database as db
from insight_core.db.database import Database
from insight_core.tests._db import (
    db_url,
    delete_scratch_sources,
    requires_db,
    requires_test_db,
    scratch_handle,
)


@requires_db
class DatabaseTests(unittest.TestCase):
    def make(self, **kwargs) -> Database:
        database = Database(db_url(), **kwargs)
        self.addCleanup(database.close)
        return database

    def test_a_statement_past_the_timeout_is_cancelled(self):
        database = self.make(statement_timeout_ms=100)
        with self.assertRaises(psycopg.errors.QueryCanceled):
            with database.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT pg_sleep(2)")

    def test_every_connection_carries_the_default_timeout(self):
        database = self.make()
        with database.connection() as conn, conn.cursor() as cur:
            cur.execute("SHOW statement_timeout")
            self.assertEqual(cur.fetchone()[0], "1min")

    def test_the_pool_hands_back_a_usable_connection_after_an_error(self):
        database = self.make(min_size=1, max_size=1)
        with self.assertRaises(psycopg.errors.UndefinedTable):
            with database.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM no_such_table_here")
        with database.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_a_connection_the_server_dropped_is_replaced(self):
        database = self.make(min_size=1, max_size=1)
        with database.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            pid = cur.fetchone()[0]
        with psycopg.connect(db_url(), autocommit=True) as killer:
            killer.execute("SELECT pg_terminate_backend(%s)", (pid,))
        with database.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            self.assertNotEqual(cur.fetchone()[0], pid)

    def test_a_session_connection_is_not_pooled(self):
        database = self.make(min_size=1, max_size=1)
        with database.connection() as pooled, pooled.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            pooled_pid = cur.fetchone()[0]
            # The only pooled connection is in use; a session connection still opens.
            with database.session_connection(autocommit=True) as session:
                pid = session.execute("SELECT pg_backend_pid()").fetchone()[0]
                self.assertTrue(session.autocommit)
        self.assertNotEqual(pid, pooled_pid)

    def test_one_database_per_url(self):
        self.assertIs(db.database(db_url()), db.database(db_url()))


@requires_test_db
class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.database = Database(db_url(), max_size=2)
        self.addCleanup(self.database.close)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)

    def count(self, handle: str) -> int:
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM sources WHERE handle_or_url = %s", (handle,))
            return cur.fetchone()[0]

    def insert(self, cur, handle: str) -> None:
        cur.execute("INSERT INTO sources (platform, handle_or_url, enabled) VALUES ('rss', %s, false)",
                    (handle,))

    def test_a_transaction_commits_when_the_block_ends(self):
        handle = scratch_handle()
        with self.database.transaction() as cur:
            self.insert(cur, handle)
        self.assertEqual(self.count(handle), 1)

    def test_a_failed_transaction_rolls_back(self):
        handle = scratch_handle()
        with self.assertRaises(RuntimeError):
            with self.database.transaction() as cur:
                self.insert(cur, handle)
                raise RuntimeError("halfway")
        self.assertEqual(self.count(handle), 0)

    def test_a_failed_statement_rolls_back_the_whole_transaction(self):
        first = scratch_handle()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.database.transaction() as cur:
                self.insert(cur, first)
                self.insert(cur, first)
        self.assertEqual(self.count(first), 0)


if __name__ == "__main__":
    unittest.main()
