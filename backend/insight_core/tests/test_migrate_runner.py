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
            self.assertEqual(b[7], 1, "an 'error' last status counts as at least one failure, "
                                      "even when the failure count is malformed")
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

    @requires_test_db
    def test_0022_repairs_error_rows_backfilled_with_no_failures(self):
        """Databases that ran the old 0019 have last_outcome='error' with 0 failures: count 1."""
        sql = (MIGRATIONS_DIR / "0022_fetch_state_error_failures.sql").read_text(encoding="utf-8")
        t1, t2 = datetime.fromisoformat("2026-09-02T10:00:00+00:00"), datetime.fromisoformat("2026-09-03T10:00:00+00:00")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            ids = {name: insert_scratch_source(cur) for name in
                   ("stale_error", "never_succeeded", "recovered", "counted", "healthy")}
            cur.execute("DELETE FROM source_fetch_state WHERE source_id = ANY(%s::uuid[])", (list(ids.values()),))
            rows = {
                "stale_error": ("error", t1, t2, 0, None),        # failed after its last success
                "never_succeeded": ("error", None, t2, 0, None),
                "recovered": ("error", t2, t1, 0, None),          # a success since the error
                "counted": ("error", t1, t2, 3, t2),              # already counted: untouched
                "healthy": ("healthy", t2, t1, 0, None),
            }
            for name, (outcome, success, error, failures, retry) in rows.items():
                cur.execute(
                    "INSERT INTO source_fetch_state (source_id, last_outcome, last_success_at, last_error_at, "
                    "consecutive_failures, next_retry_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (ids[name], outcome, success, error, failures, retry),
                )

            cur.execute(sql)
            cur.execute(sql)  # idempotent

            cur.execute("SELECT source_id::text, consecutive_failures, next_retry_at FROM source_fetch_state "
                        "WHERE source_id = ANY(%s::uuid[])", (list(ids.values()),))
            got = {sid: (n, retry) for sid, n, retry in cur.fetchall()}
            self.assertEqual(got[ids["stale_error"]], (1, None), "retry stays NULL: the next tick retries")
            self.assertEqual(got[ids["never_succeeded"]], (1, None))
            self.assertEqual(got[ids["recovered"]], (0, None))
            self.assertEqual(got[ids["counted"]], (3, t2))
            self.assertEqual(got[ids["healthy"]], (0, None))
        finally:
            conn.rollback()
            conn.close()


