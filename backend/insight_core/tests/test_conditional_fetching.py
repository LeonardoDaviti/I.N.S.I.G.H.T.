"""Conditional fetching (issue 0044): an unchanged feed costs nothing.

The HTTP layer against a real local server (urllib's own 304, redirect and gzip handling),
AddressMemory's rules, generic RSS and page watch with a memory, the runner end to end over
in-memory ports, and the validators' table in the database.
"""
from __future__ import annotations

import asyncio
import gzip
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.http import (
    VALIDATORS_MAX_AGE,
    AddressMemory,
    Conditional,
    HttpError,
    KindHttp,
    Validators,
)
from insight_core.ingestion.kinds import KindRegistry, page_watch
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.kinds.page_watch import PageWatchKind
from insight_core.ingestion.ports import JobProgressSink
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.schedule import Availability
from insight_core.ingestion.types import FetchRequest, OutcomeStatus, SourceSelector, Trigger
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
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_page_watch import LISTING, SITE, anthropic

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
FEED = '<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title>{}</channel></rss>'
LAST_MODIFIED = "Tue, 27 Oct 2026 08:00:00 GMT"


def rss(*slugs: str) -> str:
    return FEED.format("".join(
        f"<item><title>{slug}</title><link>https://blog.example/{slug}</link>"
        f"<description>The whole of {slug}, in the feed.</description>"
        f"<pubDate>Tue, 27 Oct 2026 08:00:00 GMT</pubDate></item>" for slug in slugs))


# --------------------------------------------------------------------------- the HTTP layer


class _Site(BaseHTTPRequestHandler):
    """/feed: ETag "v1" + Last-Modified, 304 to either. /moved: 301 to /feed. /packed: gzip,
    a 304 that names gzip too. /gone: 404. /plain: no validators."""

    seen: list = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        type(self).seen.append((self.path, self.headers.get("If-None-Match"), self.headers.get("If-Modified-Since")))
        if self.path == "/moved":
            self.send_response(301)
            self.send_header("Location", "/feed")
            self.end_headers()
            return
        if self.path == "/gone":
            self.send_error(404)
            return
        if self.path == "/plain":
            self._send(200, b"<rss/>", {})
            return
        matches = (self.headers.get("If-None-Match") == '"v1"'
                   or self.headers.get("If-Modified-Since") == LAST_MODIFIED)
        packed = self.path == "/packed"
        headers = {"ETag": '"v1"', "Last-Modified": LAST_MODIFIED, **({"Content-Encoding": "gzip"} if packed else {})}
        if matches:
            self._send(304, b"", headers)
        else:
            body = rss("one").encode()
            self._send(200, gzip.compress(body) if packed else body, headers)

    def _send(self, status, body, headers):
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        if status != 304:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)


class ConditionalGetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Site.seen = []

    def get(self, path, validators=None, **kwargs) -> Conditional:
        return asyncio.run(KindHttp(timeout=5).get_conditional(f"{self.base}{path}", validators, **kwargs))

    def test_a_200_gives_the_body_and_its_validators(self):
        answer = self.get("/feed")
        self.assertFalse(answer.not_modified)
        self.assertIn("<title>one</title>", answer.text)
        self.assertEqual(answer.validators, Validators('"v1"', LAST_MODIFIED))
        self.assertEqual(_Site.seen, [("/feed", None, None)])

    def test_the_validators_are_sent_and_a_304_is_not_an_error(self):
        answer = self.get("/feed", Validators('"v1"', LAST_MODIFIED))
        self.assertTrue(answer.not_modified)
        self.assertIsNone(answer.body)
        self.assertEqual(answer.text, "")
        self.assertEqual(answer.validators.etag, '"v1"')
        self.assertEqual(_Site.seen, [("/feed", '"v1"', LAST_MODIFIED)])

    def test_either_validator_alone_is_sent(self):
        self.assertTrue(self.get("/feed", Validators(last_modified=LAST_MODIFIED)).not_modified)
        self.assertTrue(self.get("/feed", Validators(etag='"v1"')).not_modified)
        self.assertEqual(_Site.seen, [("/feed", None, LAST_MODIFIED), ("/feed", '"v1"', None)])

    def test_a_redirect_is_followed_with_the_validators(self):
        answer = self.get("/moved")
        self.assertEqual(answer.url, f"{self.base}/feed")
        self.assertIn("<title>one</title>", answer.text)
        answer = self.get("/moved", Validators('"v1"'))
        self.assertTrue(answer.not_modified)
        self.assertEqual(_Site.seen[-1], ("/feed", '"v1"', None))

    def test_gzip_is_unpacked_and_a_304_naming_gzip_is_still_not_modified(self):
        for kwargs in ({}, {"max_bytes": 100_000}):
            with self.subTest(**kwargs):
                answer = self.get("/packed", **kwargs)
                self.assertIn("<title>one</title>", answer.text)
                answer = self.get("/packed", answer.validators, **kwargs)
                self.assertTrue(answer.not_modified)
                self.assertEqual(answer.headers.get("content-encoding"), "gzip")

    def test_max_bytes_caps_the_body(self):
        self.assertEqual(len(self.get("/feed", max_bytes=10).body), 10)

    def test_other_failures_are_http_errors_and_no_validators_is_falsy(self):
        with self.assertRaises(HttpError) as raised:
            self.get("/gone", Validators('"v1"'))
        self.assertEqual(raised.exception.status, 404)
        self.assertFalse(self.get("/plain").validators)


# --------------------------------------------------------------------------- AddressMemory


def _answers(http: FakeHttp, versions: dict):
    """A server keeping one version of each address ({url: (body, etag)}): a 304 to its own
    ETag, else the body with it. An etag of None sends no validators; an exception is raised."""
    def answer(url):
        body, etag = versions[url]
        if isinstance(body, BaseException):
            raise body
        sent = next((v for u, v in reversed(http.validators_sent) if u == url), None)
        if etag and sent and sent.etag == etag:
            return Conditional(None, url, {"etag": etag}, Validators(etag))
        return body, ({"ETag": etag} if etag else {})
    return answer


class AddressMemoryTests(unittest.IsolatedAsyncioTestCase):
    URL = "https://blog.example/feed"

    def http(self, etag='"v1"'):
        versions = {self.URL: (rss("one"), etag)}
        http = FakeHttp()
        http.responses = _answers(http, versions)
        return http

    async def test_a_200_is_learned_now_and_a_304_keeps_the_date(self):
        http = self.http()
        memory = AddressMemory(now=NOW)
        await memory.get(http, self.URL)
        self.assertEqual(memory.learned, {self.URL: Validators('"v1"', None, NOW)})
        self.assertFalse(memory.unchanged)

        later = AddressMemory(memory.learned, now=NOW + timedelta(days=2))
        answer = await later.get(http, self.URL)
        self.assertTrue(answer.not_modified)
        self.assertTrue(later.unchanged)
        self.assertEqual(later.learned, {self.URL: Validators('"v1"', None, NOW)})
        self.assertFalse(later.changed)

    async def test_validators_past_the_age_limit_are_not_sent(self):
        http = self.http()
        stored = {self.URL: Validators('"v1"', None, NOW)}
        late = NOW + VALIDATORS_MAX_AGE + timedelta(minutes=1)
        self.assertIsNotNone(AddressMemory(stored, now=NOW + VALIDATORS_MAX_AGE).sending(self.URL))
        memory = AddressMemory(stored, now=late)
        self.assertIsNone(memory.sending(self.URL))
        answer = await memory.get(http, self.URL)
        self.assertFalse(answer.not_modified)
        self.assertEqual(memory.learned[self.URL].learned_at, late)   # dated again: a full answer

    async def test_full_sends_nothing_and_forget_keeps_nothing(self):
        stored = {self.URL: Validators('"v1"', None, NOW)}
        memory = AddressMemory(stored, now=NOW, full=True)
        self.assertIsNone(memory.sending(self.URL))
        await memory.get(self.http(), self.URL)
        memory.forget()
        self.assertEqual(memory.learned, {})
        self.assertTrue(memory.changed)

    async def test_an_answer_without_validators_is_not_remembered(self):
        memory = AddressMemory({self.URL: Validators('"old"', None, NOW)}, now=NOW)
        await memory.get(self.http(etag=None), self.URL)
        self.assertEqual(memory.learned, {})

    async def test_a_304_repeating_no_validators_keeps_the_ones_sent(self):
        http = FakeHttp({self.URL: Conditional(None, self.URL, {}, Validators())})
        stored = {self.URL: Validators('"v1"', LAST_MODIFIED, NOW)}
        memory = AddressMemory(stored, now=NOW + timedelta(hours=1))
        await memory.get(http, self.URL)
        self.assertEqual(memory.learned, stored)


