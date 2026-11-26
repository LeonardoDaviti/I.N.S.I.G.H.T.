"""hnrss.org's feeds read from Hacker News' search (Algolia) when hnrss fails (ingestion/feed_alternates.py): the same
search hnrss asks, the same document, so every post keeps its address, title and date. No network: FakeHttp.

Fixtures (tests/fixtures/hn, public HN data): hnrss_newest.xml is six items of https://hnrss.org/newest?points=100&count=100
as hnrss served it on 2026-11-26 ~10:12 UTC; algolia_newest.json the same six stories' hits from
https://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=points>=100&hitsPerPage=100, read the same minute.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import feed_alternates
from insight_core.ingestion.feed_alternates import alternate
from insight_core.ingestion.feed_finder import find_feeds
from insight_core.ingestion.gates import HOST_FLOORS
from insight_core.ingestion.http import AddressMemory, HttpError
from insight_core.ingestion.kinds import KindRegistry, parsing
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.tests._kind_fakes import FakeHttp

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hn"
HNRSS = (FIXTURES / "hnrss_newest.xml").read_text()
ALGOLIA = (FIXTURES / "algolia_newest.json").read_text()
NEWEST = "https://hnrss.org/newest?points=100&count=100"
SHOW = "https://hnrss.org/show?points=30"
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
SOURCE = {"id": "hn", "platform": "rss", "handle_or_url": NEWEST,
          "settings": {"display_name": "Hacker News", "fetch_full_content": False}}


def query(url: str) -> dict:
    parts = urllib.parse.urlsplit(url)
    return {"at": f"{parts.scheme}://{parts.netloc}{parts.path}",
            **{k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}}


def answers(hnrss=HttpError("HTTP 502 while fetching hnrss", status=502), algolia=ALGOLIA):
    """hnrss.org answers `hnrss`, Hacker News' search `algolia`; anything else a 404."""
    def answer(url: str):
        if url.startswith("https://hnrss.org/"):
            return hnrss
        if url.startswith(feed_alternates.ALGOLIA_SEARCH):
            return algolia
        return HttpError(f"HTTP 404 while fetching {url}", status=404)
    return answer


class AlgoliaSearchOfAnAddress(unittest.TestCase):
    def test_newest_with_points_and_count(self):
        got = alternate(NEWEST)
        self.assertEqual(got.host, "hn.algolia.com")
        self.assertEqual(query(got.url), {
            "at": "https://hn.algolia.com/api/v1/search_by_date", "tags": "(story,poll)",
            "numericFilters": "points>=100", "hitsPerPage": "100", "restrictSearchableAttributes": "title"})

    def test_show_ask_and_frontpage_tags(self):
        self.assertEqual(query(alternate(SHOW).url)["tags"], "show_hn")
        self.assertNotIn("hitsPerPage", query(alternate(SHOW).url))     # none asked: Algolia's 20, as hnrss
        self.assertEqual(query(alternate("https://hnrss.org/ask?points=10").url)["tags"], "ask_hn")
        front = query(alternate("https://hnrss.org/frontpage?points=50", now=NOW).url)
        self.assertEqual(front["tags"], "front_page")
        week_ago = int(NOW.timestamp()) - 7 * 24 * 3600
        self.assertEqual(front["numericFilters"], f"points>=50,created_at_i>={week_ago}")

    def test_comments_query_and_count_as_hnrss_reads_them(self):
        got = query(alternate("https://hnrss.org/newest?q=Qwen&comments=20&count=500").url)
        self.assertEqual((got["query"], got["numericFilters"], got["hitsPerPage"]), ('"Qwen"', "num_comments>=20", "100"))
        either = query(alternate("https://hnrss.org/newest?q=rust OR zig").url)
        self.assertEqual((either["query"], either["optionalWords"]), ('"rust" "zig"', '"rust" "zig"'))
        self.assertEqual(query(alternate("https://hnrss.org/newest?count=lots").url)["hitsPerPage"], "20")
        self.assertNotIn("restrictSearchableAttributes",
                         query(alternate("https://hnrss.org/newest?q=x&search_attrs=default").url))

    def test_addresses_no_alternate_reads(self):
        for url in ("https://hnrss.org/newest.atom", "https://hnrss.org/user?id=dang", "https://hnrss.org/item?id=1",
                    "https://hnrss.org/newcomments", "https://news.ycombinator.com/rss", "https://x.example/newest"):
            self.assertIsNone(alternate(url), url)


