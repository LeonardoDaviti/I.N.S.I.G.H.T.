import unittest
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))


from insight_core.db.repo_posts import SaveBatchResult
from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter
from insight_core.ingestion.enrichment import Enricher
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import ArchivePage, Inspection, KindUnavailable
from insight_core.ingestion.kinds.youtube import YOUTUBE_PROFILE
from insight_core.ingestion.schedule import Availability
from insight_core.ingestion.kinds.telegram_rss import TelegramRssKind
from insight_core.services.source_fetch_service import SourceFetchService
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
        self.assertEqual(saved["remaining_posts"], 380)
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
        self.current = {"remaining_posts": 42, "estimated_seconds": 99, "status": "partial"}
        saved = self._record(10, {})
        self.assertEqual(saved["remaining_posts"], 42)
        self.assertEqual(saved["estimated_seconds"], 99)
        self.assertEqual(saved["status"], "partial")

    def test_unknown_available_gives_none_backlog(self):
        """E1: a plan's remaining_posts is a requested target, never the backlog."""
        saved = self._record(10, {"remaining_posts": 100, "desired_posts": 110, "page_size": 20}, mode="plan")
        self.assertIsNone(saved["backlog_posts"])
        self.assertEqual(saved["remaining_posts"], 100, "remaining_posts stays the plan field")

    def test_an_explicit_plan_wins_over_the_derived_backlog(self):
        """A plan encodes a desired_posts the operator chose, often far below the whole archive."""
        saved = self._record(0, {"available_posts": 5000, "page_size": 20, "desired_posts": 100,
                                 "remaining_posts": 100, "estimated_pages": 5,
                                 "estimated_seconds": 5},
                             mode="plan")
        self.assertEqual(saved["remaining_posts"], 100)
        self.assertEqual(saved["backlog_posts"], 5000,
                         "the full backlog is still reported alongside the plan's target")


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


class _RecordingProcessor:
    def __init__(self):
        self.ids = []

    def process_posts(self, posts):
        self.ids.extend(post["id"] for post in posts)


class ArchiveSourceLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_page_is_saved_and_checkpointed(self):
        pages = [ArchivePage([{"url": "u1"}, {"url": "u2"}], {"mode": "fake", "pages_fetched": 1, "collected_posts": 2}),
                 ArchivePage([{"url": "u3"}], {"mode": "fake", "pages_fetched": 2, "collected_posts": 3})]
        kind = FakeKind("fake_paged", inspection=Inspection(3, 2, None), pages=pages)
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]))
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
                    result.inserted_posts.append({**post, "id": post_id, "source_id": source_id})
                else:
                    result.updated_ids.append(post_id)
            return result

        service._save_posts = fake_save
        entity, event = _RecordingProcessor(), _RecordingProcessor()
        service.enricher = Enricher(entity, event)
        events = []
        result = await service.archive_source("s1", progress_callback=events.append)

        self.assertEqual(saved_batches, [["u1", "u2"], ["u3"]])
        # Each page is a save batch followed by enrichment of the posts it inserted.
        self.assertEqual(entity.ids, ["id-u1", "id-u3"])
        self.assertEqual(event.ids, ["id-u1", "id-u3"])
        self.assertEqual(result["posts_inserted"], 2)
        self.assertEqual(result["posts_updated"], 1)
        self.assertEqual(result["posts_fetched"], 3)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["checkpoint"]["collected_posts"], 3)
        self.assertEqual([e["stage"] for e in events], ["planning_complete", "page_fetched", "page_fetched", "completed"])


class ArchiveKindSessionTests(unittest.IsolatedAsyncioTestCase):
    """B8: plan and archive run inside the kind's session, opened once and always closed."""

    def service(self, kind):
        service = SourceFetchService("postgresql://test:test@localhost/test", kinds=KindRegistry([kind]))
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


if __name__ == "__main__":
    unittest.main()
