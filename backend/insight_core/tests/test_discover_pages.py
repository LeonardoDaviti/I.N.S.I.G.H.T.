"""Discover's Pages (issue 0113): each story's root you don't follow and haven't stored, one row a page."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.utils.discover_rules import Origin, origins, page_key_of, pages  # noqa: E402

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def root(story, url, *, voices=2, days=1, source=None, at_post=False):
    return Origin(story, url, None, source, NOW - timedelta(days=days), {f"v{story}{n}": "" for n in range(voices)},
                  at_post=at_post)


class PagesTests(unittest.TestCase):
    def rows(self, roots, hidden=frozenset()):
        started = origins(roots, followed={"followed.example"}, held={})
        return [(url, [r.story_id for r in rs], video) for url, rs, video in
                pages(started, since=NOW - timedelta(days=30), hidden=set(hidden))]

    def test_one_row_a_page_the_biggest_stories_first(self):
        rows = self.rows([root("s1", "https://essays.example/2026/10/an-essay"),
                          root("s2", "https://lab.example/news/a-model-card", voices=5),
                          root("s3", "https://essays.example/2026/10/an-essay", voices=2)])
        self.assertEqual(rows, [("https://lab.example/news/a-model-card", ["s2"], False),
                                ("https://essays.example/2026/10/an-essay", ["s1", "s3"], False)])

    def test_a_saved_root_an_old_story_a_front_page_or_a_hidden_page_is_no_row(self):
        rows = self.rows([root("s1", "https://essays.example/2026/10/an-essay", at_post=True),
                          root("s2", "https://essays.example/2026/09/old", days=45),
                          root("s3", "https://essays.example/"),
                          root("s4", "https://essays.example/2026/10/hidden-one")],
                         hidden={page_key_of("https://essays.example/2026/10/hidden-one")})
        self.assertEqual(rows, [])

    def test_a_video_page_is_listed_as_one(self):
        rows = self.rows([root("s1", "https://www.youtube.com/watch?v=abc")])
        self.assertEqual([video for *_, video in rows], [True])

    def test_a_root_with_a_post_at_its_address_is_stored(self):
        self.assertTrue(root("s1", "https://essays.example/a", at_post=True).stored)
        self.assertFalse(root("s1", "https://essays.example/a").stored)


if __name__ == "__main__":
    unittest.main()
