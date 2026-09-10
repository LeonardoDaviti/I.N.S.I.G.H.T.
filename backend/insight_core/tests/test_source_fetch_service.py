import asyncio
import unittest
import sys
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from datetime import datetime, timedelta, timezone

from insight_core.services import source_fetch_service as sfs
from insight_core.services.source_fetch_service import SourceFetchService


class SourceFetchServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = SourceFetchService("postgresql://test:test@localhost/test")

    def test_classify_special_sources(self):
        self.assertEqual(
            self.service.classify_source({
                "platform": "rss",
                "handle_or_url": "https://telegram.local/rss/denissexy",
            }),
            "telegram_rss",
        )
        self.assertEqual(
            self.service.classify_source({
                "platform": "rss",
                "handle_or_url": "https://nitter.local/karpathy/rss",
            }),
            "nitter_rss",
        )
        self.assertEqual(
            self.service.classify_source({
                "platform": "reddit",
                "handle_or_url": "r/LocalLLaMA",
            }),
            "reddit_subreddit",
        )
        self.assertEqual(
            self.service.classify_source({
                "platform": "youtube",
                "handle_or_url": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
            }),
            "youtube_channel",
        )
        self.assertEqual(
            self.service.classify_source({
                "platform": "rss",
                "handle_or_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCHkYOD-3fZbuGhwsADBd9ZQ",
            }),
            "youtube_channel",
        )

    def test_extract_nitter_tweet_count(self):
        html = """
        <li class="posts">
          <span class="profile-stat-header">Tweets</span>
          <span class="profile-stat-num">10,030</span>
        </li>
        """
        self.assertEqual(self.service._extract_nitter_tweet_count(html), 10030)

    def test_parse_feed_posts_extracts_inline_images(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Example</title>
              <description><![CDATA[<p>Hello</p><img src="http://127.0.0.1:9504/media/test.jpg" />]]></description>
              <pubDate>Wed, 11 Mar 2026 18:01:01 GMT</pubDate>
              <link>https://t.me/example/123</link>
            </item>
          </channel>
        </rss>
        """
        posts = self.service._parse_feed_posts(xml, "https://telegram.local/rss/example")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["media_urls"], ["https://telegram.local/media/test.jpg"])
        self.assertEqual(posts[0]["content"], "Hello")

    def test_fetch_telegram_page_skips_sponsored_items(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>[Sponsored] Buy now</title>
              <description>Ad</description>
              <link>838348a7075f39f185078f7eccc181f4</link>
            </item>
            <item>
              <title>Real post</title>
              <description><![CDATA[<p>Actual content</p><img src="http://127.0.0.1:9504/media/denissexy/1.jpg" />]]></description>
              <pubDate>Wed, 11 Mar 2026 18:18:59 +0000</pubDate>
              <link>https://t.me/denissexy/11277</link>
            </item>
          </channel>
        </rss>
        """

        async def fake_fetch_text(url, user_agent=None):
            return xml, {}

        self.service._fetch_text = fake_fetch_text  # type: ignore[method-assign]
        posts = asyncio.run(self.service._fetch_telegram_page("https://tg.i-c-a.su/rss/denissexy", "denissexy", 1))

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["external_id"], "11277")
        self.assertEqual(posts[0]["url"], "https://t.me/denissexy/11277")
        self.assertEqual(posts[0]["media_urls"], ["https://tg.i-c-a.su/media/denissexy/1.jpg"])

    def test_estimate_seconds_applies_nitter_batch_cooldown(self):
        self.assertEqual(self.service._estimate_seconds("nitter_rss", 10), 100)
        self.assertEqual(self.service._estimate_seconds("nitter_rss", 11), 131)

    def test_resolve_rate_limit_prefers_overrides(self):
        rate_limit = self.service._resolve_rate_limit(
            "telegram_rss",
            {"page_delay_seconds": 7, "batch_size": 8, "batch_cooldown_seconds": 20},
            {"page_delay_seconds": 3, "batch_size": 4},
        )

        self.assertEqual(rate_limit["page_delay_seconds"], 3)
        self.assertEqual(rate_limit["batch_size"], 4)
        self.assertEqual(rate_limit["batch_cooldown_seconds"], 20)

    def test_checkpoint_is_resumable_for_cursor_and_page_modes(self):
        self.assertTrue(self.service._checkpoint_is_resumable({"mode": "telegram_page", "next_page": 5}))
        self.assertTrue(self.service._checkpoint_is_resumable({"mode": "nitter_cursor", "cursor": "abc"}))
        self.assertTrue(self.service._checkpoint_is_resumable({"mode": "reddit_after", "after": "t3_123"}))
        self.assertFalse(self.service._checkpoint_is_resumable({"mode": "generic_rss"}))

    def test_origin_resolution_uses_source_host(self):
        self.assertEqual(
            self.service._telegram_origin("https://tg.i-c-a.su/rss/denissexy?limit=50"),
            "https://tg.i-c-a.su",
        )
        self.assertEqual(
            self.service._nitter_origin("https://nitter.local/karpathy/rss"),
            "https://nitter.local",
        )

    def test_tls_verification_is_skipped_for_local_hosts_only(self):
        self.assertTrue(self.service._should_skip_tls_verify("telegram.local"))
        self.assertTrue(self.service._should_skip_tls_verify("nitter.local"))
        self.assertFalse(self.service._should_skip_tls_verify("tg.i-c-a.su"))

    def test_extract_article_html_prefers_substantial_main_content(self):
        paragraph = "<p>" + ("This is a long-form intelligence paragraph. " * 25) + "</p>"
        html = f"""
        <html>
          <body>
            <header><p>Short intro</p></header>
            <main>
              <h1>Deep analysis</h1>
              {paragraph}
              {paragraph}
            </main>
            <footer><p>Footer links</p></footer>
          </body>
        </html>
        """

        extracted = self.service._extract_article_html(html)

        self.assertIn("<h1>Deep analysis</h1>", extracted)
        self.assertGreater(len(self.service._strip_html(extracted)), 500)

    def test_persist_posts_enriches_with_persisted_ids(self):
        class _FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _FakeConnection:
            def cursor(self):
                return _FakeCursor()

            def commit(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        posts = [
            {"title": "Post One", "url": "https://example.com/1"},
            {"title": "Post Two", "url": "https://example.com/2"},
        ]

        self.service.posts_repo = mock.Mock()
        self.service.posts_repo.upsert_post.side_effect = [
            ("post-1", True),
            ("post-2", False),
        ]
        self.service.memory_service = mock.Mock()
        self.service.memory_service.process_posts.return_value = {
            "posts_processed": 2,
            "mentions_created": 3,
            "entities_linked": 4,
        }
        self.service.event_service = mock.Mock()

        with mock.patch("insight_core.services.source_fetch_service.psycopg.connect", return_value=_FakeConnection()):
            result = self.service._persist_posts("source-1", posts)

        self.service.memory_service.process_posts.assert_called_once()
        self.service.event_service.process_posts.assert_called_once()
        enriched_posts = self.service.memory_service.process_posts.call_args.args[0]
        self.assertEqual([post["id"] for post in enriched_posts], ["post-1", "post-2"])
        self.assertTrue(all(post["_source_id"] == "source-1" for post in enriched_posts))
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["memory_processed"], 2)


