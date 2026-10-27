import unittest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))


import psycopg

from insight_core.db.repo_posts import PostDraft, SaveBatchResult
from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import ArchivePage, Inspection, KindUnavailable, PolitenessProfile, start_at
from insight_core.ingestion.ports import DbPostSaver
from insight_core.ingestion.kinds.youtube import YOUTUBE_PROFILE
from insight_core.ingestion.schedule import Availability
from insight_core.ingestion.kinds.telegram_rss import TelegramRssKind
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.services.sources_service import SourcesService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._ingestion_fakes import SleepClock, SpyFetchGates
from insight_core.tests._kind_fakes import FakeKind, RecordingKindSession


class ArchiveAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    """E7: the archive honours the yt-dlp switch like every live fetch does."""

    async def test_an_unavailable_kind_refuses_to_plan_or_run(self):
        kind = FakeKind("fake_youtube", YOUTUBE_PROFILE)
        service = SourceFetchService(
            "postgresql://test:test@localhost/test",
            kinds=KindRegistry([kind]),
            availability=lambda: Availability(ytdlp_enabled=False, telegram_credentials=False),
        )
        service.sources_service = _PlanSources()
        with self.assertRaises(KindUnavailable) as ctx:
            await service.plan_archive("s1")
        self.assertIn("yt-dlp", ctx.exception.reason)
        with self.assertRaises(KindUnavailable):
            await service.archive_source("s1")


class _Posts:
    def __init__(self):
        self.count = 0

    def get_source_post_stats(self, _source_id):
        return {"post_count": self.count}


class _Sources:
    def __init__(self):
        self.current: dict = {}
        self.saved: dict = {}

    def get_source_by_id(self, source_id):
        return {"id": source_id}

    def get_source_with_settings(self, _source_id):
        return {"settings": {"archive": self.current}}

    def merge_source_settings(self, _source_id, settings):
        self.saved = settings["archive"]


class ArchiveBacklogEstimateTests(unittest.TestCase):
    """Backlog and time-to-archive are derived on every live fetch, not remembered.

    They used to be written only by plan_archive/run_archive, so a source that had never
    been planned carried no backlog figure at all, and a partly-archived one kept whatever
    its last plan produced - the number never fell as posts came in.
    (B3: the writer moved to ingestion/archive_metadata.py and takes the kind explicitly.)
    """

    def setUp(self):
        self.posts = _Posts()
        self.sources = _Sources()
        self.writer = ArchiveMetadataWriter(posts=self.posts, sources=self.sources)
        self.kinds = KindRegistry.default(KindHttp(), object())

    @property
    def current(self):
        return self.sources.current

    @current.setter
    def current(self, value):
        self.sources.current = value

    def _record(self, stored, data, mode="live", kind="generic_rss"):
        self.posts.count = stored
        self.writer.record("s1", self.kinds.by_name(kind), data, mode)
        return self.sources.saved

    def test_backlog_is_available_minus_stored(self):
        saved = self._record(120, {"available_posts": 500, "page_size": 20})
        self.assertEqual(saved["backlog_posts"], 380)
        self.assertEqual(saved["source_type"], "generic_rss")

    def test_backlog_falls_as_posts_arrive(self):
        first = self._record(100, {"available_posts": 500, "page_size": 20})["backlog_posts"]
        second = self._record(400, {"available_posts": 500, "page_size": 20})["backlog_posts"]
        self.assertEqual((first, second), (400, 100))

    def test_a_fully_archived_source_reports_zero_not_negative(self):
        saved = self._record(900, {"available_posts": 500, "page_size": 20})
        self.assertEqual(saved["backlog_posts"], 0)
        self.assertEqual(saved["estimated_seconds"], 0)
        self.assertEqual(saved["status"], "archived")

    def test_time_estimate_scales_with_the_backlog(self):
        small = self._record(480, {"available_posts": 500, "page_size": 10}, kind="telegram_rss")["estimated_seconds"]
        large = self._record(0, {"available_posts": 500, "page_size": 10}, kind="telegram_rss")["estimated_seconds"]
        self.assertGreater(large, small)
        self.assertGreater(large, 0)

    def test_rate_limited_sources_are_estimated_slower_than_plain_rss(self):
        """The estimate must reflect the politeness delays the archive will actually pay."""
        rss = self._record(0, {"available_posts": 500, "page_size": 10})["estimated_seconds"]
        telegram = self._record(0, {"available_posts": 500, "page_size": 10}, kind="telegram_rss")["estimated_seconds"]
        self.assertGreater(telegram, rss)

    def test_status_updates_on_a_live_fetch(self):
        self.current = {"status": "not_archived"}
        saved = self._record(250, {"available_posts": 500, "page_size": 20})
        self.assertEqual(saved["status"], "partial",
                         "the badge must not stay frozen at whatever the last archive run left")

    def test_unknown_available_posts_keeps_the_stored_figures(self):
        self.current = {"estimated_seconds": 99, "status": "partial"}
        saved = self._record(10, {})
        self.assertEqual(saved["estimated_seconds"], 99)
        self.assertEqual(saved["status"], "partial")

    def test_unknown_available_gives_none_backlog(self):
        saved = self._record(10, {"page_size": 20}, mode="plan")
        self.assertIsNone(saved["backlog_posts"])

    def test_only_planning_marks_the_source_measured(self):
        self.assertIsNone(self._record(10, {"available_posts": 50}, mode="live").get("last_inspected_at"))
        self.assertIsNone(self._record(10, {"available_posts": 50}, mode="archive").get("last_inspected_at"))
        self.assertIsNotNone(self._record(10, {"available_posts": 50}, mode="plan")["last_inspected_at"])

    def test_a_finished_archives_checkpoint_is_not_resume_ready(self):
        saved = self._record(10, {"checkpoint": {"mode": "telegram_page", "next_page": 9}}, mode="archive",
                             kind="telegram_rss")
        self.assertIn("completed_at", saved["checkpoint"])
        self.assertFalse(saved["resume_ready"])


