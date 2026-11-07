"""Issue 0130 B and C: archives that work again, and archives back to a date.

No network: every answer is a fixture on an invented host, shaped like what the owner's server met on 2026-11-07
(plan/research/0130-notes.md, private): a newsletter platform's archive API answering HTTP 400 to offset=0, a
weekly newsletter's issue pages that no longer carry the payload its reader parsed, a feed answering 404, and
page-watched sites finishing "success, 0 new". What the real sites answer now is unverified until the owner's
server runs these archives.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.adapters.deeplearning_batch_adapter import DeepLearningBatchAdapter  # noqa: E402
from insight_core.db.repo_fetch_state import FetchStateRow  # noqa: E402
from insight_core.db.repo_posts import SaveBatchResult  # noqa: E402
from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter  # noqa: E402
from insight_core.ingestion.http import HttpError  # noqa: E402
from insight_core.ingestion.kinds import KindRegistry  # noqa: E402
from insight_core.ingestion.kinds.base import ArchivePage, Inspection, RateLimit  # noqa: E402
from insight_core.ingestion.kinds.page_watch import PageWatchKind  # noqa: E402
from insight_core.ingestion.kinds.substack import SITEMAP_MODE, SubstackKind  # noqa: E402
from insight_core.services.source_fetch_service import FeedMoved, SourceFetchService, why_line  # noqa: E402
from insight_core.tests._ingestion_fakes import SpyFetchGates  # noqa: E402
from insight_core.tests._kind_fakes import FakeHttp, FakeKind  # noqa: E402

RATE = RateLimit(page_delay_s=0, batch_size=0, batch_cooldown_s=0)
# An article's body: sentences a reader keeps (repeated words read as no article).
PROSE = "".join(f"<p>Paragraph {n} reports how the {w} model changed the field this week, with numbers and a quote.</p>"
                for n, w in enumerate(["first", "second", "third", "fourth", "fifth", "sixth"]))
PUB = "https://letters.example"
REFUSED = HttpError(f'HTTP 400 while fetching {PUB}/api/v1/archive?sort=new&offset=0&limit=12: '
                    '{"param":"offset","value":"0","msg":"Invalid value"}', status=400)


def _sitemap(*locs: tuple) -> str:
    urls = "".join(f"<url><loc>{loc}</loc><lastmod>{mod}</lastmod></url>" for loc, mod in locs)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'


def _sub_post(slug: str, day: int) -> dict:
    return {"id": day, "slug": slug, "audience": "everyone", "wordcount": 20, "title": f"Letter {slug}",
            "post_date": f"2026-10-{day:02d}T08:00:00Z", "canonical_url": f"{PUB}/p/{slug}",
            "body_html": "<p>" + " ".join(["word"] * 20) + "</p>"}


async def _pages(kind, source, checkpoint=None, target=1000):
    return [page async for page in kind.archive_pages(source, target, checkpoint, RATE)]


class NewsletterArchiveTests(unittest.IsolatedAsyncioTestCase):
    """B1: the platform's archive API answered HTTP 400 to offset=0."""

    def source(self):
        return {"id": "s1", "platform": "rss", "handle_or_url": f"{PUB}/", "settings": {"substack": True}}

    async def test_the_first_page_is_asked_with_no_offset(self):
        http = FakeHttp({
            f"{PUB}/api/v1/archive?sort=new&limit=12": json.dumps([{"slug": "a"}]),
            f"{PUB}/api/v1/posts/a": json.dumps(_sub_post("a", 3)),
        })
        pages = await _pages(SubstackKind(http, sid=""), self.source())
        self.assertEqual([p["url"] for page in pages for p in page.posts], [f"{PUB}/p/a"])
        self.assertNotIn("offset=0", " ".join(http.requests))

    async def test_a_refused_archive_api_is_read_from_the_sitemap_leaving_stored_posts_unread(self):
        sitemap = _sitemap((f"{PUB}/p/old", "2026-09-01"), (f"{PUB}/p/new", "2026-10-05"), (f"{PUB}/p/kept", "2026-10-01"),
                           (f"{PUB}/about", "2026-10-06"), ("https://elsewhere.example/p/x", "2026-10-07"))
        http = FakeHttp({
            f"{PUB}/api/v1/archive?sort=new&limit=12": REFUSED,
            f"{PUB}/sitemap.xml": sitemap,
            f"{PUB}/api/v1/posts/new": json.dumps(_sub_post("new", 5)),
            f"{PUB}/api/v1/posts/old": json.dumps(_sub_post("old", 1)),
        })
        kind = SubstackKind(http, sid="", stored_urls=lambda urls: {u for u in urls if u.endswith("/kept")})
        pages = await _pages(kind, self.source())
        self.assertEqual([p["url"] for page in pages for p in page.posts], [f"{PUB}/p/new", f"{PUB}/p/old"],
                         "newest lastmod first; not the stored one, nor a page or another site")
        checkpoint = pages[-1].checkpoint
        self.assertEqual(checkpoint["mode"], SITEMAP_MODE)
        self.assertEqual(checkpoint["skipped"]["stored"], 1)
        self.assertIn("HTTP 400", checkpoint["refused"])
        self.assertTrue(kind.checkpoint_resumable(checkpoint))
        self.assertNotIn(f"{PUB}/api/v1/posts/kept", http.requests)

    async def test_a_later_page_refused_goes_on_from_the_sitemap(self):
        first = [{"slug": f"p{i}"} for i in range(12)]
        responses = {f"{PUB}/api/v1/archive?sort=new&limit=12": json.dumps(first),
                     f"{PUB}/api/v1/archive?sort=new&offset=12&limit=12": REFUSED,
                     f"{PUB}/sitemap.xml": _sitemap(*((f"{PUB}/p/p{i}", f"2026-10-{20 - i:02d}") for i in range(14)))}
        responses.update({f"{PUB}/api/v1/posts/p{i}": json.dumps(_sub_post(f"p{i}", 20 - i)) for i in range(14)})
        stored: set = set()
        kind = SubstackKind(FakeHttp(responses), sid="", stored_urls=lambda urls: stored & set(urls))
        pages = []
        async for page in kind.archive_pages(self.source(), 1000, None, RATE):
            pages.append(page)
            stored.update(p["url"] for p in page.posts)   # the archive saves each page before asking the next
        self.assertEqual([len(page.posts) for page in pages], [12, 0, 2])
        self.assertEqual(pages[-1].checkpoint["collected_posts"], 14)

    async def test_a_resumed_sitemap_archive_goes_on_from_its_index(self):
        responses = {f"{PUB}/sitemap.xml": _sitemap(*((f"{PUB}/p/p{i}", f"2026-10-{20 - i:02d}") for i in range(14)))}
        responses.update({f"{PUB}/api/v1/posts/p{i}": json.dumps(_sub_post(f"p{i}", 20 - i)) for i in range(14)})
        http = FakeHttp(responses)
        checkpoint = {"mode": SITEMAP_MODE, "next_index": 12, "pages_fetched": 1, "collected_posts": 12}
        pages = await _pages(SubstackKind(http, sid=""), self.source(), checkpoint)
        self.assertEqual([p["url"] for p in pages[0].posts], [f"{PUB}/p/p12", f"{PUB}/p/p13"])
        self.assertFalse(any("/api/v1/archive" in url for url in http.requests), "a sitemap checkpoint never asks the API")

    async def test_refused_with_no_sitemap_is_the_archives_error_not_a_silent_zero(self):
        http = FakeHttp({f"{PUB}/api/v1/archive?sort=new&limit=12": REFUSED})
        with self.assertRaisesRegex(ValueError, "HTTP 400"):
            await _pages(SubstackKind(http, sid=""), self.source())
        with self.assertRaisesRegex(ValueError, "HTTP 400"):
            await SubstackKind(http, sid="").inspect(self.source())

    async def test_the_plan_measures_the_sitemap_when_the_api_refuses(self):
        http = FakeHttp({f"{PUB}/api/v1/archive?sort=new&limit=12": REFUSED,
                         f"{PUB}/sitemap.xml": _sitemap((f"{PUB}/p/a", "2026-10-01"), (f"{PUB}/p/b", "2026-10-02"))})
        inspection = await SubstackKind(http, sid="").inspect(self.source())
        self.assertEqual(inspection.raw["sitemap_posts"], 2)
        self.assertIn("refused", inspection.raw["archive_api"])

    async def test_a_host_limiting_us_is_not_a_refusal(self):
        http = FakeHttp({f"{PUB}/api/v1/archive?sort=new&limit=12": HttpError("HTTP 429", status=429)})
        with self.assertRaises(HttpError):
            await _pages(SubstackKind(http, sid=""), self.source())
        self.assertNotIn(f"{PUB}/sitemap.xml", http.requests)


