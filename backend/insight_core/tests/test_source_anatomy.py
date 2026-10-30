"""Source anatomy (issue 0054): how each source is read and what it gives.

The kind and full-text rules over the real kind registry; every column end to end against a
`_test` database (it commits scratch rows); the route over ASGI.
"""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.schedule import Availability
from insight_core.services.operations_service import OperationsService
from insight_core.services.source_anatomy_service import (
    WINDOW_DAYS, SourceAnatomyService, anatomy_kind, anatomy_row, full_text_mode,
)
from insight_core.tests._db import SCRATCH_PREFIX, db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._ingestion_fakes import FixedClock

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
DAY = timedelta(days=1)
AVAILABILITY = Availability(ytdlp_enabled=False, telegram_credentials=False)


def kinds() -> KindRegistry:
    return KindRegistry.default(KindHttp(), SimpleNamespace())


def resolve(address: str, platform: str = "rss", **settings) -> object:
    return kinds().resolve({"platform": platform, "handle_or_url": address, "settings": settings})


class KindTests(unittest.TestCase):
    def test_every_kind_by_how_it_is_read(self):
        cases = [
            ("https://simonwillison.net/atom/everything/", "rss", {}, "feed"),
            ("https://example.substack.com/feed", "rss", {}, "feed"),
            ("https://www.reddit.com/r/LocalLLaMA/.rss", "rss", {}, "feed"),       # a feed of Reddit is a feed
            ("https://news.example.com/", "rss", {"page_watch": {"prefix": "/news/"}}, "page_watch"),
            ("https://gwern.net/", "rss", {}, "site_reader"),
            ("https://www.lesswrong.com/", "rss", {}, "site_reader"),
            ("https://tg.i-c-a.su/rss/denissexy", "rss", {}, "telegram"),
            ("denissexy", "telegram", {}, "telegram"),
            ("https://nitter.local/karpathy/rss", "rss", {}, "x"),
            ("LocalLLaMA", "reddit", {}, "reddit"),
            ("UC123", "youtube", {}, "youtube"),
            ("Saved", "saved", {}, "saved"),
        ]
        for address, platform, settings, want in cases:
            with self.subTest(address=address):
                self.assertEqual(anatomy_kind(resolve(address, platform, **settings)), want)

    def test_full_text(self):
        feed = resolve("https://a.example/feed")
        self.assertEqual(full_text_mode("feed", feed, {"settings": {}}, pages_read=True), "on")
        self.assertEqual(full_text_mode("feed", feed, {"settings": {}}, pages_read=False), "feed")
        self.assertEqual(full_text_mode("feed", feed, {"settings": {"fetch_full_content": False}}, pages_read=True), "off")
        page = resolve("https://a.example/", page_watch={"prefix": "/p/"})
        self.assertEqual(full_text_mode("page_watch", page, {"settings": {}}, pages_read=False), "on")
        self.assertEqual(full_text_mode("site_reader", resolve("https://gwern.net/"), {"settings": {}}, False), "on")
        self.assertEqual(full_text_mode("telegram", resolve("chan", "telegram"), {"settings": {}}, False), "feed")

    def test_a_source_with_nothing_counts_zero(self):
        kind = resolve("https://a.example/feed")
        health = {"enabled": True, "watchable": False, "watch_changes": False, "status": "due",
                  "interval_hours": 6.0, "interval_basis": "tier", "next_due_at": None, "last_attempt_at": None,
                  "last_outcome": None, "last_error": None, "last_error_at": None}
        row = anatomy_row({"id": "x", "handle_or_url": "https://a.example/feed", "settings": {}}, kind, health, {}, {})
        self.assertEqual(row["recent"], dict.fromkeys(("posts", "read", "stories", "first", "classics", "links"), 0))
        self.assertEqual(row["all"], row["recent"])
        self.assertIsNone(row["display_name"])
        self.assertIsNone(row["watch_changes"])        # a feed cannot watch
        self.assertFalse(row["validators"])            # a feed fetches conditionally, nothing stored yet


