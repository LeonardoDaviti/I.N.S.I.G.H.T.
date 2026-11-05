"""A blog that moved (issue 0108): a post page that is a redirect stub is read at the address it
points to, once, and the post is one page with the post stored there.

Fixtures are written from the shapes measured on a real moved site (a Jekyll site whose posts are
574-byte stubs: a meta refresh, a canonical link and a `location=` script, all to the same article on
the blog's new domain); every name here is neutral. No network: FakeHttp. The store tests commit rows,
so they run only against a *_test database (@requires_test_db).
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import FULL_TEXT_FLAG, MOVED_KEY, PostsRepository
from insight_core.ingestion import full_text
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests._stories import story_post
from insight_core.utils.story_rules import grouping, keys, page_aliases

AT = datetime(2020, 10, 30, 7, tzinfo=timezone.utc)
OLD_FEED = "https://home.example/feed.xml"
OLD = "https://home.example/posts/2020/10/old-slug"
NEW = "https://www.blog.example/the-new-slug-of-the-post/"
NEW_NORMALIZED = "https://blog.example/the-new-slug-of-the-post"
ESSAY = "A paragraph of the essay as the blog keeps it, sentence after sentence. " * 30


def stub(target: str = NEW, *, refresh: bool = True, canonical: bool = True, script: bool = True) -> str:
    """A redirect stub as the measured site writes it (each of its three pointers optional)."""
    head = (f'<link rel="canonical" href="{target}"/>' if canonical else "") + \
        '<meta http-equiv="content-type" content="text/html; charset=utf-8" />' + \
        (f'<meta http-equiv="refresh" content="0;url={target}" />' if refresh else "")
    body = (f'<h1>Redirecting...</h1><a href="{target}">Click here if you are not redirected.<a>'
            + (f"<script>location='{target}'</script>" if script else ""))
    return f"<!DOCTYPE html><html><head>{head}</head><body>{body}</body></html>"


def blog_post(text: str = ESSAY) -> str:
    """The article on the blog's new domain (a Ghost-shaped post page)."""
    return ('<html><head><meta property="og:type" content="article">'
            '<meta property="article:published_time" content="2020-10-30T08:00:00.000Z"></head>'
            f'<body><header><nav><a href="/">Home</a></nav></header><article class="post"><h1>The post</h1>'
            f"<p>{text}</p></article><footer>Footer</footer></body></html>")


def empty_feed(*links: str) -> str:
    """A Jekyll Atom feed whose entries carry no body (empty content and summary)."""
    entries = "".join(
        f'<entry><title type="html">Post {n}</title><link href="{link}" rel="alternate" type="text/html"/>'
        f"<published>2020-10-30T00:00:00-07:00</published><id>{link}</id>"
        f'<content type="html" xml:base="{link}"><![CDATA[]]></content><summary type="html"><![CDATA[]]></summary></entry>'
        for n, link in enumerate(links))
    return (f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
            f'<link href="{OLD_FEED}" rel="self"/><title type="html">Home</title>{entries}</feed>')


def _src() -> dict:
    return {"id": "s-old", "platform": "rss", "handle_or_url": OLD_FEED, "settings": {}}


class PageMovedToTests(unittest.TestCase):
    """parsing.moved_to: where a page says it now is."""

    def test_a_meta_refresh_names_the_page(self):
        self.assertEqual(parsing.moved_to(stub(canonical=False), OLD), NEW)

    def test_a_canonical_link_to_another_address_names_it(self):
        self.assertEqual(parsing.moved_to(stub(refresh=False), OLD), NEW)

    def test_a_relative_refresh_is_read_against_the_page(self):
        self.assertEqual(parsing.moved_to(stub("/elsewhere/", canonical=False), OLD), "https://home.example/elsewhere/")

    def test_a_script_alone_names_nothing(self):
        self.assertIsNone(parsing.moved_to(stub(refresh=False, canonical=False), OLD))

    def test_a_canonical_to_the_page_itself_names_nothing(self):
        self.assertIsNone(parsing.moved_to(stub(OLD + "/", refresh=False), OLD))
        self.assertIsNone(parsing.moved_to(stub(OLD.replace("https:", "http:"), refresh=False), OLD))

    def test_a_refresh_without_an_address_names_nothing(self):
        page = '<html><head><meta http-equiv="refresh" content="300"></head><body>Live</body></html>'
        self.assertIsNone(parsing.moved_to(page, OLD))


