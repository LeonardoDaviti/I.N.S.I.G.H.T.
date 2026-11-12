"""Titles of pages you don't follow (issue 0106): one url -> title map per Discover answer (articles, origin
lines and archive lines alike), Classics titled by the same evidence and read the same once-only way,
the reads keep Discover's kept list kept, and a paper id is one page on its host whatever its path.
Fixtures only: nothing is fetched (a fake fetcher answers the reads).
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_discover import READS_KEY, DiscoverRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.ingestion.kinds import KindRegistry
from insight_core.services import discover_reads, stories_service
from insight_core.services.news_service import NewsService
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests._stories import insert_post, insert_source, story_post
from insight_core.tests.test_feed_finder import page, rss
from insight_core.utils.addresses import paper_id, paper_page_order
from insight_core.utils.story_rules import group, keys, page_aliases, page_key

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
DAY = datetime(2026, 10, 29, tzinfo=timezone.utc)
post = partial(story_post, at=DAY)


class PaperIdTests(unittest.TestCase):
    """0080's paper-source shapes, as one page: every shape seen on the lab, on hosts nobody named."""

    def test_every_path_of_a_preprint_is_one_paper(self):
        for url in ("https://preprints.example/abs/2005.14165", "https://preprints.example/pdf/2005.14165",
                    "https://preprints.example/pdf/2005.14165v2", "https://preprints.example/abs/2005.14165v3",
                    "https://preprints.example/html/2005.14165v1", "https://preprints.example/pdf/2005.14165.pdf",
                    "https://preprints.example/abs/2005.14165?_hsenc=tracking", "https://mirror.example/overview/2005.14165"):
            self.assertEqual(paper_id(url), "2005.14165", url)
        self.assertEqual(paper_id("https://hub.example/papers/2501.12948"), "2501.12948")

    def test_every_path_of_a_doi_is_one_paper(self):
        for url in ("https://publisher.example/doi/10.1145/3604915.3608827", "https://publisher.example/doi/abs/10.1145/3604915.3608827",
                    "https://publisher.example/doi/full/10.1145/3604915.3608827", "https://publisher.example/doi/epdf/10.1145/3604915.3608827",
                    "https://publisher.example/doi/pdf/10.1145/3604915.3608827"):
            self.assertEqual(paper_id(url), "10.1145/3604915.3608827", url)
        self.assertEqual(paper_id("https://resolver.example/10.48550/ARXIV.2604.07729"),
                         paper_id("https://resolver.example/10.48550/arXiv.2604.07729"), "a DOI's case is no other paper")
        for url in ("https://bio.example/content/10.1101/2025.02.18.638918v1", "https://bio.example/content/10.1101/2025.02.18.638918v2.full.pdf",
                    "https://bio.example/content/10.1101/2025.02.18.638918.full"):
            self.assertEqual(paper_id(url), "10.1101/2025.02.18.638918", url)

    def test_look_alikes_are_no_paper(self):
        for url in ("https://news.example/2026/10/a-story", "https://news.example/2024.10001/comments",
                    "https://blog.example/2401.12345-notes", "https://blog.example/posts/10.1145",
                    "https://a.example/one/two/three/2401.12345", "https://store.example/v1.2345", "https://preprints.example"):
            self.assertIsNone(paper_id(url), url)

    def test_the_page_names_the_paper_before_its_file(self):
        urls = ["https://preprints.example/pdf/2005.14165", "https://preprints.example/abs/2005.14165?_hsenc=x",
                "https://preprints.example/html/2005.14165v1", "https://preprints.example/abs/2005.14165"]
        self.assertEqual(min(urls, key=paper_page_order), "https://preprints.example/abs/2005.14165")
        self.assertEqual(min(["https://publisher.example/doi/pdf/10.1/x", "https://publisher.example/doi/full/10.1/x"],
                             key=paper_page_order), "https://publisher.example/doi/full/10.1/x")


