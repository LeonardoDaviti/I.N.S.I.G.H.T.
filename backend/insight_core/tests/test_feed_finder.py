"""The feed finder (issue 0026): any page address to its feeds. No network: FakeHttp."""
from __future__ import annotations

import asyncio
import io
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
from insight_core.ingestion import feed_finder
from insight_core.ingestion.feed_finder import Feed, FeedFinding, find_feeds
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.services import registry as services_registry
from insight_core.tests._asgi import call
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests.test_page_watch import article


def rss(title: str, items: int = 1, padding: str = "") -> str:
    entries = "".join(f"<item><title>Post {n}</title><link>https://x.example/{n}</link></item>" for n in range(items))
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{title}</title>'
            f"<description>{padding}</description>{entries}</channel></rss>")


def atom(title: str) -> str:
    return (f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>{title}</title>'
            "<entry><title>One</title></entry></feed>")


def page(head: str = "", body: str = "") -> str:
    return f"<!DOCTYPE html><html><head><title>A page</title>{head}</head><body>{body}</body></html>"


def find(responses, url: str, **fake) -> tuple[FeedFinding, FakeHttp]:
    http = FakeHttp(responses, **fake)
    return asyncio.run(find_feeds(http, KindRegistry.default(http, None), url)), http


def found(*feeds: tuple[str, str]) -> FeedFinding:
    return FeedFinding("found", tuple(Feed(url, title) for url, title in feeds))


async def hang(_url: str) -> str:
    await asyncio.sleep(3600)
    return ""


