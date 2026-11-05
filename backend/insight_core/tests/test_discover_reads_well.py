"""Discover that reads well (issue 0080): owners on the platforms the data finds, references and paper
sources set apart, a site you follow never suggested (and an aggregator follows no site), no voice for
Saved or a source's link to its own page, sources counted as followed, the measured order, one page at
a time, and no title made from an address.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_stories import SourceFacts
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_post, insert_source
from insight_core.utils.discover_rules import (discover_address, find_platforms, is_self_link, place_kind, platform_key,
                                               platform_rows, score)
from insight_core.utils.tree_rules import origin_title, slug_title


def owners(host, n, *, prefix="", voices=("v1",), deep=True):
    """Links to n owners' pages on a host: (voice, address)."""
    return [(v, f"https://{host}/{prefix}owner{k}/{'page/1' if deep else ''}") for k in range(n) for v in voices]


class PlatformRuleTests(unittest.TestCase):
    def test_many_owners_each_linked_by_different_voices_make_a_platform(self):
        links = owners("hub.example", 50) + [("v2", "https://hub.example/owner0/x"), ("v3", "https://hub.example/owner1/y"),
                                              ("v2", "https://hub.example/owner1/z")]
        self.assertEqual(find_platforms(platform_rows(links)), {"hub.example": ()})

    def test_owners_that_one_voice_links_alone_make_no_platform(self):
        links = owners("hub.example", 60) + [("v2", "https://hub.example/other/a"), ("v3", "https://hub.example/more/b")]
        self.assertEqual(find_platforms(platform_rows(links)), {}, "no owner is linked by 2+ voices")

    def test_a_publication_by_section_is_no_platform(self):
        sections = ["news", "tech", "world", "business", "science"] * 4
        links = [(f"v{k % 4}", f"https://paper.example/{s}/{2026}/story-{k}") for k, s in enumerate(sections * 5)]
        self.assertEqual(find_platforms(platform_rows(links)), {})

    def test_a_prefix_most_pages_share_moves_the_owner_down(self):
        links = [(v, f"https://social.example/profile/user{k}/post/{k}") for k in range(20) for v in ("v1", "v2")]
        links += [("v3", "https://social.example/about/x")]
        self.assertEqual(find_platforms(platform_rows(links)), {"social.example": ("profile",)})
        self.assertEqual(platform_key("https://social.example/profile/User3/post/1", ("profile",)), "social.example/profile/user3")
        self.assertIsNone(platform_key("https://social.example/about/x", ("profile",)), "outside the prefix")

    def test_the_owner_may_sit_at_the_third_segment(self):
        links = [(v, f"https://blogs.example/ru/companies/co{k}/articles/{k}") for k in range(20) for v in ("v1", "v2")]
        links += [("v3", "https://blogs.example/ru/news/1")]
        self.assertEqual(find_platforms(platform_rows(links)), {"blogs.example": ("ru", "companies")})

    def test_two_shared_segments_hold_documents_not_owners(self):
        links = [(v, f"https://agency.example/government/publications/doc{k}/doc{k}-html") for k in range(20) for v in ("v1", "v2")]
        links += [("v3", "https://agency.example/government/news/a-release")]
        self.assertEqual(find_platforms(platform_rows(links)), {})

    def test_ids_numbers_and_kinds_of_page_are_no_owners(self):
        links = [(v, f"https://forum.example/posts/{k}a1b2c3d4e5/slug") for k in range(60) for v in ("v1", "v2", "v3")]
        self.assertEqual(find_platforms(platform_rows(links)), {})
        self.assertIsNone(platform_key("https://hub.example/spaces/org/app", ()), "a kind of page")
        self.assertEqual(discover_address("https://hub.example/Org/model", {"hub.example": ()}),
                         ("hub.example/org", "hub.example", True))
        self.assertEqual(discover_address("https://hub.example/Org/model"), ("hub.example", "hub.example", False))

    def test_a_link_to_ones_own_page_is_a_self_link(self):
        self.assertTrue(is_self_link("https://creators.example/alice/posts/1", {"alice"}))
        self.assertTrue(is_self_link("https://social.example/@alice/1", {"alice"}))
        self.assertFalse(is_self_link("https://creators.example/bob/posts/1", {"alice"}))
        links = [(f"v{k}", f"https://creators.example/v{k}/posts/{k}") for k in range(60)]
        self.assertEqual(find_platforms(platform_rows(links)), {}, "each owner linked only by itself")


