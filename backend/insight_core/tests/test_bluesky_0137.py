"""Issue 0137 B10: the bluesky kind on the public API, behind INSIGHT_BLUESKY (default off). No network:
every request is a FakeHttp answer; the accounts and posts are invented."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.feed_finder import find_feeds
from insight_core.ingestion.gates import HOST_FLOORS
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import KindUnavailable
from insight_core.ingestion.kinds.bluesky import (
    API,
    BLUESKY_HOST_KEY,
    OPTED_OUT,
    BlueskyKind,
    actor,
    title_from,
)
from insight_core.tests._kind_fakes import FakeHttp

PROFILE_URL = "https://bsky.app/profile/someone.example"
DID = "did:plc:someone"
ON = {"INSIGHT_BLUESKY": "on"}


def run(coro):
    return asyncio.run(coro)


def profile(labels=()):
    return json.dumps({"did": DID, "handle": "someone.example", "postsCount": 3,
                       "labels": [{"val": label} for label in labels]})


def row(rkey, text, at, *, did=DID, handle="someone.example", reason=None):
    item = {"post": {"uri": f"at://{did}/app.bsky.feed.post/{rkey}", "author": {"did": did, "handle": handle},
                     "record": {"text": text, "createdAt": at}, "indexedAt": at}}
    if reason:
        item["reason"] = {"$type": reason}
    return item


def answers(pages, labels=()):
    """{url: body}: the profile, and getAuthorFeed pages by cursor (None: the first)."""
    def answer(url):
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if url.startswith(f"{API}/app.bsky.actor.getProfile"):
            return profile(labels)
        if url.startswith(f"{API}/app.bsky.feed.getAuthorFeed"):
            return json.dumps(pages[query.get("cursor")])
        raise ValueError(f"HTTP 404 while fetching {url}")
    return answer


FIRST = {"feed": [row("3k2", "Rates held again\nThe long thread follows.", "2026-11-06T10:00:00.000Z"),
                  row("3k1", "Someone else's post", "2026-11-05T10:00:00.000Z", did="did:plc:other", handle="other.example",
                      reason="app.bsky.feed.defs#reasonRepost")],
         "cursor": "c1"}
SECOND = {"feed": [row("3k0", "An older post", "2026-10-01T08:00:00.000Z")]}


class BlueskyTests(unittest.TestCase):
    def test_off_by_default_the_kind_matches_nothing_and_the_finder_is_unchanged(self):
        http = FakeHttp({})
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("INSIGHT_BLUESKY", None)
            registry = KindRegistry.default(http, None)
            self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": PROFILE_URL}).name, "generic_rss")

    def test_on_a_profile_resolves_to_bluesky_and_the_finder_answers_direct(self):
        with mock.patch.dict("os.environ", ON):
            http = FakeHttp({})
            registry = KindRegistry.default(http, None)
            self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": PROFILE_URL}).name, "bluesky")
            self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": "https://bsky.app/about"}).name,
                             "generic_rss")
            self.assertEqual(run(find_feeds(http, registry, PROFILE_URL)).status, "direct")

    def test_the_address_and_the_title(self):
        self.assertEqual(actor("bsky.app/profile/someone.example"), "someone.example")
        self.assertEqual(actor("https://bsky.app/profile/did:plc:abc/post/3k"), "did:plc:abc")
        self.assertIsNone(actor("https://bsky.app/"))
        self.assertEqual(title_from("\n  First   line here \nsecond"), "First line here")
        long = title_from("word " * 60)
        self.assertLessEqual(len(long), 120)
        self.assertTrue(long.endswith("…"))

    def test_a_fetch_reads_the_authors_own_posts_with_title_date_and_address(self):
        with mock.patch.dict("os.environ", ON):
            http = FakeHttp(answers({None: FIRST}))
            posts = run(BlueskyKind(http).fetch_latest({"handle_or_url": PROFILE_URL}, 20))
        (post,) = posts   # the repost of someone else's post is skipped
        self.assertEqual(post["url"], "https://bsky.app/profile/someone.example/post/3k2")
        self.assertEqual(post["external_id"], "3k2")
        self.assertEqual(post["title"], "Rates held again")
        self.assertEqual(post["content"], "Rates held again\nThe long thread follows.")
        self.assertEqual(post["date"], datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(post["metadata"]["at_uri"], f"at://{DID}/app.bsky.feed.post/3k2")
        self.assertTrue(http.requests[0].startswith(f"{API}/app.bsky.actor.getProfile?actor=someone.example"))
        self.assertIn("filter=posts_no_replies", http.requests[1])

    def test_an_account_that_opted_out_of_logged_out_readers_is_never_read(self):
        http = FakeHttp(answers({None: FIRST}, labels=("!no-unauthenticated",)))
        with self.assertRaises(KindUnavailable) as caught:
            run(BlueskyKind(http).fetch_latest({"handle_or_url": PROFILE_URL}, 20))
        self.assertEqual(caught.exception.reason, OPTED_OUT)
        self.assertEqual(len(http.requests), 1)   # the profile only; no post was asked for

    def test_the_archive_pages_by_cursor_and_resumes(self):
        http = FakeHttp(answers({None: FIRST, "c1": SECOND}))
        kind = BlueskyKind(http)

        async def pages(checkpoint=None):
            return [page async for page in kind.archive_pages({"handle_or_url": PROFILE_URL}, 100, checkpoint, None)]
        got = run(pages())
        self.assertEqual([[p["external_id"] for p in page.posts] for page in got], [["3k2"], ["3k0"]])
        self.assertEqual(got[0].checkpoint["cursor"], "c1")
        self.assertTrue(kind.checkpoint_resumable(got[0].checkpoint))
        self.assertFalse(kind.checkpoint_resumable(got[1].checkpoint))
        resumed = run(pages(got[0].checkpoint))
        self.assertEqual([p["external_id"] for p in resumed[0].posts], ["3k0"])

    def test_every_source_shares_one_host_floor(self):
        kind = BlueskyKind(FakeHttp({}))
        self.assertEqual(kind.host_key({"handle_or_url": PROFILE_URL}), BLUESKY_HOST_KEY)
        self.assertGreater(HOST_FLOORS[BLUESKY_HOST_KEY], 0)


if __name__ == "__main__":
    unittest.main()
