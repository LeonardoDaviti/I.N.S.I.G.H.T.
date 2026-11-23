"""Scrape regardless of a feed (0240): the one test read (where_linked.follow, scout_reads.Reader) tries the site's list
pages before it calls a source unfollowable, and dates a feed's undated or titles-only items from their own pages.
Invented sites and HTML only; no network, no database."""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import where_linked
from insight_core.ingestion.kinds import KindRegistry, page_watch
from insight_core.markx import official, scout_reads, source_judge
from insight_core.services import discover_reads
from insight_core.tests._kind_fakes import FakeHttp

SITE = "https://corp.example"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = timedelta(days=1)
BODY = "<p>" + "The company shipped a new part and wrote down how it was made, step by step. " * 8 + "</p>"
JS_SHELL = '<!DOCTYPE html><html><head><title>Corp</title></head><body><div id="root"></div><script src="/app.js"></script></body></html>'


def slug(n: int) -> str:
    return f"we-launched-thing-number-{n}"


def day(n: int) -> str:
    return (NOW - n * DAY).strftime("%Y-%m-%dT%H:%M:%SZ")


def article(title: str, *, meta_date: str | None = None, json_ld: str | None = None, og_type: str = "article") -> str:
    """An article page; its date only where the arguments put it (never in its text)."""
    head = f'<meta property="og:title" content="{title}"/><meta property="og:type" content="{og_type}"/>'
    if meta_date:
        head += f'<meta property="article:published_time" content="{meta_date}"/>'
    if json_ld:
        head += f'<script type="application/ld+json">{{"@type": "NewsArticle", "datePublished": "{json_ld}"}}</script>'
    return (f"<!DOCTYPE html><html><head><title>{title} | Corp</title>{head}</head>"
            f"<body><article><h1>{title}</h1>{BODY}</article></body></html>")


def listing(path: str, n: int) -> str:
    """A list page of n article links, titles only: no date on the list itself."""
    links = "".join(f'<li><a href="{path}/{slug(k)}">Thing {k}</a></li>' for k in range(n))
    return f"<!DOCTYPE html><html><head><title>News | Corp</title></head><body><main><ul>{links}</ul></main></body></html>"


def articles(path: str, n: int, **how) -> dict:
    return {f"{SITE}{path}/{slug(k)}": article(f"Thing {k}", **{key: day(k + 1) for key in how}) for k in range(n)}


def read(responses: dict, address: str) -> scout_reads.ReadResult:
    http = FakeHttp(responses)
    return asyncio.run(scout_reads.Reader(http, KindRegistry.default(http, None), page_gap=0).read(address))


def follow(responses: dict, address: str, linked=()) -> tuple[dict, FakeHttp]:
    http = FakeHttp(responses)
    return asyncio.run(where_linked.follow(http, KindRegistry.default(http, None), address, list(linked))), http


def proof(got: scout_reads.ReadResult) -> str | None:
    """Official's proof (official._proof) of a judgement made of this read: None when it proves a dated stream."""
    j = {"status": "answered" if got.resolved and got.items else "unreadable", "reason": got.reason,
         "resolved": got.resolved or {}, "items": source_judge.scratch_items(got.items), "signals": {}}
    return official._proof({"kind": "feed", "evidence": {}}, j)[0]