class ArchiveMetadataWriterTests(unittest.TestCase):
    def test_live_record_uses_the_kind_for_estimates_and_resume(self):
        posts, sources = _Posts(), _Sources()
        sources.current = {"checkpoint": {"mode": "fake", "next": 3}}
        posts.count = 10
        kind = FakeKind("fake_kind")
        ArchiveMetadataWriter(posts=posts, sources=sources).record(
            "s1", kind, {"available_posts": 50, "page_size": 20}, "live")
        self.assertEqual(kind.estimate_calls, [(40, 20)])
        self.assertEqual(kind.resumable_calls, [{"mode": "fake", "next": 3}])
        self.assertTrue(sources.saved["resume_ready"])
        self.assertEqual(sources.saved["estimated_pages"], 2)
        self.assertEqual(sources.saved["source_type"], "fake_kind")


class _PlanSources(_Sources):
    def get_source_by_id(self, source_id):
        return {"id": source_id, "platform": "rss", "handle_or_url": "https://tg.i-c-a.su/rss/chan",
                "settings": {"max_posts_per_fetch": 20}}


class PlanArchiveRateOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_delay_override_is_persisted_and_estimated(self):
        kind = FakeKind("fake_paged", TelegramRssKind(KindHttp()).profile,
                        inspection=Inspection(available_posts=100, page_size=10, first_post_date=None))
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]))
        service.sources_service = sources = _PlanSources()
        service.posts_service = _Posts()
        service.archive_metadata = ArchiveMetadataWriter(posts=service.posts_service, sources=sources)

        plan = await service.plan_archive("s1", rate_limit_overrides={
            "page_delay_seconds": 9, "batch_size": None, "batch_cooldown_seconds": None})

        expected = kind.profile.estimate_seconds(10, kind.profile.rate_limit({"page_delay_seconds": 9}))
        self.assertEqual(sources.saved["rate_limit"]["page_delay_seconds"], 9)
        self.assertEqual(sources.saved["rate_limit"]["batch_size"], 10, "the profile's batch values stay")
        self.assertEqual(plan["estimated_seconds"], expected)
        self.assertEqual(sources.saved["estimated_seconds"], expected)
        self.assertEqual(plan["estimated_pages"], 10)


