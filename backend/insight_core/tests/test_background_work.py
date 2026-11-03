"""Background work (issue 0062): the read-only block of Sources -> Ingestion -> overview.

Each state the block shows: stories never run, running, done; the search index up to date or
re-indexing; links all read or being read. On the database in one transaction per test, rolled
back (the stories setting and the lock are the real ones, so a test changes them only inside its
transaction); the lock is held from a second connection, as the story job holds it.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_background import background_work
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.services.stories_service import LOCK_KEY, SETTINGS_KEY
from insight_core.tests._db import db_url, insert_scratch_source, requires_db, requires_test_db

SUMMARY = {"computed_at": "2026-10-31T10:00:00+00:00", "full": False, "links_filled": 0, "posts": 5018,
           "stories": 86, "changed": 0, "boilerplate_changed": 0, "names": 31, "news": 90, "news_changed": 6,
           "classics": 175, "classics_changed": 0, "seconds": 4.77, "full_at": None}


def work(cur):
    return background_work(cur, stories_key=SETTINGS_KEY, stories_lock=LOCK_KEY)


@requires_db
class BackgroundWorkTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)

    def _post(self, source):
        url = f"https://bg-{uuid.uuid4().hex}.test/p"
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content) "
                         "VALUES (%s, %s, %s, 'A title', 'Some words') RETURNING id", (source, url, url))
        return self.cur.fetchone()[0]

    # ---- stories ---------------------------------------------------------------------------

    def test_stories_never_run(self):
        self.cur.execute("DELETE FROM system_settings WHERE key = %s", (SETTINGS_KEY,))
        self.assertEqual(work(self.cur)["stories"], {"running": False, "last_run": None})

    def test_stories_done(self):
        SystemSettingsRepository.upsert(self.cur, SETTINGS_KEY, SUMMARY)
        self.assertEqual(work(self.cur)["stories"], {"running": False, "last_run": {
            "computed_at": SUMMARY["computed_at"], "seconds": 4.77, "full": False, "posts": 5018, "stories": 86,
            "news": 90, "classics": 175, "links_filled": 0, "rebuild": None}})

    def test_stories_running_while_a_run_holds_the_lock(self):
        SystemSettingsRepository.upsert(self.cur, SETTINGS_KEY, SUMMARY)
        with psycopg.connect(db_url()) as job, job.cursor() as job_cur:
            job_cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
            self.assertTrue(job_cur.fetchone()[0])
            stories = work(self.cur)["stories"]
            self.assertTrue(stories["running"])
            self.assertEqual(stories["last_run"]["stories"], 86, "the last run still shows while one runs")
            job.rollback()
        self.assertFalse(work(self.cur)["stories"]["running"], "the lock ends with the run")

    def test_another_advisory_lock_is_no_story_run(self):
        with psycopg.connect(db_url()) as other, other.cursor() as other_cur:
            other_cur.execute("SELECT pg_advisory_xact_lock(hashtext('insight.something-else'))")
            other_cur.execute("SELECT pg_advisory_xact_lock(-1)")
            self.assertFalse(work(self.cur)["stories"]["running"])

    # ---- search and links ------------------------------------------------------------------

    def test_search_reindexing_then_up_to_date(self):
        source = insert_scratch_source(self.cur)
        post = self._post(source)
        before = work(self.cur)["search"]
        self.cur.execute("SELECT search_vector, search_version FROM posts WHERE id = %s", (post,))
        vector, version = self.cur.fetchone()
        self.cur.execute("UPDATE posts SET search_version = 0 WHERE id = %s", (post,))   # an older rule
        after = work(self.cur)["search"]
        self.assertEqual((after["total"], after["pending"]), (before["total"], before["pending"] + 1))
        self.cur.execute("UPDATE posts SET search_vector = NULL WHERE id = %s", (post,))   # stored before search
        self.assertEqual(work(self.cur)["search"]["pending"], before["pending"] + 1)
        self.cur.execute("UPDATE posts SET search_vector = %s, search_version = %s WHERE id = %s",
                         (vector, version, post))   # what the fill writes
        self.assertEqual(work(self.cur)["search"], before)

    def test_links_reading_then_all_read(self):
        source = insert_scratch_source(self.cur)
        self.cur.execute("UPDATE posts SET links_scanned_at = now() WHERE links_scanned_at IS NULL")
        self.assertEqual(work(self.cur)["links"]["pending"], 0, "all read")
        post = self._post(source)   # stored and not read yet (0050's backfill)
        links = work(self.cur)["links"]
        self.assertEqual(links["pending"], 1)
        self.cur.execute("UPDATE posts SET links_scanned_at = now() WHERE id = %s", (post,))
        self.assertEqual(work(self.cur)["links"], {"total": links["total"], "pending": 0})


@requires_test_db
class BackgroundWorkRouteTests(unittest.TestCase):
    """GET /api/operations/background over ASGI: read only, the three parts."""

    def setUp(self):
        import main
        from insight_core.services import registry
        from insight_core.tests._asgi import call

        self.app, self.call = main.app, call
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)

    def test_the_route(self):
        status, _, body = self.call(self.app, "GET", "/api/operations/background")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"success", "stories", "search", "links"})
        self.assertEqual(set(body["stories"]), {"running", "last_run"})
        self.assertEqual(set(body["search"]), {"total", "pending"})
        self.assertEqual(self.call(self.app, "POST", "/api/operations/background")[0], 405, "nothing to control")


if __name__ == "__main__":
    unittest.main()