class ReadArticleFollowsAStubTests(unittest.IsolatedAsyncioTestCase):
    """full_text.read_article: a tiny page that points elsewhere is read there, one hop."""

    async def test_a_meta_refresh_stub_is_read_at_its_target(self):
        http = FakeHttp({OLD: stub(), NEW: blog_post()})
        html, text, _, date, moved = await full_text.read_article(http, OLD, "")
        self.assertIn("A paragraph of the essay", text)
        self.assertEqual(moved, NEW)
        self.assertEqual(date, datetime(2020, 10, 30, 8, tzinfo=timezone.utc))
        self.assertEqual(http.requests, [OLD, NEW])

    async def test_a_canonical_only_stub_is_read_at_its_target(self):
        http = FakeHttp({OLD: stub(refresh=False, script=False), NEW: blog_post()})
        *_, moved = await full_text.read_article(http, OLD, "")
        self.assertEqual(moved, NEW)

    async def test_a_script_only_stub_is_not_followed(self):
        http = FakeHttp({OLD: stub(refresh=False, canonical=False), NEW: blog_post()})
        self.assertIsNone(await full_text.read_article(http, OLD, ""))
        self.assertEqual(http.requests, [OLD])

    async def test_a_full_page_with_a_canonical_elsewhere_is_read_itself(self):
        page = (f'<html><head><link rel="canonical" href="{NEW}"></head><body><article><p>{ESSAY}</p>'
                "</article></body></html>")
        http = FakeHttp({OLD: page, NEW: blog_post("Another text entirely. " * 80)})
        *_, moved = await full_text.read_article(http, OLD, "")
        self.assertIsNone(moved)
        self.assertEqual(http.requests, [OLD])

    async def test_one_hop_only(self):
        further = "https://third.example/again"
        http = FakeHttp({OLD: stub(), NEW: stub(further), further: blog_post()})
        self.assertIsNone(await full_text.read_article(http, OLD, ""))
        self.assertEqual(http.requests, [OLD, NEW])

    def test_the_post_keeps_its_address_and_records_where_it_moved(self):
        post = full_text.with_full_text({"url": OLD, "metadata": {}}, "<p>x</p>", "x", None, None, NEW)
        self.assertEqual(post["url"], OLD)
        self.assertEqual(post["canonical_url"], NEW)
        self.assertEqual(post["metadata"][MOVED_KEY], NEW_NORMALIZED)
        self.assertNotIn("canonical_url", full_text.with_full_text({"url": OLD}, "<p>x</p>", "x"))

    async def test_a_feed_of_empty_entries_is_read_at_the_moved_pages(self):
        http = FakeHttp({OLD_FEED: empty_feed(OLD), OLD: stub(), NEW: blog_post()})
        [post] = await GenericRssKind(http, stored_urls=lambda urls: set()).fetch_latest(_src(), 10)
        self.assertEqual(post["url"], OLD)
        self.assertIn("A paragraph of the essay", post["content"])
        self.assertTrue(post["metadata"][FULL_TEXT_FLAG])
        self.assertEqual(post["metadata"][MOVED_KEY], NEW_NORMALIZED)