# --------------------------------------------------------------------------- the kinds


class GenericRssConditionalTests(unittest.IsolatedAsyncioTestCase):
    URL = "https://blog.example/feed"

    async def test_an_unchanged_feed_is_no_posts_and_reads_no_page(self):
        http = FakeHttp()
        http.responses = _answers(http, {self.URL: (rss("one"), '"v1"')})
        kind = GenericRssKind(http)
        source = {"id": "s", "platform": "rss", "handle_or_url": self.URL, "settings": {}}
        first = AddressMemory(now=NOW)
        self.assertEqual(len(await kind.fetch_latest(source, 10, memory=first)), 1)
        http.requests.clear()
        again = AddressMemory(first.learned, now=NOW)
        self.assertEqual(await kind.fetch_latest(source, 10, memory=again), [])
        self.assertEqual(http.requests, [self.URL])     # no article page, nothing else
        self.assertTrue(again.unchanged)

    async def test_without_memory_it_reads_as_before(self):
        http = FakeHttp({self.URL: rss("one")})
        posts = await GenericRssKind(http).fetch_latest({"handle_or_url": self.URL, "settings": {}}, 10)
        self.assertEqual(len(posts), 1)
        self.assertEqual(http.validators_sent, [])


class PageWatchConditionalTests(unittest.TestCase):
    SITEMAP = f"{SITE}/sitemap.xml"

    def setUp(self):
        page_watch.SKIPPED.clear()
        self.addCleanup(page_watch.SKIPPED.clear)
        self.versions = {url: (body, f'"{n}"') for n, (url, body) in enumerate(anthropic().items())}
        self.versions[f"{SITE}/robots.txt"] = (anthropic()[f"{SITE}/robots.txt"], None)
        self.http = FakeHttp()
        self.http.responses = _answers(self.http, self.versions)
        self.kind = PageWatchKind(self.http)
        self.source = {"id": "s1", "platform": "rss", "handle_or_url": LISTING, "settings": {"page_watch": {}}}

    def fetch(self, memory, limit=10):
        self.http.requests.clear()
        self.http.validators_sent.clear()
        return asyncio.run(self.kind.fetch_latest(self.source, limit, memory=memory))

    def test_the_listing_and_its_sitemap_are_remembered_and_unchanged_is_two_requests(self):
        first = AddressMemory(now=NOW)
        self.assertEqual(len(self.fetch(first)), 5)
        self.assertEqual(set(first.learned), {LISTING, self.SITEMAP})   # robots.txt is read as before
        again = AddressMemory(first.learned, now=NOW)
        self.assertEqual(self.fetch(again), [])
        self.assertEqual(self.http.requests, [LISTING, self.SITEMAP])
        self.assertTrue(again.unchanged)

    def test_a_changed_listing_reads_everything_in_full(self):
        first = AddressMemory(now=NOW)
        self.fetch(first)
        page_watch.SKIPPED.clear()
        body, _ = self.versions[LISTING]
        self.versions[LISTING] = (body, '"new"')
        again = AddressMemory(first.learned, now=NOW + timedelta(hours=1))
        self.fetch(again)
        self.assertEqual(self.http.requests.count(LISTING), 1)   # its full answer is used, not asked twice
        self.assertIsNone(dict(self.http.validators_sent)[self.SITEMAP])
        self.assertFalse(again.unchanged)
        self.assertEqual(again.learned[LISTING].etag, '"new"')

    def test_an_unchanged_listing_with_a_changed_sitemap_is_read_in_full(self):
        first = AddressMemory(now=NOW)
        self.fetch(first)
        body, _ = self.versions[self.SITEMAP]
        self.versions[self.SITEMAP] = (body, '"new"')
        again = AddressMemory(first.learned, now=NOW + timedelta(hours=1))
        self.fetch(again)
        self.assertEqual(self.http.requests[:2], [LISTING, self.SITEMAP])   # asked: 304, then 200
        self.assertIn(LISTING, self.http.requests[2:])                      # the listing again, in full
        self.assertEqual(again.learned[self.SITEMAP].etag, '"new"')

    def test_a_fetch_that_left_candidates_unread_keeps_no_validators(self):
        memory = AddressMemory(now=NOW)
        self.assertEqual(len(self.fetch(memory, limit=1)), 1)
        self.assertEqual(memory.learned, {})

    def test_an_address_without_validators_keeps_none(self):
        body, _ = self.versions[self.SITEMAP]
        self.versions[self.SITEMAP] = (body, None)
        memory = AddressMemory(now=NOW)
        self.fetch(memory)
        self.assertEqual(memory.learned, {})


