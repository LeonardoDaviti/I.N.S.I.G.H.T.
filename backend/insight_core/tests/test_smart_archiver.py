"""The smart archiver (issue 0143): the platform fingerprint, the ladder of strategies, coverage, the learned order,
the re-run of what was called archived, and what each source discovered.

Every fixture is hand-written in its platform's shape (a feed of the latest posts, the platform's paging, API,
sitemap, listing pages) on invented hosts; no request leaves the test (FakeHttp). Each site holds SITE_POSTS posts,
its feed the newest FEED_POSTS: the archive must store all of them.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import BACKLOG_KEY  # noqa: E402
from insight_core.ingestion import archive_ladder as ladder  # noqa: E402
from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter  # noqa: E402
from insight_core.ingestion.http import HttpError  # noqa: E402
from insight_core.ingestion.kinds.base import RateLimit  # noqa: E402
from insight_core.ingestion.kinds.generic_rss import GenericRssKind  # noqa: E402
from insight_core.scripts import rerun_archives_0143 as rerun  # noqa: E402
from insight_core.tests._kind_fakes import FakeHttp as _FakeHttp  # noqa: E402


class FakeHttp(_FakeHttp):
    """FakeHttp that also answers bytes (a gzip sitemap) as they are."""

    async def get_start(self, url, max_bytes):
        answer = self.responses.get(url) if isinstance(self.responses, dict) else None
        if isinstance(answer, bytes):
            self.requests.append(url)
            return answer[:max_bytes], url
        return await super().get_start(url, max_bytes)

RATE = RateLimit(page_delay_s=0, batch_size=0, batch_cooldown_s=0)
SITE_POSTS = 7
FEED_POSTS = 3
START = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
BODY = "What the post says, at length, in its own words. " * 40


def when(n: int) -> datetime:
    """Post n's date: post 0 is the newest, one week apart."""
    return START - timedelta(days=7 * n)


def rfc822(n: int) -> str:
    return when(n).strftime("%a, %d %b %Y %H:%M:%S GMT")


def rss(urls, *, generator: str = "", namespaces: str = "", head: str = "", first: int = 0) -> str:
    items = "".join(
        f"<item><title>Post {first + i}</title><link>{url}</link><guid>{url}</guid><pubDate>{rfc822(first + i)}</pubDate>"
        f"<description><![CDATA[<p>{BODY}</p>]]></description></item>" for i, url in enumerate(urls))
    gen = f"<generator>{generator}</generator>" if generator else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" {namespaces}>'
            f"<channel><title>A blog</title>{gen}{head}{items}</channel></rss>")


def atom(urls, *, generator: str = "", head: str = "", first: int = 0, feed_id: str = "urn:x") -> str:
    entries = "".join(
        f'<entry><title>Post {first + i}</title><link rel="alternate" href="{url}"/><id>{url}</id>'
        f"<published>{when(first + i).isoformat()}</published><content type=\"html\">&lt;p&gt;{BODY}&lt;/p&gt;</content></entry>"
        for i, url in enumerate(urls))
    return (f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
            f'xmlns:openSearch="http://a9.com/-/spec/opensearchrss/1.0/"><id>{feed_id}</id><title>A blog</title>'
            f"{generator}{head}{entries}</feed>")


def article(n: int, *, time_tag: bool = False) -> str:
    dated = (f'<time datetime="{when(n).date().isoformat()}">{when(n):%d %b %Y}</time>' if time_tag
             else f'<meta property="article:published_time" content="{when(n).isoformat()}">')
    return (f'<html><head><title>Post {n}</title><meta property="og:type" content="article">{"" if time_tag else dated}'
            f'</head><body><article><h1>Post {n}</h1>{dated if time_tag else ""}<p>{BODY}</p></article></body></html>')


def links_page(urls, *, extra: str = "") -> str:
    return "<html><body><main>" + "".join(f'<a href="{url}">Post</a>' for url in urls) + extra + "</main></body></html>"


def source(feed: str, **settings) -> dict:
    return {"id": f"s-{uuid.uuid4().hex[:6]}", "platform": "rss", "handle_or_url": feed, "settings": settings}


def kind(http: FakeHttp, stored: set | None = None, learned=None) -> GenericRssKind:
    keys = {s.rstrip("/") for s in stored or ()}
    return GenericRssKind(http, stored_urls=lambda urls: {u for u in urls if u.rstrip("/") in keys}, learned=learned)


async def _pages(k: GenericRssKind, src: dict, checkpoint=None):
    return [page async for page in k.archive_pages(src, 10 ** 9, checkpoint, RATE)]


def archive(k: GenericRssKind, src: dict, checkpoint=None) -> list:
    return asyncio.run(_pages(k, src, checkpoint))


def stored_urls(pages) -> list:
    return [post["url"] for page in pages for post in page.posts]


# ------------------------------------------------------------------------------------------------ the sites


class Fixture:
    """A site of SITE_POSTS posts on a platform: its responses, its feed's address, its posts' addresses."""

    def __init__(self, name: str, feed: str, posts: list, responses: dict, settings: dict | None = None):
        self.name, self.feed, self.posts, self.responses, self.settings = name, feed, posts, responses, settings or {}

    def source(self) -> dict:
        return source(self.feed, **self.settings)


