"""The incremental story job (issue 0072 A) and the date-only rule (0072 D).

After each change the job regroups only what the new or changed posts touch; a full run over the
same posts then changes nothing (the full rebuild is the oracle). The rules as pure functions; the
job on the database in one transaction per test, rolled back. The lab's row-by-row check of 30, 300
and 3,000 posts is scripts/story_identity.py.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import PostsRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests._stories import insert_post, insert_source, story_post
from insight_core.utils.story_rules import group, keys, story_times
from insight_core.utils.url_normalization import normalize_url

DAY = datetime(2026, 10, 29, tzinfo=timezone.utc)
post = partial(story_post, at=DAY)
CHANGED = ("changed", "edges_changed", "keys_changed", "news_changed", "classics_changed", "surges_changed")


class DateAloneTests(unittest.TestCase):
    """A date alone counts as that day's earliest timed post of its story, never 00:00 (0072 D)."""

    def test_a_date_alone_counts_as_the_days_first_timed_post(self):
        page = [("https://lab.test/blog/a-model-ships-today", None)]
        day_only = post("blog", "s1", links=page)                 # 00:00, a date alone
        timed = post("reddit", "s2", hours=14.2, links=page)
        later = post("tweet", "s3", hours=14.4, links=page)
        [story] = group([day_only, timed, later])
        self.assertEqual(story.first_at, DAY + timedelta(hours=14.2), "its start: the day's first timed post")
        self.assertEqual([p.id for p in story.posts], ["blog", "reddit", "tweet"], "as early as it: first at the tie")
        self.assertEqual(story_times([day_only])["blog"], DAY, "with no timed post that day: its date")

    def test_a_timed_midnight_is_still_a_date_alone_unless_read_so(self):
        self.assertTrue(post("a", "s1").date_only)
        self.assertFalse(post("a", "s1", date_alone=False).date_only, "as the post was read")
        self.assertFalse(post("a", "s1", hours=0.01).date_only)


class StableIdTests(unittest.TestCase):
    def test_a_story_keeps_the_id_of_its_post_stored_first(self):
        page = [("https://lab.test/blog/a-model-ships-today", None)]
        first = post("first", "s1", hours=5, links=page, stored_at=DAY + timedelta(hours=6))
        second = post("second", "s2", hours=6, links=page, stored_at=DAY + timedelta(hours=7))
        late = post("late", "s3", hours=1, links=page, stored_at=DAY + timedelta(hours=9))   # posted first, fetched last
        [before] = group([first, second])
        [after] = group([first, second, late])
        self.assertEqual((before.id, after.id), ("first", "first"))
        self.assertEqual(after.posts[0].id, "late", "the story starts at it all the same")

    def test_keys_are_what_a_post_joins_by(self):
        p = post("a", "s1", text_hash="h", title="Five words make a title key", url="https://lab.test/blog/one-post-here",
                 links=[("https://lab.test", None), ("https://other.test/2026/notes-on-the-launch", None)])
        self.assertEqual(keys(p), {"h:h", "t:five words make a title key", "u:https://lab.test/blog/one-post-here",
                                   "g:lab.test|one-post-here", "u:https://other.test/2026/notes-on-the-launch",
                                   "g:other.test|notes-on-the-launch|2026"}, "a home page no post is at is no key")


