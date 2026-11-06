"""Fetch them (issue 0084 B, decision 2): a source's own pages that stored posts link and no stored post
is, read one each with the source's own reader, as a job like the archive.

- The kinds' read_post: Substack's API post (a teaser on a publication you don't pay for, as part A
  says), the site reader for websites (the page's article and its own date, 0070); a platform kind
  reads no single page.
- The job: never more than the list; paced by the host gate; a page that is gone (404, 410) or no
  post is listed, not retried; a host that limits twice waits out its window and the scheduler
  continues it (0107), on the same job; the archive's own checkpoint is left as it was.
No network: FakeHttp and fake kinds. Every name is neutral.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_linked import LinkedPage
from insight_core.db.repo_posts import BACKLOG_KEY, SaveBatchResult
from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import KindUnavailable
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.kinds.nitter_rss import NitterRssKind
from insight_core.ingestion.kinds.page_watch import PageWatchKind
from insight_core.ingestion.kinds.substack import SubstackKind
from insight_core.services.archive_jobs import ArchiveJobs
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.tests._ingestion_fakes import SleepClock, SpyFetchGates
from insight_core.tests._kind_fakes import FakeHttp, FakeKind

SITE = "https://blog.example"
PUB = "https://writer.substack.com"
WALL = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def article(title: str, published: str | None) -> str:
    date = f'<meta property="article:published_time" content="{published}">' if published else ""
    return (f'<html><head><title>{title}</title><meta property="og:title" content="{title}">{date}</head>'
            f"<body><article><p>{'What the older post says, at length. ' * 40}</p></article></body></html>")


def site_source() -> dict:
    return {"id": "s-blog", "platform": "rss", "handle_or_url": f"{SITE}/feed", "settings": {}}


class SiteReadPostTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_websites_page_is_its_article_with_the_pages_own_date(self):
        for kind in (GenericRssKind(FakeHttp({f"{SITE}/2020/01/old": article("An old one", "2020-01-02T03:04:05Z")})),
                     PageWatchKind(FakeHttp({f"{SITE}/2020/01/old": article("An old one", "2020-01-02T03:04:05Z")}))):
            post = await kind.read_post(site_source(), f"{SITE}/2020/01/old")
            self.assertEqual(post["url"], f"{SITE}/2020/01/old", kind.name)
            self.assertEqual(post["title"], "An old one")
            self.assertEqual(post["date"], datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
            self.assertTrue(post[BACKLOG_KEY], "an older page: never new to you")
            self.assertGreater(len(post["content"]), 700)

    async def test_a_page_with_no_date_of_its_own_is_not_stored(self):
        """Its real date or nothing (0070): a page stored at the time it was read would sort as new."""
        kind = GenericRssKind(FakeHttp({f"{SITE}/undated": article("Undated", None)}))
        self.assertIsNone(await kind.read_post(site_source(), f"{SITE}/undated"))

    async def test_a_failed_request_raises_for_the_job_to_list(self):
        kind = GenericRssKind(FakeHttp({f"{SITE}/gone": HttpError("HTTP 404 while fetching", status=404)}))
        with self.assertRaises(HttpError):
            await kind.read_post(site_source(), f"{SITE}/gone")

    def test_which_kinds_read_one_page(self):
        self.assertTrue(GenericRssKind(FakeHttp()).reads_posts)
        self.assertTrue(PageWatchKind(FakeHttp()).reads_posts)
        self.assertTrue(SubstackKind(FakeHttp(), sid="").reads_posts)
        self.assertFalse(NitterRssKind(FakeHttp()).reads_posts, "a tweet is not read one page at a time")


class SubstackReadPostTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_paid_post_of_a_publication_you_dont_pay_for_is_its_teaser(self):
        detail = {"id": 7, "slug": "older", "title": "Older", "audience": "only_paid", "body_html": "",
                  "truncated_body_text": "The opening lines.", "wordcount": 3000, "post_date": "2023-04-05T00:00:00Z"}
        http = FakeHttp({f"{PUB}/api/v1/posts/older": json.dumps(detail)})
        post = await SubstackKind(http, sid="").read_post({"platform": "rss", "handle_or_url": f"{PUB}/feed"},
                                                         f"{PUB}/p/older")
        self.assertTrue(post["metadata"]["paywalled"])
        self.assertEqual(post["date"], datetime(2023, 4, 5, tzinfo=timezone.utc))
        self.assertEqual(http.requests, [f"{PUB}/api/v1/posts/older"], "one request, no cookie, nothing more")


# ---- the job --------------------------------------------------------------------------------

def linked(*urls: str) -> list:
    return [LinkedPage(url, "s1", 1, WALL - timedelta(days=1), WALL - timedelta(days=1)) for url in urls]


class _ReadingKind(FakeKind):
    """A website kind whose read_post answers from a script: a post, None (no post page) or an error."""

    reads_posts = True

    def __init__(self, answers: dict):
        super().__init__("fake_site")
        self.answers = answers
        self.read: list[str] = []

    async def read_post(self, source, url):
        self.read.append(url)
        answer = self.answers[url]
        if isinstance(answer, list):   # one answer per ask
            answer = answer.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return None if answer is None else {"url": url, "title": url, "content": "x", "date": WALL - timedelta(days=400)}


class _Posts:
    def get_source_post_stats(self, _source_id):
        return {"post_count": 3}


class _Sources:
    def __init__(self):
        self.archive = {"checkpoint": {"mode": "fake", "offset": 24, "pages_fetched": 2, "collected_posts": 24},
                        "resume_ready": True, "status": "partial"}
        self.writes: list = []

    def get_source_by_id(self, source_id):
        return {"id": source_id, "platform": "rss", "handle_or_url": f"{SITE}/feed", "settings": {}}

    def get_source_with_settings(self, source_id):
        return {**self.get_source_by_id(source_id), "settings": {"archive": self.archive}}

    def merge_source_settings(self, _source_id, settings):
        self.writes.append(settings)


LIMITED = HttpError("HTTP 429 while fetching", status=429, retry_after=4)


class FetchLinkedTests(unittest.IsolatedAsyncioTestCase):
    def service(self, kind, pages):
        self.clock = SleepClock()
        self.wall = lambda: WALL + timedelta(seconds=self.clock.now)
        self.gates = SpyFetchGates(clock=self.clock, sleep=self.clock.sleep, host_floors={"blog.example": 2.0})
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]),
                                     gates=self.gates, clock=self.wall)
        service.sources_service = self.sources = _Sources()
        service.posts_service = _Posts()
        service.archive_metadata = ArchiveMetadataWriter(posts=service.posts_service, sources=self.sources)
        service.linked_pages = lambda source_id: pages
        self.saved: list = []
        service._save_posts = lambda _sid, posts: (self.saved.extend(posts), SaveBatchResult(
            inserted_ids=[p["url"] for p in posts]))[1]
        return service

    async def test_each_page_once_through_the_host_gate_and_the_missing_ones_listed(self):
        urls = [f"{SITE}/p/a", f"{SITE}/p/gone", f"{SITE}/p/not-a-post", f"{SITE}/p/b"]
        kind = _ReadingKind({urls[0]: "post", urls[1]: HttpError("HTTP 404 while fetching", status=404),
                             urls[2]: None, urls[3]: "post"})
        service = self.service(kind, linked(*urls))
        plan = await service.plan_linked("s1")
        self.assertEqual((plan["linked"], plan["estimated_pages"]), (4, 4))
        self.assertEqual(plan["estimated_seconds"], 4 + 3 * 2, "a second a page and the host's 2 s between them")
        events = []
        result = await service.fetch_linked("s1", progress_callback=events.append)
        self.assertEqual(kind.read, urls, "each page of the list once, nothing else")
        self.assertEqual([p["url"] for p in self.saved], [urls[0], urls[3]])
        self.assertTrue(all(p[BACKLOG_KEY] for p in self.saved))
        self.assertEqual(self.gates.slots, [("host-lock", "blog.example")] * 5, "each page, and the ask that finds the end")
        self.assertEqual(self.clock.sleeps, [2, 2, 2, 2], "the host's gap before pages 2-4 and the ask that finds the end")
        self.assertEqual(result["posts_inserted"], 2)
        self.assertEqual(result["missing"], [{"url": urls[1], "reason": "HTTP 404", "status": 404},
                                             {"url": urls[2], "reason": "no post on the page"}])
        self.assertEqual(result["message"], "Fetched 2 of 4 linked pages; 2 not stored (listed)")
        self.assertEqual(events[-1]["stage"], "completed")
        self.assertEqual(self.sources.writes, [], "the archive's own checkpoint and counts are left as they were")

    async def test_a_host_that_limits_twice_waits_and_the_scheduler_continues_the_same_list(self):
        urls = [f"{SITE}/p/a", f"{SITE}/p/b", f"{SITE}/p/c"]
        kind = _ReadingKind({urls[0]: "post", urls[1]: [LIMITED, LIMITED, "post"], urls[2]: "post"})
        service = self.service(kind, linked(*urls))
        result = await service.fetch_linked("s1")
        self.assertTrue(result["waiting"])
        self.assertEqual(result["checkpoint"]["next_index"], 1)
        self.clock.now += 5 * 60
        service.linked_pages = lambda source_id: self.fail("a continuation reuses its list")
        result = await service.continue_archive("s1", result)
        self.assertNotIn("waiting", result)
        self.assertEqual(kind.read, [urls[0], urls[1], urls[1], urls[1], urls[2]])
        self.assertEqual((result["posts_fetched"], result["posts_inserted"]), (3, 3), "the counts carry across the wait")
        self.assertEqual(self.sources.writes, [])

    async def test_nothing_linked_is_nothing_to_do(self):
        service = self.service(_ReadingKind({}), [])
        result = await service.fetch_linked("s1")
        self.assertEqual((result["success"], result["posts_fetched"]), (True, 0))
        self.assertEqual(result["message"], "Every page your posts link is stored")

    async def test_a_kind_that_reads_no_single_page_refuses(self):
        service = self.service(FakeKind("fake_platform"), linked(f"{SITE}/p/a"))
        with self.assertRaises(KindUnavailable) as ctx:
            await service.fetch_linked("s1")
        self.assertIn("one page at a time", ctx.exception.reason)

    async def test_an_expired_session_stops_it(self):
        kind = _ReadingKind({f"{SITE}/p/a": KindUnavailable("Substack session expired")})
        with self.assertRaises(KindUnavailable):
            await self.service(kind, linked(f"{SITE}/p/a")).fetch_linked("s1")


class LinkedSummaryInAThreadTests(unittest.TestCase):
    def test_the_estimate_needs_no_event_loop(self):
        """The route runs linked_summary in a worker thread; with the process's shared gates (no gates passed) the
        estimate read FetchGates.shared(), which needs a running loop, and the line answered 500 for every source
        (v10.0.2 review)."""
        import threading
        kind = _ReadingKind({})
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]), clock=lambda: WALL)
        found: list = []
        thread = threading.Thread(target=lambda: found.append(
            service._linked_estimate(kind, {"handle_or_url": f"{SITE}/feed", "settings": {}}, 3)))
        thread.start()
        thread.join()
        self.assertEqual(len(found), 1, "the estimate raised in a thread with no event loop")
        self.assertGreaterEqual(found[0], 3)


class _Ops:
    def __init__(self):
        self.started, self.finished = [], []

    def try_start_job(self, job_type, **kwargs):
        self.started.append((job_type, kwargs))
        return "job-1"

    def try_append_job_event(self, *args, **kwargs):
        pass

    def try_finish_job(self, job_id, **kwargs):
        self.finished.append((job_id, kwargs))


class _Archives:
    def __init__(self):
        self.calls = []

    async def fetch_linked(self, source_id, progress_callback=None):
        self.calls.append(("linked", source_id))
        return {"success": True, "posts_fetched": 1, "message": "Fetched 1 of 1 linked pages"}

    async def archive_source(self, source_id, **kwargs):
        self.calls.append(("archive", source_id))
        return {"success": True}


class LinkedJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_linked_fetch_is_an_archive_job_of_its_source(self):
        ops, archives = _Ops(), _Archives()
        result = await ArchiveJobs(ops, archives, trigger="manual").run("s1", linked=True)
        self.assertEqual(archives.calls, [("linked", "s1")])
        self.assertEqual(ops.started[0][0], "archive_source", "one archive job per source at a time, as any archive")
        self.assertTrue(ops.started[0][1]["payload"]["linked"])
        self.assertEqual(ops.finished[0][1]["message"], "Fetched 1 of 1 linked pages")
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
