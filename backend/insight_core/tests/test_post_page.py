"""The post page knows what INSIGHT has: its story (issue 0055, "covered by" at the end of the
post).

On the database, one transaction per test, rolled back; assertions are scoped to the test's own
rows (the story job regroups every post it sees, and nothing of it is kept).
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_reader import FeedQuery, ReaderRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_db
from insight_core.utils.url_normalization import normalize_url

LONG = "x" * 200   # a text long enough to be a copy


@requires_db
class PostPageTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc)
        self.mark = uuid.uuid4().hex[:8]

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, name, **kwargs):
        source = insert_scratch_source(self.cur, in_main_digest=True, **kwargs)
        self.cur.execute("UPDATE sources SET settings = jsonb_build_object('display_name', %s::text) WHERE id = %s",
                         (name, source))
        return source

    def _post(self, source, *, url=None, site="site", hours_ago=1.0, title="A post", content="Body", html=None,
              content_hash=None, fetched_hours_ago=None):
        url = url or f"https://{site}-{self.mark}.test/{uuid.uuid4().hex}"
        fetched = self.now - timedelta(hours=fetched_hours_ago if fetched_hours_ago is not None else hours_ago)
        self.cur.execute(
            """INSERT INTO posts (source_id, url, normalized_url, url_host, title, content, content_html, content_hash,
                                  published_at, fetched_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (source, url, normalize_url(url), f"{site}-{self.mark}.test", title, content, html,
             content_hash or uuid.uuid4().hex, self.now - timedelta(hours=hours_ago), fetched),
        )
        return str(self.cur.fetchone()[0])

    # ---- 0055: the story on the post page -------------------------------------------------------

    def _launch(self):
        """A report, a copy of it on another site, and someone's own take, all linking one page."""
        page = f"https://launch-{self.mark}.test/2026/10/the-launch"
        link = f'<p><a href="{page}">read</a></p>'
        self.anthropic = self._source("Anthropic")
        self.channel = self._source("Канал")
        self.simon = self._source("Simon Willison")
        self.lab = self._post(self.anthropic, site="anthropic", hours_ago=5, title="Introducing the new model today",
                              content=LONG, html=link, content_hash="same-" + self.mark)
        self.copy = self._post(self.channel, site="channel", hours_ago=4, content=LONG, html=link,
                               content_hash="same-" + self.mark)
        self.take = self._post(self.simon, site="simon", hours_ago=3, title="My notes on the new model", html=link)
        while StoriesRepository().fill_missing_links(self.cur):
            pass
        StoriesService(db_url(), clock=lambda: self.now).regroup(self.cur, cutoff=None)

    def _story(self, post_id):
        return PostDetailService.story(self.cur, post_id)

    def test_the_lead_carries_the_feed_rows_story(self):
        self._launch()
        story = self._story(self.lab)
        self.assertEqual((story["id"], story["voices"], story["first"]), (self.lab, 2, self.lab))
        self.assertEqual([s["name"] for s in story["sources"]], ["Anthropic", "Канал", "Simon Willison"])
        self.assertEqual([(p["id"], p["role"]) for p in story["posts"]], [(self.copy, "share"), (self.take, "report")])
        items, _ = ReaderRepository(unread_window_days=None).list_posts(self.cur, FeedQuery(limit=100), now=self.now)
        [row] = [i for i in items if i["id"] in (self.lab, self.copy, self.take)]
        self.assertEqual(row["story"], story, "the same object the feed row gets")

    def test_a_member_sees_the_others_and_who_was_first(self):
        self._launch()
        story = self._story(self.take)
        self.assertEqual([(p["id"], p["role"]) for p in story["posts"]], [(self.lab, "report"), (self.copy, "share")])
        self.assertEqual(story["first"], self.lab)

    def test_a_share_sees_the_reports(self):
        self._launch()
        story = self._story(self.copy)
        self.assertEqual([(p["id"], p["role"]) for p in story["posts"]], [(self.lab, "report"), (self.take, "report")])
        self.assertEqual(story["first"], self.lab)

    def test_read_posts_say_so(self):
        self._launch()
        ReaderRepository().set_read(self.cur, [self.copy], True)   # a share: it reads no other post
        story = self._story(self.lab)
        self.assertEqual([p["read_at"] is not None for p in story["posts"]], [True, False])

    def test_a_post_in_no_story(self):
        self._launch()
        alone = self._post(self.simon, site="simon", title="Something else")
        self.assertIsNone(self._story(alone))

    def test_copies_of_one_voice_are_not_covered_by(self):
        source = self._source("One voice")
        a = self._post(source, hours_ago=2)
        b = self._post(source, hours_ago=1)
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, now(), 1)", (a,))
        self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, 'report', 'v'),"
                         " (%s, %s, 'share', 'v')", (a, a, b, a))
        self.assertIsNone(self._story(a))
        self.assertIsNone(self._story(b))


if __name__ == "__main__":
    unittest.main()
