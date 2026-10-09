"""
Tests for the ingestion hardening in safe_ingest (c3a33e3).

That commit added ~979 lines - concurrency gates, a per-host limiter, a dead-source
backoff ladder, per-post save isolation, chunked enrichment - to a module no test module
imported. These cover the invariants that commit exists to provide, at the level they can
be checked without a network or a live cycle:

  - no single source failure may escape _fetch_source (it runs under asyncio.gather, so
    anything that escapes takes the whole cycle's fetch with it)
  - the per-host limiter must actually serialise same-host requests, and must NOT
    serialise different hosts
  - a source that answered with zero posts is a success (`empty`), not a failure
  - (Mark IX B1) should_fetch_source is a thin adapter over decide_fetch; the decision
    phase of safe_ingest_posts counts backoff from the decision kind, so yt-dlp-off
    sources are unavailable, never backoff. The ladder itself is tested in
    test_fetch_schedule (backoff_delay) and test_repo_fetch_state (record_outcome).

Deliberately not covered here: a safe_ingest_posts() run that fetches. It needs a live
corpus and real sources, and running it is exactly what we must not do.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion.schedule import Availability, DecisionKind
from insight_core.ingestion.types import FetchOutcome, OutcomeStatus
from insight_core.scripts import safe_ingest as si


def _source(handle: str, platform: str = "rss", priority: int = 999, post_count: int = 0,
            **settings) -> dict:
    base = {"display_name": handle, "priority": priority, "fetch_delay_seconds": 0,
            "max_posts_per_fetch": 20}
    base.update(settings)
    return {"id": f"id-{handle}", "handle_or_url": handle, "platform": platform,
            "enabled": True, "post_count": post_count, "settings": base}


class HostKeyTests(unittest.TestCase):
    """host_key must collapse the aliases the limiter exists to serialise."""

    def test_aliases_and_www_collapse_to_one_bucket(self):
        pairs = [
            ("https://www.reddit.com/r/x/.rss", "https://old.reddit.com/r/x/.rss"),
            ("https://www.youtube.com/@a", "https://m.youtube.com/@a"),
            ("https://github.com/a.atom", "https://www.github.com/b.atom"),
        ]
        for left, right in pairs:
            with self.subTest(left=left):
                self.assertEqual(
                    si._HostLimiter.host_key(_source(left)),
                    si._HostLimiter.host_key(_source(right)),
                    "a private urlparse copy put these in different buckets, splitting "
                    "exactly the clusters the limiter exists to serialise",
                )

    def test_distinct_hosts_stay_distinct(self):
        self.assertNotEqual(
            si._HostLimiter.host_key(_source("https://github.com/a.atom")),
            si._HostLimiter.host_key(_source("https://reddit.com/r/a/.rss")),
        )

    def test_bare_handles_group_per_platform_not_all_together(self):
        telegram = si._HostLimiter.host_key(_source("@chan", platform="telegram"))
        youtube = si._HostLimiter.host_key(_source("@chan2", platform="youtube"))
        self.assertNotEqual(telegram, youtube)
        self.assertEqual(telegram, si._HostLimiter.host_key(_source("@other", platform="telegram")))


class HostOverrideTests(unittest.TestCase):
    def test_every_telegram_and_nitter_host_has_a_floor(self):
        """The hardcoded table covered 2 of 5 hosts; telegram.local got 0s.

        That host is every self-hosted Telegram source (35 on the deployed instance) and
        the bridge already answers "Too many requests" under a sequential cycle.
        """
        from insight_core.services.source_fetch_service import SourceFetchService

        for host in SourceFetchService.TELEGRAM_HOSTS:
            self.assertEqual(si.HOST_MIN_INTERVAL_OVERRIDES.get(host),
                             float(SourceFetchService.TELEGRAM_PAGE_DELAY_SECONDS), host)
        for host in SourceFetchService.NITTER_HOSTS:
            self.assertEqual(si.HOST_MIN_INTERVAL_OVERRIDES.get(host),
                             float(SourceFetchService.NITTER_PAGE_DELAY_SECONDS), host)


class HostLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_host_requests_do_not_overlap(self):
        limiter = si._HostLimiter()
        overlap = {"max": 0, "live": 0}

        async def call():
            async with limiter.slot("example.com", 0):
                overlap["live"] += 1
                overlap["max"] = max(overlap["max"], overlap["live"])
                await asyncio.sleep(0.02)
                overlap["live"] -= 1

        await asyncio.gather(*(call() for _ in range(5)))
        self.assertEqual(overlap["max"], 1, "same-host requests must be serialised")

    async def test_different_hosts_run_concurrently(self):
        limiter = si._HostLimiter()
        live = {"max": 0, "n": 0}

        async def call(host):
            async with limiter.slot(host, 0):
                live["n"] += 1
                live["max"] = max(live["max"], live["n"])
                await asyncio.sleep(0.02)
                live["n"] -= 1

        await asyncio.gather(*(call(f"h{i}.example.com") for i in range(5)))
        self.assertEqual(live["max"], 5, "a per-HOST limiter must not serialise across hosts")

    async def test_min_interval_spaces_successive_calls(self):
        limiter = si._HostLimiter()
        loop = asyncio.get_running_loop()
        stamps = []

        async def call():
            async with limiter.slot("example.com", 0.05):
                stamps.append(loop.time())

        await asyncio.gather(call(), call(), call())
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        for gap in gaps:
            self.assertGreaterEqual(round(gap, 3), 0.045, f"gaps={gaps}")

    async def test_override_raises_a_floor_below_it(self):
        """A source configured with 0s on telegram.local still gets the bridge's floor."""
        limiter = si._HostLimiter()
        loop = asyncio.get_running_loop()
        stamps = []
        # Patch the real floor down so the test stays fast; the point is that the
        # override wins over the source's own (lower) fetch_delay_seconds.
        original = si.HOST_MIN_INTERVAL_OVERRIDES.get("telegram.local")
        si.HOST_MIN_INTERVAL_OVERRIDES["telegram.local"] = 0.05
        try:
            async def call():
                async with limiter.slot("telegram.local", 0):
                    stamps.append(loop.time())

            await asyncio.gather(call(), call())
        finally:
            if original is None:
                si.HOST_MIN_INTERVAL_OVERRIDES.pop("telegram.local", None)
            else:
                si.HOST_MIN_INTERVAL_OVERRIDES["telegram.local"] = original

        self.assertGreaterEqual(round(stamps[1] - stamps[0], 3), 0.045)


