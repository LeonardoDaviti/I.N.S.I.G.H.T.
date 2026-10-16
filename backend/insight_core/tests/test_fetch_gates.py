"""FetchGates (Mark IX B3, spec §D.3 and §5.6).

The HostLimiter, StartSpacer, interleave and host-floor tests moved here from
test_safe_ingest.py together with the classes; the slot() tests are new.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.gates import HOST_FLOORS, FetchGates, HostLimiter, StartSpacer, interleave_by_host
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import PolitenessProfile, source_host_key
from insight_core.ingestion.kinds.nitter_rss import NITTER_HOSTS
from insight_core.ingestion.kinds.telegram_rss import TELEGRAM_RSS_HOSTS
from insight_core.tests._ingestion_fakes import SleepClock

HOST_LOCK = PolitenessProfile(concurrency_pool="host-lock")
YTDLP = PolitenessProfile(concurrency_pool="ytdlp", requires="ytdlp")


def _source(handle: str, platform: str = "rss", priority: int = 999) -> dict:
    return {"id": f"id-{handle}", "handle_or_url": handle, "platform": platform,
            "settings": {"priority": priority}}


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
                self.assertEqual(source_host_key(_source(left)), source_host_key(_source(right)))

    def test_distinct_hosts_stay_distinct(self):
        self.assertNotEqual(source_host_key(_source("https://github.com/a.atom")),
                            source_host_key(_source("https://reddit.com/r/a/.rss")))

    def test_bare_handles_group_per_platform_not_all_together(self):
        telegram = source_host_key(_source("@chan", platform="telegram"))
        youtube = source_host_key(_source("@chan2", platform="youtube"))
        self.assertNotEqual(telegram, youtube)
        self.assertEqual(telegram, source_host_key(_source("@other", platform="telegram")))
        self.assertIs(HostLimiter.host_key, source_host_key)


class HostFloorTableTests(unittest.TestCase):
    def test_every_telegram_and_nitter_host_has_a_floor(self):
        """The Mark VIII hardcoded table covered 2 of 5 hosts; telegram.local got 0s."""
        for host in TELEGRAM_RSS_HOSTS:
            self.assertEqual(HOST_FLOORS.get(host), 5.0, host)
        for host in NITTER_HOSTS:
            self.assertEqual(HOST_FLOORS.get(host), 10.0, host)
        self.assertEqual(HOST_FLOORS["platform:telegram"], 2.0)


class HostLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_host_requests_do_not_overlap(self):
        limiter = HostLimiter()
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
        limiter = HostLimiter()
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
        clock = SleepClock()
        limiter = HostLimiter({}, clock=clock, sleep=clock.sleep)
        for _ in range(3):
            async with limiter.slot("example.com", 0.05):
                pass
        self.assertEqual(clock.sleeps, [0.05, 0.05])

    async def test_host_floor_raises_a_lower_source_delay(self):
        """A source configured with 0s on telegram.local still gets the bridge's floor."""
        clock = SleepClock()
        limiter = HostLimiter({"telegram.local": 5.0}, clock=clock, sleep=clock.sleep)
        for _ in range(2):
            async with limiter.slot("telegram.local", 0):
                pass
        self.assertEqual(clock.sleeps, [5.0])

    async def test_a_higher_source_delay_beats_the_floor(self):
        clock = SleepClock()
        limiter = HostLimiter({"telegram.local": 5.0}, clock=clock, sleep=clock.sleep)
        for _ in range(2):
            async with limiter.slot("telegram.local", 12):
                pass
        self.assertEqual(clock.sleeps, [12.0])


class LearnedPaceTests(unittest.IsolatedAsyncioTestCase):
    """Issue 0016: a host that limits us gets a doubled gap; a run of successes shrinks it."""

    def test_a_limit_doubles_the_gap_with_a_minimum_and_a_cap(self):
        limiter = HostLimiter({"reddit.com": 8.0, "big.test": 100.0})
        limiter.limited("reddit.com")
        self.assertEqual(limiter.gap("reddit.com"), 16.0)
        limiter.limited("free.test")
        self.assertEqual(limiter.gap("free.test"), 5.0, "a host with no floor still slows to 5 s")
        limiter.limited("big.test")
        self.assertEqual(limiter.gap("big.test"), 120.0)

    def test_the_wait_is_retry_after_capped_and_a_minute_without_it(self):
        limiter = HostLimiter({})
        self.assertEqual(limiter.limited("a.test", 7), 7)
        self.assertEqual(limiter.limited("a.test", 600), 120)
        self.assertEqual(limiter.limited("a.test", None), 60)

    def test_twenty_successes_shrink_the_gap_by_a_quarter_never_below_the_floor(self):
        limiter = HostLimiter({"reddit.com": 8.0})
        limiter.limited("reddit.com")   # 16
        for _ in range(19):
            limiter.succeeded("reddit.com")
        self.assertEqual(limiter.gap("reddit.com"), 16.0)
        limiter.succeeded("reddit.com")
        self.assertEqual(limiter.gap("reddit.com"), 12.0)
        for _ in range(40):
            limiter.succeeded("reddit.com")
        self.assertEqual(limiter.gap("reddit.com"), 8.0)

    def test_a_limit_resets_the_success_count(self):
        limiter = HostLimiter({})
        limiter.limited("a.test")       # 5
        for _ in range(19):
            limiter.succeeded("a.test")
        limiter.limited("a.test")       # 10, count back to 0
        limiter.succeeded("a.test")
        self.assertEqual(limiter.gap("a.test"), 10.0)

    async def test_spacing_uses_the_learned_gap(self):
        clock = SleepClock()
        limiter = HostLimiter({"reddit.com": 8.0}, clock=clock, sleep=clock.sleep)
        async with limiter.slot("reddit.com"):
            pass
        limiter.limited("reddit.com")
        async with limiter.slot("reddit.com"):
            pass
        self.assertEqual(clock.sleeps, [16.0])