def wordpress_paged() -> Fixture:
    site = "https://wp-paged.example"
    posts = [f"{site}/2026/10/post-{n}/" for n in range(SITE_POSTS)]
    feed = f"{site}/feed/"
    responses = {
        feed: rss(posts[:3], generator="https://wordpress.org/?v=6.6", namespaces='xmlns:wfw="http://wellformedwebnews.org/CommentAPI/"'),
        f"{feed}?paged=2": rss(posts[3:6], generator="https://wordpress.org/?v=6.6", first=3),
        f"{feed}?paged=3": rss(posts[6:], generator="https://wordpress.org/?v=6.6", first=6),
    }
    return Fixture("WordPress (feed ?paged=N)", feed, posts, responses)


def wordpress_rest() -> Fixture:
    site = "https://wp-rest.example"
    posts = [f"{site}/notes/post-{n}/" for n in range(SITE_POSTS)]
    feed = f"{site}/feed/"
    api = [{"id": 100 + n, "link": url, "date_gmt": when(n).strftime("%Y-%m-%dT%H:%M:%S"),
            "title": {"rendered": f"Post {n}"}, "content": {"rendered": f"<p>{BODY}</p>", "protected": False}}
           for n, url in enumerate(posts)]
    head = f'<link rel="https://api.w.org/" href="{site}/wp-json/" />'
    responses = {
        feed: rss(posts[:3], generator="https://wordpress.org/?v=6.6"),
        # The site ignores ?paged: the same feed again.
        f"{feed}?paged=2": rss(posts[:3], generator="https://wordpress.org/?v=6.6"),
        f"{site}/": f"<html><head>{head}</head><body></body></html>",
        f"{site}/wp-json/wp/v2/posts?per_page=50&page=1&orderby=date&order=desc":
            (json.dumps(api), {"x-wp-total": str(SITE_POSTS), "x-wp-totalpages": "1"}),
    }
    return Fixture("WordPress (REST API)", feed, posts, responses)


def blogger() -> Fixture:
    site = "https://notes-blogger.example"
    posts = [f"{site}/2026/{10 - n % 3:02d}/post-{n}.html" for n in range(SITE_POSTS)]
    feed = f"{site}/feeds/posts/default"
    entries = [{"id": {"$t": f"tag:blogger.com,1999:blog-1.post-{n}"}, "published": {"$t": when(n).isoformat()},
                "title": {"$t": f"Post {n}"}, "content": {"$t": f"<p>{BODY}</p>"},
                "link": [{"rel": "replies", "href": f"{site}/x"}, {"rel": "alternate", "href": url}]}
               for n, url in enumerate(posts)]
    responses = {
        feed: atom(posts[:3], generator="<generator>Blogger</generator>", feed_id="tag:blogger.com,1999:blog-1"),
        ladder.Ladder.blogger_url(site, 1): json.dumps({"feed": {"openSearch$totalResults": {"$t": str(SITE_POSTS)},
                                                                  "entry": entries}}),
    }
    return Fixture("Blogger (JSON feed)", feed, posts, responses)


def ghost() -> Fixture:
    site = "https://ghost-blog.example"
    posts = [f"{site}/post-{n}/" for n in range(SITE_POSTS)]
    feed = f"{site}/rss/"
    responses = {
        feed: rss(posts[:3], generator="Ghost 5.88"),
        f"{site}/rss/2/": rss(posts[3:6], generator="Ghost 5.88", first=3),
        f"{site}/rss/3/": rss(posts[6:], generator="Ghost 5.88", first=6),
    }
    return Fixture("Ghost (/rss/N/)", feed, posts, responses)


def rfc5005() -> Fixture:
    site = "https://paged-atom.example"
    posts = [f"{site}/writing/post-{n}" for n in range(SITE_POSTS)]
    feed = f"{site}/atom.xml"
    responses = {
        feed: atom(posts[:3], head=f'<link rel="next" href="{site}/atom-2.xml"/>'),
        f"{site}/atom-2.xml": atom(posts[3:6], head=f'<link rel="next" href="{site}/atom-3.xml"/>', first=3),
        f"{site}/atom-3.xml": atom(posts[6:], first=6),
    }
    return Fixture("Any feed (RFC 5005 rel=next)", feed, posts, responses)


def newsletter() -> Fixture:
    site = "https://letters.example"
    slugs = [f"post-{n}" for n in range(SITE_POSTS)]
    posts = [f"{site}/p/{slug}" for slug in slugs]
    feed = f"{site}/feed"
    items = [{"id": 500 + n, "slug": slug, "title": f"Post {n}", "post_date": when(n).isoformat(),
              "canonical_url": posts[n], "audience": "everyone"} for n, slug in enumerate(slugs)]
    responses = {
        feed: rss(posts[:3], generator="Substack"),
        f"{site}/api/v1/archive?sort=new&limit=12": json.dumps(items),
        **{f"{site}/api/v1/posts/{slug}": json.dumps({**items[n], "body_html": f"<p>{BODY}</p>"})
           for n, slug in enumerate(slugs)},
    }
    return Fixture("Newsletter platform (own domain, archive API)", feed, posts, responses)


def sitemap_gzip() -> Fixture:
    site = "https://gz-blog.example"
    posts = [f"{site}/essays/post-{n}" for n in range(SITE_POSTS)]
    feed = f"{site}/index.xml"
    urlset = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + "".join(f"<url><loc>{url}</loc><lastmod>{when(n).date().isoformat()}</lastmod></url>"
                        for n, url in enumerate(posts)) + f"<url><loc>{site}/about</loc></url></urlset>")
    responses = {
        feed: rss(posts[:3]),
        f"{site}/robots.txt": f"User-agent: *\nSitemap: {site}/sitemap.xml.gz\n",
        f"{site}/sitemap.xml.gz": gzip.compress(urlset.encode()),
        **{url: article(n) for n, url in enumerate(posts)},
    }
    return Fixture("Static site (gzip sitemap)", feed, posts, responses)


