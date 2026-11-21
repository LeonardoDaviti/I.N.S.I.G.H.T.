"""Issue 0254: ingestion after the v10.27 deploy. Invented feeds and accounts only.

1. parsing._identities: when most items link one page (a changelog, a news page), each item still has an address of
   its own (the feed's with its guid, else its title and date); a guid every item shares names no item.
2. parsing.read_feed: one broken item (an unclosed CDATA) is skipped and reported, the rest read; a CDATA left open
   that runs into the next item hides nothing; a broken header still fails the feed.
3. operations_service.stalled_fields: a source whose live fetch never worked but holds posts carries its posts and
   its last error ("its live feed fails: ...", sourceList.stalledNote).
4. kinds' test_read and feed_finder.test_read: a YouTube channel or an X account that the platform says is not there
   is refused by POST /api/sources; any other failure is a warning.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion import feed_finder
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry, parsing
from insight_core.ingestion.kinds.base import ReadCheck, checked_fetch, collapsed
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.kinds.nitter_rss import NitterRssKind
from insight_core.ingestion.kinds.youtube import YouTubeKind
from insight_core.services.operations_service import stalled_fields
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
FEED = "https://tool.example/changelog/rss.xml"
PAGE = "https://tool.example/changelog"


def run(coro):
    return asyncio.run(coro)


def _rss(items: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0" '
            'xmlns:content="http://purl.org/rss/1.0/modules/content/">\n<channel><title>Tool changelog</title>\n'
            f'{items}\n</channel></rss>')


def _item(n: int, *, link: str = PAGE, guid: str | None = None, body: str | None = None, title: str | None = None) -> str:
    guid_tag = f"<guid isPermaLink=\"false\">{guid}</guid>" if guid is not None else ""
    body = body if body is not None else f"<![CDATA[<p>Release {n} notes.</p>]]>"
    return (f"<item><title>{title or f'Release 1.{n}'}</title><link>{link}</link>{guid_tag}"
            f"<pubDate>Mon, {1 + n % 28:02d} Sep 2026 10:00:00 GMT</pubDate>"
            f"<content:encoded>{body}</content:encoded></item>\n")


# --------------------------------------------------------------------------- 1. items that share one link


class SharedLinkTests(unittest.TestCase):
    def _addresses(self, feed: str, url: str = FEED) -> list:
        posts = parsing.parse_feed_posts(feed, url)
        self.assertIsNone(collapsed(posts))
        return [post["url"] for post in posts]

    def test_a_changelog_whose_items_have_plain_guids(self):
        urls = self._addresses(_rss("".join(_item(n, guid=f"release-1.{n}") for n in range(42))))
        self.assertEqual(len(set(urls)), 42)
        self.assertIn(f"{FEED}?{parsing.ITEM_PARAM}=release-1.7", urls)

    def test_a_news_feed_whose_items_have_no_guid(self):
        urls = self._addresses(_rss("".join(_item(n, link="https://news.example/") for n in range(30))),
                               "https://news.example/news.rss")
        self.assertEqual(len(set(urls)), 30)
        self.assertTrue(all(f"?{parsing.ITEM_PARAM}=Release%201." in url for url in urls), urls[:2])

    def test_a_guid_every_item_shares_names_no_item(self):
        # Every item's guid is the home page, every link too: each is known by its title and date.
        items = "".join(_item(n, link="https://news.example/", guid="https://news.example/") for n in range(25))
        urls = self._addresses(_rss(items), "https://news.example/news.rss")
        self.assertEqual(len(set(urls)), 25)

    def test_the_addresses_are_the_same_at_every_fetch(self):
        items = [_item(n, guid=f"r{n}") for n in range(10)]
        first = self._addresses(_rss("".join(items)))
        # A newer fetch: one item more, the oldest gone; the others keep their address.
        again = self._addresses(_rss(_item(10, guid="r10") + "".join(items[1:])))
        self.assertEqual(len(set(first) & set(again)), 9)
        self.assertNotIn(f"{FEED}?{parsing.ITEM_PARAM}=r0", again)

    def test_links_of_their_own_and_true_duplicates_are_kept_as_before(self):
        own = self._addresses(_rss("".join(_item(n, link=f"https://blog.example/p/{n}", guid=f"g{n}")
                                           for n in range(5))), "https://blog.example/feed")
        self.assertEqual(own, [f"https://blog.example/p/{n}" for n in (4, 3, 2, 1, 0)])
        # The same item twice (same guid, title and date): one post.
        twice = parsing.parse_feed_posts(_rss(_item(1, guid="x") * 2), FEED)
        self.assertEqual(len({post["url"] for post in twice}), 1)


# --------------------------------------------------------------------------- 2. one broken item


class BrokenItemTests(unittest.TestCase):
    BROKEN = "<![CDATA[<p>The quote that never closes</p>"   # no ]]>

    def _feed(self, broken_at: int, total: int = 12) -> str:
        return _rss("".join(_item(n, link=f"https://blog.example/p/{n}",
                                  body=self.BROKEN if n == broken_at else None,
                                  title="The broken one" if n == broken_at else None) for n in range(total)))

    def test_the_broken_item_is_skipped_and_said_the_rest_read(self):
        for broken_at in (0, 5, 11):   # first, middle, last
            with self.subTest(broken_at=broken_at):
                posts = parsing.parse_feed_posts(self._feed(broken_at), "https://blog.example/feed")
                self.assertEqual(len(posts), 11)
                self.assertNotIn(f"https://blog.example/p/{broken_at}", [post["url"] for post in posts])
                self.assertEqual(len(posts.broken), 1)
                self.assertIn('the item "The broken one"', posts.broken[0])
                self.assertIn("unclosed CDATA section", posts.broken[0])

    def test_a_cdata_left_open_that_runs_into_the_next_item_hides_nothing(self):
        # The open CDATA closes at the next item's "]]>": valid XML that would hold 11 items of 12, one swallowed.
        posts = parsing.parse_feed_posts(self._feed(5), "https://blog.example/feed")
        self.assertIn("https://blog.example/p/6", [post["url"] for post in posts])

    def test_the_fetch_stores_the_rest_with_a_warning(self):
        kind = GenericRssKind(FakeHttp({"https://blog.example/feed": self._feed(11)}))
        fetched = run(kind.fetch_latest({"id": "s1", "platform": "rss", "handle_or_url": "https://blog.example/feed",
                                         "settings": {"display_name": "Blog"}}, 50))
        self.assertEqual(len(fetched), 11)
        self.assertIsNone(fetched.failure)
        self.assertRegex(fetched.warning, r'^1 broken item skipped: the item "The broken one" \(line \d+\): '
                                          r'unclosed CDATA section')

    def test_an_item_whose_text_holds_item_tags_is_no_broken_item(self):
        quoted = "<![CDATA[<p>Write <item> and </item> in your feed</p>]]>"
        items = "".join(_item(n, link=f"https://blog.example/p/{n}", body=quoted if n == 2 else None) for n in range(4))
        broken = _item(4, link="https://blog.example/p/4", body=self.BROKEN)
        posts = parsing.parse_feed_posts(_rss(items + broken), "https://blog.example/feed")
        self.assertEqual(sorted(post["url"] for post in posts), [f"https://blog.example/p/{n}" for n in range(4)])
        self.assertEqual(len(posts.broken), 1)

    def test_a_feed_mostly_broken_or_broken_outside_its_items_still_fails(self):
        items = "".join(_item(n, link=f"https://blog.example/p/{n}", body=self.BROKEN.replace("]]>", "")
                              if n % 3 else "<p>&undefined;</p>") for n in range(6))
        with self.assertRaises(Exception):
            parsing.parse_feed_posts(_rss(items), "https://blog.example/feed")
        with self.assertRaises(Exception):
            parsing.parse_feed_posts(_rss(_item(1)).replace("<title>Tool changelog</title>",
                                                            "<title>Tool <b>changelog</title>"), FEED)

    def test_a_valid_feed_has_no_broken_items(self):
        posts = parsing.parse_feed_posts(_rss("".join(_item(n, link=f"https://b.example/{n}") for n in range(3))),
                                         "https://b.example/feed")
        self.assertEqual((len(posts), posts.broken), (3, []))
        self.assertIsNone(checked_fetch(posts, 3, {}, broken=posts.broken).warning)


# --------------------------------------------------------------------------- 3. stopped with archived posts


class StoppedWithPostsTests(unittest.TestCase):
    def test_a_source_whose_live_feed_never_worked_carries_its_posts_and_last_error(self):
        state = FetchStateRow(source_id="s1", consecutive_failures=6, last_outcome="error",
                              last_error="the feed has 42 items but 1 would be stored",
                              last_error_at=NOW - timedelta(hours=2))
        source = {"platform": "rss", "created_at": NOW - timedelta(days=4)}
        flag = stalled_fields(source, state, timedelta(hours=6), 6, True, NOW, 48)
        self.assertEqual(flag, {"since": None, "days": 4, "failures": 6, "posts": 48,
                                "reason": "the feed has 42 items but 1 would be stored"})

    def test_no_reason_once_the_last_attempt_worked(self):
        state = FetchStateRow(source_id="s1", consecutive_failures=0, last_outcome="empty",
                              last_success_at=NOW - timedelta(days=5), last_error="old",
                              last_error_at=NOW - timedelta(days=6))
        flag = stalled_fields({"platform": "rss", "created_at": NOW - timedelta(days=9)}, state,
                              timedelta(hours=6), 0, True, NOW, 3)
        self.assertIsNone(flag["reason"])


# --------------------------------------------------------------------------- 4. the test read before adding


class FakeYouTube:
    DEFAULT_PAGE_SIZE = 15

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.asked: list = []

    def test_read_channel(self, handle):
        self.asked.append(handle)
        if self.error:
            raise self.error


NITTER_FEED = "http://nitter.local/someone/rss"
NITTER_RSS = _rss('<item><title>A post</title><link>http://nitter.local/someone/status/1234567890123456789#m</link>'
                  '<guid>http://nitter.local/someone/status/1234567890123456789</guid></item>')


class TestReadTests(unittest.TestCase):
    def _check(self, kind, source) -> ReadCheck | None:
        return run(feed_finder.test_read(KindRegistry([kind]), source))

    def test_a_youtube_handle_the_platform_does_not_know_is_gone(self):
        youtube = FakeYouTube(ValueError("yt-dlp failed (1): ERROR: [youtube:tab] @nobody: HTTP Error 404: Not Found"))
        check = self._check(YouTubeKind(youtube), {"platform": "youtube", "handle_or_url": "https://www.youtube.com/@nobody"})
        self.assertTrue(check.gone)
        self.assertIn("HTTP Error 404", check.reason)
        self.assertEqual(youtube.asked, ["https://www.youtube.com/@nobody"])

    def test_a_youtube_bot_check_is_a_warning_and_a_channel_that_reads_is_none(self):
        bot = self._check(YouTubeKind(FakeYouTube(ValueError("Sign in to confirm you're not a bot"))),
                          {"platform": "youtube", "handle_or_url": "@somechannel"})
        self.assertEqual((bot.gone, bot.reason), (False, "Sign in to confirm you're not a bot"))
        self.assertIsNone(self._check(YouTubeKind(FakeYouTube()), {"platform": "youtube", "handle_or_url": "@fine"}))

    def test_an_x_account_through_the_bridge(self):
        source = {"platform": "x", "handle_or_url": NITTER_FEED}
        gone = self._check(NitterRssKind(FakeHttp({NITTER_FEED: HttpError("HTTP 404", status=404)})), source)
        self.assertTrue(gone.gone)
        down = self._check(NitterRssKind(FakeHttp({NITTER_FEED: HttpError("HTTP 502", status=502)})), source)
        self.assertFalse(down.gone)
        self.assertIsNone(self._check(NitterRssKind(FakeHttp({NITTER_FEED: NITTER_RSS})), source))

    def test_a_feed_has_no_test_read_here(self):
        http = FakeHttp({})
        self.assertIsNone(self._check(GenericRssKind(http), {"platform": "rss", "handle_or_url": FEED}))
        self.assertEqual(http.requests, [], "a feed is read by the finder before the Add, not again")


@requires_test_db
class AddSourceRouteTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        import main
        from insight_core.services import registry

        self.main = main
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        self.youtube = registry.services().source_fetch.kinds.by_name("youtube_channel")

        def clean():
            with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s", ("%@invented0254%",))

        clean()
        self.addCleanup(clean)

    def add(self, error):
        from insight_core.tests._asgi import call

        with mock.patch.object(self.main, "_export_sources_json"), \
                mock.patch.object(self.youtube, "youtube", FakeYouTube(error)), \
                mock.patch.object(self.main, "_name_new_source", mock.AsyncMock(return_value=None)):
            return call(self.main.app, "POST", "/api/sources",
                        json_body={"platform": "youtube", "handle_or_url": "https://www.youtube.com/@invented0254"})

    def test_a_channel_the_platform_does_not_know_is_not_added(self):
        status, _, answer = self.add(ValueError("yt-dlp failed (1): ERROR: HTTP Error 404: Not Found"))
        self.assertEqual(status, 400, answer)
        self.assertIn("Not added: https://www.youtube.com/@invented0254 can't be read", str(answer))

    def test_a_channel_that_may_read_later_is_added_with_the_reason(self):
        status, _, answer = self.add(ValueError("yt-dlp timed out after 45s"))
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["warning"], "yt-dlp timed out after 45s")
        status, _, answer = self.add(None)
        self.assertEqual(status, 400, "already a source")


if __name__ == "__main__":
    unittest.main()


class UndatedBacklog(unittest.TestCase):
    """v10.30: a feed that dates only its recent items: its undated older items are no newer than the nearest dated
    item on their newer side (never "this week" on a first fetch); undated items newer than all stay "seen"."""

    def feed(self, items):
        body = "".join(f"<item><title>{t}</title><link>https://zq.example/{t}</link>"
                       + (f"<pubDate>{d}</pubDate>" if d else "") + "</item>" for t, d in items)
        return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Zq</title>{body}</channel></rss>'

    def test_newest_first(self):
        from insight_core.ingestion.kinds.parsing import parse_feed_posts
        from insight_core.db.repo_posts import published_precision
        posts = parse_feed_posts(self.feed([("top", None), ("new", "Sun, 18 Oct 2026 00:00:00 +0000"),
                                            ("mid", "Sun, 23 Aug 2026 00:00:00 +0000"), ("old1", None),
                                            ("old2", None)]), "https://zq.example/rss.xml")
        by = {p["title"]: p for p in posts}
        self.assertIsNone(by["top"]["date"])
        self.assertEqual(by["top"]["date_precision"], "seen")
        self.assertEqual(by["old1"]["date"].date().isoformat(), "2026-08-23")
        self.assertEqual(by["old2"]["date"].date().isoformat(), "2026-08-23")
        self.assertEqual(published_precision(by["old1"]), "none", "stored as no date given")

    def test_oldest_first_and_too_few_dates(self):
        from insight_core.ingestion.kinds.parsing import parse_feed_posts
        posts = parse_feed_posts(self.feed([("a", None), ("b", "Mon, 02 Mar 2026 00:00:00 +0000"), ("c", None),
                                            ("d", "Tue, 03 Nov 2026 00:00:00 +0000"), ("e", None)]), "https://zq.example/r")
        by = {p["title"]: p for p in posts}
        self.assertEqual(by["a"]["date"].date().isoformat(), "2026-03-02")
        self.assertEqual(by["c"]["date"].date().isoformat(), "2026-11-03")
        self.assertIsNone(by["e"]["date"], "newer than every dated item: seen")
        one = parse_feed_posts(self.feed([("x", "Mon, 02 Mar 2026 00:00:00 +0000"), ("y", None)]), "https://zq.example/r")
        self.assertIsNone({p["title"]: p for p in one}["y"]["date"], "one dated item tells no order")
