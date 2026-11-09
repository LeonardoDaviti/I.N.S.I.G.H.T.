"""Issue 0140: teasers read in full. Every read leaves a reason; a same-article test that works; a feed's
read-more cut; pages that need scripts (their embedded data); the repair once per rule version; the reader's line.

No network: FakeHttp. Fixtures are hand-written in the shape of the classes measured on the server (no real
site or name): a project blog whose feed gives a written abstract, a tech site's "all posts" feed cut before
"read more", a Next.js page, a page with JSON-LD articleBody, a script-built page with no data, and the pages
that must NOT be taken (a link post's page, another article, a sign-in wall, a related post in the data).
The FIXTURES table is the measure: right / wrong per class (plan/issues/0140-built.md).
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

from insight_core.db.repo_posts import (FULL_TEXT_FLAG, FULL_TEXT_RULE_KEY, PAGE_OUTCOME_KEY, PAGE_TRIES_KEY,
                                        PostsRepository)
from insight_core.ingestion import full_text
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import KindRegistry, embedded_article
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.scripts import repair_full_text
from insight_core.scripts.repair_full_text import Repair
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp

SITE = "https://blog.example.org"
FEED = f"{SITE}/feed.xml"
NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
RSITE = "https://test.invalid"   # the scratch sources' site (tests/_db.SCRATCH_PREFIX)

TITLE = "Serving a sparse model with wide expert parallelism"
ARTICLE_PARAGRAPHS = [
    "We start with the deployment we run in production today, on two nodes of eight accelerators each.",
    "The prefill stage and the decode stage live on separate machines, joined by a fast interconnect.",
    "Experts are spread across every device of the decode nodes, so each token visits a few of them.",
    "Batching across requests is what keeps the experts busy; without it most of them would sit idle.",
    "We measured throughput at several batch sizes and report the knee of the curve below.",
    "The cache for attention is paged, which lets long and short requests share the same pool.",
    "Finally we list what did not work, and the settings we would choose for a new deployment.",
]
ARTICLE_PARAGRAPHS = [f"{p[:-1]} (round {n // 7 + 1})." for n, p in enumerate(ARTICLE_PARAGRAPHS * 3)]
ARTICLE_HTML = "".join(f"<p>{p}</p>" for p in ARTICLE_PARAGRAPHS)
ARTICLE_TEXT = " ".join(ARTICLE_PARAGRAPHS)
# A written abstract: not the article's opening, and none of its sentences.
ABSTRACT = ("This post explains how a sparse mixture-of-experts model is served across many devices at once, "
            "why the two stages of inference are split, and which numbers matter when you size a cluster for it, "
            "in tokens per second.")


def page(body: str, *, title: str = TITLE, head: str = "", canonical: str | None = None) -> str:
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return (f"<html><head><title>{title} | Example Blog</title>{link}{head}</head>"
            f"<body><nav><a href='/'>Home</a></nav>{body}<footer><p>Footer</p></footer></body></html>")


def article_page(url: str, *, title: str = TITLE, opening: str = "", canonical: bool = True) -> str:
    return page(f"<article><h1>{title}</h1>{opening}{ARTICLE_HTML}</article>", title=title,
                canonical=url if canonical else None)


def feed(*items: tuple[str, str, str]) -> str:
    body = "".join(f"<item><title>{title}</title><link>{link}</link><description><![CDATA[{text}]]></description>"
                   f"<pubDate>Mon, 09 Nov 2026 10:00:00 GMT</pubDate></item>" for link, title, text in items)
    return f'<rss version="2.0"><channel>{body}</channel></rss>'


def source(address: str = FEED) -> dict:
    return {"id": "s1", "platform": "rss", "handle_or_url": address, "settings": {}}


def next_data(post: dict, related: list | None = None) -> str:
    data = {"props": {"pageProps": {"post": post, "related": related or []}}, "page": "/blog/[slug]"}
    return (f'<html><head><title>{post.get("title", "Blog")}</title></head><body><div id="__next"></div>'
            f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>')


MARKDOWN = "\n\n".join(["## Setup"] + ARTICLE_PARAGRAPHS)
OTHER_MARKDOWN = "\n\n".join(f"Another post entirely, paragraph {n}, about a database migration we ran last spring."
                             for n in range(20))


async def read(url: str, body: str, answer, *, title: str = TITLE, site: str = FEED) -> full_text.PageRead:
    http = FakeHttp({url: answer})
    return await full_text.read_page(http, url, body, title=title, site=site)


# --------------------------------------------------------------------------- the measure: one row per fixture

def _cut_body(url: str) -> str:
    """A tech site's "all posts" feed: an image's caption, the text before the cut, a read-more link to the post."""
    before = "".join(f"<p>{p}</p>" for p in ARTICLE_PARAGRAPHS[:16])
    return f'<p><img src="{SITE}/lead.png">A picture of the rack.</p>{before}<a href="{url}#cut">Read further</a>'


FIXTURES = [
    # (class, the post's address, its title, its feed body, the page, the outcome wanted)
    ("abstract, page titled as the post", f"{SITE}/2026/sparse", TITLE, ABSTRACT,
     article_page(f"{SITE}/2026/sparse", canonical=False), full_text.FULL),
    ("abstract, page names the post's address", f"{SITE}/2026/addr", "Notes", ABSTRACT,
     article_page(f"{SITE}/2026/addr", title="Notes"), full_text.FULL),
    ("read-more cut, opening changed", f"{SITE}/2026/cut", "A long post cut by its feed", _cut_body(f"{SITE}/2026/cut"),
     page(f"<article><h1>Other words</h1>{ARTICLE_HTML}<p>{'More of the article after the cut. ' * 40}</p></article>",
          title="Other words"), full_text.FULL),
    ("Next.js __NEXT_DATA__", f"{SITE}/blog/next", TITLE, ABSTRACT,
     next_data({"title": TITLE, "content": MARKDOWN}, [{"title": "A related post", "excerpt": "short"}]), full_text.FULL),
    ("JSON-LD articleBody", f"{SITE}/news/ld", TITLE, ABSTRACT,
     page('<div id="root"></div>', head='<script type="application/ld+json">'
          + json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "headline": TITLE,
                        "articleBody": "\n".join(ARTICLE_PARAGRAPHS)}) + "</script>"), full_text.FULL),
    # Wrong must be 0: these pages are not the post's article.
    ("link post: the linked page's title and address", "https://elsewhere.example.net/story", TITLE, ABSTRACT,
     article_page("https://elsewhere.example.net/story"), full_text.NOT_SAME_ARTICLE),
    ("another article on the site", f"{SITE}/2026/moved", TITLE, ABSTRACT,
     article_page(f"{SITE}/2026/other", title="A different post about databases", canonical=True),
     full_text.NOT_SAME_ARTICLE),
    ("a sign-in wall", f"{SITE}/2026/wall", TITLE, ABSTRACT,
     page("<main>" + "<p>Sign in to keep reading. Our terms of service and privacy policy apply to every account.</p>" * 12
          + "</main>", title="Sign in"), full_text.NOT_SAME_ARTICLE),
    ("Next.js data holding only another post", f"{SITE}/blog/rel", TITLE, ABSTRACT,
     next_data({"title": "Blog", "related": None}, [{"title": "A database migration", "body": OTHER_MARKDOWN}]),
     full_text.NEEDS_SCRIPT),
    ("a script-built page with no data", f"{SITE}/app/empty", TITLE, ABSTRACT,
     page('<div id="app"></div><noscript>You need to enable JavaScript to run this app.</noscript>', title="Example"),
     full_text.NEEDS_SCRIPT),
    ("a short title shared with the page", f"{SITE}/2026/notes", "Notes", ABSTRACT,
     article_page(f"{SITE}/2026/other-notes", title="Notes"), full_text.NOT_SAME_ARTICLE),
]


class FixtureMeasureTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_class_is_read_as_it_should_be_and_no_wrong_page_is_taken(self):
        wrong, right = [], []
        for name, url, title, body, answer, wanted in FIXTURES:
            post = {"url": url, "title": title, "content_html": body}
            got = await read(url, full_text.body_text(post), answer, title=title)
            (right if got.outcome == wanted else wrong).append((name, wanted, got.outcome))
            if got.article and wanted == full_text.FULL:
                text = got.article[1]
                self.assertIn("each token visits a few of them", text, name)
                self.assertNotIn("database migration", text, name)
        self.assertEqual(wrong, [])
        self.assertEqual(len(right), len(FIXTURES))


# --------------------------------------------------------------------------- the rules, one by one

class SameArticleTests(unittest.TestCase):
    URL = f"{SITE}/2026/a"

    def same(self, body: str, answer: str, *, title: str = TITLE, url: str = URL, site: str = FEED) -> bool:
        return full_text.same_article(body, ARTICLE_TEXT, answer, url=url, title=title, site=site)

    def test_the_title_rule_accepts_the_page_titled_as_the_post_and_rejects_another(self):
        self.assertTrue(self.same(ABSTRACT, page(ARTICLE_HTML)))
        self.assertTrue(self.same(ABSTRACT, page(ARTICLE_HTML, title="x", head=f'<meta property="og:title" content="Example Blog — {TITLE}">')))
        self.assertTrue(self.same(ABSTRACT, page(f"<article><h1>{TITLE}</h1>{ARTICLE_HTML}</article>", title="x")))
        self.assertFalse(self.same(ABSTRACT, page(ARTICLE_HTML, title="Another title of a post")))

    def test_the_address_rule_accepts_a_page_naming_the_post_and_rejects_one_naming_another(self):
        self.assertTrue(self.same(ABSTRACT, page(ARTICLE_HTML, title="x", canonical=self.URL + "?utm_source=rss")))
        self.assertTrue(self.same(ABSTRACT, page(ARTICLE_HTML, title="x", head=f'<meta property="og:url" content="{self.URL}">')))
        self.assertFalse(self.same(ABSTRACT, page(ARTICLE_HTML, title="x", canonical=f"{SITE}/")))

    def test_the_word_runs_rule_accepts_a_teaser_found_on_the_page_and_rejects_one_that_is_not(self):
        middle = "In short, the middle of it. " + " ".join(ARTICLE_PARAGRAPHS[14:17])   # not the opening: today's rule refuses it
        self.assertFalse(full_text._same_article(middle, ARTICLE_TEXT))
        self.assertTrue(self.same(middle, page(ARTICLE_HTML, title="x")))
        self.assertFalse(self.same(ABSTRACT, page(ARTICLE_HTML, title="x")))
        self.assertGreaterEqual(full_text.shingle_share(middle, ARTICLE_TEXT), full_text.SHINGLE_SHARE)

    def test_a_link_post_keeps_todays_rule_alone(self):
        url = "https://elsewhere.example.net/a"
        self.assertFalse(self.same(ABSTRACT, page(ARTICLE_HTML, canonical=url), url=url))
        self.assertFalse(self.same("In short, the middle of it. " + " ".join(ARTICLE_PARAGRAPHS[14:17]), page(ARTICLE_HTML), url=url))

    def test_a_short_title_is_no_evidence(self):
        self.assertFalse(self.same(ABSTRACT, page(ARTICLE_HTML, title="Notes"), title="Notes"))


class CutMarkerTests(unittest.TestCase):
    URL = f"{SITE}/2026/a"

    def cut(self, html: str, title: str = "A post") -> bool:
        return full_text.cut_marker({"url": self.URL, "title": title, "content_html": html})

    def test_a_read_more_link_to_the_post_marks_a_teaser_whatever_its_length(self):
        long_text = "<p>" + "Words before the cut. " * 100 + "</p>"
        post = {"url": self.URL, "title": "A post", "content_html": long_text + f'<a href="{self.URL}#cut">Read more</a>'}
        self.assertTrue(full_text.is_teaser(post))
        self.assertFalse(full_text.is_teaser({**post, "content_html": long_text}))
        self.assertTrue(self.cut(f'<p>Text.</p><p><a href="{self.URL}?utm_source=rss">Читать далее</a></p>'))
        self.assertTrue(self.cut(f'<p>Text and more <a class="more-link" href="{self.URL}">Continue reading <span>A post</span></a></p>'))
        self.assertTrue(self.cut(f'<p>Text.</p><a href="{self.URL}#more-123">→</a> <a href="{self.URL}#more-123">…</a>'))

    def test_a_link_with_the_title_only_or_to_another_page_or_mid_text_is_no_cut(self):
        self.assertFalse(self.cut(f'<p>The post <a href="{self.URL}">A post</a> appeared first on <a href="{SITE}/">Blog</a>.</p>'))
        self.assertFalse(self.cut(f'<p>Text. <a href="{SITE}/2026/b">Read more</a></p>'))
        self.assertFalse(self.cut(f'<p>See <a href="{self.URL}">here</a> and then the whole rest of the post goes on for a while.</p>'))
        # Whole feed bodies end so on the 2026-11-05 export: comments, a permalink, a footnote's return.
        self.assertFalse(self.cut(f'<p>Text.</p><a href="{self.URL}">Comments</a>'))
        self.assertFalse(self.cut(f'<p>Text.</p><a href="{self.URL}">[link]</a> <a href="{self.URL}">[comments]</a>'))
        self.assertFalse(self.cut(f'<p>Text.<a href="{self.URL}#fnref1">[return]</a></p>'))


class EmbeddedDataTests(unittest.TestCase):
    def test_next_data_markdown_is_read_as_paragraphs_and_headings(self):
        [found] = embedded_article.embedded_articles(next_data({"title": TITLE, "content": MARKDOWN}))
        self.assertEqual(found.title, TITLE)
        html = embedded_article.as_html(found)
        self.assertTrue(html.startswith("<h3>Setup</h3>\n<p>We start with"))

    def test_json_ld_article_body_and_a_hydration_assignment(self):
        ld = '<script type="application/ld+json">' + json.dumps(
            {"@graph": [{"@type": "WebPage", "name": "Site"}, {"@type": "BlogPosting", "headline": TITLE,
                                                                "articleBody": ARTICLE_TEXT}]}) + "</script>"
        [found] = embedded_article.embedded_articles(ld)
        self.assertEqual((found.key, found.title), ("articleBody", TITLE))
        state = "<script>window.__NUXT__ = " + json.dumps({"data": {"post": {"title": TITLE, "bodyHtml": ARTICLE_HTML}}}) + ";</script>"
        [found] = embedded_article.embedded_articles(state)
        self.assertTrue(found.is_html)

    def test_descriptions_code_and_short_strings_are_not_articles(self):
        data = {"description": ARTICLE_TEXT, "content": "short", "body": "function(a){return a;};var b={c:1};" * 40}
        self.assertEqual(embedded_article.embedded_articles(
            f'<script type="application/json">{json.dumps(data)}</script>'), [])

    def test_a_script_built_page_is_told_from_a_plain_one(self):
        self.assertTrue(embedded_article.script_rendered('<body><div id="__next"></div></body>'))
        self.assertFalse(embedded_article.script_rendered(page(ARTICLE_HTML)))


# --------------------------------------------------------------------------- every read leaves a reason

class OutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, answer, body: str = ABSTRACT, title: str = TITLE) -> dict:
        url = f"{SITE}/2026/post"
        http = FakeHttp({FEED: feed((url, title, body)), url: answer})
        [post] = await GenericRssKind(http, clock=lambda: NOW).fetch_latest(source(), 10)
        return post

    def outcome(self, post: dict) -> str:
        self.assertEqual(post["metadata"][FULL_TEXT_RULE_KEY], full_text.FULL_TEXT_RULE)
        self.assertEqual(post["metadata"][PAGE_OUTCOME_KEY]["at"], NOW.isoformat())
        return post["metadata"][PAGE_OUTCOME_KEY]["outcome"]

    async def test_full(self):
        post = await self.fetch(article_page(f"{SITE}/2026/post"))
        self.assertEqual(self.outcome(post), "full")
        self.assertTrue(post["metadata"][FULL_TEXT_FLAG])

    async def test_nothing_longer_not_same_article_and_needs_script(self):
        self.assertEqual(self.outcome(await self.fetch(page("<p>Tiny.</p>"))), "nothing_longer")
        self.assertEqual(self.outcome(await self.fetch(article_page(f"{SITE}/x", title="Another post", canonical=False))),
                         "not_same_article")
        self.assertEqual(self.outcome(await self.fetch(page('<div id="__next"></div>'))), "needs_script")

    async def test_an_http_error_and_any_other_error(self):
        post = await self.fetch(HttpError("HTTP 403 while fetching", status=403))
        self.assertEqual(self.outcome(post), "http:403")
        self.assertTrue(post["metadata"][PAGE_TRIES_KEY]["failed"])
        post = await self.fetch(HttpError("timed out", timed_out=True))
        self.assertEqual(self.outcome(post), "error:HttpError")
        post = await self.fetch(RuntimeError("the reader could not parse it"))
        self.assertEqual(self.outcome(post), "error:RuntimeError")
        self.assertNotIn(PAGE_TRIES_KEY, post["metadata"])
        self.assertEqual(post["content"], ABSTRACT)

    async def test_a_stored_teaser_read_again_records_its_outcome(self):
        url = f"{SITE}/2026/again"
        stored = {"url": url, "title": TITLE, "content": ABSTRACT, "content_html": ABSTRACT, "metadata": {
            PAGE_TRIES_KEY: {"count": 1, "last_at": "2026-11-01T00:00:00+00:00", "failed": True}}}
        http = FakeHttp({FEED: feed(), url: article_page(url)})
        kind = GenericRssKind(http, teasers_due=lambda *a, **k: [stored], clock=lambda: NOW)
        [post] = await kind.fetch_latest({**source(), "id": "s1"}, 10)
        self.assertEqual(self.outcome(post), "full")


class ReaderLineTests(unittest.TestCase):
    def reason(self, outcome: str, **post) -> str | None:
        return full_text.teaser_reason({PAGE_OUTCOME_KEY: {"outcome": outcome, "at": NOW.isoformat()}}, **post)

    def test_the_reasons(self):
        self.assertEqual(self.reason("not_same_article"), "its page did not read as the same article")
        self.assertEqual(self.reason("needs_script"), "its page needs a script to show the article")
        self.assertEqual(self.reason("http:403"), "its page answered HTTP 403")
        self.assertEqual(self.reason("error:RuntimeError"), "its page could not be read")

    def test_a_post_read_in_full_or_whole_or_never_read_shows_none(self):
        self.assertIsNone(self.reason("full"))
        self.assertIsNone(self.reason("nothing_longer", url=f"{SITE}/a", title="A", content_html="<p>A note.</p>"))
        self.assertEqual(self.reason("nothing_longer", url=f"{SITE}/a", title="A",
                                     content_html=f'<p>Text.</p><a href="{SITE}/a#cut">Read more</a>'),
                         "its page held nothing longer")
        self.assertIsNone(full_text.teaser_reason({}))
        self.assertIsNone(full_text.teaser_reason({FULL_TEXT_FLAG: True, PAGE_OUTCOME_KEY: {"outcome": "needs_script"}}))


# --------------------------------------------------------------------------- the repair, once per rule version

class _StubYouTube:
    pass


@requires_test_db
class RuleRepairTests(unittest.IsolatedAsyncioTestCase):
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

    def _upsert(self, url: str, metadata: dict | None = None, title: str = TITLE, content: str = ABSTRACT) -> str:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            # One source's same title and body is one post (issue 0070): each its own body.
            post_id, _ = self.repo.upsert_post(cur, {"url": url, "title": title, "content": f"{content} ({url})", "date": None,
                                                     "metadata": metadata or {}}, self.source_id)
            conn.commit()
        return post_id

    def _metadata(self, post_id: str) -> dict:
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute("SELECT metadata FROM posts WHERE id = %s", (post_id,))
            return cur.fetchone()[0]

    def _repair(self, http: FakeHttp, **kwargs):
        registry = KindRegistry.default(http, _StubYouTube(), db_url=self.url)
        return Repair(self.url, http=http, registry=registry, clock=lambda: NOW).run(
            source_id=self.source_id, rule=True, **kwargs)

    async def test_it_reads_the_posts_left_short_once_per_rule_version_and_resumes(self):
        old = f"{RSITE}/2026/old"                # read before 0140: no outcome, checked by the old repair
        same = f"{RSITE}/2026/not-same"          # refused by the old opening rule
        gone = f"{RSITE}/2026/gone"              # an HTTP error: 0062's retry, not this repair
        done = f"{RSITE}/2026/done"              # already read by this version
        ids = {
            old: self._upsert(old, {"full_text_checked_at": "2026-10-12T00:00:00+00:00"}),
            same: self._upsert(same, {PAGE_OUTCOME_KEY: {"outcome": "not_same_article", "at": "x"}, FULL_TEXT_RULE_KEY: 1}),
            gone: self._upsert(gone, {PAGE_OUTCOME_KEY: {"outcome": "http:404", "at": "x"}}),
            done: self._upsert(done, {PAGE_OUTCOME_KEY: {"outcome": "nothing_longer", "at": "x"},
                                      FULL_TEXT_RULE_KEY: full_text.FULL_TEXT_RULE}),
        }
        self._upsert("https://t.me/channel/1", title="A message")   # never an article page
        dry = await self._repair(FakeHttp(), dry_run=True)
        self.assertEqual(dry["by_site"], {"test.invalid": 2}, dry)
        http = FakeHttp({old: article_page(old), same: HttpError("HTTP 503", status=503)})
        summary = await self._repair(http)
        self.assertEqual(sorted(http.requests), sorted([old, same]))
        self.assertEqual(summary["outcomes"], {"full": 1, "http:503": 1})
        self.assertTrue(self._metadata(ids[old])[FULL_TEXT_FLAG])
        self.assertEqual(self._metadata(ids[old])[FULL_TEXT_RULE_KEY], full_text.FULL_TEXT_RULE)
        self.assertEqual(self._metadata(ids[same])[PAGE_OUTCOME_KEY]["outcome"], "http:503")
        # A second run (a later start) reads nothing: each read recorded its version.
        again = FakeHttp()
        self.assertEqual((await self._repair(again))["to_read"], 0)
        self.assertEqual(again.requests, [])

    async def test_a_feed_refetch_keeps_the_outcome_and_the_version(self):
        url = f"{RSITE}/2026/kept"
        post_id = self._upsert(url, {PAGE_OUTCOME_KEY: {"outcome": "needs_script", "at": "x"}, FULL_TEXT_RULE_KEY: 2})
        self._upsert(url, {"feed": "again"})
        metadata = self._metadata(post_id)
        self.assertEqual((metadata[PAGE_OUTCOME_KEY]["outcome"], metadata[FULL_TEXT_RULE_KEY], metadata["feed"]),
                         ("needs_script", 2, "again"))

    def test_the_start_reads_nothing_on_a_machine_that_must_not_fetch(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"INSIGHT_DISCOVER_READS": "0"}):
            self.assertIsNone(repair_full_text.repair_safely(self.url, http=FakeHttp()))
        with mock.patch.dict(os.environ, {"INSIGHT_DISCOVER_READS": "1", "INSIGHT_FULL_TEXT_REPAIR": "1"}):
            summary = repair_full_text.repair_safely(
                self.url, http=FakeHttp(), registry=KindRegistry.default(FakeHttp(), _StubYouTube(), db_url=self.url))
        self.assertIsNotNone(summary)


if __name__ == "__main__":
    unittest.main()
