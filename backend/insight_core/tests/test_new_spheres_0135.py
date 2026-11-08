"""Issue 0135: feeds and channels that failed silently outside AI news. No network, no database:
every request is a FakeHttp answer or a stub, every feed and caption a fixture with invented hosts."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
from insight_core.ingestion.feed_finder import REFUSED, find_feeds, is_search_feed
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import EmptyFetch, FetchedPosts, checked_fetch
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.kinds.parsing import feed_items, parse_feed_posts
from insight_core.ingestion.kinds.telegram_mtproto import synthesize_posts
from insight_core.ingestion.kinds.telegram_rss import TelegramRssKind, bridge_origin, message_order_dates
from insight_core.ingestion.ports import _source_line
from insight_core.ingestion.source_doctor import EMPTY_FETCH, failure_signal
from insight_core.ingestion.where_linked import feed_row
from insight_core.scripts import repair_0135
from insight_core.services.youtube_service import YouTubeService, plain_transcript
from insight_core.tests._asgi import call
from insight_core.tests._kind_fakes import FakeHttp, FakeKind
from insight_core.tests.test_ingestion_runner import _Harness, _source
from insight_core.tests.test_source_doctor import look, state
from insight_core.utils.post_fields import build_post_fields

JOURNAL = "https://journal.example"

# An RSS 1.0 (RDF) table of contents, as scientific publishers serve them.
RDF = f"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"
         xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel rdf:about="{JOURNAL}/toc.rss"><title>Journal of Examples</title>
    <items><rdf:Seq><rdf:li rdf:resource="{JOURNAL}/articles/a1"/><rdf:li rdf:resource="{JOURNAL}/articles/a2"/></rdf:Seq></items>
  </channel>
  <item rdf:about="{JOURNAL}/articles/a1">
    <title>Sleep and memory in
      older adults</title>
    <link>{JOURNAL}/articles/a1</link>
    <description>A short abstract.</description>
    <content:encoded><![CDATA[<p>The full abstract, longer.</p>]]></content:encoded>
    <dc:creator>A. Author</dc:creator><dc:creator>B. Author</dc:creator>
    <dc:date>2026-11-02T08:00:00Z</dc:date>
  </item>
  <item rdf:about="{JOURNAL}/articles/a2">
    <title>Heat and attention</title>
    <description>Another abstract.</description>
    <prism:publicationDate>2026-11-05</prism:publicationDate>
  </item>
</rdf:RDF>"""

