"""The fetch schedule: one pure decision for "should this source be fetched now?".

Pure - no DB, no clock. Everything goes through decide_fetch, fetch_interval, tier_for,
backoff_delay and cadence_stats (spec §5.1). Expected values are worked by hand from the
rules in spec §C.2, not recomputed the way the code does.
"""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion.kinds.base import PolitenessProfile
from insight_core.ingestion.schedule import (
    Availability,
    CadenceStats,
    CadenceTier,
    DecisionKind,
    backoff_delay,
    cadence_stats,
    decide_fetch,
    fetch_interval,
    tier_for,
)
from insight_core.ingestion.types import OutcomeStatus

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)
D = timedelta(days=1)

RSS = PolitenessProfile(concurrency_pool="host-lock")
YOUTUBE = PolitenessProfile(
    concurrency_pool="ytdlp", cadence_floor=168 * H, min_posts_per_fetch=15,
    requires="ytdlp", blocking_io=True,
)
TELEGRAM_MTPROTO = PolitenessProfile(concurrency_pool="host-lock", requires="telegram_creds")

ALL_ON = Availability(ytdlp_enabled=True, telegram_credentials=True)
YTDLP_OFF = Availability(ytdlp_enabled=False, telegram_credentials=True)


def stats(**overrides) -> CadenceStats:
    """A healthy, fast-ish source with a success an hour ago; override what the case needs."""
    base = dict(
        post_count=50,
        mean_gap=6 * H,
        sample_size=20,
        tier=CadenceTier.FAST,
        override_hours=None,
        max_posts_per_fetch=20,
        last_success_at=NOW - H,
        last_outcome=OutcomeStatus.HEALTHY,
        consecutive_failures=0,
        next_retry_at=None,
    )
    base.update(overrides)
    return CadenceStats(**base)


def decide(s: CadenceStats, profile: PolitenessProfile = RSS, **kwargs):
    kwargs.setdefault("force", False)
    kwargs.setdefault("availability", ALL_ON)
    return decide_fetch(s, profile, NOW, **kwargs)


