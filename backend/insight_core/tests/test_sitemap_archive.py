"""A feed source's archive reads the site's sitemap of posts (issue 0108, decision 5): a blog whose
feed holds its latest posts and whose sitemap lists them all. Fixtures are written from a Ghost blog's
measured shapes (robots.txt naming a sitemap index; the index's pages, posts, authors and tags files;
the posts file listing every post); every name here is neutral. No network: FakeHttp.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import BACKLOG_KEY
from insight_core.ingestion.kinds.base import RateLimit
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.tests._kind_fakes import FakeHttp

BLOG = "https://www.blog.example"
FEED = f"{BLOG}/rss/"
RATE = RateLimit(page_delay_s=0, batch_size=0, batch_cooldown_s=0)


def post_url(slug: str) -> str:
    return f"{BLOG}/{slug}/"


IN_FEED = ("newest-post", "second-post")
OLDER = ("third-post", "oldest-post")


def rss(*slugs: str) -> str:
    items = "".join(
        f"<item><title>{slug}</title><link>{post_url(slug)}</link><guid isPermaLink=\"false\">{n}</guid>"
        f"<pubDate>Mon, 0{n + 1} Mar 2021 00:00:00 GMT</pubDate>"
        f"<description>A summary.</description><content:encoded><![CDATA[<p>{'All of it. ' * 200}</p>]]></content:encoded></item>"
        for n, slug in enumerate(slugs))
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel><title>The Blog</title>{items}</channel></rss>")


def urlset(*locs: tuple[str, str]) -> str:
    entries = "".join(f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>" for loc, lastmod in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'


def index(*children: str) -> str:
    entries = "".join(f"<sitemap><loc>{BLOG}/{child}</loc></sitemap>" for child in children)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</sitemapindex>'


def article(slug: str, published: str) -> str:
    return (f'<html><head><title>{slug} - The Blog</title><meta property="og:type" content="article">'
            f'<meta property="og:site_name" content="The Blog"><meta property="og:title" content="{slug}">'
            f'<meta property="article:published_time" content="{published}"></head><body><article>'
            f"<p>{'What the older post says, at length. ' * 40}</p></article></body></html>")


def blog(**more) -> dict:
    """The blog: its feed of the latest two posts, robots.txt naming an index whose posts file lists
    all four, and the older posts' pages."""
    return {
        FEED: rss(*IN_FEED),
        f"{BLOG}/robots.txt": f"User-agent: *\nSitemap: {BLOG}/sitemap.xml\nDisallow: /ghost/\n",
        f"{BLOG}/sitemap.xml": index("sitemap-pages.xml", "sitemap-posts.xml", "sitemap-authors.xml", "sitemap-tags.xml"),
        f"{BLOG}/sitemap-posts.xml": urlset(*((post_url(slug), f"2022-01-{17 - n:02d}T19:00:00.000Z")
                                             for n, slug in enumerate(IN_FEED + OLDER))),
        f"{BLOG}/sitemap-pages.xml": urlset((f"{BLOG}/about/", "2022-01-01T00:00:00.000Z")),
        f"{BLOG}/sitemap-tags.xml": urlset((f"{BLOG}/tag/essays/", "2022-01-01T00:00:00.000Z")),
        post_url("third-post"): article("third-post", "2020-06-01T00:00:00.000Z"),
        post_url("oldest-post"): article("oldest-post", "2017-03-22T00:00:00.000Z"),
        **more,
    }


def source() -> dict:
    return {"id": "s-blog", "platform": "rss", "handle_or_url": FEED, "settings": {}}


def kind(http: FakeHttp, stored: set | None = None) -> GenericRssKind:
    return GenericRssKind(http, stored_urls=lambda urls: {u for u in urls if u.rstrip("/") in {s.rstrip("/") for s in stored or ()}})


async def archive(k: GenericRssKind, checkpoint: dict | None = None, target: int = 100) -> list:
    return [page async for page in k.archive_pages(source(), target, checkpoint, RATE)]


