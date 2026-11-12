"""Paywalls named right, a Substack on its own domain read as one, and following a feed fetching its archive
(issue 0167, parts 3 and 2).

No network: every page, feed and API answer is FakeHttp's. The follow-archive tests commit rows (sources, the
queued job), so they run only against a `_test` database; they own the sources on the invented sites below.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion import full_text
from insight_core.ingestion.inspection import DbInspectionRefresher
from insight_core.ingestion.kinds import KindRegistry, page_watch, paywall, substack
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.source_doctor import SourceDoctor
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._ingestion_fakes import FixedClock
from insight_core.tests._kind_fakes import FakeHttp, FakeKind

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
POST = "https://letters.pwexample.example/p/the-long-read"
PARAS = "".join(f"<p>Paragraph {n} of the free part, the opening of a long read for paying readers.</p>" for n in range(12))
TEASER = "The opening of a long read for paying readers."


def page(head: str = "", body: str = "<article><h1>The long read</h1><p>" + TEASER + "</p></article>") -> str:
    return f"<html><head><title>The long read</title>{head}</head><body>{body}</body></html>"


def ld(free) -> str:
    return ('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "NewsArticle",
                                                                "headline": "The long read", "isAccessibleForFree": free})
            + "</script>")


def preloads(state: dict) -> str:
    return f"<script>window._preloads = JSON.parse({json.dumps(json.dumps(state))})</script>"


class MarkerTests(unittest.TestCase):
    def test_schema_orgs_flag_as_json_ld_or_microdata(self):
        self.assertEqual(paywall.marker(page(ld(False))), "isAccessibleForFree")
        self.assertEqual(paywall.marker(page(ld("False"))), "isAccessibleForFree")
        self.assertIsNone(paywall.marker(page(ld(True))))
        self.assertEqual(paywall.marker(page(body='<div itemprop="isAccessibleForFree" content="false"></div>')),
                         "isAccessibleForFree")

    def test_a_locked_content_tier_is_one_a_metered_one_is_not(self):
        self.assertEqual(paywall.marker(page('<meta property="article:content_tier" content="locked">')), "content_tier")
        self.assertIsNone(paywall.marker(page('<meta property="article:content_tier" content="metered">')))

    def test_a_substack_pages_own_post_not_the_posts_it_recommends(self):
        self.assertEqual(paywall.marker(page(preloads({"post": {"audience": "only_paid"}}))), "audience:only_paid")
        self.assertEqual(paywall.marker(page(preloads({"post": {"audience": "only_subscribers"}}))),
                         "audience:only_subscribers")
        free = {"post": {"audience": "everyone"}, "recommendedPosts": [{"audience": "only_paid"}]}
        self.assertIsNone(paywall.marker(page(preloads(free))))
        self.assertIsNone(paywall.marker(page()))


class PageReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_paywalled_page_with_nothing_longer_says_so(self):
        http = FakeHttp({POST: page(ld(False))})
        read = await full_text.read_page(http, POST, TEASER, title="The long read", site="https://letters.pwexample.example/feed")
        self.assertEqual((read.outcome, read.article), (full_text.PAYWALLED, None))
        meta = full_text.with_outcome({"metadata": {}}, read.outcome, NOW)["metadata"]
        self.assertTrue(meta["paywalled"])
        self.assertEqual(full_text.teaser_reason(meta), "for paid subscribers")

    async def test_a_paywalled_pages_longer_free_part_is_taken_and_marked(self):
        http = FakeHttp({POST: page(ld(False), f"<article><h1>The long read</h1><p>{TEASER}</p>{PARAS}</article>")})
        read = await full_text.read_page(http, POST, TEASER, title="The long read", site="https://letters.pwexample.example/feed")
        self.assertEqual(read.outcome, full_text.PAYWALLED)
        self.assertIsNotNone(read.article)
        post = full_text.with_outcome(full_text.with_full_text({"metadata": {}}, *read.article), read.outcome, NOW)
        self.assertEqual(full_text.teaser_reason(post["metadata"]), "for paid subscribers")

    def test_a_substack_kinds_paid_teaser_says_so_and_a_free_page_with_nothing_longer_as_before(self):
        self.assertEqual(full_text.teaser_reason({"substack": True, "audience": "only_paid", "paywalled": True}),
                         "for paid subscribers")
        meta = full_text.with_outcome({"metadata": {}}, full_text.NOTHING_LONGER, NOW)["metadata"]
        self.assertNotIn("paywalled", meta)

    def test_a_watched_page_for_paying_readers_is_marked(self):
        post = page_watch.article_post(page(ld(False), f"<article><h1>The long read</h1>{PARAS}</article>"),
                                       "https://letters.pwexample.example/", POST, NOW, adapter="page_watch")
        self.assertTrue(post["metadata"]["paywalled"])
        free = page_watch.article_post(page("", f"<article><h1>The long read</h1>{PARAS}</article>"),
                                       "https://letters.pwexample.example/", POST, NOW, adapter="page_watch")
        self.assertNotIn("paywalled", free["metadata"])


SUBSTACK_FEED = ('<?xml version="1.0"?><rss version="2.0"><channel><title>Letters</title><link>https://letters.pwexample.example</link>'
                 '<generator>Substack</generator><item><title>The long read</title>'
                 f'<link>{POST}</link><guid>{POST}</guid><pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate>'
                 f'<description>{TEASER}</description></item></channel></rss>')
ASSETS_FEED = SUBSTACK_FEED.replace("<generator>Substack</generator>", "").replace(
    "<description>", '<description>&lt;img src="https://substackcdn.com/image/fetch/x.png"&gt;')
PLAIN_FEED = SUBSTACK_FEED.replace("<generator>Substack</generator>", "")
API = "https://letters.pwexample.example/api/v1/archive?sort=new&limit=1"
FEED = "https://letters.pwexample.example/feed"


class SubstackOnItsDomainTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_substack_generator_is_enough(self):
        http = FakeHttp({FEED: SUBSTACK_FEED})
        self.assertEqual(await substack.recognise(http, FEED), "generator")
        self.assertEqual(http.requests, [FEED])

    async def test_its_assets_need_its_api_to_answer_as_substacks(self):
        api = json.dumps([{"slug": "the-long-read", "post_date": "2026-11-09T10:00:00Z", "audience": "only_paid"}])
        self.assertEqual(await substack.recognise(FakeHttp({FEED: ASSETS_FEED, API: api}), FEED), "assets+api")
        self.assertIsNone(await substack.recognise(FakeHttp({FEED: ASSETS_FEED, API: "<html>not found</html>"}), FEED))

    async def test_a_feed_with_no_sign_costs_no_request_more_and_substacks_own_hosts_are_none(self):
        http = FakeHttp({FEED: PLAIN_FEED})
        self.assertIsNone(await substack.recognise(http, FEED))
        self.assertEqual(http.requests, [FEED])
        self.assertIsNone(await substack.recognise(FakeHttp(), "https://letters.substack.com/feed"))

    async def test_a_live_fetch_of_its_feed_says_what_it_is_and_the_runner_records_it(self):
        kind = GenericRssKind(FakeHttp({FEED: SUBSTACK_FEED}))
        got = await kind.fetch_latest({"id": "s1", "platform": "rss", "handle_or_url": FEED,
                                       "settings": {"fetch_full_content": False}}, 20)
        self.assertEqual(got.recognised, {"substack": True})
        plain = await GenericRssKind(FakeHttp({FEED: PLAIN_FEED})).fetch_latest(
            {"id": "s1", "platform": "rss", "handle_or_url": FEED, "settings": {"fetch_full_content": False}}, 20)
        self.assertIsNone(plain.recognised)
        merged = []
        writer = SimpleNamespace(sources=SimpleNamespace(merge_source_settings=lambda sid, s: merged.append((sid, s))))
        refresher = DbInspectionRefresher(writer=writer)
        await refresher.recognised({"id": "s1", "settings": {}}, {"substack": True})
        await refresher.recognised({"id": "s2", "settings": {"substack": True}}, {"substack": True})
        self.assertEqual(merged, [("s1", {"substack": True})])
        self.assertTrue(substack.SubstackKind(FakeHttp()).matches({"handle_or_url": FEED, "settings": {"substack": True}}))

    async def test_the_source_doctor_recognises_it(self):
        class Store:
            def __init__(self):
                self.records, self.merged = [], []

            def record(self, source_id, *, checked_at, finding):
                self.records.append(finding)

            def merge_settings(self, source_id, settings):
                self.merged.append((source_id, settings))

            def items(self, source_id):
                return []

            def switch(self, *args):
                raise AssertionError("no switch")

        http, store = FakeHttp({FEED: SUBSTACK_FEED}), Store()
        doctor = SourceDoctor(http=http, registry=KindRegistry.default(http, None), store=store, clock=FixedClock(NOW))
        row = FetchStateRow(source_id="s1", consecutive_failures=3, last_outcome="error")
        await doctor.after_failure({"id": "s1", "platform": "rss", "handle_or_url": FEED, "settings": {}},
                                   FakeKind("generic_rss"), row, HttpError("HTTP 500", status=403))
        self.assertEqual(store.merged, [("s1", {"substack": True})])
        self.assertEqual(store.records[0]["recognised"], "substack")


# --------------------------------------------------------------------------- following a feed fetches its archive

@requires_test_db
class FollowArchiveTests(unittest.TestCase):
    SITE = "https://blog.fwexample.example"

    def setUp(self):
        import main
        from insight_core.services import registry

        self.main = main
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        self.addCleanup(self._clean)
        self._clean()

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM job_runs WHERE source_id IN (SELECT id FROM sources WHERE handle_or_url LIKE %s)",
                        ("%fwexample.example%",))
            cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s", ("%fwexample.example%",))

    def add(self, body):
        from insight_core.tests._asgi import call

        with mock.patch.object(self.main, "_export_sources_json"), \
                mock.patch.object(self.main, "FEED_FINDER_HTTP", FakeHttp({f"{self.SITE}/feed.xml": PLAIN_FEED})):
            status, _, answer = call(self.main.app, "POST", "/api/sources", json_body=body)
        self.assertEqual(status, 200, answer)
        return answer

    def _jobs(self, source_id):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT status, payload FROM job_runs WHERE job_type = 'archive_source' AND source_id = %s",
                        (source_id,))
            return cur.fetchall()

    def test_following_a_feed_queues_its_archive_back_to_the_horizon(self):
        from insight_core.services import follow_archive

        answer = self.add({"platform": "rss", "handle_or_url": f"{self.SITE}/feed.xml"})
        self.assertTrue(answer["archive"]["queued"], answer)
        ((status, payload),) = self._jobs(answer["source_id"])
        self.assertEqual(status, "queued")
        self.assertEqual(payload["until"], answer["archive"]["until"])
        self.assertEqual(answer["archive"]["until"], follow_archive.horizon(db_url()))

    def test_a_disabled_source_a_page_watch_or_an_aggregator_is_not_archived_by_itself(self):
        off = self.add({"platform": "rss", "handle_or_url": f"{self.SITE}/off.xml", "state": "disabled"})
        self.assertFalse(off["archive"]["queued"])
        watched = self.add({"platform": "rss", "handle_or_url": f"{self.SITE}/news/", "page_watch": {"prefix": "/news/"}})
        self.assertFalse(watched["archive"]["queued"])
        aggregator = self.add({"platform": "rss", "handle_or_url": "https://hnrss.org/newest?q=fwexample.example"})
        self.assertFalse(aggregator["archive"]["queued"])   # months of other sites' pages: archived by hand
        self.assertEqual(self._jobs(off["source_id"]) + self._jobs(watched["source_id"])
                         + self._jobs(aggregator["source_id"]), [])

    def test_the_horizon_is_the_reading_window_in_days_else_the_default_depth(self):
        from insight_core.services import follow_archive

        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('mx_settings') IS NOT NULL")
            if not cur.fetchone()[0]:
                self.skipTest("no mx_settings")
            cur.execute("SELECT value FROM mx_settings WHERE key = 'reading_window_days'")
            before = cur.fetchone()
            self.addCleanup(self._restore, before)
            cur.execute("INSERT INTO mx_settings (key, value) VALUES ('reading_window_days', '45'::jsonb) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value")
        self.assertEqual(follow_archive.horizon(db_url(), NOW), "2026-09-28")
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("UPDATE mx_settings SET value = 'null'::jsonb WHERE key = 'reading_window_days'")
        self.assertEqual(follow_archive.horizon(db_url(), NOW), "2026-05-16")   # FOLLOW_ARCHIVE_DAYS, 180

    def _restore(self, before):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            if before is None:
                cur.execute("DELETE FROM mx_settings WHERE key = 'reading_window_days'")
            else:
                cur.execute("UPDATE mx_settings SET value = %s::jsonb WHERE key = 'reading_window_days'",
                            (json.dumps(before[0]),))

    def test_existing_sources_on_demand(self):
        from insight_core.scripts import archive_on_follow_0167 as script
        from insight_core.services import registry

        with mock.patch("insight_core.services.follow_archive.queue_on_follow",
                        return_value={"queued": False, "reason": "held"}):
            answer = self.add({"platform": "rss", "handle_or_url": f"{self.SITE}/older.xml"})
        services = registry.services()
        jobs = self.main._archive_jobs()
        dry = script.run(services, jobs, db_url(), source_id=answer["source_id"])
        self.assertEqual([row["source_id"] for row in dry["sources"]], [answer["source_id"]])
        self.assertEqual(self._jobs(answer["source_id"]), [])
        script.run(services, jobs, db_url(), apply=True, source_id=answer["source_id"])
        self.assertEqual([status for status, _ in self._jobs(answer["source_id"])], ["queued"])


if __name__ == "__main__":
    unittest.main()