BATCH = "https://www.deeplearning.ai"
CHARON = DeepLearningBatchAdapter.CHARON_SITEMAP_URL


def _issue_page(number: int, *, payload: bool) -> str:
    """An issue page: the old layout (the Next.js payload) or one without it (an article with its date)."""
    body = "<article><h1>Issue %d</h1>%s</article>" % (number, PROSE)
    head = (f'<meta property="og:type" content="article"><meta property="article:published_time" '
            f'content="2026-10-{number % 28 + 1:02d}T14:00:00Z"><title>The Batch issue {number}</title>')
    data = ""
    if payload:
        data = ('<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"post": {
            "title": f"Issue {number}", "html": "<p>" + " ".join(["news"] * 80) + "</p>",
            "published_at": "2026-07-17T14:00:00Z", "slug": f"issue-{number}"}}}) + "</script>")
    return f"<html><head>{head}</head><body>{body}{data}</body></html>"


class WeeklyNewsletterReaderTests(unittest.IsolatedAsyncioTestCase):
    """B2: the reader read 38 pages and found 0 posts: its issue pages lost the payload it parsed."""

    def source(self):
        return {"id": "s2", "platform": "rss", "handle_or_url": f"{BATCH}/the-batch/", "settings": {}}

    async def test_an_issue_page_without_the_payload_is_read_as_an_article(self):
        http = FakeHttp({f"{BATCH}/the-batch/issue-370/": _issue_page(370, payload=False)})
        post = await DeepLearningBatchAdapter(http)._fetch_issue_post(
            self.source(), {"issue_number": 370, "public_url": f"{BATCH}/the-batch/issue-370/", "published_at": None})
        self.assertEqual(post["external_id"], "370", "the issue number stays its id: the stored issue is updated")
        self.assertEqual(post["metadata"]["read_as"], "page")
        self.assertEqual(post["date"], datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc))
        self.assertIn("third model", post["content"])

    async def test_the_sites_own_sitemap_lists_the_issues_when_the_cms_sitemap_fails(self):
        http = FakeHttp({
            CHARON: HttpError("HTTP 404", status=404),
            f"{BATCH}/sitemap.xml": _sitemap((f"{BATCH}/the-batch/issue-371/", "2026-10-30"),
                                             (f"{BATCH}/the-batch/tag/letters/", "2026-10-30"),
                                             (f"{BATCH}/the-batch/issue-370/", "2026-10-23")),
        })
        entries = await DeepLearningBatchAdapter(http)._discover_entries()
        self.assertEqual([e["issue_number"] for e in entries], [371, 370])

    async def test_a_live_fetch_that_reads_no_issue_says_the_layout_changed(self):
        broken = "<html><head><title>x</title></head><body><div id=app></div></body></html>"
        locs = [(f"https://charonhub.deeplearning.ai/issue-{n}/", f"2026-10-{n - 340:02d}") for n in range(361, 366)]
        responses = {CHARON: _sitemap(*locs)}
        responses.update({f"{BATCH}/the-batch/issue-{n}/": broken for n in range(361, 366)})
        with self.assertRaisesRegex(ValueError, "layout changed"):
            await DeepLearningBatchAdapter(FakeHttp(responses)).fetch_latest(self.source(), 5)