class StartSpacerTests(unittest.IsolatedAsyncioTestCase):
    async def test_spaces_starts_without_serialising_the_work(self):
        spacer = si._StartSpacer(0.03)
        loop = asyncio.get_running_loop()
        starts = []

        async def call():
            await spacer.wait()
            starts.append(loop.time())
            await asyncio.sleep(0.1)  # far longer than the interval

        await asyncio.gather(*(call() for _ in range(3)))
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        for gap in gaps:
            self.assertGreaterEqual(round(gap, 3), 0.025, f"gaps={gaps}")

    async def test_zero_interval_is_a_no_op(self):
        spacer = si._StartSpacer(0)
        await asyncio.wait_for(asyncio.gather(*(spacer.wait() for _ in range(50))), timeout=1)


class InterleaveTests(unittest.TestCase):
    def test_same_host_runs_are_broken_up(self):
        sources = (
            [_source(f"https://www.youtube.com/@c{i}") for i in range(4)]
            + [_source(f"https://feed{i}.example.com/rss") for i in range(2)]
        )
        ordered = si._interleave_by_host(sources)
        hosts = [si._HostLimiter.host_key(s) for s in ordered]

        self.assertEqual(len(ordered), len(sources), "interleaving must not drop sources")
        self.assertNotEqual(hosts[0], hosts[1],
                            "the first tasks gather starts must want different gates")

    def test_priority_tiers_stay_ordered(self):
        sources = [
            _source("https://a.example.com/1", priority=5),
            _source("https://b.example.com/1", priority=1),
            _source("https://c.example.com/1", priority=1),
        ]
        ordered = si._interleave_by_host(sources)
        self.assertEqual([s["settings"]["priority"] for s in ordered], [1, 1, 5])

    def test_empty_input(self):
        self.assertEqual(si._interleave_by_host([]), [])


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
ALL_ON = Availability(ytdlp_enabled=True, telegram_credentials=False)
YTDLP_OFF = Availability(ytdlp_enabled=False, telegram_credentials=False)