def sitemap_fallback() -> Fixture:
    site = "https://wp-sitemap.example"
    posts = [f"{site}/{when(n):%Y/%m}/post-{n}/" for n in range(SITE_POSTS)]
    feed = f"{site}/feed/"
    urlset = ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + "".join(f"<url><loc>{url}</loc><lastmod>{when(n).date().isoformat()}</lastmod></url>"
                        for n, url in enumerate(posts)) + "</urlset>")
    responses = {
        feed: rss(posts[:3]),
        f"{site}/post-sitemap.xml": urlset,
        **{url: article(n) for n, url in enumerate(posts)},
    }
    return Fixture("Blog (no robots sitemap, post-sitemap.xml)", feed, posts, responses)


def hugo_listing() -> Fixture:
    site = "https://hugo-notes.example"
    posts = [f"{site}/posts/post-{n}/" for n in range(SITE_POSTS)]
    feed = f"{site}/index.xml"
    chrome = f'<a href="{site}/tags/go/">go</a><a href="{site}/about/">about</a><a href="{site}/posts/">all</a>'
    responses = {
        feed: rss(posts[:3], generator="Hugo -- gohugo.io"),
        f"{site}/posts/": links_page(posts[:4], extra=chrome + f'<a rel="next" href="{site}/posts/page/2/">Older</a>'),
        f"{site}/posts/page/2/": links_page(posts[4:], extra=chrome),
        **{url: article(n) for n, url in enumerate(posts)},
    }
    return Fixture("Hugo (listing with rel=next)", feed, posts, responses)


def bear_blog() -> Fixture:
    site = "https://bear-notes.example"
    posts = [f"{site}/post-{n}/" for n in range(SITE_POSTS)]
    feed = f"{site}/feed/"
    footer = '<footer>Powered by <a href="https://bearblog.dev">Bear ʕ•ᴥ•ʔ</a></footer>'
    nav = f'<nav><a href="{site}/">Home</a><a href="{site}/now/">Now</a><a href="{site}/blog/">Blog</a></nav>'
    responses = {
        feed: atom(posts[:3]),
        f"{site}/": f"<html><body>{nav}<p>Hello.</p>{footer}</body></html>",
        f"{site}/blog/": f"<html><body>{nav}" + links_page(posts) + f"{footer}</body></html>",
        **{url: article(n, time_tag=True) for n, url in enumerate(posts)},
    }
    return Fixture("Bear Blog (one-page listing)", feed, posts, responses)


FIXTURES = (wordpress_paged, wordpress_rest, blogger, ghost, rfc5005, newsletter, sitemap_gzip, sitemap_fallback,
            hugo_listing, bear_blog)


# ------------------------------------------------------------------------------------------------ fingerprints


class FingerprintTests(unittest.TestCase):
    def name(self, feed: str, url: str = "https://x.example/feed", **kw) -> str:
        return ladder.fingerprint(feed, url, **kw).platform

    def test_each_platform_from_its_feed(self):
        self.assertEqual(self.name(rss([], generator="https://wordpress.org/?v=6.6")), "wordpress")
        self.assertEqual(self.name(atom([], generator="<generator>Blogger</generator>", feed_id="tag:blogger.com,1999:blog-9")), "blogger")
        self.assertEqual(self.name(rss([], generator="Ghost 5.88")), "ghost")
        self.assertEqual(self.name(rss([], generator="Substack")), "newsletter")
        self.assertEqual(self.name(rss([], generator="Hugo -- gohugo.io")), "hugo")
        self.assertEqual(self.name(atom([], generator='<generator uri="https://jekyllrb.com/" version="4.3.3">Jekyll</generator>')), "jekyll")
        self.assertEqual(self.name(rss([], generator="Medium")), "medium")
        self.assertEqual(self.name(rss([], generator="WriteFreely")), "writeas")
        self.assertEqual(self.name(rss([], generator="Tumblr (3.0; @someone)")), "tumblr")
        self.assertEqual(self.name(rss([])), "unknown")

    def test_each_platform_from_its_pages(self):
        page = lambda body: f"<html><head>{body}</head><body></body></html>"  # noqa: E731
        self.assertEqual(self.name(rss([]), home=page('<meta name="generator" content="WordPress 6.6.1">'
                                                       '<link rel="stylesheet" href="/wp-content/themes/x.css">')), "wordpress")
        self.assertEqual(self.name(rss([]), home=page('<script src="https://substackcdn.com/bundle/main.js"></script>')), "newsletter")
        self.assertEqual(self.name(rss([]), home=page('<footer><a href="https://bearblog.dev">Bear</a></footer>')), "bearblog")
        self.assertEqual(self.name(rss([]), home=page('<meta name="generator" content="Ghost 5.88">')), "ghost")
        self.assertEqual(self.name(rss([]), home=page('<meta name="generator" content="Hugo 0.128.0">')), "hugo")
        self.assertEqual(self.name(rss([]), home=page('<link href="https://micro.blog/someone" rel="me">')), "micro.blog")
        self.assertEqual(self.name(rss([]), home=page('<script src="https://www.blogger.com/static/v1/widgets.js">')), "blogger")

    def test_headers_and_hosts_vote_too(self):
        self.assertEqual(self.name(rss([]), headers={"link": '<https://x.example/wp-json/>; rel="https://api.w.org/"',
                                                      "x-pingback": "https://x.example/xmlrpc.php"}), "wordpress")
        self.assertEqual(self.name(rss([]), "https://someone.bearblog.dev/feed/"), "bearblog")

    def test_the_evidence_is_kept(self):
        found = ladder.fingerprint(rss([], generator="Ghost 5.88"), "https://x.example/rss/",
                                   home='<meta name="generator" content="Ghost 5.88">')
        self.assertEqual(found.as_dict()["platform"], "ghost")
        self.assertIn("feed generator: ghost", found.evidence)
        self.assertIn("page generator: ghost", found.evidence)

    def test_the_kind_reads_the_home_page_only_when_the_feed_says_little(self):
        http = FakeHttp(ghost().responses)
        asyncio.run(kind(http).inspect(source(ghost().feed)))
        self.assertIn("https://ghost-blog.example/", http.requests, "one vote: the home page is read for more")


