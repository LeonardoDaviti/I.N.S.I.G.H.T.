"""0208: a link post with no words of its own (a Reddit link post: its title and the page it shares) has its page read
by the originals step (story_originals kind `linked`), and Mark X reads the post with that page's text
(tasks.load_posts), its text stamp moving once the page is there (plan_marks.STAMP). A post with words of its own, a
page stored already, a followed source's page and an old post are each handled as the step says.

No network: FakeHttp answers every page. The tests commit rows, so they run only against a `_test` database; they
own every source and post on the example sites below."""
from __future__ import annotations

import html as html_lib
from datetime import timedelta

import psycopg

from insight_core.db.repo_post_parts import PostPartsRepository
from insight_core.markx import plan_marks, tasks
from insight_core.tests._db import db_url
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_story_originals import ESSAY, OriginalsCase, essay, run

PROJECT = "https://project.oopromo.example/"
OTHER = "https://project.oopromo.example/other-page"


def reddit_html(target: str, words: str = "") -> str:
    """A Reddit feed item's body: its own words (if any), then the footer naming the page it shares."""
    return (f"{words}&#32; submitted by &#32; <a href=\"https://www.reddit.com/user/someone\"> /u/someone </a> <br/>"
            f" <span><a href=\"{html_lib.escape(target)}\">[link]</a></span> &#32; "
            f"<span><a href=\"https://www.reddit.com/r/oosub/comments/abc/x/\">[comments]</a></span>")


class LinkPosts(OriginalsCase):
    def setUp(self):
        super().setUp()
        self.reddit = self._source("rss", "https://r.oolinkr.example/feed.xml", name="r/oosub")

    def link_post(self, target, title="A method ten times faster", words="", hours=2):
        url = f"https://r.oolinkr.example/r/oosub/comments/{abs(hash((target, title, hours)))}/x/"
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, content_html, published_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id::text""",
                        (self.reddit, url, url, title, (title + " " + words).strip() if words else "",
                         reddit_html(target, words), self.now - timedelta(hours=hours)))
            pid = cur.fetchone()[0]
            PostPartsRepository.write(cur, [pid])
        return pid

    def plan(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            return self.service().plan_link_posts(cur, self.now)

    def text_and_stamp(self, pid):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            text = tasks.load_posts(cur, [pid])[pid].text
            cur.execute(f"SELECT {plan_marks.STAMP} FROM posts p WHERE p.id = %s", (pid,))
            return text, cur.fetchone()[0]

    def test_the_page_is_read_and_the_post_is_read_with_it(self):
        pid = self.link_post(ESSAY)
        before, stamp_before = self.text_and_stamp(pid)
        self.assertEqual(before, "")
        planned = self.plan()
        self.assertEqual([(c["url"], c["record"], c["from_post_id"]) for c in planned], [(ESSAY, "linked", pid)])
        http = FakeHttp({ESSAY: essay()})
        summary = run(self.service().run(http))
        self.assertEqual(summary["linked_pages"], 1)
        self.assertEqual(http.requests, [ESSAY])
        ((outcome, from_post, page),) = self._rows("SELECT outcome, from_post_id::text, post_id::text FROM story_originals "
                                                   "WHERE kind = 'linked' AND url = %s", ESSAY)
        self.assertEqual((outcome, from_post), ("collected", pid))
        after, stamp_after = self.text_and_stamp(pid)
        self.assertTrue(after.startswith("[The page it links: An essay about the release]\n"), after[:80])
        self.assertIn("A paragraph of the essay", after)
        self.assertNotEqual(stamp_before, stamp_after)                         # its questions are planned again
        self.assertEqual(self.plan(), [])                                      # never asked again

    def test_a_post_with_words_of_its_own_is_left_as_it_is(self):
        self.link_post(ESSAY, words="Here is my long take on it. " * 12)
        self.assertEqual(self.plan(), [])

    def test_a_page_stored_already_is_recorded_with_no_request(self):
        pid = self.link_post(ESSAY)
        page = self._post(self.a, ESSAY, "An essay about the release", self.now - timedelta(hours=5))
        self.assertEqual(self.plan(), [])
        self.assertEqual(self._rows("SELECT outcome, post_id::text FROM story_originals WHERE kind = 'linked' AND url = %s",
                                    ESSAY), [("already", page)])
        text, _ = self.text_and_stamp(pid)
        self.assertIn("Words of the post.", text)

    def test_an_old_post_or_a_picture_is_not_planned(self):
        self.link_post(PROJECT, hours=24 * 4)                                  # older than LINK_POSTS_WITHIN
        self.link_post("https://i.oopromo.example/a.png", title="A picture")    # a picture, not a page
        self.assertEqual(self.plan(), [])

    def test_two_posts_sharing_one_page_ask_it_once_and_both_read_it(self):
        one, two = self.link_post(ESSAY, title="First share"), self.link_post(ESSAY, title="Second share", hours=1)
        self.assertEqual(len(self.plan()), 1)
        run(self.service().run(FakeHttp({ESSAY: essay()})))
        for pid in (one, two):
            self.assertIn("[The page it links:", self.text_and_stamp(pid)[0])

    def test_any_other_post_keeps_its_stamp(self):
        pid = self._post(self.a, OTHER, "A post with words", self.now - timedelta(hours=1))
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {plan_marks.STAMP}, p.xmin::text || p.ctid::text FROM posts p WHERE p.id = %s", (pid,))
            stamp, row = cur.fetchone()
        self.assertTrue(stamp.startswith(row))
        self.assertEqual(stamp.count("|"), 3)                                  # nothing added: the stamps before 0208
