"""Discover counts in the database (issue 0062): the list is exactly the one the Python walk over
every kept link gave (0050, 0051), and discover_addresses is filled by the story job, by Discover
when an address is missing, and again when the rules change.

The oracle is the old walk itself (`reference_discover`, kept here as it was): every test compares
the service's whole list with it, on the whole test database, after adding rows that hit the edges
(platform accounts and pages that name none, lowercasing beyond ASCII, a host with a port, the
40% share exactly and just under, Reddit authors as voices, a site two sources share, titles on a tie,
more than 20 articles, a classic, a followed site and a hidden key).
"""
from __future__ import annotations

import sys
import unittest
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_discover import ADDRESS_RULES, DiscoverRepository
from insight_core.db.repo_news import NewsRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services.stories_service import DISCOVER_ARTICLES_SHOWN, StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.utils.post_links import reddit_author
from insight_core.utils.story_rules import StoryPost, discover_address, suggestions


def reference_discover(url: str):
    """Discover as 0050/0051 computed it: every kept link read into Python and walked."""
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        sources = SourceFacts(cur)
        cur.execute(
            """
            SELECT p.id, p.source_id, pl.target_url, pl.link_text,
                   CASE WHEN p.source_id = ANY(%s::uuid[]) THEN p.content_html END
            FROM post_links pl JOIN posts p ON p.id = pl.post_id
            WHERE NOT pl.boilerplate ORDER BY p.id, pl.position
            """,
            (sources.html_sources(),),
        )
        authors = {}
        links = []
        for post_id, source_id, target, text, content_html in cur.fetchall():
            if post_id not in authors:
                authors[post_id] = reddit_author(content_html) if content_html else None
            links.append({"source_id": str(source_id), "url": target, "text": text, "author": authors[post_id]})
        hidden = StoriesRepository.hidden(cur)
        classic_urls = set(NewsRepository.classic_urls(cur))
    pairs, names = [], {}
    linked_by, texts = defaultdict(set), defaultdict(Counter)
    for link in links:
        p = StoryPost(id="", source_id=link["source_id"], kind=sources.kind.get(link["source_id"], "site"),
                      own_site=sources.own_site(link["source_id"]), t=datetime.min, author=link["author"])
        names.setdefault(p.voice, sources.voice_name(p.voice, link["source_id"]))
        pairs.append((p.voice, link["url"]))
        linked_by[link["url"]].add(p.voice)
        if link["text"]:
            texts[link["url"]][link["text"]] += 1
    found = suggestions(pairs, followed=sources.followed(), hidden=hidden, followed_accounts=sources.followed_accounts())
    held = {s.key: len(s.addresses & classic_urls) for s in found}
    found = sorted(found, key=lambda s: held[s.key] == 0)
    return [{
        "key": s.key, "url": "https://" + s.key, "voices": len(s.voices),
        "voice_names": sorted(names[v] for v in s.voices), "article_count": len(s.articles),
        "link_count": s.links, "classics": held[s.key],
        "articles": [{"url": u, "title": texts[u].most_common(1)[0][0] if texts[u] else None,
                      "linked_by": sorted(names[v] for v in linked_by[u])}
                     for u in sorted(s.articles, key=lambda u: (-len(linked_by[u]), u))[:DISCOVER_ARTICLES_SHOWN]],
    } for s in found]