# ------------------------------------------------------------------------------------------------ strategies


class StrategyTests(unittest.TestCase):
    def run_fixture(self, make, stored=None, learned=None):
        fixture = make()
        http = FakeHttp(fixture.responses)
        k = kind(http, stored, learned)
        src = fixture.source()
        plan = asyncio.run(k.inspect(src))
        pages = archive(k, src)
        return fixture, plan, pages, http

    def assertWhole(self, fixture, pages):
        self.assertEqual(sorted(set(stored_urls(pages))), sorted(fixture.posts), fixture.name)

    def test_feed_paging_by_rfc5005(self):
        fixture, plan, pages, _ = self.run_fixture(rfc5005)
        self.assertWhole(fixture, pages)
        self.assertEqual(plan.raw["smart"]["strategy"], "feed_pages")
        self.assertEqual([len(p.posts) for p in pages], [3, 3, 1])
        self.assertTrue(all(post[BACKLOG_KEY] for page in pages[1:] for post in page.posts), "older pages: backlog")
        self.assertTrue(pages[-1].checkpoint["end"])

    def test_wordpress_feed_paging(self):
        fixture, plan, pages, http = self.run_fixture(wordpress_paged)
        self.assertWhole(fixture, pages)
        self.assertEqual(plan.raw["smart"]["platform"], "wordpress")
        self.assertIn("https://wp-paged.example/feed/?paged=4", http.requests, "paged until a page fails")

    def test_wordpress_rest_api_when_the_feed_ignores_paging(self):
        fixture, plan, pages, _ = self.run_fixture(wordpress_rest)
        self.assertWhole(fixture, pages)
        smart = plan.raw["smart"]
        self.assertEqual(smart["outcomes"]["feed_pages"], "paging_same")
        self.assertEqual((smart["strategy"], smart["estimate"]), ("api", SITE_POSTS))
        self.assertEqual(plan.available_posts, SITE_POSTS)

    def test_blogger_json_feed(self):
        fixture, plan, pages, _ = self.run_fixture(blogger)
        self.assertWhole(fixture, pages)
        self.assertEqual((plan.raw["smart"]["platform"], plan.raw["smart"]["strategy"]), ("blogger", "api"))

    def test_ghost_feed_paging(self):
        fixture, plan, pages, _ = self.run_fixture(ghost)
        self.assertWhole(fixture, pages)
        self.assertEqual(plan.raw["smart"]["strategy"], "feed_pages")

    def test_newsletter_archive_on_its_own_domain(self):
        fixture, plan, pages, http = self.run_fixture(newsletter)
        self.assertWhole(fixture, pages)
        self.assertEqual((plan.raw["smart"]["platform"], plan.raw["smart"]["strategy"]), ("newsletter", "api"))
        older = [post for page in pages[1:] for post in page.posts]
        self.assertTrue(all(post["source"] == fixture.feed and post[BACKLOG_KEY] for post in older))
        self.assertFalse(any("Cookie" in headers for _, headers in http.request_headers), "never the owner's cookie")

    def test_gzip_sitemap(self):
        fixture, plan, pages, _ = self.run_fixture(sitemap_gzip)
        self.assertWhole(fixture, pages)
        self.assertEqual(plan.raw["smart"]["strategy"], "sitemap")

    def test_the_posts_sitemap_a_platform_names_when_robots_names_none(self):
        fixture, plan, pages, _ = self.run_fixture(sitemap_fallback)
        self.assertWhole(fixture, pages)
        self.assertEqual(plan.raw["smart"]["outcomes"]["sitemap"], f"more:{SITE_POSTS - FEED_POSTS}")

    def test_listing_pages_followed_by_rel_next(self):
        fixture, plan, pages, http = self.run_fixture(hugo_listing)
        self.assertWhole(fixture, pages)
        self.assertEqual(plan.raw["smart"]["strategy"], "listing")
        self.assertNotIn("https://hugo-notes.example/tags/go/", http.requests, "a tag page is no post")
        self.assertNotIn("https://hugo-notes.example/about/", http.requests)

    def test_a_bear_blog_one_page_listing(self):
        fixture, plan, pages, http = self.run_fixture(bear_blog)
        self.assertWhole(fixture, pages)
        smart = plan.raw["smart"]
        self.assertEqual((smart["platform"], smart["strategy"], smart["estimate"]), ("bearblog", "listing", SITE_POSTS))
        self.assertNotIn("https://bear-notes.example/now/", http.requests)
        self.assertEqual(plan.page_size, 1, "read a post a page")

    def test_the_web_archive_only_when_the_source_opts_in(self):
        site = "https://gone-blog.example"
        posts = [f"{site}/p/post-{n}" for n in range(4)]
        cdx = [["original", "timestamp"]] + [[url.replace("https://", "http://"), f"2020010{n}000000"] for n, url in enumerate(posts)]
        responses = {
            f"{site}/feed.xml": rss(posts[:2]),
            "https://web.archive.org/cdx/search/cdx?" + __import__("urllib.parse").parse.urlencode({
                "url": "gone-blog.example/p/*", "output": "json", "fl": "original,timestamp",
                "filter": "statuscode:200", "collapse": "urlkey", "limit": ladder.MAX_LISTED}): json.dumps(cdx),
            posts[2]: article(2),
            posts[3]: HttpError("HTTP 404", status=404),
            f"https://web.archive.org/web/20200103000000id_/{posts[3]}": article(3),
        }
        http = FakeHttp(responses)
        off = asyncio.run(kind(http).inspect(source(f"{site}/feed.xml")))
        self.assertNotIn("web_archive", off.raw["smart"]["outcomes"])
        self.assertFalse(any("web.archive.org" in url for url in http.requests))
        src = source(f"{site}/feed.xml", archive={"web_archive": True})
        k = kind(FakeHttp(responses))
        on = asyncio.run(k.inspect(src))
        self.assertEqual(on.raw["smart"]["strategy"], "web_archive")
        self.assertEqual(sorted(stored_urls(archive(k, src))), sorted(posts), "the gone page from its archived copy")

    def test_nothing_more_is_one_page_with_every_strategys_reason(self):
        site = "https://small.example"
        posts = [f"{site}/post-{n}/" for n in range(3)]
        http = FakeHttp({f"{site}/feed.xml": rss(posts)})
        k = kind(http)
        plan = asyncio.run(k.inspect(source(f"{site}/feed.xml")))
        smart = plan.raw["smart"]
        self.assertEqual(smart["outcomes"], {"feed_pages": "no_paging", "api": "no_api", "sitemap": "no_sitemap",
                                             "listing": "listing_unread"})
        self.assertTrue(smart["tried_all"])
        self.assertFalse(smart["found_more"])
        self.assertEqual(plan.available_posts, 3)
        [page] = archive(k, source(f"{site}/feed.xml"))
        self.assertIsNone(page.checkpoint)

    def test_a_stored_post_is_not_read_again(self):
        fixture = hugo_listing()
        http = FakeHttp(fixture.responses)
        k = kind(http, stored={fixture.posts[5]})
        pages = archive(k, fixture.source())
        self.assertNotIn(fixture.posts[5], http.requests)
        self.assertNotIn(fixture.posts[5], stored_urls(pages))

    def test_a_resumed_listing_continues_where_it_stopped(self):
        fixture = hugo_listing()
        k = kind(FakeHttp(fixture.responses))
        pages = archive(k, fixture.source())
        middle = next(p.checkpoint for p in pages if p.checkpoint and p.checkpoint.get("mode") == "listing"
                      and p.checkpoint.get("next_index") == 2)
        self.assertTrue(k.checkpoint_resumable(middle))
        http = FakeHttp(fixture.responses)
        rest = archive(kind(http), fixture.source(), middle)
        self.assertNotIn(fixture.feed, http.requests)
        self.assertEqual(stored_urls(rest), fixture.posts[5:])

    def test_a_feed_pages_resume(self):
        fixture = rfc5005()
        k = kind(FakeHttp(fixture.responses))
        pages = archive(k, fixture.source())
        http = FakeHttp(fixture.responses)
        rest = archive(kind(http), fixture.source(), pages[1].checkpoint)
        self.assertEqual(stored_urls(rest), fixture.posts[6:])
        self.assertNotIn(fixture.feed, http.requests)
        self.assertFalse(k.checkpoint_resumable(pages[-1].checkpoint), "an ended ladder does not resume")