class FeedFinderTests(unittest.TestCase):
    def test_an_address_that_is_a_feed_is_the_feed_with_its_title(self):
        finding, http = find({"https://x.example/feed.xml": rss("X Weekly")}, "https://x.example/feed.xml")
        self.assertEqual(finding, FeedFinding("feed", (Feed("https://x.example/feed.xml", "X Weekly"),)))
        self.assertEqual(http.requests, ["https://x.example/feed.xml"])

    def test_https_is_added_when_the_address_has_no_scheme(self):
        finding, _ = find({"https://x.example/atom.xml": atom("X")}, "  x.example/atom.xml ")
        self.assertEqual(finding.status, "feed")
        self.assertEqual(finding.feeds[0].url, "https://x.example/atom.xml")

    def test_an_empty_address_is_refused(self):
        with self.assertRaises(ValueError):
            find({}, "   ")

    def test_the_pages_alternate_links_in_page_order_skipping_json_feed(self):
        head = ('<link rel="alternate" type="application/feed+json" href="/feed.json">'
                '<link rel="alternate" type="application/rss+xml" title="AI - Ars" href="/ai/feed/">'
                '<link rel="alternate" type="application/atom+xml" title="Ars" href="https://x.example/feed/">')
        finding, http = find({
            "https://x.example/ai/post": page(head),
            "https://x.example/ai/feed/": rss("AI - Ars"),
            "https://x.example/feed/": atom("Ars"),
        }, "https://x.example/ai/post")
        self.assertEqual(finding, found(("https://x.example/ai/feed/", "AI - Ars"), ("https://x.example/feed/", "Ars")))
        self.assertNotIn("https://x.example/feed.json", http.requests)
        self.assertEqual(len(http.requests), 3, "the page and its two feeds, nothing more")

    def test_a_visible_rss_link_is_found_relative_to_the_redirected_page(self):
        # borretti.me: no <link rel="alternate">, only <a href="/feed.xml">RSS</a>.
        finding, _ = find({
            "https://borretti.me/article/x": page(body='<a href="/about">About</a><a href="feed.xml">RSS</a>'),
            "https://www.borretti.me/article/feed.xml": rss("Fernando Borretti"),
        }, "https://borretti.me/article/x", redirects={"https://borretti.me/article/x": "https://www.borretti.me/article/x"})
        self.assertEqual(finding, found(("https://www.borretti.me/article/feed.xml", "Fernando Borretti")))

    def test_feed_looking_links_by_path_ending_or_text(self):
        body = ('<a href="/posts/rss/">x</a><a href="/index.xml">y</a><a href="/subscribe">Atom</a>'
                '<a href="/feedback">Feedback</a><a href="/blog/a-post">A post</a>')
        finding, http = find({
            "https://x.example/": page(body=body),
            "https://x.example/posts/rss/": rss("One"),
            "https://x.example/index.xml": rss("Two"),
            "https://x.example/subscribe": atom("Three"),
        }, "https://x.example/")
        self.assertEqual([feed.title for feed in finding.feeds], ["One", "Two", "Three"])
        self.assertNotIn("https://x.example/feedback", http.requests)
        self.assertNotIn("https://x.example/blog/a-post", http.requests)

    def test_a_comment_feed_is_dropped(self):
        head = ('<link rel="alternate" type="application/rss+xml" title="Comments Feed" href="/comments/feed/">'
                '<link rel="alternate" type="application/rss+xml" title="Blog" href="/feed/">')
        finding, http = find({
            "https://x.example/p": page(head, '<a href="/p/comment-feed.xml">RSS</a>'),
            "https://x.example/feed/": rss("Blog"),
        }, "https://x.example/p")
        self.assertEqual(finding, found(("https://x.example/feed/", "Blog")))
        self.assertEqual(http.requests, ["https://x.example/p", "https://x.example/feed/"])

    def test_base_href_resolves_relative_links(self):
        head = '<base href="https://cdn.example/site/"><link rel="alternate" type="application/rss+xml" href="rss.xml">'
        finding, _ = find({"https://x.example/a": page(head), "https://cdn.example/site/rss.xml": rss("Site")},
                          "https://x.example/a")
        self.assertEqual(finding, found(("https://cdn.example/site/rss.xml", "Site")))

    def test_a_malformed_link_is_skipped(self):
        head = ('<link rel="alternate" type="application/rss+xml" href="http://[x/">'
                '<link rel="alternate" type="application/rss+xml" href="/feed">')
        finding, _ = find({"https://x.example/": page(head, '<a href="http://[y/rss">RSS</a>'),
                           "https://x.example/feed": rss("Site")}, "https://x.example/")
        self.assertEqual(finding, found(("https://x.example/feed", "Site")))
        finding, _ = find({"https://x.example/a": page('<base href="http://[x/">'),
                           "https://x.example/feed": rss("Site")}, "https://x.example/a")
        self.assertEqual(finding, found(("https://x.example/feed", "Site")))

    def test_the_same_feed_under_two_addresses_is_kept_once(self):
        head = ('<link rel="alternate" type="application/rss+xml" href="/rss">'
                '<link rel="alternate" type="application/rss+xml" href="/feed.xml">')
        finding, _ = find({"https://x.example/": page(head), "https://x.example/rss": rss("Site"),
                           "https://x.example/feed.xml": rss("Site")},
                          "https://x.example/", redirects={"https://x.example/rss": "https://x.example/feed.xml"})
        self.assertEqual(finding, found(("https://x.example/rss", "Site")))

    def test_the_section_and_home_pages_when_the_page_has_no_feed(self):
        # Paul Graham's feed is only linked from his home page (and lives on another site).
        finding, http = find({
            "https://pg.example/essays/hackers.html": page(body="<p>An essay</p>"),
            "https://pg.example/essays/": page(),
            "https://pg.example/": page(body='<a href="http://aaron.example/feeds/pgessays.rss">RSS</a>'),
            "http://aaron.example/feeds/pgessays.rss": rss("Paul Graham: Essays"),
        }, "https://pg.example/essays/hackers.html")
        self.assertEqual(finding, found(("http://aaron.example/feeds/pgessays.rss", "Paul Graham: Essays")))
        self.assertEqual(http.requests[:3], ["https://pg.example/essays/hackers.html", "https://pg.example/essays/",
                                             "https://pg.example/"])

    def test_a_company_homepage_leads_to_its_own_blog_on_a_subdomain(self):
        # www.cloudflare.com has no feed; it links blog.cloudflare.com, whose feed is /rss/ (2026-10-28).
        finding, http = find({
            "https://www.cloud.example/": page(body='<a href="https://blog.cloud.example/">Blog</a>'
                                                    '<a href="https://blog.other.example/">Partner blog</a>'),
            "https://blog.cloud.example/": page(head='<link rel="alternate" type="application/rss+xml" href="/rss/">'),
            "https://blog.cloud.example/rss/": rss("Cloud Blog"),
            "https://blog.other.example/": page(head='<link rel="alternate" type="application/rss+xml" href="/rss/">'),
            "https://blog.other.example/rss/": rss("Someone else"),
        }, "https://www.cloud.example/")
        self.assertEqual(finding, found(("https://blog.cloud.example/rss/", "Cloud Blog")))
        self.assertNotIn("https://blog.other.example/", http.requests)

    def test_common_paths_are_tried_under_the_blog_too(self):
        # stripe.com links "Blog" -> /blog, which advertises no feed; the feed is /blog/feed.rss (2026-10-28).
        finding, _ = find({
            "https://pay.example/": page(body='<a href="/blog">Blog</a>'),
            "https://pay.example/blog": page(body="<p>Posts</p>"),
            "https://pay.example/blog/feed.rss": rss("Pay blog"),
        }, "https://pay.example/")
        self.assertEqual(finding, found(("https://pay.example/blog/feed.rss", "Pay blog")))

    def test_a_link_named_newsroom_on_the_same_site_counts_too(self):
        finding, _ = find({
            "https://corp.example/": page(body='<a href="/company/newsroom">Newsroom</a>'),
            "https://corp.example/company/newsroom": page(body='<a href="/company/newsroom/feed.xml">RSS</a>'),
            "https://corp.example/company/newsroom/feed.xml": rss("Corp news"),
        }, "https://corp.example/")
        self.assertEqual(finding, found(("https://corp.example/company/newsroom/feed.xml", "Corp news")))

    def test_common_paths_last_and_only_the_first_valid_in_their_order(self):
        finding, http = find({
            "https://x.example/": page(),
            "https://x.example/feed": page(),                 # an HTML page, not a feed
            "https://x.example/rss.xml": rss("Second"),
            "https://x.example/atom.xml": atom("Third"),
        }, "https://x.example/")
        self.assertEqual(finding, found(("https://x.example/rss.xml", "Second")))
        self.assertEqual(http.requests[0], "https://x.example/")
        self.assertEqual(http.requests[1:5], [f"https://x.example{path}" for path in feed_finder.COMMON_PATHS[:4]])

    def test_the_first_common_path_returns_without_waiting_for_the_later_ones(self):
        started = time.monotonic()
        finding, _ = find({"https://x.example/": page(), "https://x.example/feed": rss("Site"),
                           "https://x.example/rss": hang}, "https://x.example/")
        self.assertEqual(finding, found(("https://x.example/feed", "Site")))
        self.assertLess(time.monotonic() - started, feed_finder.PROOF_GRACE_S / 2)

    def test_a_huge_feed_is_proved_from_its_first_bytes(self):
        huge = rss("Huge", items=20_000)          # several megabytes
        self.assertGreater(len(huge), 1_000_000)
        finding, http = find({"https://x.example/": page('<link rel="alternate" type="application/rss+xml" href="/big.xml">'),
                              "https://x.example/big.xml": huge}, "https://x.example/")
        self.assertEqual(finding, found(("https://x.example/big.xml", "Huge")))
        self.assertLessEqual(http.byte_caps["https://x.example/big.xml"], 64 * 1024)

    def test_a_feed_without_items_or_with_another_root_is_not_a_feed(self):
        sitemap = '<?xml version="1.0"?><urlset><url><loc>https://x.example/</loc></url></urlset>'
        finding, _ = find({"https://x.example/": page('<link rel="alternate" type="application/rss+xml" href="/a">'
                                                      '<link rel="alternate" type="application/rss+xml" href="/b">'),
                           "https://x.example/a": sitemap, "https://x.example/b": rss("Empty", items=0)},
                          "https://x.example/")
        self.assertEqual(finding.status, "none")

    def test_a_kind_or_adapter_that_reads_the_site_is_left_alone(self):
        for url in ("https://www.reddit.com/r/LocalLLaMA/", "https://simon.substack.com", "https://gwern.net/",
                    "https://www.pipecraft.me/", "https://nitter.local/karpathy/rss"):
            with self.subTest(url=url):
                finding, http = find({}, url)
                self.assertEqual(finding, FeedFinding("direct"))
                self.assertEqual(http.requests, [])

    def test_medium_and_github_rules_need_no_page(self):
        cases = {
            "https://medium.com/@karpathy/a-recipe-1": "https://medium.com/feed/@karpathy",
            "https://eng.medium.com/some-post": "https://eng.medium.com/feed",
            "https://github.com/astral-sh/uv/issues": "https://github.com/astral-sh/uv/releases.atom",
        }
        for url, feed in cases.items():
            with self.subTest(url=url):
                finding, http = find({feed: atom("Releases")}, url)
                self.assertEqual(finding, found((feed, "Releases")))
                self.assertEqual(http.requests, [feed])

    def test_nothing_found_is_none(self):
        finding, http = find({"https://x.example/news/": page()}, "https://x.example/news/")
        self.assertEqual(finding, FeedFinding("none"))
        self.assertEqual(len(http.requests), 2 + len(feed_finder.COMMON_PATHS), "the page, home and the paths")

    def test_a_slow_candidate_does_not_hold_back_a_proved_feed(self):
        head = ('<link rel="alternate" type="application/rss+xml" href="/slow.xml">'
                '<link rel="alternate" type="application/rss+xml" href="/fast.xml">')
        started = time.monotonic()
        with mock.patch.object(feed_finder, "PROOF_GRACE_S", 0.05):
            finding, _ = find({"https://x.example/": page(head), "https://x.example/slow.xml": hang,
                               "https://x.example/fast.xml": rss("Fast")}, "https://x.example/")
        self.assertEqual(finding, found(("https://x.example/fast.xml", "Fast")))
        self.assertLess(time.monotonic() - started, 1)

    def test_a_hanging_site_gives_none_within_the_budget(self):
        started = time.monotonic()
        with mock.patch.object(feed_finder, "BUDGET_S", 0.2):
            finding, _ = find(hang, "https://x.example/")
        self.assertEqual(finding, FeedFinding("none"))
        self.assertLess(time.monotonic() - started, 1)

    def test_a_request_slower_than_its_timeout_is_skipped(self):
        with mock.patch.object(feed_finder, "REQUEST_TIMEOUT_S", 0.05):
            finding, _ = find({"https://x.example/": hang, "https://x.example/feed": rss("Site")}, "https://x.example/")
        self.assertEqual(finding, found(("https://x.example/feed", "Site")))

    def test_at_most_four_requests_at_once(self):
        running, most = 0, 0

        async def counted(_url):
            nonlocal running, most
            running += 1
            most = max(most, running)
            await asyncio.sleep(0.01)
            running -= 1
            return page()
        find(counted, "https://x.example/")
        self.assertEqual(most, 4)


