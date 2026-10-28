"""The source doctor (issue 0036): a broken source finds its replacement.

The doctor runs over FakeHttp (no network) with a recording store; the switch, the finding's
storage, sources.json and the routes run on the scratch test database.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.ingestion import source_doctor
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.ports import JobProgressSink
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.source_doctor import SourceDoctor, failure_signal, section, should_look
from insight_core.ingestion.types import FetchOutcome, FetchRequest, OutcomeStatus, SourceSelector, Trigger
from insight_core.services import registry as services_registry
from insight_core.services.operations_service import OperationsService, health_row
from insight_core.services.source_config_sync_service import SourceConfigSyncService
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._ingestion_fakes import (
    FakeRunLock,
    FixedClock,
    InMemoryFetchStateStore,
    InMemoryPostSaver,
    InMemorySourceCatalog,
    RecordingInspectionRefresher,
    RecordingProgressSink,
    SpyFetchGates,
)
from insight_core.tests._kind_fakes import FakeHttp, FakeKind
from insight_core.tests.test_feed_finder import dated_section, page, rss
from insight_core.tests.test_page_watch import LISTING, SITE, anthropic
from insight_core.tests.test_page_watch import article as anthropic_article
from insight_core.ingestion.schedule import Availability

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
OLD = "https://arena.ai/blog/rss/"
BLOG = "https://arena.ai/blog/"
NEW_FEED = "https://arena.ai/blog/feed.xml"
GONE = HttpError(f"HTTP 404 while fetching {OLD}: Not Found", status=404)
FLAKY = HttpError(f"HTTP 500 while fetching {OLD}: oops", status=500)


WORKING_AGAIN = {"replacement": None, "dismissed": False, "working_again": True,
                 "note": "temporary error, working again"}


def state(failures: int = 1, **fields) -> FetchStateRow:
    return FetchStateRow(source_id="s1", consecutive_failures=failures, last_outcome="error", **fields)


def arena(handle: str = OLD, **settings) -> dict:
    return {"id": "s1", "platform": "rss", "handle_or_url": handle,
            "settings": {"display_name": "Arena", **settings}}


def blog_with(feed: str) -> dict:
    """arena.ai: the old feed address gone, the blog page linking `feed`."""
    return {OLD: GONE, BLOG: page(f'<link rel="alternate" type="application/rss+xml" href="{feed}">'),
            "https://arena.ai/": page(), feed: rss("Arena blog")}


class RecordingStore:
    def __init__(self, switch_raises: Exception | None = None):
        self.records: list[tuple[str, datetime, dict]] = []
        self.switches: list[tuple[str, str, dict | None]] = []
        self.switch_raises = switch_raises

    def record(self, source_id, *, checked_at, finding):
        self.records.append((source_id, checked_at, finding))

    def switch(self, source_id, url, page_watch):
        if self.switch_raises:
            raise self.switch_raises
        self.switches.append((source_id, url, page_watch))


def doctor(responses, store=None):
    http = FakeHttp(responses)
    store = store or RecordingStore()
    return SourceDoctor(http=http, registry=KindRegistry.default(http, None), store=store,
                        clock=FixedClock(NOW)), http, store


def generic(name="generic_rss"):
    return FakeKind(name)


def look(responses, *, source=None, failures=1, error=GONE, kind="generic_rss", store=None, row=None):
    d, http, store = doctor(responses, store)
    progress = RecordingProgressSink()
    asyncio.run(d.after_failure(source or arena(), generic(kind), row or state(failures), error, progress))
    return store, http, progress


# --------------------------------------------------------------------------- when


class TriggerTests(unittest.TestCase):
    def test_three_failures_in_a_row_or_a_clear_signal(self):
        self.assertFalse(should_look("generic_rss", state(2), None, NOW))
        self.assertTrue(should_look("generic_rss", state(3), None, NOW))
        self.assertTrue(should_look("generic_rss", state(1), "gone", NOW))
        self.assertTrue(should_look("page_watch", state(1), "gone", NOW))

    def test_the_signals(self):
        self.assertEqual(failure_signal(GONE), "gone")
        self.assertEqual(failure_signal(HttpError("HTTP 410", status=410)), "gone")
        self.assertIsNone(failure_signal(FLAKY))
        self.assertIsNone(failure_signal(HttpError("Timed out", timed_out=True)))
        with self.assertRaises(ET.ParseError) as caught:
            ET.fromstring("<!DOCTYPE html><html><body>moved</html>")
        self.assertEqual(failure_signal(caught.exception), "not_feed")
        self.assertIsNone(failure_signal(None))

    def test_at_most_once_a_day(self):
        self.assertFalse(should_look("generic_rss", state(5, doctor_checked_at=NOW - timedelta(hours=23)), "gone", NOW))
        self.assertTrue(should_look("generic_rss", state(5, doctor_checked_at=NOW - timedelta(hours=25)), "gone", NOW))

    def test_not_again_in_a_streak_the_owner_dismissed(self):
        dismissed = state(9, doctor_checked_at=NOW - timedelta(days=3),
                          doctor_finding={"replacement": None, "dismissed": True})
        self.assertFalse(should_look("generic_rss", dismissed, "gone", NOW))

    def test_kinds_that_read_directly_are_skipped(self):
        for kind in ("youtube_channel", "reddit_subreddit", "substack", "telegram_mtproto", "telegram_rss",
                     "nitter_rss", "saved", "hacker_news"):
            self.assertFalse(should_look(kind, state(5), "gone", NOW), kind)

    def test_a_direct_kind_makes_no_request(self):
        store, http, _ = look(blog_with(NEW_FEED), kind="youtube_channel")
        self.assertEqual((store.records, store.switches, http.requests), ([], [], []))

    def test_a_source_of_another_platform_makes_no_request(self):
        store, http, _ = look(blog_with(NEW_FEED), source={**arena(), "platform": "telegram"})
        self.assertEqual((store.records, http.requests), ([], []))

    def test_a_second_failure_without_a_signal_is_left_alone(self):
        store, http, _ = look(blog_with(NEW_FEED), failures=2, error=FLAKY)
        self.assertEqual((store.records, http.requests), ([], []))

    def test_the_section_is_the_address_less_its_last_segment(self):
        self.assertEqual(section("https://arena.ai/blog/rss/"), "https://arena.ai/blog/")
        self.assertEqual(section("https://arena.ai/a/b/feed?x=1"), "https://arena.ai/a/b/")
        self.assertEqual(section("https://arena.ai/feed"), "https://arena.ai/")
        self.assertEqual(section("https://arena.ai/"), "https://arena.ai/")


# --------------------------------------------------------------------------- what it does


class ActTests(unittest.TestCase):
    def test_a_same_site_feed_while_the_old_address_is_gone_is_switched_to(self):
        store, _, progress = look(blog_with(NEW_FEED))
        self.assertEqual(store.switches, [("s1", NEW_FEED, None)])
        self.assertEqual(store.records, [])
        phase, data = progress.events[-1]
        self.assertEqual(phase, "doctor")
        self.assertEqual(data["line"], "Arena: feed moved, now following arena.ai/blog/feed.xml")

    def test_www_is_the_same_site(self):
        feed = "https://www.arena.ai/blog/feed.xml"
        store, _, _ = look(blog_with(feed))
        self.assertEqual(store.switches, [("s1", feed, None)])

    def test_a_page_watch_source_whose_listing_is_gone_moves_to_a_feed(self):
        listing = "https://arena.ai/blog/news"
        responses = {**blog_with(NEW_FEED), listing: GONE}
        store, _, _ = look(responses, source=arena(listing, page_watch={"prefix": "/blog/news/"}), kind="page_watch")
        self.assertEqual(store.switches, [("s1", NEW_FEED, None)])

    def test_a_feed_on_another_site_is_only_suggested(self):
        store, _, progress = look(blog_with("https://feeds.example.com/arena.xml"))
        self.assertEqual(store.switches, [])
        self.assertEqual(progress.events, [])
        (_, checked_at, finding), = store.records
        self.assertEqual(checked_at, NOW)
        self.assertEqual(finding, {"dismissed": False, "replacement": {
            "kind": "feed", "url": "https://feeds.example.com/arena.xml", "title": "Arena blog",
            "found": None, "prefix": None}})

    def test_a_flaky_feed_is_only_suggested(self):
        responses = {**blog_with(NEW_FEED), OLD: FLAKY}
        store, _, _ = look(responses, failures=3, error=FLAKY)
        self.assertEqual(store.switches, [])
        self.assertEqual(store.records[0][2]["replacement"]["url"], NEW_FEED)

    def test_a_feed_that_no_longer_parses_is_only_suggested(self):
        responses = {**blog_with(NEW_FEED), OLD: page()}
        store, _, _ = look(responses, error=ET.ParseError("not xml"))
        self.assertEqual(store.switches, [])
        self.assertEqual(store.records[0][2]["replacement"]["url"], NEW_FEED)

    def test_no_feed_then_the_section_is_followed_as_a_page(self):
        old = f"{SITE}/news/rss"
        responses = anthropic(**{old: GONE, f"{SITE}/": page(), f"{SITE}/news/": anthropic()[LISTING]})
        source = {"id": "s1", "platform": "rss", "handle_or_url": old, "settings": {"display_name": "Anthropic"}}
        store, _, _ = look(responses, source=source)
        self.assertEqual(store.switches, [])
        replacement = store.records[0][2]["replacement"]
        self.assertEqual({k: replacement[k] for k in ("kind", "url", "title", "prefix")},
                         {"kind": "page_watch", "url": f"{SITE}/news/", "title": "anthropic.com/news",
                          "prefix": "/news/"})
        self.assertGreater(replacement["found"], 0)

    def test_a_root_source_is_offered_the_sites_blog_with_the_most_articles_not_its_home_page(self):
        # Issue 0041: the whole site is a root source's section; its home page mixes everything.
        old, home = "https://shop.example/rss", "https://shop.example/"
        responses = {old: GONE, home: page(body='<a href="/press">Press</a><a href="/blog">Blog</a>'
                                                + "".join(f'<a href="/customers/{n}/x">Customer</a>' for n in range(9))),
                     **dated_section("/press", 2), **dated_section("/blog", 5)}
        store, _, _ = look(responses, source={"id": "s1", "platform": "rss", "handle_or_url": old, "settings": {}})
        replacement = store.records[0][2]["replacement"]
        self.assertEqual({k: replacement[k] for k in ("kind", "url", "title", "found", "prefix")},
                         {"kind": "page_watch", "url": "https://shop.example/blog", "title": "shop.example/blog",
                          "found": 5, "prefix": "/blog/"})

    def test_a_root_source_is_offered_a_blog_its_home_page_names_otherwise(self):
        # Issue 0047: no page named blog or news; the menu link that reads as an article list.
        old, home = "https://shop.example/rss", "https://shop.example/"
        responses = {old: GONE, home: page(body='<nav><a href="/pricing">Pricing</a><a href="/now">Now</a></nav>'),
                     "https://shop.example/pricing": page(),
                     **dated_section("/now", 6, published=datetime.now(timezone.utc).isoformat())}
        store, _, _ = look(responses, source={"id": "s1", "platform": "rss", "handle_or_url": old, "settings": {}})
        replacement = store.records[0][2]["replacement"]
        self.assertEqual({k: replacement[k] for k in ("kind", "url", "found", "prefix")},
                         {"kind": "page_watch", "url": "https://shop.example/now", "found": 6, "prefix": "/now/"})

    def test_a_section_source_keeps_its_section_not_the_sites_blog(self):
        # The same-section rule: /news/rss gone is followed as /news/, never the site's /blog.
        old = "https://shop.example/news/rss"
        responses = {old: GONE, "https://shop.example/": page(body='<a href="/blog">Blog</a>'),
                     "https://shop.example/news/": dated_section("/news", 3)["https://shop.example/news"],
                     **dated_section("/news", 3), **dated_section("/blog", 9)}
        store, _, _ = look(responses, source={"id": "s1", "platform": "rss", "handle_or_url": old, "settings": {}})
        self.assertEqual(store.records[0][2]["replacement"]["url"], "https://shop.example/news/")

    def test_nothing_found_is_recorded_as_nothing(self):
        store, _, _ = look({OLD: GONE, BLOG: page(), "https://arena.ai/": page()})
        self.assertEqual(store.switches, [])
        self.assertEqual(store.records[0][2], {"replacement": None, "dismissed": False})

    def test_an_old_address_that_reads_as_a_feed_again_is_working_again(self):
        # Answering again (flaky): the old address is checked first; that is no move, and
        # nothing else is looked at.
        store, http, _ = look({OLD: rss("Arena"), BLOG: page(), "https://arena.ai/": page()}, failures=3, error=FLAKY)
        self.assertEqual(store.switches, [])
        self.assertEqual(store.records, [("s1", NOW, WORKING_AGAIN)])
        self.assertEqual(http.requests, [OLD])

    def test_a_switch_that_fails_is_suggested_instead(self):
        store, _, progress = look(blog_with(NEW_FEED), store=RecordingStore(ValueError("already a source")))
        self.assertEqual(progress.events, [])
        self.assertEqual(store.records[0][2]["replacement"]["url"], NEW_FEED)

    def test_it_never_raises(self):
        class Broken(RecordingStore):
            def record(self, *a, **k):
                raise RuntimeError("database down")

        store, _, _ = look({OLD: GONE}, store=Broken())   # no exception


# --------------------------------------------------------------------------- the server's dry run


class DryRunCaseTests(unittest.TestCase):
    """The three real cases of the dry run on the server's failing sources (2026-10-28)."""

    OLD_NEW_THING = "https://devblogs.microsoft.com/oldnewthing/feed"
    DEVBLOGS = "https://devblogs.microsoft.com/"
    LANDING = "https://devblogs.microsoft.com/landing"

    def _devblogs(self, **overrides):
        # The home page links the feed of every Microsoft blog; the section page none.
        responses = {self.DEVBLOGS: page(f'<link rel="alternate" type="application/rss+xml" href="{self.LANDING}">'),
                     "https://devblogs.microsoft.com/oldnewthing/": page(),
                     self.LANDING: rss("Microsoft Developer Blogs")}
        responses.update(overrides)
        return responses

    def _source(self, handle, name):
        return {"id": "s1", "platform": "rss", "handle_or_url": handle, "settings": {"display_name": name}}

    def test_oldnewthing_a_temporary_error_that_reads_again_suggests_nothing(self):
        ssl = HttpError(f"SSL: CERTIFICATE_VERIFY_FAILED while fetching {self.OLD_NEW_THING}")
        store, http, progress = look(self._devblogs(**{self.OLD_NEW_THING: rss("The Old New Thing")}),
                                     source=self._source(self.OLD_NEW_THING, "The Old New Thing"),
                                     failures=3, error=ssl)
        self.assertEqual((store.switches, progress.events), ([], []))
        self.assertEqual(store.records, [("s1", NOW, WORKING_AGAIN)])
        self.assertEqual(http.requests, [self.OLD_NEW_THING], "nothing else is looked at")

    def test_working_again_shows_no_finding_on_the_health_row(self):
        # Not "looked for a replacement and found none": there was nothing to replace.
        row = health_row({"id": "s1", "platform": "rss", "handle_or_url": self.OLD_NEW_THING, "enabled": True,
                          "settings": {}, "state": state(3, doctor_checked_at=NOW, doctor_finding=WORKING_AGAIN)},
                         generic(), Availability(True, False), NOW)
        self.assertEqual((row["doctor_looked_at"], row["replacement"]), (None, None))

    def test_oldnewthing_gone_never_takes_the_whole_sites_feed(self):
        store, _, _ = look(self._devblogs(**{self.OLD_NEW_THING: GONE}),
                           source=self._source(self.OLD_NEW_THING, "The Old New Thing"))
        self.assertEqual(store.switches, [])
        self.assertEqual(store.records[0][2]["replacement"], None, "devblogs.microsoft.com/landing is all the blogs")

    def test_a_feed_within_the_section_is_still_taken(self):
        inside = "https://devblogs.microsoft.com/oldnewthing/feed/atom"
        responses = self._devblogs(**{
            self.OLD_NEW_THING: GONE,
            "https://devblogs.microsoft.com/oldnewthing/": page(
                f'<link rel="alternate" type="application/rss+xml" href="{self.LANDING}">'
                f'<link rel="alternate" type="application/atom+xml" href="{inside}">'),
            inside: rss("The Old New Thing")})
        store, _, _ = look(responses, source=self._source(self.OLD_NEW_THING, "The Old New Thing"))
        self.assertEqual(store.switches, [("s1", inside, None)])

    def test_joanwestenberg_a_gone_root_feed_moves_to_the_home_pages_feed(self):
        old, new = "https://joanwestenberg.com/rss", "https://www.joanwestenberg.com/feed"
        responses = {old: GONE, "https://joanwestenberg.com/": page(f'<link rel="alternate" type="application/rss+xml" href="{new}">'),
                     new: rss("Joan Westenberg")}
        store, _, progress = look(responses, source=self._source(old, "Joan Westenberg"))
        self.assertEqual(store.switches, [("s1", new, None)])
        self.assertEqual(progress.events[-1][1]["line"], "Joan Westenberg: feed moved, now following joanwestenberg.com/feed")

    def test_incompleteideas_a_page_that_is_no_feed_suggests_following_it(self):
        home = "http://www.incompleteideas.net/"
        essays = [f"/IncIdeas/Essay{n}.html" for n in range(12)]
        listing = page(body="<main><h1>Rich Sutton</h1>" + "".join(f'<a href="{path}">Essay {n}</a>'
                                                                  for n, path in enumerate(essays)) + "</main>")
        responses = {home: listing, **{f"http://www.incompleteideas.net{path}": anthropic_article(f"Essay {n}")
                                       for n, path in enumerate(essays)}}
        store, _, _ = look(responses, source=self._source(home, "Rich Sutton"), error=ET.ParseError("not xml"))
        self.assertEqual(store.switches, [])
        replacement = store.records[0][2]["replacement"]
        self.assertEqual((replacement["kind"], replacement["url"]), ("page_watch", home))
        self.assertEqual(replacement["found"], 12)