if __name__ == "__main__":
    unittest.main()


class ArchiveInspectionCadenceTests(unittest.TestCase):
    """The archive refresh is a SECOND full fetch of every source in the same cycle.

    _inspect_generic_rss_source re-downloads and re-parses the feed the fetch phase just
    read; inspect_channel runs an unbounded yt-dlp dump of the whole channel. It produces
    available_posts (drifts by a few items a day) and first_post_date (the oldest post's
    date, which never changes), so it belongs on its own cadence.
    """

    def setUp(self):
        self.service = SourceFetchService("postgresql://test:test@localhost/test")

    @staticmethod
    def _source(last_inspected_at=None, **archive):
        if last_inspected_at is not None:
            archive["last_inspected_at"] = last_inspected_at
        return {"id": "s1", "platform": "rss", "handle_or_url": "https://a.example.com/rss",
                "settings": {"archive": archive}}

    def _hours_ago(self, hours):
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def test_never_inspected_source_is_due(self):
        self.assertTrue(self.service._archive_inspection_due(self._source()))

    def test_recently_inspected_source_is_not_due(self):
        source = self._source(last_inspected_at=self._hours_ago(24))
        self.assertFalse(self.service._archive_inspection_due(source),
                         "a source measured yesterday must not be re-downloaded today")

    def test_source_past_the_interval_is_due(self):
        source = self._source(last_inspected_at=self._hours_ago(sfs.ARCHIVE_INSPECT_INTERVAL_HOURS + 1))
        self.assertTrue(self.service._archive_inspection_due(source))

    def test_unreadable_timestamp_measures_rather_than_skipping_forever(self):
        self.assertTrue(self.service._archive_inspection_due(self._source(last_inspected_at="whenever")))

    def test_naive_timestamp_does_not_raise(self):
        naive = datetime.now() - timedelta(hours=1)
        self.assertFalse(self.service._archive_inspection_due(self._source(last_inspected_at=naive.isoformat())))

    def test_last_live_fetch_at_does_not_gate_the_measurement(self):
        """It updates every cycle by definition, so it would report 'just inspected' forever."""
        source = self._source(last_live_fetch_at=self._hours_ago(0.1))
        self.assertTrue(self.service._archive_inspection_due(source))

    def test_zero_interval_restores_every_cycle_behaviour(self):
        with mock.patch.object(sfs, "ARCHIVE_INSPECT_INTERVAL_HOURS", 0):
            source = self._source(last_inspected_at=self._hours_ago(0.01))
            self.assertTrue(self.service._archive_inspection_due(source))


