"""Page watch, v10.15 Discover fixes (part F): a prefix is never a date (c5), www. and the bare host are one page (c6),
a form is never a post (c7), the site's name comes off the titles (c8), a listing's numbered page is never an article
or an offer (c10), and a page the preview reads is the source's post once fetched (item 5).

No network: FakeHttp answers the pages. Invented sites only. The item 5 store test commits rows, so it runs only
against a `_test` database; it owns every source and post on lab.acmef1015.example.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.kinds import page_watch
from insight_core.ingestion.kinds.page_watch import (PageWatchKind, action_page, discover, form_page, infer_prefix,
                                                     offers, page_date, pagination_page, preview, section_prefix,
                                                     site_suffixes, stable_prefix)
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp

SITE = "https://acme.example"
PARAGRAPH = "<p>" + "A paragraph of an article about a new model and what it can do for its readers. " * 12 + "</p>"


def article(title: str, date: str = "2026-11-05T00:00:00Z", *, og_title: str | None = None, extra: str = "") -> str:
    og = f'<meta property="og:title" content="{og_title}"/>' if og_title else ""
    return (f'<!DOCTYPE html><html><head><title>{title}</title>{og}'
            f'<meta property="article:published_time" content="{date}"/></head>'
            f'<body><article><h1>{title}</h1>{PARAGRAPH}{extra}</article></body></html>')


def listing(links, title: str = "News") -> str:
    return (f"<!DOCTYPE html><html><head><title>{title}</title></head><body><main>"
            + "".join(f'<a href="{href}">{href}</a>' for href in links) + "</main></body></html>")


def run(coro):
    return asyncio.run(coro)


def source(url: str, source_id: str = "s1", **settings) -> dict:
    return {"id": source_id, "platform": "rss", "handle_or_url": url, "settings": {"page_watch": settings}}


class PrefixNeverADate(unittest.TestCase):
    """c5: a prefix is the stable section above any date segments."""

    def test_a_site_whose_articles_are_dated_at_its_root_is_followed_at_the_root(self):
        self.assertEqual(infer_prefix(f"{SITE}/", [f"{SITE}/2026/first-thing-we-did"]), "/")
        links = [f"{SITE}/2026/a-b-c", f"{SITE}/2026/d-e-f", f"{SITE}/2025/g-h-i", f"{SITE}/tags/x"]
        self.assertEqual(infer_prefix(f"{SITE}/", links), "/")

    def test_a_listing_path_stops_above_its_year(self):
        self.assertEqual(infer_prefix(f"{SITE}/blog/2026/11", []), "/blog/")
        self.assertEqual(infer_prefix(f"{SITE}/2026", []), "/")
        self.assertEqual(stable_prefix("/blog/2026/11/"), "/blog/")
        self.assertEqual(stable_prefix("/news/"), "/news/")
        self.assertEqual(stable_prefix("/news/2048-edition/"), "/news/2048-edition/", "a year is the whole segment")

    def test_the_section_of_a_listing_is_never_a_year(self):
        links = [f"{SITE}/2026/one-two-three", f"{SITE}/2026/four-five-six", f"{SITE}/2026/seven-eight-nine"]
        self.assertIsNone(section_prefix(f"{SITE}/resources/articles", links))

    def test_a_given_prefix_ending_in_a_year_reads_the_section_above_it(self):
        http = FakeHttp({f"{SITE}/": listing(["/2026/a-new-model", "/2025/an-old-model"])})
        found = run(discover(http, f"{SITE}/", "/2026/"))
        self.assertEqual(found.prefix, "/")
        self.assertEqual(found.candidates(), [f"{SITE}/2026/a-new-model", f"{SITE}/2025/an-old-model"],
                         "next year's article is still under it")


class WwwAndBareHostAreOnePage(unittest.TestCase):
    """c6: one page at www. and at the bare host is one candidate, one item, one stored post."""

    def responses(self):
        return {f"{SITE}/news": listing([f"{SITE}/news/model-two", "https://www.acme.example/news/model-two",
                                         "/news/model-one"]),
                f"{SITE}/news/model-two": article("Model two"),
                "https://www.acme.example/news/model-two": article("Model two"),
                f"{SITE}/news/model-one": article("Model one", "2026-10-01T00:00:00Z")}

    def test_the_preview_counts_and_shows_it_once(self):
        result = run(preview(FakeHttp(self.responses()), f"{SITE}/news"))
        self.assertEqual(result["found"], 2)
        self.assertEqual([item["url"] for item in result["items"]], [f"{SITE}/news/model-two", f"{SITE}/news/model-one"])

    def test_the_sitemap_s_other_form_is_the_listed_page(self):
        responses = self.responses()
        responses[f"{SITE}/robots.txt"] = f"Sitemap: {SITE}/sitemap.xml\n"
        responses[f"{SITE}/sitemap.xml"] = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://www.acme.example/news/model-one</loc><lastmod>2026-10-02</lastmod></url></urlset>')
        found = run(discover(FakeHttp(responses), f"{SITE}/news"))
        self.assertEqual(found.candidates(), [f"{SITE}/news/model-two", f"{SITE}/news/model-one"])
        self.assertEqual(found.sitemap, {f"{SITE}/news/model-one": datetime(2026, 10, 2, tzinfo=timezone.utc)})

    def test_a_page_stored_at_its_other_form_is_not_read_again(self):
        http = FakeHttp(self.responses())
        kind = PageWatchKind(http, stored_urls=lambda urls: {u for u in urls if u == "https://www.acme.example/news/model-two"})
        posts = run(kind.fetch_latest(source(f"{SITE}/news"), 10))
        self.assertEqual([p["url"] for p in posts], [f"{SITE}/news/model-one"])
        self.assertNotIn(f"{SITE}/news/model-two", http.requests)


class FormsAreNoPosts(unittest.TestCase):
    """c7: an action page (apply, sign up, contact...) or a page whose body is a form is never a post."""

    def test_an_action_word_at_the_end_of_the_address(self):
        for path in ("/news/research-grants/apply", "/news/login", "/blog/subscribe", "/contact", "/events/x/rsvp",
                     "/news/sign-up"):
            self.assertTrue(action_page(SITE + path), path)
        for path in ("/news/research-grants", "/news/how-to-apply-a-patch", "/news/applying-models", "/blog/contacts-api"):
            self.assertFalse(action_page(SITE + path), path)

    def test_the_apply_page_under_a_grant_is_no_candidate(self):
        http = FakeHttp({f"{SITE}/news": listing(["/news/research-grants", "/news/research-grants/apply"]),
                         f"{SITE}/news/research-grants": article("Announcing research grants"),
                         f"{SITE}/news/research-grants/apply": article("Research grants: how to apply")})
        posts = run(PageWatchKind(http).fetch_latest(source(f"{SITE}/news"), 10))
        self.assertEqual([p["url"] for p in posts], [f"{SITE}/news/research-grants"])
        self.assertNotIn(f"{SITE}/news/research-grants/apply", http.requests)

    def test_a_page_whose_body_is_a_form_is_no_post(self):
        fields = "".join(f'<label>{n}</label><input type="text" name="{n}"/>' for n in ("name", "email", "org", "role"))
        form = f'<form action="/submit">{fields}<textarea name="why"></textarea><input type="submit"/></form>'
        short = "<p>Tell us about your project and we will be in touch.</p>"
        page = (f'<html><head><title>Join the programme</title><meta property="article:published_time" content="2026-11-01"/>'
                f'</head><body><article><h1>Join the programme</h1>{short}{form}</article></body></html>')
        http = FakeHttp({f"{SITE}/news": listing(["/news/programme-intake-form-2026"]),
                         f"{SITE}/news/programme-intake-form-2026": page})
        self.assertEqual(run(PageWatchKind(http).fetch_latest(source(f"{SITE}/news"), 10)), [])

    def test_an_article_with_a_comment_or_newsletter_form_is_a_post(self):
        comments = ('<form id="commentform" action="/wp-comments-post.php"><input name="author"/><input name="email"/>'
                    '<input name="url"/><textarea name="comment"></textarea></form>')
        newsletter = '<form action="/subscribe"><input type="email" name="email"/><input type="submit"/></form>'
        self.assertFalse(form_page(article("A post", extra=comments), "short"))
        self.assertFalse(form_page(article("A post", extra=newsletter), "short"))
        long_text = "word " * 400
        fields = "".join(f'<input name="f{n}"/>' for n in range(5))
        self.assertFalse(form_page(f"<form>{fields}</form>", long_text), "an article with a form in it")


class SiteNameOffTitles(unittest.TestCase):
    """c8: the trailing segment most of a section's titles share is the site's name."""

    def test_the_shared_suffix_is_learned_and_a_lone_one_kept(self):
        self.assertEqual(site_suffixes(["One | Acme Blog", "Two | Acme Blog", "Three | Acme Blog"]), {"acme blog"})
        self.assertEqual(site_suffixes(["Model two - the next model"]), set(), "one title teaches nothing")
        self.assertEqual(site_suffixes(["A - x", "B - y", "C - z"]), set(), "no segment repeats")
        self.assertEqual(site_suffixes(["One — Acme", "Two — Acme", "Three"]), {"acme"})
        self.assertEqual(site_suffixes(["One / Blog", "Two / Blog"]), {"blog"})
        self.assertEqual(site_suffixes(["One works- Acme Developers Blog", "Two- Acme Developers Blog"]),
                         {"acme developers blog"})

    def test_the_preview_and_the_fetch_strip_it(self):
        titles = {"a-new-model-ships": "A new model ships | Acme Blog", "pricing-changes-today": "Pricing changes today | Acme Blog",
                  "a-talk-we-gave": "A talk we gave - in two parts"}
        responses = {f"{SITE}/blog": listing([f"/blog/{slug}" for slug in titles]),
                     **{f"{SITE}/blog/{slug}": article("x", og_title=title) for slug, title in titles.items()}}
        result = run(preview(FakeHttp(responses), f"{SITE}/blog"))
        self.assertEqual([item["title"] for item in result["items"]],
                         ["A new model ships", "Pricing changes today", "A talk we gave - in two parts"])
        posts = run(PageWatchKind(FakeHttp(responses)).fetch_latest(source(f"{SITE}/blog"), 10))
        self.assertEqual([p["title"] for p in posts], ["A new model ships", "Pricing changes today", "A talk we gave - in two parts"])

    def test_one_new_post_learns_from_its_listing_s_title(self):
        responses = {f"{SITE}/blog": listing(["/blog/a-new-model-ships"], title="Blog | Acme Blog"),
                     f"{SITE}/blog/a-new-model-ships": article("x", og_title="A new model ships | Acme Blog")}
        [post] = run(PageWatchKind(FakeHttp(responses)).fetch_latest(source(f"{SITE}/blog"), 10))
        self.assertEqual(post["title"], "A new model ships")
        responses[f"{SITE}/blog"] = listing(["/blog/a-new-model-ships"], title="Blog")
        [post] = run(PageWatchKind(FakeHttp(responses)).fetch_latest(source(f"{SITE}/blog"), 10))
        self.assertEqual(post["title"], "A new model ships | Acme Blog", "one title alone keeps its suffix")


class PaginationIsNoArticle(unittest.TestCase):
    """c10: a listing's numbered page is never a candidate, a post or a section offered."""

    def test_the_shapes(self):
        for url in (f"{SITE}/news/page/7", f"{SITE}/blog/p/3", f"{SITE}/news?page=7", f"{SITE}/news/pages/2"):
            self.assertTrue(pagination_page(url), url)
        self.assertTrue(pagination_page(f"{SITE}/news/archive-seven", "News (Page 7)"))
        self.assertTrue(pagination_page(f"{SITE}/news/x", "News — Page 2 of 9"))
        for url in (f"{SITE}/p/a-substack-post", f"{SITE}/news/page-one-of-history", f"{SITE}/?p=123"):
            self.assertFalse(pagination_page(url), url)

    def test_a_section_whose_only_page_read_is_its_seventh_is_not_offered(self):
        responses = {f"{SITE}/news": listing(["/news/page/7", "/news/page/8"]),
                     f"{SITE}/news/page/7": article("News (Page 7)", "2023-09-21T00:00:00Z"),
                     f"{SITE}/news/page/8": article("News (Page 8)", "2023-09-21T00:00:00Z"),
                     f"{SITE}/blog": listing(["/blog/a-real-post-here"]),
                     f"{SITE}/blog/a-real-post-here": article("A real post")}
        found = run(offers(FakeHttp(responses), [f"{SITE}/news", f"{SITE}/blog", f"{SITE}/news/page/2"]))
        self.assertEqual([offer["url"] for offer in found], [f"{SITE}/blog"])
        result = run(preview(FakeHttp(responses), f"{SITE}/news"))
        self.assertEqual((result["found"], result["items"]), (0, []))

    def test_a_page_titled_as_a_numbered_listing_is_no_post(self):
        responses = {f"{SITE}/news": listing(["/news/older-news-archive"]),
                     f"{SITE}/news/older-news-archive": article("News (Page 7)")}
        self.assertEqual(run(PageWatchKind(FakeHttp(responses)).fetch_latest(source(f"{SITE}/news"), 10)), [])