class PlaceKindTests(unittest.TestCase):
    def test_references_are_told_by_their_address(self):
        self.assertEqual(place_kind("help.tool.example", []), "reference")
        self.assertEqual(place_kind("developer.tool.example", []), "reference")
        self.assertEqual(place_kind("tool.example", ["https://tool.example/docs/a", "https://tool.example/en/docs/b",
                                                     "https://tool.example/blog/c"]), "reference")
        self.assertIsNone(place_kind("developers.blog.example", ["https://developers.blog.example/2026/a"]), "a blog")
        self.assertIsNone(place_kind("agency.gov", ["https://agency.gov/news/2026/10/a-release"]), "a government publishes")

    def test_a_host_of_paper_ids_is_a_paper_source(self):
        self.assertEqual(place_kind("preprints.example", ["https://preprints.example/abs/2601.01234",
                                                          "https://preprints.example/pdf/2601.04321v2"]), "paper")
        self.assertIsNone(place_kind("news.example", ["https://news.example/2026/10/a-story"]))


class OrderTests(unittest.TestCase):
    def test_stories_and_classics_carry_the_order(self):
        started = score(origins=3, classics=0, opened=0, voices=3, days=1)
        linked = score(origins=0, classics=0, opened=0, voices=12, days=1)
        self.assertGreater(started, linked)
        self.assertGreater(score(origins=0, classics=0, opened=2, voices=3, days=1), score(origins=0, classics=0, opened=0, voices=3, days=1))
        self.assertGreater(score(origins=0, classics=0, opened=0, voices=3, days=3),
                           score(origins=0, classics=0, opened=0, voices=3, days=90), "recency")


class TitleTests(unittest.TestCase):
    def test_discover_never_makes_a_title_from_the_slug(self):
        url = "https://news.example/2026/10/ai-jobs-white-collar-unemployment"
        self.assertEqual(origin_title(url, []), "Ai jobs white collar unemployment")
        self.assertIsNone(origin_title(url, [], slug=False))
        self.assertEqual(slug_title(url), "Ai jobs white collar unemployment")


