"""A post its feed added late, with an earlier date (issue 0039, v10.13.13).

A live read's new post dated more than ADDED_LATE_SLACK before the source's previous successful
read was not in that read (every item a read returns is stored then): its feed added it after
INSIGHT last looked, so it sorts at when it was first seen (surfaced_at = fetched_at), like the
2-day rule's. Not on a source's first fetch, an archive's pages, a backlog page, or a page your
other sources linked before (0058). A source switched to a new address has no previous read.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import psycopg

    from insight_core.db.repo_fetch_state import FetchStateRepository
    from insight_core.db.repo_posts import BACKLOG_KEY, PostDraft, PostsRepository
    from insight_core.ingestion.ports import DbPostSaver
    from insight_core.utils.url_normalization import normalize_url
    from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
except ImportError:  # pragma: no cover - outside the backend image
    requires_test_db = unittest.skip("no database driver")


@requires_test_db
class AddedLateTests(unittest.TestCase):
    """save_batch commits: scratch sources, deleted in tearDown (posts and fetch state cascade)."""

    def setUp(self):
        self.repo = PostsRepository(db_url())
        self.conn = psycopg.connect(db_url())
        with self.conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = insert_scratch_source(cur)
            self.other = insert_scratch_source(cur)
            cur.execute("SELECT now()")
            self.now = cur.fetchone()[0]
        self.conn.commit()
        self.base = f"https://test.invalid/mark-ix-post/late/{uuid.uuid4().hex}/"

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            delete_scratch_sources(cur)
        self.conn.commit()
        self.conn.close()

    def read_before(self, at: Optional[datetime]) -> None:
        """The source's previous successful read (source_fetch_state.last_success_at)."""
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO source_fetch_state (source_id, last_success_at, updated_at) VALUES (%s, %s, now())
                           ON CONFLICT (source_id) DO UPDATE SET last_success_at = EXCLUDED.last_success_at""",
                        (self.source, at))
        self.conn.commit()

    def draft(self, slug: str, date: Optional[datetime], *, surface=False, **extra) -> PostDraft:
        return PostDraft(self.source, {"url": self.base + slug, "title": slug, "content": f"The {slug} post.",
                                       "date": date, "metadata": {}, **extra}, surface=surface)

    def save(self, *drafts: PostDraft, live=True):
        return self.repo.save_batch(self.conn, list(drafts), live=live)

    def placed(self, slug: str):
        """(surfaced_at, fetched_at, published_at) of a stored post."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT surfaced_at, fetched_at, published_at FROM posts WHERE url = %s", (self.base + slug,))
            found = cur.fetchone()
        self.conn.commit()
        return found

    # ------------------------------------------------------------------ the rule

    def test_a_post_dated_before_the_previous_read_sorts_at_when_it_was_first_seen(self):
        # The owner's case: read at 17:08 without the post dated 10:00; the next read stores it ~31 h after its date.
        self.read_before(self.now - timedelta(hours=24))
        self.save(self.draft("late", self.now - timedelta(hours=31)))
        surfaced, fetched, _ = self.placed("late")
        self.assertEqual(surfaced, fetched)

    def test_a_post_published_between_the_reads_keeps_its_date(self):
        self.read_before(self.now - timedelta(hours=6))
        self.save(self.draft("between", self.now - timedelta(hours=2)))
        self.assertIsNone(self.placed("between")[0])

    def test_within_the_slack_of_the_previous_read_keeps_its_date(self):
        self.read_before(self.now - timedelta(hours=6))
        self.save(self.draft("rounded", self.now - timedelta(hours=6, minutes=10)))
        self.assertIsNone(self.placed("rounded")[0])

    def test_a_first_fetch_is_backlog_never_new_to_you(self):
        self.save(self.draft("history", self.now - timedelta(hours=31)))     # no previous read
        self.assertIsNone(self.placed("history")[0])

    def test_an_archive_page_keeps_its_date(self):
        self.read_before(self.now - timedelta(hours=6))
        self.save(self.draft("archived", self.now - timedelta(days=30)), live=False)
        self.assertIsNone(self.placed("archived")[0])

    def test_a_backlog_page_keeps_its_date(self):
        self.read_before(self.now - timedelta(hours=6))
        self.save(self.draft("sitemap", self.now - timedelta(hours=31), **{BACKLOG_KEY: True}))
        self.assertIsNone(self.placed("sitemap")[0])

    def test_a_stored_post_read_again_is_not_moved(self):
        self.save(self.draft("known", self.now - timedelta(hours=31)))
        self.read_before(self.now - timedelta(hours=6))
        result = self.save(self.draft("known", self.now - timedelta(hours=31)))
        self.assertEqual(result.updated, 1)
        self.assertIsNone(self.placed("known")[0])

    def test_an_undated_post_is_left_to_its_own_rules(self):
        self.save(self.draft("first", self.now - timedelta(days=3)))   # the source's first fetch
        self.read_before(self.now - timedelta(hours=6))
        self.save(self.draft("undated", None))
        surfaced, fetched, published = self.placed("undated")
        self.assertEqual((surfaced, published), (None, None))   # a later fetch's undated post sorts at its fetch

    def test_known_news_keeps_its_date(self):
        # 0058: another source's post linked the page before it was first seen.
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO posts (source_id, url, title, content, published_at, fetched_at)
                           VALUES (%s, %s, 'Links', 'A link post', now(), now() - interval '1 hour') RETURNING id""",
                        (self.other, self.base + "links"))
            cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, 'test.invalid', 0)",
                        (cur.fetchone()[0], normalize_url(self.base + "linked")))
        self.conn.commit()
        self.read_before(self.now - timedelta(hours=24))
        self.save(self.draft("linked", self.now - timedelta(hours=31)))
        self.assertIsNone(self.placed("linked")[0])

    def test_the_two_day_rule_still_surfaces_a_page_based_sources_old_page(self):
        self.save(self.draft("page", self.now - timedelta(days=60), surface=True), live=False)
        surfaced, fetched, _ = self.placed("page")
        self.assertEqual(surfaced, fetched)
        # and a recent page of a page-based fetch with no previous read keeps its date
        self.save(self.draft("recent", self.now - timedelta(hours=31), surface=True), live=False)
        self.assertIsNone(self.placed("recent")[0])

    # ------------------------------------------------------------------ a daily-dated feed

    def test_a_daily_dated_feed_surfaces_only_what_the_previous_read_did_not_have(self):
        # Every item is stamped 00:00 of its day. The read at 06:00 had "morning"; the next read finds
        # "morning" again and "evening", both stamped 00:00 of that day.
        day = (self.now - timedelta(hours=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        self.save(self.draft("morning", day))                     # the 06:00 read (the source's first)
        self.read_before(day + timedelta(hours=6))
        self.save(self.draft("morning", day), self.draft("evening", day))
        self.assertIsNone(self.placed("morning")[0])               # it was in the 06:00 read
        surfaced, fetched, _ = self.placed("evening")
        self.assertEqual(surfaced, fetched)                         # it was not: added after 06:00

    def test_a_daily_dated_post_of_a_day_that_began_after_the_previous_read_keeps_its_date(self):
        day = (self.now - timedelta(hours=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        self.read_before(day - timedelta(hours=1))                # read at 23:00 the day before
        self.save(self.draft("today", day))
        self.assertIsNone(self.placed("today")[0])

    # ------------------------------------------------------------------ the runner's saver, a switched source

    def test_the_runners_saver_is_a_live_read(self):
        self.read_before(self.now - timedelta(hours=24))
        DbPostSaver(db_url(), self.repo).save([self.draft("live", self.now - timedelta(hours=31))])
        surfaced, fetched, _ = self.placed("live")
        self.assertEqual(surfaced, fetched)

    def test_a_source_switched_to_a_new_address_has_no_previous_read(self):
        self.read_before(self.now - timedelta(hours=24))
        state = FetchStateRepository()
        with self.conn.cursor() as cur:
            state.clear_failures(cur, self.source)                  # the same address: the read stands
            cur.execute("SELECT last_success_at FROM source_fetch_state WHERE source_id = %s", (self.source,))
            self.assertIsNotNone(cur.fetchone()[0])
            state.clear_failures(cur, self.source, new_address=True)
            cur.execute("SELECT last_success_at FROM source_fetch_state WHERE source_id = %s", (self.source,))
            self.assertIsNone(cur.fetchone()[0])
        self.conn.commit()
        self.save(self.draft("new-feed", self.now - timedelta(hours=31)))
        self.assertIsNone(self.placed("new-feed")[0])

    def test_the_feed_sorts_a_late_post_above_one_published_between_the_reads(self):
        self.read_before(self.now - timedelta(hours=6))
        self.save(self.draft("between", self.now - timedelta(hours=2)), self.draft("late", self.now - timedelta(hours=31)))
        with self.conn.cursor() as cur:
            cur.execute("""SELECT url FROM posts WHERE source_id = %s
                            ORDER BY COALESCE(surfaced_at, published_at, fetched_at) DESC""", (self.source,))
            order = [url.rsplit("/", 1)[1] for (url,) in cur.fetchall()]
        self.conn.commit()
        self.assertEqual(order, ["late", "between"])


if __name__ == "__main__":
    unittest.main()