class PaperOnePageInStoriesTests(unittest.TestCase):
    ABS, PDF = "https://preprints.example/abs/2601.01234", "https://preprints.example/pdf/2601.01234v2"

    def test_links_to_its_abstract_and_its_pdf_are_one_page(self):
        a = post("a", "s1", links=[(self.ABS, None)])
        b = post("b", "s2", hours=2, links=[(self.PDF, None)])
        self.assertEqual(page_aliases([a, b]), {self.PDF: self.ABS})
        [story] = group([a, b])
        self.assertEqual(({p.id for p in story.posts}, story.origin_url), ({"a", "b"}, self.ABS))
        self.assertEqual(page_key(self.ABS), page_key(self.PDF))
        self.assertIn(page_key(self.ABS), keys(b), "the incremental job reads every post linking any of its paths")

    def test_a_stored_page_of_the_paper_is_the_page(self):
        own = post("own", "feed", url="https://preprints.example/abs/2601.01234", home="preprints.example", site="preprints.example")
        a = post("a", "s1", hours=1, links=[(self.PDF, None)])
        b = post("b", "s2", hours=2, links=[("https://preprints.example/html/2601.01234v1", None)])
        self.assertEqual(page_aliases([own, a, b]), {self.PDF: own.url, "https://preprints.example/html/2601.01234v1": own.url})
        [story] = group([own, a, b])
        self.assertEqual((story.posts[0].id, story.origin_url), ("own", None))

    def test_another_paper_or_another_host_is_another_page(self):
        a = post("a", "s1", links=[(self.ABS, None)])
        b = post("b", "s2", hours=2, links=[("https://preprints.example/pdf/2601.01235", None)])
        c = post("c", "s3", hours=3, links=[("https://mirror.example/abs/2601.01234", None)])
        self.assertEqual(page_aliases([a, b, c]), {})
        self.assertEqual(group([a, b, c]), [])


class WorkTests(unittest.TestCase):
    def test_the_reads_include_origin_and_archive_lines_and_classics(self):
        first = [{"key": "a.example", "articles": [{"url": "https://a.example/1", "title": None}],
                  "origin_stories": [{"url": "https://a.example/1", "title": None}, {"url": "https://a.example/2", "title": None},
                                     {"url": "https://a.example/3", "title": "Has one"}]}]
        archives = [{"origin_stories": [{"url": "https://b.example/old-1", "title": None},
                                        {"url": "https://x.com/u/status/2111872584338018562", "title": None}]}]
        classics = ["https://c.example/essay", "https://b.example/old-1"]
        reads = {"follow": {"a.example": {"label": "feed", "at": NOW.isoformat(), "test": discover_reads.FOLLOW_TEST}},
                 "titles": {"https://c.example/essay": {"title": None, "at": (NOW - timedelta(days=31)).isoformat()}}}
        self.assertEqual(discover_reads.work(first, reads, NOW, archives=archives, classics=classics),
                         {"follow": [], "titles": ["https://a.example/1", "https://a.example/2", "https://b.example/old-1",
                                                   "https://c.example/essay"]},
                         "each page once; a titled line, a tweet and a page read within 30 days aren't asked")


@requires_test_db
class ReadBatchTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (READS_KEY,))
        row = self.cur.fetchone()
        self.addCleanup(self._restore, row[0] if row else None)

    def _restore(self, value):
        self.conn.rollback()
        if value is None:
            self.cur.execute("DELETE FROM system_settings WHERE key = %s", (READS_KEY,))
        else:
            DiscoverRepository.keep_reads(self.cur, value)
        self.conn.commit()
        self.conn.close()

    def test_a_batch_reads_origin_archive_and_classic_pages_then_keeps_the_list_once(self):
        m = uuid.uuid4().hex[:8]
        key = f"site-{m}.example"
        origin, old, essay = f"https://{key}/2026/10/a", f"https://old-{m}.example/index/b", f"https://essays-{m}.example/c"
        first = [{"key": key, "articles": [], "origin_stories": [{"url": origin, "title": None}]}]
        opened = []

        def discover(limit=None):
            opened.append(limit)
            return {"suggestions": first, "archives": [{"origin_stories": [{"url": old, "title": None}]}]}

        stories = SimpleNamespace(db_url=db_url(), discover=discover, refresh=lambda: opened.append("refresh"),
                                  linked_articles=lambda address: [],
                                  untitled_classics=lambda: [essay])
        responses = {f"https://{key}/": page('<link rel="alternate" type="application/rss+xml" href="/feed.xml">'),
                     f"https://{key}/feed.xml": rss("Site"),
                     origin: "<html><head><title>The origin</title></head></html>",
                     old: "<html><head><title>The archive's page</title></head></html>",
                     essay: "<html><head><title>The essay</title></head></html>"}
        http = FakeHttp(responses)
        got = asyncio.run(discover_reads.read_first_page(stories, http, KindRegistry.default(http, None), clock=lambda: NOW))
        self.assertEqual(got, {"follow": 1, "titles": 3})
        self.cur.execute("SELECT 1")
        titles = DiscoverRepository.reads(self.cur)["titles"]
        self.assertEqual({u: titles[u]["title"] for u in (origin, old, essay)},
                         {origin: "The origin", old: "The archive's page", essay: "The essay"})
        self.assertEqual(opened, [None, "refresh"], "the first page, then the answer built and kept once at the batch's end (0172)")
        again = asyncio.run(discover_reads.read_first_page(stories, http, KindRegistry.default(http, None),
                                                           clock=lambda: NOW + timedelta(days=1)))
        self.assertEqual((again, len(opened)), ({"follow": 0, "titles": 0}, 3), "nothing read: nothing kept again")