class SitemapArchiveTests(unittest.TestCase):
    def test_inspect_counts_the_sitemaps_older_posts(self):
        http = FakeHttp(blog())
        found = asyncio.run(kind(http).inspect(source()))
        self.assertEqual(found.available_posts, 4)
        self.assertEqual(found.raw.get("sitemap_posts"), 2)
        self.assertIn(f"{BLOG}/sitemap-posts.xml", http.requests)
        self.assertNotIn(f"{BLOG}/sitemap-tags.xml", http.requests, "an index's post sitemap only")
        self.assertNotIn(f"{BLOG}/sitemap-pages.xml", http.requests)

    def test_the_archive_reads_the_feed_then_each_older_post_one_page_each(self):
        http = FakeHttp(blog())
        pages = asyncio.run(archive(kind(http)))
        self.assertEqual([len(page.posts) for page in pages], [2, 1, 1])
        third, oldest = pages[1].posts[0], pages[2].posts[0]
        self.assertEqual((third["url"], third["title"]), (post_url("third-post"), "third-post"))
        self.assertEqual(oldest["date"].year, 2017, "the page's own date, not the sitemap's lastmod")
        self.assertIn("What the older post says", oldest["content"])
        self.assertTrue(third[BACKLOG_KEY], "from the sitemap: never new to you")
        # An index into the sitemap's four posts, newest first: the feed's two are skipped, not read.
        self.assertEqual([(p.checkpoint or {}).get("next_index") for p in pages], [0, 3, 4])
        self.assertEqual({(p.checkpoint or {}).get("mode") for p in pages}, {"sitemap"})

    def test_a_resumed_archive_continues_in_the_sitemap(self):
        http = FakeHttp(blog())
        k = kind(http)
        checkpoint = {"mode": "sitemap", "site": BLOG, "prefix": "/", "next_index": 3, "pages_fetched": 2,
                      "collected_posts": 3, "total_candidates": 4}
        self.assertTrue(k.checkpoint_resumable(checkpoint))
        pages = asyncio.run(archive(k, checkpoint))
        self.assertEqual([page.posts[0]["url"] for page in pages], [post_url("oldest-post")])
        self.assertNotIn(FEED, http.requests)
        self.assertNotIn(post_url("third-post"), http.requests)

    def test_a_finished_or_foreign_checkpoint_does_not_resume(self):
        k = kind(FakeHttp())
        self.assertFalse(k.checkpoint_resumable({"mode": "sitemap", "next_index": 4, "total_candidates": 4}))
        self.assertFalse(k.checkpoint_resumable({"mode": "generic_rss", "pages_fetched": 1}))

    def test_a_stored_older_post_is_not_read_again(self):
        http = FakeHttp(blog())
        pages = asyncio.run(archive(kind(http, stored={post_url("third-post")})))
        self.assertNotIn(post_url("third-post"), http.requests)
        self.assertEqual([post["url"] for page in pages for post in page.posts][-1:], [post_url("oldest-post")])

    def test_a_sitemap_page_that_is_no_post_is_skipped(self):
        responses = blog()
        responses[post_url("third-post")] = '<html><head><meta property="og:type" content="website"></head><body><p>Tags</p></body></html>'
        pages = asyncio.run(archive(kind(FakeHttp(responses))))
        self.assertEqual([len(page.posts) for page in pages], [2, 0, 1])

    def test_a_feed_holding_the_whole_sitemap_archives_as_before(self):
        responses = blog()
        responses[FEED] = rss(*IN_FEED, *OLDER)
        http = FakeHttp(responses)
        self.assertEqual(asyncio.run(kind(http).inspect(source())).available_posts, 4)
        [page] = asyncio.run(archive(kind(http)))
        self.assertEqual((len(page.posts), page.checkpoint), (4, None))

    def test_no_sitemap_archives_as_before(self):
        http = FakeHttp({FEED: rss(*IN_FEED)})
        found = asyncio.run(kind(http).inspect(source()))
        self.assertEqual(found.available_posts, 2)
        [page] = asyncio.run(archive(kind(http)))
        self.assertEqual((len(page.posts), page.checkpoint), (2, None))

    def test_only_the_feeds_section_of_a_plain_sitemap_counts(self):
        # A site's single sitemap (no index, no robots.txt) of its posts and its other pages.
        section = "https://words.example/posts"
        feed = "https://words.example/feed.xml"
        responses = {
            feed: rss().replace("<channel><title>The Blog</title>", "<channel><title>Words</title>"
                                f"<item><title>a</title><link>{section}/2021/03/a</link><description>{'x' * 50}</description></item>"
                                f"<item><title>b</title><link>{section}/2020/12/b</link><description>{'x' * 50}</description></item>"),
            "https://words.example/sitemap.xml": urlset((f"{section}/2021/03/a", "2021-03-01"), (f"{section}/2020/12/b", "2020-12-01"),
                                                        (f"{section}/2019/01/c", "2019-01-01"), ("https://words.example/about", "2024-01-01"),
                                                        ("https://words.example/cv", "2024-01-01")),
        }
        found = asyncio.run(GenericRssKind(FakeHttp(responses)).inspect({**source(), "handle_or_url": feed}))
        self.assertEqual(found.available_posts, 3)

    def test_a_feeds_section_is_the_folder_its_items_share(self):
        from insight_core.ingestion.kinds.generic_rss import feed_section
        self.assertEqual(feed_section(["https://w.example/posts/2021/03/a", "https://w.example/posts/2020/12/b"]), "/posts/")
        self.assertEqual(feed_section(["https://w.example/posts/2020/10/a"]), "/posts/")
        self.assertEqual(feed_section(["https://w.example/a/", "https://w.example/b/"]), "/")
        self.assertEqual(feed_section(["https://w.example/blog/a", "https://w.example/blog/b"]), "/blog/")


if __name__ == "__main__":
    unittest.main()
