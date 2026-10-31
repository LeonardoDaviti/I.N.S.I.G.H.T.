"""Teasers are tried again (issue 0062, item 2): a teaser whose page read failed is read again
on its source's later fetches, at most MAX_PAGE_TRIES reads, RETRY_APART apart.

No network: FakeHttp. The kind tests need no database; the store tests commit rows, so they run
only against a *_test database (@requires_test_db).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import FULL_TEXT_FLAG, PAGE_TRIES_KEY, PostsRepository
from insight_core.ingestion import full_text
from insight_core.ingestion.http import AddressMemory, Conditional, HttpError, Validators
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_full_text import ARTICLE_TEXT, FEED_URL, _article, _feed, _src

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
FORBIDDEN = HttpError("HTTP 403 while fetching: bot protection", status=403)


def _tried(count: int, *, days_ago: float = 2, failed: bool = True) -> dict:
    return {PAGE_TRIES_KEY: {"count": count, "last_at": (NOW - timedelta(days=days_ago)).isoformat(),
                             "failed": failed}}


def _stored_teaser(url: str, metadata: dict) -> dict:
    return {"url": url, "title": "A teaser", "content": "Short summary.", "content_html": None, "date": None,
            "media_urls": [], "categories": [], "metadata": metadata}


class TeaserReadAgainTests(unittest.IsolatedAsyncioTestCase):
    """The kind: a failed read is counted, and a counted teaser due again is read again."""

    def _kind(self, http: FakeHttp, due: list | None = None, stored: set | None = None) -> GenericRssKind:
        self.asked: list = []

        def teasers_due(source_id, **kwargs):
            self.asked.append((source_id, kwargs))
            return list(due or [])

        return GenericRssKind(http, stored_urls=lambda urls: set(stored or ()) & set(urls),
                              teasers_due=teasers_due, clock=lambda: NOW)

    async def test_a_failed_read_of_a_new_teaser_is_counted(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary.")),
                         "https://news.example.com/a": FORBIDDEN})
        [post] = await self._kind(http).fetch_latest(_src(), 10)
        self.assertEqual(post["content"], "Short summary.")
        self.assertEqual(post["metadata"][PAGE_TRIES_KEY], {"count": 1, "last_at": NOW.isoformat(), "failed": True})

    async def test_a_timeout_is_a_failed_read_too(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary.")),
                         "https://news.example.com/a": HttpError("Timed out", timed_out=True)})
        [post] = await self._kind(http).fetch_latest(_src(), 10)
        self.assertTrue(post["metadata"][PAGE_TRIES_KEY]["failed"])

    async def test_a_page_that_holds_nothing_longer_is_never_counted(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary.")),
                         "https://news.example.com/a": _article("Tiny.")})
        [post] = await self._kind(http).fetch_latest(_src(), 10)
        self.assertNotIn(PAGE_TRIES_KEY, post["metadata"])

    async def test_a_failed_read_is_retried_and_success_ends_it(self):
        url = "https://news.example.com/a"
        http = FakeHttp({FEED_URL: _feed((url, "Short summary.")), url: _article()})
        [post] = await self._kind(http, due=[_stored_teaser(url, {"feed": "kept", **_tried(1)})],
                                  stored={url}).fetch_latest(_src(), 10)
        self.assertIn("Every paragraph of the article", post["content"])
        self.assertTrue(post["metadata"][FULL_TEXT_FLAG])
        self.assertEqual(post["metadata"]["feed"], "kept")
        self.assertEqual(post["metadata"][PAGE_TRIES_KEY], {"count": 2, "last_at": NOW.isoformat(), "failed": False})
        self.assertIsNone(post["date"], "the stored date stays")
        self.assertEqual(http.requests, [FEED_URL, url], "the post still in the feed is read once, as a retry")
        self.assertEqual(self.asked, [("s1", {"now": NOW, "max_tries": full_text.MAX_PAGE_TRIES,
                                              "apart": full_text.RETRY_APART, "limit": full_text.RETRY_SLICE})])

    async def test_a_retry_that_fails_again_is_counted(self):
        url = "https://news.example.com/gone-from-the-feed"
        http = FakeHttp({FEED_URL: _feed(), url: FORBIDDEN})
        [post] = await self._kind(http, due=[_stored_teaser(url, _tried(2))]).fetch_latest(_src(), 10)
        self.assertEqual(post["content"], "Short summary.")
        self.assertEqual(post["metadata"][PAGE_TRIES_KEY], {"count": 3, "last_at": NOW.isoformat(), "failed": True})

    async def test_a_retry_that_finds_nothing_longer_ends_it(self):
        url = "https://news.example.com/a"
        http = FakeHttp({FEED_URL: _feed(), url: _article("Tiny.")})
        [post] = await self._kind(http, due=[_stored_teaser(url, _tried(1))]).fetch_latest(_src(), 10)
        self.assertFalse(post["metadata"][PAGE_TRIES_KEY]["failed"])
        self.assertNotIn(FULL_TEXT_FLAG, post["metadata"])

    async def test_an_unchanged_feed_still_reads_its_teasers_again(self):
        url = "https://news.example.com/a"
        http = FakeHttp({FEED_URL: Conditional(None, FEED_URL, {}, Validators()), url: _article()})
        memory = AddressMemory({}, now=NOW)
        [post] = await self._kind(http, due=[_stored_teaser(url, _tried(1))]).fetch_latest(_src(), 10, memory=memory)
        self.assertTrue(post["metadata"][FULL_TEXT_FLAG])

    async def test_a_limiting_host_ends_the_slice_after_that_try(self):
        due = [_stored_teaser(f"https://news.example.com/{n}", _tried(1)) for n in range(3)]
        http = FakeHttp({FEED_URL: _feed(), "https://news.example.com/0": HttpError("HTTP 429", status=429)})
        posts = await self._kind(http, due=due).fetch_latest(_src(), 10)
        self.assertEqual([p["url"] for p in posts], ["https://news.example.com/0"])
        self.assertEqual(posts[0]["metadata"][PAGE_TRIES_KEY]["count"], 2)
        self.assertEqual(http.requests, [FEED_URL, "https://news.example.com/0"])

    async def test_retries_are_read_apart_and_only_where_full_text_is_on(self):
        due = [_stored_teaser(f"https://news.example.com/{n}", _tried(1)) for n in range(2)]
        http = FakeHttp({FEED_URL: _feed(), **{p["url"]: _article() for p in due}})
        await self._kind(http, due=due).fetch_latest(_src(), 10)
        self.assertEqual(http.sleeper.calls, [full_text.PAGE_DELAY_S])
        off = FakeHttp({FEED_URL: _feed()})
        self.assertEqual(await self._kind(off, due=due).fetch_latest(_src(fetch_full_content=False), 10), [])
        self.assertEqual(off.requests, [FEED_URL])


@requires_test_db
class TeaserReadAgainDbTests(unittest.IsolatedAsyncioTestCase):
    """The store: which teasers are due, and a feed re-fetch keeping the count."""

    def setUp(self):
        self.url = db_url()
        self.repo = PostsRepository(self.url)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _upsert(self, post: dict) -> str:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            post_id, _ = self.repo.upsert_post(cur, {"title": "A teaser", "date": None, **post}, self.source_id)
            conn.commit()
        return post_id

    def _row(self, post_id: str) -> tuple:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT content, metadata, published_at, title FROM posts WHERE id = %s", (post_id,))
            return cur.fetchone()

    def _due(self) -> list:
        return [post["url"] for post in self.repo.teasers_to_read_again(
            self.source_id, now=NOW, max_tries=full_text.MAX_PAGE_TRIES, apart=full_text.RETRY_APART,
            limit=full_text.RETRY_SLICE)]

    def test_only_failed_reads_under_three_tries_a_day_apart_are_due(self):
        base = "https://news.example.com/due"
        self._upsert({"url": f"{base}/failed-2-days-ago", "content": "Short.", "metadata": _tried(1)})
        self._upsert({"url": f"{base}/failed-twice", "content": "Short.", "metadata": _tried(2, days_ago=1)})
        self._upsert({"url": f"{base}/failed-an-hour-ago", "content": "Short.", "metadata": _tried(1, days_ago=1 / 24)})
        self._upsert({"url": f"{base}/third-failure", "content": "Short.", "metadata": _tried(3, days_ago=5)})
        self._upsert({"url": f"{base}/nothing-longer", "content": "Short.", "metadata": _tried(2, failed=False)})
        self._upsert({"url": f"{base}/never-counted", "content": "Short."})
        self._upsert({"url": f"{base}/read", "content": ARTICLE_TEXT, "metadata": {FULL_TEXT_FLAG: True, **_tried(1)}})
        self.assertEqual(self._due(), [f"{base}/failed-2-days-ago", f"{base}/failed-twice"])

    async def test_a_refetch_keeps_the_count_and_a_retry_writes_in_place(self):
        url = "https://news.example.com/kept-count"
        dated = datetime(2026, 10, 26, tzinfo=timezone.utc)
        post_id = self._upsert({"url": url, "content": "Short summary.", "date": dated, "metadata": _tried(1)})
        self._upsert({"url": url, "content": "Short summary.", "date": dated, "metadata": {"feed": "again"}})
        self.assertEqual(self._row(post_id)[1][PAGE_TRIES_KEY], _tried(1)[PAGE_TRIES_KEY])
        self.assertEqual(self._due(), [url])

        http = FakeHttp({FEED_URL: _feed(), url: _article()})
        kind = GenericRssKind(http, teasers_due=self.repo.teasers_to_read_again, clock=lambda: NOW)
        [post] = await kind.fetch_latest({**_src(), "id": self.source_id}, 10)
        self._upsert(post)
        content, metadata, published_at, title = self._row(post_id)
        self.assertIn("Every paragraph of the article", content)
        self.assertEqual((metadata[PAGE_TRIES_KEY]["count"], metadata["feed"]), (2, "again"))
        self.assertEqual((published_at, title), (dated, "A teaser"))
        self.assertEqual(self._due(), [])


if __name__ == "__main__":
    unittest.main()