@requires_test_db
class DiscoverTitleMapTests(unittest.TestCase):
    """On the database, through the service (it opens its own connections), as test_discover_origins."""

    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (READS_KEY,))
        row = self.cur.fetchone()
        self.reads = row[0] if row else None
        self.addCleanup(self._clean)

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM sources WHERE handle_or_url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM stories WHERE origin_url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        if self.reads is None:
            self.cur.execute("DELETE FROM system_settings WHERE key = %s", (READS_KEY,))
        else:
            DiscoverRepository.keep_reads(self.cur, self.reads)
        self.conn.commit()
        self.conn.close()

    def _post(self, source, url, links=(), *, days=0):
        return insert_post(self.cur, source, url, at=datetime(2026, 10, 31, tzinfo=timezone.utc) - timedelta(days=days),
                           normalized=url, links=list(links))

    def _voices(self, n=3):
        out = []
        for k in range(n):
            source = insert_source(self.cur, f"Voice {k} {self.mark}")
            host = f"voice{k}-{self.mark}.example"
            self._post(source, f"https://{host}/p/home")
            out.append((source, host))
        return out

    def _cite(self, voices, origin, words=None):
        """Each voice posts once linking `origin` (the first with `words`); one story rooted there, untitled."""
        posts = [(self._post(source, f"https://{host}/p/{uuid.uuid4().hex}", [(origin, words if not n else None)]),
                  f"site:{host}") for n, (source, host) in enumerate(voices)]
        story = posts[0][0]
        self.cur.execute("INSERT INTO stories (id, first_at, voices, origin_url, origin_linked_by) VALUES (%s, now(), %s, %s, %s)",
                         (story, len(posts), origin, len(posts)))
        for post_id, voice in posts:
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_reason, parent_url) "
                             "VALUES (%s, %s, 'report', %s, 'citation', %s)", (post_id, story, voice, origin))

    def _discover(self):
        self.conn.commit()
        return StoriesService(db_url()).discover()

    def test_one_title_per_page_in_an_answer(self):
        m = self.mark
        voices = self._voices(3)
        site, feed_site = f"wire-{m}.example", f"newsroom-{m}.example"
        pages = [f"https://{site}/world/agents-hijacked-a-website-{n}" for n in range(2)]
        self._cite(voices, pages[0], "Agents took over a website in a breakout")
        self._cite(voices, pages[1])
        feed = insert_source(self.cur, f"Newsroom {m}", handle=f"https://{feed_site}/news/rss.xml")
        self._post(feed, f"https://{feed_site}/index/recent")
        older = [f"https://{feed_site}/index/older-{n}" for n in range(2)]
        self._cite(voices, older[0], "The newsroom's older launch")
        self._cite(voices, older[1])
        result = self._discover()
        [s] = [s for s in result["suggestions"] if s["key"] == site]
        articles = {a["url"]: a["title"] for a in s["articles"]}
        lines = {o["url"]: o["title"] for o in s["origin_stories"]}
        self.assertEqual(articles[pages[0]], "Agents took over a website in a breakout")
        self.assertEqual(lines[pages[0]], articles[pages[0]], "the story it started reads as its article does")
        [missing] = [a for a in result["archives"] if a["source_id"] == feed]
        self.assertEqual({o["url"]: o["title"] for o in missing["origin_stories"]},
                         {older[0]: "The newsroom's older launch", older[1]: None}, "an archive line, by the same map")

        reads = DiscoverRepository.reads(self.cur)
        reads.setdefault("titles", {}).update({u: {"title": f"Read {n}", "at": NOW.isoformat()}
                                               for n, u in enumerate((pages[1], older[1], pages[0]))})
        DiscoverRepository.keep_reads(self.cur, reads)
        result = self._discover()
        [s] = [s for s in result["suggestions"] if s["key"] == site]
        self.assertEqual({o["url"]: o["title"] for o in s["origin_stories"]},
                         {pages[0]: "Agents took over a website in a breakout", pages[1]: "Read 0"},
                         "a read fills a page with no title, never over the stored data's")
        self.assertEqual({a["url"]: a["title"] for a in s["articles"]}[pages[1]], "Read 0")
        [missing] = [a for a in result["archives"] if a["source_id"] == feed]
        self.assertEqual({o["url"]: o["title"] for o in missing["origin_stories"]}[older[1]], "Read 1")

    def test_a_read_batch_keeps_the_list_for_the_next_process(self):
        """0080 cold open: the reads change Discover's inputs; the batch keeps the list it changed, so a fresh
        process's first open reads one row and makes nothing."""
        m = self.mark
        voices = self._voices(3)
        site = f"kept-{m}.example"
        for n in range(2):
            self._cite(voices, f"https://{site}/2026/10/page-{n}")
        self.conn.commit()
        service = StoriesService(db_url())
        service.discover()
        http = FakeHttp(lambda url: ValueError(f"HTTP 404 while fetching {url}"))   # every read fails: stored all the same
        asyncio.run(discover_reads.read_first_page(service, http, KindRegistry.default(http, None), clock=lambda: NOW))
        built = []

        class Counting(SourceFacts):
            def __init__(self, cur):
                built.append(1)
                super().__init__(cur)

        with mock.patch.object(stories_service, "SourceFacts", Counting):
            got = StoriesService(db_url()).discover()
        self.assertEqual(built, [], "the next open, in another process, reads the kept list")
        [s] = [s for s in got["suggestions"] if s["key"] == site]
        self.assertIn("follow_test", s, "the list kept is the one the reads made")