def _state(source: dict, **fields) -> FetchStateRow:
    return FetchStateRow(source_id=source["id"], **fields)


class _FakeFetchState:
    """In-memory stand-in for DbFetchStateStore; records every call."""

    def __init__(self, states: dict | None = None):
        self.states = dict(states or {})
        self.outcomes: list[tuple[FetchOutcome, str]] = []
        self.decisions: list[tuple[str, object]] = []
        self.refreshed = 0

    def load(self, source_ids):
        return {sid: self.states[sid] for sid in source_ids if sid in self.states}

    def record_decisions(self, decisions):
        self.decisions.extend(decisions)

    def record_outcome(self, outcome, *, trigger):
        self.outcomes.append((outcome, trigger))

    def record_outcomes(self, outcomes, *, trigger):
        for outcome in outcomes:
            self.record_outcome(outcome, trigger=trigger)

    def refresh_cadence(self):
        self.refreshed += 1
        return 0


class _RaisingFetchState(_FakeFetchState):
    def record_outcome(self, outcome, *, trigger):
        raise RuntimeError("db down")


class ShouldFetchSourceTests(unittest.TestCase):
    """The B1 adapter: Mark VIII call shape, decide_fetch underneath."""

    def decide(self, source, state=None, trigger="scheduler", **kwargs):
        kwargs.setdefault("now", NOW)
        kwargs.setdefault("availability", ALL_ON)
        return si.should_fetch_source(source, state, trigger, **kwargs)

    def test_source_in_backoff_is_skipped_on_a_scheduled_run(self):
        source = _source("https://a.example.com/rss", post_count=10)
        answer = self.decide(source, _state(source, consecutive_failures=5,
                                            next_retry_at=NOW + timedelta(hours=4),
                                            last_success_at=NOW - timedelta(days=30)))
        should, reason = answer
        self.assertFalse(should)
        self.assertEqual(answer.kind, DecisionKind.SKIP_BACKOFF)
        self.assertIn("Backoff", reason)

    def test_manual_trigger_ignores_backoff_but_respects_freshness(self):
        source = _source("https://a.example.com/rss", post_count=10)
        in_backoff = dict(consecutive_failures=5, next_retry_at=NOW + timedelta(hours=4))

        fresh = self.decide(source, _state(source, **in_backoff,
                                           last_success_at=NOW - timedelta(hours=2)),
                            trigger="manual")
        self.assertFalse(fresh.fetch)
        self.assertEqual(fresh.kind, DecisionKind.SKIP_NOT_DUE)

        stale = self.decide(source, _state(source, **in_backoff,
                                           last_success_at=NOW - timedelta(hours=25)),
                            trigger="manual")
        self.assertTrue(stale.fetch)
        self.assertEqual(stale.kind, DecisionKind.FETCH_DUE)

    def test_expired_backoff_window_lets_the_source_through(self):
        source = _source("https://a.example.com/rss", post_count=10)
        answer = self.decide(source, _state(source, consecutive_failures=5,
                                            next_retry_at=NOW - timedelta(hours=1),
                                            last_success_at=NOW - timedelta(hours=1)))
        self.assertTrue(answer.fetch)
        self.assertEqual(answer.kind, DecisionKind.FETCH_RETRY)

    def test_new_source_is_always_fetched(self):
        should, reason = self.decide(_source("https://a.example.com/rss"))
        self.assertTrue(should)
        self.assertIn("New source", reason)

    def test_recently_fetched_source_is_skipped(self):
        source = _source("https://a.example.com/rss", post_count=10)
        answer = self.decide(source, _state(source, last_success_at=NOW - timedelta(hours=1)))
        self.assertFalse(answer.fetch)
        self.assertEqual(answer.kind, DecisionKind.SKIP_NOT_DUE)

    def test_stale_source_is_fetched(self):
        source = _source("https://a.example.com/rss", post_count=10)
        answer = self.decide(source, _state(source, last_success_at=NOW - timedelta(hours=30)))
        self.assertTrue(answer.fetch)

    def test_staleness_counts_from_the_last_success_not_from_posts(self):
        """Posts but no recorded success (pre-0019 source): due, not 'recently fetched'."""
        source = _source("https://a.example.com/rss", post_count=10)
        self.assertTrue(self.decide(source, None).fetch)

    def test_empty_fetch_counts_as_fresh(self):
        source = _source("https://a.example.com/rss", post_count=10)
        answer = self.decide(source, _state(source, last_outcome="empty",
                                            last_success_at=NOW - timedelta(hours=2)))
        self.assertFalse(answer.fetch)