@requires_test_db
class DiscoverReadsWellTests(unittest.TestCase):
    def setUp(self):
        self.mark = uuid.uuid4().hex[:8]
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self._clean)

    def _clean(self):
        self.conn.rollback()
        delete_scratch_sources(self.cur)
        self.cur.execute("DELETE FROM discover_addresses WHERE url LIKE %s", (f"%{self.mark}%",))
        self.conn.commit()
        self.conn.close()

    def _voice(self, n, *, platform="rss", name=None):
        return insert_source(self.cur, name or f"Voice {n} {self.mark}", platform=platform), f"voice{n}-{self.mark}.example"

    def _post(self, voice, links):
        source, host = voice
        url = f"https://{host}/p/{uuid.uuid4().hex}"
        insert_post(self.cur, source, url, host=host, normalized=url, links=list(links))

    def _pages(self, host, n=2):
        return [f"https://{host}-{self.mark}.example/2026/10/story-{k}" for k in range(n)]

    def _discover(self, **page):
        self.conn.commit()
        return StoriesService(db_url()).discover(**page)

    def test_an_aggregators_most_linked_site_is_not_followed(self):
        hn = insert_source(self.cur, f"HN {self.mark}", handle=f"https://hnrss.org/frontpage?{self.mark}")
        big = f"big-{self.mark}.example"
        for k in range(3):
            insert_post(self.cur, hn, f"https://{big}/2026/10/item-{k}", host=big)
        self.conn.commit()
        self.assertNotIn(big, SourceFacts(self.cur).followed())
        for n in range(3):
            self._post(self._voice(n), [f"https://{big}/2026/10/story-{k}" for k in range(2)])
        self.assertIn(big, [s["key"] for s in self._discover()["suggestions"]], "suggested by links again")

    def test_saved_is_no_voice_and_a_reddit_source_counts_once(self):
        voices = [self._voice(n) for n in range(2)]
        saved = insert_source(self.cur, "Saved", platform="saved")
        reddit = insert_source(self.cur, f"r/sub {self.mark}", platform="reddit")
        pages = self._pages("linked")
        for voice in voices:
            self._post(voice, pages)
        insert_post(self.cur, saved, f"https://saved-{self.mark}.example/p/1", links=pages)
        self.assertNotIn(f"linked-{self.mark}.example", [s["key"] for s in self._discover()["suggestions"]],
                         "two voices and Saved: under the bar")
        for author in ("alice", "bob"):
            html = f'submitted by &#32; <a href="https://www.reddit.com/user/{author}"> /u/{author} </a>'
            insert_post(self.cur, reddit, f"https://reddit.com/r/sub/{uuid.uuid4().hex}", html=html, host="reddit.com", links=pages)
        self._story_run()
        [got] = [s for s in self._discover()["suggestions"] if s["key"] == f"linked-{self.mark}.example"]
        self.assertEqual(got["voices"], 3, "two sites and one subreddit; its authors are voices for the bar only")
        self.assertIn(f"r/sub {self.mark}", got["voice_names"])
        self.assertNotIn("Saved", got["voice_names"])

    def test_a_sources_links_to_its_own_page_are_no_voice(self):
        host = f"creators-{self.mark}.example"
        voices = [self._voice(n) for n in range(3)]
        for n, voice in enumerate(voices):
            self._post(voice, [f"https://{host}/voice{n}-{self.mark}/posts/{k}" for k in range(2)])
        self.assertNotIn(host, [s["key"] for s in self._discover()["suggestions"]])

    def test_a_reference_is_listed_apart(self):
        for n in range(3):
            self._post(self._voice(n), self._pages("help.tool"))
        got = self._discover()
        self.assertNotIn(f"help.tool-{self.mark}.example", [s["key"] for s in got["suggestions"]])
        self.assertIn(f"help.tool-{self.mark}.example", [r["key"] for r in got["references"]])

    def test_a_rebuild_step_that_counts_nothing_keeps_discover_valid(self):
        """Issue 0080 speed: each rebuild step (keys, threads, names) wrote a new run time that Discover's
        kept counts and its list were keyed by, so every open during a rebuild counted everything again."""
        from datetime import datetime, timedelta, timezone

        from insight_core.db.repo_discover import DiscoverRepository
        from insight_core.db.repo_stories import StoriesRepository

        for n in range(3):
            self._post(self._voice(n), self._pages("steady"))
        service = StoriesService(db_url())
        self._discover()
        listed = service._discover_all()

        def stamp():
            sources = SourceFacts(self.cur)
            return DiscoverRepository.stamp(self.cur, [sorted(sources.kind)]), StoriesRepository.discover_inputs(self.cur)

        self.cur.execute("SELECT value FROM system_settings WHERE key = 'stories'")
        kept = self.cur.fetchone()
        self.addCleanup(self._restore_stories, kept[0] if kept else None)
        first = datetime.now(timezone.utc)
        service._settle(self.cur, SourceFacts(self.cur), {"computed_at": first.isoformat(), "full": False}, first,
                        {"discover": []})   # a batch: Discover's inputs are now
        self.conn.commit()
        listed = service._discover_all()
        before = stamp()
        now = first + timedelta(minutes=1)
        service._settle(self.cur, SourceFacts(self.cur), {"computed_at": now.isoformat(), "full": False}, now,
                        {})   # a keys, threads or names step: no addresses to count
        self.conn.commit()
        self.assertEqual(stamp(), before, "a keys step: the same inputs")
        self.assertIs(service._discover_all(), listed, "the list is kept")
        service._settle(self.cur, SourceFacts(self.cur), {"computed_at": now.isoformat(), "full": False}, now,
                        {"discover": []})
        self.conn.commit()
        self.assertNotEqual(stamp(), before, "a batch: Discover counts again")

    def test_a_fresh_process_reads_the_kept_list(self):
        """Issue 0080 cold open: a process's first open made the whole list again, ~16k pages of posts and
        links (13.6 s on the lab with a cold cache and a busy disk). The list is kept in the database by its
        inputs and code, so a fresh process reads it; inputs that move or other code make it again."""
        import json
        from unittest import mock

        from insight_core.services import stories_service

        for n in range(3):
            self._post(self._voice(n), self._pages("kept"))
        made = json.loads(json.dumps(self._discover()))
        built = []

        class Counting(SourceFacts):
            def __init__(self, cur):
                built.append(1)
                super().__init__(cur)

        with mock.patch.object(stories_service, "SourceFacts", Counting):
            self.assertEqual(json.loads(json.dumps(StoriesService(db_url()).discover())), made)
            self.assertEqual(built, [], "a fresh service reads the kept list: no source facts, no posts read")
            with mock.patch.object(stories_service, "code_stamp", lambda: "other code"):
                StoriesService(db_url()).discover()
            self.assertEqual(len(built), 1, "a list kept by other code is made again")
            self.cur.execute("INSERT INTO discover_hidden (key, reason) VALUES (%s, 'not_interested')",
                             (f"kept-{self.mark}.example",))
            self.addCleanup(self._unhide, f"kept-{self.mark}.example")
            got = self._discover()
            self.assertEqual(len(built), 2, "inputs that moved: made again")
            self.assertNotIn(f"kept-{self.mark}.example", [s["key"] for s in got["suggestions"]])
            StoriesService(db_url()).discover()
            self.assertEqual(len(built), 2, "and kept again")

    def test_the_story_job_keeps_discovers_list(self):
        """The job (its own process after a fetch run, and at start) makes and keeps the list for what it
        changed, so the first open after it reads it."""
        from unittest import mock

        from insight_core.services import stories_service

        for n in range(3):
            self._post(self._voice(n), self._pages("job"))
        self.conn.commit()
        StoriesService(db_url()).recompute_safely()
        built = []

        class Counting(SourceFacts):
            def __init__(self, cur):
                built.append(1)
                super().__init__(cur)

        with mock.patch.object(stories_service, "SourceFacts", Counting):
            got = StoriesService(db_url()).discover()
        self.assertEqual(built, [], "the first open after the job reads its list")
        self.assertIn(f"job-{self.mark}.example", [s["key"] for s in got["suggestions"]])

    def _story_run(self):
        """What a story run does to Discover for posts stored since the last (issue 0080 cold open): the list kept
        for the old ones is made again. (These tests store posts without running the job.)"""
        from insight_core.db.repo_discover import LIST_KEY
        self.cur.execute("DELETE FROM system_settings WHERE key = %s", (LIST_KEY,))

    def _unhide(self, key):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM discover_hidden WHERE key = %s", (key,))

    def _restore_stories(self, value):
        from insight_core.db.repo_operations import SystemSettingsRepository
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            if value is None:
                cur.execute("DELETE FROM system_settings WHERE key = 'stories'")
            else:
                SystemSettingsRepository.upsert(cur, "stories", value)

    def test_one_page_at_a_time(self):
        voices = [self._voice(n) for n in range(3)]
        for name in ("one", "two", "three"):
            for voice in voices:
                self._post(voice, self._pages(f"paged-{name}"))
        everything = self._discover(q=self.mark)
        self.assertEqual(everything["total"], 3)
        first = self._discover(limit=2, q=self.mark)
        self.assertEqual((len(first["suggestions"]), first["more"], first["total"]), (2, True, 3))
        rest = self._discover(offset=2, limit=2, q=self.mark)
        self.assertEqual((len(rest["suggestions"]), rest["more"]), (1, False))
        self.assertEqual([s["key"] for s in first["suggestions"] + rest["suggestions"]],
                         [s["key"] for s in everything["suggestions"]])
        self.assertTrue(all(a["title"] is None for s in everything["suggestions"] for a in s["articles"]),
                        "no title made from an address (story-0 has no words of letters to make one)")


if __name__ == "__main__":
    unittest.main()