@requires_test_db
class IncrementalJobTests(unittest.TestCase):
    """Each test starts from a full run, changes posts, runs the incremental job, and a full run
    over the same posts then changes nothing."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mark = uuid.uuid4().hex[:8]
        self.service = StoriesService(db_url(), clock=lambda: self.now)
        self._fill()
        self.service.full_on(self.cur)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _fill(self):
        while StoriesRepository().fill_missing_links(self.cur):
            pass

    def _source(self, name, **kwargs):
        return insert_source(self.cur, f"{name} {self.mark}", in_main_digest=True, **kwargs)

    def _post(self, source, *, hours_ago=1.0, title=None, links=(), url=None, stored_hours_ago=None):
        url = url or f"https://{uuid.uuid4().hex[:10]}-{self.mark}.test/2026/{uuid.uuid4().hex}"
        html = "".join(f'<p><a href="{target}">read</a></p>' for target in links)
        pid = str(insert_post(self.cur, source, url, at=self.now - timedelta(hours=hours_ago), title=title or "A post",
                              content="Body", html=html, content_hash=uuid.uuid4().hex))
        if stored_hours_ago is not None:
            self.cur.execute("UPDATE posts SET created_at = %s WHERE id = %s",
                             (self.now - timedelta(hours=stored_hours_ago), pid))
        return pid

    def _page(self, name):
        return f"https://{name}-{self.mark}.test/2026/10/{name}-ships-a-model-today"

    def _story(self, pid):
        self.cur.execute("SELECT story_id FROM story_posts WHERE post_id = %s", (pid,))
        row = self.cur.fetchone()
        return str(row[0]) if row else None

    def _incremental(self):
        self._fill()
        return self.service.update(self.cur)

    def assert_same_as_full(self):
        rebuilt = self.service.full_on(self.cur)
        self.assertEqual({k: rebuilt[k] for k in CHANGED}, dict.fromkeys(CHANGED, 0),
                         "a full run over the same posts changes nothing")

    def test_a_new_post_joins_a_story(self):
        page = self._page("join")
        a, b = self._post(self._source("A"), links=[page]), self._post(self._source("B"), links=[page])
        self._incremental()
        c = self._post(self._source("C"), links=[page])
        done = self._incremental()
        self.assertEqual(self._story(c), self._story(a))
        self.assertEqual(self._story(b), self._story(a))
        self.assertLess(done["posts"], 50, "only what the new post touches")
        self.assert_same_as_full()

    def test_a_post_that_joins_two_stories_merges_them(self):
        title = f"A field guide to small models {self.mark}"
        page = self._page("merge")
        a, b = self._post(self._source("A"), title=title), self._post(self._source("B"), title=title)
        c, d = self._post(self._source("C"), links=[page]), self._post(self._source("D"), links=[page])
        self._incremental()
        self.assertNotEqual(self._story(a), self._story(c))
        e = self._post(self._source("E"), title=title, links=[page])
        self._incremental()
        self.assertEqual({self._story(p) for p in (a, b, c, d, e)}, {self._story(a)})
        self.assert_same_as_full()

    def test_a_changed_post_splits_its_story(self):
        title = f"Notes on a chain of copies today {self.mark}"
        a = self._post(self._source("A"), hours_ago=24 * 10, title=title)
        b = self._post(self._source("B"), hours_ago=24 * 5, title=title)
        c = self._post(self._source("C"), hours_ago=1, title=title)
        self._incremental()
        self.assertEqual({self._story(p) for p in (a, b, c)}, {self._story(a)}, "a chain: 5 days, then 5")
        self.cur.execute("UPDATE posts SET title = 'Something else entirely now' WHERE id = %s", (b,))
        self._incremental()
        self.assertEqual([self._story(p) for p in (a, b, c)], [None, None, None], "10 days apart: no story")
        self.assert_same_as_full()

    def test_a_removed_post_takes_its_join_with_it(self):
        page = self._page("removed")
        a, b = self._post(self._source("A"), links=[page]), self._post(self._source("B"), links=[page])
        self._incremental()
        self.assertIsNotNone(self._story(a))
        self.cur.execute("DELETE FROM posts WHERE id = %s", (b,))
        self._incremental()
        self.assertIsNone(self._story(a))
        self.assert_same_as_full()

    def _x(self, user):
        source = insert_scratch_source(self.cur, in_main_digest=True)
        self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s", (f"https://nitter.local/{user}/rss", source))
        return source

    def _tweet(self, source, user, n, title, *, minutes, html=None):
        return str(PostsRepository(db_url()).upsert_post(self.cur, {
            "url": f"https://nitter.local/{user}/status/{n}#m", "title": title, "content": title.split(": ", 1)[-1],
            "content_html": html or f"<p>{title}</p>", "date": self.now - timedelta(hours=3) + timedelta(minutes=minutes),
            "external_id": str(n)}, source)[0])

    def test_a_reply_to_itself_and_a_quote_join_a_tweet(self):
        n = 2115002476311241104 + int(self.mark, 16) % 10**6 * 10
        user, fan = f"writer{self.mark}", f"fan{self.mark}"
        writer = self._x(user)
        first = self._tweet(writer, user, n, "Thread on evaluation methods, part one of it", minutes=0)
        self._incremental()
        reply = self._tweet(writer, user, n + 1, f"R to @{user}: part two, with the numbers", minutes=5)
        self._incremental()
        self.assertEqual(self._story(reply), self._story(first), "a reply to itself continues the thread")
        quote = (f'<p>Great thread</p><blockquote><b>{user}</b>Thread<footer> — <cite><a href="https://nitter.local/'
                 f'{user}/status/{n}#m">x.com/{user}</a></cite></footer></blockquote>')
        quoting = self._tweet(self._x(fan), fan, n + 2, "Great thread", minutes=30, html=quote)
        self._incremental()
        self.assertEqual(self._story(quoting), self._story(first), "a quote joins the tweet it quotes")
        self.assert_same_as_full()

    def test_a_page_root_becomes_the_post_stored_at_it(self):
        host = f"press-{self.mark}.test"
        page = f"https://{host}/2026/10/the-press-release-on-models"
        a, b = self._post(self._source("A"), links=[page]), self._post(self._source("B"), links=[page])
        self._incremental()
        self.cur.execute("SELECT origin_url FROM stories WHERE id = %s", (self._story(a),))
        self.assertEqual(self.cur.fetchone()[0], normalize_url(page), "the page they link is the origin")
        press = self._source("Press", handle=f"https://{host}/feed")
        own = self._post(press, hours_ago=2, url=page)
        self._incremental()
        self.assertEqual({self._story(p) for p in (a, b, own)}, {self._story(a)})
        self.cur.execute("SELECT parent_id, parent_reason FROM story_posts WHERE post_id = %s", (own,))
        self.assertEqual(self.cur.fetchone(), (None, None), "the stored page is the root now")
        self.assert_same_as_full()

    def test_a_story_past_its_window_keeps_its_news_row(self):
        """Issue 0077: nothing is deleted. Past the 30 days the job writes, the row stays as it was,
        in the incremental job and a full run alike; a later change to its story leaves it too."""
        page = self._page("news")
        a = self._post(self._source("A"), links=[page])
        self._post(self._source("B"), links=[page])
        self._incremental()
        self.cur.execute("SELECT news_id::text FROM news_posts WHERE post_id = %s", (a,))
        held = self.cur.fetchone()
        self.assertIsNotNone(held, "in News")
        news = held[0]
        self.cur.execute("SELECT * FROM news_stories WHERE id = %s", (news,))
        row = self.cur.fetchone()
        self.now += timedelta(days=31)
        self.assertEqual(self._incremental().get("news_removed", 0), 0)
        self.cur.execute("SELECT news_id::text FROM news_posts WHERE post_id = %s", (a,))
        self.assertEqual(self.cur.fetchone(), (news,), "kept past the 30 days News writes")
        self.cur.execute("SELECT * FROM news_stories WHERE id = %s", (news,))
        self.assertEqual(self.cur.fetchone(), row, "as it was")
        self.assertIsNotNone(self._story(a), "still a story")
        self.assert_same_as_full()
        late = self._post(self._source("C"), hours_ago=24 * 31 - 1, links=[page])   # joins the old story
        self._incremental()
        self.assertEqual(self._story(late), self._story(a))
        self.cur.execute("SELECT news_id FROM news_posts WHERE post_id = %s", (late,))
        self.assertIsNone(self.cur.fetchone(), "the row before the window is not rewritten")
        self.cur.execute("SELECT * FROM news_stories WHERE id = %s", (news,))
        self.assertEqual(self.cur.fetchone(), row)
        self.assert_same_as_full()

    def test_a_row_leaves_the_window_whole(self):
        """Issue 0111: a row is in the window by its first post. When that post leaves, the row leaves as it
        was, all its posts in it; its second post never comes back leading a row of its own. The incremental
        job and a full run alike."""
        name = f"Zork{self.mark[:4]} 9"
        sources = [self._source(n, followed_days=90) for n in ("A", "B", "C")]
        first, second, third = (self._post(s, hours_ago=h, title=f"{name} {t}") for s, h, t in
                                zip(sources, (10, 7, 4), ("is out", "explained", "reviewed")))
        self._incremental()
        self.cur.execute("SELECT news_id::text, (SELECT count(*) FROM news_posts o WHERE o.news_id = np.news_id) "
                         "FROM news_posts np WHERE post_id = %s", (first,))
        self.assertEqual(self.cur.fetchone(), (first, 3), "one row of the three, by the name")
        self.now += timedelta(days=30, hours=-8.5)   # the window's edge between the first post and the second
        self._incremental()
        self.cur.execute("SELECT post_id::text, news_id::text FROM news_posts WHERE post_id = ANY(%s::uuid[])",
                         ([first, second, third],))
        self.assertEqual(dict(self.cur.fetchall()), dict.fromkeys((first, second, third), first), "whole, as it was")
        self.cur.execute("SELECT count(*) FROM news_stories WHERE id = ANY(%s::uuid[])", ([second, third],))
        self.assertEqual(self.cur.fetchone()[0], 0, "no row led by its second post")
        self.assert_same_as_full()

    def test_a_story_keeps_its_id_when_an_earlier_post_joins(self):
        page = self._page("stable")
        a = self._post(self._source("A"), hours_ago=2, links=[page], stored_hours_ago=1.5)
        b = self._post(self._source("B"), hours_ago=1, links=[page], stored_hours_ago=0.5)
        self._incremental()
        self.assertEqual(self._story(b), a)
        early = self._post(self._source("C"), hours_ago=10, links=[page])   # posted first, stored now
        self._incremental()
        self.assertEqual((self._story(early), self._story(a)), (a, a))
        self.cur.execute("SELECT first_at FROM stories WHERE id = %s", (a,))
        self.assertEqual(self.cur.fetchone()[0], self.now - timedelta(hours=10), "it starts at the earlier post")
        self.assert_same_as_full()

    def _relink(self, pid, links):
        html = "".join(f'<p><a href="{target}">read</a></p>' for target in links) or "<p>Body</p>"
        self.cur.execute("UPDATE posts SET content_html = %s, links_scanned_at = NULL WHERE id = %s", (html, pid))

    def assert_every_story_row_is_whole(self):
        """Issue 0110: every story_posts and story_mentions row names a stored story."""
        self.cur.execute("SELECT count(*) FROM story_posts sp LEFT JOIN stories s ON s.id = sp.story_id WHERE s.id IS NULL")
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.cur.execute("SELECT count(*) FROM story_mentions m LEFT JOIN stories s ON s.id = m.story_id WHERE s.id IS NULL")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_a_roundup_listing_a_page_its_story_left_mentions_nothing(self):
        """Issue 0110 (the server's v9.17 rebuild failed on it): a page is outside the scope's stories
        once the posts joined through it stop linking it, and a roundup of the same batch lists it. Its
        story was read from the stored link edges, of those very posts: a story this batch removes,
        so the mention named a story no longer stored (story_mentions_story_id_fkey)."""
        page, first, other = self._page("left"), self._page("first"), self._page("other")
        a = self._post(self._source("A"), links=[page], stored_hours_ago=3)
        b = self._post(self._source("B"), links=[page], stored_hours_ago=2)
        self._incremental()
        self.assertEqual(self._story(b), a, "a story through the page")
        self._relink(a, [])
        self._relink(b, [])
        roundup = self._post(self._source("Weekly"), links=[first, page, other])
        self._incremental()
        self.assertEqual([self._story(a), self._story(b)], [None, None], "the page joins no one now")
        self.cur.execute("SELECT story_id::text FROM story_mentions WHERE post_id = %s", (roundup,))
        self.assertEqual(self.cur.fetchall(), [], "the page is in no story: the roundup mentions none")
        self.assert_every_story_row_is_whole()
        self.assert_same_as_full()

    def test_nothing_new_writes_nothing(self):
        self.assertEqual(self._incremental(), {}, "an empty queue and the same clock: no step")


if __name__ == "__main__":
    unittest.main()
