import asyncio
import unittest
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

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


if __name__ == "__main__":
    unittest.main()
