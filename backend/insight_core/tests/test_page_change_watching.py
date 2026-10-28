"""Watching pages for changes (issue 0039), and "new to you is new".

The text summary and the page's own modified date (pure); the cheap checks in order over a fake
network; the runner over in-memory ports; and, against the scratch database, the saver (an
update brought back, a tiny change kept silently, a page new to you), the due order and the
reader's sort key and Updated filter.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.adapters.gwern_adapter import GwernAdapter
from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion import page_changes
from insight_core.ingestion.http import Conditional, HttpError, Validators
from insight_core.ingestion.kinds import KindRegistry, parsing
from insight_core.ingestion.kinds.page_watch import PageWatchKind
from insight_core.ingestion.page_changes import HEAD_BYTES, WatchedPage, check_page, check_pages
from insight_core.ingestion.http import AddressMemory
from insight_core.ingestion.ports import JobProgressSink
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.schedule import Availability
from insight_core.ingestion.types import FetchRequest, SourceSelector, Trigger
from insight_core.services.sources_service import SourcesService
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
from insight_core.utils.text_changes import MIN_CHANGED_WORDS, change_summary, meaningful, text_hash

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
SENTENCE = "Scaling laws hold for small models trained on clean text. "


def paragraphs(*texts: str) -> str:
    return "\n".join(f"<p>{text}</p>" for text in texts)


def page(body: str, *, modified: str | None = "2026-09-21", pad: int = 0) -> str:
    """An article page; pad puts that many bytes of inline style before the modified date."""
    meta = f'<meta name="dcterms.modified" content="{modified}">' if modified else ""
    return (f'<html><head><title>Lean scaling</title><style>{"x" * pad}</style>{meta}</head>'
            f'<body><article>{body}</article></body></html>')


def read_post(url: str, html: str):
    """A kind's page_post: the article as text and html, or None when there is none."""
    start = html.find("<article>")
    if start < 0:
        return None
    body = html[start + 9: html.find("</article>")]
    return {"url": url, "title": "Lean scaling", "content": parsing.strip_html(body), "content_html": body,
            "date": NOW, "metadata": {"modified": parsing.page_modified(html)}}


BODY = paragraphs(SENTENCE * 6, SENTENCE * 4)
TEXT = parsing.strip_html(BODY)


# --------------------------------------------------------------------------- pure


class TextChangeTests(unittest.TestCase):
    def test_the_hash_is_of_the_text_not_its_wrapping(self):
        self.assertEqual(text_hash("a  b\n c"), text_hash("a b c"))
        self.assertNotEqual(text_hash("a b c"), text_hash("a b d"))

    def test_a_fixed_typo_is_one_word_and_tiny(self):
        old = paragraphs(SENTENCE * 6, "The model was trained on tokns of text.")
        new = paragraphs(SENTENCE * 6, "The model was trained on tokens of text.")
        summary = change_summary(parsing.strip_html(old), parsing.strip_html(new), old, new)
        self.assertEqual((summary["words_added"], summary["words_removed"]), (1, 1))
        self.assertFalse(meaningful(summary))

    def test_a_new_section_counts_its_heading_and_words(self):
        old = paragraphs(SENTENCE * 6)
        new = old + "\n<h2>Results</h2>\n" + paragraphs(SENTENCE * 20) + "\n<h2>Limits</h2>\n<p>None.</p>"
        summary = change_summary(parsing.strip_html(old), parsing.strip_html(new), old, new)
        self.assertEqual(summary["sections_added"], 2)
        self.assertEqual(summary["words_added"], 2 + 20 * len(SENTENCE.split()) + 1)
        self.assertEqual(summary["words"], len(parsing.strip_html(new).split()))
        self.assertTrue(meaningful(summary))

    def test_plain_text_is_compared_by_sentence(self):
        old = SENTENCE * 3
        new = SENTENCE * 3 + "A new finding. " * MIN_CHANGED_WORDS
        summary = change_summary(old, new)
        self.assertEqual(summary["words_added"], 3 * MIN_CHANGED_WORDS)
        self.assertTrue(meaningful(summary))
        self.assertFalse(meaningful(change_summary(old, old)))