# ------------------------------------------------------------------------------------------------ order, date, learning


class OrderTests(unittest.TestCase):
    def test_the_default_order(self):
        self.assertEqual(ladder.ordered("unknown", None), ["feed_pages", "api", "sitemap", "listing"])
        self.assertEqual(ladder.ordered("unknown", None, web_archive=True)[-1], "web_archive")

    def test_the_learned_order_puts_what_worked_for_the_platform_first(self):
        learned = {"bearblog": {"listing": 40}, "wordpress": {"api": 300, "sitemap": 20}}
        self.assertEqual(ladder.ordered("bearblog", learned)[0], "listing")
        self.assertEqual(ladder.ordered("wordpress", learned)[:2], ["api", "sitemap"])
        self.assertEqual(ladder.ordered("ghost", learned)[0], "feed_pages", "never another platform's")

    def test_an_archive_records_what_worked(self):
        class Store:
            def __init__(self):
                self.added = []

            def get(self):
                return {}

            def add(self, platform, strategy, posts):
                self.added.append((platform, strategy, posts))

        store = Store()
        fixture = bear_blog()
        k = kind(FakeHttp(fixture.responses), learned=store)
        archive(k, fixture.source())
        self.assertEqual(store.added, [("bearblog", "listing", SITE_POSTS - FEED_POSTS)])
        self.assertEqual(ladder.learned_after({}, "bearblog", "listing", 4), {"bearblog": {"listing": 4}})

    def test_the_ladder_tries_the_learned_strategy_first(self):
        fixture = sitemap_fallback()
        # Both the sitemap and a listing find more; learned says the listing.
        site = "https://wp-sitemap.example"
        fixture.responses[f"{site}/blog/"] = links_page(fixture.posts)

        class Store:
            def get(self):
                return {"unknown": {"listing": 9}}

            def add(self, *args):
                pass

        k = kind(FakeHttp(fixture.responses), learned=Store())
        plan = asyncio.run(k.inspect(fixture.source()))
        self.assertEqual(plan.raw["smart"]["order"][0], "listing")
        self.assertEqual(plan.raw["smart"]["strategy"], "listing")
        pages = archive(k, fixture.source())
        self.assertEqual(sorted(set(stored_urls(pages))), sorted(fixture.posts))
        self.assertEqual(pages[-1].checkpoint["mode"], "listing", "the sitemap left: everything was seen")

    def test_a_feed_archive_can_stop_at_a_date(self):
        from insight_core.services.source_fetch_service import SourceFetchService
        k = kind(FakeHttp())
        self.assertTrue(k.chronological)
        support = SourceFetchService._support(k, {}, lambda profile: None)   # noqa: SLF001
        self.assertTrue(support["until"])

    def test_a_listing_goes_newest_first(self):
        fixture = hugo_listing()
        pages = archive(kind(FakeHttp(fixture.responses)), fixture.source())
        dates = [post["date"] for page in pages[1:] for post in page.posts]
        self.assertEqual(dates, sorted(dates, reverse=True), "a date's stop holds: each page is older")