# --------------------------------------------------------------------------- the runner


class RecordingDoctor:
    def __init__(self):
        self.calls = []

    async def after_failure(self, source, kind, state, error, progress):
        self.calls.append(source["id"])


class RunnerConditionalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.feeds = {"https://a.example/feed": (rss("a1"), '"a"'), "https://b.example/feed": (rss("b1"), None)}
        self.http = FakeHttp()
        self.http.responses = _answers(self.http, self.feeds)
        self.sources = [{"id": f"id-{host}", "platform": "rss", "handle_or_url": f"https://{host}/feed",
                         "enabled": True, "settings": {"display_name": host, "fetch_full_content": False}}
                        for host in ("a.example", "b.example")]
        self.state = InMemoryFetchStateStore()
        self.saver = InMemoryPostSaver()
        self.clock = FixedClock(NOW)
        self.doctor = RecordingDoctor()

    async def fetch(self, selector=None, trigger=Trigger.SCHEDULER):
        self.http.validators_sent.clear()
        self.progress = RecordingProgressSink()
        runner = IngestionRunner(
            catalog=InMemorySourceCatalog(self.sources), state=self.state, saver=self.saver,
            inspections=RecordingInspectionRefresher(), registry=KindRegistry([GenericRssKind(self.http)]),
            gates=SpyFetchGates(), run_lock=FakeRunLock(), availability=lambda: Availability(True, False),
            clock=self.clock, rand=lambda: 1.0, doctor=self.doctor,
        )
        return await runner.run(FetchRequest(selector or SourceSelector.all(), trigger, force=True),
                                progress=self.progress)

    def sent(self, url):
        return next(v for u, v in self.http.validators_sent if u == url)

    def events(self):
        return {data["source_id"]: data for phase, data in self.progress.events if phase == "source"}

    async def test_validators_are_kept_per_address_after_the_save(self):
        await self.fetch()
        self.assertEqual(self.state.validators, {
            "id-a.example": {"https://a.example/feed": Validators('"a"', None, NOW)}})
        self.assertEqual(len(self.saver.known), 2)

    async def test_an_unchanged_feed_is_a_calm_success_and_never_wakes_the_doctor(self):
        await self.fetch()
        self.clock.advance(timedelta(hours=3))
        saves = len(self.state.validator_saves)
        report = await self.fetch()
        self.assertEqual(self.sent("https://a.example/feed"), Validators('"a"', None, NOW))
        a = self.state.rows["id-a.example"]
        self.assertEqual((a.last_outcome, a.consecutive_failures, a.next_retry_at), ("empty", 0, None))
        self.assertEqual(a.last_success_at, NOW + timedelta(hours=3))
        self.assertEqual(self.doctor.calls, [])
        self.assertEqual(report.status, "success")
        events = self.events()
        self.assertTrue(events["id-a.example"]["unchanged"])
        self.assertEqual(events["id-a.example"]["status"], OutcomeStatus.EMPTY.value)
        self.assertFalse(events["id-b.example"]["unchanged"])    # no validators: read in full, as today
        self.assertEqual(len(self.state.validator_saves), saves)  # nothing new to write

    async def test_the_unchanged_line(self):
        await self.fetch()
        await self.fetch()
        lines = []

        class _Ops:
            def append_job_event(self, job_id, *, message, **_kw):
                lines.append(message)

        JobProgressSink(_Ops(), "job").event("source", self.events()["id-a.example"])
        self.assertEqual(lines, ["a.example: unchanged · 1 of 2 sources"])

    async def test_past_the_age_limit_the_feed_is_read_in_full(self):
        await self.fetch()
        self.clock.advance(VALIDATORS_MAX_AGE + timedelta(hours=1))
        await self.fetch()
        self.assertIsNone(self.sent("https://a.example/feed"))
        self.assertEqual(self.state.validators["id-a.example"]["https://a.example/feed"].learned_at, self.clock())

    async def test_fetch_now_on_one_source_reads_in_full(self):
        await self.fetch()
        await self.fetch(SourceSelector.source("id-a.example"), Trigger.MANUAL)
        self.assertIsNone(self.sent("https://a.example/feed"))
        self.assertFalse(self.events()["id-a.example"]["unchanged"])

    async def test_validators_wait_for_the_save(self):
        self.saver.failing_urls = {"https://blog.example/a1"}
        report = await self.fetch()
        self.assertEqual(report.sources_failed, 1)
        self.assertEqual(self.state.validators, {})   # all its posts failed: the next fetch reads in full

    async def test_a_post_that_failed_to_save_forgets_the_validators(self):
        self.feeds["https://a.example/feed"] = (rss("a1", "a2"), '"a"')
        self.saver.failing_urls = {"https://blog.example/a2"}
        await self.fetch()
        self.assertEqual(self.state.rows["id-a.example"].last_outcome, "healthy")
        self.assertEqual(self.state.validators.get("id-a.example", {}), {})

    async def test_a_failing_feed_still_wakes_the_doctor(self):
        self.feeds["https://a.example/feed"] = (HttpError("HTTP 404", status=404), None)
        await self.fetch()
        self.assertEqual(self.doctor.calls, ["id-a.example"])
        self.assertEqual(self.state.validators, {})