class TheListedPageIsRead(unittest.TestCase):
    """Item 5 (second case): a listed page linked with a trailing slash, dated only by its byline under its title
    while related cards below carry other dates, is the source's post."""

    PAGE = ('<!DOCTYPE html><html><head><title>Introducing Model Three</title>'
            '<meta name="og:title" content="Introducing Model Three"/></head><body>'
            '<div>FEATURED Research</div><h1>Introducing Model Three</h1><div><span>July 7, 2026</span> • 15 minute read</div>'
            f'<article>{PARAGRAPH}</article>'
            '<aside><a href="/blog/older-one-here">Older one</a><span>April 5, 2023</span>'
            '<a href="/blog/older-two-here">Older two</a><span>November 18, 2022</span></aside></body></html>')

    def test_the_byline_dates_a_page_of_several_written_dates(self):
        self.assertEqual(page_date(self.PAGE), datetime(2026, 7, 7, tzinfo=timezone.utc))
        far = self.PAGE.replace("<div><span>July 7, 2026</span>", "<div>" + "words " * 40 + "<span>July 7, 2026</span>")
        self.assertIsNone(page_date(far), "a date far below the title is no byline")

    def test_a_trailing_slash_link_is_fetched_and_kept(self):
        responses = {f"{SITE}/blog": listing(["/blog/introducing-model-three/", "/blog/a-plain-post-here"]),
                     f"{SITE}/blog/introducing-model-three": self.PAGE,
                     f"{SITE}/blog/a-plain-post-here": article("A plain post", "2026-07-01T00:00:00Z")}
        posts = run(PageWatchKind(FakeHttp(responses)).fetch_latest(source(f"{SITE}/blog"), 10))
        self.assertEqual([(p["url"], p["date"]) for p in posts], [
            (f"{SITE}/blog/introducing-model-three", datetime(2026, 7, 7, tzinfo=timezone.utc)),
            (f"{SITE}/blog/a-plain-post-here", datetime(2026, 7, 1, tzinfo=timezone.utc))])

    def test_a_page_held_elsewhere_is_read_when_kept_urls_says_so(self):
        responses = {f"{SITE}/news": listing(["/news/model-two-launch", "/news/model-one-launch"]),
                     f"{SITE}/news/model-two-launch": article("Model two"),
                     f"{SITE}/news/model-one-launch": article("Model one", "2026-10-01T00:00:00Z")}
        asked = []

        def kept(urls, source_id):
            asked.append(source_id)
            return {u for u in urls if u.endswith("model-one-launch")}   # model two is held where it is taken back

        http = FakeHttp(responses)
        kind = PageWatchKind(http, stored_urls=lambda urls: set(urls), kept_urls=kept)
        posts = run(kind.fetch_latest(source(f"{SITE}/news", "src-9"), 10))
        self.assertEqual([p["url"] for p in posts], [f"{SITE}/news/model-two-launch"])
        self.assertEqual(asked, ["src-9"])