class OnePageTests(unittest.TestCase):
    """The story rules: a post that moved is one page with the post at its new address."""

    def _posts(self):
        old = story_post("old", "s-old", at=AT, site="home.example", url=OLD, moved_to=NEW_NORMALIZED)
        new = story_post("new", "s-new", at=AT, hours=1, site="blog.example", url=NEW_NORMALIZED)
        return old, new

    def test_the_old_address_is_an_alias_of_the_new_one(self):
        self.assertEqual(page_aliases(self._posts()), {OLD: NEW_NORMALIZED})

    def test_the_two_posts_are_one_story(self):
        found = grouping(self._posts())
        [story] = found.stories
        self.assertEqual(sorted(p.id for p in story.posts), ["new", "old"])
        self.assertIn("address", {edge.kind for edge in found.edges})

    def test_a_link_to_the_old_address_is_a_link_to_the_new_post(self):
        old, new = self._posts()
        linker = story_post("l", "s-link", at=AT, hours=2, site="links.example", url="https://links.example/notes/today",
                            links=[(OLD, "old")])
        found = grouping([old, new, linker])
        self.assertEqual(len(found.stories), 1)
        self.assertEqual(sorted(p.id for p in found.stories[0].posts), ["l", "new", "old"])

    def test_the_moved_post_holds_its_new_address_as_a_key(self):
        old, _ = self._posts()
        self.assertIn("u:" + NEW_NORMALIZED, keys(old))

    def test_a_post_that_did_not_move_is_unchanged(self):
        plain = story_post("p", "s-old", at=AT, site="home.example", url=OLD)
        self.assertEqual(page_aliases([plain]), {})


@requires_test_db
class MovedStoreTests(unittest.TestCase):
    """The saver: the post keeps its address; its canonical is where it moved, kept on a re-fetch."""

    def setUp(self):
        self.url = db_url()
        self.repo = PostsRepository(self.url)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _upsert(self, post: dict) -> str:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            post_id, _ = self.repo.upsert_post(cur, {"title": "Post 0", "date": AT, "media_urls": [], "categories": [],
                                                     **post}, self.source_id)
            conn.commit()
        return post_id

    def _row(self, post_id: str) -> tuple:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT url, normalized_url, canonical_url, metadata ->> %s, length(content) FROM posts WHERE id = %s",
                        (MOVED_KEY, post_id))
            return cur.fetchone()

    def test_a_moved_post_is_stored_at_its_address_with_its_canonical(self):
        read = full_text.with_full_text({"url": OLD, "content": "", "metadata": {}}, f"<p>{ESSAY}</p>", ESSAY, None, None, NEW)
        post_id = self._upsert(read)
        self.assertEqual(self._row(post_id), (OLD, OLD, NEW_NORMALIZED, NEW_NORMALIZED, len(ESSAY)))
        # The feed brings its empty entry again: the body, the canonical and the move stay.
        self._upsert({"url": OLD, "content": "", "metadata": {}})
        self.assertEqual(self._row(post_id), (OLD, OLD, NEW_NORMALIZED, NEW_NORMALIZED, len(ESSAY)))

    def test_the_repair_writes_where_a_stored_post_moved(self):
        post_id = self._upsert({"url": OLD, "content": "", "metadata": {}})
        found = full_text.with_full_text({}, f"<p>{ESSAY}</p>", ESSAY, None, None, NEW)
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            self.repo.save_full_text(cur, post_id, found)
            conn.commit()
        self.assertEqual(self._row(post_id), (OLD, OLD, NEW_NORMALIZED, NEW_NORMALIZED, len(ESSAY)))

    def test_the_story_job_reads_where_a_post_moved(self):
        from insight_core.db.repo_stories import SourceFacts, StoriesRepository
        from insight_core.services.stories_service import StoriesService
        read = full_text.with_full_text({"url": OLD, "content": "", "metadata": {}}, f"<p>{ESSAY}</p>", ESSAY, None, None, NEW)
        post_id = self._upsert(read)
        plain = self._upsert({"url": "https://home.example/posts/2020/11/plain", "content": "Body.", "metadata": {}})
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            sources = SourceFacts(cur)
            rows = StoriesRepository.load_posts(cur, sources, [post_id, plain])
            posts = {p.id: p for p in (StoriesService._story_post(row, sources) for row in rows)}
        self.assertEqual(posts[str(post_id)].moved_to, NEW_NORMALIZED)
        self.assertIsNone(posts[str(plain)].moved_to)


if __name__ == "__main__":
    unittest.main()
