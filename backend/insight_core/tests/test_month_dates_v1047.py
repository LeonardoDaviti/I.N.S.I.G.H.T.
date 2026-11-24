"""Stealth v10.47: a page that states only its month and year is dated the 1st of that month, precision "month"
(page_watch.month_date, DATED_BY_MONTH, migration 0180), and a page's one data-published attribute is its markup
date. The fixtures mirror two real archives that went missing: a research index whose month is written before the
title ("published November 2026"), and a lab blog whose month stands alone after the author list."""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

import psycopg

from insight_core.db.repo_posts import PostDraft, PostsRepository, published_precision
from insight_core.ingestion.kinds import page_watch
from insight_core.ingestion.kinds.page_watch import (DATE_HELD, DATED_BY_BODY, DATED_BY_MONTH, DATED_BY_PAGE,
                                                     page_dating, post_from)
from insight_core.tests._db import db_url, delete_scratch_sources, requires_test_db
from insight_core.tests._stories import insert_source

BODY = "<p>" + "Agents that fail incoherently are a different risk from agents that pursue the wrong goal. " * 12 + "</p>"


def first(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)


# month before the <h1>, its label in its own span (the research index's markup)
RESEARCH = ('<html><head><title>Depth 2 - Research</title></head><body><nav><a href="/">Home</a></nav><section>'
            '<div class="tag-header"><a href="/research/?domain=Vision"><span class="a11y">research area </span>'
            'Computer Vision</a></div><div class="typography-tout"><span><span class="text-capitalize">'
            '<a href="/research/"><span class="a11y">content type </span>paper</a></span>'
            '<span class="post-separator" aria-hidden="true"></span><span class="a11y">published </span>'
            'October 2026</span></div><h1 class="post-title"><p>Depth 2: Sharp Monocular Depth</p></h1>'
            '<p><span class="a11y">Authors</span>Ada Byron, Alan Turing</p></section>'
            f'<article>{BODY}</article></body></html>')

# month alone after a long author list (the lab blog's markup)
LAB_BLOG = ('<html><head><title>The Hot Mess of AI</title></head><body><div class="article-header">'
            '<a href="/">Alignment Blog</a></div><d-title><h1>The Hot Mess of AI: How Does Misalignment Scale?</h1>'
            '</d-title><div class="authors"><div>Ada Byron<sup>1, 2</sup>, Alan Turing<sup>1, 3</sup>, Grace Hopper'
            '<sup>4</sup>, Edsger Dijkstra<sup>5</sup>, Barbara Liskov<sup>5</sup></div>'
            '<div style="margin-top: 1em"><sup>1</sup>Fellows Program <sup>2</sup>EPFL <sup>3</sup>University of'
            ' Edinburgh <sup>4</sup>Constellation <sup>5</sup>Lab</div>'
            '<div style="margin-top: 1em; color: #666;">\n                    February 2026\n                </div>'
            f'</div><d-article>{BODY}<p>Research done during Summer 2025.</p></d-article></body></html>')


class MonthAloneTests(unittest.TestCase):
    def test_the_research_pages_month_before_its_title(self):
        self.assertEqual(page_dating(RESEARCH, "https://ml.example/research/depth-2"), (first(2026, 10), DATED_BY_MONTH))

    def test_the_lab_blogs_month_after_its_authors(self):
        self.assertEqual(page_dating(LAB_BLOG, "https://lab.example/2026/hot-mess/"), (first(2026, 2), DATED_BY_MONTH))

    def test_a_month_a_sentence_names_deep_in_the_article_is_no_date(self):
        page = (f'<html><body><h1>Our results</h1><article>{BODY}{BODY}'
                '<p>In March 2024 we began the study.</p><p>March 2024</p></article></body></html>')
        self.assertEqual(page_dating(page, "https://lab.example/results/"), (None, None))

    def test_a_month_in_a_sentence_by_the_title_is_no_date(self):
        page = f'<html><body><h1>Our results</h1><p>In March 2024 we began the study.</p>{BODY}</body></html>'
        self.assertEqual(page_dating(page, "https://lab.example/results/"), (None, None))

    def test_two_months_by_the_title_are_no_date(self):
        page = f'<html><body><div>January 2026</div><h1>Notes</h1><div>March 2026</div>{BODY}</body></html>'
        self.assertEqual(page_dating(page), (None, None))

    def test_no_title_or_two_titles_no_month(self):
        self.assertEqual(page_dating(f'<html><body><div>March 2026</div>{BODY}</body></html>'), (None, None))
        two = f'<html><body><h1>A</h1><div>March 2026</div><h1>B</h1>{BODY}</body></html>'
        self.assertEqual(page_dating(two), (None, None))

    def test_a_future_month_is_no_date(self):
        page = RESEARCH.replace("October 2026", "December 2099")
        self.assertEqual(page_dating(page), (None, None))

    def test_a_month_its_address_contradicts_is_held(self):
        self.assertEqual(page_dating(LAB_BLOG, "https://lab.example/2025/07/hot-mess/"), (None, DATE_HELD))
        self.assertEqual(page_dating(LAB_BLOG, "https://lab.example/2026/02/hot-mess/"), (first(2026, 2), DATED_BY_MONTH))

    def test_a_month_before_the_web_is_held(self):
        self.assertEqual(page_dating(RESEARCH.replace("October 2026", "May 1985")), (None, DATE_HELD))

    def test_a_day_the_page_states_still_wins(self):
        # the month is the last fallback: a byline day under the title is read first
        page = LAB_BLOG.replace("February 2026", "February 12, 2026")
        self.assertEqual(page_dating(page), (datetime(2026, 2, 12, tzinfo=timezone.utc), DATED_BY_BODY))
        meta = RESEARCH.replace("<head>", '<head><meta property="article:published_time" content="2026-10-03T09:00:00Z">')
        self.assertEqual(page_dating(meta), (datetime(2026, 10, 3, 9, tzinfo=timezone.utc), DATED_BY_PAGE))

    def test_labels_and_abbreviations(self):
        for written in ("Nov 2025", "Nov. 2025", "Published: November 2025", "Updated November 2025", "Sept 2025"):
            page = f'<html><body><h1>A title</h1><p class="meta">{written}</p>{BODY}</body></html>'
            want = first(2025, 9) if written.startswith("Sept") else first(2025, 11)
            self.assertEqual(page_dating(page), (want, DATED_BY_MONTH), written)