class StartSpacerTests(unittest.IsolatedAsyncioTestCase):
    async def test_spaces_starts_without_serialising_the_work(self):
        spacer = StartSpacer(0.03)
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
        spacer = StartSpacer(0)
        await asyncio.wait_for(asyncio.gather(*(spacer.wait() for _ in range(50))), timeout=1)


class InterleaveTests(unittest.TestCase):
    def test_same_host_runs_are_broken_up(self):
        sources = ([_source(f"https://www.youtube.com/@c{i}") for i in range(4)]
                   + [_source(f"https://feed{i}.example.com/rss") for i in range(2)])
        ordered = interleave_by_host(sources)
        hosts = [source_host_key(s) for s in ordered]
        self.assertEqual(len(ordered), len(sources), "interleaving must not drop sources")
        self.assertNotEqual(hosts[0], hosts[1], "the first tasks gather starts must want different gates")

    def test_priority_tiers_stay_ordered(self):
        sources = [_source("https://a.example.com/1", priority=5),
                   _source("https://b.example.com/1", priority=1),
                   _source("https://c.example.com/1", priority=1)]
        self.assertEqual([s["settings"]["priority"] for s in interleave_by_host(sources)], [1, 1, 5])

    def test_empty_input(self):
        self.assertEqual(interleave_by_host([]), [])


class SlotTests(unittest.IsolatedAsyncioTestCase):
    async def _peak(self, gates: FetchGates, entries: list[tuple[PolitenessProfile, str]]) -> int:
        live = {"n": 0, "max": 0}

        async def enter(profile, host):
            async with gates.slot(profile, host):
                live["n"] += 1
                live["max"] = max(live["max"], live["n"])
                await asyncio.sleep(0.03)
                live["n"] -= 1

        await asyncio.gather(*(enter(p, h) for p, h in entries))
        return live["max"]

    async def test_ytdlp_profile_holds_the_ytdlp_semaphore(self):
        gates = FetchGates(max_concurrency=8, ytdlp_concurrency=2, ytdlp_min_start_interval_s=0)
        held = asyncio.Event()
        release = asyncio.Event()
        entered: list[int] = []

        async def hold(i):
            async with gates.slot(YTDLP, "youtube.com"):
                entered.append(i)
                if len(entered) == 2:
                    held.set()
                await release.wait()

        tasks = [asyncio.create_task(hold(i)) for i in range(3)]
        await asyncio.wait_for(held.wait(), timeout=1)
        await asyncio.sleep(0.02)
        self.assertEqual(len(entered), 2, "a third yt-dlp entry must wait while two are held")
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
        self.assertEqual(len(entered), 3)

    async def test_ytdlp_slots_do_not_take_the_host_lock(self):
        gates = FetchGates(ytdlp_concurrency=2, ytdlp_min_start_interval_s=0)
        self.assertEqual(await self._peak(gates, [(YTDLP, "youtube.com")] * 2), 2)

    async def test_host_lock_serialises_one_host_but_not_two(self):
        gates = FetchGates(host_floors={})
        self.assertEqual(await self._peak(gates, [(HOST_LOCK, "a")] * 3), 1)
        self.assertEqual(await self._peak(gates, [(HOST_LOCK, "a"), (HOST_LOCK, "b"), (HOST_LOCK, "c")]), 3)

    async def test_global_budget_caps_everything(self):
        gates = FetchGates(max_concurrency=2, host_floors={})
        self.assertEqual(await self._peak(gates, [(HOST_LOCK, f"h{i}") for i in range(5)]), 2)

    async def test_floors_are_keyed_by_host_not_kind(self):
        """generic_rss on www.reddit.com and reddit_subreddit r/x both get 8s; tg RSS 5s; others 0."""
        registry = KindRegistry.default(KindHttp(), object())
        cases = [
            (_source("https://www.reddit.com/r/x/.rss"), "generic_rss", 8.0),
            (_source("r/x", platform="reddit"), "reddit_subreddit", 8.0),
            (_source("https://tg.i-c-a.su/rss/chan?limit=50"), "telegram_rss", 5.0),
            (_source("https://unlisted.example.com/feed"), "generic_rss", None),
        ]
        for source, kind_name, floor in cases:
            with self.subTest(handle=source["handle_or_url"]):
                kind = registry.resolve(source)
                self.assertEqual(kind.name, kind_name)
                clock = SleepClock()
                gates = FetchGates(clock=clock, sleep=clock.sleep)
                for _ in range(2):
                    async with gates.slot(kind.profile, kind.host_key(source)):
                        pass
                self.assertEqual(clock.sleeps, [floor] if floor else [])

    async def test_per_source_delay_applies_when_above_the_floor(self):
        clock = SleepClock()
        gates = FetchGates(host_floors={}, clock=clock, sleep=clock.sleep)
        for _ in range(2):
            async with gates.slot(HOST_LOCK, "a.example.com", per_source_delay_s=3):
                pass
        self.assertEqual(clock.sleeps, [3.0])

    async def test_shared_is_one_instance_per_loop(self):
        self.assertIs(FetchGates.shared(), FetchGates.shared())


if __name__ == "__main__":
    unittest.main()