class NewsroomWithoutAFeed(unittest.TestCase):
    """A newsroom with no feed: a home page built in JavaScript, and a dated list page at /news."""

    RESPONSES = {f"{SITE}/": JS_SHELL, f"{SITE}/news": listing("/news", 6), **articles("/news", 6, meta_date=True)}

    def test_follow_offers_the_list_page(self):
        found, _ = follow(self.RESPONSES, SITE)
        self.assertEqual(found["status"], "none")
        [offer] = found["pages"]
        self.assertEqual((offer["url"], offer["prefix"]), (f"{SITE}/news", "/news/"))
        self.assertTrue(page_watch.dated_list(offer["items"]))

    def test_the_test_read_reads_it_dated_and_official_proves_it(self):
        got = read(self.RESPONSES, SITE)
        self.assertEqual(got.reason, "")
        self.assertEqual((got.resolved["via"], got.resolved["handle_or_url"]), ("page", f"{SITE}/news"))
        self.assertEqual(got.resolved["settings"], {"page_watch": {"prefix": "/news/"}})
        self.assertEqual(len(got.items), 6)
        self.assertTrue(scout_reads.health(got.items)["reads_well"])
        self.assertIsNone(proof(got), "six dated items: a dated stream")

    def test_discover_labels_it_followable_and_the_judge_takes_it(self):
        http = FakeHttp(self.RESPONSES)
        out = asyncio.run(discover_reads.follow_read(http, KindRegistry.default(http, None), SITE, []))
        self.assertEqual(out["label"], "page")
        self.assertEqual(source_judge.to_judge([{"key": "corp.example", "follow_test": out, "score": 1}], [], 5),
                         ["corp.example"])

    def test_the_page_given_is_watched_itself(self):
        # a list page deeper than the home page is previewed itself
        responses = {f"{SITE}/company/newsroom": listing("/company/newsroom", 5),
                     **articles("/company/newsroom", 5, meta_date=True)}
        got = read(responses, f"{SITE}/company/newsroom")
        self.assertEqual((got.reason, got.resolved["handle_or_url"]), ("", f"{SITE}/company/newsroom"))
        self.assertEqual(len(got.items), 5)

    def test_an_article_finds_its_own_sections_list(self):
        responses = {f"{SITE}/stories/{slug(9)}": article("Nine", meta_date=day(1)),
                     f"{SITE}/stories": listing("/stories", 4), **articles("/stories", 4, meta_date=True)}
        got = read(responses, f"{SITE}/stories/{slug(9)}")
        self.assertEqual((got.reason, got.resolved["handle_or_url"]), ("", f"{SITE}/stories"))

    def test_a_page_under_an_account_keeps_to_it(self):
        # a page under an account or section (hub.example/<org>) is never offered the site's own news
        responses = {f"{SITE}/example-org": "<html><body><h1>Example org</h1><p>Models.</p></body></html>",
                     f"{SITE}/news": listing("/news", 4), **articles("/news", 4, meta_date=True)}
        got = read(responses, f"{SITE}/example-org")
        self.assertEqual((got.reason, got.resolved), (scout_reads.NOTHING, None))


class UndatedListDatedArticles(unittest.TestCase):
    """A list with undated items whose article pages carry their dates."""

    def test_list_items_take_the_dates_of_their_pages(self):
        # The press list shows titles only; each article page states its date in JSON-LD, and is no og:type article.
        responses = {f"{SITE}/": JS_SHELL, f"{SITE}/press": listing("/press", 5),
                     **articles("/press", 5, json_ld=True, og_type="website")}
        got = read(responses, SITE)
        self.assertEqual(got.resolved["handle_or_url"], f"{SITE}/press")
        self.assertEqual([i["published_at"].date() for i in got.items], [(NOW - (k + 1) * DAY).date() for k in range(5)])
        self.assertIsNone(proof(got))

    def test_a_titles_only_undated_feed_is_dated_from_its_pages(self):
        entries = "".join(f"<item><title>Thing {k}</title><link>{SITE}/updates/{slug(k)}</link></item>" for k in range(6))
        feed = f'<?xml version="1.0"?><rss version="2.0"><channel><title>Corp</title>{entries}</channel></rss>'
        responses = {f"{SITE}/updates/feed.xml": feed, **articles("/updates", 6, meta_date=True)}
        before = read({f"{SITE}/updates/feed.xml": feed}, f"{SITE}/updates/feed.xml")
        self.assertTrue(scout_reads.health(before.items)["reason"].startswith("undated"))
        self.assertEqual(proof(before), "no dated stream: 0 dated items read")
        got = read(responses, f"{SITE}/updates/feed.xml")
        h = scout_reads.health(got.items)
        self.assertTrue(h["reads_well"], h)
        self.assertEqual((h["dated"], got.resolved["from_pages"]), (6, 6))
        self.assertGreater(min(i["chars"] for i in got.items), scout_reads.NO_TEXT_CHARS)
        self.assertIsNone(proof(got), "titles only, dated from its article pages: a dated stream")

    def test_pages_read_for_dates_are_bounded(self):
        n = scout_reads.DATE_PAGES + 8
        entries = "".join(f"<item><title>T{k}</title><link>{SITE}/u/{slug(k)}</link></item>" for k in range(n))
        feed = f'<?xml version="1.0"?><rss version="2.0"><channel><title>Corp</title>{entries}</channel></rss>'
        http = FakeHttp({f"{SITE}/u/feed.xml": feed})
        asyncio.run(scout_reads.Reader(http, KindRegistry.default(http, None), page_gap=0).read(f"{SITE}/u/feed.xml"))
        # the finder reads the first entry's page once itself (a bodiless feed may have moved)
        self.assertEqual(sum(1 for url in http.requests if "/u/we-launched" in url), scout_reads.DATE_PAGES + 1)

    def test_a_news_sitemap_dates_a_javascript_list(self):
        # The newsroom list is built in JavaScript; the news sitemap names its articles with their publication date.
        entries = "".join(
            f"<url><loc>{SITE}/en/newsroom/{slug(k)}</loc><lastmod>{day(0)}</lastmod>"
            f"<news:news><news:publication_date>{day(k + 2)}</news:publication_date></news:news></url>" for k in range(4))
        sitemap = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                   f'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">{entries}</urlset>')
        responses = {f"{SITE}/": JS_SHELL, f"{SITE}/robots.txt": f"Sitemap: {SITE}/news-sitemap.xml\n",
                     f"{SITE}/news-sitemap.xml": sitemap, f"{SITE}/en/newsroom": JS_SHELL,
                     **articles("/en/newsroom", 4)}            # the pages state no date: og:type article only
        got = read(responses, SITE)
        self.assertEqual((got.reason, got.resolved["handle_or_url"]), ("", f"{SITE}/en/newsroom"))
        self.assertEqual(sorted(i["published_at"].date() for i in got.items),
                         sorted((NOW - (k + 2) * DAY).date() for k in range(4)), "the publication dates, not lastmod")


