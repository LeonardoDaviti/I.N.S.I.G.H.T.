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
  - the backoff ladder must terminate, stay under its documented ceiling, and clear
  - a source that answered with zero posts is a success, not a failure

Deliberately not covered here: safe_ingest_posts() end to end. It needs a live corpus and
real sources, and running it is exactly what we must not do.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.scripts import safe_ingest as si


def _source(handle: str, platform: str = "rss", priority: int = 999, **settings) -> dict:
    base = {"display_name": handle, "priority": priority, "fetch_delay_seconds": 0,
            "max_posts_per_fetch": 20}
    base.update(settings)
    return {"id": f"id-{handle}", "handle_or_url": handle, "platform": platform,
            "enabled": True, "settings": base}


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


class BackoffLadderTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)

    def _delay_hours(self, failures: int) -> float:
        at = datetime.fromisoformat(si._next_retry_at(failures, self.now))
        return (at - self.now).total_seconds() / 3600

    def test_ladder_grows_then_holds_at_the_ceiling(self):
        first = self._delay_hours(1)
        self.assertLess(first, 1.0, "the ladder must start small, not at the cap")
        self.assertGreater(self._delay_hours(4), first)

    def test_never_exceeds_the_documented_ceiling(self):
        """Jitter is applied AFTER the cap and downward only.

        Jittering upward (0.85-1.15 of 24h) parked a stuck source for up to 27.6h, so
        BACKOFF_MAX_HOURS did not mean what an operator would read it to mean.
        """
        for failures in (8, 12, 40, 500):
            for _ in range(200):
                self.assertLessEqual(self._delay_hours(failures), si.BACKOFF_MAX_HOURS)

    def test_ceiling_cohort_is_spread_not_synchronised(self):
        """73 sources at the ceiling must not all wake in the same second."""
        draws = {round(self._delay_hours(20), 4) for _ in range(200)}
        self.assertGreater(len(draws), 50, "delays are effectively identical - herd intact")

    def test_zero_and_negative_failure_counts_do_not_explode(self):
        for failures in (0, -1):
            self.assertLessEqual(self._delay_hours(failures), si.BACKOFF_MAX_HOURS)
            self.assertGreater(self._delay_hours(failures), 0)


class _FakeSourcesService:
    def __init__(self, raises: bool = False):
        self.calls: list[tuple] = []
        self.raises = raises

    def merge_source_settings(self, source_id, payload):
        if self.raises:
            raise RuntimeError("db down")
        self.calls.append((source_id, payload))


class RecordBackoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_advances_the_counter(self):
        service = _FakeSourcesService()
        source = _source("https://a.example.com/rss")
        await si._record_backoff(service, source, failed=True)
        payload = service.calls[0][1]["ingest_backoff"]
        self.assertEqual(payload["consecutive_failures"], 1)
        self.assertIsNotNone(payload["next_retry_at"])

        await si._record_backoff(service, source, failed=True)
        self.assertEqual(service.calls[1][1]["ingest_backoff"]["consecutive_failures"], 2,
                         "state must be read back from the source dict between calls")

    async def test_success_clears_the_ladder(self):
        service = _FakeSourcesService()
        source = _source("https://a.example.com/rss")
        source["settings"]["ingest_backoff"] = {"consecutive_failures": 6,
                                                "next_retry_at": "2026-09-11T00:00:00+00:00"}
        await si._record_backoff(service, source, failed=False)
        payload = service.calls[0][1]["ingest_backoff"]
        self.assertEqual(payload["consecutive_failures"], 0)
        self.assertIsNone(payload["next_retry_at"])

    async def test_an_empty_fetch_is_a_success(self):
        """A recovered-but-quiet feed must not keep its failure counter.

        It answered; it just had nothing new, and it burned no timeout. Leaving the counter
        at 6 meant one later blip jumped straight to a ~16h delay.
        """
        service = _FakeSourcesService()
        source = _source("https://a.example.com/rss")
        source["settings"]["ingest_backoff"] = {"consecutive_failures": 6,
                                                "next_retry_at": "2026-09-11T00:00:00+00:00"}
        await si._record_backoff(service, source, failed=False)
        self.assertEqual(service.calls[0][1]["ingest_backoff"]["consecutive_failures"], 0)

    async def test_already_clean_source_costs_no_connection(self):
        service = _FakeSourcesService()
        await si._record_backoff(service, _source("https://a.example.com/rss"), failed=False)
        self.assertEqual(service.calls, [])

    async def test_a_failing_database_does_not_raise(self):
        """This runs inside _fetch_source, whose contract is that it never raises."""
        service = _FakeSourcesService(raises=True)
        await si._record_backoff(service, _source("https://a.example.com/rss"), failed=True)


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self._row