class YouTubeCadenceTests(unittest.TestCase):
    """YouTube runs on a weekly cadence (the yt-dlp profile floor) and can be switched off."""

    YT = _source("https://www.youtube.com/@a", platform="youtube", post_count=10)
    RSS = _source("https://a.example.com/rss", post_count=10)

    def decide(self, source, hours_ago, *, profile, trigger="scheduler", availability=ALL_ON):
        state = _state(source, last_success_at=NOW - timedelta(hours=hours_ago))
        return si.should_fetch_source(source, state, trigger, profile=profile, now=NOW,
                                      availability=availability)

    def test_youtube_is_skipped_inside_the_weekly_window(self):
        answer = self.decide(self.YT, 48, profile=si.YTDLP_PROFILE)
        self.assertFalse(answer.fetch, "48h is stale for RSS but fresh for a weekly cadence")
        self.assertIn("168.0h", answer.reason)

    def test_youtube_is_fetched_once_the_week_is_up(self):
        self.assertTrue(self.decide(self.YT, 169, profile=si.YTDLP_PROFILE).fetch)

    def test_other_platforms_keep_the_short_cadence(self):
        """The weekly cadence must not leak onto the RSS sources."""
        self.assertTrue(self.decide(self.RSS, 25, profile=si.HOST_LOCK_PROFILE).fetch)

    def test_disabling_ytdlp_skips_youtube_as_unavailable(self):
        answer = self.decide(self.YT, 9999, profile=si.YTDLP_PROFILE, availability=YTDLP_OFF)
        self.assertFalse(answer.fetch)
        self.assertEqual(answer.kind, DecisionKind.SKIP_UNAVAILABLE)
        self.assertIn("yt-dlp disabled", answer.reason)

    def test_disabling_ytdlp_does_not_touch_other_platforms(self):
        answer = self.decide(self.RSS, 25, profile=si.HOST_LOCK_PROFILE, availability=YTDLP_OFF)
        self.assertTrue(answer.fetch)

    def test_disabling_ytdlp_beats_a_manual_trigger(self):
        """Off means off - a manual run must not spawn yt-dlp behind the operator's back."""
        answer = self.decide(self.YT, 9999, profile=si.YTDLP_PROFILE, trigger="manual",
                             availability=YTDLP_OFF)
        self.assertFalse(answer.fetch)

    def test_youtube_decision_raises_the_post_limit_to_the_floor(self):
        source = _source("https://www.youtube.com/@a", platform="youtube", post_count=10,
                         max_posts_per_fetch=5)
        answer = self.decide(source, 200, profile=si.YTDLP_PROFILE)
        self.assertEqual(answer.decision.post_limit, 15)

    def test_interim_profile_follows_the_kind_not_the_platform(self):
        class _Classify:
            def classify_source(self, source):
                return "youtube_channel" if "videos.xml" in source["handle_or_url"] else "generic_rss"

        feed = _source("https://www.youtube.com/feeds/videos.xml?channel_id=x", platform="rss")
        self.assertIs(si.interim_profile(_Classify(), feed), si.YTDLP_PROFILE)
        self.assertIs(si.interim_profile(_Classify(), self.RSS), si.HOST_LOCK_PROFILE)