# ------------------------------------------------------------------------------------------------ coverage


class FakePosts:
    def __init__(self, count):
        self.count = count

    def get_source_post_stats(self, source_id):
        return {"post_count": self.count}


class FakeSources:
    def __init__(self, archive=None):
        self.settings = {"archive": dict(archive or {})}

    def get_source_by_id(self, source_id):
        return {"id": source_id, "handle_or_url": "https://x.example/feed"}

    def get_source_with_settings(self, source_id):
        return {"settings": self.settings}

    def merge_source_settings(self, source_id, settings):
        self.settings["archive"].update(settings["archive"])


class CoverageTests(unittest.TestCase):
    def test_the_states(self):
        self.assertEqual(ladder.coverage_status(0, {"estimate": 10}), "not_archived")
        self.assertEqual(ladder.coverage_status(19, {"estimate": 20, "found_more": True}), "archived", "95%")
        self.assertEqual(ladder.coverage_status(18, {"estimate": 20, "found_more": True}), "partial")
        self.assertEqual(ladder.coverage_status(18, {"estimate": 20, "exhausted": True}), "archived")
        self.assertEqual(ladder.coverage_status(5, {"estimate": None, "tried_all": True, "found_more": False}), "archived")
        self.assertEqual(ladder.reasons({"outcomes": {"sitemap": "no_sitemap", "listing": "more:4", "api": "api_refused:403"}}),
                         {"sitemap": "no_sitemap", "api": "api_refused:403"})

    def write(self, stored, archive, data, mode):
        sources = FakeSources(archive)
        ArchiveMetadataWriter(posts=FakePosts(stored), sources=sources).record("s1", kind(FakeHttp()), data, mode)
        return sources.settings["archive"]

    def test_a_plan_that_finds_more_makes_an_archived_feed_partial(self):
        # The Bear Blog case: "archived" by the feed alone, its archive never run.
        smart = {"platform": "bearblog", "found_more": True, "tried_all": True, "estimate": 34,
                 "outcomes": {"listing": "more:15", "sitemap": "no_sitemap"}}
        archive = self.write(19, {"status": "archived", "last_archived_at": None, "available_posts": 19},
                             {"available_posts": 34, "page_size": 1, "smart": smart}, "plan")
        self.assertEqual(archive["status"], "partial")
        self.assertEqual(archive["smart"]["estimate"], 34)
        # A live fetch keeps it partial: the feed's count no longer says archived.
        self.assertEqual(self.write(19, archive, {"source_type": "generic_rss", "posts_fetched": 3}, "live")["status"], "partial")

    def test_an_archive_that_ran_the_ladder_to_its_end_is_archived(self):
        smart = {"found_more": True, "tried_all": True, "estimate": 40}
        end = {"mode": "listing", "end": True, "ladder": {"order": [], "worked": {"listing": 12}}}
        archive = self.write(30, {"smart": smart}, {"success": True, "checkpoint": end, "available_posts": 40}, "archive")
        self.assertEqual(archive["status"], "archived")
        self.assertTrue(archive["smart"]["exhausted"])
        self.assertEqual(archive["smart"]["worked"], {"listing": 12})

    def test_an_archive_stopped_at_its_date_stays_partial(self):
        smart = {"found_more": True, "tried_all": True, "estimate": 40}
        cp = {"mode": "listing", "end": False, "urls": ["a", "b"], "next_index": 1, "ladder": {"order": []}}
        archive = self.write(30, {"smart": smart}, {"success": True, "checkpoint": cp, "until_reached": "2025-01-01"}, "archive")
        self.assertEqual(archive["status"], "partial")

    def test_a_short_feed_archives_once_its_ladder_found_more(self):
        from insight_core.services.source_fetch_service import SourceFetchService
        k = kind(FakeHttp())
        never = SourceFetchService._support(k, {"archive": {"available_posts": 20}}, lambda p: None)
        none_more = SourceFetchService._support(k, {"archive": {"available_posts": 20, "smart": {"found_more": False}}},
                                                lambda p: None)
        more = SourceFetchService._support(k, {"archive": {"available_posts": 20, "smart": {"found_more": True}}},
                                           lambda p: None)
        self.assertEqual((never["archivable"], none_more["archivable"], more["archivable"]), (False, False, True))

    def test_the_coverage_line(self):
        from insight_core.services.source_fetch_service import coverage_of
        self.assertIsNone(coverage_of({}, 3))
        line = coverage_of({"smart": {"estimate": 34, "platform": "bearblog", "outcomes": {"sitemap": "no_sitemap"}}}, 19)
        self.assertEqual((line["stored"], line["estimate"], line["platform"], line["reasons"]),
                         (19, 34, "bearblog", {"sitemap": "no_sitemap"}))


