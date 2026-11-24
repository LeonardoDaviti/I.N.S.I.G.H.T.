"""v10.49.4: a stated date ahead of now is no publication date (Brave's research papers dated "Jul 1, 2027", their
venue's issue). The post is dated when first seen ("seen"), the stated date kept in metadata; a refetch keeps it so;
a date within a day's slack (time zones) stays. Synthetic posts on a _test database."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.db.repo_posts import STATED_DATE_KEY, PostsRepository, not_ahead, published_precision
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


class Pure(unittest.TestCase):
    def test_a_date_ahead_is_seen_and_kept_in_metadata(self):
        ahead = {"url": "https://example.org/paper", "date": datetime(2027, 7, 1, tzinfo=timezone.utc),
                 "metadata": {"adapter": "generic_rss"}}
        got = not_ahead(ahead, NOW)
        self.assertIsNone(got["date"])
        self.assertEqual(published_precision(got), "seen")
        self.assertEqual(got["metadata"], {"adapter": "generic_rss", STATED_DATE_KEY: "2027-07-01T00:00:00+00:00"})
        self.assertEqual(ahead["date"], datetime(2027, 7, 1, tzinfo=timezone.utc), "the draft itself unchanged")
        for date in (NOW + timedelta(hours=20), NOW - timedelta(days=400), datetime(2026, 11, 25, 6, 0)):  # naive: UTC
            with self.subTest(date=date):
                post = {"date": date}
                self.assertIs(not_ahead(post, NOW), post)
        self.assertIs(not_ahead({"date": None}, NOW)["date"], None)


class Stored(unittest.TestCase):
    def setUp(self):
        self.url = db_url()
        self.repo = PostsRepository(self.url)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = insert_scratch_source(cur)
            conn.commit()
        self.addCleanup(self._clean)

    def _clean(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _save(self, date):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            pid, _ = self.repo.upsert_post(cur, {"url": "https://example.org/research/paper/", "title": "A paper",
                                                 "content": "Abstract.", "date": date, "media_urls": [],
                                                 "categories": [], "metadata": {}}, self.source)
            cur.execute("""SELECT published_at, published_precision, metadata ->> %s, fetched_at FROM posts
                            WHERE id = %s""", (STATED_DATE_KEY, pid))
            row = cur.fetchone()
            conn.commit()
        return row

    def test_saved_and_refetched_a_date_ahead_never_dates_the_post(self):
        ahead = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=200)
        at, precision, stated, fetched = self._save(ahead)
        self.assertEqual(precision, "seen")
        self.assertLessEqual(at, datetime.now(timezone.utc) + timedelta(minutes=1))
        self.assertEqual(datetime.fromisoformat(stated), ahead)
        again = self._save(ahead)
        self.assertEqual(again[:3], (at, "seen", stated), "the feed's date again: the post stays dated when seen")
