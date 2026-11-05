"""Versions that keep themselves (issue 0071 B1): each stamp is what its rules make of the sample
(utils/stamps.py). A change in what a rule makes changes its stamp; a rename doesn't; and the sample
still exercises every rule, so a change there can't hide."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_stories import SourceFacts
from insight_core.services import posts_service
from insight_core.services.stories_service import StoriesService, rules_stamp
from insight_core.tests._db import db_url, requires_test_db
from insight_core.utils import addresses, discover_rules, stamps, story_rules, tree_rules
from insight_core.utils.discover_rules import discover_address
from insight_core.utils.story_rules import REASONS, group
from insight_core.utils.tree_rules import PARENT_REASONS


def sample_stories():
    sources = SourceFacts.of((s[:4] for s in stamps.SOURCES), stamps.HOSTS)
    return group([StoriesService._story_post(row, sources) for row in stamps.posts()])


def stamps_now():
    return (rules_stamp.__wrapped__(), discover_rules.address_rules(), posts_service.stored_bodies_stamp.__wrapped__())


class SampleCoversTheRulesTests(unittest.TestCase):
    def test_every_join_and_every_parent_reason(self):
        stories = sample_stories()
        self.assertEqual({r for s in stories for rs in s.reasons.values() for r in rs}, set(REASONS))
        self.assertEqual({parent[2] for s in stories for parent in s.parents.values()} - {None}, set(PARENT_REASONS))
        self.assertTrue(any(s.mentions for s in stories), "a roundup mentions a story")

    def test_a_date_alone_and_a_late_fetch(self):
        # Issue 0072: a date alone counts as that day's earliest timed post; a story keeps the id of its
        # post stored first.
        stories = {p.id: s for s in sample_stories() for p in s.posts}
        update = stories["h7"]
        self.assertEqual(update.first_at, stamps._at(80), "the day's first timed post, not 00:00")
        self.assertEqual([p.id for p in update.posts[:2]], ["h7", "h1"], "as early as it, first at the tie")
        self.assertEqual(stories["k1"].id, "k2", "the post stored first, not the first posted")

    def test_a_reply_continues_the_own_tweet_it_quotes(self):
        # Issue 0103: not the account's tweet right before it, which is about something else.
        stories = {p.id: s for s in sample_stories() for p in s.posts}
        self.assertEqual(stories["t9"].parents["t9"][:3:2], ("t7", "thread"))
        self.assertNotIn("t8", stories, "the tweet in between joins nothing")

    def test_a_papers_abstract_and_pdf_are_one_page(self):
        # Issue 0106: a paper id names one page on its host, whatever its path.
        [story] = [s for s in sample_stories() if s.origin_url == stamps.PAPER]
        self.assertEqual({p.id for p in story.posts}, {"q1", "q2"})

    def test_each_way_an_outside_origin_is_titled(self):
        titles = {s.origin_url: s.origin_title for s in sample_stories() if s.origin_url}
        self.assertEqual(titles[stamps.L4], "Fast Tokenizer Ships", "the page's own words, quoted")
        self.assertEqual(titles[stamps.L1], "Lab Model Seven Released Today", "link words two voices agree on")
        self.assertEqual(titles[stamps.L2], "sparse routing at scale", "link words the slug confirms")
        self.assertEqual(titles[stamps.L5], "Show HN: A tiny database in one file", "a link post of only this link")
        self.assertEqual(titles[stamps.L3], "Open weights arrive for everyone", "the slug made readable")
        self.assertEqual(titles[stamps.L6], "A Short Note On Caching", "one voice's words")
        self.assertIsNone(titles[stamps.L7], "none: the address")
        self.assertEqual(titles[stamps.SAVED], "On Careful Measurement", "a page you saved")

    def test_the_addresses_a_hosting_platform_a_tweet_anywhere_a_kind_of_page(self):
        sites = {url: discover_address(url) for url in stamps.ADDRESSES}
        self.assertEqual(sites["https://writer-one.github.io/2026/03/routing"][1], "writer-one.github.io")
        self.assertEqual(sites["https://nitter.local/writer_x/status/1900000000000000101"][0], "x.com/writer_x")
        self.assertIsNone(sites["https://youtube.com/watch?v=abcdefghijk"][0])


class StampsFollowTheRulesTests(unittest.TestCase):
    def test_a_rule_that_makes_other_output_changes_its_stamp(self):
        stories, sites, bodies = stamps_now()
        # 0068's miss, replayed: a github.io writer's site as before the Public Suffix List's private section
        with mock.patch.object(addresses, "_hosting_suffixes", lambda: frozenset()):
            self.assertNotEqual(discover_rules.address_rules(), sites)
            self.assertNotEqual(rules_stamp.__wrapped__(), stories)
        # 0068's other miss: how an outside origin is titled
        with mock.patch.object(tree_rules, "origin_title", lambda url, posts: None):
            self.assertNotEqual(rules_stamp.__wrapped__(), stories)
        with mock.patch.object(story_rules, "SAME_TITLE_MIN_WORDS", 4):
            self.assertNotEqual(rules_stamp.__wrapped__(), stories)
        # 0103's: a reply threaded under the account's previous tweet, not the one it quotes
        with mock.patch.object(story_rules, "own_quote", lambda post: None):
            self.assertNotEqual(rules_stamp.__wrapped__(), stories)
        # 0106's: a paper's paths as two pages
        story_rules._page_key.cache_clear()
        with mock.patch.object(story_rules, "paper_id", lambda url: None):
            self.assertNotEqual(rules_stamp.__wrapped__(), stories)
        story_rules._page_key.cache_clear()
        from insight_core.ingestion.kinds import parsing
        with mock.patch.object(parsing, "_without_hidden_link_labels", lambda html: html):
            self.assertNotEqual(posts_service.stored_bodies_stamp.__wrapped__(), bodies)

    def test_a_rename_keeps_every_stamp(self):
        before = stamps_now()
        title_key, site_of = story_rules.title_key, addresses.site_of

        def renamed_title_key(title):
            return title_key(title)

        def renamed_site_of(host):
            return site_of(host)

        with mock.patch.object(story_rules, "title_key", renamed_title_key), \
                mock.patch.object(story_rules, "site_of", renamed_site_of):
            self.assertEqual(stamps_now(), before)
        self.assertEqual(stamps.fingerprint({"b": {1, 2}, "a": [1]}), stamps.fingerprint({"a": [1], "b": {2, 1}}))


@requires_test_db
class SearchVersionTests(unittest.TestCase):
    """search_vector_version() is what post_search_vector makes of its sample (migration 0055)."""

    def test_a_vector_rule_that_makes_other_vectors_changes_the_version(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT search_vector_version(), pg_get_functiondef('post_search_vector(text,text,text)'::regprocedure)")
            version, definition = cur.fetchone()
            cur.execute(definition.replace("$function$\n", "$function$\n  -- a comment: the same rule\n", 1))
            cur.execute("SELECT search_vector_version()")
            self.assertEqual(cur.fetchone()[0], version, "rewritten, the same vectors: the same version")
            cur.execute(definition.replace("to_tsvector('russian', normalize(COALESCE(title", "to_tsvector('simple', normalize(COALESCE(title", 1))
            cur.execute("SELECT search_vector_version()")
            self.assertNotEqual(cur.fetchone()[0], version, "titles read by another dictionary: another version")
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