@requires_test_db
class ClassicsTitleAndPaperTests(unittest.TestCase):
    """Classics count a paper's paths once (a full run and a batch alike), titled by the evidence a story's
    outside origin is titled by; a read fills an untitled one."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.mark = uuid.uuid4().hex[:8]
        self.news = NewsService(db_url(), clock=lambda: self.now)
        self.service = StoriesService(db_url(), clock=lambda: self.now, news=self.news)
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (READS_KEY,))
        row = self.cur.fetchone()
        self.reads = row[0] if row else None

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def _source(self, name):
        return insert_source(self.cur, f"{name} {self.mark}", in_main_digest=True, followed_days=900)

    def _cite(self, source, url, *, days, words="read"):
        host = f"{uuid.uuid4().hex[:8]}-{self.mark}.test"
        return str(insert_post(self.cur, source, f"https://{host}/{uuid.uuid4().hex}", at=self.now - timedelta(days=days),
                               title="A post", content="Body", html=f'<p><a href="{url}">{words}</a></p>',
                               content_hash=uuid.uuid4().hex, host=host))

    def _fill(self):
        while StoriesRepository().fill_missing_links(self.cur):
            pass

    def _mine(self):
        return {c["url"]: c for c in self.news.classics_on(self.cur, "all")["classics"] if self.mark in c["url"]}

    def test_a_papers_paths_are_one_classic(self):
        abs_, pdf = f"https://preprints-{self.mark}.test/abs/2005.14165", f"https://preprints-{self.mark}.test/pdf/2005.14165"
        x, y, z = (self._source(n) for n in ("Xeno", "Yolk", "Zinc"))
        self._cite(x, abs_, days=400)
        self._cite(y, pdf, days=300, words="12,288 numbers long")
        self._cite(z, abs_ + "?_hsenc=tracking", days=100)
        self._fill()
        self.service.full_on(self.cur)
        mine = self._mine()
        self.assertEqual(list(mine), [abs_], "no classic at its PDF")
        self.assertEqual(mine[abs_]["voices"], 3)

        later = self._source("Later")
        self._cite(later, f"https://preprints-{self.mark}.test/html/2005.14165v1", days=1)
        self._fill()
        self.service.update(self.cur)
        mine = self._mine()
        self.assertEqual((list(mine), mine[abs_]["voices"]), ([abs_], 4), "a batch counts every path of the paper")
        rebuilt = self.service.full_on(self.cur)
        self.assertEqual(rebuilt["classics_changed"], 0, "a full run over the same posts changes nothing")

    def test_a_classic_is_titled_by_the_evidence_and_a_read_fills_an_untitled_one(self):
        page = f"https://essays-{self.mark}.test/research/sparse-routing-at-scale"
        bare = f"https://essays-{self.mark}.test/research/x1"
        a, b, c = (self._source(n) for n in ("Alpha", "Beta", "Gamma"))
        for days in (400, 390, 380):
            self._cite(a, page, days=days, words="Smith et al., 2024")
        self._cite(b, page, days=200, words="Sparse Routing at Scale")
        self._cite(c, page, days=10, words="Sparse Routing at Scale")
        self._cite(a, bare, days=400)
        self._cite(b, bare, days=300)
        self._cite(c, bare, days=10)
        self._fill()
        self.service.full_on(self.cur)
        mine = self._mine()
        self.assertEqual(mine[page]["title"], "Sparse Routing at Scale", "words 2 voices agree on, over one voice's thrice")
        self.assertIsNone(mine[bare]["title"])
        self.assertIn(bare, self.news.untitled_classics(self.cur))
        self.assertNotIn(page, self.news.untitled_classics(self.cur))
        reads = DiscoverRepository.reads(self.cur)
        reads.setdefault("titles", {}).update({bare: {"title": "The page's own title", "at": NOW.isoformat()},
                                               page: {"title": "Never over the evidence", "at": NOW.isoformat()}})
        DiscoverRepository.keep_reads(self.cur, reads)
        mine = self._mine()
        self.assertEqual((mine[bare]["title"], mine[page]["title"]), ("The page's own title", "Sparse Routing at Scale"))


if __name__ == "__main__":
    unittest.main()
