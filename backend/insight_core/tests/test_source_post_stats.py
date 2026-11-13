"""Each source's post statistics, kept (issue 0195, migration 0131, db/repo_post_stats.py).

Source health read six subqueries per source over posts on every request; they are kept now and read. The promise:
a read always equals the live statistics (the old subqueries), whoever wrote the posts and whether or not the refresh
ran since. One transaction per test, rolled back; scratch sources only."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.db import repo_post_stats as R
from insight_core.db.repo_fetch_state import OPENED_POST_SQL, FetchStateRepository
from insight_core.tests._db import db_url, insert_scratch_source, requires_db

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


@requires_db
class KeptPostStats(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.a = insert_scratch_source(self.cur)
        self.b = insert_scratch_source(self.cur)
        self.n = 0

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def post(self, source: str, *, fetched: datetime = NOW, published=None, metadata=None) -> str:
        self.n += 1
        self.cur.execute("INSERT INTO posts (source_id, url, published_at, fetched_at, metadata) "
                         "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id::text",
                         (source, f"https://test.invalid/0195/{source}/{self.n}", published, fetched,
                          json.dumps(metadata or {})))
        return self.cur.fetchone()[0]

    def live(self, source: str) -> dict:
        """The statistics as the old per-request subqueries read them."""
        names = list(R.COLUMNS)
        self.cur.execute(f"SELECT {', '.join(R.COLUMNS.values())} FROM sources s WHERE s.id = %s", (source,))
        return dict(zip(names, self.cur.fetchone()))

    def read(self, source: str) -> dict:
        self.cur.execute(f"SELECT * FROM ({R.stats_sql('WHERE s.id = %s')}) x", (source,))
        row = self.cur.fetchone()
        return dict(zip(list(R.COLUMNS), row[1:]))

    def logged(self, source: str) -> int:
        self.cur.execute("SELECT count(*) FROM source_post_stats_changes WHERE source_id = %s", (source,))
        return self.cur.fetchone()[0]

    def kept(self, source: str):
        self.cur.execute(f"SELECT {', '.join(R.COLUMNS)} FROM source_post_stats WHERE source_id = %s", (source,))
        row = self.cur.fetchone()
        return dict(zip(list(R.COLUMNS), row)) if row else None

    def world(self) -> None:
        self.post(self.a, fetched=NOW - 3 * H, published=NOW - 30 * 24 * H)
        self.post(self.a, fetched=NOW - 2 * H, metadata={"page_read": {"kept_images": 1}})
        self.post(self.a, fetched=NOW - H, metadata={"audience": "only_paid", "paywalled": True, "moved_to": "https://x.invalid/a"})
        self.post(self.b, fetched=NOW - 5 * H)

    def test_a_read_equals_the_live_statistics_before_and_after_the_refresh(self):
        self.world()
        self.assertEqual(self.read(self.a), self.live(self.a))   # changed: read live
        self.assertGreater(self.logged(self.a), 0)
        self.assertIsNotNone(R.refresh(self.cur))
        self.assertEqual(self.logged(self.a), 0)
        self.assertEqual(self.kept(self.a), self.live(self.a))   # kept, and read from what is kept
        self.assertEqual(self.read(self.a), self.live(self.a))
        self.assertEqual(self.read(self.a)["post_count"], 3)
        self.assertEqual(self.read(self.b)["post_count"], 1)

    def test_every_write_that_moves_a_statistic_is_logged_and_read_live_until_kept(self):
        self.world()
        R.refresh(self.cur)
        newest = self.post(self.a, fetched=NOW)                                       # insert
        self.assertEqual(self.read(self.a), self.live(self.a))
        self.assertEqual(self.read(self.a)["post_count"], 4)
        R.refresh(self.cur)
        self.cur.execute("UPDATE posts SET metadata = metadata || '{\"page_read\": {\"kept_images\": 9}}'::jsonb "
                         "WHERE id = %s", (newest,))                                   # a page read
        self.assertEqual(self.read(self.a)["page_reads"][0], {"kept_images": 9})
        R.refresh(self.cur)
        self.cur.execute("UPDATE posts SET source_id = %s WHERE id = %s", (self.b, newest))   # moved to b
        self.assertEqual((self.read(self.a)["post_count"], self.read(self.b)["post_count"]), (3, 2))
        self.assertEqual(self.read(self.a), self.live(self.a))
        self.assertEqual(self.read(self.b), self.live(self.b))
        R.refresh(self.cur)
        self.cur.execute("DELETE FROM posts WHERE id = %s", (newest,))                 # deleted
        self.assertEqual(self.read(self.b)["post_count"], 1)
        R.refresh(self.cur)
        self.assertEqual((self.kept(self.a), self.kept(self.b)), (self.live(self.a), self.live(self.b)))

    def test_a_write_that_moves_no_statistic_is_not_logged(self):
        self.world()
        R.refresh(self.cur)
        self.cur.execute("UPDATE posts SET links_scanned_at = now(), title = 'x', "
                         "metadata = metadata || '{\"other\": 1}'::jsonb WHERE source_id = %s", (self.a,))
        self.assertEqual(self.logged(self.a), 0)

    def test_a_source_never_kept_is_read_live(self):
        self.world()
        R.refresh(self.cur)
        fresh = insert_scratch_source(self.cur)
        self.assertIsNone(self.kept(fresh))
        self.assertEqual(self.read(fresh)["post_count"], 0)
        self.assertEqual(self.read(fresh)["page_reads"], [])

    def test_the_corpus_is_every_post(self):
        self.world()
        corpus = R.corpus(self.cur)
        self.cur.execute("SELECT count(*), max(COALESCE(published_at, fetched_at)), "
                         "min(COALESCE(published_at, fetched_at)), max(fetched_at) FROM posts")
        self.assertEqual(tuple(corpus.values()), self.cur.fetchone())
        R.refresh(self.cur)
        self.assertEqual(R.corpus(self.cur), corpus)

    def test_opened_posts_count_as_the_old_rule(self):
        ids = [self.post(self.a, fetched=NOW - i * H) for i in range(4)]
        self.cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')", (ids[0],))
        self.cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened')", (ids[0],))
        self.cur.execute("INSERT INTO post_reader_state (post_id, later_at) VALUES (%s, now())", (ids[1],))
        self.cur.execute("INSERT INTO post_reader_state (post_id, read_at) VALUES (%s, now())", (ids[2],))  # no open
        self.cur.execute(f"SELECT count(*) FROM posts p WHERE p.source_id = %s AND {OPENED_POST_SQL}", (self.a,))
        old_rule = self.cur.fetchone()[0]
        self.assertEqual(R.opened_counts(self.cur, [self.a]), {self.a: old_rule})
        (row,) = FetchStateRepository().load_schedule_view(self.cur, [self.a])
        self.assertEqual(row["opened_posts"], 2)


if __name__ == "__main__":
    unittest.main()
