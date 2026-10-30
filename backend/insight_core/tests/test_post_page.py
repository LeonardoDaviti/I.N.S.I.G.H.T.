"""The post page knows what INSIGHT has: its story (issue 0055, "covered by" at the end of the
post) and the links of its text that are stored posts (issue 0057, they open in INSIGHT).

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
from insight_core.utils.post_links import body_hrefs
from insight_core.utils.url_normalization import normalize_url

LONG = "x" * 200   # a text long enough to be a copy


class BodyHrefsTests(unittest.TestCase):
    def test_html_hrefs_each_once_entities_decoded(self):
        html = ('<a href="https://a.test/1?x=1&amp;y=2">a</a> <a href=\'/rel\'>b</a>'
                '<a href="https://a.test/1?x=1&amp;y=2">again</a>')
        self.assertEqual(body_hrefs(html, "ignored https://c.test/2"), ["https://a.test/1?x=1&y=2", "/rel"])

    def test_escaped_html_as_the_reader_decodes_it(self):
        self.assertEqual(body_hrefs('&lt;a href=&quot;https://a.test/1?x=1&amp;amp;y=2&quot;&gt;a&lt;/a&gt;'),
                         ["https://a.test/1?x=1&y=2"])

    def test_plain_text_bare_addresses_without_trailing_punctuation(self):
        text = "See https://t.me/chan/1. And (https://b.test/x), [it](https://c.test/y)!"
        self.assertEqual(body_hrefs(None, text), ["https://t.me/chan/1", "https://b.test/x", "https://c.test/y"])

    def test_nothing(self):
        self.assertEqual(body_hrefs(None, None), [])
        self.assertEqual(body_hrefs("", "no links here"), [])


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

    # ---- 0057: the links that are stored posts --------------------------------------------------

    def _links(self, post_id, url, html=None, content=None):
        return PostDetailService.internal_links(self.cur, post_id, url, html, content)

    def _linking(self, *hrefs, url=None):
        source = self._source("Linking")
        url = url or f"https://t.me/chan{self.mark}/200"
        html = "".join(f'<a href="{h}">{h}</a> ' for h in hrefs)
        return self._post(source, url=url, html=html), url, html

    def test_a_link_into_the_same_platform(self):
        channel = self._source("Channel")
        earlier = self._post(channel, url=f"https://t.me/chan{self.mark}/9951", hours_ago=24 * 20)
        href = f"https://t.me/chan{self.mark}/9951"
        post, url, html = self._linking(href)
        self.assertEqual(self._links(post, url, html), {href: earlier})

    def test_a_link_to_another_site_and_one_not_stored(self):
        blog = self._source("Blog")
        article = self._post(blog, url=f"https://blog-{self.mark}.test/2026/10/a-post")
        stored = f"https://blog-{self.mark}.test/2026/10/a-post"
        missing = f"https://blog-{self.mark}.test/2026/10/never-stored"
        post, url, html = self._linking(stored, missing)
        self.assertEqual(self._links(post, url, html), {stored: article})

    def test_another_form_of_the_address(self):
        blog = self._source("Blog")
        article = self._post(blog, url=f"https://blog-{self.mark}.test/2026/10/a-post/")
        tagged = f"http://www.blog-{self.mark}.test/2026/10/a-post?utm_source=rss&amp;utm_medium=x#comments"
        post, url, html = self._linking(tagged)
        self.assertEqual(self._links(post, url, html),
                         {f"http://www.blog-{self.mark}.test/2026/10/a-post?utm_source=rss&utm_medium=x#comments": article},
                         "the key is the href as the reader gets it, entities decoded")

    def test_two_posts_at_one_address_the_first_seen_unless_one_is_the_exact_url(self):
        blog = self._source("Blog")
        base = f"https://blog-{self.mark}.test/2026/10/shared"
        first = self._post(blog, url=f"{base}#fn1", title="One", fetched_hours_ago=10)
        second = self._post(blog, url=f"{base}#fn2", title="Two", fetched_hours_ago=5)
        post, url, html = self._linking(f"{base}?utm_campaign=x", f"{base}#fn2")
        self.assertEqual(self._links(post, url, html), {f"{base}?utm_campaign=x": first, f"{base}#fn2": second})

    def test_relative_links_plain_text_and_not_the_post_itself(self):
        blog = self._source("Blog")
        url = f"https://blog-{self.mark}.test/2026/10/this-post"
        older = self._post(blog, url=f"https://blog-{self.mark}.test/2026/09/older")
        this = self._post(blog, url=url, html='<a href="/2026/09/older">older</a> <a href="#top">top</a>')
        self.assertEqual(self._links(this, url, '<a href="/2026/09/older">older</a> <a href="#top">top</a>'),
                         {"/2026/09/older": older}, "made absolute against the post; itself never")
        text = f"Earlier: https://blog-{self.mark}.test/2026/09/older."
        self.assertEqual(self._links(this, url, None, text), {f"https://blog-{self.mark}.test/2026/09/older": older})

    def test_a_malformed_link_is_skipped(self):
        post, url, html = self._linking("https://bad.test:not a port/x", "mailto:a@b.test", "javascript:void(0)")
        self.assertEqual(self._links(post, url, html), {})


if __name__ == "__main__":
    unittest.main()
