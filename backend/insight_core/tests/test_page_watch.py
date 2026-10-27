"""page_watch (issue 0028): a page without a feed, followed through its links and the sitemap.

Fixtures trimmed from https://www.anthropic.com/news, its robots.txt, sitemap.xml, one article
and one category page (2026-10-27).
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import RateLimit
from insight_core.ingestion.kinds.page_watch import PageWatchKind, infer_prefix, preview
from insight_core.services import registry as services_registry
from insight_core.tests._asgi import call
from insight_core.tests._kind_fakes import FakeHttp

SITE = "https://www.anthropic.com"
LISTING = f"{SITE}/news"
PARAGRAPH = "<p>" + "Distillation attacks harvest a model's outputs to train a copy of it. " * 12 + "</p>"

NEWS_PAGE = f"""<!DOCTYPE html><html><head><title>Newsroom \\ Anthropic</title>
<link rel="canonical" href="{SITE}/news"/></head><body>
<nav><a href="/">Home</a><a href="/claude-opus-5-5">Claude Opus</a><a href="#main-content">Skip</a></nav>
<main><h1>Newsroom</h1>
<a href="/news/announcements">Announcements</a>
<a href="/news/public-benefit-fund"><h3>Public benefit fund</h3></a><a href="/news/announcements">Announcements</a>
<a href="/news/distillation-defenses#top">Distillation defenses</a>
<a href="https://www.anthropic.com/news/s1-sec/">S-1</a>
<a href="/news/public-benefit-fund">Public benefit fund again</a>
<a href="https://example.com/news/elsewhere">Elsewhere</a>
</main></body></html>"""

ROBOTS = f"User-Agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"


def url_entry(path: str, lastmod: str) -> str:
    return f"<url><loc>{SITE}{path}</loc><lastmod>{lastmod}</lastmod></url>"


SITEMAP = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + url_entry("/", "2026-10-21T19:10:47.000Z")
           + url_entry("/careers", "2026-10-20T00:00:00.000Z")
           + url_entry("/news", "2026-10-14T00:00:00.000Z")
           + url_entry("/news/100k-context-windows", "2026-10-14T00:00:00.000Z")
           + url_entry("/news/announcements", "2026-10-14T00:00:00.000Z")
           + url_entry("/news/claude-2", "2026-10-16T00:00:00.000Z")
           + url_entry("/news/distillation-defenses", "2026-10-14T00:00:00.000Z")
           + url_entry("/news/s1-sec", "2026-10-14T00:00:00.000Z")
           + url_entry("/news/public-benefit-fund", "2026-10-14T00:00:00.000Z")
           + "</urlset>")


def article(title: str, published: str | None = None, *, og_type: str = "article", body: str = PARAGRAPH) -> str:
    meta = f'<meta property="article:published_time" content="{published}"/>' if published else ""
    return (f'<!DOCTYPE html><html><head><title>{title} \\ Anthropic</title>'
            f'<meta property="og:title" content="{title}"/><meta property="og:type" content="{og_type}"/>'
            f'<meta property="og:image" content="https://www-cdn.anthropic.com/images/{title[:4]}.jpg"/>{meta}'
            f'</head><body><nav><a href="/news">News</a></nav><article><h1>{title}</h1>{body}</article>'
            '<footer><p>Footer</p></footer></body></html>')


CATEGORY = article("Announcements", og_type="website",
                   body="".join(f'<a href="/news/x{n}"><p>An article teaser number {n} with words.</p></a>' for n in range(40)))
JS_SHELL = '<!DOCTYPE html><html><head><title>Pipecraft</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'


def anthropic(**overrides) -> dict:
    responses = {
        LISTING: NEWS_PAGE,
        f"{SITE}/robots.txt": ROBOTS,
        f"{SITE}/sitemap.xml": SITEMAP,
        f"{SITE}/news/announcements": CATEGORY,
        f"{SITE}/news/public-benefit-fund": article("Public benefit fund", "2026-10-22T00:00:00.000Z"),
        f"{SITE}/news/distillation-defenses": article("Strengthening our defenses against distillation attacks",
                                                      "2026-10-12T00:00:00.000Z"),
        f"{SITE}/news/s1-sec": article("Anthropic files S-1", "2026-10-20T00:00:00.000Z"),
        f"{SITE}/news/claude-2": article("Claude 2", "2023-07-11T00:00:00.000Z"),
        f"{SITE}/news/100k-context-windows": article("100K context windows"),   # no page date
    }
    responses.update(overrides)
    return responses


def source(**settings) -> dict:
    return {"id": "s1", "platform": "rss", "handle_or_url": LISTING, "settings": {"page_watch": settings}}


def run(coro):
    return asyncio.run(coro)


class PrefixTests(unittest.TestCase):
    def test_the_listing_path_is_the_prefix(self):
        self.assertEqual(infer_prefix(f"{SITE}/news", []), "/news/")
        self.assertEqual(infer_prefix(f"{SITE}/blog/", []), "/blog/")

    def test_a_site_root_takes_the_most_common_first_segment_of_its_deep_links(self):
        links = [f"{SITE}/posts/a", f"{SITE}/posts/b", f"{SITE}/about", f"{SITE}/tags/x", "https://x.example/p/q/r"]
        self.assertEqual(infer_prefix(f"{SITE}/", links), "/posts/")
        self.assertEqual(infer_prefix(f"{SITE}/", [f"{SITE}/about"]), "/")


class PageWatchKindTests(unittest.TestCase):
    def kind(self, responses=None, stored=()):
        self.http = FakeHttp(responses or anthropic())
        self.lookups = []

        def stored_urls(urls):
            self.lookups.append(list(urls))
            return set(stored) & set(urls)

        return PageWatchKind(self.http, stored_urls=stored_urls)

    def test_matches_only_on_the_setting_and_the_registry_resolves_it_first(self):
        kind = self.kind()
        self.assertTrue(kind.matches(source()))
        self.assertFalse(kind.matches({"platform": "rss", "handle_or_url": LISTING, "settings": {}}))
        registry = KindRegistry.default(self.http, None)
        self.assertEqual(registry.resolve(source(prefix="/news/")).name, "page_watch")
        self.assertEqual(registry.resolve({"platform": "rss", "handle_or_url": "https://gwern.net",
                                           "settings": {"page_watch": {}}}).name, "page_watch")

    def test_fetch_reads_listing_links_in_page_order_then_the_sitemap_by_lastmod(self):
        kind = self.kind()
        posts = run(kind.fetch_latest(source(prefix="/news/"), 10))
        self.assertEqual([post["url"] for post in posts], [
            f"{SITE}/news/public-benefit-fund", f"{SITE}/news/distillation-defenses", f"{SITE}/news/s1-sec",
            f"{SITE}/news/claude-2", f"{SITE}/news/100k-context-windows",
        ])
        # Robots named the sitemap; other hosts, the listing itself and fragments are left out.
        self.assertEqual(self.http.requests[:3], [LISTING, f"{SITE}/robots.txt", f"{SITE}/sitemap.xml"])
        self.assertNotIn("https://example.com/news/elsewhere", self.http.requests)
        self.assertEqual(self.http.requests.count(f"{SITE}/news/public-benefit-fund"), 1)
        # A pause between two article pages, none before the first.
        self.assertEqual(self.http.sleeper.calls, [kind.PAGE_DELAY_SECONDS] * 5)

    def test_one_article_in_full_with_the_page_date(self):
        posts = run(self.kind().fetch_latest(source(), 3))
        post = next(p for p in posts if p["url"].endswith("distillation-defenses"))
        self.assertEqual(post["title"], "Strengthening our defenses against distillation attacks")
        self.assertEqual(post["date"], datetime(2026, 10, 12, tzinfo=timezone.utc))   # not lastmod 10-14
        self.assertIn("Distillation attacks harvest", post["content"])
        self.assertNotIn("Footer", post["content"])
        self.assertEqual(post["media_urls"], ["https://www-cdn.anthropic.com/images/Stre.jpg"])
        self.assertEqual(post["platform"], "rss")
        self.assertEqual(post["source"], LISTING)

    def test_the_title_loses_the_site_suffix(self):
        site_named = (f'<meta property="og:title" content="Voxtral 3: Speech &amp; Voice | Mistral">'
                      f'<meta property="og:site_name" content="Mistral">'
                      f'<meta property="article:published_time" content="2026-10-22T09:00:00+02:00"><article>{PARAGRAPH}</article>')
        title_tag = f'<title>Claude 2 \\ Anthropic</title><time datetime="2023-07-11">July</time><article>{PARAGRAPH}</article>'
        kept = (f'<meta property="og:title" content="Claude 2 - the next model"><time datetime="2023-07-11">July</time>'
                f'<article>{PARAGRAPH}</article>')
        responses = {**anthropic(), f"{SITE}/news/s1-sec": site_named, f"{SITE}/news/claude-2": title_tag,
                     f"{SITE}/news/100k-context-windows": kept}
        titles = {p["url"].rsplit("/", 1)[1]: p["title"] for p in run(self.kind(responses).fetch_latest(source(), 10))}
        self.assertEqual(titles["s1-sec"], "Voxtral 3: Speech & Voice")
        self.assertEqual(titles["claude-2"], "Claude 2")
        self.assertEqual(titles["100k-context-windows"], "Claude 2 - the next model")

    def test_a_page_without_a_date_of_its_own_takes_the_lastmod(self):
        posts = run(self.kind().fetch_latest(source(), 10))
        undated = next(p for p in posts if p["url"].endswith("100k-context-windows"))
        self.assertEqual(undated["date"], datetime(2026, 10, 14, tzinfo=timezone.utc))

    def test_a_category_page_is_no_post_and_is_not_read_again(self):
        kind = self.kind()
        run(kind.fetch_latest(source(), 10))
        self.assertIn(f"{SITE}/news/announcements", self.http.requests)
        self.http.requests.clear()
        run(kind.fetch_latest(source(), 10))
        self.assertNotIn(f"{SITE}/news/announcements", self.http.requests)

    def test_stored_urls_are_not_read_and_the_limit_counts_posts(self):
        kind = self.kind(stored=[f"{SITE}/news/public-benefit-fund", f"{SITE}/news/s1-sec"])
        posts = run(kind.fetch_latest(source(), 2))
        self.assertEqual([p["url"] for p in posts], [f"{SITE}/news/distillation-defenses", f"{SITE}/news/claude-2"])
        self.assertNotIn(f"{SITE}/news/s1-sec", self.http.requests)
        self.assertIn(f"{SITE}/news/s1-sec", self.lookups[0])

    def test_without_robots_the_sitemap_is_looked_for_at_its_usual_address(self):
        responses = anthropic()
        del responses[f"{SITE}/robots.txt"]
        posts = run(self.kind(responses).fetch_latest(source(), 10))
        self.assertIn(f"{SITE}/news/claude-2", [p["url"] for p in posts])

    def test_a_sitemap_index_is_followed(self):
        index = (f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 f"<sitemap><loc>{SITE}/sitemap-old.xml.gz</loc></sitemap>"
                 f"<sitemap><loc>{SITE}/sitemap-news.xml</loc></sitemap></sitemapindex>")
        responses = anthropic(**{f"{SITE}/sitemap.xml": index, f"{SITE}/sitemap-news.xml": SITEMAP})
        posts = run(self.kind(responses).fetch_latest(source(), 10))
        self.assertIn(f"{SITE}/news/claude-2", [p["url"] for p in posts])
        self.assertNotIn(f"{SITE}/sitemap-old.xml.gz", self.http.requests)

    def test_a_failing_article_page_is_skipped_but_a_limiting_one_stops_the_fetch(self):
        posts = run(self.kind(anthropic(**{f"{SITE}/news/s1-sec": ValueError("HTTP 404")})).fetch_latest(source(), 10))
        self.assertNotIn(f"{SITE}/news/s1-sec", [p["url"] for p in posts])
        limited = anthropic(**{f"{SITE}/news/s1-sec": HttpError("HTTP 429", status=429)})
        with self.assertRaises(HttpError):
            run(self.kind(limited).fetch_latest(source(), 10))

    def test_inspect_reports_the_section(self):
        inspection = run(self.kind().inspect(source()))
        self.assertEqual(inspection.available_posts, 6)
        self.assertEqual(inspection.raw["prefix"], "/news/")
        self.assertEqual(inspection.raw["sitemap_urls"], 6)

    def test_archive_covers_the_section_one_page_each_and_resumes(self):
        kind = self.kind()
        rate = kind.profile.rate_limit()
        pages = run(self._pages(kind, source(), 100, None, rate))
        self.assertEqual(len(pages), 6)
        posts = [post for page in pages for post in page.posts]
        self.assertEqual(len(posts), 5)            # the category page is no post
        self.assertEqual(pages[-1].checkpoint["next_index"], 6)
        self.assertTrue(kind.checkpoint_resumable(pages[2].checkpoint))
        self.assertIsNone(run(kind.start_checkpoint(source(), {"post_count": 5})))

        self.http.requests.clear()
        resumed = run(self._pages(kind, source(), 100, pages[3].checkpoint, rate))
        self.assertEqual([p.posts[0]["url"] for p in resumed], [f"{SITE}/news/claude-2", f"{SITE}/news/100k-context-windows"])
        self.assertEqual(resumed[-1].checkpoint["collected_posts"], 5)

    @staticmethod
    async def _pages(kind, src, target, checkpoint, rate: RateLimit):
        return [page async for page in kind.archive_pages(src, target, checkpoint, rate)]


class PreviewTests(unittest.TestCase):
    def test_preview_counts_the_articles_and_reads_the_first_five(self):
        http = FakeHttp(anthropic())
        result = run(preview(http, "www.anthropic.com/news"))
        self.assertEqual((result["prefix"], result["found"], result["sitemap"]), ("/news/", 6, True))
        self.assertEqual([item["title"] for item in result["items"]], [
            "Public benefit fund", "Strengthening our defenses against distillation attacks", "Anthropic files S-1",
            "Claude 2", "100K context windows",
        ])
        self.assertEqual(result["items"][0], {"url": f"{SITE}/news/public-benefit-fund", "title": "Public benefit fund",
                                              "published_at": "2026-10-22T00:00:00+00:00"})

    def test_a_prefix_override_narrows_the_section(self):
        result = run(preview(FakeHttp(anthropic()), LISTING, "news/claude"))
        self.assertEqual((result["prefix"], result["found"]), ("/news/claude/", 0))

    def test_a_javascript_shell_has_no_readable_articles(self):
        site = "https://www.pipecraft.me"
        shell = JS_SHELL.replace("</body>", '<a href="/posts/one">One</a><a href="/posts/two">Two</a></body>')
        http = FakeHttp({f"{site}/": shell, f"{site}/posts/one": JS_SHELL, f"{site}/posts/two": JS_SHELL})
        result = run(preview(http, f"{site}/"))
        self.assertEqual((result["prefix"], result["found"], result["sitemap"], result["items"]), ("/posts/", 2, False, []))


class PreviewRouteTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttp(anthropic())
        patcher = mock.patch.object(main, "FEED_FINDER_HTTP", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_route_shape(self):
        status, _, body = call(main.app, "POST", "/api/sources/page-watch/preview", json_body={"url": LISTING})
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"success", "prefix", "found", "sitemap", "items"})
        self.assertEqual((body["success"], body["prefix"], body["found"], len(body["items"])), (True, "/news/", 6, 5))

    def test_an_unreadable_page_is_an_error(self):
        status, _, body = call(main.app, "POST", "/api/sources/page-watch/preview",
                               json_body={"url": "https://nothing.example/"})
        self.assertGreaterEqual(status, 400)
        self.assertFalse(body.get("success", False))


class AddPageWatchSourceTests(unittest.TestCase):
    def test_add_passes_settings_page_watch(self):
        added = {}

        def add_with_settings(platform, handle, *, settings=None, enabled=True):
            added.update(platform=platform, handle=handle, settings=settings)
            return {"source_id": "new", "handle": handle}

        fake = SimpleNamespace(sources=SimpleNamespace(add_with_settings=add_with_settings))
        self.addCleanup(services_registry.use, services_registry.use(fake))
        with mock.patch.object(main, "_export_sources_json"):
            status, _, _ = call(main.app, "POST", "/api/sources", json_body={
                "handle_or_url": LISTING, "display_name": "Anthropic News", "page_watch": {"prefix": "/news/"}})
        self.assertEqual(status, 200)
        self.assertEqual(added["settings"], {"display_name": "Anthropic News", "page_watch": {"prefix": "/news/"}})

    def test_the_setting_is_validated(self):
        from insight_core.services.sources_service import SourcesService

        self.assertEqual(SourcesService._valid_settings({"page_watch": {"prefix": "news"}}),
                         {"page_watch": {"prefix": "/news/"}})
        self.assertEqual(SourcesService._valid_settings({"page_watch": {}}), {"page_watch": {}})
        with self.assertRaises(ValueError):
            SourcesService._valid_settings({"page_watch": "yes"})


if __name__ == "__main__":
    unittest.main()