# --------------------------------------------------------------------------- the table


try:
    import psycopg

    from insight_core.db.repo_fetch_state import FetchStateRepository
    from insight_core.tests._db import db_url, insert_scratch_source, requires_db
except ImportError:  # pragma: no cover - outside the backend image
    requires_db = unittest.skip("no database driver")


@requires_db
class ValidatorTableTests(unittest.TestCase):
    def setUp(self):
        self.repo = FetchStateRepository()
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.a, self.b = insert_scratch_source(self.cur), insert_scratch_source(self.cur)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_validators_are_per_source_and_address_and_replaced_whole(self):
        listing = Validators('"l"', LAST_MODIFIED, NOW)
        sitemap = Validators(None, LAST_MODIFIED, NOW - timedelta(days=1))
        self.repo.replace_validators(self.cur, self.a, {"https://x.test/news": listing,
                                                        "https://x.test/sitemap.xml": sitemap,
                                                        "https://x.test/none": Validators(learned_at=NOW)})
        self.repo.replace_validators(self.cur, self.b, {"https://x.test/news": Validators('"b"', None, NOW)})
        found = self.repo.load_validators(self.cur, [self.a, self.b])
        self.assertEqual(found[self.a], {"https://x.test/news": listing, "https://x.test/sitemap.xml": sitemap})
        self.assertEqual(found[self.b]["https://x.test/news"].etag, '"b"')

        self.repo.replace_validators(self.cur, self.a, {})
        self.assertEqual(self.repo.load_validators(self.cur, [self.a, self.b]).keys(), {self.b})
        self.assertEqual(self.repo.load_validators(self.cur, []), {})


if __name__ == "__main__":
    unittest.main()
