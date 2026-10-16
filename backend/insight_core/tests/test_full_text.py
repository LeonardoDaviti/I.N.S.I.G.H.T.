"""Full text: a teaser is read from its article page, once (ingestion/full_text.py).

No network: FakeHttp. The kind tests need no database; the upsert and repair tests commit
rows, so they run only against a *_test database (@requires_test_db).
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import FULL_TEXT_CHECKED, FULL_TEXT_FLAG, PostsRepository
from insight_core.ingestion import full_text
from insight_core.ingestion.kinds import KindRegistry, parsing
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.scripts.repair_full_text import STOP_AFTER_FAILURES, Repair
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.utils.content_fingerprints import hash_post_content

FEED_URL = "https://news.example.com/feed"
ARTICLE_TEXT = "Every paragraph of the article, read from its page. " * 40


def _article(text: str = ARTICLE_TEXT) -> str:
    return f"<html><body><nav><p>Menu</p></nav><article><h1>Title</h1><p>{text}</p></article></body></html>"


def _feed(*items: tuple[str, str]) -> str:
    body = "".join(
        f"<item><title>{link}</title><link>{link}</link><description>{text}</description>"
        f"<pubDate>Wed, 11 Mar 2026 18:01:01 GMT</pubDate></item>"
        for link, text in items
    )
    return f'<rss version="2.0"><channel>{body}</channel></rss>'


def _src(**settings) -> dict:
    return {"id": "s1", "platform": "rss", "handle_or_url": FEED_URL, "settings": settings}


PARAGRAPHS = "".join(f"<p>Paragraph {n} of what the author wrote, sentence after sentence.</p>" for n in range(12))

# Modelled on danielmiessler.com (VitePress): preload <link>s, a nav menu in the header,
# the article in plain <div>s (no <article> or <main>), a related list and a footer.
MIESSLER_PAGE = f"""<html><head>
<link rel="preload stylesheet" href="/assets/theme.css" as="style">
<link rel="modulepreload" href="/assets/chunks/framework.js">
</head><body><div id="app">
<header class="VPNav"><div class="VPNavBar"><span class="theme-title">Daniel Miessler</span>
  <div class="content-body"><nav class="VPNavBarMenu menu"><span class="visually-hidden">Main Navigation</span>
    <ul><li><a href="/">home</a></li><li><a href="/blog/">blog</a></li><li><a href="/telos/">telos</a></li></ul></nav>
  <div class="menu"><div class="VPMenu"><p>Newsletter</p></div></div></div></div></header>
<div class="page-title"><h1 class="frontmatter-title">Custom Content for Everyone</h1>
<p>People are starting to think about teams making full games with AI.</p>{PARAGRAPHS}
<ul><li>AIL 1: Daniel dictated this post.</li></ul>
<div class="related-posts"><h2 class="related-heading">Related Reading</h2>
  <ul><li class="related-item"><a href="/blog/x"><span class="related-title">Gaming is Metaverse 1.0</span></a></li></ul></div>