ARXIV_RSS = [
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.CL",
    "https://rss.arxiv.org/rss/cs.LG",
    "https://rss.arxiv.org/rss/physics.optics",
]


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class ReaderMigrationTests(unittest.TestCase):
    """0020 (read-state projection) and 0021 (arXiv out of the main digest)."""

    def test_reader_state_schema_exists(self):
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'post_reader_state'")
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)",
                (["posts_feed_order_idx", "posts_source_feed_order_idx", "post_reader_state_starred_idx"],),
            )
            self.assertEqual(len(cur.fetchall()), 3)

    @requires_test_db
    def test_0020_backfill_from_interactions(self):
        sql = (MIGRATIONS_DIR / "0020_reader_state.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            source = insert_scratch_source(cur)
            posts = []
            for n in range(3):
                cur.execute(
                    "INSERT INTO posts (source_id, url) VALUES (%s, %s) RETURNING id",
                    (source, f"https://test.invalid/mark-ix/post/{n}/{source}"),
                )
                posts.append(str(cur.fetchone()[0]))
            opened, starred, unstarred = posts
            t = lambda h: f"2026-10-0{h}T10:00:00+00:00"  # noqa: E731
            for post_id, kind, ts in [
                (opened, "opened", t(2)), (opened, "opened", t(1)), (opened, "reading_session", t(3)),
                (starred, "unfavorited", t(1)), (starred, "favorited", t(2)),
                (unstarred, "favorited", t(1)), (unstarred, "unfavorited", t(2)),
            ]:
                cur.execute(
                    "INSERT INTO post_interactions (post_id, interaction_type, created_at) VALUES (%s, %s, %s)",
                    (post_id, kind, ts),
                )
            cur.execute(sql)
            cur.execute(
                "SELECT post_id::text, read_at, starred_at FROM post_reader_state WHERE post_id = ANY(%s::uuid[])",
                (posts,),
            )
            rows = {r[0]: r[1:] for r in cur.fetchall()}
            self.assertEqual(rows[opened], (datetime.fromisoformat(t(1)), None), "read_at = first open")
            self.assertEqual(rows[starred], (None, datetime.fromisoformat(t(2))), "latest toggle was a favorite")
            self.assertEqual(rows[unstarred], (None, None), "latest toggle was an unfavorite")
            cur.execute(sql)  # idempotent
        finally:
            conn.rollback()
            conn.close()

    @requires_test_db
    def test_0021_arxiv_main_digest(self):
        sql = (MIGRATIONS_DIR / "0021_arxiv_out_of_main_digest.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            for url in ARXIV_RSS:
                cur.execute(
                    """
                    INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest)
                    VALUES ('rss', %s, true, true)
                    ON CONFLICT (platform, handle_or_url) DO UPDATE SET enabled = true, in_main_digest = true
                    """,
                    (url,),
                )
            other = insert_scratch_source(cur, enabled=True, in_main_digest=True)

            cur.execute(sql)

            cur.execute(
                "SELECT handle_or_url, enabled, in_main_digest FROM sources WHERE handle_or_url = ANY(%s)",
                (ARXIV_RSS,),
            )
            rows = cur.fetchall()
            self.assertEqual(len(rows), 4)
            for url, enabled, in_main_digest in rows:
                self.assertTrue(enabled, url)
                self.assertFalse(in_main_digest, url)
            cur.execute("SELECT enabled, in_main_digest FROM sources WHERE id = %s", (other,))
            self.assertEqual(cur.fetchone(), (True, True), "other sources are untouched")
        finally:
            conn.rollback()
            conn.close()


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class MediaUrlEntitiesMigrationTests(unittest.TestCase):
    """0023 decodes the HTML entities older ingests left in posts.media_urls."""

    @requires_test_db
    def test_0023_unescapes_media_urls(self):
        sql = (MIGRATIONS_DIR / "0023_media_url_entities.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            source = insert_scratch_source(cur)
            cases = {
                "amp": ["https://preview.redd.it/a.jpg?w=1&amp;s=x", "https://x.invalid/b.png"],
                "numeric": ["https://i0.wp.com/a.jpg?a=1&#038;b=2&#38;c=3"],
                "double": ["https://x.invalid/a.jpg?a=1&amp;#038;b=2"],
                "clean": ["https://x.invalid/a.jpg?a=1&b=2"],
                "mixed": ["https://x.invalid/a.jpg?a=1&amp;b=2", 7],
                "empty": [],
            }
            ids = {}
            for name, urls in cases.items():
                cur.execute("INSERT INTO posts (source_id, url, title, content, media_urls) "
                            "VALUES (%s, %s, 't', 'c', %s::jsonb) RETURNING id",
                            (source, f"https://test.invalid/mark-ix/0023/{name}", json.dumps(urls)))
                ids[name] = cur.fetchone()[0]

            cur.execute(sql)
            cur.execute(sql)  # idempotent

            cur.execute("SELECT id, media_urls FROM posts WHERE id = ANY(%s)", (list(ids.values()),))
            got = dict(cur.fetchall())
            self.assertEqual(got[ids["amp"]], ["https://preview.redd.it/a.jpg?w=1&s=x", "https://x.invalid/b.png"],
                             "order kept")
            self.assertEqual(got[ids["numeric"]], ["https://i0.wp.com/a.jpg?a=1&b=2&c=3"])
            self.assertEqual(got[ids["double"]], ["https://x.invalid/a.jpg?a=1&b=2"])
            self.assertEqual(got[ids["clean"]], cases["clean"])
            self.assertEqual(got[ids["mixed"]], ["https://x.invalid/a.jpg?a=1&b=2", 7], "non-strings survive as-is")
            self.assertEqual(got[ids["empty"]], [])
        finally:
            conn.rollback()
            conn.close()



@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class StalePostLimitMigrationTests(unittest.TestCase):
    """0029 drops the stored max_posts_per_fetch nothing shows or edits any more (issue 0029)."""

    @requires_test_db
    def test_0029_drops_stored_post_limits(self):
        sql = (MIGRATIONS_DIR / "0029_drop_stored_post_limits.sql").read_text(encoding="utf-8")
        conn = psycopg.connect(DATABASE_URL)
        try:
            cur = conn.cursor()
            stale = insert_scratch_source(cur, settings_json=json.dumps(
                {"max_posts_per_fetch": 3, "display_name": "Kept", "page_watch": {"prefix": "/news/"}}))
            plain = insert_scratch_source(cur, settings_json=json.dumps({"priority": 5}))
            cur.execute(sql)
            cur.execute(sql)  # idempotent
            cur.execute("SELECT id::text, settings FROM sources WHERE id = ANY(%s::uuid[])", ([stale, plain],))
            got = dict(cur.fetchall())
            self.assertEqual(got[stale], {"display_name": "Kept", "page_watch": {"prefix": "/news/"}})
            self.assertEqual(got[plain], {"priority": 5})
        finally:
            conn.rollback()
            conn.close()

if __name__ == "__main__":
    unittest.main()
