"""v10.35: a listing of other posts (a tag, category, topic or author archive) is never stored as a post.

Production 2026-11-21: a WordPress blog's archive read its sitemap index's taxonomy files (wp-sitemap-taxonomies-
post_tag-N.xml names "post"), and each tag page, listing one article with its title, opening and date, was stored as
a post duplicating that article (2,594 at one blog on the server's copy). Markup shapes trimmed from WordPress, Ghost,
Hugo and a JSON-LD author page.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.kinds import generic_rss, page_watch
from insight_core.tests._kind_fakes import FakeHttp

SITE = "https://blog.example.org"
BODY = "<p>" + "A botnet of a million TV boxes was taken down by several firms this week. " * 12 + "</p>"
ARTICLE = (f'<html><head><title>Botnet dismantled</title><meta property="article:published_time" '
           f'content="2026-11-03T10:00:00+00:00"><link rel="alternate" type="application/rss+xml" '
           f'title="Blog &raquo; Botnet dismantled Comments Feed" href="{SITE}/2026/11/botnet/feed/"></head>'
           f'<body class="post-template-default single single-post"><article><h1>Botnet dismantled</h1>{BODY}'
           f'</article></body></html>')


def tag_page(body_class: str = "archive tag tag-gaganode", head: str = "") -> str:
    """A tag page listing one article: its title linked, its opening, its date."""
    return (f'<html><head><title>GaGaNode</title>{head}</head><body class="{body_class}"><main>'
            f'<article class="post type-post"><h2><a href="{SITE}/2026/11/botnet/">Botnet dismantled</a></h2>'
            f'<time datetime="2026-11-03T10:00:00+00:00">Nov 3</time>{BODY}</article></main></body></html>')


class ListingAddressTests(unittest.TestCase):
    def test_a_taxonomy_word_before_the_last_segment_is_a_listing(self):
        for url in (f"{SITE}/tag/gaganode/", f"{SITE}/blog/tags/usb/", f"{SITE}/category/podcast-2/",
                    f"{SITE}/blog/author/ben-kelley", f"{SITE}/topics/ai"):
            self.assertTrue(page_watch.listing_address(url), url)

    def test_an_article_is_not_and_the_sources_own_section_stays_its_articles(self):
        self.assertFalse(page_watch.listing_address(f"{SITE}/2026/11/botnet/"))
        self.assertFalse(page_watch.listing_address(f"{SITE}/tag-team-wins/"))
        # a watched /topics/ section: its /topics/<slug> pages are its articles
        self.assertFalse(page_watch.listing_address(f"{SITE}/topics/how-we-build", "/topics/"))


class ListingMarkupTests(unittest.TestCase):
    def test_wordpress_ghost_jsonld_and_an_own_feed_say_listing(self):
        url = f"{SITE}/tag/gaganode/"
        self.assertTrue(page_watch.listing_markup(tag_page(), url))
        self.assertTrue(page_watch.listing_markup(tag_page("tag-template tag-gaganode"), url))
        self.assertTrue(page_watch.listing_markup(
            tag_page("", '<script type="application/ld+json">{"@type": "CollectionPage"}</script>'), url))
        self.assertTrue(page_watch.listing_markup(
            tag_page("list", f'<link rel="alternate" type="application/rss+xml" href="{url}index.xml">'), url))

    def test_an_article_with_its_comments_feed_is_no_listing(self):
        self.assertFalse(page_watch.listing_markup(ARTICLE, f"{SITE}/2026/11/botnet/"))
        self.assertFalse(page_watch.listing_markup(
            ARTICLE.replace("Comments Feed", "Feed").replace(f"{SITE}/2026/11/botnet/feed/", f"{SITE}/feed/"),
            f"{SITE}/2026/11/botnet/"))

    def test_post_from_refuses_a_listing_and_keeps_the_article(self):
        self.assertIsNone(page_watch.post_from(tag_page(), SITE, f"{SITE}/tag/gaganode/", None))
        post = page_watch.post_from(ARTICLE, SITE, f"{SITE}/2026/11/botnet/", None)
        self.assertIsNotNone(post)
        self.assertEqual(post["title"], "Botnet dismantled")


class SitemapTests(unittest.TestCase):
    def test_an_archive_never_reads_the_taxonomy_or_users_files(self):
        index = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 + "".join(f"<sitemap><loc>{SITE}/{name}</loc></sitemap>" for name in (
                     "wp-sitemap-posts-post-1.xml", "wp-sitemap-taxonomies-post_tag-1.xml",
                     "wp-sitemap-taxonomies-category-1.xml", "wp-sitemap-users-1.xml"))
                 + "</sitemapindex>")

        def urlset(*locs):
            return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + "".join(f"<url><loc>{loc}</loc></url>" for loc in locs) + "</urlset>")

        http = FakeHttp({
            f"{SITE}/robots.txt": f"Sitemap: {SITE}/sitemap.xml",
            f"{SITE}/sitemap.xml": index,
            f"{SITE}/wp-sitemap-posts-post-1.xml": urlset(f"{SITE}/2026/11/botnet/"),
            f"{SITE}/wp-sitemap-taxonomies-post_tag-1.xml": urlset(f"{SITE}/tag/gaganode/"),
            f"{SITE}/wp-sitemap-taxonomies-category-1.xml": urlset(f"{SITE}/category/news/"),
            f"{SITE}/wp-sitemap-users-1.xml": urlset(f"{SITE}/author/brian/"),
        })
        entries = asyncio.run(page_watch.sitemap_entries(http, SITE + "/", "/", posts_only=True, max_files=60))
        self.assertEqual([loc for loc, _ in entries], [f"{SITE}/2026/11/botnet/"])
        asked = [getattr(call, "url", call) for call in getattr(http, "requests", [])]
        self.assertFalse(any("taxonomies" in str(url) or "users" in str(url) for url in asked), asked)

    def test_the_archives_section_leaves_listing_addresses_out(self):
        entries = [(f"{SITE}/2026/11/botnet/", "2026-11-03"), (f"{SITE}/tag/gaganode/", "2026-11-03"),
                   (f"{SITE}/author/brian/", None)]
        found = generic_rss._under_section(entries, SITE, "/")
        self.assertEqual([loc for loc, _ in found], [f"{SITE}/2026/11/botnet/"])
        self.assertEqual(found[0][1], datetime(2026, 11, 3, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
