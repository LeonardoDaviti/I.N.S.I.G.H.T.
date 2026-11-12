"""A page's own source takes its row back from a source that stored it first (issue 0167, part 1).

An aggregator (a link blog, a news aggregator's feed) stores a company's page first; the company's own followed
source (its feed, its page watch) fetches the same address later. The row moves to the company's source (its id
kept: stories, notes, reader state stay), and the aggregator keeps a post citing the page. The repair finds the pages
held so and moves those the owner's listing names.

The rows are committed (the save path commits), so this runs only against a `_test` database; it owns every source
and post on the invented sites below. No network: the repair's listing reads answer from FakeHttp.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import PostsRepository
from insight_core.scripts import repair_own_pages_0167 as repair
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.utils import own_pages
from insight_core.utils.post_fields import CITES_KEY, TAKEN_KEY

COMPANY = "https://www.opcompany.example"
NEWS = f"{COMPANY}/news"
PAGE = f"{NEWS}/introducing-the-widget"
LINKS = "https://oplinks.example"
AGGREGATOR = "https://hnrss.org/newest?points=100&opsuite=1"   # a news aggregator's feed (source_kind "hn")
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def feed(*items):
    entries = "".join(f"<item><title>{title}</title><link>{url}</link><guid>{url}</guid>"
                      f"<pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate><description>{title}.</description></item>"
                      for url, title in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title><link>{COMPANY}</link>{entries}</channel></rss>'


class OwnsTests(unittest.TestCase):
    def test_a_website_source_owns_the_pages_of_its_own_site(self):
        self.assertTrue(own_pages.owns("rss", f"{NEWS}/feed.xml", PAGE))
        self.assertTrue(own_pages.owns("rss", f"{COMPANY}/news", f"https://opcompany.example/blog/other"))

    def test_an_aggregator_a_link_blog_saved_and_platform_accounts_own_no_other_sites_page(self):
        self.assertFalse(own_pages.owns("rss", AGGREGATOR, PAGE))
        self.assertFalse(own_pages.owns("rss", f"{LINKS}/feed", PAGE))
        self.assertFalse(own_pages.owns("saved", "Saved", PAGE))
        self.assertFalse(own_pages.owns("rss", "https://nitter.local/opcompany/rss", "https://x.com/opcompany/status/1"))

    def test_two_writers_at_subdomains_of_one_host_are_two_and_a_sites_blog_is_the_site(self):
        self.assertFalse(own_pages.owns("rss", "https://one.letters.example/feed", "https://two.letters.example/p/x"))
        self.assertTrue(own_pages.owns("rss", "https://blog.opcompany.example/feed", f"{NEWS}/x"))

    def test_a_citation_has_an_address_of_its_own_that_opens_the_page(self):
        cite = own_pages.citation_address("https://opcompany.example/news/x", "abc")
        self.assertEqual(cite, "https://opcompany.example/news/x#!/cited-by/abc")
        self.assertTrue(own_pages.is_citation_address(cite))


@requires_test_db
class TakeBackTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self._clean)
        self._clean()
        self.repo = PostsRepository(db_url())
        self.links = self._source("rss", f"{LINKS}/feed", "Links")
        self.aggregator = self._source("rss", AGGREGATOR, "Aggregator")
        self.company = self._source("rss", f"{NEWS}/feed.xml", "Company news")

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM stories WHERE id IN (SELECT id FROM posts WHERE url LIKE %s)", ("%opcompany.example%",))
            cur.execute("DELETE FROM posts WHERE url LIKE %s OR url LIKE %s", ("%opcompany.example%", "%oplinks.example%"))
            cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s OR handle_or_url LIKE %s OR handle_or_url LIKE %s",
                        ("%opcompany.example%", "%oplinks.example%", "%opsuite=1%"))

    def _rows(self, sql, *args):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else None

    def _source(self, platform, handle, name, settings=None):
        ((sid,),) = self._rows("INSERT INTO sources (platform, handle_or_url, enabled, settings) VALUES (%s, %s, true, %s::jsonb)"
                               " RETURNING id::text", platform, handle, json.dumps({"display_name": name, **(settings or {})}))
        return sid

    def save(self, source_id, *, url=PAGE, title="Introducing the widget", content=None, external_id=None, metadata=None):
        post = {"url": url, "title": title, "content": content or f"{title}. " + "The widget does things. " * 30,
                "date": NOW - timedelta(days=1), "external_id": external_id, "metadata": metadata or {}}
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            post_id, inserted = self.repo.upsert_post(cur, post, source_id)
        return str(post_id), inserted

    def where(self, url=PAGE):
        return self._rows("SELECT id::text, source_id::text, metadata FROM posts WHERE url = %s", url)[0]

    def citations(self, source_id):
        return self._rows("SELECT id::text, url, metadata, content FROM posts WHERE source_id = %s::uuid AND metadata ? %s",
                          source_id, CITES_KEY)

    def test_the_owners_fetch_takes_the_row_back_and_the_holder_cites_it(self):
        held, _ = self.save(self.links, content="A link blog's words about the widget. " * 5,
                            metadata={"comments_url": f"{LINKS}/2026/widget"})
        self._rows("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 1)", held, NOW)
        self._rows("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, 'report', 'v')", held, held)
        self._rows("INSERT INTO post_reader_state (post_id, read_at) VALUES (%s, %s)", held, NOW)
        self._rows("INSERT INTO post_notes (post_id, notes_markdown) VALUES (%s, 'mine')", held)

        post_id, inserted = self.save(self.company, title="Introducing the widget", external_id="/news/introducing-the-widget")

        self.assertEqual((post_id, inserted), (held, False))   # one row, its id kept
        _, source, meta = self.where()
        self.assertEqual(source, self.company)
        self.assertEqual(meta[TAKEN_KEY]["source_id"], self.links)
        self.assertEqual(self._rows("SELECT story_id::text FROM story_posts WHERE post_id = %s", held), [(held,)])
        self.assertEqual(self._rows("SELECT notes_markdown FROM post_notes WHERE post_id = %s", held), [("mine",)])
        (cite_id, cite_url, cite_meta, cite_text), = self.citations(self.links)
        self.assertEqual(cite_url, own_pages.citation_address("https://opcompany.example/news/introducing-the-widget", self.links))
        self.assertEqual(cite_meta[CITES_KEY]["post_id"], held)
        self.assertEqual(cite_meta["comments_url"], f"{LINKS}/2026/widget")
        self.assertIn("A link blog's words", cite_text)       # the holder's text as it was
        self.assertEqual(meta[TAKEN_KEY]["citation"], cite_id)
        self.assertIsNotNone(self._rows("SELECT read_at FROM post_reader_state WHERE post_id = %s", cite_id)[0][0])

        # A later fetch of the owner keeps the mark; the holder's later fetch updates its citation, not the page.
        self.save(self.company, content="The company's own words. " * 40)
        self.save(self.links, content="The link blog again. " * 5)
        _, source, meta = self.where()
        self.assertEqual(source, self.company)
        self.assertIn(TAKEN_KEY, meta)
        self.assertIn("company's own words", self._rows("SELECT content FROM posts WHERE id = %s", held)[0][0])
        (_, _, _, cite_text), = self.citations(self.links)
        self.assertIn("link blog again", cite_text)

    def test_an_aggregator_fetching_a_page_its_owner_holds_gets_a_citation(self):
        owned, _ = self.save(self.company, content="The company's own words. " * 40)
        cite_id, inserted = self.save(self.aggregator, content="Article URL: x Points: 120")
        self.assertTrue(inserted)
        self.assertNotEqual(cite_id, owned)
        self.assertEqual(self.where()[1], self.company)
        self.assertIn("company's own words", self._rows("SELECT content FROM posts WHERE id = %s", owned)[0][0])
        (row_id, _, meta, _), = self.citations(self.aggregator)
        self.assertEqual((row_id, meta[CITES_KEY]["post_id"]), (cite_id, owned))
        again, inserted = self.save(self.aggregator, content="Article URL: x Points: 340")
        self.assertEqual((again, inserted), (cite_id, False))

    def test_two_sources_of_one_site_keep_the_page_where_it_is(self):
        watch = self._source("rss", f"{COMPANY}/research", "Company research", {"page_watch": {"prefix": "/research/"}})
        held, _ = self.save(watch)
        self.save(self.company)
        self.assertEqual(self.where()[1], watch)
        self.assertEqual(self.citations(watch), [])

    def test_the_repair_moves_the_pages_the_owners_listing_names(self):
        other = f"{NEWS}/not-listed"
        moved, _ = self.save(self.aggregator)
        left, _ = self.save(self.aggregator, url=other, title="Not listed")
        http = FakeHttp({f"{NEWS}/feed.xml": feed((PAGE, "Introducing the widget"))})
        dry = asyncio.run(repair.run(db_url(), http=http, source_id=self.company))
        self.assertEqual((dry["would_move"], dry["moved"], dry["left"]), (1, 0, 1))
        self.assertEqual(self.where()[1], self.aggregator)          # a dry run changes nothing
        done = asyncio.run(repair.run(db_url(), apply=True, http=http, source_id=self.company))
        self.assertEqual(done["moved"], 1)
        self.assertEqual(self.where()[1], self.company)
        self.assertEqual(self.where(other)[1], self.aggregator)
        self.assertEqual(len(self.citations(self.aggregator)), 1)
        again = asyncio.run(repair.run(db_url(), apply=True, http=http, source_id=self.company))
        self.assertEqual(again["would_move"], 0)                     # resumable: what moved is no candidate


if __name__ == "__main__":
    unittest.main()
