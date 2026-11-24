"""Stealth v10.47 (0280 A1): a month-precise date travels every path that reads a page. The full-text reader
(full_text.read_page -> PageRead.precision -> with_full_text) stores "month", the Mark X scout keeps it on its items
and shows the month, and the story rules read a month post as any day of its month, never as the 1st."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

from insight_core.db.repo_posts import published_precision
from insight_core.ingestion import full_text
from insight_core.markx import scout_reads, source_judge
from insight_core.tests._kind_fakes import FakeHttp
from insight_core.tests._stories import story_post
from insight_core.tests.test_month_dates_v1047 import BODY, LAB_BLOG, first
from insight_core.utils.story_rules import apart, grouping, story_times

URL = "https://lab.example/2026/hot-mess/"
DAY_PAGE = ('<html><head><meta property="article:published_time" content="2026-02-17T09:00:00Z"/></head><body>'
            f'<h1>A dated post</h1><article>{BODY}</article></body></html>')


def read(page: str) -> full_text.PageRead:
    return asyncio.run(full_text.read_page(FakeHttp({URL: page}), URL, "", title=None))


class FullTextTests(unittest.TestCase):
    def test_a_month_page_read_in_full_is_a_month_precise_post(self):
        got = read(LAB_BLOG)
        self.assertEqual((got.outcome, got.article[3], got.precision), (full_text.FULL, first(2026, 2), "month"))
        post = full_text.with_full_text({"url": URL, "date": None}, *got.article, precision=got.precision)
        self.assertEqual((post["date"], published_precision(post)), (first(2026, 2), "month"))

    def test_a_day_page_keeps_its_precision_told_by_the_date(self):
        got = read(DAY_PAGE)
        self.assertIsNone(got.precision)
        post = full_text.with_full_text({"url": URL, "date": None}, *got.article, precision=got.precision)
        self.assertEqual(published_precision(post), "exact")

    def test_the_feeds_own_date_wins_over_the_pages_month(self):
        got = read(LAB_BLOG)
        at = datetime(2026, 2, 20, 8, tzinfo=timezone.utc)
        post = full_text.with_full_text({"url": URL, "date": at}, *got.article, precision=got.precision)
        self.assertEqual((post["date"], published_precision(post)), (at, "exact"))


class ScoutTests(unittest.TestCase):
    def test_a_month_item_keeps_its_precision_and_reads_as_its_month(self):
        item = scout_reads.item_of({"url": URL, "title": "Hot mess", "content": "x" * 500,
                                    "date": first(2026, 2), "date_precision": "month"})
        self.assertEqual(item["precision"], "month")
        kept = source_judge.scratch_items([item])
        self.assertEqual(kept[0]["precision"], "month")
        with mock.patch.object(source_judge, "measured_lines", return_value=[]):
            q = source_judge.question(URL, {"via": "page"}, kept, {"key": "lab.example", "platform": "site"}, [])
        self.assertIn("[i1] 2026-02 · Hot mess", q)

    def test_a_day_item_has_no_precision(self):
        item = scout_reads.item_of({"url": URL, "title": "t", "content": "x", "date": first(2026, 2)})
        self.assertIsNone(item["precision"])


class StoryTests(unittest.TestCase):
    def test_a_month_post_is_no_time_apart_from_a_post_in_its_month(self):
        month = story_post("m", "lab", at=first(2026, 2), month_alone=True)
        late = story_post("x", "news", at=datetime(2026, 2, 25, 10, tzinfo=timezone.utc))
        after = story_post("y", "news", at=datetime(2026, 3, 4, tzinfo=timezone.utc))
        self.assertEqual(apart(month, late), timedelta(0))
        self.assertEqual(apart(month, after), timedelta(days=3))
        self.assertTrue(month.date_only and not month.trusted_time)

    def test_a_post_citing_a_month_post_late_in_its_month_joins_it(self):
        month = story_post("m", "lab", at=first(2026, 2), month_alone=True, url="https://lab.example/2026/hot-mess")
        cite = story_post("x", "news", at=datetime(2026, 2, 25, 10, tzinfo=timezone.utc), links=[(month.url, "m")])
        stories = grouping([month, cite]).stories
        self.assertEqual([sorted(p.id for p in s.posts) for s in stories], [["m", "x"]])
        # as a day on the 1st it would not have: 24 days apart
        day = story_post("m", "lab", at=first(2026, 2), url=month.url)
        self.assertEqual(grouping([day, cite]).stories, [])

    def test_a_month_post_counts_as_its_months_earliest_timed_post(self):
        month = story_post("m", "lab", at=first(2026, 2), month_alone=True)
        timed = story_post("x", "news", at=datetime(2026, 2, 25, 10, tzinfo=timezone.utc))
        self.assertEqual(story_times([month, timed])["m"], timed.t)
        self.assertEqual(story_times([month])["m"], first(2026, 2))

    def test_a_december_month_ends_with_the_year(self):
        self.assertEqual(story_post("m", "lab", at=first(2025, 12), month_alone=True).last_t, first(2026, 1))


if __name__ == "__main__":
    unittest.main()