class JavaScriptOnlyFails(unittest.TestCase):
    """A site built in JavaScript everywhere, no feed and no sitemap: unfollowable, after a bounded read."""

    RESPONSES = {f"{SITE}/": JS_SHELL, f"{SITE}/news": JS_SHELL, f"{SITE}/blog": JS_SHELL}

    def test_it_truly_fails(self):
        got = read(self.RESPONSES, SITE)
        self.assertIsNone(got.resolved)
        self.assertEqual((got.reason, got.items), (scout_reads.NOTHING, []))
        self.assertEqual(proof(got), f"no dated stream: {scout_reads.NOTHING}")
        self.assertLess(got.requests, 60, "a bounded read")
        http = FakeHttp(self.RESPONSES)
        out = asyncio.run(discover_reads.follow_read(http, KindRegistry.default(http, None), SITE, []))
        self.assertEqual(out["label"], "headlines")
        self.assertEqual(source_judge.to_judge([{"key": "corp.example", "follow_test": out, "score": 1}], [], 5), [])

    def test_undated_list_pages_are_not_offered(self):
        # Pages that are articles but state no date anywhere: no dated stream, nothing offered.
        responses = {f"{SITE}/": JS_SHELL, f"{SITE}/news": listing("/news", 5), **articles("/news", 5)}
        found, _ = follow(responses, SITE)
        self.assertEqual(found["pages"], [])

    def test_a_rate_limiting_site_is_not_tried_further(self):
        from insight_core.ingestion.http import HttpError
        http = FakeHttp({f"{SITE}/": HttpError("HTTP 429", status=429)})
        found = asyncio.run(where_linked.follow(http, KindRegistry.default(http, None), SITE, []))
        self.assertEqual((found["pages"], found.get("reason")), ([], "rate-limited"))
        self.assertNotIn(f"{SITE}/news", http.requests)


class Rules(unittest.TestCase):
    def test_list_pages_in_order(self):
        sitemap = [f"{SITE}/en/newsroom/{slug(k)}" for k in range(3)] + [
            f"{SITE}/blog/{slug(1)}", f"{SITE}/company/press/{slug(1)}", "https://other.example/news/x"]
        self.assertEqual(page_watch.list_pages(SITE, sitemap), [
            f"{SITE}/en/newsroom", f"{SITE}/blog", f"{SITE}/news", f"{SITE}/newsroom", f"{SITE}/press"])
        # Under a section: the page, its parent, its section and the sitemap's lists under it; never the root's.
        self.assertEqual(page_watch.list_pages(f"{SITE}/company/about/team", sitemap), [
            f"{SITE}/company/about/team", f"{SITE}/company/about", f"{SITE}/company", f"{SITE}/company/press"])
        # A feed address stands for its site.
        self.assertEqual(page_watch.list_pages(f"{SITE}/feed.xml"), [f"{SITE}/{p}" for p in page_watch.ROOT_LISTS])

    def test_dated_list(self):
        self.assertTrue(page_watch.dated_list([{"published_at": "x"}, {"published_at": "y"}, {"published_at": None}]))
        self.assertFalse(page_watch.dated_list([{"published_at": "x"}, {"published_at": None}, {"published_at": None}]))
        self.assertFalse(page_watch.dated_list([{"published_at": "x"}]))

    def test_only_unfollowable_tests_of_rule_four_are_due_again(self):
        at = NOW.isoformat()
        self.assertFalse(discover_reads.due({"label": "feed", "test": 4, "at": at}, NOW, test=True))
        self.assertFalse(discover_reads.due({"label": "page", "test": 4, "at": at}, NOW, test=True))
        self.assertTrue(discover_reads.due({"label": "headlines", "test": 4, "at": at}, NOW, test=True))
        self.assertTrue(discover_reads.due({"label": "other_feed", "test": 4, "at": at}, NOW, test=True))
        self.assertTrue(discover_reads.due({"label": "feed", "test": 3, "at": at}, NOW, test=True))
        self.assertFalse(discover_reads.due({"label": "headlines", "test": discover_reads.FOLLOW_TEST, "at": at}, NOW,
                                            test=True))


if __name__ == "__main__":
    unittest.main()
