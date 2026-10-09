"""The substack kind (Mark IX §10): paid posts read with the owner's substack.sid cookie.

No network: FakeHttp answers the archive and posts API. The JSON shapes follow what
kaitchup.substack.com answered on 2026-10-10: the archive list has empty body_html; a paid
post fetched without access returns a truncated body_html (270 of 1367 words) with HTTP 200,
the same as with a bogus cookie, so an expired cookie can only be seen in the body.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.gates import HOST_FLOORS
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import KindUnavailable, RateLimit
from insight_core.ingestion.kinds.substack import (
    EXPIRED_REASON,
    SUBSTACK_HOST_KEY,
    SubstackKind,
)
from insight_core.tests._kind_fakes import FakeHttp

BASE = "https://kaitchup.substack.com"


def _src(handle: str = f"{BASE}/", **settings) -> dict:
    return {"id": "s1", "platform": "rss", "handle_or_url": handle, "settings": dict(settings)}


def _words(n: int) -> str:
    return " ".join(["word"] * n)


def _item(slug: str, audience: str = "everyone", wordcount: int = 100, **extra) -> dict:
    return {
        "id": abs(hash(slug)) % 10**6, "slug": slug, "audience": audience, "wordcount": wordcount,
        "title": f"Title {slug}", "subtitle": f"Sub {slug}", "post_date": "2026-10-09T02:50:52.764Z",
        "canonical_url": f"{BASE}/p/{slug}", "cover_image": f"https://substackcdn.com/{slug}.png",
        "body_html": None, "postTags": [{"name": "LLM"}], **extra,
    }


def _post(slug: str, audience: str = "everyone", wordcount: int = 100, body_words: int | None = None, **extra):
    words = wordcount if body_words is None else body_words
    return {**_item(slug, audience, wordcount, **extra), "body_html": f"<p>{_words(words)}</p>"}


def _archive_url(offset: int, limit: int) -> str:
    return f"{BASE}/api/v1/archive?sort=new&offset={offset}&limit={limit}"


def _post_url(slug: str) -> str:
    return f"{BASE}/api/v1/posts/{slug}"


class SubstackResolutionTests(unittest.TestCase):
    def _registry(self):
        from insight_core.tests.test_source_kinds import _StubYouTube

        return KindRegistry.default(FakeHttp(), _StubYouTube())

    def test_substack_hosts_and_configured_custom_domains_resolve_to_substack(self):
        registry = self._registry()
        self.assertEqual(registry.resolve(_src()).name, "substack")
        self.assertEqual(registry.resolve(_src("https://kaitchup.substack.com/feed")).name, "substack")
        self.assertEqual(registry.resolve(_src("https://www.example-news.com/", substack=True)).name, "substack")
        self.assertEqual(registry.resolve(_src("https://www.other-news.com/")).name, "generic_rss")

    def test_every_substack_source_shares_one_floored_host_key(self):
        kind = SubstackKind(FakeHttp(), sid="")
        self.assertEqual(kind.host_key(_src()), SUBSTACK_HOST_KEY)
        self.assertEqual(kind.host_key(_src("https://x.example.com/", substack=True)), SUBSTACK_HOST_KEY)
        self.assertEqual(HOST_FLOORS[SUBSTACK_HOST_KEY], 2.0)
        self.assertEqual(kind.profile.concurrency_pool, "host-lock")


class SubstackFetchTests(unittest.IsolatedAsyncioTestCase):
    def _http(self, responses: dict) -> FakeHttp:
        return FakeHttp({url: json.dumps(body) if not isinstance(body, (str, Exception)) else body
                         for url, body in responses.items()})

    async def test_free_post_is_stored_in_full_without_a_cookie(self):
        http = self._http({
            _archive_url(0, 1): [_item("free")],
            _post_url("free"): _post("free", title="Q &amp; A", body_words=100),
        })
        posts = await SubstackKind(http, sid="").fetch_latest(_src(), 1)
        self.assertEqual(len(posts), 1)
        post = posts[0]
        self.assertEqual(post["url"], f"{BASE}/p/free")
        self.assertEqual(post["title"], "Q & A")
        self.assertEqual(len(post["content"].split()), 100)
        self.assertFalse(post["metadata"]["paywalled"])
        self.assertEqual(post["metadata"]["audience"], "everyone")
        self.assertIn("https://substackcdn.com/free.png", post["media_urls"])
        self.assertEqual(post["categories"], ["LLM"])
        self.assertIsNotNone(post["date"])
        self.assertEqual(http.headers_for(_post_url("free")).get("Cookie"), None)

    async def test_paid_post_with_a_cookie_is_stored_in_full_and_sends_the_cookie(self):
        http = self._http({
            _archive_url(0, 1): [_item("paid", "only_paid", 1000)],
            _post_url("paid"): _post("paid", "only_paid", 1000),
        })
        posts = await SubstackKind(http, sid="s3cret").fetch_latest(_src(), 1)
        self.assertFalse(posts[0]["metadata"]["paywalled"])
        self.assertEqual(len(posts[0]["content"].split()), 1000)
        self.assertEqual(http.headers_for(_post_url("paid"))["Cookie"], "substack.sid=s3cret")

    async def test_paid_post_without_a_cookie_is_truncated_and_marked_paywalled(self):
        http = self._http({
            _archive_url(0, 1): [_item("paid", "only_paid", 1367)],
            _post_url("paid"): _post("paid", "only_paid", 1367, body_words=270),
        })
        posts = await SubstackKind(http, sid="").fetch_latest(_src(), 1)
        self.assertTrue(posts[0]["metadata"]["paywalled"])
        self.assertEqual(len(posts[0]["content"].split()), 270)

    async def test_truncated_paid_post_with_a_cookie_means_the_session_expired(self):
        http = self._http({
            _archive_url(0, 1): [_item("paid", "only_paid", 1367)],
            _post_url("paid"): _post("paid", "only_paid", 1367, body_words=270),
        })
        with self.assertRaises(KindUnavailable) as caught:
            await SubstackKind(http, sid="s3cret").fetch_latest(_src(), 1)
        self.assertEqual(caught.exception.reason, EXPIRED_REASON)
        self.assertNotIn("s3cret", str(caught.exception))

    async def test_rejected_cookie_means_the_session_expired(self):
        http = self._http({
            _archive_url(0, 1): [_item("paid", "only_paid", 1367)],
            _post_url("paid"): ValueError(f"HTTP 403 while fetching {_post_url('paid')}: denied"),
        })
        with self.assertRaises(KindUnavailable) as caught:
            await SubstackKind(http, sid="s3cret").fetch_latest(_src(), 1)
        self.assertEqual(caught.exception.reason, EXPIRED_REASON)

    async def test_founding_only_posts_never_expire_the_session(self):
        http = self._http({
            _archive_url(0, 1): [_item("founders", "founding", 1000)],
            _post_url("founders"): _post("founders", "founding", 1000, body_words=100),
        })
        posts = await SubstackKind(http, sid="s3cret").fetch_latest(_src(), 1)
        self.assertTrue(posts[0]["metadata"]["paywalled"])

    async def test_the_archive_api_failing_falls_back_to_the_rss_feed(self):
        feed = (
            '<?xml version="1.0"?><rss version="2.0"><channel><item><title>Tips &amp;amp; tricks</title>'
            f"<link>{BASE}/p/tips</link><description>teaser</description>"
            "<pubDate>Wed, 08 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>"
        )
        http = self._http({
            _archive_url(0, 5): ValueError("HTTP 500 while fetching archive"),
            f"{BASE}/feed": feed,
            _post_url("tips"): _post("tips", body_words=50),
        })
        posts = await SubstackKind(http, sid="").fetch_latest(_src(), 5)
        self.assertEqual([p["url"] for p in posts], [f"{BASE}/p/tips"])
        self.assertEqual(len(posts[0]["content"].split()), 50)

    async def test_live_fetch_pages_the_archive_and_spaces_post_requests(self):
        page0 = [_item(f"p{i}") for i in range(12)]
        page1 = [_item(f"p{i}") for i in range(12, 15)]
        responses = {_archive_url(0, 12): page0, _archive_url(12, 3): page1}
        responses.update({_post_url(f"p{i}"): _post(f"p{i}") for i in range(15)})
        http = self._http(responses)
        posts = await SubstackKind(http, sid="").fetch_latest(_src(), 15)
        self.assertEqual(len(posts), 15)
        self.assertTrue(http.sleeper.calls)
        self.assertTrue(all(delay > 0 for delay in http.sleeper.calls))


class SubstackArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_archive_pages_by_offset_with_resumable_checkpoints(self):
        responses = {
            _archive_url(0, 12): json.dumps([_item(f"p{i}") for i in range(12)]),
            _archive_url(12, 12): json.dumps([_item(f"p{i}") for i in range(12, 20)]),
        }
        responses.update({_post_url(f"p{i}"): json.dumps(_post(f"p{i}")) for i in range(20)})
        http = FakeHttp(responses)
        kind = SubstackKind(http, sid="")
        rate = RateLimit(page_delay_s=3, batch_size=0, batch_cooldown_s=0)
        pages = [page async for page in kind.archive_pages(_src(), 30, None, rate)]
        self.assertEqual([len(p.posts) for p in pages], [12, 8])
        self.assertEqual(pages[0].checkpoint["offset"], 12)
        self.assertTrue(kind.checkpoint_resumable(pages[0].checkpoint))
        self.assertIn(3, http.sleeper.calls)

        resumed = [page async for page in kind.archive_pages(_src(), 30, pages[0].checkpoint, rate)]
        self.assertEqual([len(p.posts) for p in resumed], [8])
        self.assertEqual(resumed[0].checkpoint["collected_posts"], 20)


if __name__ == "__main__":
    unittest.main()