class PageModifiedTests(unittest.TestCase):
    def test_each_place_a_page_states_it(self):
        self.assertEqual(parsing.page_modified('<meta name="dcterms.modified" content="2026-09-21">'),
                         "2026-09-21T00:00:00+00:00")
        self.assertEqual(parsing.page_modified('<meta property="article:modified_time" content="2026-06-23T10:00:00Z">'),
                         "2026-06-23T10:00:00+00:00")
        self.assertEqual(parsing.page_modified('<script type="application/ld+json">{"dateModified": "2026-06-23"}</script>'),
                         "2026-06-23T00:00:00+00:00")
        self.assertIsNone(parsing.page_modified('<meta name="date" content="2026-06-23"><p>Updated yesterday</p>'))
        self.assertIsNone(parsing.page_modified(None))


# --------------------------------------------------------------------------- the checks


def watched(**overrides) -> WatchedPage:
    fields = {"post_id": "p1", "url": "https://site.test/lean", "text_hash": text_hash(TEXT),
              "modified": "2026-09-21T00:00:00+00:00"}
    fields.update(overrides)
    return WatchedPage(**fields)


class CheapCheckTests(unittest.IsolatedAsyncioTestCase):
    async def check(self, http, watched_page, *, now=NOW):
        memory = AddressMemory({watched_page.url: watched_page.validators} if watched_page.validators else {}, now=now)
        return await check_page(http, watched_page, read_post, memory)

    async def test_a_304_is_unchanged_with_no_body(self):
        http = FakeHttp({"https://site.test/lean": Conditional(None, "https://site.test/lean", {}, Validators('"e"'))})
        result = await self.check(http, watched(validators=Validators('"e"', None, NOW)))
        self.assertEqual((result.outcome, result.bytes_read, result.post), ("unchanged", 0, None))
        self.assertEqual(http.validators_sent, [("https://site.test/lean", Validators('"e"', None, NOW))])

    async def test_the_same_date_in_the_head_is_unchanged_reading_only_the_head(self):
        html = page(BODY + paragraphs(SENTENCE * 3000))
        http = FakeHttp({"https://site.test/lean": html})
        result = await self.check(http, watched())
        self.assertEqual(result.outcome, "unchanged")
        self.assertEqual(http.byte_caps["https://site.test/lean"], HEAD_BYTES)
        self.assertEqual(result.bytes_read, HEAD_BYTES)
        self.assertEqual(http.requests, ["https://site.test/lean"])

    async def test_a_moved_date_reads_the_page_and_a_new_text_is_a_change(self):
        new_body = BODY + "\n<h2>Update</h2>\n" + paragraphs(SENTENCE * 30)
        html = page(new_body, modified="2026-10-27") + "<!--" + "y" * HEAD_BYTES + "-->"
        http = FakeHttp({"https://site.test/lean": html})
        result = await self.check(http, watched())
        self.assertEqual(result.outcome, "changed")
        self.assertEqual(http.requests, ["https://site.test/lean", "https://site.test/lean"])   # head, then whole
        self.assertEqual(result.modified, "2026-10-27T00:00:00+00:00")
        self.assertEqual(result.post["url"], "https://site.test/lean")
        self.assertIsNone(result.post["date"])        # the stored date stays
        self.assertEqual(result.text_hash, text_hash(parsing.strip_html(new_body)))

    async def test_a_moved_date_with_the_same_text_still_saves_the_new_date(self):
        http = FakeHttp({"https://site.test/lean": page(BODY, modified="2026-10-27")})
        result = await self.check(http, watched())
        self.assertEqual(result.outcome, "changed")
        self.assertEqual(result.text_hash, text_hash(TEXT))
        self.assertEqual(http.requests, ["https://site.test/lean"])   # the page fit in the head read

    async def test_a_page_with_no_date_is_read_whole_and_compared_by_its_text(self):
        http = FakeHttp({"https://site.test/lean": page(BODY, modified=None)})
        result = await self.check(http, watched(modified=None))
        self.assertEqual((result.outcome, result.modified, result.head_missed), ("unchanged", None, False))
        self.assertNotIn("https://site.test/lean", http.byte_caps)

    async def test_a_date_past_the_head_is_remembered_so_the_head_is_skipped_next_time(self):
        http = FakeHttp({"https://site.test/lean": page(BODY, pad=HEAD_BYTES + 10)})
        result = await self.check(http, watched(modified=None))
        self.assertTrue(result.head_missed)
        self.assertEqual(result.modified, "2026-09-21T00:00:00+00:00")
        http.requests.clear()
        again = await self.check(http, watched(head_missed=True))
        self.assertEqual(again.outcome, "unchanged")
        self.assertNotIn("https://site.test/lean", http.byte_caps)

    async def test_a_page_gone_or_no_longer_an_article_keeps_its_text(self):
        gone = await self.check(FakeHttp({"https://site.test/lean": HttpError("HTTP 404", status=404)}), watched())
        self.assertEqual((gone.outcome, gone.post), ("gone", None))
        empty = await self.check(FakeHttp({"https://site.test/lean": "<html>moved</html>"}), watched(modified=None))
        self.assertEqual((empty.outcome, empty.post), ("gone", None))
        failed = await self.check(FakeHttp({"https://site.test/lean": HttpError("HTTP 500", status=500)}), watched())
        self.assertEqual(failed.outcome, "failed")

    async def test_a_limiting_host_ends_the_slice_and_pages_are_spaced(self):
        http = FakeHttp({"https://site.test/a": page(BODY), "https://site.test/b": HttpError("HTTP 429", status=429),
                         "https://site.test/c": page(BODY)})
        pages = [watched(post_id=p, url=f"https://site.test/{p}") for p in "abc"]
        checks = await check_pages(http, pages, read_post, now=NOW, delay_s=2)
        self.assertEqual([c.post_id for c in checks], ["a"])
        self.assertEqual(http.sleeper.calls, [2])
        self.assertNotIn("https://site.test/c", http.requests)