# --------------------------------------------------------------------------- the runner and the job


class RecordingDoctor:
    def __init__(self):
        self.calls = []

    async def after_failure(self, source, kind, state, error, progress):
        self.calls.append((source["id"], kind.name, state.consecutive_failures, error))


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def _runner(self, behaviour, doctor):
        source = arena()
        return IngestionRunner(
            catalog=InMemorySourceCatalog([source]), state=InMemoryFetchStateStore(),
            saver=InMemoryPostSaver(), inspections=RecordingInspectionRefresher(),
            registry=KindRegistry([FakeKind("generic_rss", behaviour=behaviour)]), gates=SpyFetchGates(),
            run_lock=FakeRunLock(), availability=lambda: Availability(True, False), clock=FixedClock(NOW),
            rand=lambda: 1.0, doctor=doctor,
        )

    async def test_a_failed_fetch_is_shown_with_its_error_and_fresh_state(self):
        def gone(_s, _n):
            raise GONE

        recording = RecordingDoctor()
        await self._runner(gone, recording).run(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER, force=True))
        self.assertEqual(recording.calls, [("s1", "generic_rss", 1, GONE)])

    async def test_a_fetch_that_works_is_not(self):
        recording = RecordingDoctor()
        await self._runner(lambda s, n: [], recording).run(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER, force=True))
        self.assertEqual(recording.calls, [])


