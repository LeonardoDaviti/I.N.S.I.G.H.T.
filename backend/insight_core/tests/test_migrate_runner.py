import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.migrate import MIGRATION_LOCK_KEY, acquire_migration_lock, apply_one
from insight_core.tests._db import insert_scratch_source, requires_test_db

MIGRATIONS_DIR = BACKEND_DIR / "insight_core" / "db" / "migrations"


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class MigrationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(DATABASE_URL)
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT 1 FROM schema_migrations LIMIT 1")

        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False)
        self.tmp.write("SELECT 1;")
        self.tmp.flush()
        self.tmp.close()
        self.version = Path(self.tmp.name).name

    def tearDown(self):
        try:
            self.cur.execute("DELETE FROM schema_migrations WHERE version = %s", (self.version,))
            self.conn.commit()
        finally:
            self.conn.close()
            Path(self.tmp.name).unlink(missing_ok=True)

    def test_apply_one_is_idempotent_for_recording(self):
        first = apply_one(self.cur, Path(self.tmp.name), self.version)
        self.assertTrue(first)

        second = apply_one(self.cur, Path(self.tmp.name), self.version)
        self.assertFalse(second)

        self.cur.execute("SELECT count(*) FROM schema_migrations WHERE version = %s", (self.version,))
        self.assertEqual(self.cur.fetchone()[0], 1)


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class FetchScheduleMigrationTests(unittest.TestCase):
    """0019: cadence columns, the source_fetch_state table, the JSONB backfill, the lock."""

    def test_fetch_schedule_schema_exists(self):
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sources' AND column_name = ANY(%s)",
                (["mean_gap_seconds", "cadence_sample_size", "cadence_tier",
                  "cadence_computed_at", "fetch_interval_hours_override"],),
            )
            self.assertEqual(len(cur.fetchall()), 5)
            cur.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'source_fetch_state'"
            )
            self.assertEqual(cur.fetchone()[0], 1)

    def test_migration_lock_is_taken(self):
        holder = psycopg.connect(DATABASE_URL)
        probe = psycopg.connect(DATABASE_URL, autocommit=True)
        try:
            with holder.cursor() as cur:
                acquire_migration_lock(cur)
                self.assertFalse(
                    probe.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                                  (MIGRATION_LOCK_KEY,)).fetchone()[0],
                    "a second migrator must not get the lock while the first transaction is open",
                )
            holder.rollback()
            self.assertTrue(
                probe.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                              (MIGRATION_LOCK_KEY,)).fetchone()[0],
                "the xact lock must end with the transaction",
            )
        finally:
            holder.close()
            probe.close()

    @requires_test_db
    def test_0019_backfill(self):
        """Malformed Mark VIII JSONB must backfill to NULL/0, never abort the migration."""
        sql = (MIGRATIONS_DIR / "0019_fetch_schedule.sql").read_text(encoding="utf-8")
        t0, t1, t2 = "2026-09-01T10:00:00+00:00", "2026-09-02T10:00:00+00:00", "2026-09-03T10:00:00+00:00"
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            healthy = insert_scratch_source(cur, settings_json=json.dumps({
                "display_name": "keep me",
                "ops": {"last_status": "healthy", "last_checked_at": t1, "last_success_at": t1,
                        "last_trigger": "scheduler", "last_fetched_posts": 7},
                "ingest_backoff": {"consecutive_failures": 0, "next_retry_at": None},
            }))
            empty = insert_scratch_source(cur, settings_json=json.dumps({
                "ops": {"last_status": "empty", "last_checked_at": t2, "last_success_at": t0},
            }))
            running = insert_scratch_source(cur, settings_json=json.dumps({
                "ops": {"last_status": "running", "last_checked_at": t1},
            }))
            broken = insert_scratch_source(cur, settings_json=json.dumps({
                "ops": {"last_status": "error", "last_message": "boom", "last_error_at": t2},
                "ingest_backoff": {"consecutive_failures": "x", "next_retry_at": "not-a-date"},
            }))
            ids = [healthy, empty, running, broken]
            cur.execute("DELETE FROM source_fetch_state WHERE source_id = ANY(%s::uuid[])", (ids,))

            cur.execute(sql)

            def snapshot():
                cur.execute(
                    "SELECT source_id::text, last_attempt_at, last_success_at, last_outcome, "
                    "last_trigger, last_fetched_posts, last_error, last_error_at, "
                    "consecutive_failures, next_retry_at "
                    "FROM source_fetch_state WHERE source_id = ANY(%s::uuid[])",
                    (ids,),
                )
                return {r[0]: r[1:] for r in cur.fetchall()}

            rows = snapshot()
            self.assertEqual(set(rows), set(ids))
            ts = lambda v: datetime.fromisoformat(v)  # noqa: E731

            h = rows[healthy]
            self.assertEqual(h[0], ts(t1))
            self.assertEqual(h[1], ts(t1))
            self.assertEqual(h[2], "healthy")
            self.assertEqual(h[3], "scheduler")
            self.assertEqual(h[4], 7)
            self.assertEqual(h[7], 0)

            self.assertEqual(rows[empty][1], ts(t2), "an empty last check is the newer success")
            self.assertEqual(rows[empty][2], "empty")

            self.assertIsNone(rows[running][2], "out-of-set statuses are normalised to NULL")

            b = rows[broken]
            self.assertEqual(b[2], "error")
            self.assertEqual(b[5], "boom")
            self.assertEqual(b[6], ts(t2))
            self.assertEqual(b[7], 0, "a malformed failure count backfills to 0")
            self.assertIsNone(b[8], "a malformed retry time backfills to NULL")

            cur.execute("SELECT settings FROM sources WHERE id = ANY(%s::uuid[])", (ids,))
            for (settings,) in cur.fetchall():
                self.assertNotIn("ops", settings)
                self.assertNotIn("ingest_backoff", settings)
            cur.execute("SELECT settings->>'display_name' FROM sources WHERE id = %s", (healthy,))
            self.assertEqual(cur.fetchone()[0], "keep me", "other settings keys survive")

            cur.execute(sql)
            self.assertEqual(snapshot(), rows, "0019 must be idempotent")
        finally:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    unittest.main()