class RecordLiveFetchTests(unittest.TestCase):
    def setUp(self):
        self.service = SourceFetchService("postgresql://test:test@localhost/test")
        self.recorded = []

        async def fake_record(source_id, data, mode):
            self.recorded.append((source_id, data, mode))

        self.service._record_archive_metadata = fake_record

    def _source(self, last_inspected_at=None):
        archive = {"last_inspected_at": last_inspected_at} if last_inspected_at else {}
        return {"id": "s1", "platform": "rss", "handle_or_url": "https://a.example.com/rss",
                "settings": {"archive": archive}}

    def test_skips_the_network_when_not_due(self):
        called = []

        async def boom(_source):
            called.append(1)
            raise AssertionError("inspect_source must not run inside the interval")

        self.service.inspect_source = boom
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        asyncio.run(self.service.record_live_fetch("s1", self._source(recent), 7))

        self.assertEqual(called, [])
        source_id, data, mode = self.recorded[0]
        self.assertEqual(mode, "live")
        self.assertEqual(data["posts_fetched"], 7, "the cheap half must still be recorded")
        self.assertNotIn("inspected", data)
        self.assertNotIn("available_posts", data,
                         "absent means _record_archive_metadata keeps the stored value")

    def test_inspects_and_flags_when_due(self):
        async def inspect(_source):
            return {"available_posts": 42, "first_post_date": "2020-01-01"}

        self.service.inspect_source = inspect
        asyncio.run(self.service.record_live_fetch("s1", self._source(), 3))

        _, data, _ = self.recorded[0]
        self.assertEqual(data["available_posts"], 42)
        self.assertTrue(data["inspected"], "only a real measurement may stamp last_inspected_at")

    def test_a_failed_inspection_still_records_the_cheap_half(self):
        """Returning early meant a source whose inspection failed also stopped
        reporting its stored post count, freezing the Archive panel on exactly the
        sources most worth watching."""
        async def boom(_source):
            raise RuntimeError("feed gone")

        self.service.inspect_source = boom
        asyncio.run(self.service.record_live_fetch("s1", self._source(), 5))

        self.assertEqual(len(self.recorded), 1)
        _, data, _ = self.recorded[0]
        self.assertEqual(data["posts_fetched"], 5)
        self.assertNotIn("inspected", data,
                         "a failed inspection must not stamp last_inspected_at, or the "
                         "source would wait a full interval before retrying")