class _SupportSources(_Sources):
    def __init__(self, max_posts_per_fetch=50, available=None):
        super().__init__()
        self.max_posts_per_fetch = max_posts_per_fetch
        self.current = {} if available is None else {"available_posts": available}

    def get_source_by_id(self, source_id):
        # The raw row: a setting the user never set is absent (issue 0027: it was read as 50).
        return {"id": source_id, "platform": "rss", "handle_or_url": "https://example.com/feed", "settings": {}}

    def get_source_with_settings(self, source_id):
        # Merged with the kind's defaults, as every fetch reads them.
        return {"id": source_id, "platform": "rss", "handle_or_url": "https://example.com/feed",
                "settings": {"max_posts_per_fetch": self.max_posts_per_fetch, "archive": self.current}}


class ArchiveSupportTests(unittest.TestCase):
    """What the source sheet shows before anything touches the network: can this source archive?"""

    def support(self, kind, sources, availability=None):
        service = SourceFetchService(
            "postgresql://test:test@localhost/test",
            kinds=KindRegistry([kind]),
            availability=availability or (lambda: Availability(ytdlp_enabled=True, telegram_credentials=True)),
        )
        service.sources_service = sources
        return service.archive_support("s1")

    def history_kind(self, profile=None):
        kind = FakeKind("fake_history", profile)
        kind.available_basis = "exact"
        return kind

    def feed_kind(self):
        kind = FakeKind("fake_feed")
        kind.available_basis = "feed_window"
        return kind

    def test_a_kind_with_history_can_archive_and_says_what_its_count_means(self):
        support = self.support(self.history_kind(), _SupportSources())
        self.assertEqual(support, {"kind": "fake_history", "available_basis": "exact", "archivable": True,
                                   "reason": None, "unavailable": False, "live_fetch_limit": 50})

    def test_an_unavailable_kind_cannot_archive_and_says_why(self):
        support = self.support(self.history_kind(YOUTUBE_PROFILE), _SupportSources(),
                               availability=lambda: Availability(ytdlp_enabled=False, telegram_credentials=False))
        self.assertFalse(support["archivable"])
        self.assertTrue(support["unavailable"])
        self.assertIn("yt-dlp", support["reason"])

    def test_a_feed_no_longer_than_one_fetch_has_nothing_older_to_archive(self):
        support = self.support(self.feed_kind(), _SupportSources(max_posts_per_fetch=50, available=20))
        self.assertFalse(support["archivable"])
        self.assertFalse(support["unavailable"])
        self.assertEqual(support["reason"],
                         "This feed only lists its latest 20 posts, and every fetch already reads up to 50.")

    def test_a_feed_longer_than_one_fetch_can_archive_its_window(self):
        support = self.support(self.feed_kind(), _SupportSources(max_posts_per_fetch=50, available=503))
        self.assertTrue(support["archivable"])
        self.assertIsNone(support["reason"])

    def test_the_limit_is_what_a_fetch_reads_not_a_made_up_50(self):
        # Issue 0027: an RSS feed fetches 20 (its merged default); a feed listing 30 has 10 older
        # posts to archive, so it must not be refused as "every fetch already reads up to 50".
        support = self.support(self.feed_kind(), _SupportSources(max_posts_per_fetch=20, available=30))
        self.assertTrue(support["archivable"])
        self.assertEqual(support["live_fetch_limit"], 20)
        refused = self.support(self.feed_kind(), _SupportSources(max_posts_per_fetch=20, available=20))
        self.assertEqual(refused["reason"],
                         "This feed only lists its latest 20 posts, and every fetch already reads up to 20.")

    def test_the_limit_is_floored_by_the_kinds_minimum_like_a_fetch(self):
        kind = self.history_kind(PolitenessProfile(concurrency_pool="host-lock", min_posts_per_fetch=15))
        support = self.support(kind, _SupportSources(max_posts_per_fetch=5))
        self.assertEqual(support["live_fetch_limit"], 15)

    def test_an_unmeasured_feed_can_be_planned(self):
        support = self.support(self.feed_kind(), _SupportSources(max_posts_per_fetch=50))
        self.assertTrue(support["archivable"])


class PlanAvailableBasisTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_plan_says_what_its_available_count_means(self):
        kind = FakeKind("fake_capped", inspection=Inspection(250, 100, None))
        kind.available_basis = "listing_cap"
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]))
        service.sources_service = sources = _PlanSources()
        service.posts_service = _Posts()
        service.archive_metadata = ArchiveMetadataWriter(posts=service.posts_service, sources=sources)

        plan = await service.plan_archive("s1")

        self.assertEqual(plan["available_posts"], 250)
        self.assertEqual(plan["available_basis"], "listing_cap")


class ArchiveSourceLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_page_is_saved_and_checkpointed(self):
        pages = [ArchivePage([{"url": "u1"}, {"url": "u2"}], {"mode": "fake", "pages_fetched": 1, "collected_posts": 2}),
                 ArchivePage([{"url": "u3"}], {"mode": "fake", "pages_fetched": 2, "collected_posts": 3})]
        kind = FakeKind("fake_paged", inspection=Inspection(3, 2, None), pages=pages)
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]),
                                     gates=SpyFetchGates())
        service.sources_service = sources = _PlanSources()
        service.posts_service = _Posts()
        service.archive_metadata = ArchiveMetadataWriter(posts=service.posts_service, sources=sources)
        saved_batches = []

        def fake_save(source_id, posts):
            saved_batches.append([p["url"] for p in posts])
            # The first post of each page is new, the rest already known.
            result = SaveBatchResult()
            for index, post in enumerate(posts):
                post_id = f"id-{post['url']}"
                if index == 0:
                    result.inserted_ids.append(post_id)
                else:
                    result.updated_ids.append(post_id)
            return result

        service._save_posts = fake_save
        events = []
        result = await service.archive_source("s1", progress_callback=events.append)

        self.assertEqual(saved_batches, [["u1", "u2"], ["u3"]])
        self.assertEqual(result["posts_inserted"], 2)
        self.assertEqual(result["posts_updated"], 1)
        self.assertEqual(result["posts_fetched"], 3)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["checkpoint"]["collected_posts"], 3)
        self.assertEqual([e["stage"] for e in events], ["planning_complete", "page_fetched", "page_fetched", "completed"])


def _page(n: int) -> ArchivePage:
    return ArchivePage([{"url": f"u{n}"}], {"mode": "fake", "page": n, "pages_fetched": n, "collected_posts": n})


LIMITED = HttpError("HTTP 429 while fetching", status=429, retry_after=4)


class _ScriptedPagesKind(FakeKind):
    """Each archive_pages call plays the next script: pages, then maybe an error."""

    def __init__(self, *scripts):
        super().__init__("fake_paged", inspection=Inspection(10, 1, None))
        self.scripts = list(scripts)
        self.started_from: list = []

    async def archive_pages(self, source, target, checkpoint, rate):
        self.started_from.append(checkpoint)
        for step in self.scripts.pop(0):
            if isinstance(step, BaseException):
                raise step
            yield step