RDF_UNDATED = f"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns="http://purl.org/rss/1.0/"><channel rdf:about="{JOURNAL}/x"><title>Undated</title></channel>
  <item rdf:about="{JOURNAL}/articles/u1"><title>No date</title><link>{JOURNAL}/articles/u1</link></item></rdf:RDF>"""

# Items INSIGHT's parser does not read: an <rss> whose items sit outside its channel.
STRAY_ITEMS = ('<?xml version="1.0"?><rss version="2.0"><channel><title>Stray</title></channel>'
               "<item><title>One</title><link>https://stray.example/1</link></item>"
               "<item><title>Two</title><link>https://stray.example/2</link></item></rss>")


def toc_rss(title: str, *links: str) -> str:
    items = "".join(f"<item><title>Paper {n}</title><link>{link}</link><description>Abstract</description></item>"
                    for n, link in enumerate(links))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{items}</channel></rss>'


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- 1. RSS 1.0 (RDF)


class RdfFeedTests(unittest.TestCase):
    def test_an_rdf_feed_is_read_with_its_dates_authors_and_full_text(self):
        posts = parse_feed_posts(RDF, f"{JOURNAL}/toc.rss")
        self.assertEqual([p["title"] for p in posts], ["Heat and attention", "Sleep and memory in older adults"])
        heat, sleep = posts
        self.assertEqual(sleep["url"], f"{JOURNAL}/articles/a1")
        self.assertEqual(sleep["date"], datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(sleep["content_html"], "<p>The full abstract, longer.</p>")
        self.assertEqual(sleep["metadata"], {"authors": ["A. Author", "B. Author"]})
        # No <link>: its rdf:about; a PRISM date with no time of day says so.
        self.assertEqual(heat["url"], f"{JOURNAL}/articles/a2")
        self.assertEqual(heat["date"], datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertEqual(heat["date_precision"], "date")

    def test_an_rdf_item_without_a_date_is_kept_undated(self):
        (post,) = parse_feed_posts(RDF_UNDATED, f"{JOURNAL}/x")
        self.assertIsNone(post["date"])
        self.assertEqual(post["date_precision"], "seen")   # dated when first seen (issue 0137 B9)

    def test_a_generic_rss_source_on_an_rdf_feed_stores_its_items(self):
        http = FakeHttp({f"{JOURNAL}/toc.rss": RDF})
        posts = run(GenericRssKind(http).fetch_latest({"handle_or_url": f"{JOURNAL}/toc.rss",
                                                       "settings": {"fetch_full_content": False}}, 20))
        self.assertEqual(len(posts), 2)


# --------------------------------------------------------------------------- 2. an empty fetch is an error


class EmptyFetchTests(unittest.TestCase):
    def test_a_feed_with_items_none_read_is_an_error_saying_so(self):
        self.assertEqual(feed_items(STRAY_ITEMS), 2)
        http = FakeHttp({"https://stray.example/feed": STRAY_ITEMS})
        with self.assertRaises(EmptyFetch) as caught:
            run(GenericRssKind(http).fetch_latest({"handle_or_url": "https://stray.example/feed"}, 20))
        self.assertEqual(str(caught.exception), "the feed has 2 items but 0 were stored")

    def test_a_feed_with_no_items_is_still_empty_not_an_error(self):
        http = FakeHttp({"https://quiet.example/feed": toc_rss("Quiet")})
        self.assertEqual(run(GenericRssKind(http).fetch_latest({"handle_or_url": "https://quiet.example/feed"}, 20)), [])

    def test_every_item_skipped_is_an_error_with_its_reasons_counted(self):
        with self.assertRaises(EmptyFetch) as caught:
            checked_fetch([], 15, Counter({"the bot check": 14, "timed out": 1}), noun="videos")
        self.assertEqual(str(caught.exception), "every item was skipped (15 videos): 14 the bot check, 1 timed out")

    def test_over_half_skipped_is_a_warning(self):
        posts = checked_fetch([{"url": "a"}] * 3, 15, Counter({"the bot check": 12}), noun="videos")
        self.assertEqual(posts.warning, "12 of 15 videos skipped: 12 the bot check")
        self.assertIsNone(checked_fetch([{"url": "a"}] * 9, 15, Counter({"the bot check": 6})).warning)

    def test_a_channel_whose_every_video_hit_the_bot_check_fails_with_that_reason(self):
        service = YouTubeService("postgresql:///unused")
        service._list_channel_entries = lambda url, limit=None: [{"id": f"vid{n:08d}"} for n in range(4)]

        def blocked(video, handle):
            raise ValueError("yt-dlp failed (1): ERROR: [youtube] x: Sign in to confirm you're not a bot")
        service._build_video_post = blocked
        with self.assertRaises(EmptyFetch) as caught:
            service.fetch_live_posts("https://www.youtube.com/@a-channel", 4)
        self.assertEqual(str(caught.exception), "every item was skipped (4 videos): 4 the bot check")

    def test_the_runner_records_it_as_a_failure_with_backoff_and_the_warning_in_the_job(self):
        def empty(source, limit):
            if "blocked" in source["handle_or_url"]:
                raise EmptyFetch("every item was skipped (15 videos): 15 the bot check")
            posts = FetchedPosts([{"url": f"{source['handle_or_url']}/p", "title": "t", "content": "c"}])
            posts.warning = "12 of 15 videos skipped: 12 the bot check"
            return posts

        blocked, partly = _source("https://blocked.test/feed"), _source("https://partly.test/feed")
        h = _Harness([blocked, partly], [FakeKind("fake_rss", behaviour=empty, matches=lambda s: True)])
        report = run(h.run(force=True))
        row = h.state.rows[blocked["id"]]
        self.assertEqual((row.last_outcome, row.consecutive_failures), ("error", 1))
        self.assertEqual(row.last_error, "every item was skipped (15 videos): 15 the bot check")
        self.assertIsNotNone(row.next_retry_at)
        self.assertEqual(report.sources_failed, 1)
        self.assertEqual(h.state.rows[partly["id"]].last_outcome, "healthy")
        events = [data for phase, data in h.progress.events if phase == "source"]
        warned = next(data for data in events if data["source_id"] == partly["id"])
        self.assertEqual(warned["warning"], "12 of 15 videos skipped: 12 the bot check")
        self.assertIn("· warning: 12 of 15 videos skipped", _source_line(warned))

    def test_the_doctor_records_the_reason_and_looks_for_nothing(self):
        error = EmptyFetch("the feed has 2 items but 0 were stored")
        self.assertEqual(failure_signal(error), "empty")
        store, http, _ = look({}, error=error, row=state(1))
        self.assertEqual(http.requests, [])
        self.assertEqual(store.records[0][2], {**EMPTY_FETCH, "note": "the feed has 2 items but 0 were stored"})


# --------------------------------------------------------------------------- 3. transcripts


def track(url: str, ext: str = "json3") -> list:
    return [{"ext": ext, "url": url}]


def json3(*lines: str) -> str:
    return json.dumps({"events": [{"segs": [{"utf8": line}]} for line in lines]})


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.service = YouTubeService("postgresql:///unused")
        self.service.preferred_languages = YouTubeService.DEFAULT_LANGUAGES   # English first, as the server's
        self.payloads = {"https://cap.example/en": json3("Greetings, my glorious friends"),
                         "https://cap.example/ru": json3("Приветствую, друзья"),
                         "https://cap.example/ru-orig": json3("Приветствую, мои друзья"),
                         "https://cap.example/en-manual": json3("Hello, friends (by hand)")}
        self.service._fetch_text = lambda url, timeout=None: self.payloads[url]

    def video(self, **details) -> dict:
        return {"id": "abcdefghijk", "title": "Температура и интеллект", "upload_date": "20260830",
                "automatic_captions": {"en": track("https://cap.example/en"), "en-US": track("https://cap.example/en"),
                                       "ru": track("https://cap.example/ru"),
                                       "ru-orig": track("https://cap.example/ru-orig")}, **details}

    def test_a_russian_video_stores_its_own_captions_not_the_english_translation(self):
        text, source = self.service._extract_transcript(self.video(language="ru"))
        self.assertEqual((text, source), ("Приветствую, мои друзья", "automatic_captions:ru-orig"))

    def test_the_videos_language_is_read_from_its_audio_track_or_its_original_captions(self):
        details = self.video()
        details["_audio_language"] = "ru"
        self.assertEqual(self.service._extract_transcript(details)[1], "automatic_captions:ru-orig")
        self.assertEqual(self.service._extract_transcript(self.video())[1], "automatic_captions:ru-orig")

    def test_with_no_original_track_a_translation_is_never_taken(self):
        details = self.video(language="ru", automatic_captions={"en": track("https://cap.example/en")})
        self.assertEqual(self.service._extract_transcript(details), (None, None))

    def test_hand_made_subtitles_in_a_preferred_language_follow_the_original(self):
        details = self.video(language="ru", subtitles={"en": track("https://cap.example/en-manual")})
        self.assertEqual(self.service._extract_transcript(details)[1], "automatic_captions:ru-orig")
        details = self.video(language="ru", subtitles={"en": track("https://cap.example/en-manual")},
                             automatic_captions={"en": track("https://cap.example/en")})
        self.assertEqual(self.service._extract_transcript(details)[1], "subtitles:en")

    def test_the_posts_language_is_the_stored_tracks(self):
        details = self.video(language="ru", webpage_url="https://www.youtube.com/watch?v=abcdefghijk")
        self.service._get_video_details = lambda video_id: details
        post = self.service._build_video_post("abcdefghijk", "https://www.youtube.com/@a-channel")
        self.assertEqual(post["language_code"], "ru")
        self.assertEqual(post["metadata"]["video_language"], "ru")
        self.assertEqual(build_post_fields(post)["language_code"], "ru")
        english = self.video(automatic_captions={"en": track("https://cap.example/en")})
        self.service._get_video_details = lambda video_id: english
        self.assertEqual(build_post_fields(self.service._build_video_post("abcdefghijk", "@a"))["language_code"], "en")

    def test_every_caption_format_is_stored_as_plain_text(self):
        srv1 = ('<?xml version="1.0" encoding="utf-8" ?><transcript><text start="0" dur="4.2">The world today</text>'
                '<text start="4.2" dur="3">isn&amp;#39;t &lt;i&gt;quiet&lt;/i&gt;</text></transcript>')
        srv3 = '<timedtext format="3"><body><p t="0" d="900"><s>Hello</s><s> there</s></p></body></timedtext>'
        vtt = ("WEBVTT\nKind: captions\nLanguage: ru\n\n00:00:00.000 --> 00:00:02.000\n"
               "<00:00:00.199><c>Привет</c><00:00:00.500><c> мир</c>\n\n00:00:02.000 --> 00:00:03.000\nПривет мир\n")
        self.assertEqual(plain_transcript(srv1), "The world today\nisn't quiet")
        self.assertEqual(plain_transcript(srv3), "Hello there")
        self.assertEqual(plain_transcript(vtt), "Привет мир")
        self.assertEqual(plain_transcript(json3("One", "Two")), "One\nTwo")
        self.assertEqual(plain_transcript("Already plain."), "Already plain.")
        # Whatever the track says it is: an "srv1" answered with XML is read as XML.
        self.assertEqual(self.service._parse_subtitle_payload(srv1, "srv1"), "The world today\nisn't quiet")


# --------------------------------------------------------------------------- 4. Telegram dates


def bridge_page(*posts: tuple[int, str]) -> str:
    items = "".join(f"<item><title>Post {n}</title><link>https://t.me/achannel/{n}</link>"
                    f"<description>Post {n}</description><pubDate>{date}</pubDate></item>" for n, date in posts)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>achannel</title>{items}</channel></rss>'


class TelegramDateTests(unittest.TestCase):
    def test_a_post_dated_by_its_edit_takes_the_message_order_and_keeps_the_bridge_date(self):
        page = bridge_page((520, "Thu, 03 Sep 2026 10:00:00 GMT"), (519, "Wed, 02 Sep 2026 18:00:00 GMT"),
                           (518, "Sun, 20 Sep 2026 09:00:00 GMT"), (517, "Tue, 01 Sep 2026 08:00:00 GMT"))
        http = FakeHttp({"https://tg.example/rss/achannel/1": page})
        posts = run(TelegramRssKind(http).fetch_latest({"handle_or_url": "https://tg.example/rss/achannel"}, 4))
        by_id = {p["external_id"]: p for p in posts}
        self.assertEqual(by_id["518"]["date"], datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc))
        self.assertEqual(by_id["518"]["metadata"]["bridge_date"], "2026-09-20T09:00:00+00:00")
        self.assertEqual(by_id["517"]["date"], datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc))
        self.assertNotIn("bridge_date", by_id["519"]["metadata"])

    def test_the_order_carries_across_pages(self):
        newer = message_order_dates([{"external_id": "10", "date": datetime(2026, 9, 2, tzinfo=timezone.utc)}])
        older = [{"external_id": "9", "date": datetime(2026, 9, 9, tzinfo=timezone.utc), "metadata": {}}]
        message_order_dates(older, newer)
        self.assertEqual(older[0]["date"], datetime(2026, 9, 2, tzinfo=timezone.utc))

    def test_the_mtproto_path_reads_the_message_date_never_the_edit(self):
        sent, edited = datetime(2026, 9, 2, tzinfo=timezone.utc), datetime(2026, 9, 20, tzinfo=timezone.utc)
        message = SimpleNamespace(id=518, grouped_id=None, text="A post", media=None, date=sent, edit_date=edited)
        (post,) = synthesize_posts([message], "achannel", forwards=False)
        self.assertEqual(post["date"], sent)


# --------------------------------------------------------------------------- 5. the feed finder


def finder(responses, url):
    http = FakeHttp(responses)
    return run(find_feeds(http, KindRegistry.default(http, None), url)), http


class FeedFinderTests(unittest.TestCase):
    def test_a_feed_with_items_insight_cannot_read_is_refused(self):
        finding, _ = finder({"https://stray.example/feed": STRAY_ITEMS}, "https://stray.example/feed")
        self.assertEqual((finding.status, finding.feeds, finding.refused), ("none", (), REFUSED))

    def test_a_pasted_rdf_feed_is_a_feed(self):
        finding, _ = finder({f"{JOURNAL}/toc.rss": RDF}, f"{JOURNAL}/toc.rss")
        self.assertEqual((finding.status, finding.feeds[0].title), ("feed", "Journal of Examples"))

    def test_a_search_feed_is_ranked_below_the_table_of_contents_and_said_to_be_one(self):
        head = ('<link rel="alternate" type="application/rss+xml" href="/feed">'
                '<link rel="alternate" type="application/rss+xml" href="/toc/current.rss">')
        page = f"<html><head>{head}</head><body></body></html>"
        finding, _ = finder({f"{JOURNAL}/": page,
                             f"{JOURNAL}/feed": toc_rss("Keyword search for query", f"{JOURNAL}/s1"),
                             f"{JOURNAL}/toc/current.rss": toc_rss("Current issue", f"{JOURNAL}/a1")}, JOURNAL)
        self.assertEqual([f.url for f in finding.feeds], [f"{JOURNAL}/toc/current.rss", f"{JOURNAL}/feed"])
        self.assertEqual(feed_row(finding.feeds[1])["saved_search"], True)
        self.assertNotIn("saved_search", feed_row(finding.feeds[0]))
        self.assertTrue(is_search_feed("Results", "https://index.example/rss?term=sleep+memory"))
        self.assertFalse(is_search_feed("Current issue", "https://pub.example/action/showFeed?jc=abc&type=etoc"))

    def test_a_blocked_page_tries_its_feed_paths_directly(self):
        blocked = HttpError(f"HTTP 403 while fetching {JOURNAL}/home/jex: Forbidden", status=403)
        finding, http = finder({f"{JOURNAL}/home/jex": blocked, f"{JOURNAL}/home/jex/rss": RDF}, f"{JOURNAL}/home/jex")
        self.assertEqual((finding.status, finding.feeds[0].url), ("found", f"{JOURNAL}/home/jex/rss"))
        self.assertEqual(http.requests[:3], [f"{JOURNAL}/home/jex", f"{JOURNAL}/home/jex/feed", f"{JOURNAL}/home/jex/rss"])


# --------------------------------------------------------------------------- the one-off repair


class RepairTests(unittest.TestCase):
    def test_stored_bridge_dates_out_of_message_order_are_found(self):
        day = lambda d: datetime(2026, 9, d, tzinfo=timezone.utc)  # noqa: E731
        rows = [("p520", "520", day(3)), ("p519", "519", day(2)), ("p518", "518", day(20)), ("p517", "517", day(1)),
                ("pnone", None, day(30))]
        self.assertEqual(repair_0135.date_fixes(rows), [("p518", day(20), day(2))])

    def test_stored_translations_and_markup_are_found_and_nothing_else(self):
        ru = {"title": "Температура и интеллект", "content": "Greetings, my glorious friends",
              "metadata": {"transcript_source": "automatic_captions:en-US"}}
        self.assertEqual(repair_0135.needs_transcript(ru), "translation")
        own = {**ru, "metadata": {"transcript_source": "automatic_captions:ru-orig"}}
        self.assertIsNone(repair_0135.needs_transcript(own))
        english = {"title": "Why sleep matters", "content": "Hello", "metadata": {"transcript_source": "automatic_captions:en"}}
        self.assertIsNone(repair_0135.needs_transcript(english))
        markup = {**english, "content": '<?xml version="1.0"?><transcript><text start="0">Hi</text></transcript>'}
        self.assertEqual(repair_0135.needs_transcript(markup), "markup")
        # A WebVTT track stored with its header and inline tags (one on the server's copy).
        vtt = {**english, "content": "Kind: captions\nLanguage: en\nHow <00:00:00.234><c> many</c>\nHow many"}
        self.assertEqual(repair_0135.needs_transcript(vtt), "markup")
        self.assertEqual(plain_transcript(vtt["content"]), "How many")
        # An English title read as Portuguese by the stopword guess is no translation (44 on the server's copy).
        self.assertIsNone(repair_0135.needs_transcript({**english, "title": "A total disaster para a casa"}))


# --------------------------------------------------------------------------- 6. the Telegram bridge


class TelegramBridgeTests(unittest.TestCase):
    def test_the_bridge_is_the_configured_one_the_default_or_none(self):
        self.assertEqual(bridge_origin({}), "https://telegram.local")
        self.assertEqual(bridge_origin({"TELEGRAM_RSS_HOSTS": "tg.example, other.example"}), "https://tg.example")
        self.assertEqual(bridge_origin({"TELEGRAM_RSS_HOSTS": "http://127.0.0.1:9504/"}), "http://127.0.0.1:9504")
        self.assertIsNone(bridge_origin({"TELEGRAM_RSS_HOSTS": " "}))

    def test_the_route_says_which_bridge(self):
        with mock.patch.dict("os.environ", {"TELEGRAM_RSS_HOSTS": ""}):
            self.assertEqual(call(main.app, "GET", "/api/sources/telegram-bridge")[2], {"success": True, "bridge": None})
        with mock.patch.dict("os.environ", {"TELEGRAM_RSS_HOSTS": "tg.example"}):
            self.assertEqual(call(main.app, "GET", "/api/sources/telegram-bridge")[2]["bridge"], "https://tg.example")


if __name__ == "__main__":
    unittest.main()