class _FakeYouTubeService:
    def __init__(self):
        self.limits: list[int] = []

    def fetch_live_posts(self, _handle, limit):
        self.limits.append(limit)
        return []


class _YtFetchService:
    def __init__(self, youtube):
        self.youtube_service = youtube

    def classify_source(self, _source):
        return "youtube_channel"


def _gates() -> dict:
    return {
        "semaphore": asyncio.Semaphore(4),
        "ytdlp_semaphore": asyncio.Semaphore(2),
        "ytdlp_spacer": si._StartSpacer(0),
        "host_limiter": si._HostLimiter(),
    }


class YouTubeBacklogGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_stored_limit_of_five_is_raised_to_the_floor(self):
        youtube = _FakeYouTubeService()
        source = _source("https://www.youtube.com/@a", platform="youtube",
                         max_posts_per_fetch=5)
        await si._fetch_source(source, fetch_service=_YtFetchService(youtube),
                               fetch_state=_FakeFetchState(), trigger="scheduler", **_gates())
        self.assertEqual(youtube.limits, [si.YTDLP_PROFILE.min_posts_per_fetch])

    async def test_a_higher_configured_limit_is_respected(self):
        youtube = _FakeYouTubeService()
        source = _source("https://www.youtube.com/@a", platform="youtube",
                         max_posts_per_fetch=50)
        await si._fetch_source(source, fetch_service=_YtFetchService(youtube),
                               fetch_state=_FakeFetchState(), trigger="scheduler", **_gates())
        self.assertEqual(youtube.limits, [50], "the floor must not cap an operator's setting")

    async def test_the_decision_limit_is_used(self):
        youtube = _FakeYouTubeService()
        source = _source("https://www.youtube.com/@a", platform="youtube",
                         max_posts_per_fetch=5)
        await si._fetch_source(source, fetch_service=_YtFetchService(youtube),
                               fetch_state=_FakeFetchState(), trigger="scheduler",
                               post_limit=30, **_gates())
        self.assertEqual(youtube.limits, [30])


class _FakeFetchService:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def classify_source(self, source):
        return "youtube_channel" if source.get("platform") == "youtube" else "generic_rss"

    async def fetch_live_posts(self, source, limit=20):
        return self.behaviour(source, limit)


class FetchSourceNeverRaisesTests(unittest.IsolatedAsyncioTestCase):
    """_fetch_source runs under asyncio.gather; anything escaping costs the cycle."""

    async def _run(self, source, behaviour, fetch_state=None):
        return await si._fetch_source(
            source,
            fetch_service=_FakeFetchService(behaviour),
            fetch_state=fetch_state or _FakeFetchState(),
            trigger="scheduler",
            **_gates(),
        )

    async def test_a_raising_fetch_returns_an_error_result(self):
        def boom(_source, _limit):
            raise RuntimeError("feed exploded")

        result = await self._run(_source("https://a.example.com/rss"), boom)
        self.assertEqual(result["posts"], [])
        self.assertIn("feed exploded", str(result["error"]))

    async def test_malformed_settings_do_not_raise(self):
        """Reading source['settings'] must itself be inside the try.

        A settings dict missing max_posts_per_fetch was a KeyError raised OUTSIDE the
        original try, so 'never raises' was not actually true.
        """
        source = {"id": "x", "handle_or_url": "https://a.example.com/rss",
                  "platform": "rss", "settings": {}}
        result = await self._run(source, lambda _s, _l: [])
        self.assertIsInstance(result, dict)
        self.assertIn("posts", result)

    async def test_settings_missing_entirely_does_not_raise(self):
        source = {"id": "x", "handle_or_url": "https://a.example.com/rss", "platform": "rss"}
        result = await self._run(source, lambda _s, _l: [])
        self.assertIsInstance(result, dict)

    async def test_a_failing_fetch_state_store_does_not_raise(self):
        result = await self._run(_source("https://a.example.com/rss"), lambda _s, _l: [],
                                 fetch_state=_RaisingFetchState())
        self.assertIsNone(result["error"])

    async def test_one_failure_does_not_take_the_gather_down(self):
        def sometimes(source, _limit):
            if "bad" in source["handle_or_url"]:
                raise RuntimeError("nope")
            return [{"url": "u"}]

        sources = [_source("https://good1.example.com/rss"),
                   _source("https://bad.example.com/rss"),
                   _source("https://good2.example.com/rss")]
        results = await asyncio.gather(*(self._run(s, sometimes) for s in sources))
        self.assertEqual(len(results), 3)
        self.assertEqual(sum(1 for r in results if r.get("error")), 1)
        self.assertEqual(sum(1 for r in results if r["posts"]), 2,
                         "the healthy sources must still deliver their posts")