class JobLineTests(unittest.TestCase):
    def test_the_switch_is_a_job_event_line(self):
        ops = mock.Mock()
        JobProgressSink(ops, "job-1").event("doctor", {"line": "Arena: feed moved, now following arena.ai/blog/feed.xml"})
        self.assertEqual(ops.append_job_event.call_args.kwargs["message"],
                         "Arena: feed moved, now following arena.ai/blog/feed.xml")


class RegistryCacheTests(unittest.TestCase):
    def test_an_address_once_resolved_as_a_feed_resolves_as_a_page_once_switched_to_follow_it(self):
        registry = KindRegistry.default(FakeHttp({}), None)
        self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": BLOG}).name, "generic_rss")
        switched = {"platform": "rss", "handle_or_url": BLOG, "settings": {"page_watch": {"prefix": "/blog/"}}}
        self.assertEqual(registry.resolve(switched).name, "page_watch")
        self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": BLOG, "settings": {}}).name,
                         "generic_rss")


# --------------------------------------------------------------------------- the database


@requires_test_db
class SwitchDbTests(unittest.TestCase):
    def setUp(self):
        self.url = db_url()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.json_path = Path(self.tmp.name) / "sources.json"
        self.sync = SourceConfigSyncService(self.url, config_path=self.json_path)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur, settings_json='{"display_name": "Arena"}')
            cur.execute("SELECT handle_or_url FROM sources WHERE id = %s", (self.source_id,))
            self.base = cur.fetchone()[0]
            self.old = f"{self.base}/blog/rss/"
            self.new = f"{self.base}/blog/feed.xml"
            cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s", (self.old, self.source_id))
            cur.execute("INSERT INTO posts (source_id, url, title, content) VALUES (%s, %s, 'One', 'c')",
                        (self.source_id, f"{self.base}/blog/one"))
            cur.execute("INSERT INTO folders (name) VALUES (%s) RETURNING id", (f"doctor-{self.source_id}",))
            self.folder_id = str(cur.fetchone()[0])
            cur.execute("INSERT INTO source_folders (source_id, folder_id) VALUES (%s, %s)", (self.source_id, self.folder_id))
            conn.commit()
        self.repo = FetchStateRepository()
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            self.repo.record_outcome(cur, FetchOutcome(self.source_id, OutcomeStatus.ERROR, 0, "HTTP 404", 0.1),
                                     trigger="scheduler", now=NOW, backoff=lambda n: timedelta(hours=n))
            self.repo.record_doctor(cur, self.source_id, checked_at=NOW, finding={
                "replacement": {"kind": "feed", "url": self.new, "title": "Arena blog", "found": None, "prefix": None},
                "dismissed": False})
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM folders WHERE id = %s", (self.folder_id,))
            delete_scratch_sources(cur)
            conn.commit()

    def _fetch(self, sql):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute(sql, (self.source_id,))
            return cur.fetchone()

    def _addresses_in_json(self):
        document = json.loads(self.json_path.read_text())
        return {s["id"] for p in document["platforms"].values() for s in p["sources"]}

    def test_a_switch_keeps_the_source_and_moves_its_address_and_sources_json(self):
        old = self.sync.switch_source(self.source_id, self.new)
        self.assertEqual(old, {"handle_or_url": self.old, "page_watch": None})
        self.assertEqual(self._fetch("SELECT handle_or_url, settings->>'display_name' FROM sources WHERE id = %s"),
                         (self.new, "Arena"))
        self.assertEqual(self._fetch("SELECT count(*) FROM posts WHERE source_id = %s")[0], 1)
        self.assertEqual(self._fetch("SELECT count(*) FROM source_folders WHERE source_id = %s")[0], 1)
        self.assertEqual(
            self._fetch("SELECT consecutive_failures, next_retry_at, last_error, doctor_checked_at, doctor_finding "
                        "FROM source_fetch_state WHERE source_id = %s"), (0, None, None, None, None))
        addresses = self._addresses_in_json()
        self.assertIn(self.new, addresses)
        self.assertNotIn(self.old, addresses)

    def test_a_switch_to_follow_a_page_and_back_to_a_feed(self):
        self.sync.switch_source(self.source_id, f"{self.base}/blog/", {"prefix": "blog"})
        self.assertEqual(self._fetch("SELECT settings->'page_watch' FROM sources WHERE id = %s")[0], {"prefix": "/blog/"})
        self.sync.switch_source(self.source_id, self.new)
        self.assertEqual(self._fetch("SELECT settings ? 'page_watch', settings->>'display_name' FROM sources WHERE id = %s"),
                         (False, "Arena"))

    def test_when_sources_json_cannot_be_written_the_switch_is_undone(self):
        with mock.patch.object(self.sync, "export_db_to_json", side_effect=OSError("read-only")):
            with self.assertRaises(OSError):
                self.sync.switch_source(self.source_id, self.new)
        self.assertEqual(self._fetch("SELECT handle_or_url FROM sources WHERE id = %s")[0], self.old)

    def test_an_address_that_is_already_a_source_is_refused(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            other = insert_scratch_source(cur)
            cur.execute("SELECT handle_or_url FROM sources WHERE id = %s", (other,))
            taken = cur.fetchone()[0]
            conn.commit()
        with self.assertRaises(ValueError):
            self.sync.switch_source(self.source_id, taken)
        self.assertEqual(self._fetch("SELECT handle_or_url FROM sources WHERE id = %s")[0], self.old)

    def test_the_health_row_carries_the_finding_until_dismissed_or_a_fetch_works(self):
        ops = OperationsService(self.url)
        row = ops.get_source_health_row(self.source_id)
        self.assertEqual(row["replacement"]["url"], self.new)
        self.assertEqual(row["doctor_looked_at"], NOW.isoformat())
        dismissed = ops.dismiss_replacement(self.source_id)
        self.assertEqual((dismissed["replacement"], dismissed["doctor_looked_at"]), (None, None))
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            row = self.repo.load(cur, [self.source_id])[self.source_id]
            self.assertTrue(row.doctor_finding["dismissed"])
            self.repo.record_outcome(cur, FetchOutcome(self.source_id, OutcomeStatus.EMPTY, 0, None, 0.1),
                                     trigger="scheduler", now=NOW, backoff=lambda n: timedelta(hours=n))
            row = self.repo.load(cur, [self.source_id])[self.source_id]
            self.assertEqual((row.doctor_checked_at, row.doctor_finding), (None, None))
            conn.commit()
        with self.assertRaises(LookupError):
            ops.dismiss_replacement(self.source_id)

    def test_the_auto_switch_end_to_end_through_the_db_store(self):
        http = FakeHttp({self.old: GONE, f"{self.base}/blog/": page(
            f'<link rel="alternate" type="application/rss+xml" href="{self.new}">'), self.new: rss("Arena blog")})
        progress = RecordingProgressSink()
        d = SourceDoctor(http=http, registry=KindRegistry.default(http, None), clock=FixedClock(NOW),
                         store=source_doctor.DbDoctorStore(self.url, switch=self.sync.switch_source))
        source = {"id": self.source_id, "platform": "rss", "handle_or_url": self.old, "settings": {"display_name": "Arena"}}
        asyncio.run(d.after_failure(source, FakeKind("generic_rss"), state(1), GONE, progress))
        self.assertEqual(self._fetch("SELECT handle_or_url FROM sources WHERE id = %s")[0], self.new)
        self.assertIn(self.new, self._addresses_in_json())
        self.assertEqual(progress.events[-1][1]["line"],
                         f"Arena: feed moved, now following {source_doctor.short_address(self.new)}")


@requires_test_db
class RouteTests(unittest.TestCase):
    def setUp(self):
        self.url = db_url()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        real = services_registry.build_services(self.url)
        self.services = dataclasses.replace(
            real, source_config_sync=SourceConfigSyncService(self.url, config_path=Path(self.tmp.name) / "sources.json"))
        self.addCleanup(services_registry.use, services_registry.use(self.services))
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            cur.execute("SELECT handle_or_url FROM sources WHERE id = %s", (self.source_id,))
            self.handle = cur.fetchone()[0]
            FetchStateRepository().record_doctor(cur, self.source_id, checked_at=NOW, finding={
                "replacement": {"kind": "page_watch", "url": f"{self.handle}/blog/", "title": "x", "found": 7,
                                "prefix": "/blog/"}, "dismissed": False})
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def test_switch_follows_the_page(self):
        status, _, body = call(main.app, "POST", f"/api/sources/{self.source_id}/switch",
                               json_body={"url": f"{self.handle}/blog/", "page_watch": {"prefix": "/blog/"}})
        self.assertEqual(status, 200, body)
        self.assertEqual((body["handle_or_url"], body["previous"]), (f"{self.handle}/blog/", self.handle))
        source = self.services.sources.get_source_by_id(self.source_id)
        self.assertEqual(source["settings"]["page_watch"], {"prefix": "/blog/"})
        self.assertEqual(self.services.operations.get_source_health_row(self.source_id)["kind"], "page_watch")

    def test_switch_refuses_a_bad_address_and_an_unknown_source(self):
        status, _, _ = call(main.app, "POST", f"/api/sources/{self.source_id}/switch", json_body={"url": ""})
        self.assertEqual(status, 400)
        status, _, _ = call(main.app, "POST", f"/api/sources/{self.source_id}/switch",
                            json_body={"url": "file:///etc/hostname"})
        self.assertEqual(status, 400)
        status, _, _ = call(main.app, "POST", "/api/sources/00000000-0000-0000-0000-000000000000/switch",
                            json_body={"url": "https://test.invalid/mark-ix/none"})
        self.assertEqual(status, 404)

    def test_dismiss_hides_the_finding(self):
        status, _, body = call(main.app, "POST", f"/api/sources/{self.source_id}/replacement/dismiss")
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["row"]["replacement"])
        status, _, _ = call(main.app, "POST", f"/api/sources/{self.source_id}/replacement/dismiss")
        self.assertEqual(status, 200)   # still a finding, still dismissed

    def test_dismiss_without_a_finding_is_a_404(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("UPDATE source_fetch_state SET doctor_finding = NULL WHERE source_id = %s", (self.source_id,))
            conn.commit()
        status, _, _ = call(main.app, "POST", f"/api/sources/{self.source_id}/replacement/dismiss")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
