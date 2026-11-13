"""The feed finder (issue 0026): any page address to its feeds. No network: FakeHttp."""
from __future__ import annotations

import asyncio
import io
import sys
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
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


# The stories service of a library whose sources linked nothing (issue 0060).
NO_LINKS = SimpleNamespace(linked_articles=lambda _address: [])


async def hang(_url: str) -> str:
    await asyncio.sleep(3600)
    return ""


class FeedFinderTests(unittest.TestCase):
    def test_an_address_that_is_a_feed_is_the_feed_with_its_title(self):
        finding, http = find({"https://x.example/feed.xml": rss("X Weekly")}, "https://x.example/feed.xml")
        self.assertEqual(finding, FeedFinding("feed", (Feed("https://x.example/feed.xml", "X Weekly"),)))
        self.assertEqual(http.requests, ["https://x.example/feed.xml", "https://x.example/0"])  # its items have no body: the first one's page is read once (issue 0108)

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
        self.assertEqual(len(http.requests), 4, "the page, its two feeds and the first item's page (no body: 0108)")

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
        self.assertEqual(http.requests, ["https://x.example/p", "https://x.example/feed/", "https://x.example/0"])  # its items have no body: the first one's page is read once (issue 0108)

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
                    "https://www.pipecraft.me/"):
            with self.subTest(url=url):
                finding, http = find({}, url)
                self.assertEqual(finding, FeedFinding("direct"))
                self.assertEqual(http.requests, [])
        # A bridge's address is probed first (issue 0137 B3): one that answers is direct.
        finding, http = find({"https://nitter.local/nn_teacher/rss": atom("nn_teacher")}, "https://nitter.local/nn_teacher/rss")
        self.assertEqual((finding, http.requests), (FeedFinding("direct"), ["https://nitter.local/nn_teacher/rss"]))

    def test_medium_and_github_rules_need_no_page(self):
        cases = {
            "https://medium.com/@nn_teacher/a-recipe-1": "https://medium.com/feed/@nn_teacher",
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

        with mock.patch.object(KindHttp, "_open", return_value=Response(b"a" * 100)):
            body, final = asyncio.run(KindHttp().get_start("https://x.example/", 10))
        self.assertEqual((body, final), (b"a" * 10, "https://x.example/final"))


class FindFeedRouteTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttp({"https://x.example/": page('<link rel="alternate" type="application/rss+xml" href="/feed">'),
                              "https://x.example/feed": rss("X")})
        kinds = KindRegistry.default(self.http, None)
        self.addCleanup(services_registry.use, services_registry.use(SimpleNamespace(source_fetch=SimpleNamespace(kinds=kinds), stories=NO_LINKS)))
        patcher = mock.patch.object(main, "FEED_FINDER_HTTP", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_the_status_and_the_feeds(self):
        status, _, body = call(main.app, "POST", "/api/sources/find-feed", json_body={"url": "x.example"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"success": True, "status": "found", "feeds": [{"url": "https://x.example/feed", "title": "X"}],
                                "homepage": False, "pages": [], "linked": 0, "start": None,
                                "landed": "https://x.example/"})   # where the address landed (issue 0172 b1)

    def test_an_empty_address_is_a_400(self):
        status, _, body = call(main.app, "POST", "/api/sources/find-feed", json_body={"url": " "})
        self.assertEqual(status, 400)
        self.assertIn("An address is needed", str(body))


SHOP = "https://shop.example"


def dated_section(path: str, count: int, site: str = SHOP, published: str = "2026-10-01T00:00:00Z") -> dict:
    """A section page of `count` dated articles (no sitemap), and the articles."""
    links = "".join(f'<a href="{path}/post-{n}">Post {n}</a>' for n in range(count))
    return {f"{site}{path}": page(body=f"<main>{links}</main>"),
            **{f"{site}{path}/post-{n}": article(f"Post {n}", published) for n in range(count)}}


class FollowTheBlogTests(unittest.TestCase):
    """Issue 0041: a home page with no feed offers its own blog or news page to follow, the one
    with the most articles first. stripe.com's home page would follow /customers/ (557 links,
    0 articles); its /blog had 269 dated articles (2026-10-28)."""

    def ask(self, responses, url: str, **fake) -> dict:
        http = FakeHttp(responses, **fake)
        kinds = KindRegistry.default(http, None)
        self.addCleanup(services_registry.use, services_registry.use(SimpleNamespace(source_fetch=SimpleNamespace(kinds=kinds), stories=NO_LINKS)))
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


def menu(header: str = "", footer: str = "", body: str = "") -> str:
    return page(body=f"<header><nav>{header}</nav></header><main>{body}</main><footer>{footer}</footer>")


def recent_section(path: str, count: int, days_ago: int = 3) -> dict:
    """dated_section, its articles published days_ago."""
    return dated_section(path, count, published=(datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat())


class BlogUnderAnotherNameTests(unittest.TestCase):
    """Issue 0047: a home page that names no blog or news page may still have one under another
    word: linear.app's "Now" (/now), reka.ai's "Reka Latest" (/news), atlassian.com's "AI blogs &
    news" (2026-10-28). Its own menu links are previewed and the evidence chooses: the one that
    reads as an article list, the most articles first. No word is added to BLOG_LINK_TEXTS."""

    ask = FollowTheBlogTests.ask

    def test_an_unnamed_blog_is_found_by_its_article_count(self):
        body = self.ask({f"{SHOP}/": menu('<a href="/pricing">Pricing</a><a href="/now">Now</a>'),
                         f"{SHOP}/pricing": page(body="<p>Plans</p>"), **recent_section("/now", 6)}, SHOP)
        self.assertEqual([(offer["url"], offer["prefix"], offer["found"]) for offer in body["pages"]],
                         [(f"{SHOP}/now", "/now/", 6)])

    def test_the_menu_link_with_the_most_articles_comes_first(self):
        body = self.ask({f"{SHOP}/": menu('<a href="/stories">Stories</a>', '<a href="/latest">Latest</a>'),
                         **recent_section("/stories", 7), **recent_section("/latest", 12)}, SHOP)
        self.assertEqual([offer["url"] for offer in body["pages"]], [f"{SHOP}/latest", f"{SHOP}/stories"])

    def test_a_product_page_with_few_dated_links_is_not_offered(self):
        # atlassian.com's /software: 572 links, one dated page among those read (2026-10-28).
        responses = {f"{SHOP}/": menu('<a href="/software">Software</a>'), **recent_section("/software", 2)}
        responses[f"{SHOP}/software"] = responses[f"{SHOP}/software"].replace(
            "</main>", "".join(f'<a href="/software/tool-{n}">Tool {n}</a>' for n in range(30)) + "</main>")
        responses.update({f"{SHOP}/software/tool-{n}": page(body="<p>A tool</p>") for n in range(30)})
        body = self.ask(responses, SHOP)
        self.assertEqual((body["status"], body["homepage"], body["pages"]), ("none", True, []))

    def test_a_page_of_people_with_old_dates_is_not_offered(self):
        # ideo.com's /leaders: 25 pages, each dated by a joining year (2026-10-28).
        body = self.ask({f"{SHOP}/": menu('<a href="/leaders">Leaders</a>'),
                         **recent_section("/leaders", 9, days_ago=400)}, SHOP)
        self.assertEqual(body["pages"], [])

    def test_a_page_of_policies_with_few_recent_dates_is_not_offered(self):
        # 37signals.com's /policies: 3 dated pages among the 8 read, 2 updated this year (2026-10-28).
        responses = {f"{SHOP}/": menu('<a href="/policies">Policies</a>'), **recent_section("/policies", 2),
                     **recent_section("/policies/old", 1, days_ago=1500)}
        responses[f"{SHOP}/policies"] = responses[f"{SHOP}/policies"].replace(
            "</main>", '<a href="/policies/old/post-0">Old</a></main>')
        body = self.ask(responses, SHOP)
        self.assertEqual(body["pages"], [])

    def test_a_named_blog_still_wins(self):
        body = self.ask({f"{SHOP}/": menu('<a href="/blog">Blog</a><a href="/now">Now</a>'),
                         **dated_section("/blog", 2), **recent_section("/now", 9)}, SHOP)
        self.assertEqual([offer["url"] for offer in body["pages"]], [f"{SHOP}/blog"])

    def test_the_budget_is_respected(self):
        # One menu page that never answers is left out; the others are offered in time.
        async def never(_url):
            await asyncio.sleep(3600)
        responses = {f"{SHOP}/": menu('<a href="/slow">Slow</a><a href="/now">Now</a>'), f"{SHOP}/slow": never,
                     **recent_section("/now", 6)}
        started = time.monotonic()
        with mock.patch.object(main.page_watch, "OFFER_BUDGET_S", 0.5):
            body = self.ask(responses, SHOP)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual([offer["url"] for offer in body["pages"]], [f"{SHOP}/now"])

    def test_the_previews_of_one_run_read_the_sites_sitemap_once(self):
        sitemap = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                   f"<url><loc>{SHOP}/now/post-0</loc></url><url><loc>{SHOP}/stories/post-0</loc></url></urlset>")
        http = FakeHttp({f"{SHOP}/robots.txt": f"Sitemap: {SHOP}/sitemap.xml", f"{SHOP}/sitemap.xml": sitemap,
                         **recent_section("/now", 4), **recent_section("/stories", 3)})
        found = asyncio.run(main.page_watch.offers(http, [], [f"{SHOP}/now", f"{SHOP}/stories"]))
        self.assertEqual([offer["url"] for offer in found], [f"{SHOP}/now", f"{SHOP}/stories"])
        self.assertEqual((http.requests.count(f"{SHOP}/robots.txt"), http.requests.count(f"{SHOP}/sitemap.xml")), (1, 1))

    def test_the_finder_reports_the_menu_header_first_shallowest_first_at_most_twelve(self):
        header = ("".join(f'<a href="/h{n}">H{n}</a>' for n in range(10)) + '<a href="/deep/page">Deep</a>'
                  '<a href="/signup?plan=team">Sign up</a>')
        footer = ('<a href="/f0">F0</a><a href="/f1">F1</a><a href="/f2">F2</a><a href="https://other.example/x">Away</a>'
                  '<a href="/">Home</a>')
        finding, _ = find({f"{SHOP}/": menu(header, footer, body='<a href="/body">In the page</a>')}, SHOP)
        self.assertEqual(finding.menu, (*(f"{SHOP}/h{n}" for n in range(10)), f"{SHOP}/f0", f"{SHOP}/f1"))
        self.assertEqual(finding.pages, ())

    def test_no_menu_is_reported_when_a_page_is_named(self):
        finding, _ = find({f"{SHOP}/": menu('<a href="/blog">Blog</a><a href="/now">Now</a>'), f"{SHOP}/blog": page()}, SHOP)
        self.assertEqual((finding.pages, finding.menu), ((f"{SHOP}/blog",), ()))


# ---- issue 0108: a feed whose posts moved, and a blog on another domain ---------------------------

from insight_core.tests.test_moved_pages import NEW, OLD, OLD_FEED, blog_post, empty_feed, stub  # noqa: E402

HOME = "https://home.example/"
BLOG_FEED = "https://www.blog.example/rss/"


def blog_rss(title: str = "The Blog") -> str:
    """The moved-to blog's RSS (Ghost-shaped: full bodies)."""
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{title}</title>'
            f"<item><title>The post</title><link>{NEW}</link><description>A summary.</description>"
            f"<content:encoded xmlns:content=\"http://purl.org/rss/1.0/modules/content/\"><![CDATA[<p>All of it.</p>]]>"
            "</content:encoded></item></channel></rss>")


def moved_site(**more) -> dict:
    """The measured shape: a home page naming its own feed of empty entries, each post page a stub to the
    blog's post, whose page names the blog's feed."""
    return {HOME: page(f'<link rel="alternate" type="application/atom+xml" href="{OLD_FEED}">'),
            OLD_FEED: empty_feed(OLD, "https://home.example/posts/2020/08/another"), OLD: stub(),
            NEW: blog_post().replace("<head>", f'<head><link rel="alternate" type="application/rss+xml" href="{BLOG_FEED}">'),
            BLOG_FEED: blog_rss(), **more}


class MovedFeedTests(unittest.TestCase):
    """Decision 3: the finder looks past a feed whose posts have moved."""

    def test_the_moved_to_feed_comes_first_and_the_old_one_says_where_its_posts_live(self):
        finding, http = find(moved_site(), HOME)
        self.assertEqual(finding, found((BLOG_FEED, "The Blog"), (OLD_FEED, "Home")))
        self.assertEqual([feed.moved_to for feed in finding.feeds], ["", "blog.example"])
        self.assertIn(OLD, http.requests, "the first entry's page")
        self.assertNotIn("https://home.example/posts/2020/08/another", http.requests, "only the first")

    def test_a_feed_address_whose_posts_moved_offers_both(self):
        finding, _ = find(moved_site(), OLD_FEED)
        self.assertEqual(finding, found((BLOG_FEED, "The Blog"), (OLD_FEED, "Home")))

    def test_an_entry_page_redirected_by_http_to_another_site_counts(self):
        responses = moved_site()
        responses[OLD] = responses[NEW]
        finding, _ = find(responses, HOME, redirects={OLD: NEW})
        self.assertEqual([feed.url for feed in finding.feeds], [BLOG_FEED, OLD_FEED])

    def test_a_feed_with_bodies_is_not_looked_past(self):
        responses = moved_site()
        responses[OLD_FEED] = responses[OLD_FEED].replace('<summary type="html"><![CDATA[]]>',
                                                          '<summary type="html"><![CDATA[What the post says.]]>')
        finding, http = find(responses, HOME)
        self.assertEqual(finding, found((OLD_FEED, "Home")))
        self.assertNotIn(OLD, http.requests)

    def test_an_entry_page_canonical_on_the_same_site_is_no_move(self):
        responses = moved_site()
        responses[OLD] = stub("https://home.example/posts/new-path")
        finding, _ = find(responses, HOME)
        self.assertEqual(finding, found((OLD_FEED, "Home")))

    def test_an_entry_page_that_cannot_be_read_leaves_the_feed(self):
        responses = moved_site()
        del responses[OLD]
        finding, _ = find(responses, HOME)
        self.assertEqual(finding, found((OLD_FEED, "Home")))

    def test_the_route_says_where_the_posts_live(self):
        body = FollowTheBlogTests.ask(self, moved_site(), "home.example")
        self.assertEqual(body["feeds"], [{"url": BLOG_FEED, "title": "The Blog"},
                                         {"url": OLD_FEED, "title": "Home", "moved_to": "blog.example"}])


def nav(*links: tuple[str, str], head: str = "", body: str = "") -> str:
    """A personal site's home page: its menu links in a <nav>."""
    items = "".join(f'<a href="{href}">{text}</a>' for href, text in links)
    return page(head, f'<nav id="site-nav">{items}</nav><main>{body}</main>')


class BlogOnAnotherDomainTests(unittest.TestCase):
    """Decision 4: the home page's menu link named Blog (or Writing, Posts, Essays) on another domain
    is a candidate after the site's own feeds."""

    def test_the_menu_blog_on_another_domain_comes_after_the_sites_own_feed(self):
        responses = {HOME: nav(("https://home.example/about/", "About"), ("https://blog.example", "Blog"),
                               head='<link rel="alternate" type="application/rss+xml" href="/feed.xml">'),
                     "https://home.example/feed.xml": blog_rss("Home"),
                     "https://blog.example": page(f'<link rel="alternate" type="application/rss+xml" href="{BLOG_FEED}">'),
                     BLOG_FEED: blog_rss()}
        finding, _ = find(responses, HOME)
        self.assertEqual(finding, found(("https://home.example/feed.xml", "Home"), (BLOG_FEED, "The Blog")))

    def test_with_no_feed_of_its_own_the_menu_writing_link_is_the_feed(self):
        responses = {HOME: nav(("https://home.example/cv/", "CV"), ("https://words.example/", "Writing")),
                     "https://words.example/": page('<link rel="alternate" type="application/atom+xml" href="/atom.xml">'),
                     "https://words.example/atom.xml": atom("Words")}
        finding, _ = find(responses, HOME)
        self.assertEqual(finding, found(("https://words.example/atom.xml", "Words")))

    def test_each_word_counts_and_only_in_the_menu(self):
        for word in ("Blog", "Writing", "Posts", "Essays", "blog"):
            responses = {HOME: nav(("https://words.example/", word)),
                         "https://words.example/": page('<link rel="alternate" type="application/atom+xml" href="/atom.xml">'),
                         "https://words.example/atom.xml": atom("Words")}
            self.assertEqual(find(responses, HOME)[0].status, "found", word)
        responses = {HOME: nav(body='<a href="https://words.example/">Blog</a>'),
                     "https://words.example/": page('<link rel="alternate" type="application/atom+xml" href="/atom.xml">'),
                     "https://words.example/atom.xml": atom("Words")}
        finding, http = find(responses, HOME)
        self.assertEqual(finding.status, "none", "a Blog link in the page's text is someone else's")
        self.assertNotIn("https://words.example/", http.requests)

    def test_another_word_on_another_domain_is_not_a_blog(self):
        responses = {HOME: nav(("https://work.example/", "Work")),
                     "https://work.example/": page('<link rel="alternate" type="application/atom+xml" href="/atom.xml">'),
                     "https://work.example/atom.xml": atom("Work")}
        finding, http = find(responses, HOME)
        self.assertEqual(finding.status, "none")
        self.assertNotIn("https://work.example/", http.requests)

    def test_a_menu_blog_on_a_platform_takes_its_platform_rule(self):
        responses = {HOME: nav(("https://medium.com/@writer", "Blog")),
                     "https://medium.com/feed/@writer": rss("Writer on Medium")}
        finding, _ = find(responses, HOME)
        self.assertEqual(finding, found(("https://medium.com/feed/@writer", "Writer on Medium")))

    def test_the_moved_site_is_found_both_ways_once(self):
        # The measured case: the site's feed (posts moved), and its menu's Blog link to where they moved.
        responses = moved_site()
        responses[HOME] = nav(("https://www.blog.example", "Blog"),
                              head=f'<link rel="alternate" type="application/atom+xml" href="{OLD_FEED}">')
        responses["https://www.blog.example"] = page(f'<link rel="alternate" type="application/rss+xml" href="{BLOG_FEED}">')
        finding, _ = find(responses, HOME)
        self.assertEqual(finding, found((BLOG_FEED, "The Blog"), (OLD_FEED, "Home")))
        self.assertEqual(finding.feeds[1].moved_to, "blog.example")


# ---- v10.13.5: an account or project page on a platform ------------------------------------------

def items_rss(title: str, *links: str) -> str:
    entries = "".join(f"<item><title>{n}</title><link>{url}</link><description>x</description></item>"
                      for n, url in enumerate(links))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{entries}</channel></rss>'


def empty_atom(title: str) -> str:
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>{title}</title></feed>'


def alternate(href: str) -> str:
    return f'<link rel="alternate" type="application/rss+xml" href="{href}">'


HUB = "https://hub.example"          # a platform: accounts at /<name>, its own blog at /blog
HUB_BLOG_FEED = f"{HUB}/blog/feed.xml"
HUB_BLOG_ELSEWHERE = {               # the platform's blog on a domain of its own (github.blog's shape)
    "https://hub-blog.example/": page(alternate("/feed/")),
    "https://hub-blog.example/feed/": items_rss("The Hub Blog", "https://hub-blog.example/a-post"),
}


def hub_site(**more) -> dict:
    """The measured shape: an account page with no feed; the home page names the platform's blog feed
    (its items under /blog/) and links its blog, whose page names it too."""
    return {f"{HUB}/": page(alternate("/blog/feed.xml"), '<a href="/blog">Blog</a>'),
            f"{HUB}/blog": page(alternate("/blog/feed.xml")),
            HUB_BLOG_FEED: items_rss("Hub - Blog", f"{HUB}/blog/a-launch-post", f"{HUB}/blog/another-post"),
            **more}


class PlatformAccountTests(unittest.TestCase):
    """An account or project page on a platform is never offered the platform's own blog (v10.13.5)."""

    def test_an_account_or_model_page_is_not_offered_the_platforms_blog_feed(self):
        for url in (f"{HUB}/example-org", f"{HUB}/example-org/widget-model"):
            with self.subTest(url=url):
                finding, _ = find(hub_site(**{url: page(body="<p>An account</p>")}), url)
                self.assertEqual((finding.status, finding.feeds, finding.reason), ("none", (), "none found"))

    def test_the_home_page_still_gets_the_platforms_blog_feed(self):
        finding, _ = find(hub_site(), f"{HUB}/")
        self.assertEqual([feed.url for feed in finding.feeds], [HUB_BLOG_FEED])

    def test_a_feed_holding_the_sections_posts_is_the_pages(self):
        # Posts under /posts/, the feed at /blog/feed.xml: still the article's.
        responses = {"https://x.example/posts/a-post": page(body="<p>A post</p>"),
                     "https://x.example/": page(alternate("/blog/feed.xml")),
                     "https://x.example/blog/feed.xml": items_rss("X", "https://x.example/posts/a-post")}
        finding, _ = find(responses, "https://x.example/posts/a-post")
        self.assertEqual([feed.url for feed in finding.feeds], ["https://x.example/blog/feed.xml"])

    def test_a_root_feed_and_the_sections_own_feed_are_still_an_articles(self):
        for feed_url in ("https://x.example/feed.xml", "https://x.example/rss/all.xml", "https://x.example/essays/feed.xml"):
            with self.subTest(feed=feed_url):
                responses = {"https://x.example/essays/one.html": page(body="<p>An essay</p>"),
                             "https://x.example/": page(alternate(feed_url)),
                             feed_url: items_rss("X", "https://x.example/elsewhere/a")}
                finding, _ = find(responses, "https://x.example/essays/one.html")
                self.assertEqual([feed.url for feed in finding.feeds], [feed_url])

    def test_the_home_pages_menu_blog_elsewhere_is_the_home_pages_only(self):
        home = nav(("https://hub-blog.example/", "Blog"))
        finding, http = find({f"{HUB}/": home, f"{HUB}/example-org": page(), **HUB_BLOG_ELSEWHERE}, f"{HUB}/example-org")
        self.assertEqual((finding.status, finding.feeds), ("none", ()))
        self.assertNotIn("https://hub-blog.example/feed/", http.requests)
        finding, _ = find({f"{HUB}/": home, **HUB_BLOG_ELSEWHERE}, f"{HUB}/")
        self.assertEqual([feed.url for feed in finding.feeds], ["https://hub-blog.example/feed/"])

    def test_github_account_pages_take_their_activity_feed(self):
        feed = "https://github.com/example-org.atom"
        finding, http = find({feed: atom("example-org")}, "https://github.com/example-org")
        self.assertEqual(finding, found((feed, "example-org")))
        self.assertEqual(http.requests, [feed])

    def test_a_github_org_with_an_empty_activity_feed_or_a_repo_without_releases_gets_none_not_the_blog(self):
        for url, rule in (("https://github.com/example-org", "https://github.com/example-org.atom"),
                          ("https://github.com/example-org/widget", "https://github.com/example-org/widget/releases.atom")):
            with self.subTest(url=url):
                responses = {rule: empty_atom("Public Timeline"), url: nav(("https://hub-blog.example/", "Blog")),
                             "https://github.com/": nav(("https://hub-blog.example/", "Blog")), **HUB_BLOG_ELSEWHERE}
                finding, http = find(responses, url)
                self.assertEqual((finding.status, finding.feeds), ("none", ()))
                self.assertNotIn("https://hub-blog.example/feed/", http.requests)

    def test_arxiv_and_pypi_rules_need_no_page(self):
        cases = {
            "https://arxiv.org/list/cs.XY/recent": "https://rss.arxiv.org/rss/cs.XY",
            "https://arxiv.org/list/cs.XY/pastweek?show=50": "https://rss.arxiv.org/rss/cs.XY",
            "https://arxiv.org/archive/math": "https://rss.arxiv.org/rss/math",
            "https://pypi.org/project/widget/": "https://pypi.org/rss/project/widget/releases.xml",
            "https://pypi.org/project/widget/1.2.0/": "https://pypi.org/rss/project/widget/releases.xml",
        }
        for url, feed in cases.items():
            with self.subTest(url=url):
                finding, http = find({feed: atom("Updates")}, url)
                self.assertEqual(finding, found((feed, "Updates")))
                self.assertEqual(http.requests, [feed])

    def test_a_pypi_project_is_offered_its_releases_not_the_sites_feeds(self):
        head = "".join(alternate(href) for href in ("/rss/updates.xml", "/rss/packages.xml", "/rss/project/widget/releases.xml"))
        responses = {"https://pypi.org/project/widget/": page(head),
                     "https://pypi.org/rss/updates.xml": items_rss("Recent updates", "https://pypi.org/project/other/1/"),
                     "https://pypi.org/rss/packages.xml": items_rss("Newest packages", "https://pypi.org/project/new/"),
                     "https://pypi.org/rss/project/widget/releases.xml": items_rss("widget", "https://pypi.org/project/widget/1.2.0/")}
        finding, _ = find(responses, "https://pypi.org/project/widget/")
        self.assertEqual([feed.url for feed in finding.feeds], ["https://pypi.org/rss/project/widget/releases.xml"])

    def test_a_normal_blogs_post_still_finds_the_blogs_feed_on_its_home_page(self):
        post = "https://writer.example/2026/10/a-post-here"
        responses = {"https://writer.example/": page(alternate("/atom.xml")), post: page(body="<p>A post</p>"),
                     "https://writer.example/atom.xml": items_rss("Writer", "https://writer.example/2026/09/older")}
        for url in ("https://writer.example/", post):
            with self.subTest(url=url):
                finding, _ = find(responses, url)
                self.assertEqual([feed.url for feed in finding.feeds], ["https://writer.example/atom.xml"])


PROFILE_API = "https://substack.com/api/v1/user/examplewriter/public_profile"


def profile(primary=None, *memberships) -> str:
    """Substack's public profile answer: primaryPublication and publicationUsers [(role, publication)]."""
    import json

    return json.dumps({"id": 1, "handle": "examplewriter", "name": "Example Writer", "primaryPublication": primary,
                       "publicationUsers": [{"role": role, "publication": pub} for role, pub in memberships]})


def publication(subdomain: str, name: str, custom_domain=None, optional: bool = False) -> dict:
    return {"id": abs(hash(subdomain)) % 1000, "subdomain": subdomain, "custom_domain": custom_domain,
            "custom_domain_optional": optional, "name": name}


class SubstackProfileTests(unittest.TestCase):
    """A Substack profile is offered the person's publications, never Substack's own feed (v10.13.10)."""

    def assert_only_the_profile_asked(self, http):
        self.assertEqual(http.requests, [PROFILE_API])
        self.assertNotIn("https://substack.com/feed", http.requests)

    def test_a_profile_is_offered_its_primary_publications_feed(self):
        answer = profile(publication("examplewriter", "Example Notes"))
        for url in ("https://substack.com/@examplewriter", "https://substack.com/@examplewriter/posts",
                    "https://www.substack.com/@examplewriter", "substack.com/@examplewriter?utm_source=x"):
            with self.subTest(url=url):
                finding, http = find({PROFILE_API: answer}, url)
                self.assertEqual(finding, found(("https://examplewriter.substack.com/feed", "Example Notes")))
                self.assert_only_the_profile_asked(http)

    def test_a_custom_domain_is_the_publications_address(self):
        answer = profile(publication("examplewriter", "Example Notes", custom_domain="www.example-notes.com"))
        finding, http = find({PROFILE_API: answer}, "https://substack.com/@examplewriter")
        self.assertEqual(finding, found(("https://www.example-notes.com/feed", "Example Notes")))
        self.assert_only_the_profile_asked(http)

    def test_several_publications_primary_first_writers_only_once_each(self):
        primary = publication("examplewriter", "Example Notes")
        answer = profile(primary, ("admin", publication("sideproject", "Side Project", custom_domain="side.example")),
                         ("contributor", publication("guestspot", "Guest Spot")),
                         ("author", publication("groupblog", "Group Blog")), ("admin", primary))
        finding, _ = find({PROFILE_API: answer}, "https://substack.com/@examplewriter")
        self.assertEqual(finding, found(("https://examplewriter.substack.com/feed", "Example Notes"),
                                        ("https://side.example/feed", "Side Project"),
                                        ("https://groupblog.substack.com/feed", "Group Blog")))

    def test_a_reader_without_a_primary_publication_is_offered_the_ones_they_write_for(self):
        answer = profile(None, ("admin", publication("groupblog", "Group Blog")))
        finding, _ = find({PROFILE_API: answer}, "https://substack.com/@examplewriter")
        self.assertEqual(finding, found(("https://groupblog.substack.com/feed", "Group Blog")))

    def test_a_profile_with_no_publication_is_none_never_substacks_own_feed(self):
        for answer in (profile(None), profile(None, ("contributor", publication("guestspot", "Guest Spot"))),
                       profile({"subdomain": None, "custom_domain": None, "name": "Nothing"}), "[]"):
            with self.subTest(answer=answer):
                finding, http = find({PROFILE_API: answer, "https://substack.com/feed": rss("Substack")},
                                     "https://substack.com/@examplewriter")
                self.assertEqual((finding.status, finding.feeds, finding.reason),
                                 ("none", (), feed_finder.NO_PUBLICATION))
                self.assert_only_the_profile_asked(http)

    def test_a_profile_that_cant_be_read_is_none_saying_so(self):
        from insight_core.ingestion.http import HttpError

        cases = ((HttpError("HTTP 404", status=404), feed_finder.NO_PROFILE),
                 (HttpError("HTTP 503", status=503), feed_finder.PROFILE_UNREADABLE),
                 ("<html>not json</html>", feed_finder.PROFILE_UNREADABLE))
        for answer, reason in cases:
            with self.subTest(reason=reason):
                finding, http = find({PROFILE_API: answer, "https://substack.com/feed": rss("Substack")},
                                     "https://substack.com/@examplewriter")
                self.assertEqual((finding.status, finding.feeds, finding.reason), ("none", (), reason))
                self.assert_only_the_profile_asked(http)

    def test_an_app_link_to_a_publication_takes_its_feed(self):
        feed = "https://examplewriter.substack.com/feed"
        finding, http = find({feed: atom("Example Notes")}, "https://open.substack.com/pub/examplewriter/p/a-post")
        self.assertEqual(finding, found((feed, "Example Notes")))
        self.assertEqual(http.requests, [feed])

    def test_a_publication_on_substack_is_still_read_directly(self):
        for url in ("https://examplewriter.substack.com", "https://examplewriter.substack.com/p/a-post"):
            with self.subTest(url=url):
                finding, http = find({}, url)
                self.assertEqual((finding, http.requests), (FeedFinding("direct"), []))


if __name__ == "__main__":
    unittest.main()