class SamePosts(unittest.TestCase):
    """The critical part: the posts read from Algolia are the posts read from hnrss."""

    def both(self, url=NEWEST, hnrss=HNRSS, algolia=ALGOLIA):
        real = {post["guid"]: post for post in parsing.parse_feed_posts(hnrss, url)}
        instead = {post["guid"]: post for post in parsing.parse_feed_posts(alternate(url).render(algolia), url)}
        return real, instead

    def test_every_item_has_the_same_address_title_date_and_thread(self):
        real, instead = self.both()
        self.assertEqual(len(real), 6)
        self.assertEqual(set(real), set(instead))
        for guid, post in real.items():
            for field in ("url", "title", "date", "date_precision", "guid", "metadata", "external_id"):
                self.assertEqual(instead[guid].get(field), post.get(field), (guid, field))

    def test_the_story_hnrss_missed_and_a_text_post(self):
        _, instead = self.both()
        qwen = instead["https://news.ycombinator.com/item?id=50648365"]
        self.assertEqual((qwen["url"], qwen["title"], qwen["date"]), (
            "https://github.com/alesha-pro/llm.asm/tree/main/02-baremetal-os", "Bare Metal Qwen",
            datetime(2026, 11, 25, 22, 15, 34, tzinfo=timezone.utc)))
        tell = instead["https://news.ycombinator.com/item?id=50649864"]    # no link: the HN item page is its address
        self.assertEqual(tell["url"], "https://news.ycombinator.com/item?id=50649864")
        self.assertTrue(tell["content"].startswith("There have been questions about why the /ask page"))

    def test_the_body_is_hnrss_own_but_for_counts_that_moved(self):
        real, instead = self.both()
        same = "https://news.ycombinator.com/item?id=50648365"     # 110 points in both reads
        self.assertEqual(instead[same]["content_html"], real[same]["content_html"])
        moved = "https://news.ycombinator.com/item?id=50648050"    # a point more by the Algolia read
        self.assertEqual(instead[moved]["content"], real[moved]["content"].replace("Points: 386", "Points: 387"))

    def test_link_to_comments_and_no_description(self):
        url = "https://hnrss.org/newest?points=100&link=comments&description=0"
        doc = alternate(url).render(ALGOLIA)
        self.assertEqual(doc.count("<description>"), 1)    # the channel's own, no item's
        posts = parsing.parse_feed_posts(doc, url)
        self.assertTrue(all(post["url"].startswith("https://news.ycombinator.com/item?id=") for post in posts))

    def test_a_title_with_entities_and_cdata_end(self):
        hit = '{"hits": [{"objectID": "7", "title": "A &amp; B ]]> C", "url": "https://x.example/?a=1&b=2", ' \
              '"created_at_i": 1795664218, "author": "me", "points": 1, "num_comments": 0}]}'
        post = parsing.parse_feed_posts(alternate(NEWEST).render(hit), NEWEST)[0]
        self.assertEqual((post["title"], post["url"]), ("A & B ]]> C", "https://x.example/?a=1&b=2"))

    def test_an_answer_that_is_no_search_is_an_error(self):
        with self.assertRaises(ValueError):
            alternate(NEWEST).render('{"message": "Invalid"}')


class ReadWhenHnrssFails(unittest.TestCase):
    def fetch(self, http, memory=None, source=SOURCE):
        return asyncio.run(GenericRssKind(http).fetch_latest(source, 100, memory=memory))

    def test_a_502_reads_the_same_posts_from_algolia_and_says_so(self):
        posts = self.fetch(FakeHttp(answers()))
        read = self.fetch(FakeHttp(answers(hnrss=HNRSS)))
        self.assertEqual([p["url"] for p in posts], [p["url"] for p in read])
        self.assertIn("hnrss.org answered HTTP 502: read from Hacker News' search (hn.algolia.com) instead",
                      posts.warning)
        self.assertIsNone(posts.failure)
        self.assertIsNone(read.warning)                     # hnrss answering: read as ever, no Algolia request

    def test_a_conditional_fetch_falls_back_too_and_learns_nothing(self):
        http = FakeHttp(answers(hnrss=HttpError("timed out", timed_out=True)))
        memory = AddressMemory({}, now=NOW)
        posts = self.fetch(http, memory)
        self.assertEqual(len(posts), 6)
        self.assertIn("did not answer in time", posts.warning)
        self.assertFalse(memory.changed)
        self.assertTrue(http.requests[-1].startswith(feed_alternates.ALGOLIA_SEARCH))
        self.assertEqual(http.user_agents[-1], (http.requests[-1], None))   # the app's own User-Agent

    def test_both_failing_is_hnrss_failing(self):
        with self.assertRaises(HttpError) as raised:
            self.fetch(FakeHttp(answers(algolia=HttpError("HTTP 503", status=503))))
        self.assertEqual(raised.exception.status, 502)     # the source's failure stays its own (backoff: their trouble)

    def test_another_address_failing_asks_nothing_else(self):
        http = FakeHttp(answers())
        with self.assertRaises(HttpError):
            self.fetch(http, source={**SOURCE, "handle_or_url": "https://hnrss.org/newest.atom"})
        self.assertEqual(http.requests, ["https://hnrss.org/newest.atom"])


class AddingAnHnrssAddressWhileItFails(unittest.TestCase):
    def test_the_feed_finder_finds_the_address_itself(self):
        http = FakeHttp(answers())
        finding = asyncio.run(find_feeds(http, KindRegistry.default(http, None), NEWEST))
        self.assertEqual(finding.status, "feed")
        self.assertEqual((finding.feeds[0].url, finding.feeds[0].title), (NEWEST, "Hacker News: Newest"))


class HostBudget(unittest.TestCase):
    def test_hnrss_sources_keep_algolias_floor(self):
        from insight_core.ingestion.discussions import HN

        self.assertEqual(HOST_FLOORS["hnrss.org"], HN.floors["hn.algolia.com"])


if __name__ == "__main__":
    unittest.main()
