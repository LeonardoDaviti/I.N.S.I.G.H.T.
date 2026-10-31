"""Discover, cleaner (issue 0067): a roundup's link weighs half in the order, never in the bar; a
language segment is not a section; a tweet mirror's other pages are X's, not a site; the counts are
kept between story runs, identical to a fresh count.
"""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_discover import KEPT_KEY
from insight_core.services.stories_service import StoriesService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests.test_discover_counts import assert_links_as_walked, reference_discover
from insight_core.tests.test_discover_origins import root
from insight_core.utils.post_links import section_of
from insight_core.utils.story_rules import origins, suggestions


class LanguageSegmentTests(unittest.TestCase):
    def test_a_language_segment_is_skipped(self):
        self.assertEqual(section_of("https://openai.com/ru-RU/index/introducing-the-codex-app"), "index")
        self.assertEqual(section_of("https://help.openai.com/en/articles/11487775-apps-in-chatgpt"), "articles")
        self.assertEqual(section_of("https://example.com/zh-hans/blog/a-post"), "blog")
        self.assertEqual(section_of("https://example.com/en_US/news/a-post"), "news")

    def test_a_section_of_its_shape_is_kept_when_no_section_follows_it(self):
        """The shape is also many sections' (/ai/, /us/): a language is read only when a section
        and a page follow it, never a date or a number."""
        self.assertEqual(section_of("https://arstechnica.com/ai/2026/10/a-story"), "ai", "a date follows")
        self.assertEqual(section_of("https://huggingface.co/ai-sage/GigaChat"), "ai-sage", "a page follows, no section")
        self.assertEqual(section_of("https://developers.googleblog.com/en/a-post"), "en", "a language's own home")
        self.assertEqual(section_of("https://example.com/v2/docs/a-page"), "v2", "not a language's shape")
        self.assertEqual(section_of("https://example.com/api/docs/a-page"), "api", "three letters alone: not a language")

    def test_a_languages_stories_move_to_the_section_they_belong_to(self):
        roots = [root("https://openai.com/ru-RU/index/devday-2026-recap"), root("https://openai.com/ru-RU/index/codex-app")]
        found = origins(roots, followed={"openai.com"}, held={"openai.com/index": "s-openai"})
        self.assertEqual({k: len(v) for k, v in found.missing.items()}, {"s-openai": 2})
        self.assertFalse(found.suggest)


class RulesTests(unittest.TestCase):
    def test_a_mirrors_pages_that_are_not_tweets_start_no_site_suggestion(self):
        roots = [root("https://nitter.net/t.co/FRJIzwUwYs"), root("https://nitter.net/i/article/2097730969369477120")]
        self.assertEqual(sorted(origins(roots, followed=set(), held={}).suggest), ["nitter.net"], "without the rule")
        found = origins(roots, followed=set(), held={}, mirrors={"nitter.net"})
        self.assertFalse(found.suggest)
        self.assertEqual(sorted(found.unnamed), ["nitter.net/i", "nitter.net/t.co"], "listed as pages that name no account")

    def test_the_walk_weighs_a_roundup_voice_half(self):
        pages = [f"https://{{}}/2026/10/story-{n}" for n in range(2)]
        links = [(v, p.format("listed.example"), True) for v in ("a", "b", "c", "d") for p in pages]
        links += [(v, p.format("own.example"), False) for v in ("a", "b", "c") for p in pages]
        found = suggestions(links, followed=set(), hidden=set())
        self.assertEqual([(s.key, len(s.voices), s.weight) for s in found], [("own.example", 3, 3), ("listed.example", 4, 2)])


