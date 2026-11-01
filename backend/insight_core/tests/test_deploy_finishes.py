"""A deploy that finishes by itself (issue 0069).

- The background fills (the search refill, the link reading) take their rows `FOR UPDATE SKIP LOCKED`.
  While another worker holds rows, a batch comes back empty: each fill waits and goes on until no post
  is pending, instead of stopping there (the rehearsal's run 3 left 311 posts un-indexed).
- The stories setting records the rules version the stories were grouped by: when the code's differs,
  the next story run is full, so a rule change reaches the frozen stories too.

Both commit (the fills run their own transactions), so they run only on a `_test` database.
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db import database
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.services.reader_service import ReaderService
from insight_core.services.stories_service import SETTINGS_KEY, StoriesService, rules_stamp
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db

HELD_SECONDS = 0.5


@requires_test_db
class FillsFinishTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            source = insert_scratch_source(cur)
            cur.execute(
                """INSERT INTO posts (source_id, url, normalized_url, title, content, content_html)
                   SELECT %s, u, u, 'A post', 'Some words', '<p><a href="https://elsewhere.test/a/page">a page</a></p>'
                   FROM (SELECT 'https://fills-' || gen_random_uuid() || '.test/p' AS u FROM generate_series(1, 6)) s
                   RETURNING id""",
                (source,),
            )
            self.posts = [str(r[0]) for r in cur.fetchall()]
            # As a deploy leaves them: indexed by an older rule, their links never read.
            cur.execute("UPDATE posts SET search_version = NULL, links_scanned_at = NULL WHERE id = ANY(%s::uuid[])",
                        (self.posts,))
        self.addCleanup(self._clean)
        patch = mock.patch.object(database, "LOCKED_WAIT_SECONDS", 0.05)
        patch.start()
        self.addCleanup(patch.stop)

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)

    def _pending(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("""SELECT count(*) FILTER (WHERE search_version IS DISTINCT FROM search_vector_version()),
                                  count(*) FILTER (WHERE links_scanned_at IS NULL)
                           FROM posts WHERE id = ANY(%s::uuid[])""", (self.posts,))
            return cur.fetchone()

    def _while_another_worker_holds_them(self, fill):
        """Run `fill` while another transaction holds every one of the posts, as the other fill
        holds its batch, and let them go after HELD_SECONDS. Returns what `fill` returned."""
        result = {}
        with psycopg.connect(db_url()) as other, other.cursor() as other_cur:
            other_cur.execute("SELECT id FROM posts WHERE id = ANY(%s::uuid[]) FOR UPDATE", (self.posts,))
            worker = threading.Thread(target=lambda: result.update(filled=fill()))
            worker.start()
            time.sleep(HELD_SECONDS)
            self.assertTrue(worker.is_alive(), "it waits while the posts are held, rather than stopping")
            other.rollback()
        worker.join(timeout=30)
        self.assertFalse(worker.is_alive())
        return result["filled"]

    def test_the_search_refill_waits_for_held_rows_and_leaves_none_pending(self):
        reader = ReaderService(db_url())
        with psycopg.connect(db_url()) as other, other.cursor() as other_cur:
            other_cur.execute("SELECT id FROM posts WHERE id = ANY(%s::uuid[]) FOR UPDATE", (self.posts,))
            with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
                self.assertEqual(reader.search_repo.fill_missing_vectors(cur), 0,
                                 "a batch finds only held rows: the case that stopped the refill")
                self.assertTrue(reader.search_repo.missing_vectors(cur), "while they are pending")
        self.assertGreaterEqual(self._while_another_worker_holds_them(reader.fill_search_vectors), len(self.posts))
        self.assertEqual(self._pending()[0], 0)

    def test_the_link_reading_waits_for_held_rows_and_leaves_none_pending(self):
        stories = StoriesService(db_url())
        self.assertGreaterEqual(self._while_another_worker_holds_them(stories.fill_links), len(self.posts))
        self.assertEqual(self._pending()[1], 0)

    def test_both_fills_over_the_same_rows_leave_none_pending(self):
        reader, stories = ReaderService(db_url()), StoriesService(db_url())
        workers = [threading.Thread(target=fill) for fill in (reader.fill_search_vectors, stories.fill_links)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertEqual(self._pending(), (0, 0))

    def test_with_nothing_pending_a_fill_stops_at_once(self):
        ReaderService(db_url()).fill_search_vectors()
        started = time.monotonic()
        self.assertEqual(ReaderService(db_url()).fill_search_vectors(), 0)
        self.assertLess(time.monotonic() - started, 1)


@requires_test_db
class RulesVersionTests(unittest.TestCase):
    """The story job's choice of a full or a windowed run, from the stories setting (its regroup
    stubbed: what it groups is the other suites')."""

    def setUp(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            kept = SystemSettingsRepository.get(cur, SETTINGS_KEY)
        self.addCleanup(self._restore, kept[0] if kept else None)
        self.service = StoriesService(db_url())
        self.cutoffs = []
        for name, value in (("fill_links", lambda: 0), ("fill_discover_addresses", lambda: 0),
                            ("regroup", lambda cur, cutoff: self.cutoffs.append(cutoff) or {})):
            patch = mock.patch.object(self.service, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def _restore(self, value):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            if value is None:
                cur.execute("DELETE FROM system_settings WHERE key = %s", (SETTINGS_KEY,))
            else:
                SystemSettingsRepository.upsert(cur, SETTINGS_KEY, value)

    def _setting(self, value):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            SystemSettingsRepository.upsert(cur, SETTINGS_KEY, value)

    def test_stories_grouped_by_other_rules_are_all_regrouped(self):
        self._setting({"computed_at": "2026-10-31T12:44:20+00:00", "full": True, "full_at": "2026-10-31T12:44:20+00:00"})
        summary = self.service.recompute()
        self.assertTrue(summary["full"], "a setting without a rules version: a full run")
        self.assertEqual(self.cutoffs, [None])
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertEqual(SystemSettingsRepository.get(cur, SETTINGS_KEY)[0]["rules"], rules_stamp())

        self.assertFalse(self.service.recompute()["full"], "the same rules: the window only")
        self.assertIsNotNone(self.cutoffs[-1])

        self._setting({"computed_at": "2026-10-31T12:44:20+00:00", "full": False, "rules": "older rules"})
        self.assertTrue(self.service.recompute()["full"], "other rules: a full run")
        self.assertEqual(self.cutoffs[-1], None)


if __name__ == "__main__":
    unittest.main()