def _service(kind, *, stored=0, current=None, saver=None):
    service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]),
                                 gates=SpyFetchGates())
    service.sources_service = sources = _Sources(current or {})
    service.posts_service = _Posts(stored)
    service.archive_metadata = ArchiveMetadataWriter(posts=service.posts_service, sources=sources)
    service._save_posts = saver or (lambda _sid, posts: _saved(len(posts), 0))
    return service, sources


def _saved(inserted: int, updated: int) -> SaveBatchResult:
    result = SaveBatchResult()
    result.inserted_ids.extend(f"i{n}" for n in range(inserted))
    result.updated_ids.extend(f"u{n}" for n in range(updated))
    return result


class _Posts:
    def __init__(self, count=0, oldest=None):
        self.count, self.oldest = count, oldest

    def get_source_post_stats(self, _source_id):
        return {"post_count": self.count, "oldest_published_at": self.oldest, "oldest_external_id": None}


class _Sources:
    def __init__(self, current):
        self.current, self.saved = current, {}
        self.handle = "https://lab.example/blog/index.xml"

    def get_source_by_id(self, source_id):
        return {"id": source_id, "platform": "rss", "handle_or_url": self.handle, "settings": {}}

    def get_source_with_settings(self, source_id):
        return {**self.get_source_by_id(source_id), "settings": {"archive": self.current}}

    def merge_source_settings(self, _source_id, settings):
        self.saved = self.current = settings["archive"]


