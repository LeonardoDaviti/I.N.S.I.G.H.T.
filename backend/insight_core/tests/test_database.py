"""The database module: pooled connections, a statement timeout, the transaction scope.

Each test builds its own small Database on the test database and closes it.
"""
from __future__ import annotations

import os
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
            self.assertEqual(cur.fetchone()[0], "5min")

    def test_jit_is_off_for_pooled_connections(self):
        """Measured on the server's data: JIT compiling cost ~300 ms of the Sources list."""
        database = self.make()
        with database.connection() as conn, conn.cursor() as cur:
            cur.execute("SHOW jit")
            self.assertEqual(cur.fetchone()[0], "off")

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


def _show(database: Database, *names: str) -> tuple:
    with database.connection() as conn, conn.cursor() as cur:
        out = []
        for name in names:
            cur.execute(f"SHOW {name}")
            out.append(cur.fetchone()[0])
        return tuple(out)


def _hold_lock_and_sleep(url: str, key: int) -> None:
    """A job's process: an advisory lock in a transaction, then a statement that runs on (killed meanwhile)."""
    database = Database(url, min_size=1, max_size=1)
    with database.transaction() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        cur.execute("SELECT pg_sleep(120)")


@requires_db
class RoleTimeoutTests(unittest.TestCase):
    """Issue 0188: the jobs' and the API's timeouts, set where connections are made."""

    def setUp(self):
        saved = {k: os.environ.get(k) for k in (db.ROLE_ENV, "INSIGHT_DB_CLIENT_CHECK_MS")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)

    def make(self, **kwargs) -> Database:
        database = Database(db_url(), min_size=1, max_size=1, **kwargs)
        self.addCleanup(database.close)
        return database

    def test_a_job_s_statements_end_before_its_process_is_killed(self):
        db.use_role("jobs")
        timeout, idle, check = _show(self.make(), "statement_timeout", "idle_in_transaction_session_timeout",
                                     "client_connection_check_interval")
        self.assertEqual((timeout, idle, check), ("14min", "16min", "10s"))
        from insight_core.markx import jobs
        self.assertLess(db.JOBS_STATEMENT_TIMEOUT_MS / 1000, jobs.HARD_LIMIT)
        self.assertGreater(db.JOBS_IDLE_IN_TRANSACTION_MS / 1000, jobs.HARD_LIMIT)

    def test_the_api_s_idle_transactions_end_and_unset_is_as_before(self):
        db.use_role("api")
        self.assertEqual(_show(self.make(), "statement_timeout", "idle_in_transaction_session_timeout"),
                         ("5min", "2min"))
        os.environ.pop(db.ROLE_ENV)
        self.assertEqual(_show(self.make(), "statement_timeout", "idle_in_transaction_session_timeout"),
                         ("5min", "0"))

    def test_a_request_s_statements_get_30_s_and_its_background_work_the_default(self):
        import asyncio

        database = self.make()
        seen = {}

        async def app(scope, receive, send):        # a response, then a background task (as Starlette runs one)
            seen["request"] = _show(database, "statement_timeout")[0]
            with db.long_statements():
                seen["long"] = _show(database, "statement_timeout")[0]
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
            seen["background"] = _show(database, "statement_timeout")[0]

        async def send(message):
            return None
        asyncio.run(db.RequestTimeouts(app)({"type": "http"}, None, send))
        self.assertEqual(seen, {"request": "30s", "long": "5min", "background": "5min"})
        self.assertEqual(_show(database, "statement_timeout")[0], "5min")      # outside any request

    def test_a_killed_job_s_statement_ends_and_its_locks_are_freed(self):
        import multiprocessing
        import time

        db.use_role("jobs")
        os.environ["INSIGHT_DB_CLIENT_CHECK_MS"] = "500"
        key = 7_188_000 + os.getpid() % 1000
        process = multiprocessing.get_context("spawn").Process(target=_hold_lock_and_sleep, args=(db_url(), key))
        process.start()
        self.addCleanup(process.join, 5)
        with psycopg.connect(db_url(), autocommit=True) as watch:
            def held() -> bool:
                return bool(watch.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s",
                                          (key,)).fetchone()[0])
            deadline = time.monotonic() + 20
            while not held() and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertTrue(held(), "the job took its lock")
            process.kill()                      # as at HARD_LIMIT, or by the kernel's OOM killer
            deadline = time.monotonic() + 10
            while held() and time.monotonic() < deadline:
                time.sleep(0.2)
            self.assertFalse(held(), "the killed job's statement ended and its lock is free")


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
