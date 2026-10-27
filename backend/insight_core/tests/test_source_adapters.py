import asyncio
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.adapters.dario_adapter import DarioAmodeiAdapter
from insight_core.adapters.deeplearning_batch_adapter import DeepLearningBatchAdapter
from insight_core.adapters.gwern_adapter import GwernAdapter
from insight_core.adapters.lesswrong_adapter import LessWrongAdapter
from insight_core.adapters.philschmid_adapter import PhilSchmidCloudAttentionAdapter
from insight_core.adapters.pipecraft_adapter import PipecraftAdapter
from insight_core.adapters.zerotomastery_adapter import ZeroToMasteryMonthlyAdapter
from insight_core.ingestion.kinds import KindRegistry
from insight_core.tests._kind_fakes import FakeHttp

# Trimmed from https://www.pipecraft.me/api/posts and /api/posts/<section>/<slug> (2026-10-27).
PIPECRAFT_INDEX = {
    "posts": [
        {"slug": "mobile-engineerind-teams", "title": "The foundational elements of scalability in mobile engineering teams",
         "date": "2024-04-26", "spoiler": "Scaling mobile teams is not funny though", "section": "posts",
         "readingTime": 7, "youtubeId": "SxdOUGdseq4"},
    ],
    "essays": [
        {"slug": "the-part-that-cant-be-cloned", "title": "The part of Software which can't be cloned",
         "date": "2026-10-11", "spoiler": "If software becomes increasingly easy to copy...", "section": "essays",
         "readingTime": 5},
        {"slug": "cost-of-thinking", "title": "Cost of Thinking", "date": "2025-11-16",
         "spoiler": "Why most programmers avoid thinking and how this shapes software culture.",
         "section": "essays", "readingTime": 3},
    ],
    "projects": [
        {"slug": "talkify", "title": "Talkify", "date": "2026-08-18", "spoiler": "Voice dictation for macOS",
         "section": "projects", "readingTime": 1},
    ],
    "talks": [
        {"slug": "local-first-mobile", "title": "Local First Mobile", "date": "2025-12-13",
         "spoiler": "Exploring local-first architecture", "section": "talks", "readingTime": 1,
         "youtubeId": "mSNS7CgMMKw"},
    ],
}
PIPECRAFT_IMAGE = "https://miro.medium.com/v2/resize:fit:1400/format:webp/1*3KUxMR1t.jpeg"


def _pipecraft_http():
    responses = {"https://www.pipecraft.me/api/posts": json.dumps(PIPECRAFT_INDEX)}
    for section in ("posts", "essays"):
        for entry in PIPECRAFT_INDEX[section]:
            body = f'<p>{entry["title"]}: the whole text.</p><img src="{PIPECRAFT_IMAGE}" alt="captionless image">'
            url = f"https://www.pipecraft.me/api/posts/{section}/{entry['slug']}"
            responses[url] = json.dumps({**entry, "content": body})
    return FakeHttp(responses)


