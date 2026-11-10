"""Stealth v10.13.9: an archive reads the source's own site, and an older page is never dated "now".

1. The archive's site is the source's own publication (the feed's host, its channel link), never the host its items
   link: a link blog's archive had crawled a newspaper's sitemap (its first item's host). A sitemap of another site is
   refused (foreign_site), an older checkpoint on another site is not resumed, an archive that finds a post in under
   5% of 1,000 pages stops (low_yield), and an address crawl waits at least a second between pages.
2. "date or now" is gone from the backlog's paths: article_post keeps None, the page watch's genuinely new page alone
   is dated now, an archive's / collected / missed page stays undated (sorted before its source's oldest) or takes its
   address's day or month (/2003/07/: the 1st). Migration 0101 repairs the posts stored with their fetch time.

Fictional names only; no network (FakeHttp); the database tests run against a `_test` database.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_posts import BACKLOG_KEY, PostDraft, PostsRepository
from insight_core.ingestion import archive_ladder
from insight_core.ingestion.kinds import page_watch
from insight_core.ingestion.kinds.base import RateLimit
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.services.saved_service import SavedService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp, RecordingSleeper
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils import originals_rules

RATE = RateLimit(page_delay_s=0, batch_size=0, batch_cooldown_s=0)
LINKS = "https://links-blog.example"          # a link blog: its items link other sites
LINKS_FEED = f"{LINKS}/feed.xml"
PAPER = "https://www.daily-paper.example"     # the site its items link
BLOG = "https://quiet-blog.example"
BLOG_FEED = f"{BLOG}/rss/"
MIGRATION = BACKEND_DIR / "insight_core/db/migrations/0101_older_pages_dated_now.sql"


def rss(items, *, link=None) -> str:
    entries = "".join(f"<item><title>t{n}</title><link>{url}</link><guid>{url}</guid>"
                      f"<pubDate>Mon, 0{n + 1} Nov 2026 00:00:00 GMT</pubDate><description>A link.</description></item>"
                      for n, url in enumerate(items))
    channel_link = f"<link>{link}</link>" if link else ""
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>{channel_link}{entries}</channel></rss>'


def urlset(*locs: str) -> str:
    entries = "".join(f"<url><loc>{loc}</loc><lastmod>2026-01-0{1 + n % 9}T00:00:00Z</lastmod></url>"
                      for n, loc in enumerate(locs))
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'


def article(title: str, published: str | None = "2020-06-01T00:00:00Z") -> str:
    date = f'<meta property="article:published_time" content="{published}">' if published else ""
    return (f'<html><head><title>{title}</title><meta property="og:type" content="article">{date}</head>'
            f"<body><article><p>{'What the post says, at length. ' * 40}</p></article></body></html>")


def source(feed: str) -> dict:
    return {"id": f"s-{uuid.uuid4().hex[:6]}", "platform": "rss", "handle_or_url": feed, "settings": {}}


async def pages_of(kind: GenericRssKind, src: dict, checkpoint=None, rate=RATE, target: int = 100) -> list:
    return [page async for page in kind.archive_pages(src, target, checkpoint, rate)]


def link_blog() -> dict:
    """The link blog: its feed's items link the paper; its own sitemap lists its own two older entries. The paper's
    sitemap is there too, listing many pages: it must never be read."""
    items = [f"{PAPER}/2026/11/0{n}/story-{n}" for n in range(1, 4)]
    paper_pages = [f"{PAPER}/2026/10/{n:02d}/old-story-{n}" for n in range(1, 20)]
    return {
        LINKS_FEED: rss(items, link=f"{LINKS}/"),
        f"{LINKS}/robots.txt": f"User-agent: *\nSitemap: {LINKS}/sitemap.xml\n",
        f"{LINKS}/sitemap.xml": urlset(f"{LINKS}/2025/03/an-entry/", f"{LINKS}/2024/12/another-entry/"),
        f"{LINKS}/2025/03/an-entry/": article("an entry", "2025-03-02T00:00:00Z"),
        f"{LINKS}/2024/12/another-entry/": article("another entry", "2024-12-20T00:00:00Z"),
        f"{PAPER}/robots.txt": f"User-agent: *\nSitemap: {PAPER}/sitemap.xml\n",
        f"{PAPER}/sitemap.xml": urlset(*paper_pages),
        **{page: article(page) for page in paper_pages},
    }


class ArchiveSiteTests(unittest.TestCase):
    def test_the_archive_reads_the_feeds_own_site_when_its_items_link_elsewhere(self):
        http = FakeHttp(link_blog())
        pages = asyncio.run(pages_of(GenericRssKind(http, min_page_delay=0), source(LINKS_FEED)))
        # (the feed's own teasers are read in full as any fetch reads them; the paper's site is never crawled)
        crawled = [url for url in http.requests if "daily-paper" in url and "/story-" not in url]
        self.assertEqual(crawled, [], "never the items' site")
        older = [post["url"] for page in pages[1:] for post in page.posts]
        self.assertEqual(sorted(older), [f"{LINKS}/2024/12/another-entry/", f"{LINKS}/2025/03/an-entry/"])
        checkpoint = pages[-1].checkpoint
        self.assertEqual((checkpoint["site"], checkpoint["ladder"]["site"]), (LINKS, LINKS))

    def test_the_source_site_rule(self):
        items = [f"{PAPER}/a", f"{PAPER}/b"]
        self.assertEqual(archive_ladder.source_site(LINKS_FEED, rss(items), items), LINKS, "the feed's own host")
        # A feed at feeds.<site> of posts at <site>: the items' host is the feed's own site.
        own = ["https://quiet-blog.example/p/1"]
        self.assertEqual(archive_ladder.source_site("https://feeds.quiet-blog.example/rss", rss(own), own), BLOG)
        # A feed served by a feed host whose channel link is its blog's home page: that blog.
        self.assertEqual(archive_ladder.source_site("https://feedhost.example/quiet", rss(own, link=f"{BLOG}/"), own),
                         BLOG)
        # A feed made elsewhere of a code host's pages, its channel link a page of that host: never the code host.
        repos = ["https://code-host.example/someone/repo"]
        self.assertEqual(archive_ladder.source_site("https://trends.example/daily.xml",
                                                    rss(repos, link="https://code-host.example/trending"), repos),
                         "https://trends.example")

    def test_a_sitemap_of_another_site_is_refused(self):
        responses = {
            BLOG_FEED: rss([f"{BLOG}/a-post/"]),
            f"{BLOG}/robots.txt": f"User-agent: *\nSitemap: {BLOG}/sitemap.xml\n",
            f"{BLOG}/sitemap.xml": urlset(*(f"{PAPER}/2026/10/{n:02d}/story" for n in range(1, 9))),
        }
        kind = GenericRssKind(FakeHttp(responses), min_page_delay=0)
        refused = asyncio.run(kind._sitemap_read([{"url": f"{BLOG}/a-post/"}], site=BLOG))
        self.assertEqual(refused[4], archive_ladder.FOREIGN_SITE)
        self.assertEqual(refused[2], [])
        http = FakeHttp(responses)
        found = asyncio.run(GenericRssKind(http, min_page_delay=0).inspect(source(BLOG_FEED)))
        self.assertEqual(found.raw["smart"]["outcomes"]["sitemap"], "foreign_site")
        self.assertFalse([url for url in http.requests if "daily-paper" in url])

    def test_an_older_checkpoint_on_another_site_stops_and_does_not_resume(self):
        http = FakeHttp(link_blog())
        kind = GenericRssKind(http, min_page_delay=0)
        older = {"mode": "sitemap", "site": PAPER, "prefix": "/", "next_index": 40, "pages_fetched": 41,
                 "collected_posts": 30, "total_candidates": 2000}
        ladder = {**older, "next_index": 3, "end": False,
                  "ladder": {"platform": "unknown", "order": ["listing"], "estimate": 2000, "items": [],
                             "starts": {"sitemap": {"site": PAPER, "prefix": "/"}}, "worked": {}}}
        for checkpoint in (older, ladder):
            self.assertTrue(kind.checkpoint_resumable(checkpoint), "the kind alone can't tell")
            pages = asyncio.run(pages_of(kind, source(LINKS_FEED), checkpoint))
            self.assertEqual(len(pages), 1)
            self.assertEqual((pages[0].posts, pages[0].checkpoint["stopped"]), ([], archive_ladder.FOREIGN_SITE))
            self.assertEqual(pages[0].checkpoint["collected_posts"], 30, "what it stored is kept, its counts too")
            self.assertFalse(kind.checkpoint_resumable(pages[0].checkpoint), "the next archive starts afresh")
        self.assertEqual(http.requests, [], "nothing read from the other site")

    def test_a_checkpoint_on_the_sources_own_site_resumes(self):
        kind = GenericRssKind(FakeHttp(link_blog()), min_page_delay=0)
        checkpoint = {"mode": "sitemap", "site": LINKS, "prefix": "/", "next_index": 0, "pages_fetched": 1,
                      "collected_posts": 3, "total_candidates": 2}
        pages = asyncio.run(pages_of(kind, source(LINKS_FEED), checkpoint))
        self.assertEqual(sum(len(page.posts) for page in pages), 2)
        self.assertNotIn("stopped", pages[-1].checkpoint)

    def test_an_archive_finding_a_post_in_under_5_percent_of_1000_pages_stops(self):
        kind = GenericRssKind(FakeHttp(link_blog()), min_page_delay=0)
        checkpoint = {"mode": "sitemap", "site": LINKS, "prefix": "/", "next_index": 0,
                      "pages_fetched": archive_ladder.LOW_YIELD_PAGES - 1, "collected_posts": 10,
                      "total_candidates": 2}
        pages = asyncio.run(pages_of(kind, source(LINKS_FEED), checkpoint))
        self.assertEqual([len(page.posts) for page in pages], [1, 0], "the page read is kept, then it stops")
        self.assertEqual(pages[-1].checkpoint["stopped"], archive_ladder.LOW_YIELD)
        self.assertFalse(kind.checkpoint_resumable(pages[-1].checkpoint))
        fine = {**checkpoint, "collected_posts": 60}
        pages = asyncio.run(pages_of(GenericRssKind(FakeHttp(link_blog()), min_page_delay=0), source(LINKS_FEED), fine))
        self.assertEqual([len(page.posts) for page in pages], [1, 1], "5% or more goes on")

    def test_an_address_crawl_waits_a_second_between_pages_unless_the_source_waits_longer(self):
        checkpoint = {"mode": "sitemap", "site": LINKS, "prefix": "/", "next_index": 0, "pages_fetched": 1,
                      "collected_posts": 0, "total_candidates": 2}
        self.assertEqual(GenericRssKind(FakeHttp()).min_page_delay, 1.0, "the default")
        for rate, kwargs, waits in ((RATE, {}, [1.0]), (RateLimit(0.25, 0, 0), {}, [0.75]),
                                    (RateLimit(3, 0, 0), {}, []), (RATE, {"min_page_delay": 0}, [])):
            sleeper = RecordingSleeper()
            kind = GenericRssKind(FakeHttp(link_blog(), sleep=sleeper), **kwargs)
            asyncio.run(pages_of(kind, source(LINKS_FEED), dict(checkpoint), rate))
            self.assertEqual(sleeper.calls, waits, (rate, kwargs))


class OlderPageDateTests(unittest.TestCase):
    def test_article_post_keeps_no_date_as_none(self):
        post = page_watch.article_post(article("x", None), BLOG_FEED, f"{BLOG}/x", None, adapter="t")
        self.assertIsNone(post["date"])

    def test_only_a_watched_pages_new_page_is_dated_now(self):
        page, url = article("x", None), f"{BLOG}/2003/07/a-note"
        self.assertIsNotNone(page_watch.post_from(page, BLOG, f"{BLOG}/a-note", None, new=True)["date"])
        self.assertIsNone(page_watch.post_from(page, BLOG, f"{BLOG}/a-note", None)["date"])
        self.assertEqual(page_watch.post_from(page, BLOG, url, None)["date"],
                         datetime(2003, 7, 1, tzinfo=timezone.utc), "its address's month")
        stated = page_watch.post_from(article("x", "2003-07-19T10:00:00Z"), BLOG, url, None)["date"]
        self.assertEqual(stated, datetime(2003, 7, 19, 10, tzinfo=timezone.utc), "the page's date first")

    def test_the_month_rule(self):
        hint = originals_rules.address_hint
        self.assertEqual(hint(f"{BLOG}/2003/07/a-note.html"), datetime(2003, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(hint(f"{BLOG}/2009/11/15/a-note"), datetime(2009, 11, 15, tzinfo=timezone.utc))
        self.assertEqual(hint(f"{BLOG}/2008/Jul/7/a-note"), datetime(2008, 7, 7, tzinfo=timezone.utc))
        self.assertIsNone(hint(f"{BLOG}/2023/a-note"), "a year alone: no guess")
        self.assertIsNone(hint(f"{BLOG}/a-note"))
        self.assertIsNone(hint(f"{BLOG}/2099/01/a-note"), "never ahead")
        self.assertIsNone(originals_rules.address_month(f"{BLOG}/2009/11/15/a-note"), "a day is no month alone")

    def test_an_archived_page_takes_its_addresss_month_before_the_lastmod(self):
        url = f"{LINKS}/2003/07/a-link"
        kind = GenericRssKind(FakeHttp({url: article("a link", None)}), min_page_delay=0)
        post = asyncio.run(kind._sitemap_post(source(LINKS_FEED), url, datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(post["date"], datetime(2003, 7, 1, tzinfo=timezone.utc))
        self.assertTrue(post[BACKLOG_KEY])

    def test_an_archive_apis_undated_post_stays_undated_or_takes_its_address(self):
        plain = archive_ladder.wordpress_post({"id": 1, "link": f"{BLOG}/a-note/", "title": {"rendered": "A"},
                                               "content": {"rendered": "<p>Body</p>"}}, BLOG_FEED)
        self.assertIsNone(plain["date"])
        self.assertTrue(plain[BACKLOG_KEY])
        dated = archive_ladder.wordpress_post({"id": 2, "link": f"{BLOG}/2009/11/a-note/", "title": {"rendered": "B"},
                                               "content": {"rendered": "<p>Body</p>"}}, BLOG_FEED)
        self.assertEqual(dated["date"], datetime(2009, 11, 1, tzinfo=timezone.utc))


@requires_test_db
class StoredBacklogTests(unittest.TestCase):
    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.oldest = datetime(2024, 5, 4, 12, tzinfo=timezone.utc)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = insert_source(cur, handle=f"https://own-{self.mark}.example/feed")
            insert_post(cur, self.source, f"https://own-{self.mark}.example/oldest", at=self.oldest)
            conn.commit()

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _row(self, url: str):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT published_at, surfaced_at FROM posts WHERE url = %s", (url,))
            return cur.fetchone()

    def test_each_archive_paths_undated_post_sorts_before_the_oldest(self):
        site = f"https://own-{self.mark}.example"
        sitemap_page = f"{site}/an-old-note/"
        kind = GenericRssKind(FakeHttp({sitemap_page: article("an old note", None)}), min_page_delay=0)
        from_sitemap = asyncio.run(kind._sitemap_post({"handle_or_url": f"{site}/feed"}, sitemap_page, None))
        from_api = archive_ladder.wordpress_post({"id": 9, "link": f"{site}/api-note/", "title": {"rendered": "A"},
                                                  "content": {"rendered": "<p>Body</p>"}}, f"{site}/feed")
        watched = page_watch.post_from(article("watched", None), site, f"{site}/watched-note/", None)
        watched[BACKLOG_KEY] = True   # the page watch's sitemap-only page and its archive's pages are backlog
        drafts = [PostDraft(self.source, post) for post in (from_sitemap, from_api, watched)]
        with psycopg.connect(db_url()) as conn:
            PostsRepository(db_url()).save_batch(conn, drafts)
        for url in (sitemap_page, f"{site}/api-note/", f"{site}/watched-note/"):
            published_at, surfaced_at = self._row(url)
            self.assertIsNone(published_at, url)
            self.assertLess(surfaced_at, self.oldest, url)

    def test_a_page_its_feed_missed_stays_undated_before_the_oldest_or_takes_its_addresss_month(self):
        site = f"https://own-{self.mark}.example"
        plain, monthly = f"{site}/a-missed-note", f"{site}/2003/07/a-missed-note"
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            # an undated post linking it: its fetch time is no date for the missed page (first_linked)
            linker = insert_post(cur, self.source, f"{site}/linker", links=[plain])
            cur.execute("UPDATE posts SET published_at = NULL WHERE id = %s", (linker,))
            conn.commit()
        http = FakeHttp({plain: article("missed", None), monthly: article("missed", None)})
        service = SavedService(db_url(), sources=None, source_config_sync=None, kinds=None)
        self.assertEqual(asyncio.run(service.collect_for_source(http, plain, self.source))["status"], "collected")
        published_at, surfaced_at = self._row(plain)
        self.assertIsNone(published_at)
        self.assertLess(surfaced_at, self.oldest)
        asyncio.run(service.collect_for_source(http, monthly, self.source))
        self.assertEqual(self._row(monthly)[0], datetime(2003, 7, 1, tzinfo=timezone.utc))

    def test_0101_dates_the_posts_stored_at_their_fetch_by_their_address(self):
        site = f"https://dated-{self.mark}.example"
        fetched = datetime(2026, 11, 9, 8, 30, tzinfo=timezone.utc)
        rows = {  # url -> (published_at, the date 0101 leaves)
            f"{site}/2003/07/a-month": (fetched, datetime(2003, 7, 1, tzinfo=timezone.utc)),
            f"{site}/2009/11/15/a-day": (fetched, datetime(2009, 11, 15, tzinfo=timezone.utc)),
            f"{site}/2008/Jul/7/a-named-day": (fetched, datetime(2008, 7, 7, tzinfo=timezone.utc)),
            f"{site}/2023/a-year-alone": (fetched, fetched),
            f"{site}/2026/11/this-month": (fetched, fetched),
            f"{site}/2020/02/31/no-such-day": (fetched, fetched),
            f"{site}/2015/03/a-feeds-date": (fetched - timedelta(hours=3), fetched - timedelta(hours=3)),
        }
        sql = MIGRATION.read_text()
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            for url, (published, _) in rows.items():
                post = insert_post(cur, self.source, url, at=published)
                cur.execute("UPDATE posts SET fetched_at = %s, surfaced_at = %s WHERE id = %s", (fetched, fetched, post))
            for _ in range(2):   # a second run changes nothing more
                cur.execute(sql)
            cur.execute("SELECT url, published_at, published_precision, surfaced_at FROM posts WHERE url LIKE %s",
                        (f"{site}/%",))
            got = {url: (published, precision, surfaced) for url, published, precision, surfaced in cur.fetchall()}
            conn.rollback()
        for url, (_, expected) in rows.items():
            self.assertEqual(got[url][0], expected, url)
            if expected != rows[url][0]:
                self.assertEqual((got[url][1], got[url][2]), ("date", None), url)


if __name__ == "__main__":
    unittest.main()