class FetchOutcomeRecordingTests(unittest.IsolatedAsyncioTestCase):
    """Every fetch writes exactly one outcome; the classification is healthy/empty/error."""

    async def _recorded_outcome(self, behaviour):
        state = _FakeFetchState()
        source = _source("https://a.example.com/rss")
        await si._fetch_source(source, fetch_service=_FakeFetchService(behaviour),
                               fetch_state=state, trigger="manual", **_gates())
        self.assertEqual(len(state.outcomes), 1)
        outcome, trigger = state.outcomes[0]
        self.assertEqual(outcome.source_id, source["id"])
        self.assertEqual(trigger, "manual")
        return outcome

    async def test_posts_are_healthy(self):
        outcome = await self._recorded_outcome(lambda _s, _l: [{"url": "a"}, {"url": "b"}])
        self.assertEqual((outcome.status, outcome.fetched), (OutcomeStatus.HEALTHY, 2))

    async def test_zero_posts_is_empty_not_healthy(self):
        """An empty answer is how a silently dead feed looks - but it is still a success."""
        outcome = await self._recorded_outcome(lambda _s, _l: [])
        self.assertEqual(outcome.status, OutcomeStatus.EMPTY)
        self.assertTrue(outcome.status.is_success)

    async def test_a_raise_is_an_error(self):
        def boom(_s, _l):
            raise RuntimeError("503")

        outcome = await self._recorded_outcome(boom)
        self.assertEqual(outcome.status, OutcomeStatus.ERROR)
        self.assertIn("503", outcome.error)

    async def test_connector_outage_is_unavailable_not_error(self):
        """A shared connector fault must not advance every telegram source's backoff."""
        state = _FakeFetchState()
        sources = [_source("@a", platform="telegram"), _source("@b", platform="telegram")]
        results = await si._record_connector_outage(state, sources, "session locked", "scheduler")
        self.assertEqual(len(results), 2)
        self.assertEqual({o.status for o, _ in state.outcomes}, {OutcomeStatus.UNAVAILABLE})
        self.assertIn("session locked", state.outcomes[0][0].error)


class _FakeSourcesService:
    def __init__(self, sources):
        self.sources = sources

    def get_all_sources_with_settings(self):
        return [dict(s) for s in self.sources]