class KindReaderTests(unittest.TestCase):
    def test_page_watch_and_gwern_watch_and_the_feeds_do_not(self):
        http = FakeHttp()
        registry = KindRegistry.default(http, youtube=None)
        self.assertTrue(registry.by_name("page_watch").watches)
        self.assertTrue(registry.by_name("gwern_site").watches)
        self.assertFalse(registry.by_name("generic_rss").watches)
        self.assertTrue(registry.by_name("page_watch").page_based)
        self.assertTrue(registry.by_name("gwern_site").page_based)
        self.assertFalse(registry.by_name("generic_rss").page_based)

    def test_the_page_post_is_the_fetch_reader(self):
        html = (page(paragraphs(SENTENCE * 20)).replace("<head>", '<head><meta property="og:type" content="article">'))
        post = PageWatchKind(FakeHttp()).page_post({"handle_or_url": "https://site.test/news"}, "https://site.test/news/a", html)
        self.assertEqual(post["metadata"]["modified"], "2026-09-21T00:00:00+00:00")
        gwern = GwernAdapter(FakeHttp()).page_post({"handle_or_url": "https://gwern.net"}, "https://gwern.net/lean", html)
        self.assertEqual(gwern["metadata"]["modified"], "2026-09-21")
        self.assertIn("Scaling laws", gwern["content"])


# --------------------------------------------------------------------------- the runner


class InMemoryPageWatchStore:
    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.checks: list = []
        self.due_calls: list = []

    def due(self, source_id, *, now, limit):
        self.due_calls.append((source_id, limit))
        return self.pages[:limit]

    def checked(self, source_id, checks, *, now):
        self.checks.append((source_id, [(c.post_id, c.outcome) for c in checks]))


class WatchingKind(FakeKind):
    watches = True
    page_based = True

    def __init__(self, http, posts=None):
        super().__init__("watching", behaviour=lambda _s, _l: [dict(p) for p in (posts or [])])
        self.http = http

    def page_post(self, source, url, html):
        return read_post(url, html)


class RunnerWatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http = FakeHttp({"https://site.test/a": page(BODY + paragraphs(SENTENCE * 30), modified="2026-10-27"),
                              "https://site.test/b": page(BODY)})
        self.store = InMemoryPageWatchStore([watched(post_id="a", url="https://site.test/a"),
                                             watched(post_id="b", url="https://site.test/b")])
        self.source = {"id": "s1", "platform": "rss", "handle_or_url": "https://site.test/news", "enabled": True,
                       "settings": {"display_name": "Site", "watch_changes": True}}
        self.saver = InMemoryPostSaver()
        self.state = InMemoryFetchStateStore()
        self.new_post = {"url": "https://site.test/new", "title": "New", "content": "x", "date": NOW}

    async def fetch(self, kind=None, selector=None):
        self.progress = RecordingProgressSink()
        runner = IngestionRunner(
            catalog=InMemorySourceCatalog([self.source]), state=self.state, saver=self.saver,
            inspections=RecordingInspectionRefresher(),
            registry=KindRegistry([kind or WatchingKind(self.http, [self.new_post])]),
            gates=SpyFetchGates(), run_lock=FakeRunLock(), availability=lambda: Availability(True, False),
            clock=FixedClock(NOW), rand=lambda: 1.0, watch=self.store,
        )
        return await runner.run(FetchRequest(selector or SourceSelector.all(), Trigger.SCHEDULER, force=True),
                                progress=self.progress)

    def drafts(self):
        return [draft for call in self.saver.calls for draft in call]

    async def test_a_watching_source_checks_a_slice_and_saves_what_changed(self):
        self.saver.known = {"https://site.test/a": "a", "https://site.test/b": "b"}   # stored pages
        report = await self.fetch()
        self.assertEqual(self.store.due_calls, [("s1", page_changes.WATCH_SLICE)])
        drafts = self.drafts()
        self.assertEqual([d.post["url"] for d in drafts], ["https://site.test/new", "https://site.test/a"])
        self.assertTrue(all(d.watch for d in drafts))
        self.assertEqual(self.store.checks, [("s1", [("a", "changed"), ("b", "unchanged")])])
        self.assertEqual(report.posts_fetched, 1)           # the fetch's own posts; a change is no new post
        event = next(data for phase, data in self.progress.events if phase == "source")
        self.assertEqual((event["fetched"], event["checked"]), (1, 2))
        lines = []

        class _Ops:
            def append_job_event(self, job_id, *, message, **_kw):
                lines.append(message)

        JobProgressSink(_Ops(), "job").event("source", event)
        self.assertEqual(lines, ["Site: 1 new of 1 · 2 pages checked for changes, 0 updated · 1 of 1 source"])

    async def test_switched_off_nothing_is_checked(self):
        self.source["settings"]["watch_changes"] = False
        await self.fetch()
        self.assertEqual(self.store.due_calls, [])
        self.assertFalse(any(d.watch for d in self.drafts()))

    async def test_a_kind_that_cannot_watch_ignores_the_switch(self):
        await self.fetch(kind=FakeKind(behaviour=lambda _s, _l: [dict(self.new_post)]))
        self.assertEqual(self.store.due_calls, [])

    async def test_a_changed_page_whose_save_failed_is_checked_again(self):
        self.saver.failing_urls = {"https://site.test/a"}
        await self.fetch()
        self.assertEqual(self.store.checks, [("s1", [("b", "unchanged")])])

    async def test_new_to_you_only_after_the_first_fetch_of_a_page_based_kind(self):
        await self.fetch()
        self.assertFalse(any(d.surface for d in self.drafts()))
        self.state.rows["s1"] = FetchStateRow(source_id="s1", last_success_at=NOW - timedelta(days=1))
        self.saver.calls.clear()
        await self.fetch()
        self.assertTrue(all(d.surface for d in self.drafts()))
        self.saver.calls.clear()
        await self.fetch(kind=FakeKind(behaviour=lambda _s, _l: [dict(self.new_post)]))   # a feed: never
        self.assertFalse(any(d.surface for d in self.drafts()))


class SettingTests(unittest.TestCase):
    def test_watch_changes_is_a_switch(self):
        self.assertEqual(SourcesService._valid_settings({"watch_changes": True}), {"watch_changes": True})
        with self.assertRaises(ValueError):
            SourcesService._valid_settings({"watch_changes": "yes"})

    def test_the_health_row_says_whether_the_source_can_watch_and_does(self):
        from insight_core.services.operations_service import health_row

        source = {"id": "s1", "platform": "rss", "handle_or_url": "https://gwern.net", "enabled": True,
                  "settings": {"watch_changes": True}}
        row = health_row(source, GwernAdapter(FakeHttp()), Availability(True, False), NOW)
        self.assertEqual((row["watchable"], row["watch_changes"]), (True, True))
        feed = health_row(source, FakeKind(), Availability(True, False), NOW)
        self.assertEqual((feed["watchable"], feed["watch_changes"]), (False, False))


# --------------------------------------------------------------------------- the database