# ------------------------------------------------------------------------------------------------ the re-run


class RerunTests(unittest.TestCase):
    SOURCES = [
        {"id": "never", "enabled": True, "post_count": 19,
         "settings": {"archive": {"status": "archived", "last_archived_at": None, "available_posts": 19}}},
        {"id": "capped", "enabled": True, "post_count": 21, "settings": {"archive": {"status": "partial", "available_posts": 20}}},
        {"id": "deep", "enabled": True, "post_count": 120,
         "settings": {"archive": {"status": "partial", "available_posts": 400, "last_archived_at": "2026-11-01"}}},
        {"id": "off", "enabled": False, "post_count": 10, "settings": {"archive": {"status": "archived", "available_posts": 10}}},
        {"id": "telegram", "enabled": True, "post_count": 10, "settings": {"archive": {"status": "archived"}}},
        {"id": "done", "enabled": True, "post_count": 10,
         "settings": {"archive": {"status": "archived", "rerun_0143": {"at": "2026-11-10", "outcome": "nothing_more"}}}},
    ]

    def kind_of(self, source):
        return "telegram_mtproto" if source["id"] == "telegram" else "generic_rss"

    def test_the_selection(self):
        chosen = rerun.select(self.SOURCES, self.kind_of)
        self.assertEqual(chosen, [{"id": "never", "why": "never_ran"}, {"id": "capped", "why": "at_feed"}])

    def test_it_plans_queues_marks_and_resumes(self):
        sources = [dict(s, settings={"archive": dict(s["settings"]["archive"])}) for s in self.SOURCES]
        planned, queued, sleeps = [], [], []

        class Service:
            async def plan_archive(self, source_id):
                planned.append(source_id)
                found = source_id == "never"
                return {"smart": {"platform": "bearblog" if found else "unknown", "found_more": found,
                                  "strategy": "listing" if found else None, "requests": 4}}

        def mark(source_id, mark):
            next(s for s in sources if s["id"] == source_id)["settings"]["archive"]["rerun_0143"] = mark

        async def sleep(seconds):
            sleeps.append(seconds)

        job = rerun.Rerun(service=Service(), enqueue=queued.append, sources=lambda: sources, kind_of=self.kind_of,
                          mark=mark, sleep=sleep)
        summary = asyncio.run(job.run())
        self.assertEqual((planned, queued, sleeps), (["never", "capped"], ["never"], [rerun.PLAN_GAP_S]))
        self.assertEqual((summary["selected"], summary["queued"], summary["nothing_more"], summary["plan_requests"]),
                         (3, 1, 2, 8))
        # A later start: nothing to plan; once the queued archive ran and covers the site, it counts as full.
        never = sources[0]["settings"]["archive"]
        never.update(status="archived", last_archived_at="2099-01-01T00:00:00+00:00")
        again = asyncio.run(job.run())
        self.assertEqual(planned, ["never", "capped"])
        self.assertEqual(again["capped_to_full"], 1)

    def test_a_dry_run_requests_nothing(self):
        class Service:
            async def plan_archive(self, source_id):
                raise AssertionError("no plan in a dry run")

        job = rerun.Rerun(service=Service(), enqueue=None, sources=lambda: self.SOURCES, kind_of=self.kind_of, mark=None)
        self.assertEqual(asyncio.run(job.run(dry_run=True)), {"selected": 2, "why": {"never_ran": 1, "at_feed": 1}})

    def test_nothing_on_a_machine_that_must_not_fetch(self):
        import os
        old = os.environ.get("INSIGHT_DISCOVER_READS")
        os.environ["INSIGHT_DISCOVER_READS"] = "0"
        try:
            self.assertIsNone(rerun.rerun_safely("postgresql://nowhere/none"))
        finally:
            if old is None:
                os.environ.pop("INSIGHT_DISCOVER_READS", None)
            else:
                os.environ["INSIGHT_DISCOVER_READS"] = old


# ------------------------------------------------------------------------------------------------ the measure