class SourceAdapterTests(unittest.TestCase):
    """The site adapters are SourceKinds (B3): they take KindHttp, here a FakeHttp."""

    def setUp(self):
        self.http = FakeHttp()
        self.kinds = KindRegistry.default(self.http, object())

    def classify(self, source):
        return self.kinds.resolve(source).name

    def test_classify_source_detects_custom_adapters(self):
        self.assertEqual(
            self.classify(
                {"platform": "rss", "handle_or_url": "https://www.lesswrong.com/feed.xml"}
            ),
            "lesswrong_graphql",
        )
        self.assertEqual(
            self.classify(
                {"platform": "rss", "handle_or_url": "https://gwern.net"}
            ),
            "gwern_site",
        )
        self.assertEqual(
            self.classify(
                {"platform": "rss", "handle_or_url": "https://darioamodei.com"}
            ),
            "dario_site",
        )
        self.assertEqual(
            self.classify(
                {"platform": "rss", "handle_or_url": "https://www.deeplearning.ai/the-batch/"}
            ),
            "deeplearning_batch_site",
        )
        self.assertEqual(
            self.classify(
                {"platform": "rss", "handle_or_url": "https://www.philschmid.de/cloud-attention"}
            ),
            "philschmid_cloud_attention",
        )
        self.assertEqual(
            self.classify(
                {"platform": "rss", "handle_or_url": "https://zerotomastery.io/newsletters/machine-learning-monthly/1/"}
            ),
            "zerotomastery_ml_monthly",
        )

    def test_lesswrong_count_available_posts_uses_offset_search(self):
        adapter = LessWrongAdapter(self.http)

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

        self.http.post_json = fake_post_json  # type: ignore[method-assign]
        count = asyncio.run(adapter._count_available_posts())
        self.assertEqual(count, 5)

    def test_lesswrong_fetch_live_posts_formats_html_body(self):
        adapter = LessWrongAdapter(self.http)

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

        self.http.post_json = fake_post_json  # type: ignore[method-assign]
        posts = asyncio.run(adapter.fetch_latest({"handle_or_url": "https://www.lesswrong.com/feed.xml"}, 1))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["external_id"], "abc123")
        self.assertEqual(posts[0]["content"], "Hello")
        self.assertEqual(posts[0]["media_urls"], ["https://example.com/image.png"])
        self.assertEqual(posts[0]["metadata"]["author_slug"], "alice")

    def test_gwern_sitemap_filters_to_html_pages(self):
        adapter = GwernAdapter(self.http)
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

        self.http.get_text = fake_fetch_text  # type: ignore[method-assign]
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
        adapter = GwernAdapter(self.http)
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

        self.http.get_text = fake_fetch_text  # type: ignore[method-assign]
        urls = asyncio.run(adapter._discover_recent_urls({"handle_or_url": "https://gwern.net"}, limit=10))
        self.assertEqual(
            urls,
            [
                "https://gwern.net/style-guide",
                "https://gwern.net/fiction/alice",
            ],
        )

    def test_dario_discovers_homepage_entries_and_fetches_post(self):
        adapter = DarioAmodeiAdapter(self.http)
        homepage = """
        <a href="/essay/machines-of-loving-grace">Essay</a>
        <a href="/post/the-urgency-of-interpretability">Post</a>
        <a href="/post/the-urgency-of-interpretability">Post</a>
        """
        detail = """
        <html>
          <head><meta property="og:image" content="https://example.com/dario.jpg" /></head>
          <body>
            <h1 class="post-title">The Urgency of Interpretability</h1>
            <div class="post-date">April 2025</div>
            <div data-toc-contents="" class="rich-text w-richtext"><p>Interpretability matters a lot for frontier AI systems and institutional steering.</p></div>
          </body>
        </html>
        """

        async def fake_fetch_text(url, user_agent=None):
            if url == "https://darioamodei.com":
                return homepage, {}
            return detail, {}

        self.http.get_text = fake_fetch_text  # type: ignore[method-assign]
        entries = asyncio.run(adapter._discover_entries({"handle_or_url": "https://darioamodei.com"}))
        self.assertEqual(
            entries,
            [
                {"url": "https://darioamodei.com/essay/machines-of-loving-grace"},
                {"url": "https://darioamodei.com/post/the-urgency-of-interpretability"},
            ],
        )
        post = asyncio.run(adapter._fetch_entry_post({"handle_or_url": "https://darioamodei.com"}, entries[1]))
        self.assertEqual(post["title"], "The Urgency of Interpretability")
        self.assertEqual(post["media_urls"], ["https://example.com/dario.jpg"])
        self.assertEqual(post["categories"], ["post"])

    def test_batch_adapter_discovers_issue_urls_from_sitemap(self):
        adapter = DeepLearningBatchAdapter(self.http)
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://charonhub.deeplearning.ai/issue-345/</loc><lastmod>2026-03-20T15:36:15.000Z</lastmod></url>
          <url><loc>https://charonhub.deeplearning.ai/deepseek-r1-an-affordable-rival-to-openais-o1/</loc><lastmod>2026-01-22T00:00:00.000Z</lastmod></url>
          <url><loc>https://charonhub.deeplearning.ai/issue-344/</loc><lastmod>2026-03-14T23:58:51.000Z</lastmod></url>
        </urlset>
        """

        async def fake_fetch_text(url, user_agent=None):
            return xml, {}

        self.http.get_text = fake_fetch_text  # type: ignore[method-assign]
        entries = asyncio.run(adapter._discover_entries())
        self.assertEqual([entry["issue_number"] for entry in entries], [345, 344])
        self.assertEqual(entries[0]["public_url"], "https://www.deeplearning.ai/the-batch/issue-345/")

    def test_batch_adapter_extracts_post_from_next_data(self):
        adapter = DeepLearningBatchAdapter(self.http)
        next_payload = {
            "props": {
                "pageProps": {
                    "post": {
                        "title": "Issue 286",
                        "html": "<p>Full newsletter content.</p>",
                        "published_at": "2025-01-29T14:48:00.000-08:00",
                        "feature_image": "https://example.com/batch.jpg",
                        "tags": [{"name": "The Batch"}],
                        "authors": [{"name": "Analytics DeepLearning.AI"}],
                        "primary_author": {"name": "Analytics DeepLearning.AI"},
                        "slug": "issue-286",
                    }
                }
            }
        }
        html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_payload)}</script>'

        async def fake_fetch_text(url, user_agent=None):
            return html, {}

        self.http.get_text = fake_fetch_text  # type: ignore[method-assign]
        post = asyncio.run(
            adapter._fetch_issue_post(
                {"handle_or_url": "https://www.deeplearning.ai/the-batch/"},
                {"public_url": "https://www.deeplearning.ai/the-batch/issue-286/", "issue_number": 286, "published_at": None},
            )
        )
        self.assertEqual(post["external_id"], "286")
        self.assertEqual(post["media_urls"], ["https://example.com/batch.jpg"])
        self.assertEqual(post["categories"], ["The Batch"])

    def test_philschmid_extracts_issue_urls_and_page_count(self):
        adapter = PhilSchmidCloudAttentionAdapter(self.http)
        html = """
        <a href="/cloud-attention/issue-30">Issue 30</a>
        <a href="/cloud-attention/issue-29">Issue 29</a>
        <a href="/cloud-attention?page=2">2</a>
        <a href="/cloud-attention?page=4">4</a>
        """
        self.assertEqual(adapter._extract_max_page(html), 4)
        async def fake_fetch_text(url, user_agent=None):
            return html, {}
        self.http.get_text = fake_fetch_text  # type: ignore[method-assign]
        entries = asyncio.run(adapter._discover_entries({"handle_or_url": "https://www.philschmid.de/cloud-attention"}))
        self.assertEqual(entries[0]["url"], "https://www.philschmid.de/cloud-attention/issue-30")

    def test_zerotomastery_extracts_archive_entries_from_page_data(self):
        adapter = ZeroToMasteryMonthlyAdapter(self.http)
        payload = {
            "result": {
                "data": {
                    "allContentfulBlogPost": {
                        "edges": [
                            {
                                "node": {
                                    "blogTitle": "[February 2026] AI & Machine Learning Monthly Newsletter",
                                    "seoPageTitle": "[February 2026] AI & Machine Learning Monthly Newsletter",
                                    "excerpt": "Monthly ML newsletter",
                                    "publishDate": "March 1st, 2026",
                                    "slug": "ai-and-machine-learning-monthly-newsletter-february-2026",
                                    "tags": [{"label": "A.I. & ML Monthly"}],
                                    "author": {"authorName": "Daniel Bourke", "authorSlug": "daniel-bourke"},
                                    "heroImage": {
                                        "gatsbyImageData": {
                                            "images": {
                                                "sources": [
                                                    {"srcSet": "https://images.example.com/hero.webp 100w, https://images.example.com/hero2.webp 200w"}
                                                ]
                                            }
                                        }
                                    },
                                }
                            }
                        ]
                    }
                }
            }
        }
        entries = adapter._extract_archive_entries(
            {"handle_or_url": "https://zerotomastery.io/newsletters/machine-learning-monthly/1/"},
            payload,
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]["url"],
            "https://zerotomastery.io/blog/ai-and-machine-learning-monthly-newsletter-february-2026/",
        )
        self.assertEqual(entries[0]["hero_image"], "https://images.example.com/hero.webp")
        self.assertEqual(entries[0]["categories"], ["A.I. & ML Monthly"])


class PipecraftAdapterTests(unittest.IsolatedAsyncioTestCase):
    """pipecraft.me is a client-rendered site: its posts come from its own JSON API."""

    SOURCE = {"platform": "rss", "handle_or_url": "https://www.pipecraft.me/"}

    def test_any_pipecraft_url_is_the_blog(self):
        kinds = KindRegistry.default(FakeHttp(), object())
        for url in ("https://www.pipecraft.me/", "https://pipecraft.me", "https://www.pipecraft.me/essays/cost-of-thinking"):
            with self.subTest(url=url):
                self.assertEqual(kinds.resolve({"platform": "rss", "handle_or_url": url}).name, "pipecraft_site")

    async def test_fetch_latest_reads_posts_and_essays_newest_first_in_full(self):
        http = _pipecraft_http()
        posts = await PipecraftAdapter(http).fetch_latest(self.SOURCE, 2)
        self.assertEqual([p["url"] for p in posts], [
            "https://www.pipecraft.me/essays/the-part-that-cant-be-cloned",
            "https://www.pipecraft.me/essays/cost-of-thinking",
        ])
        post = posts[1]
        self.assertEqual(post["title"], "Cost of Thinking")
        self.assertEqual(post["date"], datetime(2025, 11, 16, tzinfo=timezone.utc))
        self.assertTrue(post["content_html"].startswith("<p>Cost of Thinking: the whole text.</p>"))
        self.assertEqual(post["content"], "Cost of Thinking: the whole text.")
        self.assertEqual(post["media_urls"], [PIPECRAFT_IMAGE])
        self.assertEqual(post["categories"], ["essays"])
        self.assertEqual(post["external_id"], "essays/cost-of-thinking")
        self.assertNotIn("https://www.pipecraft.me/api/posts/posts/mobile-engineerind-teams", http.requests,
                         "only the posts asked for are read")

    async def test_projects_and_talks_are_not_posts(self):
        posts = await PipecraftAdapter(_pipecraft_http()).fetch_latest(self.SOURCE, 10)
        self.assertEqual([p["categories"] for p in posts], [["essays"], ["essays"], ["posts"]])

    async def test_inspect_counts_the_index_without_reading_a_post(self):
        http = _pipecraft_http()
        inspection = await PipecraftAdapter(http).inspect(self.SOURCE)
        self.assertEqual(inspection.available_posts, 3)
        self.assertEqual(inspection.first_post_date, "2024-04-26T00:00:00+00:00")
        self.assertEqual(http.requests, ["https://www.pipecraft.me/api/posts"])

    async def test_archive_pages_resume_through_the_index(self):
        adapter = PipecraftAdapter(_pipecraft_http())
        pages = [page async for page in adapter.archive_pages(self.SOURCE, 3, None, adapter.profile.rate_limit())]
        self.assertEqual(sum(len(p.posts) for p in pages), 3)
        self.assertEqual(pages[-1].checkpoint["next_index"], 3)
        self.assertTrue(adapter.checkpoint_resumable(pages[-1].checkpoint))


if __name__ == "__main__":
    unittest.main()