@requires_test_db
class AnatomyDbTests(unittest.TestCase):
    """Every column against a `_test` database: scratch sources, posts in and out of the window,
    opens, two stories, links (one a signature), two classics (one hidden), validators, a watched page."""

    def setUp(self):
        self.url = db_url()
        self.mark = uuid.uuid4().hex[:8]
        self.addCleanup(self._clean)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.a = self._source(cur, "a/feed", {"display_name": "Alpha"})
            self.b = self._source(cur, "b/feed", {})
            self.c = self._source(cur, "c/feed", {"fetch_full_content": False})
            self.d = self._source(cur, "d/", {"page_watch": {"prefix": "/p/"}, "watch_changes": True})
            recent, old = NOW - 2 * DAY, NOW - 60 * DAY
            a1 = self._post(cur, self.a, "a1", recent, metadata={"full_content_fetched": True})
            a2 = self._post(cur, self.a, "a2", old)
            self._post(cur, self.a, "a3", recent)
            b1 = self._post(cur, self.b, "b1", recent + DAY)
            b2 = self._post(cur, self.b, "b2", old + DAY)
            d1 = self._post(cur, self.d, "d1", old)
            cur.execute("INSERT INTO post_interactions (post_id, interaction_type) VALUES (%s, 'opened'), (%s, 'opened'), "
                        "(%s, 'reading_session'), (%s, 'favorited')", (a1, a1, b2, b1))
            # S1: a1 reports first, b1 later. S2: a2 shares first, b2 reports later: b2 leads.
            for story, posts in ((a1, ((a1, "report"), (b1, "report"))), (a2, ((a2, "share"), (b2, "report")))):
                cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (story, NOW))
                for post, role in posts:
                    cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice) VALUES (%s, %s, %s, %s)",
                                (post, story, role, post))
            classic, hidden, plain, signature = (f"https://{n}-{self.mark}.test/essay" for n in ("classic", "hidden", "plain", "sig"))
            for post, target, boilerplate in ((a1, classic, False), (a1, hidden, False), (a1, signature, True),
                                              (a2, classic, False), (a2, plain, False), (b2, classic, True)):
                cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, boilerplate) "
                            "VALUES (%s, %s, 'x.test', 0, %s)", (post, target, boilerplate))
            for target in (classic, hidden):
                cur.execute("INSERT INTO classics (target_url, voices, first_at, last_at) VALUES (%s, 2, %s, %s)",
                            (target, old, recent))
            cur.execute("INSERT INTO classic_hidden (target_url) VALUES (%s)", (hidden,))
            cur.execute("INSERT INTO source_fetch_validators (source_id, url, etag, learned_at) VALUES (%s, 'u', 'e', now())",
                        (self.c,))
            cur.execute("INSERT INTO post_watch (post_id, source_id, text_hash, next_check_at) VALUES (%s, %s, 'h', now())",
                        (d1, self.d))
            cur.execute("INSERT INTO source_fetch_state (source_id, last_attempt_at, last_outcome, last_error, "
                        "last_error_at, consecutive_failures) VALUES (%s, %s, 'error', 'HTTP 404', %s, 1)",
                        (self.b, NOW - DAY, NOW - DAY))
            conn.commit()
        self.classic, self.hidden = classic, hidden
        ops = OperationsService(self.url, kinds=kinds(), availability=lambda: AVAILABILITY, clock=FixedClock(NOW))
        result = SourceAnatomyService(self.url, ops).anatomy()
        self.result = result
        self.rows = {r["source_id"]: r for r in result["rows"]}

    def _source(self, cur, path: str, settings: dict) -> str:
        cur.execute("INSERT INTO sources (platform, handle_or_url, enabled, in_main_digest, settings) "
                    "VALUES ('rss', %s, true, false, %s::jsonb) RETURNING id",
                    (f"{SCRATCH_PREFIX}{self.mark}/{path}", json.dumps(settings)))
        return str(cur.fetchone()[0])

    def _post(self, cur, source: str, name: str, at: datetime, metadata: dict | None = None) -> str:
        cur.execute("INSERT INTO posts (source_id, url, published_at, metadata) VALUES (%s, %s, %s, %s::jsonb) RETURNING id",
                    (source, f"{SCRATCH_PREFIX}{self.mark}/post/{name}", at, json.dumps(metadata or {})))
        return str(cur.fetchone()[0])

    def _clean(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("DELETE FROM classics WHERE target_url LIKE %s", (f"%{self.mark}%",))
            cur.execute("DELETE FROM classic_hidden WHERE target_url LIKE %s", (f"%{self.mark}%",))
            conn.commit()

    def counts(self, source: str) -> tuple:
        row = self.rows[source]
        return tuple((row["recent"][k], row["all"][k]) for k in ("posts", "read", "stories", "first", "classics", "links"))

    def test_the_window(self):
        self.assertEqual(self.result["window_days"], WINDOW_DAYS)

    def test_posts_and_read(self):
        # a1 opened twice is one; b2 read for a while; a favorite is no read.
        self.assertEqual(self.counts(self.a)[:2], ((2, 3), (1, 1)))
        self.assertEqual(self.counts(self.b)[:2], ((1, 2), (0, 1)))
        self.assertEqual(self.counts(self.c)[:2], ((0, 0), (0, 0)))

    def test_stories_and_reported_first(self):
        # A leads S1 (its report came first); S2's first post is A's share, but B's report leads it.
        self.assertEqual(self.counts(self.a)[2:4], ((1, 2), (1, 1)))
        self.assertEqual(self.counts(self.b)[2:4], ((1, 2), (0, 1)))
        self.assertEqual(self.counts(self.d)[2:4], ((0, 0), (0, 0)))

    def test_classics_cited(self):
        # The classic once though linked twice; the hidden one not; B's link to it is its signature.
        self.assertEqual(self.counts(self.a)[4], (1, 1))
        self.assertEqual(self.counts(self.b)[4], (0, 0))

    def test_outside_links(self):
        # A: a1 classic + hidden (its signature not), a2 classic + plain.
        self.assertEqual(self.counts(self.a)[5], (2, 4))
        self.assertEqual(self.counts(self.b)[5], (0, 0))

    def test_how_it_is_read(self):
        a, b, c, d = (self.rows[s] for s in (self.a, self.b, self.c, self.d))
        self.assertEqual((a["kind"], a["full_text"], a["display_name"]), ("feed", "on", "Alpha"))
        self.assertEqual((b["full_text"], b["display_name"]), ("feed", None))   # no post needed its page
        self.assertEqual(c["full_text"], "off")
        self.assertEqual((d["kind"], d["full_text"], d["watch_changes"], d["watched_pages"]), ("page_watch", "on", True, 1))
        self.assertIsNone(a["watch_changes"])
        self.assertEqual((a["validators"], c["validators"]), (False, True))
        self.assertTrue(a["address"].endswith("/a/feed"))

    def test_schedule_and_last_fetch(self):
        b = self.rows[self.b]
        self.assertEqual((b["last_outcome"], b["last_error"]), ("error", "HTTP 404"))
        self.assertEqual(b["last_attempt_at"], (NOW - DAY).isoformat())
        self.assertGreater(b["interval_hours"], 0)
        self.assertIn(b["status"], ("error", "backoff", "due"))

    def test_most_posts_in_the_window_first(self):
        mine = [r["source_id"] for r in self.result["rows"] if r["source_id"] in (self.a, self.b, self.c, self.d)]
        self.assertEqual(mine[:2], [self.a, self.b])


class AnatomyRouteTests(unittest.TestCase):
    def test_the_route(self):
        import main
        from insight_core.services import registry
        from insight_core.tests._asgi import call

        answer = {"success": True, "window_days": 30, "generated_at": NOW.isoformat(), "rows": []}
        previous = registry.use(SimpleNamespace(anatomy=SimpleNamespace(anatomy=lambda: answer)))
        self.addCleanup(registry.use, previous)
        status, _, body = call(main.app, "GET", "/api/sources/anatomy")
        self.assertEqual((status, body), (200, answer))


if __name__ == "__main__":
    unittest.main()
