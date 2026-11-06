"""A story's original fetched when INSIGHT lacks it (issues 0114, 0123), on the database.

0114: a story links a followed source's page not stored -> the source is wanted (fetch_linked), once.
0123: Collect originals (off by default) -> a News story's original no followed source owns is read once
and stored as a Saved post by itself, joined to its story as its root; a walled one never is.

No network: FakeHttp answers every page. The tests commit rows, so they run only against a `_test`
database; they own every source and post on the example sites below.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_fetch_state import FetchStateRepository
from insight_core.db.repo_posts import PostsRepository
from insight_core.ingestion.kinds.base import PolitenessProfile
from insight_core.ingestion.schedule import Availability, DecisionKind, cadence_stats, decide_fetch
from insight_core.services.news_service import NewsService
from insight_core.services.originals_service import OriginalsService, collect_on
from insight_core.services.saved_service import SavedService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.utils.addresses import host_of, site_of

LAB = "https://news.oolab.example"
RELEASE = f"{LAB}/news/the-new-release"
ESSAY = "https://essays.ooessay.example/2026/11/05/an-essay-about-the-release"
WALLED = "https://paper.oopaper.example/2026/11/05/the-paywalled-story"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJpZCI6IngifQ.c2lnbmF0dXJl"
LIKE = ("http%.oo___.example%", "http%.oo_____.example%")
PARAGRAPH = "<p>" + "A paragraph of the essay, the page a story's posts link. " * 12 + "</p>"


def essay(date="2026-11-05T06:00:00Z"):
    return (f'<!DOCTYPE html><html><head><title>An essay about the release</title>'
            f'<meta property="og:title" content="An essay about the release"/>'
            f'<meta property="article:published_time" content="{date}"/></head>'
            f'<body><article><h1>An essay about the release</h1>{PARAGRAPH}</article></body></html>')


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@requires_test_db
class OriginalsCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self._clean)
        self._clean()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.lab = self._source("rss", f"{LAB}/feed.xml", name="Example Lab")
        for slug in ("one", "two", "three"):
            self._post(self.lab, f"{LAB}/news/post-{slug}", f"Lab post {slug}", self.now - timedelta(days=5))
        self.a = self._source("rss", "https://a.oochana.example/feed.xml", name="Channel A")
        self.b = self._source("rss", "https://b.oochanb.example/feed.xml", name="Channel B")
        self.c = self._source("rss", "https://c.oochanc.example/feed.xml", name="Channel C")
        self.saved = SavedService(db_url(), sources=mock.Mock(), source_config_sync=mock.Mock(), kinds=mock.Mock(),
                                  clock=lambda: self.now)
        self.saved.saved_source_id = lambda: self._saved_source()

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM story_originals WHERE url LIKE %s OR url LIKE %s", LIKE)
            cur.execute("DELETE FROM posts WHERE url LIKE %s OR url LIKE %s", LIKE)
            cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s OR handle_or_url LIKE %s", LIKE)
            cur.execute("DELETE FROM system_settings WHERE key IN ('scheduler_config', 'originals_budget')")

    def _rows(self, sql, *args):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else None

    def _source(self, platform, handle, *, name=None):
        settings = json.dumps({"display_name": name} if name else {})
        ((source_id,),) = self._rows("INSERT INTO sources (platform, handle_or_url, enabled, settings, created_at) "
                                     "VALUES (%s, %s, true, %s::jsonb, now() - interval '30 days') RETURNING id::text",
                                     platform, handle, settings)
        return source_id

    def _saved_source(self):
        found = self._rows("SELECT id::text FROM sources WHERE handle_or_url = 'https://saved.oosaved.example/'")
        return found[0][0] if found else self._source("saved", "https://saved.oosaved.example/")

    def _post(self, source_id, url, title, at, *, links=()):
        post = {"url": url, "title": title, "content": f"{title}. " + "Words of the post. " * 20, "date": at,
                "external_id": url}
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            post_id, _ = PostsRepository(db_url()).upsert_post(cur, post, source_id)
            for n, target in enumerate(links):
                cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                            (post_id, target, site_of(host_of(target)), n))
            if links:   # read as given: the story job never reads them again from the HTML
                cur.execute("UPDATE posts SET links_scanned_at = now() WHERE id = %s", (post_id,))
        return str(post_id)

    def stories(self):
        clock = lambda: self.now  # noqa: E731
        StoriesService(db_url(), clock=clock, news=NewsService(db_url(), clock=clock)).recompute(full=True)

    def service(self, budget=5):
        return OriginalsService(db_url(), saved=self.saved, clock=lambda: self.now,
                                budget=lambda cur, now: float(budget))

    def story_of(self, post_id):
        found = self._rows("SELECT story_id::text FROM story_posts WHERE post_id = %s::uuid", post_id)
        return found[0][0] if found else None


class FetchLinkedTests(OriginalsCase):
    """0114: a followed source whose page a story links is fetched early."""

    def linked(self, *sources, hours=1, tag=""):
        return [self._post(s, f"https://{s[:4]}.oochan{n}.example/p/{n}{tag}", f"Post {n}{tag} about the new release {n}",
                           self.now - timedelta(hours=hours), links=[RELEASE])
                for n, s in zip("abc", sources)]

    def test_a_story_linking_a_page_makes_its_source_due_once(self):
        a, _ = self.linked(self.a, self.b)
        self.stories()
        self.assertIsNotNone(self.story_of(a), "the two posts are one story by the page they link")
        summary = run(self.service().run())
        self.assertEqual(summary["fetch_linked"], 1)
        ((wanted, url),) = self._rows("SELECT linked_wanted_at, linked_url FROM source_fetch_state WHERE source_id = %s::uuid", self.lab)
        self.assertEqual((wanted, url), (self.now, RELEASE))
        ((kind, outcome, requests),) = self._rows("SELECT kind, outcome, requests FROM story_originals WHERE url = %s", RELEASE)
        self.assertEqual((kind, outcome, requests), ("fetch_linked", "wanted", 1))
        self._rows("UPDATE source_fetch_state SET last_success_at = %s WHERE source_id = %s::uuid", self.now - timedelta(hours=2), self.lab)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            state = FetchStateRepository().load(cur, [self.lab])[self.lab]
        source = {"post_count": 3, "settings": {}, "cadence_tier": "unknown"}
        decision = decide_fetch(cadence_stats(source, state), PolitenessProfile(concurrency_pool="host-lock"),
                                self.now + timedelta(minutes=30), force=False,
                                availability=Availability(ytdlp_enabled=True, telegram_credentials=True))
        self.assertEqual(decision.kind, DecisionKind.FETCH_LINKED)
        self.assertEqual(run(self.service().run())["fetch_linked"], 0, "never asked twice")

    def test_the_ask_settles_found_or_missing(self):
        self.linked(self.a, self.b)
        self.stories()
        run(self.service().run())
        self._rows("UPDATE source_fetch_state SET last_success_at = %s WHERE source_id = %s::uuid",
                   self.now + timedelta(minutes=5), self.lab)
        self.now += timedelta(minutes=10)
        run(self.service().run())
        self.assertEqual(self._rows("SELECT outcome FROM story_originals WHERE url = %s", RELEASE), [("missing",)])

    def test_no_story_no_budget_or_a_recent_fetch_ask_nothing(self):
        self.linked(self.a)
        self.stories()
        self.assertEqual(run(self.service().run())["fetch_linked"], 0, "one post linking it is no story")
        self.linked(self.a, self.b, tag="-2")
        self.stories()
        self.assertEqual(run(self.service(budget=0).run())["fetch_linked"], 0, "no budget left")
        self._rows("INSERT INTO source_fetch_state (source_id, last_attempt_at, last_success_at) VALUES (%s::uuid, %s, %s) "
                   "ON CONFLICT (source_id) DO UPDATE SET last_attempt_at = EXCLUDED.last_attempt_at",
                   self.lab, self.now - timedelta(minutes=5), self.now - timedelta(minutes=5))
        self.assertEqual(run(self.service().run())["fetch_linked"], 0, "fetched 5 minutes ago")


class CreditTests(OriginalsCase):
    """The shared credit: 1% of a request per source the schedule fetched since it was counted, spent per request."""

    def test_the_credit_accrues_from_the_schedule_s_fetches_and_is_spent(self):
        from insight_core.services.originals_service import accrue, spend
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            first = accrue(cur, self.now)   # never counted: from an hour back
            conn.rollback()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO system_settings (key, value) VALUES ('originals_budget', %s::jsonb) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (json.dumps({"credit": 1.5, "counted_at": (self.now - timedelta(hours=1)).isoformat()}),))
            for source in (self.lab, self.a, self.b, self.c):
                cur.execute("INSERT INTO source_fetch_state (source_id, last_attempt_at) VALUES (%s::uuid, %s) "
                            "ON CONFLICT (source_id) DO UPDATE SET last_attempt_at = EXCLUDED.last_attempt_at",
                            (source, self.now - timedelta(minutes=30)))
            cur.execute("SELECT count(*) FROM source_fetch_state WHERE last_attempt_at > %s AND last_attempt_at <= %s",
                        (self.now - timedelta(hours=1), self.now))
            attempts = cur.fetchone()[0]
            credit = accrue(cur, self.now)
            self.assertAlmostEqual(credit, min(3.0, 1.5 + 0.01 * attempts))
            spend(cur, 1)
            cur.execute("SELECT value->>'credit' FROM system_settings WHERE key = 'originals_budget'")
            self.assertAlmostEqual(float(cur.fetchone()[0]), credit - 1)
            self.assertAlmostEqual(accrue(cur, self.now), credit - 1, msg="nothing new to count")
            conn.rollback()
        self.assertGreaterEqual(first, 0.0)


class CollectTests(OriginalsCase):
    """0123: a News story's original collected, when Collect originals is on."""

    def news_story(self, page, *sources):
        posts = [self._post(s, f"https://{s[:4]}.oochan{n}.example/p/essay-{n}", f"Thoughts {n} on an essay {n}",
                            self.now - timedelta(hours=3 - i), links=[page])
                 for i, (n, s) in enumerate(zip("abc", sources))]
        self.stories()
        story = self.story_of(posts[0])
        self.assertIsNotNone(story)
        # News's own rows, as its job writes them (the rules are tested in test_news).
        self._rows("INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score) "
                   "VALUES (%s::uuid, %s, %s, %s, 0, 0, 1) ON CONFLICT (id) DO NOTHING", story, self.now - timedelta(hours=3),
                   len(posts), len(posts))
        for n, post_id in enumerate(posts):
            self._rows("INSERT INTO news_posts (post_id, news_id, role, voice, position) VALUES (%s::uuid, %s::uuid, 'report', %s, %s) "
                       "ON CONFLICT (post_id) DO NOTHING", post_id, story, f"v{n}", n)
        return story, posts

    def switch(self, on, **more):
        self._rows("INSERT INTO system_settings (key, value) VALUES ('scheduler_config', %s::jsonb) "
                   "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                   json.dumps({"collect_originals": on, "collect_originals_default": "on", **more}))

    def test_on_by_default_and_an_explicit_off_collects_nothing(self):
        """Issue 0126 (4): on unless you switched it off; a false the dialog wrote while off was the default is no choice."""
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertTrue(collect_on(cur), "no scheduler row: on")
        self._rows("INSERT INTO system_settings (key, value) VALUES ('scheduler_config', %s::jsonb)",
                   json.dumps({"interval_hours": 20, "collect_originals": False}))
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertTrue(collect_on(cur), "written by the old default's dialog: on")
        self.news_story(ESSAY, self.a, self.b)
        self.switch(False)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            self.assertFalse(collect_on(cur))
        http = FakeHttp({ESSAY: essay()})
        summary = run(self.service().run(http))
        self.assertEqual((summary["collect_on"], summary["collect"], http.requests), (False, [], []))

    def test_on_the_original_is_read_once_and_joins_its_story_as_its_root(self):
        story, posts = self.news_story(ESSAY, self.a, self.b)
        self.switch(True)
        http = FakeHttp({ESSAY: essay()})
        summary = run(self.service().run(http))
        self.assertEqual(summary["collect"], [{"url": ESSAY, "outcome": "collected", "requests": 1}])
        self.assertEqual(http.requests, [ESSAY])
        ((post_id, platform, metadata, published),) = self._rows(
            "SELECT p.id::text, s.platform, p.metadata, p.published_at FROM posts p JOIN sources s ON s.id = p.source_id "
            "WHERE p.normalized_url = %s", ESSAY.replace("https://", "https://"))
        self.assertEqual(platform, "saved")
        self.assertIn("collected_original", metadata)
        self.assertEqual(published, datetime(2026, 11, 5, 6, tzinfo=timezone.utc), "its own date")
        self.assertEqual(self._rows("SELECT count(*) FROM post_reader_state WHERE post_id = %s::uuid AND later_at IS NOT NULL",
                                    post_id), [(0,)], "never in Later: you didn't save it")
        self.stories()
        self.assertEqual(self.story_of(post_id), self.story_of(posts[0]))
        self.assertEqual(self._rows("SELECT parent_id, parent_reason FROM story_posts WHERE post_id = %s::uuid", post_id),
                         [(None, "address")], "the story's root")
        self.assertEqual(run(self.service().run(FakeHttp({})))["collect"], [], "never asked again")

    def test_a_walled_original_is_never_read_and_keeps_no_token(self):
        self.news_story(f"{WALLED}?accessToken={JWT}", self.a, self.b)
        self.switch(True)
        http = FakeHttp({})
        summary = run(self.service().run(http))
        self.assertEqual(http.requests, [])
        self.assertEqual([c["outcome"] for c in summary["collect"]], ["walled"])
        self.assertEqual(self._rows("SELECT url, requests FROM story_originals WHERE kind = 'collect' AND url LIKE %s", WALLED + "%"),
                         [(WALLED, 0)], "the address is stored without its token")

    def test_an_unreadable_page_is_not_stored(self):
        self.news_story(ESSAY, self.a, self.b)
        self.switch(True)
        summary = run(self.service().run(FakeHttp({ESSAY: "<html><body>Sign in to read</body></html>"})))
        self.assertEqual([c["outcome"] for c in summary["collect"]], ["unreadable"])
        self.assertEqual(self._rows("SELECT count(*) FROM posts p JOIN sources s ON s.id = p.source_id "
                                    "WHERE s.platform = 'saved' AND p.normalized_url = %s", ESSAY), [(0,)])

    def test_a_quoted_tweet_is_stored_from_its_quote_with_no_request(self):
        tweet = "https://x.com/someone_oo/status/2118068667103453360"
        result = self.saved.collect_quote(tweet, "The release is out today.", title=None,
                                          at=datetime(2026, 11, 4, 20, tzinfo=timezone.utc))
        self.assertEqual((result["status"], result["requests"]), ("collected", 0))
        ((content, metadata),) = self._rows("SELECT content, metadata FROM posts WHERE id = %s::uuid", result["post_id"])
        self.assertEqual(content, "The release is out today.")
        self.assertTrue(metadata["from_quote"])
        self._rows("DELETE FROM posts WHERE id = %s::uuid", result["post_id"])


if __name__ == "__main__":
    unittest.main()
