import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.adapters.gwern_adapter import GwernAdapter
from insight_core.adapters.lesswrong_adapter import LessWrongAdapter
from insight_core.services.source_fetch_service import SourceFetchService


class SourceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.service = SourceFetchService("postgresql://test:test@localhost/test")

    def test_classify_source_detects_lesswrong_and_gwern(self):
        self.assertEqual(
            self.service.classify_source(
                {"platform": "rss", "handle_or_url": "https://www.lesswrong.com/feed.xml"}
            ),
            "lesswrong_graphql",
        )
        self.assertEqual(
            self.service.classify_source(
                {"platform": "rss", "handle_or_url": "https://gwern.net"}
            ),
            "gwern_site",
        )

    def test_lesswrong_count_available_posts_uses_offset_search(self):
        adapter = LessWrongAdapter(self.service)

        async def fake_post_json(url, payload, user_agent=None, extra_headers=None):
            variables = payload.get("variables") or {}
            offset = int(variables.get("offset") or 0)
            limit = int(variables.get("limit") or 1)
            total_posts = 5
            if offset >= total_posts:
                rows = []
            else:
                rows = [
                    {
                        "_id": f"post-{index}",
                        "title": f"Post {index}",
                        "pageUrl": f"https://www.lesswrong.com/posts/post-{index}",
                        "postedAt": "2026-03-23T10:00:00+00:00",
                        "htmlBody": "<p>Body</p>",
                        "baseScore": 1,
                        "user": {"slug": "author", "displayName": "Author"},
                    }
                    for index in range(offset, min(total_posts, offset + limit))
                ]
            return {"data": {"posts": {"results": rows}}}

        self.service._post_json = fake_post_json  # type: ignore[method-assign]
        count = asyncio.run(adapter._count_available_posts())
        self.assertEqual(count, 5)

    def test_lesswrong_fetch_live_posts_formats_html_body(self):
        adapter = LessWrongAdapter(self.service)

        async def fake_post_json(url, payload, user_agent=None, extra_headers=None):
            return {
                "data": {
                    "posts": {
                        "results": [
                            {
                                "_id": "abc123",
                                "title": "A LessWrong Post",
                                "pageUrl": "https://www.lesswrong.com/posts/abc123/a-lesswrong-post",
                                "postedAt": "2026-03-23T11:00:00+00:00",
                                "htmlBody": '<p>Hello</p><img src="https://example.com/image.png" />',
                                "baseScore": 42,
                                "user": {"slug": "alice", "displayName": "Alice"},
                            }
                        ]
                    }
                }
            }

        self.service._post_json = fake_post_json  # type: ignore[method-assign]
        posts = asyncio.run(adapter.fetch_live_posts({"handle_or_url": "https://www.lesswrong.com/feed.xml"}, 1))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["external_id"], "abc123")
        self.assertEqual(posts[0]["content"], "Hello")
        self.assertEqual(posts[0]["media_urls"], ["https://example.com/image.png"])
        self.assertEqual(posts[0]["metadata"]["author_slug"], "alice")

    def test_gwern_sitemap_filters_to_html_pages(self):
        adapter = GwernAdapter(self.service)
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://gwern.net/style-guide</loc></url>
          <url><loc>https://gwern.net/fiction/alice</loc></url>
          <url><loc>https://gwern.net/doc/psychology/index</loc></url>
          <url><loc>https://gwern.net/doc/psychology/2021-paper.pdf</loc></url>
          <url><loc>https://gwern.net/static/app.js</loc></url>
          <url><loc>https://gwern.net/doc/newest/index</loc></url>
        </urlset>
        """

        async def fake_fetch_text(url, user_agent=None):
            return xml, {}

        self.service._fetch_text = fake_fetch_text  # type: ignore[method-assign]
        urls = asyncio.run(adapter._discover_archive_urls({"handle_or_url": "https://gwern.net"}))

        self.assertEqual(
            urls,
            [
                "https://gwern.net/doc/psychology/index",
                "https://gwern.net/fiction/alice",
                "https://gwern.net/style-guide",
            ],
        )

    def test_gwern_recent_url_discovery_ignores_nav_and_assets(self):
        adapter = GwernAdapter(self.service)
        html = """
        <html>
          <body>
            <a href="/about" class="site link-page">About</a>
            <a href="/style-guide" class="prefetch-not link-page link-modified-recently">Style Guide</a>
            <a href="/fiction/alice" class="prefetch-not link-page link-modified-recently">Alice</a>
            <a href="/doc/paper.pdf" class="link-page link-modified-recently">Paper</a>
            <a href="/static/app.js" class="link-page">Asset</a>
          </body>
        </html>
        """

        async def fake_fetch_text(url, user_agent=None):
            return html, {}

        self.service._fetch_text = fake_fetch_text  # type: ignore[method-assign]
        urls = asyncio.run(adapter._discover_recent_urls({"handle_or_url": "https://gwern.net"}, limit=10))
        self.assertEqual(
            urls,
            [
                "https://gwern.net/style-guide",
                "https://gwern.net/fiction/alice",
            ],
        )


if __name__ == "__main__":
    unittest.main()