class ArchiveLearnedPaceTests(unittest.IsolatedAsyncioTestCase):
    """Issue 0016: an archive takes the gate slot per page, retries a limit once, then pauses."""

    def service(self, kind, host_floors=None):
        self.clock = SleepClock()
        self.gates = SpyFetchGates(clock=self.clock, sleep=self.clock.sleep, host_floors=host_floors or {})
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]),
                                     gates=self.gates)
        service.sources_service = self.sources = _PlanSources()
        service.posts_service = _Posts()
        service.archive_metadata = ArchiveMetadataWriter(posts=service.posts_service, sources=self.sources)
        service._save_posts = lambda _sid, _posts: SaveBatchResult()
        return service

    async def test_every_page_takes_the_shared_gate_slot(self):
        kind = _ScriptedPagesKind([_page(1), _page(2)])
        await self.service(kind).archive_source("s1")
        self.assertEqual(self.gates.slots, [("host-lock", "tg.i-c-a.su")] * 3, "each page, and the ask that finds the end")

    async def test_pages_wait_the_larger_of_the_host_gap_and_the_kinds_pause_and_the_plan_says_so(self):
        """Never the sum: a 5 s host with a 2 s page delay waits 5 s, a 30 s batch cooldown 30 s."""
        profile = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=2, batch_size=2, batch_cooldown_s=30)
        kind = FakeKind("fake_paced", profile, inspection=Inspection(4, 1, None), pages=[_page(n) for n in range(1, 5)])
        service = self.service(kind, host_floors={"tg.i-c-a.su": 5.0})
        plan = await service.plan_archive("s1")
        await service.archive_source("s1")
        self.assertEqual(self.clock.sleeps, [5, 30, 5, 30], "pages 2-4, then the ask that finds the end")
        self.assertEqual(plan["estimated_seconds"], 4 + 5 + 30 + 5, "one second a page plus the same waits")

    async def test_a_page_failing_once_is_retried_from_the_last_checkpoint(self):
        kind = _ScriptedPagesKind([_page(1), LIMITED], [_page(2)])
        events = []
        result = await self.service(kind).archive_source("s1", progress_callback=events.append)
        self.assertEqual(kind.started_from, [None, _page(1).checkpoint])
        self.assertEqual(self.clock.sleeps, [4, 1, 5], "the Retry-After, then the new 5 s gap from the last ask")
        self.assertEqual((result["posts_fetched"], result.get("paused")), (2, None))
        self.assertEqual([(e["message"], e["level"]) for e in events if e["stage"] == "slowed"],
                         [("tg.i-c-a.su: too many requests, slowing to 5 s", "warning")], "a warning, as in a run")

    async def test_failing_twice_pauses_with_the_checkpoint_and_resume_starts_there(self):
        kind = _ScriptedPagesKind([_page(1), LIMITED], [LIMITED], [_page(2)])
        service = self.service(kind)
        result = await service.archive_source("s1")
        self.assertTrue(result["success"])
        self.assertTrue(result["paused"])
        self.assertEqual(result["paused_reason"], "tg.i-c-a.su is limiting us")
        self.assertEqual(result["message"], "Paused: tg.i-c-a.su is limiting us; resume later")
        saved = self.sources.saved["checkpoint"]
        self.assertEqual(saved["page"], 1)
        self.assertNotIn("completed_at", saved, "a paused archive's checkpoint stays resumable")
        self.assertTrue(self.sources.saved["resume_ready"])

        self.sources.current = self.sources.saved
        await service.archive_source("s1", resume=True)
        self.assertEqual(kind.started_from[-1]["page"], 1)


class ArchiveKindSessionTests(unittest.IsolatedAsyncioTestCase):
    """B8: plan and archive run inside the kind's session, opened once and always closed."""

    def service(self, kind):
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]),
                                     gates=SpyFetchGates())
        service.sources_service = sources = _PlanSources()
        service.posts_service = _Posts()
        service.archive_metadata = ArchiveMetadataWriter(posts=service.posts_service, sources=sources)
        service._save_posts = lambda _sid, _posts: SaveBatchResult()
        return service

    async def test_archive_opens_the_session_once_around_the_plan_and_every_page(self):
        session = RecordingKindSession()
        pages = [ArchivePage([{"url": "u1"}], {"mode": "fake", "pages_fetched": 1, "collected_posts": 1}),
                 ArchivePage([{"url": "u2"}], {"mode": "fake", "pages_fetched": 2, "collected_posts": 2})]
        kind = FakeKind("fake_session", inspection=Inspection(5, 1, None), pages=pages, session=session)
        await self.service(kind).archive_source("s1")
        self.assertEqual(session.events, ["open", "inspect", "page", "page", "close"])

    async def test_plan_closes_the_session(self):
        session = RecordingKindSession()
        kind = FakeKind("fake_session", inspection=Inspection(5, 1, None), session=session)
        await self.service(kind).plan_archive("s1")
        self.assertEqual(session.events, ["open", "inspect", "close"])

    async def test_a_session_that_cannot_open_is_kind_unavailable(self):
        session = RecordingKindSession(open_raises=KindUnavailable("Telegram session not authorised"))
        kind = FakeKind("fake_session", session=session)
        service = self.service(kind)
        with self.assertRaises(KindUnavailable) as ctx:
            await service.archive_source("s1")
        self.assertIn("not authorised", ctx.exception.reason)
        with self.assertRaises(KindUnavailable):
            await service.plan_archive("s1")
        self.assertNotIn("inspect", kind.events)