class SafeIngestDecisionPhaseTests(unittest.IsolatedAsyncioTestCase):
    """safe_ingest_posts end to end through its seams, for runs that fetch nothing."""

    async def _run(self, sources, states=None, trigger="scheduler", **kwargs):
        fetch_state = _FakeFetchState(states)
        result = await si.safe_ingest_posts(
            trigger,
            sources_service=_FakeSourcesService(sources),
            fetch_service=_FakeFetchService(lambda _s, _l: self.fail("nothing may be fetched")),
            fetch_state=fetch_state,
            clock=lambda: NOW,
            **kwargs,
        )
        return result, fetch_state

    async def test_ytdlp_off_counts_unavailable_not_backoff(self):
        youtube = _source("https://www.youtube.com/@a", platform="youtube", post_count=10)
        # In backoff too: the Mark VIII 🚫 prefix counted this as backoff either way.
        states = {youtube["id"]: _state(youtube, consecutive_failures=3,
                                        next_retry_at=NOW + timedelta(hours=1))}
        with unittest.mock.patch.dict(os.environ, {"INSIGHT_YTDLP_ENABLED": "0"}):
            result, fetch_state = await self._run([youtube], states)

        self.assertEqual(result["sources_backoff_skipped"], 0)
        self.assertEqual(result["sources_unavailable_skipped"], 1)
        self.assertEqual(result["decisions"], {"skip_unavailable": 1})
        self.assertEqual(result["sources_attempted"], 0)
        self.assertEqual(fetch_state.outcomes, [], "unavailable is never an outcome of a skip")
        self.assertEqual([d.kind for _, d in fetch_state.decisions], [DecisionKind.SKIP_UNAVAILABLE])

    async def test_manual_trigger_ignores_backoff_but_respects_freshness(self):
        source = _source("https://a.example.com/rss", post_count=10)
        states = {source["id"]: _state(source, consecutive_failures=5,
                                       next_retry_at=NOW + timedelta(hours=4),
                                       last_success_at=NOW - timedelta(hours=2))}
        result, _ = await self._run([source], states, trigger="manual",
                                    availability=lambda: ALL_ON)
        self.assertEqual(result["decisions"], {"skip_not_due": 1})
        self.assertEqual(result["sources_backoff_skipped"], 0)

    async def test_backoff_is_counted_from_the_decision_kind(self):
        source = _source("https://a.example.com/rss", post_count=10)
        states = {source["id"]: _state(source, consecutive_failures=2,
                                       next_retry_at=NOW + timedelta(hours=1))}
        result, fetch_state = await self._run([source], states, availability=lambda: ALL_ON)
        self.assertEqual(result["sources_backoff_skipped"], 1)
        self.assertEqual(fetch_state.refreshed, 1, "cadence is refreshed once per cycle")

    async def test_disabled_sources_are_not_decided(self):
        source = _source("https://a.example.com/rss")
        source["enabled"] = False
        result, fetch_state = await self._run([source], availability=lambda: ALL_ON)
        self.assertEqual(fetch_state.decisions, [])
        self.assertEqual(result["sources_attempted"], 0)


class EnrichmentTests(unittest.TestCase):
    def test_batch_is_chunked_and_fully_covered(self):
        seen: list[int] = []
        posts = [{"id": i} for i in range(250)]
        si._run_enrichment("test", lambda chunk: seen.extend(p["id"] for p in chunk), posts)
        self.assertEqual(seen, list(range(250)), "every post must reach the service exactly once")

    def test_a_failing_chunk_does_not_lose_the_rest(self):
        seen: list[int] = []

        def flaky(chunk):
            if chunk[0]["id"] == 0:
                raise RuntimeError("first chunk fails")
            seen.extend(p["id"] for p in chunk)

        posts = [{"id": i} for i in range(250)]
        si._run_enrichment("test", flaky, posts)
        self.assertEqual(len(seen), 250 - si.ENRICH_CHUNK_SIZE)

    def test_empty_batch_is_a_no_op(self):
        si._run_enrichment("test", lambda _chunk: self.fail("must not be called"), [])


class ResultShapeTests(unittest.TestCase):
    """run_scheduler and insight_api_bridge read these keys off every return path."""

    REQUIRED = {"success", "posts_ingested", "posts_fetched", "posts_duplicate",
                "sources_ingested", "sources_attempted", "sources_failed", "failures", "error"}

    def test_empty_result_carries_the_full_key_set(self):
        self.assertTrue(self.REQUIRED.issubset(si._empty_result().keys()))

    def test_failed_result_shape(self):
        source = _source("https://a.example.com/rss")
        result = si._failed_result(source, "boom")
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["error"], "boom")
        self.assertIs(result["source"], source)


if __name__ == "__main__":
    unittest.main()
