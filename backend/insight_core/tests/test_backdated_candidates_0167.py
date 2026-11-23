"""Backdated archive items reach the candidate finder by their own date (0167, part 2). An archived page is stored
now, dated then, never surfaced; Mark X's time of a post is its surfacing, else its date (pairing.post_date), so the
page is paired with the story's posts of its own days when its vector arrives. Rolled back after each test.
"""
from __future__ import annotations

import unittest

from insight_core.markx import candidates as C
from insight_core.tests.test_markx_candidates import D, H, T0, _Cands, at_cos, unit


class Backdated(_Cands):
    def test_an_archived_page_pairs_with_its_storys_posts_by_its_date(self):
        story_a = self.post(self.source(), T0, vector=unit((0, 1.0)))
        story_b = self.post(self.source(), T0 + 6 * H, vector=at_cos(0.80, axis=2))
        self.story(story_a, story_b)
        today = self.post(self.source(), T0 + 40 * D, vector=at_cos(0.95, axis=3))   # the day the archive ran
        page = self.post(self.source("rss"), T0 - 5 * H, vector=at_cos(0.90))
        self.cur.execute("UPDATE posts SET fetched_at = %s, created_at = %s WHERE id = %s", (T0 + 40 * D, T0 + 40 * D, page))
        self.find(page)
        pairs = self.pairs("embedding")
        self.assertIn((page, story_a), pairs)
        self.assertFalse(any(today in pair for pair in pairs))
        self.assertEqual(C.find(self.cur, [page])["embedding"], 0)   # found once: a second run adds nothing


if __name__ == "__main__":
    unittest.main()
