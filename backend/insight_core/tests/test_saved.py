"""Save any page (issue 0031): the Saved kind, reading one page, and POST /api/saved.

No network: FakeHttp answers. The route tests commit rows, so they run only against a `_test`
database; they own the Saved source and every post under SITE.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.saved import SavedKind
from insight_core.ingestion.schedule import Availability, cadence_stats, decide_fetch
from insight_core.services import registry
from insight_core.services.operations_service import health_row
from insight_core.services.saved_service import SavedService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp

SITE = "https://saved.test.invalid"
ARTICLE_URL = f"{SITE}/2026/10/an-essay"
PARAGRAPH = "<p>" + "A long paragraph of an essay worth keeping for later reading. " * 12 + "</p>"
ARTICLE = (f'<!DOCTYPE html><html><head><title>An essay | Saved Site</title>'
           f'<meta property="og:title" content="An essay"/><meta property="og:image" content="{SITE}/cover.jpg"/>'
           '<meta property="article:published_time" content="2026-10-20T08:00:00Z"/>'
           f'<link rel="alternate" type="application/rss+xml" href="{SITE}/feed.xml"/>'
           f'</head><body><nav><a href="/">Home</a></nav><article><h1>An essay</h1>{PARAGRAPH}</article></body></html>')
JS_SHELL = '<!DOCTYPE html><html><head><title>An app</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
FEED = ('<?xml version="1.0"?><rss version="2.0"><channel><title>Saved Site</title>'
        f'<item><title>One</title><link>{SITE}/1</link></item></channel></rss>')
NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
AVAILABLE = Availability(ytdlp_enabled=True, telegram_credentials=True)


def run(coro):
    return asyncio.run(coro)


def saved_source(**fields):
    return {"id": "s1", "platform": "saved", "handle_or_url": "Saved", "enabled": True, "settings": {}, **fields}


class SavedKindTests(unittest.TestCase):
    def test_the_registry_resolves_the_saved_platform_to_it(self):
        kinds = KindRegistry.default(FakeHttp(), None)
        self.assertEqual(kinds.resolve(saved_source()).name, "saved")
        self.assertNotEqual(kinds.resolve({"platform": "rss", "handle_or_url": "Saved"}).name, "saved")

    def test_never_due_not_even_forced_or_new(self):
        stats = cadence_stats(saved_source(post_count=0), None)
        for force in (False, True):
            decision = decide_fetch(stats, SavedKind.profile, NOW, force=force, availability=AVAILABLE)
            self.assertFalse(decision.fetch)
            self.assertIsNone(decision.next_due_at)

    def test_health_says_scheduled_never_failing_or_due(self):
        row = health_row(saved_source(post_count=3), SavedKind(), AVAILABLE, NOW)
        self.assertEqual((row["status"], row["kind"], row["would_fetch_now"], row["next_due_at"]),
                         ("deferred", "saved", False, None))

    def test_it_fetches_nothing_and_has_no_archive(self):
        self.assertEqual(run(SavedKind().fetch_latest(saved_source(), 20)), [])
        support = SourceFetchService._support(SavedKind(), {}, AVAILABLE)
        self.assertFalse(support["archivable"])


class ReadPageTests(unittest.TestCase):
    def read(self, responses, url=ARTICLE_URL, title="From the bookmarklet", **fake):
        service = SavedService("unused", sources=None, source_config_sync=None, kinds=None)
        return run(service.read(FakeHttp(responses, **fake), url, title))

    def test_an_article_is_read_in_full(self):
        post, reason = self.read({ARTICLE_URL: ARTICLE})
        self.assertIsNone(reason)
        self.assertEqual(post["title"], "An essay")
        self.assertIn("worth keeping", post["content"])
        self.assertEqual(post["date"], datetime(2026, 10, 20, 8, tzinfo=timezone.utc))
        self.assertEqual(post["media_urls"][0], f"{SITE}/cover.jpg")
        self.assertEqual((post["url"], post["external_id"]), (ARTICLE_URL, ARTICLE_URL))

    def test_a_redirect_saves_where_it_landed(self):
        post, _ = self.read({ARTICLE_URL: ARTICLE}, redirects={ARTICLE_URL: f"{SITE}/essay"})
        self.assertEqual(post["url"], f"{SITE}/essay")

    def test_a_javascript_shell_is_saved_with_its_title(self):
        post, reason = self.read({ARTICLE_URL: JS_SHELL})
        self.assertEqual((post["title"], post["content"], reason), ("An app", "", "no article on the page"))
        self.assertTrue(post["metadata"]["unreadable"])

    def test_a_blocked_page_is_saved_with_the_bookmarklets_title_and_no_body_in_the_reason(self):
        blocked = HttpError("HTTP 403 while fetching x: <html>Access denied, secret</html>", status=403)
        post, reason = self.read({ARTICLE_URL: blocked})
        self.assertEqual((post["title"], post["url"], reason), ("From the bookmarklet", ARTICLE_URL, "HTTP 403"))

    def test_with_no_title_at_all_the_address_is_the_title(self):
        post, _ = self.read({}, title="")
        self.assertEqual(post["title"], ARTICLE_URL)


@requires_test_db
class SaveRouteTests(unittest.TestCase):
    def setUp(self):
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        self.export = mock.Mock()
        registry.services().saved.source_config_sync = mock.Mock(sync_db_to_json=self.export)
        self.addCleanup(self._clean)
        self._clean()

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sources WHERE platform = 'saved' OR handle_or_url LIKE %s", (SITE + "%",))
            cur.execute("DELETE FROM posts WHERE url LIKE %s", (SITE + "%",))

    def save(self, responses, url=ARTICLE_URL, title="An essay"):
        with mock.patch.object(main, "FEED_FINDER_HTTP", FakeHttp(responses)):
            status, _, body = call(main.app, "POST", "/api/saved", json_body={"url": url, "title": title})
        return status, body

    def _rows(self, sql, *args):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()

    def test_save_reads_the_article_into_the_saved_source_unread(self):
        status, body = self.save({ARTICLE_URL: ARTICLE})
        self.assertEqual(status, 200, body)
        self.assertEqual((body["status"], body["title"], body["readable"]), ("saved", "An essay", True))
        ((platform, handle, title, content),) = self._rows(
            "SELECT s.platform, s.handle_or_url, p.title, p.content FROM posts p JOIN sources s ON s.id = p.source_id "
            "WHERE p.id = %s", body["post_id"])
        self.assertEqual((platform, handle, title), ("saved", "Saved", "An essay"))
        self.assertIn("worth keeping", content)
        status, _, feed = call(main.app, "GET", "/api/feed", query={"scope": f"source:{body['source_id']}", "filter": "unread"})
        self.assertEqual([item["id"] for item in feed["items"]], [body["post_id"]])

    def test_the_saved_source_is_created_once_and_written_to_sources_json(self):
        _, first = self.save({ARTICLE_URL: ARTICLE})
        _, second = self.save({f"{SITE}/other": ARTICLE}, url=f"{SITE}/other")
        self.assertEqual(first["source_id"], second["source_id"])
        self.assertEqual(self._rows("SELECT count(*) FROM sources WHERE platform = 'saved'"), [(1,)])
        self.export.assert_called_once()
        row = registry.services().operations.get_source_health_row(first["source_id"])
        self.assertEqual((row["status"], row["would_fetch_now"]), ("deferred", False))

    def test_a_page_already_stored_is_not_stored_again(self):
        _, first = self.save({ARTICLE_URL: ARTICLE})
        status, again = self.save({ARTICLE_URL: ARTICLE}, url=ARTICLE_URL + "/?utm_source=x")
        self.assertEqual(status, 200, again)
        self.assertEqual((again["status"], again["post_id"]), ("already", first["post_id"]))
        self.assertEqual(self._rows("SELECT count(*) FROM posts WHERE url LIKE %s", SITE + "%"), [(1,)])

    def test_an_unreadable_page_is_saved_with_its_title_and_says_so(self):
        status, body = self.save({ARTICLE_URL: JS_SHELL}, title="An app, from the bookmarklet")
        self.assertEqual(status, 200, body)
        self.assertEqual((body["status"], body["readable"], body["reason"], body["title"]),
                         ("saved", False, "no article on the page", "An app"))

    def test_a_feed_that_is_not_a_source_is_offered(self):
        _, body = self.save({ARTICLE_URL: ARTICLE, f"{SITE}/feed.xml": FEED})
        self.assertEqual(body["feed"], {"url": f"{SITE}/feed.xml", "title": "Saved Site"})

    def test_a_feed_already_followed_is_not_offered(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO sources (platform, handle_or_url, enabled) VALUES ('rss', %s, false)",
                        (f"{SITE}/feed.xml/",))
        _, body = self.save({ARTICLE_URL: ARTICLE, f"{SITE}/feed.xml": FEED})
        self.assertIsNone(body["feed"])

    # ---- saved pages go to Later and sort by when they were saved (issue 0022, owner's decisions)

    def _at(self, when):
        registry.services().saved.clock = lambda: when

    def _state(self, post_id):
        ((published_at, later_at, metadata),) = self._rows(
            "SELECT p.published_at, rs.later_at, p.metadata FROM posts p "
            "LEFT JOIN post_reader_state rs ON rs.post_id = p.id WHERE p.id = %s", post_id)
        return published_at, later_at, metadata

    def test_a_save_is_in_later_at_the_save_time_and_dated_by_it(self):
        saved_at = datetime.now(timezone.utc).replace(microsecond=0)
        self._at(saved_at)
        _, body = self.save({ARTICLE_URL: ARTICLE})
        published_at, later_at, metadata = self._state(body["post_id"])
        self.assertEqual((published_at, later_at), (saved_at, saved_at))
        self.assertEqual(metadata["article_published_at"], "2026-10-20T08:00:00+00:00", "the page's own date is kept")
        _, _, later = call(main.app, "GET", "/api/feed", query={"scope": "all", "filter": "later"})
        self.assertIn(body["post_id"], [item["id"] for item in later["items"]])

    def test_saved_pages_sort_by_when_they_were_saved_not_the_articles_date(self):
        newer_article = ARTICLE.replace("2026-10-20T08:00:00Z", "2026-10-27T08:00:00Z")
        saved_at = datetime.now(timezone.utc).replace(microsecond=0)
        self._at(saved_at - timedelta(hours=2))
        _, first = self.save({f"{SITE}/newer": newer_article}, url=f"{SITE}/newer")
        self._at(saved_at)
        _, second = self.save({ARTICLE_URL: ARTICLE})
        # A post from a followed source, newer than both articles but older than the saves.
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO sources (platform, handle_or_url, enabled) VALUES ('rss', %s, true) RETURNING id",
                        (f"{SITE}/feed.xml",))
            (other_source,) = cur.fetchone()
            cur.execute("INSERT INTO posts (source_id, url, title, content, published_at) VALUES (%s, %s, 'Other', 'Body', %s) "
                        "RETURNING id", (other_source, f"{SITE}/followed/1", saved_at - timedelta(hours=3)))
            (other,) = cur.fetchone()
        _, _, feed = call(main.app, "GET", "/api/feed", query={"scope": f"source:{second['source_id']}", "filter": "all"})
        self.assertEqual([item["id"] for item in feed["items"]], [second["post_id"], first["post_id"]])
        self.assertEqual(datetime.fromisoformat(feed["items"][0]["sort_at"].replace("Z", "+00:00")), saved_at)
        _, _, main_feed = call(main.app, "GET", "/api/feed", query={"scope": "all", "filter": "unread", "limit": "100"})
        ids = [item["id"] for item in main_feed["items"]]
        self.assertLess(ids.index(second["post_id"]), ids.index(str(other)), "a save tops the Main feed")

    def test_a_page_already_in_insight_goes_to_later_and_keeps_its_date(self):
        dated = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO sources (platform, handle_or_url, enabled) VALUES ('rss', %s, true) RETURNING id",
                        (f"{SITE}/feed.xml",))
            (source,) = cur.fetchone()
            cur.execute("INSERT INTO posts (source_id, url, title, content, published_at) VALUES (%s, %s, 'An essay', 'Body', %s) "
                        "RETURNING id", (source, ARTICLE_URL, dated))
            (existing,) = cur.fetchone()
        saved_at = datetime.now(timezone.utc).replace(microsecond=0)
        self._at(saved_at)
        status, body = self.save({ARTICLE_URL: ARTICLE})
        self.assertEqual((status, body["status"], body["post_id"]), (200, "already", str(existing)))
        published_at, later_at, _ = self._state(existing)
        self.assertEqual((published_at, later_at), (dated, saved_at))

    def test_only_web_addresses(self):
        for url in ("", "file:///etc/passwd", "javascript:alert(1)"):
            status, body = self.save({}, url=url)
            self.assertEqual(status, 400, (url, body))


if __name__ == "__main__":
    unittest.main()
