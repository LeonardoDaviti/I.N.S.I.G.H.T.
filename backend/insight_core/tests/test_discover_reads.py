"""What Discover reads of the web for its first page (issue 0080): the follow test's labels, a page's
title, read once in 30 days and stored with a date. Fixtures only: nothing is fetched.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_discover import READS_KEY, DiscoverRepository
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.services import discover_reads
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_feed_finder import page, rss

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def refused(status):
    return lambda url: HttpError(f"HTTP {status} while fetching {url}", status=status)


def test_of(responses, url):
    http = FakeHttp(responses)
    return asyncio.run(discover_reads.follow_test(http, KindRegistry.default(http, None), url, []))


class FollowTestTests(unittest.TestCase):
    def test_a_feed_the_finder_finds(self):
        site = "https://feeds.example/"
        responses = {site: page('<link rel="alternate" type="application/rss+xml" href="/feed.xml">'),
                     "https://feeds.example/feed.xml": rss("Feeds")}
        self.assertEqual(test_of(responses, "https://feeds.example"), "feed")

    def test_a_site_refusing_every_reader(self):
        self.assertEqual(test_of(refused(403), "https://walled.example"), "blocked")
        self.assertEqual(test_of(refused(401), "https://walled.example"), "blocked")

    def test_a_paywall_or_nothing_to_read_is_headlines_only(self):
        self.assertEqual(test_of(refused(402), "https://paid.example"), "headlines")
        self.assertEqual(test_of({"https://bare.example/": page()}, "https://bare.example"), "headlines")

    def test_the_labels_of_an_answer(self):
        polite = discover_reads.Polite(None)
        self.assertEqual(discover_reads.label({"status": "direct"}, polite), "feed", "a kind reads it (an X account)")
        self.assertEqual(discover_reads.label({"status": "none", "feeds": [], "pages": [{"items": [{}]}]}, polite), "page")
        polite.refused, polite.answered = [403, 401], 0
        self.assertEqual(discover_reads.label({"status": "none"}, polite), "blocked")
        polite.answered = 1
        self.assertEqual(discover_reads.label({"status": "none"}, polite), "headlines", "it answered once")


def bridge_rss(user, items=2):
    entries = "".join(f"<item><title>Tweet {n}</title><link>https://nitter.local/{user}/status/{2000000000000000000 + n}#m</link></item>"
                      for n in range(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{user}</title>{entries}</channel></rss>'


class PlatformAccountTests(unittest.TestCase):
    """Issue 0109 W1: a platform account is tested through the source kind INSIGHT follows it by, not the
    feed finder on its web address (which found nothing on x.com and called 11 of 11 accounts headlines)."""

    def registry(self, http=None):
        return KindRegistry.default(http or FakeHttp({}), None)

    def test_each_platform_account_reads_through_its_kind(self):
        registry = self.registry()
        cases = {"x.com/someone": ("https://nitter.local/someone/rss", "nitter_rss"),
                 "t.me/achannel": ("https://telegram.local/rss/achannel?limit=50", "telegram_rss"),
                 "reddit.com/r/asub": ("r/asub", "reddit_subreddit"),
                 "youtube.com/@achannel": ("https://www.youtube.com/@achannel", "youtube_channel")}
        for key, (address, kind) in cases.items():
            source = discover_reads.kind_source(key, registry)
            self.assertIsNotNone(source, key)
            self.assertEqual(source["handle_or_url"], address, key)
            self.assertEqual(registry.resolve(source).name, kind, key)

    def test_a_site_or_an_owner_with_no_kind_goes_to_the_finder(self):
        registry = self.registry()
        for key in ("news.example", "github.com/anorg", "hub.example/anowner", "x.com/someone/status", "youtube.com/watch"):
            self.assertIsNone(discover_reads.kind_source(key, registry), key)

    def test_an_x_account_whose_bridge_answers_is_a_feed(self):
        http = FakeHttp({"https://nitter.local/someone/rss": bridge_rss("someone")})
        got = asyncio.run(discover_reads.follow_test(http, self.registry(http), "https://x.com/someone", []))
        self.assertEqual(got, "feed")
        self.assertNotIn("https://x.com/someone", http.requests, "x.com itself is never asked")

    def test_an_x_account_the_bridge_has_nothing_of_is_headlines(self):
        http = FakeHttp({"https://nitter.local/someone/rss": bridge_rss("someone", items=0)})
        self.assertEqual(asyncio.run(discover_reads.follow_test(http, self.registry(http), "https://x.com/someone", [])), "headlines")
        http = FakeHttp(refused(403))
        self.assertEqual(asyncio.run(discover_reads.follow_test(http, self.registry(http), "https://x.com/someone", [])), "blocked")

    def test_a_test_by_older_rules_is_due_again(self):
        old = {"label": "headlines", "at": (NOW - timedelta(days=1)).isoformat()}
        self.assertTrue(discover_reads.due(old, NOW, test=True), "the 11 X accounts tested by the finder are tested again")
        fresh = {**old, "test": discover_reads.FOLLOW_TEST}
        self.assertFalse(discover_reads.due(fresh, NOW, test=True))
        self.assertFalse(discover_reads.due(old, NOW), "a title read has no rules version")
        listed = [{"key": "low.example", "articles": []}]
        reads = {"follow": {"low.example": old}}
        self.assertEqual(discover_reads.work([], reads, NOW, listed=listed)["follow"], ["low.example"],
                         "a stale test is redone wherever its suggestion is listed, not only on the first page")


def site_rss(host, paths):
    entries = "".join(f"<item><title>{p}</title><link>https://{host}{p}</link></item>" for p in paths)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{host}</title>{entries}</channel></rss>'


class FeedOfThesePagesTests(unittest.TestCase):
    """Issue 0109 W9: "Feed found" for a hub's owners, whose feed is the hub's own blog (it holds none of their pages)."""

    def test_a_hubs_feed_is_not_its_owners(self):
        owner = ["https://hub.example/anowner/model-one", "https://hub.example/anowner/model-two"]
        responses = {"https://hub.example/anowner": page(),
                     "https://hub.example/": page('<link rel="alternate" type="application/rss+xml" href="/feed.xml">'),
                     "https://hub.example/feed.xml": site_rss("hub.example", ["/blog/post-1", "/blog/post-2"])}
        http = FakeHttp(responses)
        got = asyncio.run(discover_reads.follow_test(http, KindRegistry.default(http, None), "https://hub.example/anowner",
                                                     owner + ["https://hub.example/blog/post-1"]))
        self.assertEqual(got, "other_feed", "the hub's blog post linked elsewhere is not the owner's")
        # The hub's blog feed under another section (/blog/feed.xml) is not even found for an owner (v10.13.5).
        responses["https://hub.example/"] = page('<link rel="alternate" type="application/rss+xml" href="/blog/feed.xml">')
        responses["https://hub.example/blog/feed.xml"] = responses.pop("https://hub.example/feed.xml")
        http = FakeHttp(responses)
        got = asyncio.run(discover_reads.follow_test(http, KindRegistry.default(http, None), "https://hub.example/anowner",
                                                     owner + ["https://hub.example/blog/post-1"]))
        self.assertEqual(got, "headlines")

    def test_a_feed_holding_a_linked_page_is_found(self):
        linked = ["https://news.example/2026/10/a-story", "https://news.example/2026/10/another"]
        responses = {"https://news.example/": page('<link rel="alternate" type="application/rss+xml" href="/feed.xml">'),
                     "https://news.example/feed.xml": site_rss("news.example", ["/2026/10/a-story", "/2026/11/newer"])}
        http = FakeHttp(responses)
        self.assertEqual(asyncio.run(discover_reads.follow_test(http, KindRegistry.default(http, None), "https://news.example", linked)),
                         "feed")

    def test_the_labels(self):
        self.assertIn("other_feed", discover_reads.LABELS)
        self.assertGreaterEqual(discover_reads.FOLLOW_TEST, 3, "a hub owner's 'feed' by the older rule is tested again")
        self.assertEqual(discover_reads.own_pages("hub.example/anowner", ["https://hub.example/anowner/a", "https://hub.example/b",
                                                                           "https://www.hub.example/AnOwner/c"]),
                         ["https://hub.example/anowner/a", "https://www.hub.example/AnOwner/c"])


class TitleTests(unittest.TestCase):
    def test_a_pages_own_title(self):
        html = '<html><head><meta property="og:title" content="A real headline"><title>A real headline | Site</title></head></html>'
        self.assertEqual(discover_reads.page_title(html, "https://news.example/a"), "A real headline")
        self.assertIsNone(discover_reads.page_title("<html><head></head><body></body></html>", "https://news.example/a"))
        self.assertIsNone(discover_reads.page_title("<title>news.example/a-b</title>", "https://news.example/a"),
                          "an address is no title")

    def test_what_the_first_page_asks_to_read(self):
        first = [{"key": "a.example", "articles": [{"url": "https://a.example/1", "title": None},
                                                   {"url": "https://a.example/2", "title": "Has one"},
                                                   {"url": "https://x.com/u/status/2111872584338018562", "title": None}]},
                 {"key": "b.example", "articles": [{"url": "https://b.example/1", "title": None}]}]
        reads = {"follow": {"a.example": {"label": "feed", "at": (NOW - timedelta(days=3)).isoformat(), "test": discover_reads.FOLLOW_TEST},
                            "b.example": {"label": "feed", "at": (NOW - timedelta(days=31)).isoformat()}},
                 "titles": {"https://b.example/1": {"title": None, "at": (NOW - timedelta(days=1)).isoformat()}}}
        self.assertEqual(discover_reads.work(first, reads, NOW),
                         {"follow": ["b.example"], "titles": ["https://a.example/1"]},
                         "a test 31 days old again; a failed read is not asked again; a tweet never")


@requires_test_db
class ReadFirstPageTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (READS_KEY,))
        row = self.cur.fetchone()
        self.addCleanup(self._restore, row[0] if row else None)

    def _restore(self, value):
        self.conn.rollback()
        if value is None:
            self.cur.execute("DELETE FROM system_settings WHERE key = %s", (READS_KEY,))
        else:
            DiscoverRepository.keep_reads(self.cur, value)
        self.conn.commit()
        self.conn.close()

    def test_answers_are_stored_with_their_date_and_not_read_again(self):
        m = uuid.uuid4().hex[:8]
        key, article = f"site-{m}.example", f"https://site-{m}.example/2026/10/a"
        first = [{"key": key, "articles": [{"url": article, "title": None}]}]
        stories = SimpleNamespace(db_url=db_url(), discover=lambda limit=None: {"suggestions": first}, refresh=lambda: None,
                                  linked_articles=lambda address: [], untitled_classics=lambda: [])
        responses = {f"https://{key}/": page('<link rel="alternate" type="application/rss+xml" href="/feed.xml">'),
                     f"https://{key}/feed.xml": rss("Site"),
                     article: '<html><head><title>The article</title></head></html>'}
        http = FakeHttp(responses)
        got = asyncio.run(discover_reads.read_first_page(stories, http, KindRegistry.default(http, None), clock=lambda: NOW))
        self.assertEqual(got, {"follow": 1, "titles": 1})
        self.cur.execute("SELECT 1")   # a fresh snapshot
        reads = DiscoverRepository.reads(self.cur)
        self.assertEqual(reads["follow"][key], {"label": "feed", "at": NOW.isoformat(), "test": discover_reads.FOLLOW_TEST})
        self.assertEqual(reads["titles"][article], {"title": "The article", "at": NOW.isoformat()})
        again = asyncio.run(discover_reads.read_first_page(stories, http, KindRegistry.default(http, None),
                                                           clock=lambda: NOW + timedelta(days=29)))
        self.assertEqual(again, {"follow": 0, "titles": 0}, "never within 30 days")


if __name__ == "__main__":
    unittest.main()