class GetStartTests(unittest.TestCase):
    def test_reads_only_the_first_bytes_and_reports_the_final_url(self):
        class Response(io.BytesIO):
            def geturl(self):
                return "https://x.example/final"

        with mock.patch.object(urllib.request, "urlopen", return_value=Response(b"a" * 100)):
            body, final = asyncio.run(KindHttp().get_start("https://x.example/", 10))
        self.assertEqual((body, final), (b"a" * 10, "https://x.example/final"))


class FindFeedRouteTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttp({"https://x.example/": page('<link rel="alternate" type="application/rss+xml" href="/feed">'),
                              "https://x.example/feed": rss("X")})
        kinds = KindRegistry.default(self.http, None)
        self.addCleanup(services_registry.use, services_registry.use(SimpleNamespace(source_fetch=SimpleNamespace(kinds=kinds))))
        patcher = mock.patch.object(main, "FEED_FINDER_HTTP", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_the_status_and_the_feeds(self):
        status, _, body = call(main.app, "POST", "/api/sources/find-feed", json_body={"url": "x.example"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"success": True, "status": "found", "feeds": [{"url": "https://x.example/feed", "title": "X"}],
                                "homepage": False, "pages": []})

    def test_an_empty_address_is_a_400(self):
        status, _, body = call(main.app, "POST", "/api/sources/find-feed", json_body={"url": " "})
        self.assertEqual(status, 400)
        self.assertIn("An address is needed", str(body))


SHOP = "https://shop.example"


def dated_section(path: str, count: int, site: str = SHOP) -> dict:
    """A section page of `count` dated articles (no sitemap), and the articles."""
    links = "".join(f'<a href="{path}/post-{n}">Post {n}</a>' for n in range(count))
    return {f"{site}{path}": page(body=f"<main>{links}</main>"),
            **{f"{site}{path}/post-{n}": article(f"Post {n}", "2026-10-01T00:00:00Z") for n in range(count)}}


class FollowTheBlogTests(unittest.TestCase):
    """Issue 0041: a home page with no feed offers its own blog or news page to follow, the one
    with the most articles first. stripe.com's home page would follow /customers/ (557 links,
    0 articles); its /blog had 269 dated articles (2026-10-28)."""

    def ask(self, responses, url: str, **fake) -> dict:
        http = FakeHttp(responses, **fake)
        kinds = KindRegistry.default(http, None)
        self.addCleanup(services_registry.use, services_registry.use(SimpleNamespace(source_fetch=SimpleNamespace(kinds=kinds))))
        with mock.patch.object(main, "FEED_FINDER_HTTP", http):
            status, _, body = call(main.app, "POST", "/api/sources/find-feed", json_body={"url": url})
        self.assertEqual(status, 200)
        return body

    def test_a_home_page_with_a_feedless_blog_offers_the_blog_with_its_count(self):
        body = self.ask({f"{SHOP}/": page(body='<a href="/customers/a/b">A customer</a><a href="/blog">Blog</a>'),
                         **dated_section("/blog", 3)}, "shop.example")
        self.assertEqual((body["status"], body["homepage"]), ("none", True))
        [offer] = body["pages"]
        self.assertEqual((offer["url"], offer["prefix"], offer["found"], len(offer["items"])),
                         (f"{SHOP}/blog", "/blog/", 3, 3))

    def test_the_page_with_the_most_articles_comes_first_whatever_its_order(self):
        body = self.ask({f"{SHOP}/": page(body='<a href="/press">Press</a><a href="/news">News</a>'),
                         **dated_section("/press", 2), **dated_section("/news", 6)}, "https://shop.example/")
        self.assertEqual([(offer["url"], offer["found"]) for offer in body["pages"]],
                         [(f"{SHOP}/news", 6), (f"{SHOP}/press", 2)])

    def test_a_page_without_articles_is_not_offered(self):
        body = self.ask({f"{SHOP}/": page(body='<a href="/blog">Blog</a><a href="/news">News</a>'),
                         f"{SHOP}/news": page(body="<p>No links here</p>"), **dated_section("/blog", 1)}, SHOP)
        self.assertEqual([offer["url"] for offer in body["pages"]], [f"{SHOP}/blog"])

    def test_another_sites_blog_is_never_followed(self):
        # A link to another site's blog, and the site's own "News" that lands on another site.
        other = "https://other.example"
        body = self.ask({f"{SHOP}/": page(body=f'<a href="{other}/blog">Blog</a><a href="/news">News</a>'),
                         **dated_section("/blog", 4, other), f"{SHOP}/news": dated_section("/news", 4, other)[f"{other}/news"]},
                        SHOP, redirects={f"{SHOP}/news": f"{other}/news"})
        self.assertEqual((body["status"], body["homepage"], body["pages"]), ("none", True, []))

    def test_a_home_page_with_no_blog_link_is_the_last_resort(self):
        body = self.ask({f"{SHOP}/": page(body='<a href="/customers/a/b">A customer</a>')}, SHOP)
        self.assertEqual((body["status"], body["homepage"], body["pages"]), ("none", True, []))

    def test_a_section_address_is_followed_as_it_is(self):
        responses = {**dated_section("/blog", 2), f"{SHOP}/": page(body='<a href="/news">News</a>'), **dated_section("/news", 5)}
        responses[f"{SHOP}/blog"] = responses[f"{SHOP}/blog"].replace("<main>", '<main><a href="/news">News</a>')
        body = self.ask(responses, f"{SHOP}/blog")
        self.assertEqual((body["status"], body["homepage"], body["pages"]), ("none", False, []))

    def test_a_feed_found_is_unchanged(self):
        body = self.ask({f"{SHOP}/": page(body='<a href="/blog">Blog</a>'), f"{SHOP}/blog": page(),
                         f"{SHOP}/blog/feed": rss("Shop blog")}, SHOP)
        self.assertEqual((body["status"], body["homepage"], body["pages"]), ("found", False, []))

    def test_the_finder_reports_the_blog_pages_it_read(self):
        finding, _ = find({f"{SHOP}/": page(body='<a href="/blog/tag/launches">Blog</a><a href="/news">News</a>'
                                                 '<a href="/blog">Blog</a>'),
                           f"{SHOP}/news": page(), f"{SHOP}/blog": page()}, SHOP)
        # The section before a page within it (cohere.com's "Blog" links /blog/tag/research first).
        self.assertEqual(finding, FeedFinding("none", pages=(f"{SHOP}/news", f"{SHOP}/blog")))

    def test_a_menu_item_named_blog_with_a_description_counts(self):
        # harvey.ai's menu: "Blog →" over "Product updates, insights, …" in one link (2026-10-28).
        finding, _ = find({f"{SHOP}/": page(body='<a href="/blog"><span>Blog</span><svg></svg>'
                                                 '<p>Product updates, insights and stories</p></a>'
                                                 '<a href="/pricing"><span>Pricing</span><p>Our blog plans</p></a>'),
                           f"{SHOP}/blog": page()}, SHOP)
        self.assertEqual(finding.pages, (f"{SHOP}/blog",))

    def test_an_address_that_cannot_be_read_takes_the_home_pages_blog(self):
        # A source's gone feed at the root (the source doctor): its home page's blog stands in.
        finding, _ = find({f"{SHOP}/": page(body='<a href="/blog">Blog</a>'), f"{SHOP}/blog": page()},
                          f"{SHOP}/rss")
        self.assertEqual(finding, FeedFinding("none", pages=(f"{SHOP}/blog",)))


if __name__ == "__main__":
    unittest.main()