class ZeroNewTests(unittest.IsolatedAsyncioTestCase):
    """B4: "success, 0 new" while the site lists more: the result says why."""

    async def test_a_page_watch_archive_leaves_stored_pages_unread_and_counts_why(self):
        site = "https://org.example"
        listing = "<html><body>" + "".join(f'<a href="/research/r{n}">r{n}</a>' for n in range(4)) + "</body></html>"
        article = ('<html><head><meta property="article:published_time" content="2026-10-01T00:00:00Z"><title>R</title>'
                   "</head><body><article>" + PROSE + "</article></body></html>")
        category = "<html><head><title>All</title></head><body><article>" + PROSE + "</article></body></html>"
        http = FakeHttp({f"{site}/research": listing, f"{site}/research/r1": article,
                         f"{site}/research/r2": category, f"{site}/research/r3": HttpError("HTTP 500", status=500)})
        kind = PageWatchKind(http, stored_urls=lambda urls: {u for u in urls if u.endswith("/r0")})
        source = {"id": "s3", "platform": "rss", "handle_or_url": f"{site}/research", "settings": {"page_watch": {}}}
        pages = await _pages(kind, source)
        self.assertEqual([p["url"] for page in pages for p in page.posts], [f"{site}/research/r1"])
        self.assertEqual(pages[-1].checkpoint["skipped"], {"stored": 1, "no_post": 1, "unreadable": 1})
        self.assertNotIn(f"{site}/research/r0", http.requests, "a stored page is not read again")

    async def test_the_archives_result_says_why_it_added_nothing(self):
        checkpoint = {"mode": "fake", "pages_fetched": 3, "collected_posts": 1,
                      "skipped": {"stored": 102, "no_post": 8, "unreadable": 2}}
        kind = FakeKind("fake_site", inspection=Inspection(113, 1, None),
                        pages=[ArchivePage([{"url": "https://org.example/a"}], checkpoint)])
        kind.skips_stored = True
        service, sources = _service(kind, saver=lambda _sid, posts: _saved(0, len(posts)))
        result = await service.archive_source("s1")
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Archive completed with 1 posts; nothing new: 102 pages already stored "
                         "(not read again) · 1 post already stored under another address · 8 pages no post "
                         "(no article, or no date) · 2 pages could not be read")
        self.assertEqual(result["unreached"], {"stored": 102, "no_post": 8, "unreadable": 2, "updated": 1})
        self.assertEqual(sources.saved["unreached"]["no_post"], 8)

    def test_a_listing_that_ends_says_so(self):
        self.assertEqual(why_line({}, 0, 0, re_read=True), "the source's listing ends here")
        self.assertIsNone(why_line({}, 0, 4, re_read=True))

    async def test_a_reader_whose_listed_posts_all_read_as_no_post_fails_saying_the_layout_changed(self):
        checkpoint = {"mode": "site_index", "next_index": 380, "pages_fetched": 38, "collected_posts": 0,
                      "skipped": {"no_post": 380}}
        kind = FakeKind("fake_newsletter", inspection=Inspection(380, 10, None), pages=[ArchivePage([], checkpoint)])
        kind.LISTS_ONLY_POSTS = True
        service, _ = _service(kind)
        result = await service.archive_source("s1")
        self.assertFalse(result["success"])
        self.assertTrue(result["layout_changed"])
        self.assertIn("layout changed: 380 listed pages read", result["error"])


class _Doctor:
    def __init__(self, sources, *, switch_to=None, finding=None):
        self.sources, self.switch_to, self.finding = sources, switch_to, finding
        self.looked: list = []
        self.state = FetchStateRow(source_id="s1")

    async def after_failure(self, source, kind, state, error, progress=None):
        self.looked.append((source["handle_or_url"], getattr(error, "status", None)))
        if self.switch_to:
            self.sources.handle = self.switch_to
        else:
            self.state = FetchStateRow(source_id="s1", doctor_checked_at=datetime.now(timezone.utc),
                                       doctor_finding=self.finding)