class DecideFetchTests(unittest.TestCase):
    def test_new_source_is_fetched(self):
        d = decide(stats(post_count=0, last_success_at=None, last_outcome=None,
                         tier=CadenceTier.UNKNOWN, mean_gap=None, sample_size=0))
        self.assertEqual(d.kind, DecisionKind.FETCH_NEW_SOURCE)
        self.assertTrue(d.fetch)

    def test_unknown_tier_is_on_24h_probation(self):
        unknown = dict(tier=CadenceTier.UNKNOWN, mean_gap=None, sample_size=2)
        not_yet = decide(stats(**unknown, last_success_at=NOW - 23 * H))
        self.assertEqual(not_yet.kind, DecisionKind.SKIP_NOT_DUE)
        self.assertFalse(not_yet.fetch)
        self.assertEqual(not_yet.interval_basis, "probation")

        due = decide(stats(**unknown, last_success_at=NOW - 24 * H))
        self.assertEqual(due.kind, DecisionKind.FETCH_DUE)
        self.assertTrue(due.fetch)

    def test_fast_source_gets_the_24h_floor(self):
        # 6h x 20 posts = a 120h window: a quarter of it (30h) is past the floor.
        self.assertEqual(fetch_interval(stats(mean_gap=6 * H), RSS), (24 * H, "tier"))

    def test_medium_source_is_half_its_gap(self):
        s = stats(mean_gap=3 * D, tier=CadenceTier.MEDIUM)
        self.assertEqual(fetch_interval(s, RSS), (36 * H, "tier"))

    def test_slow_source_is_capped_at_21_days(self):
        s = stats(mean_gap=60 * D, tier=CadenceTier.SLOW)
        self.assertEqual(fetch_interval(s, RSS), (21 * D, "tier"))

    def test_backlog_guard_binds_for_very_fast_sources(self):
        # 30m gap x 20 posts per fetch = the feed rolls over in 10h; polled at a quarter of that.
        s = stats(mean_gap=timedelta(minutes=30), max_posts_per_fetch=20)
        self.assertEqual(fetch_interval(s, RSS), (2.5 * H, "backlog_guard"))

    def test_a_busy_subreddit_is_polled_before_its_window_is_a_quarter_full(self):
        # r/LocalLLaMA: a post every ~10 minutes, 25 in the feed = a 4.25h window.
        s = stats(mean_gap=timedelta(minutes=10.2), max_posts_per_fetch=25)
        self.assertEqual(fetch_interval(s, RSS), (timedelta(minutes=63.75), "backlog_guard"))

    def test_backlog_guard_binds_once_a_quarter_of_the_window_is_under_the_interval(self):
        # 4h gap x 20 = an 80h window: the 24h floor would let it fill past a quarter (20h).
        s = stats(mean_gap=4 * H, max_posts_per_fetch=20)
        self.assertEqual(fetch_interval(s, RSS), (20 * H, "backlog_guard"))

    def test_backlog_guard_beats_the_youtube_floor(self):
        # 2h gap x max(5, 15) = a 30h window, a quarter of it well under the 168h yt-dlp floor.
        s = stats(mean_gap=2 * H, max_posts_per_fetch=5)
        self.assertEqual(fetch_interval(s, YOUTUBE), (7.5 * H, "backlog_guard"))

    def test_backlog_guard_never_goes_below_one_hour(self):
        for gap in (timedelta(minutes=1), timedelta(minutes=8)):  # windows of 20m and 2.7h
            with self.subTest(gap=gap):
                s = stats(mean_gap=gap, max_posts_per_fetch=20)
                self.assertEqual(fetch_interval(s, RSS), (1 * H, "backlog_guard"))

    def test_override_beats_tier_guard_and_floor(self):
        for profile, s in (
            (RSS, stats(override_hours=6.0, mean_gap=60 * D, tier=CadenceTier.SLOW)),
            (RSS, stats(override_hours=6.0, mean_gap=timedelta(minutes=1))),
            (YOUTUBE, stats(override_hours=6.0, mean_gap=3 * D, tier=CadenceTier.MEDIUM)),
            (RSS, stats(override_hours=6.0, tier=CadenceTier.UNKNOWN, mean_gap=None, sample_size=1)),
        ):
            with self.subTest(profile=profile.concurrency_pool, tier=s.tier):
                self.assertEqual(fetch_interval(s, profile), (6 * H, "override"))

    def test_youtube_gets_the_weekly_profile_floor(self):
        s = stats(mean_gap=3 * D, tier=CadenceTier.MEDIUM)
        self.assertEqual(fetch_interval(s, YOUTUBE), (168 * H, "profile_floor"))

    def test_backoff_window_in_the_future_skips(self):
        d = decide(stats(consecutive_failures=3, next_retry_at=NOW + 2 * H,
                         last_outcome=OutcomeStatus.ERROR, last_success_at=NOW - 30 * D))
        self.assertEqual(d.kind, DecisionKind.SKIP_BACKOFF)
        self.assertFalse(d.fetch)
        self.assertEqual(d.next_retry_at, NOW + 2 * H)

    def test_expired_backoff_retries_even_inside_the_tier_interval(self):
        d = decide(stats(consecutive_failures=3, next_retry_at=NOW - timedelta(minutes=1),
                         last_outcome=OutcomeStatus.ERROR, last_success_at=NOW - H))
        self.assertEqual(d.kind, DecisionKind.FETCH_RETRY)
        self.assertTrue(d.fetch)

    def test_force_beats_active_backoff(self):
        d = decide(stats(consecutive_failures=3, next_retry_at=NOW + 2 * H), force=True)
        self.assertEqual(d.kind, DecisionKind.FETCH_FORCED)
        self.assertTrue(d.fetch)

    def test_force_beats_freshness(self):
        d = decide(stats(last_success_at=NOW - timedelta(minutes=5)), force=True)
        self.assertEqual(d.kind, DecisionKind.FETCH_FORCED)

    def test_ignore_backoff_is_gone(self):
        """B4: force superseded the interim ignore_backoff argument."""
        with self.assertRaises(TypeError):
            decide(stats(), ignore_backoff=True)

    def test_force_never_beats_ytdlp_off(self):
        """Regression: the manual paths used to bypass the yt-dlp switch."""
        d = decide(stats(), YOUTUBE, force=True, availability=YTDLP_OFF)
        self.assertEqual(d.kind, DecisionKind.SKIP_UNAVAILABLE)
        self.assertFalse(d.fetch)
        self.assertIsNone(d.next_due_at)

    def test_ytdlp_off_is_unavailable_not_backoff(self):
        """Regression for the 🚫 miscount: yt-dlp-off sources were counted as backoff."""
        d = decide(stats(consecutive_failures=4, next_retry_at=NOW + H), YOUTUBE,
                   availability=YTDLP_OFF)
        self.assertEqual(d.kind, DecisionKind.SKIP_UNAVAILABLE)
        self.assertIn("yt-dlp", d.detail)

    def test_ytdlp_off_does_not_touch_host_lock_kinds(self):
        d = decide(stats(last_success_at=NOW - 25 * H), RSS, availability=YTDLP_OFF)
        self.assertEqual(d.kind, DecisionKind.FETCH_DUE)

    def test_missing_telegram_credentials_are_unavailable_with_the_reason(self):
        none = Availability(ytdlp_enabled=True, telegram_credentials=False,
                            telegram_reason="no Telegram session")
        d = decide(stats(), TELEGRAM_MTPROTO, force=True, availability=none)
        self.assertEqual(d.kind, DecisionKind.SKIP_UNAVAILABLE)
        self.assertIn("no Telegram session", d.detail)

    def test_rss_platform_source_of_youtube_kind_gets_the_ytdlp_rules(self):
        """The rules read only the profile, which comes from the kind, never the platform.

        A /feeds/videos.xml URL stored as platform rss resolves to youtube_channel, so it
        must get the yt-dlp floor and switch - the Mark VIII code had two checks that
        disagreed on exactly this source.
        """
        s = stats(mean_gap=3 * D, tier=CadenceTier.MEDIUM, last_success_at=NOW - 48 * H)
        self.assertEqual(decide(s, YOUTUBE).kind, DecisionKind.SKIP_NOT_DUE)
        self.assertEqual(decide(s, YOUTUBE, availability=YTDLP_OFF).kind,
                         DecisionKind.SKIP_UNAVAILABLE)

    def test_post_limit(self):
        self.assertEqual(decide(stats(max_posts_per_fetch=5), YOUTUBE).post_limit, 15)
        self.assertEqual(decide(stats(), YOUTUBE, requested_limit=3).post_limit, 15)
        self.assertEqual(decide(stats(), RSS, requested_limit=50).post_limit, 50)
        self.assertEqual(decide(stats(max_posts_per_fetch=20), RSS).post_limit, 20)

    def test_next_due_is_last_success_plus_interval_when_not_due(self):
        cases = [
            (stats(last_success_at=NOW - H), RSS, 24 * H),
            (stats(mean_gap=3 * D, tier=CadenceTier.MEDIUM, last_success_at=NOW - 10 * H), RSS, 36 * H),
            (stats(mean_gap=3 * D, tier=CadenceTier.MEDIUM, last_success_at=NOW - 2 * D), YOUTUBE, 168 * H),
            (stats(tier=CadenceTier.UNKNOWN, mean_gap=None, sample_size=1,
                   last_success_at=NOW - 3 * H), RSS, 24 * H),
        ]
        for s, profile, interval in cases:
            with self.subTest(interval=interval):
                d = decide(s, profile)
                self.assertEqual(d.kind, DecisionKind.SKIP_NOT_DUE)
                self.assertEqual(d.interval, interval)
                self.assertEqual(d.next_due_at, s.last_success_at + interval)

    def test_an_hourly_source_fetched_into_a_tick_is_due_at_the_next_tick(self):
        # The tick starts at NOW - 1h, the fetch ends (last_success_at) 5 minutes into it.
        d = decide(stats(override_hours=1.0, last_success_at=NOW - 55 * timedelta(minutes=1)))
        self.assertEqual(d.kind, DecisionKind.FETCH_DUE)
        self.assertEqual(d.next_due_at, NOW + 5 * timedelta(minutes=1))

    def test_due_slack_is_ten_minutes(self):
        d = decide(stats(override_hours=1.0, last_success_at=NOW - 49 * timedelta(minutes=1)))
        self.assertEqual(d.kind, DecisionKind.SKIP_NOT_DUE)

    def test_decision_kind_knows_whether_it_fetches(self):
        fetching = {k for k in DecisionKind if k.fetches}
        self.assertEqual(fetching, {DecisionKind.FETCH_NEW_SOURCE, DecisionKind.FETCH_DUE,
                                    DecisionKind.FETCH_RETRY, DecisionKind.FETCH_FORCED})