@requires_test_db
class DiscoverCleanTests(unittest.TestCase):
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

    def _voice(self, n):
        source = insert_scratch_source(self.cur)
        self.cur.execute("UPDATE sources SET settings = jsonb_build_object('display_name', %s::text) WHERE id = %s",
                         (f"Voice {n} {self.mark}", source))
        return source, f"voice{n}-{self.mark}.example"

    def _post(self, voice, links, *, html=""):
        source, host = voice
        url = f"https://{host}/p/{uuid.uuid4().hex}"
        self.cur.execute(
            "INSERT INTO posts (source_id, url, normalized_url, url_host, content_html, published_at, links_scanned_at) "
            "VALUES (%s, %s, %s, %s, %s, now(), now()) RETURNING id", (source, url, url, host, html))
        post_id = self.cur.fetchone()[0]
        for position, target in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, '', %s)",
                             (post_id, target, position))

    def _pages(self, host, n=2):
        return [f"https://{host}-{self.mark}.example/2026/10/story-{k}" for k in range(n)]

    def _roundup(self, voice, *links):
        """A post listing news: its links have 3+ anchors."""
        self._post(voice, [*links, *self._pages(f"elsewhere{uuid.uuid4().hex[:6]}", 3)])

    def _discover(self):
        self.conn.commit()
        got = StoriesService(db_url()).discover()["suggestions"]
        assert_links_as_walked(self, got, reference_discover(db_url()))
        return {s["key"]: s for s in got if self.mark in s["key"]}, [s["key"] for s in got if self.mark in s["key"]]

    def test_a_roundup_voice_weighs_half_in_the_order_and_counts_in_the_bar(self):
        voices = [self._voice(n) for n in range(4)]
        for voice in voices:                     # 4 voices, every one in a roundup: 2 in the order
            self._roundup(voice, *self._pages("listed"))
        for voice in voices[:3]:                 # 3 voices in their own posts: 3
            self._post(voice, self._pages("own"))
        by_key, order = self._discover()
        listed, own = f"listed-{self.mark}.example", f"own-{self.mark}.example"
        self.assertEqual(by_key[listed]["voices"], 4, "the bar and the card count every voice")
        self.assertLess(order.index(own), order.index(listed))

    def test_a_voice_with_a_roundup_link_and_an_ordinary_link_counts_one(self):
        a, b, c, d = (self._voice(n) for n in (3, 0, 1, 2))
        self._roundup(a, self._pages("mixed")[0])
        self._post(a, self._pages("mixed")[1:])  # a: one roundup link, one ordinary: 1
        for voice in (b, c):
            self._roundup(voice, *self._pages("mixed"))
        for voice in (b, c, d):                  # every voice in roundups: 1.5
            self._roundup(voice, *self._pages("listed", 3))
        by_key, order = self._discover()
        mixed, listed = f"mixed-{self.mark}.example", f"listed-{self.mark}.example"
        self.assertLess(order.index(mixed), order.index(listed), "2 against 1.5, though fewer articles")
        self.assertEqual(by_key[mixed]["voice_names"][0], f"Voice 3 {self.mark}", "its own post's voice first")

    def test_a_mirrors_pages_that_are_not_tweets_are_no_site(self):
        mirror, plain = f"mirror-{self.mark}.example", f"plain-{self.mark}.example"
        voices = [self._voice(n) for n in range(3)]
        self._post(voices[0], [], html=f'<a href="https://{mirror}/someone/status/2111872584338018562">a tweet</a>')
        for voice in voices:
            self._post(voice, [f"https://{host}/i/article/a-long-slug-here-{k}" for host in (mirror, plain) for k in range(2)])
        by_key, _ = self._discover()
        self.assertIn(plain, by_key, "a host where no tweet is found is a site")
        self.assertNotIn(mirror, by_key, "a host where tweets are found is X: its other pages name no account")

    def test_the_story_job_keeps_the_counts_and_discover_reads_them(self):
        voices = [self._voice(n) for n in range(3)]
        for voice in voices:
            self._post(voice, self._pages("kept"))
        self.conn.commit()
        StoriesService(db_url()).recompute()
        self.cur.execute("SELECT value FROM system_settings WHERE key = %s", (KEPT_KEY,))
        kept = self.cur.fetchone()[0]
        key = f"kept-{self.mark}.example"
        self.assertIn(key, [s["key"] for s in kept["found"]])
        read = StoriesService(db_url()).discover()
        self.cur.execute("DELETE FROM system_settings WHERE key = %s", (KEPT_KEY,))
        self.conn.commit()
        self.assertEqual(json.dumps(StoriesService(db_url()).discover(), sort_keys=True), json.dumps(read, sort_keys=True),
                         "the kept counts are a fresh count's")
        for s in kept["found"]:                  # what is kept is what an open reads
            if s["key"] == key:
                s["link_count"] = 999
        self.cur.execute("UPDATE system_settings SET value = %s WHERE key = %s", (json.dumps(kept), KEPT_KEY))
        self.conn.commit()
        self.assertEqual({s["key"]: s for s in StoriesService(db_url()).discover()["suggestions"]}[key]["link_count"], 999)
        self.cur.execute("DELETE FROM sources WHERE id = %s", (voices[2][0],))   # a source removed, with its posts
        by_key, _ = self._discover()
        self.assertNotIn(key, by_key, "counted again: two voices are not enough")


if __name__ == "__main__":
    unittest.main()