class DataPublishedTests(unittest.TestCase):
    def test_one_data_published_attribute_is_the_pages_day(self):
        page = (f'<html><body><div class="section-authors" data-author="Ada Byron" data-published="April 23, 2025">'
                f'</div><h1>Putting up Bumpers</h1>{BODY}</body></html>')
        self.assertEqual(page_dating(page, "https://lab.example/2025/bumpers/"),
                         (datetime(2025, 4, 23, tzinfo=timezone.utc), DATED_BY_PAGE))

    def test_two_different_ones_are_no_date(self):
        page = (f'<html><body><div data-published="April 23, 2025"></div><div data-published="May 2, 2025"></div>'
                f'<h1>Two</h1>{BODY}</body></html>')
        self.assertEqual(page_dating(page), (None, None))


class MonthPrecisionTests(unittest.TestCase):
    def test_a_month_dated_page_is_a_month_precise_post(self):
        post = post_from(RESEARCH, "https://ml.example/research", "https://ml.example/research/depth-2", None)
        self.assertEqual((post["date"], post["date_precision"]), (first(2026, 10), "month"))
        self.assertEqual(published_precision(post), "month")

    def test_a_day_dated_page_stays_a_date(self):
        page = LAB_BLOG.replace("February 2026", "February 12, 2026")
        post = post_from(page, "https://lab.example/", "https://lab.example/2026/hot-mess/", None)
        self.assertNotIn("date_precision", post)
        self.assertEqual(published_precision(post), "date")

    def test_an_undated_page_dated_by_its_lastmod_is_no_month(self):
        page = f'<html><head><meta property="og:type" content="article"></head><body><h1>x</h1>{BODY}</body></html>'
        lastmod = datetime(2026, 3, 4, 12, tzinfo=timezone.utc)
        post = post_from(page, "https://lab.example/", "https://lab.example/x/", lastmod)
        self.assertNotIn("date_precision", post)
        self.assertEqual(published_precision(post), "exact")

    def test_stated_precision(self):
        self.assertEqual(page_watch.stated_precision(DATED_BY_MONTH), "month")
        self.assertIsNone(page_watch.stated_precision(DATED_BY_PAGE))


@requires_test_db
class StoredMonthTests(unittest.TestCase):
    """0180: posts.published_precision takes 'month'; the saver stores it as the page told it."""

    def test_a_month_precise_page_is_stored_as_month(self):
        mark = uuid.uuid4().hex[:8]
        url = f"https://ml-{mark}.example/research/depth-2"
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            source = insert_source(cur, handle=f"https://ml-{mark}.example/research")
            conn.commit()
        try:
            post = post_from(RESEARCH, f"https://ml-{mark}.example/research", url, None)
            with psycopg.connect(db_url()) as conn:
                PostsRepository(db_url()).save_batch(conn, [PostDraft(source, post)])
            with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
                cur.execute("SELECT published_at, published_precision FROM posts WHERE url = %s", (url,))
                self.assertEqual(cur.fetchone(), (first(2026, 10), "month"))
        finally:
            with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
                delete_scratch_sources(cur)
                conn.commit()


if __name__ == "__main__":
    unittest.main()