</div>
<footer class="VPFooter"><p>&copy; 1999 &mdash; 2026 Daniel Miessler. All rights reserved.</p></footer>
</div></body></html>"""


def _text(html: str) -> str:
    return parsing.strip_html(parsing.extract_article_html(html))


class ArticleExtractionTests(unittest.TestCase):
    def test_menus_footers_and_related_lists_are_not_the_article(self):
        page = ("<html><body><nav><ul><li>Home</li><li>About</li></ul></nav>"
                f"<div class=\"post\">{PARAGRAPHS}</div>"
                "<aside><ul><li>Popular post</li></ul></aside>"
                "<div id=\"related\"><ul><li>Another post</li></ul></div>"
                "<footer><p>Footer links</p></footer></body></html>")
        self.assertEqual(_text(page), parsing.strip_html(PARAGRAPHS))

    def test_a_nested_menu_is_dropped_whole(self):
        page = (f"<article>{PARAGRAPHS}<div class=\"menu-wrap\"><div><p>Menu item</p></div>"
                "<p>More menu</p></div><p>The last word.</p></article>")
        text = _text(page)
        self.assertNotIn("enu", text)
        self.assertTrue(text.endswith("The last word."))

    def test_a_themes_tag_list_goes_but_wordpress_article_classes_stay(self):
        # The NVIDIA blog's shape: WordPress classes on <article>, a plugin wrapper, a tag list.
        page = ('<article class="post category-ai tag-agents"><div class="has-highlight-and-share">'
                f'{PARAGRAPHS}</div><div class="nvidia-tags"><ul><li>Tags:</li><li>Agentic AI</li></ul></div>'
                '<div class="nvidia-categories"><p>Categories: AI</p></div></article>')
        self.assertEqual(_text(page), parsing.strip_html(PARAGRAPHS))

    def test_the_miessler_page_is_only_its_article(self):
        text = _text(MIESSLER_PAGE)
        self.assertTrue(text.startswith("Custom Content for Everyone People are starting"), text[:80])
        self.assertTrue(text.endswith("AIL 1: Daniel dictated this post."), text[-80:])
        for chrome in ("Main Navigation", "telos", "Newsletter", "Related Reading", "Metaverse", "rights reserved"):
            self.assertNotIn(chrome, text)


class _StubYouTube:
    pass


class GenericRssFullPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_new_teaser_is_read_from_its_page_by_default(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary.")),
                         "https://news.example.com/a": _article()})
        [post] = await GenericRssKind(http).fetch_latest(_src(), 10)
        self.assertIn("Every paragraph of the article", post["content"])
        self.assertTrue(post["metadata"][FULL_TEXT_FLAG])

    async def test_pages_of_one_feed_are_read_apart(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "One."), ("https://news.example.com/b", "Two.")),
                         "https://news.example.com/a": _article(), "https://news.example.com/b": _article()})
        await GenericRssKind(http).fetch_latest(_src(), 10)
        self.assertEqual(http.sleeper.calls, [full_text.PAGE_DELAY_S])

    async def test_a_stored_post_is_not_read_again(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary."))})
        kind = GenericRssKind(http, stored_urls=lambda urls: set(urls))
        [post] = await kind.fetch_latest(_src(), 10)
        self.assertEqual(post["content"], "Short summary.")
        self.assertEqual(http.requests, [FEED_URL])

    async def test_it_can_be_turned_off_for_a_source(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary."))})
        await GenericRssKind(http).fetch_latest(_src(fetch_full_content=False), 10)
        self.assertEqual(http.requests, [FEED_URL])

    async def test_links_that_are_not_articles_and_full_bodies_are_not_read(self):
        long_body = "A whole post in the feed. " * 80
        http = FakeHttp({FEED_URL: _feed(("https://github.com/o/r/commit/1", "Fix."),
                                         ("https://www.reddit.com/r/x/comments/1", "Thread."),
                                         ("https://news.example.com/full", long_body))})
        await GenericRssKind(http).fetch_latest(_src(), 10)
        self.assertEqual(http.requests, [FEED_URL])

    async def test_a_page_with_nothing_longer_or_an_error_keeps_the_summary(self):
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary."),
                                         ("https://news.example.com/b", "Other summary.")),
                         "https://news.example.com/a": _article("Tiny.")})
        posts = await GenericRssKind(http).fetch_latest(_src(), 10)
        self.assertEqual(sorted(p["content"] for p in posts), ["Other summary.", "Short summary."])

    async def test_a_page_that_is_not_the_same_article_keeps_the_feed_body(self):
        body = "A clean feed body that opens the way the author opened it. " * 5
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", body)),
                         "https://news.example.com/a": _article()})
        [post] = await GenericRssKind(http).fetch_latest(_src(), 10)
        self.assertEqual(post["content"], body.strip())
        self.assertNotIn(FULL_TEXT_FLAG, post["metadata"])

    async def test_a_page_that_opens_like_the_feed_body_wins(self):
        body = "Every paragraph of the article, read from its page. " * 4
        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", body)),
                         "https://news.example.com/a": _article()})
        [post] = await GenericRssKind(http).fetch_latest(_src(), 10)
        self.assertTrue(post["metadata"][FULL_TEXT_FLAG])
        self.assertEqual(post["content"], _text(_article()))

    async def test_a_failed_lookup_reads_no_page(self):
        def broken(urls):
            raise RuntimeError("database down")

        http = FakeHttp({FEED_URL: _feed(("https://news.example.com/a", "Short summary."))})
        [post] = await GenericRssKind(http, stored_urls=broken).fetch_latest(_src(), 10)
        self.assertEqual(post["content"], "Short summary.")
        self.assertEqual(http.requests, [FEED_URL])


@requires_test_db
class FullTextDbTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.url = db_url()
        self.repo = PostsRepository(self.url)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            self.substack_id = insert_scratch_source(cur, settings_json='{"substack": true}')
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _upsert(self, post: dict, source_id: str | None = None) -> str:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            post_id, _ = self.repo.upsert_post(cur, {"title": "T", "date": None, **post}, source_id or self.source_id)
            conn.commit()
        return post_id

    def _row(self, post_id: str) -> tuple:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT content, metadata FROM posts WHERE id = %s", (post_id,))
            return cur.fetchone()

    def _repair(self, http: FakeHttp, **kwargs) -> dict:
        registry = KindRegistry.default(http, _StubYouTube(), db_url=self.url)
        clock = lambda: datetime(2026, 10, 12, tzinfo=timezone.utc)  # noqa: E731
        return Repair(self.url, http=http, registry=registry, clock=clock).run(
            source_id=kwargs.pop("source_id", self.source_id), **kwargs)

    def test_the_feed_summary_never_replaces_a_body_read_from_the_page(self):
        url = "https://news.example.com/kept"
        post_id = self._upsert({"url": url, "content": ARTICLE_TEXT, "metadata": {FULL_TEXT_FLAG: True}})
        self._upsert({"url": url, "content": "Short summary.", "metadata": {"feed": "again"}})
        content, metadata = self._row(post_id)
        self.assertEqual(content, ARTICLE_TEXT)
        self.assertTrue(metadata[FULL_TEXT_FLAG])
        self.assertEqual(metadata["feed"], "again")

    def test_a_feed_body_still_updates_a_post_never_read_from_its_page(self):
        url = "https://news.example.com/plain"
        post_id = self._upsert({"url": url, "content": "Old body."})
        self._upsert({"url": url, "content": "New body."})
        self.assertEqual(self._row(post_id)[0], "New body.")

    async def test_repair_reads_a_stored_teaser_once(self):
        url = "https://news.example.com/teaser"
        post_id = self._upsert({"url": url, "content": "Short summary."})
        http = FakeHttp({url: _article()})
        summary = await self._repair(http)
        self.assertEqual((summary["repaired"], summary["failed"]), (1, 0))
        content, metadata = self._row(post_id)
        self.assertIn("Every paragraph of the article", content)
        self.assertTrue(metadata[FULL_TEXT_FLAG])
        self.assertEqual(metadata[FULL_TEXT_CHECKED], "2026-10-12T00:00:00+00:00")

        again = await self._repair(FakeHttp())
        self.assertEqual(again["candidates"], 0)

    async def test_repair_marks_a_post_with_nothing_longer_and_skips_it_next_time(self):
        url = "https://news.example.com/short"
        post_id = self._upsert({"url": url, "content": "A short post."})
        summary = await self._repair(FakeHttp({url: _article("Tiny.")}))
        self.assertEqual(summary["nothing_longer"], 1)
        content, metadata = self._row(post_id)
        self.assertEqual(content, "A short post.")
        self.assertIn(FULL_TEXT_CHECKED, metadata)
        self.assertEqual((await self._repair(FakeHttp()))["candidates"], 0)
        self.assertEqual((await self._repair(FakeHttp(), retry=True, dry_run=True))["to_read"], 1)

    async def test_dry_run_reads_nothing(self):
        self._upsert({"url": "https://news.example.com/x", "content": "Short."})
        self._upsert({"url": "https://github.com/o/r/commit/1", "content": "Fix."})
        http = FakeHttp()
        summary = await self._repair(http, dry_run=True)
        self.assertEqual(http.requests, [])
        self.assertEqual(summary["by_site"], {"news.example.com": 1})
        self.assertEqual(summary["skipped"], {"link is not an article": 1})

    async def test_a_site_that_keeps_failing_is_left_for_the_next_run(self):
        for n in range(STOP_AFTER_FAILURES + 2):
            self._upsert({"url": f"https://blocked.example.com/{n}", "content": "Short."})
        http = FakeHttp({})  # every page is a 404
        summary = await self._repair(http)
        self.assertEqual(summary["failed"], STOP_AFTER_FAILURES)
        self.assertEqual(summary["left_for_next_run"], 2)
        self.assertIn("blocked.example.com", summary["stopped_sites"])
        self.assertEqual(len(http.requests), STOP_AFTER_FAILURES)
        self.assertEqual((await self._repair(FakeHttp(), dry_run=True))["to_read"], STOP_AFTER_FAILURES + 2)

    async def test_a_substack_post_is_read_from_the_api(self):
        url = "https://test.invalid/p/exploding"
        post_id = self._upsert({"url": url, "content": "AI! Sluts! Viscerally terrifying self-knowledge!"},
                               self.substack_id)
        body = "<p>" + ("The whole free post. " * 200) + "</p>"
        http = FakeHttp({"https://test.invalid/api/v1/posts/exploding": json.dumps(
            {"id": 7, "slug": "exploding", "title": "Everything is exploding", "audience": "everyone",
             "wordcount": 800, "body_html": body})})
        summary = await self._repair(http, source_id=self.substack_id)
        self.assertEqual(summary["repaired"], 1)
        content, metadata = self._row(post_id)
        self.assertIn("The whole free post.", content)
        self.assertEqual(metadata["audience"], "everyone")


@requires_test_db
class EntityRepairTests(unittest.IsolatedAsyncioTestCase):
    """repair_full_text --entities: the HTML codes in stored plain text, decoded with no network."""

    def setUp(self):
        self.url = db_url()
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            conn.commit()
        repo = PostsRepository(self.url)
        self.ids = []
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            for n, content in enumerate(["That&#39;s it.", "the world&amp;#39;s first", "Plain & simple."]):
                post_id, _ = repo.upsert_post(cur, {"title": "T", "date": None, "content": content,
                                                    "url": f"https://news.example.com/e{n}"}, self.source_id)
                self.ids.append(post_id)
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _contents(self) -> list:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT content FROM posts WHERE id = ANY(%s::uuid[]) ORDER BY url", (self.ids,))
            return [row[0] for row in cur.fetchall()]

    def _repair(self, http: FakeHttp, **kwargs) -> dict:
        registry = KindRegistry.default(http, _StubYouTube(), db_url=self.url)
        return Repair(self.url, http=http, registry=registry).run(entities=True, source_id=self.source_id, **kwargs)

    async def test_codes_are_decoded_without_reading_any_page(self):
        http = FakeHttp()
        summary = await self._repair(http)
        self.assertEqual(summary, {"with_codes": 2, "decoded": 2})
        self.assertEqual(self._contents(), ["That's it.", "the world's first", "Plain & simple."])
        self.assertEqual(http.requests, [])

    async def test_a_decoded_body_gets_the_hash_a_refetch_would_give(self):
        await self._repair(FakeHttp())
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT content, content_hash FROM posts WHERE id = ANY(%s::uuid[])", (self.ids,))
            for content, content_hash in cur.fetchall():
                self.assertEqual(content_hash, hash_post_content("T", content, None), content)

    async def test_a_dry_run_counts_and_writes_nothing(self):
        summary = await self._repair(FakeHttp(), dry_run=True)
        self.assertEqual(summary, {"with_codes": 2, "to_decode": 2})
        self.assertEqual(self._contents(), ["That&#39;s it.", "the world&amp;#39;s first", "Plain & simple."])