class CadenceStatsTests(unittest.TestCase):
    SOURCE = {
        "id": "src-1",
        "platform": "rss",
        "handle_or_url": "https://a.example.com/rss",
        "post_count": 42,
        "mean_gap_seconds": 6 * 3600.0,
        "cadence_sample_size": 20,
        "cadence_tier": "fast",
        "fetch_interval_hours_override": 12.0,
        "settings": {"max_posts_per_fetch": 30},
    }

    def test_no_state_row(self):
        s = cadence_stats(self.SOURCE, None)
        self.assertEqual(s.consecutive_failures, 0)
        self.assertIsNone(s.last_success_at)
        self.assertIsNone(s.last_outcome)
        self.assertIsNone(s.next_retry_at)
        self.assertEqual(s.post_count, 42)
        self.assertEqual(s.mean_gap, 6 * H)
        self.assertEqual(s.sample_size, 20)
        self.assertEqual(s.tier, CadenceTier.FAST)
        self.assertEqual(s.override_hours, 12.0)
        self.assertEqual(s.max_posts_per_fetch, 30)

    def test_state_row_fields_are_copied(self):
        row = FetchStateRow(
            source_id="src-1",
            last_attempt_at=NOW - H,
            last_success_at=NOW - 5 * H,
            last_outcome="error",
            last_trigger="scheduler",
            last_fetched_posts=None,
            last_error="boom",
            last_error_at=NOW - H,
            consecutive_failures=3,
            next_retry_at=NOW + 3 * H,
        )
        s = cadence_stats(self.SOURCE, row)
        self.assertEqual(s.last_success_at, NOW - 5 * H)
        self.assertEqual(s.last_outcome, OutcomeStatus.ERROR)
        self.assertEqual(s.consecutive_failures, 3)
        self.assertEqual(s.next_retry_at, NOW + 3 * H)

    def test_missing_cadence_columns_mean_unknown(self):
        bare = {"id": "x", "platform": "rss", "handle_or_url": "u", "settings": {}}
        s = cadence_stats(bare, None)
        self.assertEqual(s.tier, CadenceTier.UNKNOWN)
        self.assertIsNone(s.mean_gap)
        self.assertEqual(s.post_count, 0)
        self.assertEqual(s.max_posts_per_fetch, 20)
        self.assertIsNone(s.override_hours)