@requires_test_db
class DiscoverCountsTests(unittest.TestCase):
    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self._clean)
        delete_scratch_sources(self.cur)
        self.conn.commit()

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM discover_hidden WHERE key LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM classics WHERE target_url LIKE %s", (f"%{self.mark}%",))
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.conn.commit()
        self.conn.close()

    # ---- fixture ----------------------------------------------------------------------------

    def _source(self, name, *, platform="rss"):
        source = insert_scratch_source(self.cur, platform=platform)
        self.cur.execute("UPDATE sources SET settings = jsonb_build_object('display_name', %s::text) WHERE id = %s",
                         (name, source))
        return source

    def _post(self, source, host, links, *, html=""):
        """A post on `host` whose kept links are `links`: (address, words) pairs, in order."""
        url = f"https://{host}/p/{uuid.uuid4().hex}"
        self.cur.execute(
            "INSERT INTO posts (source_id, url, normalized_url, url_host, content_html, published_at, links_scanned_at) "
            "VALUES (%s, %s, %s, %s, %s, now(), now()) RETURNING id", (source, url, url, host, html))
        post_id = self.cur.fetchone()[0]
        for position, (target, text) in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, link_text) "
                             "VALUES (%s, %s, '', %s, %s)", (post_id, target, position, text))
        return post_id

    def _edges(self):
        m = self.mark
        a, b, c = (self._source(f"Voice {n} {m}") for n in "ABC")
        shared = self._source(f"Also A {m}")          # posts on A's site: one voice with A
        reddit = self._source(f"r/sub {m}", platform="reddit")
        for source, host in ((a, f"a-{m}.example"), (b, f"b-{m}.example"), (c, f"c-{m}.example"),
                             (shared, f"a-{m}.example")):
            self._post(source, host, [])
        cited = [f"https://cited-{m}.example/2026/10/story-{k}" for k in range(25)]   # more than 20 articles
        edge = [f"https://edge-{m}.example/{'the-long-slug-' if k < 6 else 'page'}{k}" for k in range(15)]
        just = [f"https://just-{m}.example/{'a-b-c-d-' if k < 2 else 'x'}{k}" for k in range(5)]
        under = [f"https://under-{m}.example/{'a-b-c-d-' if k < 2 else 'x'}{k}" for k in range(6)]
        account = [f"https://x.com/Karp{m}/status/{k}-a-long-slug-here" for k in range(3)]
        page = [f"https://x.com/i/{m}-a-long-slug-here-{k}" for k in range(3)]       # names no account
        unicode = [f"https://youtube.com/@ТЕСТ{m}/видео-a-b-c-d-{k}" for k in range(3)]
        ported = [f"https://port-{m}.example:8080/2026/10/p{k}" for k in range(3)]
        uk = [f"https://news.paper-{m}.co.uk/2026/10/p{k}" for k in range(3)]
        followed = [f"https://b-{m}.example/2026/10/p{k}" for k in range(3)]      # B's own site
        hidden = [f"https://hidden-{m}.example/2026/10/p{k}" for k in range(3)]
        everything = cited + edge + just + under + account + page + unicode + ported + uk + followed + hidden
        self._post(a, f"a-{m}.example", [(u, "Story" if i % 3 else "Other") for i, u in enumerate(everything)])
        self._post(b, f"b-{m}.example", [(u, "Other") for u in cited[:10] + edge + just + under + account + page + unicode
                                         + ported + uk + followed + hidden])
        self._post(c, f"c-{m}.example", [(u, None) for u in cited[:3] + edge + just + under + account + page + unicode
                                         + ported + uk + followed + hidden])
        self._post(shared, f"a-{m}.example", [(cited[0], "Story")])
        for author in ("Alice", "bob"):
            html = f'submitted by &#32; <a href="https://www.reddit.com/user/{author}"> /u/{author} </a>'
            self._post(reddit, f"reddit.com", [(cited[0], "Story"), (cited[1], "")], html=html)
        self.cur.execute("INSERT INTO discover_hidden (key, reason) VALUES (%s, 'not_interested')", (f"hidden-{m}.example",))
        self.cur.execute("INSERT INTO classics (target_url, voices, first_at, last_at) VALUES (%s, 3, now(), now())",
                         (just[0],))
        self.conn.commit()
        return {"a": a, "shared": shared}

    def _discover(self):
        return StoriesService(db_url()).discover()["suggestions"]

    # ---- the list ---------------------------------------------------------------------------

    def test_the_list_is_the_python_walks_in_content_and_order(self):
        self._edges()
        got = self._discover()
        self.assertEqual(got, reference_discover(db_url()))
        m = self.mark
        keys = {s["key"]: s for s in got}
        cited = keys[f"cited-{m}.example"]
        self.assertEqual(len(cited["articles"]), DISCOVER_ARTICLES_SHOWN, "the top 20 of 25")
        self.assertIn("u/alice", cited["voice_names"], "a Reddit author is a voice, lowercase")
        self.assertIn("u/bob", cited["voice_names"])
        self.assertIn(f"just-{m}.example", keys, "2 articles of 5 addresses: 40% exactly")
        self.assertIn(f"edge-{m}.example", keys, "6 of 15: 40% exactly")
        self.assertNotIn(f"under-{m}.example", keys, "2 of 6 is under 40%")
        self.assertIn(f"x.com/karp{m}", keys, "a platform suggests the account")
        self.assertFalse([k for k in keys if k.startswith("x.com/i")], "a page that names no account")
        self.assertIn(f"youtube.com/@тест{m}", keys, "lowercase beyond ASCII, as Python's")
        self.assertIn(f"port-{m}.example:8080", keys)
        self.assertNotIn(f"b-{m}.example", keys, "a site you follow")
        self.assertNotIn(f"hidden-{m}.example", keys, "a key you hid")
        self.assertEqual(got[0]["classics"] > 0, True, "a suggestion holding a classic leads")

    def test_a_site_two_sources_share_is_named_after_its_first_link(self):
        ids = self._edges()
        got = {s["key"]: s for s in self._discover()}[f"cited-{self.mark}.example"]
        self.cur.execute("SELECT min(id::text) FROM posts WHERE source_id IN (%s, %s) AND EXISTS "
                         "(SELECT 1 FROM post_links WHERE post_id = posts.id)", (ids["a"], ids["shared"]))
        first = self.cur.fetchone()[0]
        self.cur.execute("SELECT settings->>'display_name' FROM sources s JOIN posts p ON p.source_id = s.id "
                         "WHERE p.id = %s", (first,))
        name = self.cur.fetchone()[0]
        self.assertIn(name, got["voice_names"])
        self.assertEqual(len([n for n in got["voice_names"] if self.mark in n and n != f"r/sub {self.mark}"]), 3,
                         "A and the source on its site are one voice")

    # ---- discover_addresses -----------------------------------------------------------------

    def test_discover_fills_the_addresses_it_finds_missing(self):
        self._edges()
        target = f"https://cited-{self.mark}.example/2026/10/story-0"
        self.cur.execute("DELETE FROM discover_addresses WHERE url = %s", (target,))
        self.conn.commit()
        self.assertEqual(self._discover(), reference_discover(db_url()))
        self.cur.execute("SELECT key, site, platform, article, rules FROM discover_addresses WHERE url = %s", (target,))
        self.assertEqual(self.cur.fetchone(), (f"cited-{self.mark}.example", f"cited-{self.mark}.example",
                                               False, True, ADDRESS_RULES))

    def test_the_story_job_fills_them_after_reading_links(self):
        self._edges()
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.conn.commit()
        StoriesService(db_url()).recompute()
        self.cur.execute("SELECT count(*) FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.assertGreater(self.cur.fetchone()[0], 50)
        self.cur.execute("SELECT count(*) FROM (SELECT DISTINCT target_url FROM post_links WHERE NOT boilerplate "
                         "EXCEPT SELECT url FROM discover_addresses) missing")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_a_row_of_older_rules_is_worked_out_again(self):
        self._edges()
        target = f"https://x.com/Karp{self.mark}/status/0-a-long-slug-here"
        DiscoverRepository.fill_addresses(self.cur)
        self.cur.execute("UPDATE discover_addresses SET key = 'wrong', rules = 'old' WHERE url = %s", (target,))
        self.conn.commit()
        self.assertEqual(self._discover(), reference_discover(db_url()))
        self.cur.execute("SELECT key, rules FROM discover_addresses WHERE url = %s", (target,))
        self.assertEqual(self.cur.fetchone(), (f"x.com/karp{self.mark}", ADDRESS_RULES))

    def test_an_address_no_link_points_to_is_dropped(self):
        self._edges()
        gone = f"https://gone-{self.mark}.example/2026/10/a"
        self.cur.execute("INSERT INTO discover_addresses (url, key, site, platform, article, rules) "
                         "VALUES (%s, 'x', 'x', false, true, %s)", (gone, ADDRESS_RULES))
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%cited-{self.mark}%",))
        DiscoverRepository.fill_addresses(self.cur)   # it adds the missing, then drops the unlinked
        self.cur.execute("SELECT count(*) FROM discover_addresses WHERE url = %s", (gone,))
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_discover_address_is_the_rules_of_suggestions(self):
        self.assertEqual(discover_address("https://x.com/Karp/status/1"), ("x.com/karp", "x.com", True))
        self.assertEqual(discover_address("https://x.com/i/web/status/1"), (None, "x.com", True))
        self.assertEqual(discover_address("https://reddit.com/r/LocalLLaMA/comments/x"),
                         ("reddit.com/r/localllama", "reddit.com", True))
        self.assertEqual(discover_address("https://news.paper.co.uk/a"), ("news.paper.co.uk", "paper.co.uk", False))


if __name__ == "__main__":
    unittest.main()
