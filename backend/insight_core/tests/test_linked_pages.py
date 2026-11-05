"""A source's own pages that stored posts link and no stored post is (issue 0084 B, decision 1).

The pure rules (utils/linked_rules.py): which links of a post are to its own publication (the ones
post_links never keeps), and whose page an address is, by the shapes of each source's stored posts
(a Substack's /p/<slug>, a blog's /<year>/<month>/<slug>, a section's /news/<slug>) or, on a
platform, by its account (0065). Then the database function (db/repo_linked.py) over real rows.
Every name is neutral.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg.types.json import Jsonb

from insight_core.db.repo_linked import linked_not_stored
from insight_core.tests._db import db_url, requires_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils.addresses import host_of, site_of
from insight_core.utils.linked_rules import OwnPages, own_links, signature_links


class OwnLinksTests(unittest.TestCase):
    def test_links_to_the_posts_own_publication_absolute_and_relative(self):
        html = ('<p>As I wrote <a href="https://writer.substack.com/p/older-post?utm_source=x">before</a>, and '
                '<a href="/p/another-one">here</a>; elsewhere <a href="https://other.example/a">a</a>.</p>')
        self.assertEqual(own_links(html, "https://writer.substack.com/p/new-post"),
                         ["https://writer.substack.com/p/older-post", "https://writer.substack.com/p/another-one"])

    def test_not_the_post_itself_nor_media_nor_another_publication(self):
        html = ('<a href="https://writer.substack.com/p/new-post">me</a><a href="/img/x.png">i</a>'
                '<a href="https://other.substack.com/p/theirs">them</a><a href="mailto:a@b.c">m</a>')
        self.assertEqual(own_links(html, "https://writer.substack.com/p/new-post"), [])

    def test_www_is_the_same_publication(self):
        self.assertEqual(own_links('<a href="https://blog.example/2020/01/old">x</a>', "https://www.blog.example/2024/05/new"),
                         ["https://blog.example/2020/01/old"])

    def test_escaped_html_is_read_as_the_reader_reads_it(self):
        self.assertEqual(own_links('&lt;a href="/p/old"&gt;x&lt;/a&gt;', "https://writer.substack.com/p/new"),
                         ["https://writer.substack.com/p/old"])

    def test_a_signature_link_in_a_quarter_of_the_posts_is_left_out(self):
        posts = {f"p{n}": ["https://w.example/p/subscribe-page", f"https://w.example/p/old-{n}"] for n in range(8)}
        posts["p0"].append("https://w.example/p/old-1")
        self.assertEqual(signature_links(posts), {"https://w.example/p/subscribe-page"})
        self.assertEqual(signature_links({"a": ["https://w.example/p/x"], "b": ["https://w.example/p/x"]}), set(),
                         "4 posts at least")


def pages(**sources):
    """OwnPages from {source id: (kind, account, [stored post addresses][, the sites it publishes on])};
    by default the site of its first post."""
    return OwnPages({sid: (kind, account, rest[0] if rest else {site_of(host_of(urls[0]))} if urls else set(), urls)
                     for sid, (kind, account, urls, *rest) in sources.items()})


SUB = "https://writer.substack.com"


class OwnerTests(unittest.TestCase):
    def test_a_substacks_own_post_pages(self):
        own = pages(sub=("site", None, [f"{SUB}/p/a", f"{SUB}/p/b", f"{SUB}/p/c"]))
        self.assertEqual(own.owner(f"{SUB}/p/an-older-one"), "sub")
        self.assertIsNone(own.owner(f"{SUB}/about"), "its about page is no post")
        self.assertIsNone(own.owner(f"{SUB}/archive"))
        self.assertIsNone(own.owner(f"{SUB}/"), "nor its front page")
        self.assertIsNone(own.owner(f"{SUB}/p/a/comments"), "a post's comments page has another shape")
        self.assertIsNone(own.owner("https://other.substack.com/p/x"), "another publication")
        self.assertEqual(own.page(f"{SUB}/p/older?r=8tdk6"), ("sub", f"{SUB}/p/older"),
                         "a query its pages don't have is no part of the page")
        self.assertIsNone(own.owner(f"{SUB}/form/apply"), "a form is no post")

    def test_a_blog_by_date_and_one_at_its_root(self):
        own = pages(dated=("site", None, ["https://dated.example/2024/05/one", "https://dated.example/2023/11/two"]),
                    ghost=("site", None, ["https://ghost.example/first-post/", "https://ghost.example/second-post/"]))
        self.assertEqual(own.owner("https://dated.example/2019/01/an-old-one"), "dated")
        self.assertIsNone(own.owner("https://dated.example/tag/essays"))
        self.assertEqual(own.owner("https://ghost.example/an-older-post/"), "ghost")
        for page in ("about", "tag/essays", "author/someone", "page/2", "subscribe"):
            self.assertIsNone(own.owner(f"https://ghost.example/{page}/"), page)

    def test_two_sections_of_one_site_are_two_sources(self):
        own = pages(news=("site", None, ["https://lab.example/news/a", "https://lab.example/news/b"]),
                    research=("site", None, ["https://lab.example/research/c", "https://lab.example/research/d"]))
        self.assertEqual(own.owner("https://lab.example/news/older"), "news")
        self.assertEqual(own.owner("https://lab.example/research/older"), "research")
        self.assertIsNone(own.owner("https://lab.example/careers/x"), "a section no source holds")

    def test_one_shape_held_by_two_sources_of_a_site_is_the_one_with_more_posts(self):
        own = pages(all=("site", None, [f"https://b.example/p/{n}" for n in "abc"]),
                    some=("site", None, ["https://b.example/p/d", "https://b.example/p/e"]))
        self.assertEqual(own.owner("https://b.example/p/older"), "all")

    def test_a_query_is_part_of_the_shape(self):
        own = pages(wp=("site", None, ["https://wp.example/?p=12", "https://wp.example/?p=40"]))
        self.assertEqual(own.owner("https://wp.example/?p=3"), "wp")
        self.assertIsNone(own.owner("https://wp.example/"))

    def test_on_a_platform_the_account_owns_its_posts(self):
        own = pages(acct=("x", "x.com/someone", ["https://x.com/someone/status/1234567890123456789"]),
                    chan=("telegram", "t.me/achannel", ["https://t.me/achannel/10"]),
                    vid=("youtube", "youtube.com/channel/ucabc", ["https://youtube.com/watch?v=abc"]),
                    vid2=("youtube", "youtube.com/channel/ucdef", ["https://youtube.com/watch?v=def"]))
        self.assertEqual(own.owner("https://x.com/someone/status/1111111111111111111"), "acct")
        self.assertIsNone(own.owner("https://x.com/someone"), "a profile is no post")
        self.assertIsNone(own.owner("https://x.com/another/status/1111111111111111111"))
        self.assertEqual(own.owner("https://t.me/achannel/3"), "chan")
        self.assertIsNone(own.owner("https://t.me/achannel/A-FILE-NAME-OF-FOUR-WORDS.md"),
                          "an article-like address under a channel is no post of it")
        self.assertIsNone(own.owner("https://youtube.com/watch?v=xyz"), "a video's address names no channel")

    def test_a_repost_does_not_make_another_accounts_posts_yours(self):
        own = pages(acct=("x", "x.com/someone", [f"https://x.com/other/status/12345678901234567{n}" for n in range(10, 20)]))
        self.assertIsNone(own.owner("https://x.com/other/status/1111111111111111111"))

    def test_a_link_blogs_posts_at_the_pages_it_links_are_not_its_pages(self):
        own = pages(links=("site", None, ["https://links.example/2024/05/a", "https://wiki.example/wiki/A",
                                          "https://wiki.example/wiki/B"], {"links.example"}))
        self.assertIsNone(own.owner("https://wiki.example/wiki/C"))
        self.assertEqual(own.owner("https://links.example/2023/01/b"), "links")

    def test_a_few_pages_at_a_sectioned_sites_root_do_not_make_its_root_pages_posts(self):
        site = "https://lab.example"
        own = pages(news=("site", None, [f"{site}/index/post-{n}" for n in range(20)] + [f"{site}/product-a", f"{site}/product-b"]))
        self.assertEqual(own.owner(f"{site}/index/older"), "news")
        self.assertIsNone(own.owner(f"{site}/careers"))
        root = pages(blog=("site", None, [f"{site}/post-{n}" for n in range(5)] + [f"{site}/docs/a", f"{site}/docs/b"]))
        self.assertEqual(root.owner(f"{site}/an-older-post"), "blog")
        self.assertIsNone(root.owner(f"{site}/pricing"), "a page you look things up in")

    def test_an_aggregator_and_saved_own_nothing(self):
        own = pages(hn=("hn", None, ["https://news.example/item?id=1", "https://news.example/item?id=2"]),
                    saved=("saved", None, ["https://a.example/p/1", "https://a.example/p/2"]))
        self.assertIsNone(own.owner("https://news.example/item?id=3"))
        self.assertIsNone(own.owner("https://a.example/p/3"))


@requires_db
class LinkedNotStoredTests(unittest.TestCase):
    """db/repo_linked.linked_not_stored over rows: one transaction, rolled back."""

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self._clean)
        self.now = datetime.now(timezone.utc)

    def _clean(self):
        self.conn.rollback()
        self.conn.close()

    def source(self, handle, platform="rss"):
        source = insert_source(self.cur, handle=handle, platform=platform)
        self.cur.execute("UPDATE sources SET enabled = true WHERE id = %s", (source,))
        return str(source)

    def post(self, source, url, *, days=0, html=None, links=None, **fields):
        post = insert_post(self.cur, source, url, at=self.now - timedelta(days=days), html=html, links=links)
        for target in links or ():   # the site a kept link is on, as the story job writes it
            self.cur.execute("UPDATE post_links SET target_site = %s WHERE post_id = %s AND target_url = %s",
                             (site_of(host_of(target)), post, target))
        for key, value in fields.items():
            self.cur.execute(f"UPDATE posts SET {key} = %s WHERE id = %s", (value, post))
        return post

    def test_a_substacks_own_older_posts_linked_by_it_and_by_others(self):
        pub = f"https://w{self.mark}.substack.com"
        sub = self.source(f"{pub}/feed")
        other = self.source(f"https://o{self.mark}.example/feed")
        self.post(sub, f"{pub}/p/new", html=f'<p>See <a href="{pub}/p/old-one">this</a> and <a href="/p/stored">that</a>.</p>')
        self.post(sub, f"{pub}/p/stored", days=3, html=f'<p>A referral: <a href="{pub}/p/new?r=abc">x</a></p>')
        self.post(sub, f"{pub}/p/third", days=4, html=f'<a href="{pub}/p/old-one?utm_source=x">again</a>'
                                                     f'<a href="{pub}/about">about</a>')
        self.post(other, f"https://o{self.mark}.example/a", days=1, links=[f"{pub}/p/old-two", f"{pub}/p/new"])
        found = linked_not_stored(self.cur, source_ids=[sub, other])
        self.assertEqual(sorted(found), [sub], "the other source's pages are all stored")
        pages = {page.url: page for page in found[sub]}
        self.assertEqual(sorted(pages), [f"{pub}/p/old-one", f"{pub}/p/old-two"])
        self.assertEqual(pages[f"{pub}/p/old-one"].posts, 2)
        self.assertEqual(pages[f"{pub}/p/old-two"].posts, 1)
        self.assertEqual(pages[f"{pub}/p/old-one"].first_linked_at, self.now - timedelta(days=4))
        self.assertEqual(found[sub][0].url, f"{pub}/p/old-one", "the most linked first")

    def test_a_page_stored_at_another_address_is_stored(self):
        site = f"https://b{self.mark}.example"
        blog = self.source(f"{site}/feed")
        self.post(blog, f"{site}/posts/a", html=f'<a href="{site}/posts/moved">x</a><a href="{site}/posts/canon">y</a>'
                                                 f'<a href="{site}/posts/missing">z</a>')
        self.post(blog, f"{site}/posts/b", days=1)
        self.post(blog, f"https://elsewhere{self.mark}.example/x", metadata=Jsonb({"moved_to": f"{site}/posts/moved"}))
        self.post(blog, f"https://elsewhere{self.mark}.example/y", canonical_url=f"{site}/posts/canon/")
        found = linked_not_stored(self.cur, source_ids=[blog])
        self.assertEqual([page.url for page in found[blog]], [f"{site}/posts/missing"])

    def test_a_signature_link_is_none_and_a_disabled_source_follows_nothing(self):
        site = f"https://s{self.mark}.example"
        blog = self.source(f"{site}/feed")
        for n in range(8):
            self.post(blog, f"{site}/p/post-{n}", days=n, html=f'<a href="{site}/p/the-series-index">series</a>')
        self.assertEqual(linked_not_stored(self.cur, source_ids=[blog]), {})
        self.post(blog, f"{site}/p/post-9", html=f'<a href="{site}/p/an-old-one">x</a>')
        self.assertEqual([p.url for p in linked_not_stored(self.cur, source_ids=[blog])[blog]], [f"{site}/p/an-old-one"])
        self.cur.execute("UPDATE sources SET enabled = false WHERE id = %s", (blog,))
        self.assertEqual(linked_not_stored(self.cur, source_ids=[blog]), {}, "only the sources you follow")

    def test_since_keeps_the_links_of_recent_posts_only(self):
        """What 0114's wanted links reuse: the same set, from posts published since then."""
        pub = f"https://r{self.mark}.substack.com"
        sub = self.source(f"{pub}/feed")
        self.post(sub, f"{pub}/p/new", days=1, html=f'<a href="{pub}/p/recent-link">x</a>')
        self.post(sub, f"{pub}/p/older", days=10, html=f'<a href="{pub}/p/old-link">x</a>')
        found = linked_not_stored(self.cur, source_ids=[sub], since=self.now - timedelta(days=3))
        self.assertEqual([p.url for p in found[sub]], [f"{pub}/p/recent-link"])
        self.assertEqual(len(linked_not_stored(self.cur, source_ids=[sub])[sub]), 2)

    def test_a_followed_accounts_tweet_quoted_by_another_source(self):
        user = f"u{self.mark}"
        acct = self.source(f"https://nitter.local/{user}/rss")
        other = self.source(f"https://o{self.mark}.example/feed")
        self.post(acct, f"https://x.com/{user}/status/1234567890123456789")
        self.post(other, f"https://o{self.mark}.example/a", links=[f"https://x.com/{user}/status/1111111111111111111"])
        found = linked_not_stored(self.cur, source_ids=[acct])
        self.assertEqual([p.url for p in found[acct]], [f"https://x.com/{user}/status/1111111111111111111"])


if __name__ == "__main__":
    unittest.main()
