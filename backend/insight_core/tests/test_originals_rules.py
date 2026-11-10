"""The rules of a story's original (issues 0114, 0123): tokens, page dates, wanted links, the budget, the kinds."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.utils.originals_rules import (  # noqa: E402
    FOLLOWED, FROM_QUOTE, NO_ARTICLE, PAGE, TWEET_UNHELD, WALLED, SiteReads, credit_after, early_fetch_blocked,
    linked_wanted, page_date, strip_access_tokens, tokened, trigger_kind, tweet_time, whole,
)

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJpZCI6IngifQ.c2lnbmF0dXJl"


class TokenTests(unittest.TestCase):
    def test_access_and_gift_tokens_are_found_by_their_key_or_a_signed_value(self):
        for url in (f"https://news.example.com/a/b?accessToken={JWT}", "https://paper.example.com/x.html?unlocked_article_code=1.N1E",
                    "https://mag.example.com/p?gift=abc", f"https://blog.example.com/p?dib={JWT}",
                    "https://site.example.com/s?view_token=abc&utm_source=x"):
            self.assertTrue(tokened(url), url)
        for url in ("https://example.com/tokenizer-benchmarks", "https://example.com/a?page=2", "https://example.com/p?id=42"):
            self.assertFalse(tokened(url), url)

    def test_a_token_is_never_kept_the_rest_is(self):
        self.assertEqual(strip_access_tokens(f"https://news.example.com/a?accessToken={JWT}&leadSource=gifting&x=1"),
                         "https://news.example.com/a?leadSource=gifting&x=1")
        self.assertEqual(strip_access_tokens("https://paper.example.com/x.html?smid=url-share&unlocked_article_code=1.N1E"),
                         "https://paper.example.com/x.html?smid=url-share")
        self.assertEqual(strip_access_tokens("https://example.com/a?b=1"), "https://example.com/a?b=1")


class DateTests(unittest.TestCase):
    def test_a_tweet_is_dated_by_its_id_a_page_by_its_address(self):
        self.assertEqual(tweet_time("https://x.com/someone/status/2118068667103453360").date().isoformat(), "2026-11-04")
        self.assertEqual(page_date("https://blog.example.com/2026/10/21/a-post"), datetime(2026, 10, 21, tzinfo=timezone.utc))
        self.assertEqual(page_date("https://example.com/news/2026-09/a-post"), datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertIsNone(page_date("https://example.com/news/a-post"))
        # v10.13.5: a month by name with its day
        self.assertEqual(page_date("https://blog.example.com/2008/Jul/7/a-link/"), datetime(2008, 7, 7, tzinfo=timezone.utc))
        self.assertEqual(page_date("https://example.com/2019/september/03/x"), datetime(2019, 9, 3, tzinfo=timezone.utc))
        self.assertIsNone(page_date("https://example.com/2025/Feb/30/x/"))

    def test_address_day_needs_a_whole_day(self):
        from insight_core.utils.originals_rules import address_day
        self.assertEqual(address_day("https://blog.example.com/2026/10/21/a-post"), datetime(2026, 10, 21, tzinfo=timezone.utc))
        self.assertEqual(address_day("https://blog.example.com/2008/Jul/7/a-link/"), datetime(2008, 7, 7, tzinfo=timezone.utc))
        self.assertIsNone(address_day("https://example.com/news/2026-09/a-post"))     # a month alone is no day
        self.assertIsNone(address_day("https://example.com/news/a-post"))


class LinkedTests(unittest.TestCase):
    def test_only_a_story_s_link_to_a_page_its_feed_can_still_hold(self):
        self.assertIsNone(linked_wanted("https://lab.example.com/news/a-release", NOW, in_story=True, last_fetch=NOW - timedelta(hours=18)))
        self.assertEqual(linked_wanted("https://lab.example.com/news/a-release", NOW, in_story=False, last_fetch=None), "no story links it")
        self.assertEqual(linked_wanted("https://lab.example.com/2026/09/01/old", NOW, in_story=True, last_fetch=None), "older than its feed")
        self.assertEqual(linked_wanted("https://lab.example.com/2026/11/02/before", NOW, in_story=True, last_fetch=NOW - timedelta(hours=6)),
                         "dated before the source's last fetch")

    def test_never_within_15_minutes_in_backoff_or_twice_an_interval(self):
        ok = dict(last_attempt=NOW - timedelta(hours=5), failures=0, retry_at=None, linked_fetched_at=None, interval=timedelta(hours=24))
        self.assertIsNone(early_fetch_blocked(NOW, **ok))
        self.assertTrue(early_fetch_blocked(NOW, **{**ok, "last_attempt": NOW - timedelta(minutes=10)}))
        self.assertTrue(early_fetch_blocked(NOW, **{**ok, "failures": 2, "retry_at": NOW + timedelta(hours=1)}))
        self.assertTrue(early_fetch_blocked(NOW, **{**ok, "linked_fetched_at": NOW - timedelta(hours=20)}))
        self.assertIsNone(early_fetch_blocked(NOW, **{**ok, "linked_fetched_at": NOW - timedelta(hours=25)}))


class BudgetTests(unittest.TestCase):
    def test_one_percent_of_the_schedule_as_a_credit_capped(self):
        self.assertEqual(whole(credit_after(0.0, 99)), 0)
        self.assertEqual(whole(credit_after(0.0, 100)), 1)
        self.assertAlmostEqual(credit_after(0.5, 50), 1.0)
        self.assertEqual(credit_after(0.0, 100_000), 3.0, "a burst of 3 at most")
        self.assertEqual(whole(-1.0), 0)


class TriggerTests(unittest.TestCase):
    def kind(self, url, **kw):
        args = dict(owner=None, names_account=True, reads=SiteReads())
        return trigger_kind(url, **{**args, **kw})

    def test_kinds(self):
        self.assertEqual(self.kind("https://blog.example.com/a", owner="source-1"), FOLLOWED)
        self.assertEqual(self.kind("https://news.example.com/a", linked_as=[f"https://news.example.com/a?accessToken={JWT}"]), WALLED)
        self.assertEqual(self.kind("https://wire.example.com/a", reads=SiteReads(read=15, titled=0)), WALLED)
        self.assertEqual(self.kind("https://wire.example.com/a", reads=SiteReads(read=1, titled=0)), PAGE, "one untitled read is no wall")
        self.assertEqual(self.kind("https://shop.example.com/a", reads=SiteReads(follow="blocked")), WALLED)
        self.assertEqual(self.kind("https://x.com/someone/status/2118068667103453360", quoted="The release is out."), FROM_QUOTE)
        self.assertEqual(self.kind("https://x.com/someone/status/2118068667103453360"), TWEET_UNHELD)
        self.assertEqual(self.kind("https://video.example.com/watch?v=abc", names_account=False,
                                   reads=SiteReads(read=2, titled=0)), NO_ARTICLE, "a video page is no article, walled or not")
        self.assertEqual(self.kind("https://help.example.com/en/articles/1", article=False), NO_ARTICLE)
        self.assertEqual(self.kind("https://essays.example.com/2026/10/08/an-essay"), PAGE)


if __name__ == "__main__":
    unittest.main()
