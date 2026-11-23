"""A source's archive stores only pages on its own site; another site's pages it stored are moved out (v10.42).

1. Every address strategy (sitemap, listing, Web Archive) asks archive_ladder.own_site of each page before reading
   it: a page off the source's own site is never its post, whatever the checkpoint names. A listing's post shape is
   the feed's items on the source's own site, so a link blog's listing finds its own entries, not the sites it links.
2. scripts/repair_foreign_pages moves a source's foreign pages (read from an address, collected or saved to it) to
   the Saved source as an outside page is kept there (story_only; a saved page as it was), recorded in
   metadata.moved_from; feed items linking elsewhere stay; nothing is deleted.

Fictional names; no network (FakeHttp); DB tests against a `_test` database.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.ingestion.kinds import page_watch, saved
from insight_core.ingestion.kinds.base import RateLimit
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.scripts import repair_foreign_pages
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests._stories import insert_post, insert_source
from insight_core.tests.test_archive_site_and_dates import LINKS, LINKS_FEED, PAPER, article, rss, source

RATE = RateLimit(page_delay_s=0, batch_size=0, batch_cooldown_s=0)


class OwnPagesOnlyTests(unittest.TestCase):
    def test_a_page_off_the_sources_site_is_never_read_as_its_post(self):
        url = f"{PAPER}/2026/10/01/a-crossword"
        http = FakeHttp({url: article("a crossword")})
        kind = GenericRssKind(http, min_page_delay=0)
        self.assertIsNone(asyncio.run(kind._sitemap_post(source(LINKS_FEED), url, None)))
        self.assertIsNone(asyncio.run(kind._sitemap_post(source(LINKS_FEED), url, None, site=LINKS)))
        self.assertEqual(http.requests, [], "not even read")
        own = f"{LINKS}/2025/03/an-entry/"
        http.responses[own] = article("an entry", "2025-03-02T00:00:00Z")
        self.assertEqual(asyncio.run(kind._sitemap_post(source(LINKS_FEED), own, None, site=LINKS))["url"], own)

    def test_a_sitemap_checkpoint_naming_another_site_stores_none_of_its_pages(self):
        # a ladder checkpoint whose sitemap names the paper while its ladder recorded the blog
        paper = [f"{PAPER}/2026/10/{n:02d}/story" for n in range(1, 4)]
        http = FakeHttp({url: article(url) for url in paper})
        kind = GenericRssKind(http, min_page_delay=0)
        checkpoint = {"mode": "sitemap", "site": PAPER, "prefix": "/", "next_index": 0, "pages_fetched": 1,
                      "collected_posts": 0, "total_candidates": 3,
                      "ladder": {"platform": "unknown", "order": [], "site": LINKS, "items": [], "starts": {},
                                 "worked": {}}}
        pages = _pages(kind._sitemap_pages(source(LINKS_FEED), checkpoint, [(url, None) for url in paper], set(),
                                           100, RATE))
        self.assertEqual([post for page in pages for post in page.posts], [])
        self.assertEqual(http.requests, [])

    def test_a_link_blogs_listing_finds_its_own_entries_never_the_sites_it_links(self):
        items = [f"{PAPER}/2026/11/01/story-1", f"{LINKS}/2026/11/a-note", f"{PAPER}/2026/11/02/story-2",
                 f"{LINKS}/2026/10/another-note"]
        listing = f"{LINKS}/archive/"
        older = f"{LINKS}/2019/05/an-old-note"
        page = (f'<html><body><a href="{older}">old</a><a href="{PAPER}/2019/05/01/old-story">paper</a>'
                f'<a href="{PAPER}/2019/05/02/another-story">paper</a></body></html>')
        http = FakeHttp({LINKS_FEED: rss(items, link=f"{LINKS}/"), listing: page,
                         older: article("an old note", "2019-05-03T00:00:00Z"),
                         f"{PAPER}/2019/05/01/old-story": article("old story"),
                         f"{PAPER}/2019/05/02/another-story": article("another story")})
        kind = GenericRssKind(http, min_page_delay=0)
        checkpoint = kind._start("listing", {"listing": listing},
                                 {"platform": "unknown", "order": [], "site": LINKS, "items": items, "starts": {},
                                  "worked": {}}, pages_fetched=1, collected=0)
        pages = _pages(kind._listing_pages(source(LINKS_FEED), checkpoint, set(), RATE))
        self.assertEqual([post["url"] for p in pages for post in p.posts], [older])
        self.assertFalse([url for url in http.requests if url.startswith(PAPER)], "the linked sites are never read")

    def test_the_row_signature_of_a_page_read_from_its_address(self):
        self.assertTrue(page_watch.read_from_address("/2026/10/01/a-crossword", "generic_rss"))
        self.assertTrue(page_watch.read_from_address("/news/a-page", "page_watch"))
        self.assertFalse(page_watch.read_from_address("https://x.example/guid", "generic_rss"), "a feed item's guid")
        self.assertFalse(page_watch.read_from_address(None, None), "a feed item")
        self.assertFalse(page_watch.read_from_address("/a-page", "saved"))


def _pages(gen) -> list:
    """An archive generator's pages, run to the end."""
    async def collect():
        return [page async for page in gen]
    return asyncio.run(collect())