class TierForTests(unittest.TestCase):
    def test_boundaries(self):
        cases = [
            (timedelta(hours=11, minutes=59), 20, CadenceTier.FAST),
            (12 * H, 20, CadenceTier.MEDIUM),
            (7 * D, 20, CadenceTier.MEDIUM),
            (7 * D + timedelta(seconds=1), 20, CadenceTier.SLOW),
            (H, 2, CadenceTier.UNKNOWN),
            (H, 3, CadenceTier.FAST),
            (None, 20, CadenceTier.UNKNOWN),
        ]
        for gap, n, tier in cases:
            with self.subTest(gap=gap, n=n):
                self.assertEqual(tier_for(gap, n), tier)


class BackoffDelayTests(unittest.TestCase):
    def band(self, n: int) -> tuple[timedelta, timedelta]:
        return backoff_delay(n, rand=lambda: 0.0), backoff_delay(n, rand=lambda: 1.0)

    def test_first_failure_waits_about_an_hour(self):
        self.assertEqual(self.band(1), (timedelta(minutes=51), timedelta(minutes=60)))

    def test_fifth_failure_is_the_16h_band(self):
        self.assertEqual(self.band(5), (16 * H * 0.85, 16 * H))

    def test_sixth_failure_hits_the_24h_cap(self):
        self.assertEqual(self.band(6), (24 * H * 0.85, 24 * H))

    def test_dormant_sources_wait_up_to_a_week(self):
        self.assertEqual(self.band(10), (7 * D * 0.85, 7 * D))

    def test_no_failures_no_wait(self):
        self.assertEqual(backoff_delay(0), timedelta(0))
        self.assertEqual(backoff_delay(-1), timedelta(0))

    def test_jitter_only_goes_down(self):
        for n in (1, 6, 12, 500):
            with self.subTest(n=n):
                low, high = self.band(n)
                self.assertLessEqual(low, high)
                self.assertLessEqual(backoff_delay(n), high)


if __name__ == "__main__":
    unittest.main()