class FixtureMeasureTests(unittest.TestCase):
    """Per platform: the feed's posts, the site's, what the archive stored, and the strategy that worked."""

    def test_every_platform_archives_its_whole_site(self):
        rows = []
        for make in FIXTURES:
            fixture = make()
            http = FakeHttp(fixture.responses)
            k = kind(http)
            plan = asyncio.run(k.inspect(fixture.source()))
            pages = archive(k, fixture.source())
            got = set(stored_urls(pages))
            right = len(got & set(fixture.posts))
            wrong = len(got - set(fixture.posts))
            rows.append((fixture.name, plan.raw["smart"]["platform"], plan.raw["smart"]["strategy"], FEED_POSTS,
                         len(fixture.posts), right, wrong, len(http.requests)))
        print("\n| Fixture | Platform | Strategy | Feed | Site | Stored | Wrong | Requests |")
        for row in rows:
            print("| " + " | ".join(str(cell) for cell in row) + " |")
        self.assertTrue(all(row[5] == row[4] and row[6] == 0 for row in rows), rows)


# ------------------------------------------------------------------------------------------------ discoveries


class DiscoveriesRouteTests(unittest.TestCase):
    def setUp(self):
        import main
        from insight_core.routers import source_discoveries as route
        from insight_core.tests._asgi import call
        self.call, self.app, self.route = call, main.app, route
        self.asked = []

        def read(source_id):
            self.asked.append(source_id)
            if source_id.startswith("0000"):
                raise LookupError("Source not found")
            return {"source_id": source_id, "sites": [], "originals": [], "entities": [], "followed_from_here": [],
                    "counts": {}, "discover_counted": True}

        class Sources:
            def __init__(self):
                self.merged = []

            def get_source_by_id(self, source_id):
                return None if source_id.startswith("0000") else {"id": source_id}

            def merge_source_settings(self, source_id, settings):
                self.merged.append((source_id, settings))

        self.sources = Sources()
        route.use(read, self.sources)

    def tearDown(self):
        self.route.use(None, None)

    def test_the_discoveries_of_a_source(self):
        sid = str(uuid.uuid4())
        status, _, body = self.call(self.app, "GET", f"/api/sources/{sid}/discoveries")
        self.assertEqual((status, body["source_id"], self.asked), (200, sid, [sid]))
        self.assertEqual(self.call(self.app, "GET", "/api/sources/nope/discoveries")[0], 400)
        self.assertEqual(self.call(self.app, "GET", f"/api/sources/{uuid.UUID(int=1)}/discoveries")[0], 404)

    def test_the_web_archive_switch(self):
        sid = str(uuid.uuid4())
        status, _, body = self.call(self.app, "PUT", f"/api/archive/{sid}/web-archive", json_body={"on": True})
        self.assertEqual((status, body), (200, {"on": True}))
        self.assertEqual(self.sources.merged, [(sid, {"archive": {"web_archive": True}})])


from insight_core.tests._db import db_url, requires_test_db  # noqa: E402


@requires_test_db
class DiscoveriesDbTests(unittest.TestCase):
    """One transaction, rolled back: a source linking two sites Discover lists, one you followed after it."""

    def setUp(self):
        import psycopg
        from insight_core.tests._stories import insert_post, insert_source
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        cur = self.cur
        self.mark = uuid.uuid4().hex[:8]
        followed_site, open_site = f"followed-{self.mark}.example", f"open-{self.mark}.example"
        self.linker = insert_source(cur, "The linker", handle=f"https://linker-{self.mark}.example/feed", followed_days=60)
        linked = [f"https://{followed_site}/a", f"https://{open_site}/b"]
        post = insert_post(cur, self.linker, f"https://linker-{self.mark}.example/post", at=datetime.now(timezone.utc) - timedelta(days=30),
                           links=linked)
        cur.execute("UPDATE posts SET fetched_at = now() - interval '30 days' WHERE id = %s", (post,))   # stored then
        self.followed = insert_source(cur, "Followed later", handle=f"https://{followed_site}/feed")
        from insight_core.utils.discover_rules import address_stamp
        for url, site in zip(linked, (followed_site, open_site)):
            cur.execute("INSERT INTO discover_addresses (url, key, site, platform, article, rules) VALUES (%s, %s, %s, false, true, %s) "
                        "ON CONFLICT (url) DO NOTHING", (url, site, site, address_stamp({})))
        found = [{"key": site, "voices": [["site:a", self.linker], ["site:b", None], ["site:c", None]],
                  "sources": [[self.linker, False]]} for site in (followed_site, open_site)]
        cur.execute("INSERT INTO system_settings (key, value) VALUES ('discover_counts', %s::jsonb) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (json.dumps({"found": found, "platforms": {}}),))
        cur.execute("INSERT INTO story_originals (kind, url, outcome, post_id) VALUES ('collect', %s, 'collected', %s) "
                    "ON CONFLICT DO NOTHING", (linked[1], post))
        self.sites = (followed_site, open_site)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_what_the_source_discovered(self):
        from insight_core.db.repo_source_discoveries import source_discoveries
        found = source_discoveries(self.cur, str(self.linker))
        self.assertEqual([(s["key"], s["state"]) for s in found["sites"]],
                         [(self.sites[0], "followed"), (self.sites[1], "open")], "what you followed first")
        self.assertEqual([f["id"] for f in found["followed_from_here"]], [str(self.followed)])
        self.assertEqual([o["url"] for o in found["originals"]], [f"https://{self.sites[1]}/b"])
        self.assertEqual(found["entities"], [])
        self.assertEqual(found["sites"][1]["articles"], 1)
        with self.assertRaises(LookupError):
            source_discoveries(self.cur, str(uuid.UUID(int=7)))


if __name__ == "__main__":
    unittest.main()