try:
    import psycopg

    from insight_core.db.repo_page_watch import PageWatchRepository
    from insight_core.db.repo_posts import BACKLOG_KEY, PostDraft, PostsRepository
    from insight_core.db.repo_reader import FeedQuery, FeedScope, ReaderRepository
    from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
except ImportError:  # pragma: no cover - outside the backend image
    requires_test_db = unittest.skip("no database driver")


@requires_test_db
class SaverTests(unittest.TestCase):
    """save_batch commits: scratch sources, deleted in tearDown (posts and watch rows cascade)."""

    def setUp(self):
        self.repo = PostsRepository(db_url())
        self.conn = psycopg.connect(db_url())
        with self.conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = insert_scratch_source(cur)
        self.conn.commit()
        self.url = f"https://test.invalid/mark-ix-post/watch/{uuid.uuid4().hex}"

    def tearDown(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            delete_scratch_sources(cur)
        self.conn.commit()
        self.conn.close()

    def save(self, body: str, *, watch=True, surface=False, date=NOW - timedelta(days=400), **extra):
        post = {"url": self.url, "title": "Lean scaling", "content": parsing.strip_html(body), "content_html": body,
                "date": date, "metadata": {"modified": "2026-09-21"}, **extra}
        return self.repo.save_batch(self.conn, [PostDraft(self.source, post, watch=watch, surface=surface)])

    def row(self):
        with self.conn.cursor() as cur:
            cur.execute("""SELECT p.id, p.surfaced_at, p.metadata->'page_update', p.content, p.published_at,
                                  w.text_hash, w.modified, w.changed_at, w.next_check_at, rs.read_at
                             FROM posts p LEFT JOIN post_watch w ON w.post_id = p.id
                             LEFT JOIN post_reader_state rs ON rs.post_id = p.id WHERE p.url = %s""", (self.url,))
            found = cur.fetchone()
        self.conn.commit()
        return found

    def test_a_new_watched_post_keeps_its_hash_and_is_due_in_two_weeks(self):
        self.save(BODY)
        post_id, surfaced, update, _, _, hashed, modified, changed, next_check, _ = self.row()
        self.assertEqual((surfaced, update, changed), (None, None, None))
        self.assertEqual((hashed, modified), (text_hash(TEXT), "2026-09-21T00:00:00+00:00"))
        with self.conn.cursor() as cur:
            cur.execute("SELECT now()")
            db_now = cur.fetchone()[0]
        self.assertAlmostEqual((next_check - db_now).total_seconds(), 14 * 86400, delta=60)

    def test_a_tiny_change_keeps_the_new_text_silently(self):
        self.save(BODY)
        self.save(BODY.replace("clean text", "clean, deduplicated text", 1))
        _, surfaced, update, content, _, hashed, _, changed, _, _ = self.row()
        self.assertIn("deduplicated", content)
        self.assertEqual((surfaced, update, changed), (None, None, None))
        self.assertEqual(hashed, text_hash(content))

    def test_a_meaningful_change_brings_the_post_back_unread_and_says_what_changed(self):
        result = self.save(BODY)
        post_id = result.inserted_ids[0]
        with self.conn.cursor() as cur:
            ReaderRepository(unread_window_days=None).set_read(cur, [post_id], True)
        self.conn.commit()
        new_body = BODY + "\n<h2>Results</h2>\n" + paragraphs(SENTENCE * 20)
        result = self.save(new_body, date=None)
        self.assertEqual(result.resurfaced_ids, [post_id])
        _, surfaced, update, _, published, _, _, changed, next_check, read_at = self.row()
        self.assertIsNotNone(surfaced)
        self.assertIsNone(read_at)                                   # it comes back unread
        self.assertEqual(published, NOW - timedelta(days=400))       # the date it was published stays
        self.assertEqual((update["sections_added"], update["words_added"]), (1, 1 + 20 * len(SENTENCE.split())))
        self.assertIn("at", update)
        self.assertAlmostEqual((next_check - changed).total_seconds(), 86400, delta=60)   # changed: due tomorrow
        # A later fetch of the same text keeps the update's summary.
        self.save(new_body, metadata={"modified": "2026-10-27"})
        self.assertEqual(self.row()[2]["sections_added"], 1)

    def test_a_page_new_to_you_sorts_at_when_it_was_first_seen(self):
        self.save(BODY, watch=False, surface=True)
        self.assertIsNotNone(self.row()[1])

    def test_a_recent_post_a_backlog_page_or_a_feed_post_keep_their_date(self):
        self.save(BODY, watch=False, surface=True, date=datetime.now(timezone.utc) - timedelta(hours=5))
        self.assertIsNone(self.row()[1])
        self.url += "-b"
        self.save(BODY, watch=False, surface=True, **{BACKLOG_KEY: True})
        self.assertIsNone(self.row()[1])
        self.url += "-c"
        self.save(BODY, watch=False, surface=False)
        self.assertIsNone(self.row()[1])


@requires_test_db
class DueAndReaderTests(unittest.TestCase):
    """The due order, a check recorded, and the reader's sort key and Updated filter."""

    def setUp(self):
        self.repo = PageWatchRepository()
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        delete_scratch_sources(self.cur)
        self.source = insert_scratch_source(self.cur)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def post(self, slug: str, published: datetime, *, surfaced: datetime | None = None, update: bool = False) -> str:
        self.cur.execute(
            """INSERT INTO posts (source_id, url, title, content, published_at, surfaced_at, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id""",
            (self.source, f"https://test.invalid/mark-ix-post/{uuid.uuid4().hex}/{slug}", slug, f"Text of {slug}",
             published, surfaced, '{"page_update": {"words_added": 120}}' if update else "{}"),
        )
        return str(self.cur.fetchone()[0])

    def test_overdue_pages_first_then_those_never_checked_newest_first(self):
        old, new, overdue, later = (self.post("old", NOW - timedelta(days=900)), self.post("new", NOW - timedelta(days=3)),
                                    self.post("overdue", NOW - timedelta(days=50)), self.post("later", NOW - timedelta(days=10)))
        for post_id, due in ((overdue, NOW - timedelta(days=2)), (later, NOW + timedelta(days=5))):
            self.cur.execute("""INSERT INTO post_watch (post_id, source_id, text_hash, next_check_at)
                                VALUES (%s, %s, 'h', %s)""", (post_id, self.source, due))
        due = self.repo.due(self.cur, self.source, now=NOW, limit=10)
        self.assertEqual([d["post_id"] for d in due], [overdue, new, old])
        self.assertEqual(due[1]["text_hash"], text_hash("Text of new"))   # never checked: its stored text's
        self.assertEqual(len(self.repo.due(self.cur, self.source, now=NOW, limit=2)), 2)

    def test_a_check_sets_when_the_page_is_due_again(self):
        recent, old = self.post("recent", NOW - timedelta(days=4)), self.post("old", NOW - timedelta(days=400))
        row = {"text_hash": "h", "modified": None, "head_missed": False, "etag": '"e"', "last_modified": None,
               "learned_at": NOW}
        self.repo.checked(self.cur, self.source, [{**row, "post_id": recent}, {**row, "post_id": old}], now=NOW)
        self.cur.execute("SELECT post_id, next_check_at, etag, checked_at FROM post_watch WHERE source_id = %s", (self.source,))
        found = {str(r[0]): r[1:] for r in self.cur.fetchall()}
        self.assertEqual(found[recent][0], NOW + timedelta(days=2))     # half the four days since
        self.assertEqual(found[old][0], NOW + timedelta(days=14))       # at most two weeks
        self.assertEqual(found[old][1:], ('"e"', NOW))

    def test_a_surfaced_post_sorts_at_when_it_reached_you_and_updated_lists_the_changed(self):
        plain = self.post("plain", NOW - timedelta(hours=2))
        found_late = self.post("found-late", NOW - timedelta(days=300), surfaced=NOW - timedelta(hours=1))
        changed = self.post("changed", NOW - timedelta(days=700), surfaced=NOW - timedelta(minutes=5), update=True)
        reader = ReaderRepository(unread_window_days=None)
        items, _ = reader.list_posts(self.cur, FeedQuery(scope=FeedScope("source", self.source)), now=NOW)
        self.assertEqual([i["id"] for i in items], [changed, found_late, plain])
        self.assertEqual(items[1]["published_at"], NOW - timedelta(days=300))   # the date shown stays
        self.assertEqual(items[0]["update"], {"words_added": 120})
        updated, _ = reader.list_posts(self.cur, FeedQuery(scope=FeedScope("source", self.source), filter="updated"), now=NOW)
        self.assertEqual([i["id"] for i in updated], [changed])


if __name__ == "__main__":
    unittest.main()