class MovedFeedTests(unittest.IsolatedAsyncioTestCase):
    """B3: a feed that answers 404 runs the feed finder and the source sheet offers the repair."""

    def service(self, **doctor):
        kind = FakeKind("generic_rss")
        gone = HttpError("HTTP 404 while fetching https://lab.example/blog/index.xml", status=404)

        async def inspect(_source):
            raise gone
        kind.inspect = inspect
        service, sources = _service(kind)
        service.doctor = _Doctor(sources, **doctor)
        service._fetch_state = lambda _sid: service.doctor.state
        return service

    async def test_a_feed_that_moved_on_its_site_is_followed_and_the_error_says_so(self):
        service = self.service(switch_to="https://lab.example/blog/rss.xml")
        with self.assertRaisesRegex(FeedMoved, "now follows lab.example/blog/rss.xml; run the archive again"):
            await service.archive_source("s1")
        self.assertEqual(service.doctor.looked, [("https://lab.example/blog/index.xml", 404)])

    async def test_a_replacement_elsewhere_is_offered_on_the_sheet(self):
        finding = {"replacement": {"kind": "page_watch", "url": "https://lab.example/news", "shared": 3}, "dismissed": False}
        service = self.service(finding=finding)
        with self.assertRaisesRegex(FeedMoved, "a page to follow at lab.example/news: switch to it on the source's sheet"):
            await service.plan_archive("s1")

    async def test_another_error_does_not_wake_the_doctor(self):
        kind = FakeKind("generic_rss")

        async def inspect(_source):
            raise HttpError("HTTP 503", status=503)
        kind.inspect = inspect
        service, sources = _service(kind)
        service.doctor = _Doctor(sources)
        with self.assertRaises(HttpError):
            await service.archive_source("s1")
        self.assertEqual(service.doctor.looked, [])


def _day(day: int) -> datetime:
    return datetime(2025, 11, day, 12, 0, tzinfo=timezone.utc)


class BackToADateTests(unittest.IsolatedAsyncioTestCase):
    """C: an archive back to a date stops once its pages pass it."""

    def kind(self, chronological=True):
        pages = [ArchivePage([{"url": f"https://t.example/c/{n}", "date": _day(day)} for n, day in batch],
                             {"mode": "fake", "pages_fetched": i + 1, "collected_posts": 2 * (i + 1)})
                 for i, batch in enumerate([[(9, 9), (8, 8)], [(7, 3), (6, 1)], [(5, 1), (4, 1)], [(3, 1), (2, 1)]])]
        kind = FakeKind("fake_channel", inspection=Inspection(None, 2, None), pages=pages)
        kind.chronological = chronological
        return kind

    async def test_it_stops_within_one_page_of_the_date_and_keeps_its_checkpoint(self):
        kind = self.kind()
        service, sources = _service(kind)
        result = await service.archive_source("s1", until="2025-11-02")
        self.assertEqual(result["posts_fetched"], 4, "the page that passed the date is saved, no page after it")
        self.assertEqual(kind.events.count("page"), 2)
        self.assertEqual(result["until_reached"], "2025-11-02T00:00:00+00:00")
        self.assertTrue(result["message"].startswith("Archive reached 2 Nov 2025 with 4 posts"))
        self.assertNotIn("completed_at", sources.saved["checkpoint"], "a later archive goes on from here")
        self.assertTrue(sources.saved["resume_ready"])

    async def test_a_kind_not_newest_first_runs_to_its_end(self):
        kind = self.kind(chronological=False)
        service, _ = _service(kind)
        result = await service.archive_source("s1", until="2025-11-02")
        self.assertEqual(result["posts_fetched"], 8)
        self.assertNotIn("until_reached", result)

    async def test_stored_posts_already_past_the_date_need_no_page(self):
        kind = self.kind()

        async def start_checkpoint(_source, _stored):
            return {"mode": "fake", "collected_posts": 0, "pages_fetched": 0}
        kind.start_checkpoint = start_checkpoint
        service, _ = _service(kind, stored=40)
        service.posts_service.oldest = _day(1)
        result = await service.archive_source("s1", resume=False, until="2025-11-02")
        self.assertEqual(kind.events.count("page"), 0)
        self.assertEqual(result["message"], "The archive already reaches 2 Nov 2025")


if __name__ == "__main__":
    unittest.main()
