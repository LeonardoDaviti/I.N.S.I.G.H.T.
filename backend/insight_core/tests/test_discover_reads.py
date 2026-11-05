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
        reads = {"follow": {"a.example": {"label": "feed", "at": (NOW - timedelta(days=3)).isoformat()},
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
        stories = SimpleNamespace(db_url=db_url(), discover=lambda limit: {"suggestions": first},
                                  linked_articles=lambda address: [], untitled_classics=lambda: [])
        responses = {f"https://{key}/": page('<link rel="alternate" type="application/rss+xml" href="/feed.xml">'),
                     f"https://{key}/feed.xml": rss("Site"),
                     article: '<html><head><title>The article</title></head></html>'}
        http = FakeHttp(responses)
        got = asyncio.run(discover_reads.read_first_page(stories, http, KindRegistry.default(http, None), clock=lambda: NOW))
        self.assertEqual(got, {"follow": 1, "titles": 1})
        self.cur.execute("SELECT 1")   # a fresh snapshot
        reads = DiscoverRepository.reads(self.cur)
        self.assertEqual(reads["follow"][key], {"label": "feed", "at": NOW.isoformat()})
        self.assertEqual(reads["titles"][article], {"title": "The article", "at": NOW.isoformat()})
        again = asyncio.run(discover_reads.read_first_page(stories, http, KindRegistry.default(http, None),
                                                           clock=lambda: NOW + timedelta(days=29)))
        self.assertEqual(again, {"follow": 0, "titles": 0}, "never within 30 days")


if __name__ == "__main__":
    unittest.main()