@requires_test_db
class RepairForeignPagesTests(unittest.TestCase):
    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.site = f"https://links-{self.mark}.example"
        self.paper = f"https://paper-{self.mark}.example"
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("""INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest)
                           VALUES (%s, %s, true, false) ON CONFLICT (platform, handle_or_url) DO NOTHING""",
                        (saved.PLATFORM, saved.HANDLE))
            cur.execute("SELECT id::text FROM sources WHERE platform = %s AND handle_or_url = %s",
                        (saved.PLATFORM, saved.HANDLE))
            self.saved = cur.fetchone()[0]
            self.source = insert_source(cur, handle=f"{self.site}/feed")
            self.feeds = {f"{self.site}/feed": rss([f"{self.paper}/2026/11/01/linked-story"], link=f"{self.site}/")}
            self.own_entry = self._post(cur, f"{self.site}/2025/03/an-entry", "/2025/03/an-entry", "generic_rss")
            self.feed_link = self._post(cur, f"{self.paper}/2026/11/01/linked-story", None, None)   # a feed item
            for n in range(2):   # its feed's own entries
                self._post(cur, f"{self.site}/2026/11/0{n + 1}/a-note", f"{self.site}/2026/11/0{n + 1}/a-note", None)
            self.crawled = [self._post(cur, f"{self.paper}/2026/10/{n:02d}/crossword", f"/2026/10/{n:02d}/crossword",
                                       "generic_rss") for n in range(1, 4)]
            self.collected = self._post(cur, f"{self.paper}/live/2026/11/12/a-live-blog",
                                        f"{self.paper}/live/2026/11/12/a-live-blog", "saved",
                                        {"missed_by_feed": "2026-11-14T03:14:22+00:00"})
            self.saved_page = self._post(cur, f"{self.paper}/2026/11/13/saved-story",
                                         f"{self.paper}/2026/11/13/saved-story", "saved",
                                         {"saved_by_owner": "2026-11-14T03:14:22+00:00"})
            cur.execute("INSERT INTO post_reader_state (post_id, read_at, updated_at) VALUES (%s, now(), now())",
                        (self.crawled[0],))
            conn.commit()

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM posts WHERE source_id = %s::uuid AND url LIKE %s", (self.saved, f"{self.paper}%"))
            delete_scratch_sources(cur)
            conn.commit()

    def _post(self, cur, url, external_id, adapter, extra=None):
        pid = insert_post(cur, self.source, url, title=url.rsplit("/", 1)[-1], content="A page.")
        metadata = {**({"adapter": adapter} if adapter else {}), **(extra or {})}
        cur.execute("UPDATE posts SET external_id = %s, metadata = %s::jsonb WHERE id = %s",
                    (external_id, json.dumps(metadata), pid))
        return str(pid)

    def _where(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT id::text, source_id::text, external_id, metadata FROM posts WHERE source_id = ANY(%s::uuid[])",
                        ([self.source, self.saved],))
            return {row[0]: row[1:] for row in cur.fetchall()}

    def test_a_dry_run_counts_and_changes_nothing(self):
        before = self._where()
        with psycopg.connect(db_url()) as conn:
            out = repair_foreign_pages.run(conn, dry_run=True, source_id=self.source, read_feed=self._feed)
        self.assertEqual(out["posts"], 5)
        (s,) = out["sources"]
        self.assertEqual(s["kinds"], {"read_from_address": 3, "collected": 1, "saved": 1})
        self.assertEqual(self._where(), before)

    def test_the_foreign_pages_move_to_saved_and_the_sources_own_stay(self):
        with psycopg.connect(db_url()) as conn:
            out = repair_foreign_pages.run(conn, dry_run=False, source_id=self.source, read_feed=self._feed)
        self.assertEqual(out["sources"][0]["done"], 5)
        rows = self._where()
        self.assertEqual(rows[self.own_entry][0], self.source, "its own page stays")
        self.assertEqual(rows[self.feed_link][0], self.source, "a feed item linking elsewhere stays")
        for pid in (*self.crawled, self.collected):
            sid, external_id, metadata = rows[pid]
            self.assertEqual(sid, self.saved)
            self.assertTrue(metadata["story_only"], "kept as an outside page: no feed row, no unread count")
            self.assertEqual((metadata["moved_from"]["source_id"], metadata["moved_from"]["why"]),
                             (self.source, "foreign_site"))
        self.assertEqual(rows[self.crawled[0]][1].split("://")[0], "https", "its external id is its address now")
        self.assertEqual(rows[self.crawled[0]][2]["moved_from"]["external_id"], "/2026/10/01/crossword")
        sid, _, metadata = rows[self.saved_page]
        self.assertEqual(sid, self.saved)
        self.assertNotIn("story_only", metadata, "a page you saved stays a saved page")
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT read_at IS NOT NULL FROM post_reader_state WHERE post_id = %s", (self.crawled[0],))
            self.assertTrue(cur.fetchone()[0], "the row and its read state kept")
            again = repair_foreign_pages.run(conn, dry_run=True, source_id=self.source, read_feed=self._feed)
        self.assertEqual(again["posts"], 0, "once")

    def _feed(self, url):
        if url not in self.feeds:
            raise ValueError(f"HTTP 404 while fetching {url}")
        return self.feeds[url]

    def _elsewhere(self, feed, channel_link):
        """A feed served off the site its items are on, with one page its archive read from that site."""
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            other = insert_source(cur, handle=feed)
            for n in range(3):
                insert_post(cur, other, f"{self.site}/feed-item-{n}", content="A page.")
            pid = insert_post(cur, other, f"{self.site}/2019/an-archived-entry", content="A page.")
            cur.execute("""UPDATE posts SET external_id = '/2019/an-archived-entry',
                                  metadata = '{"adapter": "generic_rss"}' WHERE id = %s""", (pid,))
            conn.commit()
        self.feeds[feed] = rss([f"{self.site}/feed-item-{n}" for n in range(3)], link=channel_link)
        return other

    def test_a_feed_served_elsewhere_keeps_the_pages_of_the_site_its_channel_links_home(self):
        other = self._elsewhere(f"https://feedhost-{self.mark}.example/feed", f"{self.site}/")
        with psycopg.connect(db_url()) as conn:
            out = repair_foreign_pages.run(conn, dry_run=True, source_id=other, read_feed=self._feed)
        self.assertEqual(out["posts"], 0, "its channel link is that site's home: its own")

    def test_a_feed_made_of_another_sites_pages_gives_back_what_its_archive_read_there(self):
        # a trending feed of a code host's pages: its items are there, its site is its own host
        other = self._elsewhere(f"https://trends-{self.mark}.example/daily.xml", f"{self.site}/trending")
        with psycopg.connect(db_url()) as conn:
            out = repair_foreign_pages.run(conn, dry_run=True, source_id=other, read_feed=self._feed)
        self.assertEqual(out["posts"], 1, "the page its archive read on the code host; its feed items stay")

    def test_a_source_whose_feed_cannot_be_read_is_skipped(self):
        del self.feeds[f"{self.site}/feed"]
        with psycopg.connect(db_url()) as conn:
            out = repair_foreign_pages.run(conn, dry_run=True, source_id=self.source, read_feed=self._feed)
        self.assertEqual((out["posts"], out["skipped"][0]["candidates"]), (0, 5))


if __name__ == "__main__":
    unittest.main()
