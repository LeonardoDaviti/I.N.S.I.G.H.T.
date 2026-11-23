"""A story is dated by the posts that report it, never by a background page it cites (0263): a Saved copy of a paper
a release cites, dated long before, must not become the release story's start. Pure rules over invented posts: Mark
IX's grouping, News's rows (Mark IX's and Mark X's code), and Mark X's story date.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from functools import partial

from insight_core.markx import decide
from insight_core.services.news_service import NewsService
from insight_core.tests._stories import story_post
from insight_core.utils.story_rules import Story, background, group, story_start, story_times

NOW = datetime(2030, 3, 20, 12, 0, tzinfo=timezone.utc)
post = partial(story_post, at=NOW)
PAPER = "https://arxiv.example/abs/2901.00001"
MAKER = "https://lumen.example/news/glimmer-3"


def release(paper_days: float = 365, paper_kind: str = "saved"):
    """Glimmer 3's release (invented): the maker's post linking the paper it builds on, three reports linking the
    maker's post, and the paper, stored `paper_days` before as a `paper_kind` post."""
    paper = post("paper", "sv" if paper_kind == "saved" else "papers", kind=paper_kind, hours=-24 * paper_days,
                 url=PAPER, title="Sparse routing for small models")
    maker = post("maker", "lumen", url=MAKER, title="Introducing Glimmer 3", links=[(PAPER, "paper")])
    hn = post("hn", "hn", kind="hn", hours=1, url=MAKER, title="Glimmer 3", home="news.ycombinator.com")
    x1 = post("x1", "xa", kind="x", hours=2, links=[(MAKER, "maker"), (PAPER, "paper")], title="Glimmer 3 is out")
    x2 = post("x2", "xb", kind="x", hours=3, links=[(MAKER, "maker")], title="Trying Glimmer 3 today")
    return [paper, maker, hn, x1, x2]


class BackgroundTests(unittest.TestCase):
    def test_a_saved_paper_a_year_older_is_background(self):
        posts = release()
        times = story_times(posts)
        self.assertEqual(background(posts, times), {"paper"})
        self.assertEqual(story_start(posts, times), NOW, "the release's first report, not the paper")

    def test_a_saved_page_inside_the_link_window_still_dates_it(self):
        posts = release(paper_days=2)
        self.assertEqual(background(posts, story_times(posts)), set())
        self.assertEqual(story_start(posts, story_times(posts)), NOW - timedelta(days=2))

    def test_a_voiced_leak_days_before_still_begins_the_story(self):
        """A report of a voice is never background, however early: a leak four days before the launch (and the
        cited paper of a source of its own) still date the story."""
        leak = post("leak", "rumours", hours=-96, title="Glimmer 3 leaked")
        posts = release()[1:] + [leak]
        self.assertEqual(background(posts, story_times(posts)), set())
        self.assertEqual(story_start(posts, story_times(posts)), NOW - timedelta(hours=96))
        voiced_paper = release(paper_kind="arxiv")
        self.assertEqual(background(voiced_paper, story_times(voiced_paper)), set())

    def test_only_saved_pages_tell_no_start(self):
        posts = [post("a", "sv", kind="saved", hours=-1000), post("b", "sv", kind="saved")]
        self.assertEqual(story_start(posts, story_times(posts)), NOW - timedelta(hours=1000))


class GroupedReleaseTests(unittest.TestCase):
    def test_mark_ix_keeps_the_paper_a_member_and_dates_the_story_by_the_release(self):
        [story] = group(release())
        self.assertIn("paper", {p.id for p in story.posts}, "the cited paper stays in the story (0113)")
        self.assertEqual(story.first_at, NOW)

    def test_the_release_row_stays_in_news_with_its_first_report_first(self):
        posts = release()
        [story] = group(posts)
        rows = NewsService.rows(posts=posts, stories=[story], found=[], since=NOW - timedelta(hours=48))
        self.assertEqual(len(rows), 1, "the release row is in the window")
        self.assertEqual(rows[0].first_at, NOW)
        self.assertEqual(rows[0].posts[0].id, "maker", "a background page is never the row's first post")
        self.assertIn("paper", {p.id for p in rows[0].posts})

    def test_mark_x_rows_of_shape_keeps_the_row(self):
        """Mark X builds each Story from its members in date order (markx/news.rows_of): the same rule."""
        posts = release()
        times = story_times(posts)
        bg = background(posts, times)
        ps = sorted(posts, key=lambda p: (p.id in bg, times[p.id], not p.date_only, p.t, p.id))
        story = Story(id="mx", first_at=times[ps[0].id], posts=ps, voices=0, roles={}, reasons={}, mentions=set())
        self.assertEqual(story.first_at, NOW)
        self.assertEqual(len(NewsService.rows(posts=posts, stories=[story], found=[], since=NOW - timedelta(hours=48))), 1)

    def test_a_leak_days_before_still_dates_the_row_earlier(self):
        leak = post("leak", "rumours", hours=-30, title="Glimmer 3 leaked", links=[(PAPER, "paper")])
        posts = release() + [leak]
        story = Story(id="s", first_at=story_start(posts, story_times(posts)), posts=posts, voices=0, roles={},
                      reasons={}, mentions=set())
        [row] = NewsService.rows(posts=posts, stories=[story], found=[], since=NOW - timedelta(hours=48))
        self.assertEqual(row.first_at, NOW - timedelta(hours=30), "the leak begins the row (leaked before)")
        self.assertEqual(row.posts[0].id, "leak")


class MarkXStoryDateTests(unittest.TestCase):
    def test_persists_first_at_from_the_reports(self):
        rules = {p.id: decide.Post(p.id, p.source_id, p.kind, p.t, 50) for p in release()}
        self.assertEqual(decide._start(list(rules), rules), NOW)
        leak = decide.Post("leak", "rumours", "site", NOW - timedelta(days=4), 50)
        self.assertEqual(decide._start([*rules, "leak"], {**rules, "leak": leak}), NOW - timedelta(days=4))


if __name__ == "__main__":
    unittest.main()