class _JumpingKind(_ScriptedPagesKind):
    """Continues from a start checkpoint built from what is stored; records what it was given."""

    def __init__(self, *scripts):
        super().__init__(*scripts)
        self._inspection = Inspection(2300, 20, None)
        self.stored_seen: list = []

    async def start_checkpoint(self, source, stored):
        self.stored_seen.append(dict(stored))
        return start_at(mode="fake", page=int(stored["post_count"]) // 20)


@requires_test_db
class ArchivePlanDbTests(unittest.IsolatedAsyncioTestCase):
    """Issue 0015: the plan continues below the stored posts, over the real stores."""

    def setUp(self):
        self.url = db_url()
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            conn.commit()
        first = datetime(2025, 3, 3, 9, 30, tzinfo=timezone.utc)
        DbPostSaver(self.url).save([
            PostDraft(self.source_id, {"url": f"https://scratch.test/p/{i}", "title": f"Post {i}", "content": "c",
                                       "date": first + timedelta(days=i), "external_id": str(1000 + i)})
            for i in range(120)
        ])

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def service(self, kind):
        return SourceFetchService(self.url, kinds=KindRegistry([kind]), gates=SpyFetchGates())

    def save_checkpoint(self, checkpoint):
        SourcesService(self.url).merge_source_settings(self.source_id, {"archive": {"checkpoint": checkpoint}})

    async def test_with_120_stored_the_plan_continues_below_them(self):
        kind = _JumpingKind()
        plan = await self.service(kind).plan_archive(self.source_id)
        self.assertEqual(plan["continues_from"], "2025-03-03T09:30:00+00:00")
        self.assertEqual(plan["older_posts"], 2180)
        self.assertEqual(plan["checkpoint"], start_at(mode="fake", page=6))
        self.assertFalse(plan["resume"])
        self.assertEqual((kind.stored_seen[0]["post_count"], kind.stored_seen[0]["oldest_external_id"]), (120, "1000"))
        archive = SourcesService(self.url).get_source_with_settings(self.source_id)["settings"]["archive"]
        self.assertIsNotNone(archive["last_inspected_at"], "planning measures the source")

    async def test_a_resumable_checkpoint_wins(self):
        self.save_checkpoint({"mode": "fake", "page": 30, "pages_fetched": 4, "collected_posts": 80})
        plan = await self.service(_JumpingKind()).plan_archive(self.source_id)
        self.assertTrue(plan["resume"])
        self.assertEqual(plan["checkpoint"]["page"], 30)
        self.assertIsNone(plan["continues_from"])

    async def test_a_finished_archives_checkpoint_does_not_win(self):
        self.save_checkpoint({"mode": "fake", "page": 30, "completed_at": "2026-10-01T00:00:00+00:00"})
        plan = await self.service(_JumpingKind()).plan_archive(self.source_id)
        self.assertFalse(plan["resume"])
        self.assertFalse(plan["resume_available"])
        self.assertEqual(plan["checkpoint"]["page"], 6)

    async def test_an_archive_measures_once_and_starts_at_the_plans_checkpoint(self):
        kind = _JumpingKind([_page(7)])
        result = await self.service(kind).archive_source(self.source_id)
        self.assertEqual(kind.events.count("inspect"), 1)
        self.assertEqual(kind.started_from, [start_at(mode="fake", page=6)])
        self.assertEqual(result["posts_fetched"], 1)


if __name__ == "__main__":
    unittest.main()