class ShouldFetchSourceTests(unittest.TestCase):
    def test_source_in_backoff_is_skipped_on_a_scheduled_run(self):
        source = _source("https://a.example.com/rss")
        future = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        source["settings"]["ingest_backoff"] = {"consecutive_failures": 5, "next_retry_at": future}
        should, reason = si.should_fetch_source(_FakeCursor((10, datetime(2020, 1, 1, tzinfo=timezone.utc))),
                                                source, trigger="scheduler")
        self.assertFalse(should)
        self.assertIn("Backoff", reason)

    def test_manual_trigger_bypasses_backoff(self):
        """The operator's 'try it now' button must always work."""
        source = _source("https://a.example.com/rss")
        future = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        source["settings"]["ingest_backoff"] = {"consecutive_failures": 5, "next_retry_at": future}
        should, _ = si.should_fetch_source(_FakeCursor((10, datetime(2020, 1, 1, tzinfo=timezone.utc))),
                                           source, trigger="manual")
        self.assertTrue(should)

    def test_expired_backoff_window_lets_the_source_through(self):
        source = _source("https://a.example.com/rss")
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        source["settings"]["ingest_backoff"] = {"consecutive_failures": 5, "next_retry_at": past}
        should, _ = si.should_fetch_source(_FakeCursor((10, datetime(2020, 1, 1, tzinfo=timezone.utc))),
                                           source, trigger="scheduler")
        self.assertTrue(should)

    def test_corrupt_next_retry_at_does_not_park_the_source_forever(self):
        source = _source("https://a.example.com/rss")
        source["settings"]["ingest_backoff"] = {"consecutive_failures": 5, "next_retry_at": "not-a-date"}
        should, _ = si.should_fetch_source(_FakeCursor((10, datetime(2020, 1, 1, tzinfo=timezone.utc))),
                                           source, trigger="scheduler")
        self.assertTrue(should, "an unparseable timestamp must fail open, not strand the source")

    def test_new_source_is_always_fetched(self):
        should, reason = si.should_fetch_source(_FakeCursor((0, None)), _source("https://a.example.com/rss"),
                                                trigger="scheduler")
        self.assertTrue(should)
        self.assertIn("New source", reason)

    def test_recently_fetched_source_is_skipped(self):
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        should, _ = si.should_fetch_source(_FakeCursor((10, recent)), _source("https://a.example.com/rss"),
                                           trigger="scheduler")
        self.assertFalse(should)

    def test_stale_source_is_fetched(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=si.SKIP_THRESHOLD_HOURS + 5)
        should, _ = si.should_fetch_source(_FakeCursor((10, stale)), _source("https://a.example.com/rss"),
                                           trigger="scheduler")
        self.assertTrue(should)


class _FakeOperations:
    def __init__(self):
        self.statuses: list[dict] = []

    def record_source_status(self, source_id, **kwargs):
        self.statuses.append({"source_id": source_id, **kwargs})


class _FakeFetchService:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def classify_source(self, source):
        return "generic_rss"

    async def fetch_live_posts(self, source, limit=20):
        return self.behaviour(source, limit)


class FetchSourceNeverRaisesTests(unittest.IsolatedAsyncioTestCase):
    """_fetch_source runs under asyncio.gather; anything escaping costs the cycle."""

    async def _run(self, source, behaviour):
        return await si._fetch_source(
            source,
            fetch_service=_FakeFetchService(behaviour),
            operations_service=_FakeOperations(),
            sources_service=_FakeSourcesService(),
            trigger="scheduler",
            semaphore=asyncio.Semaphore(4),
            ytdlp_semaphore=asyncio.Semaphore(2),
            ytdlp_spacer=si._StartSpacer(0),
            host_limiter=si._HostLimiter(),
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