LAB = "https://lab.acmef1015.example"


@requires_test_db
class ACollectedPageIsTheNewSourcesPost(unittest.TestCase):
    """Item 5: a page INSIGHT collected into Saved (a News story's original, shown only inside its story) is the
    newest article of a page watch added later. Its first fetch reads it first, before the source holds any post of
    its shape: the page moves to the source (a row of its feed), at its exact address or another form of it."""

    def setUp(self):
        import psycopg

        from insight_core.db.repo_posts import PostsRepository

        self.psycopg, self.repo = psycopg, PostsRepository(db_url())
        self.addCleanup(self._clean)
        self._clean()
        self.saved = self._saved_source()
        self.watch = self._rows("INSERT INTO sources (platform, handle_or_url, enabled, settings) VALUES "
                                "('rss', %s, true, %s::jsonb) RETURNING id::text",
                                f"{LAB}/news", json.dumps({"page_watch": {"prefix": "/news/"}}))[0][0]

    def _rows(self, sql, *args):
        with self.psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else None

    def _clean(self):
        self._rows("DELETE FROM posts WHERE url LIKE %s", f"{LAB}%")
        self._rows("DELETE FROM sources WHERE handle_or_url LIKE %s", f"{LAB}%")

    def _saved_source(self):
        found = self._rows("SELECT id::text FROM sources WHERE platform = 'saved' LIMIT 1")
        if found:
            return found[0][0]
        return self._rows("INSERT INTO sources (platform, handle_or_url, enabled) VALUES ('saved', 'Saved', true) "
                          "RETURNING id::text")[0][0]

    def _collected(self, url):
        post = {"url": url, "title": "Introducing model two", "content": "Introducing model two. " + "Words. " * 30,
                "date": datetime(2026, 11, 5, tzinfo=timezone.utc), "external_id": url,
                "metadata": {"adapter": "saved", "collected_original": "2026-11-08T21:38:41+00:00", "story_only": True}}
        with self.psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            return str(self.repo.upsert_post(cur, post, self.saved)[0])

    def _fetch_and_store(self):
        responses = {f"{LAB}/news": listing(["/news/model-two-launch", "/news/model-one-launch", "/news/model-zero-launch"]),
                     f"{LAB}/news/model-two-launch": article("Introducing model two"),
                     f"{LAB}/news/model-one-launch": article("Model one", "2026-10-01T00:00:00Z"),
                     f"{LAB}/news/model-zero-launch": article("Model zero", "2026-09-01T00:00:00Z")}
        kind = PageWatchKind(FakeHttp(responses), stored_urls=self.repo.stored_urls, kept_urls=self.repo.kept_urls)
        posts = run(kind.fetch_latest(source(f"{LAB}/news", self.watch), 20))
        with self.psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            return [self.repo.upsert_post(cur, post, self.watch) for post in posts]

    def _assert_moved(self, post_id):
        ((source_id, url, metadata),) = self._rows("SELECT source_id::text, url, metadata FROM posts WHERE id = %s::uuid",
                                                    post_id)
        self.assertEqual(source_id, self.watch, "the source's own post now")
        self.assertEqual(url, f"{LAB}/news/model-two-launch")
        self.assertNotIn("story_only", metadata, "a row of its feed")
        self.assertEqual(self._rows("SELECT count(*) FROM posts WHERE source_id = %s::uuid", self.watch), [(3,)])

    def test_at_its_exact_address(self):
        collected = self._collected(f"{LAB}/news/model-two-launch")
        self.assertEqual(self.repo.kept_urls([f"{LAB}/news/model-two-launch"], self.watch), set(), "read: it moves")
        saved = self._fetch_and_store()
        self.assertIn((collected, False), saved)
        self._assert_moved(collected)
        self.assertEqual(self.repo.kept_urls([f"{LAB}/news/model-two-launch"], self.watch),
                         {f"{LAB}/news/model-two-launch"}, "the source's own post now: not read again")

    def test_at_its_trailing_slash_form(self):
        collected = self._collected(f"{LAB}/news/model-two-launch/")
        self._fetch_and_store()
        self._assert_moved(collected)

    def test_a_source_of_another_site_leaves_it_held(self):
        self._collected(f"{LAB}/news/model-two-launch")
        links = self._rows("INSERT INTO sources (platform, handle_or_url, enabled) VALUES ('rss', %s, true) "
                           "RETURNING id::text", "https://links.acmef1015.example/feed.xml")[0][0]
        self.addCleanup(self._rows, "DELETE FROM sources WHERE id = %s::uuid", links)
        self.assertEqual(self.repo.kept_urls([f"{LAB}/news/model-two-launch"], links), {f"{LAB}/news/model-two-launch"})


if __name__ == "__main__":
    unittest.main()
