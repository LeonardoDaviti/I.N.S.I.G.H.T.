import asyncio
import unittest
import sys
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from datetime import datetime, timedelta, timezone

from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import ArchivePage, Inspection
from insight_core.ingestion.kinds.telegram_rss import TelegramRssKind
from insight_core.services import source_fetch_service as sfs
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.tests._kind_fakes import FakeKind


class SourceFetchServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = SourceFetchService("postgresql://test:test@localhost/test")

    def test_classify_source_delegates_to_the_kind_registry(self):
        """The resolution table itself lives in test_source_kinds (moved there in B3)."""
        self.assertEqual(
            self.service.classify_source({"platform": "rss", "handle_or_url": "https://nitter.local/karpathy/rss"}),
            "nitter_rss",
        )
        self.assertIs(
            self.service.resolve_kind({"platform": "reddit", "handle_or_url": "r/x"}),
            self.service.kinds.by_name("reddit_subreddit"),
        )

    def test_persist_posts_enriches_with_persisted_ids(self):
        class _FakeCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _FakeConnection:
            def cursor(self):
                return _FakeCursor()

            def commit(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        posts = [
            {"title": "Post One", "url": "https://example.com/1"},
            {"title": "Post Two", "url": "https://example.com/2"},
        ]

        self.service.posts_repo = mock.Mock()
        self.service.posts_repo.upsert_post.side_effect = [
            ("post-1", True),
            ("post-2", False),
        ]
        self.service.memory_service = mock.Mock()
        self.service.memory_service.process_posts.return_value = {
            "posts_processed": 2,
            "mentions_created": 3,
            "entities_linked": 4,
        }
        self.service.event_service = mock.Mock()

        with mock.patch("insight_core.services.source_fetch_service.psycopg.connect", return_value=_FakeConnection()):
            result = self.service._persist_posts("source-1", posts)

        self.service.memory_service.process_posts.assert_called_once()
        self.service.event_service.process_posts.assert_called_once()
        enriched_posts = self.service.memory_service.process_posts.call_args.args[0]
        self.assertEqual([post["id"] for post in enriched_posts], ["post-1", "post-2"])
        self.assertTrue(all(post["_source_id"] == "source-1" for post in enriched_posts))
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["memory_processed"], 2)


class ArchiveInspectionCadenceTests(unittest.TestCase):
    """The archive refresh is a SECOND full fetch of every source in the same cycle.

    _inspect_generic_rss_source re-downloads and re-parses the feed the fetch phase just
    read; inspect_channel runs an unbounded yt-dlp dump of the whole channel. It produces
    available_posts (drifts by a few items a day) and first_post_date (the oldest post's
    date, which never changes), so it belongs on its own cadence.
    """

    def setUp(self):
        self.service = SourceFetchService("postgresql://test:test@localhost/test")

    @staticmethod
    def _source(last_inspected_at=None, **archive):
        if last_inspected_at is not None:
            archive["last_inspected_at"] = last_inspected_at
        return {"id": "s1", "platform": "rss", "handle_or_url": "https://a.example.com/rss",
                "settings": {"archive": archive}}

    def _hours_ago(self, hours):
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def test_never_inspected_source_is_due(self):
        self.assertTrue(self.service._archive_inspection_due(self._source()))

    def test_recently_inspected_source_is_not_due(self):
        source = self._source(last_inspected_at=self._hours_ago(24))
        self.assertFalse(self.service._archive_inspection_due(source),
                         "a source measured yesterday must not be re-downloaded today")

    def test_source_past_the_interval_is_due(self):
        source = self._source(last_inspected_at=self._hours_ago(sfs.ARCHIVE_INSPECT_INTERVAL_HOURS + 1))
        self.assertTrue(self.service._archive_inspection_due(source))

    def test_unreadable_timestamp_measures_rather_than_skipping_forever(self):
        self.assertTrue(self.service._archive_inspection_due(self._source(last_inspected_at="whenever")))

    def test_naive_timestamp_does_not_raise(self):
        naive = datetime.now() - timedelta(hours=1)
        self.assertFalse(self.service._archive_inspection_due(self._source(last_inspected_at=naive.isoformat())))

    def test_last_live_fetch_at_does_not_gate_the_measurement(self):
        """It updates every cycle by definition, so it would report 'just inspected' forever."""
        source = self._source(last_live_fetch_at=self._hours_ago(0.1))
        self.assertTrue(self.service._archive_inspection_due(source))

    def test_zero_interval_restores_every_cycle_behaviour(self):
        with mock.patch.object(sfs, "ARCHIVE_INSPECT_INTERVAL_HOURS", 0):
            source = self._source(last_inspected_at=self._hours_ago(0.01))
            self.assertTrue(self.service._archive_inspection_due(source))


class RecordLiveFetchTests(unittest.TestCase):
    def setUp(self):
        self.service = SourceFetchService("postgresql://test:test@localhost/test")
        self.recorded = []

        async def fake_record(source_id, data, mode, *, kind=None):
            self.recorded.append((source_id, data, mode))

        self.service._record_archive_metadata = fake_record

    def _source(self, last_inspected_at=None):
        archive = {"last_inspected_at": last_inspected_at} if last_inspected_at else {}
        return {"id": "s1", "platform": "rss", "handle_or_url": "https://a.example.com/rss",
                "settings": {"archive": archive}}

    def test_skips_the_network_when_not_due(self):
        called = []

        async def boom(_source):
            called.append(1)
            raise AssertionError("inspect_source must not run inside the interval")

        self.service.inspect_source = boom
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        asyncio.run(self.service.record_live_fetch("s1", self._source(recent), 7))

        self.assertEqual(called, [])
        source_id, data, mode = self.recorded[0]
        self.assertEqual(mode, "live")
        self.assertEqual(data["posts_fetched"], 7, "the cheap half must still be recorded")
        self.assertNotIn("inspected", data)
        self.assertNotIn("available_posts", data,
                         "absent means _record_archive_metadata keeps the stored value")

    def test_inspects_and_flags_when_due(self):
        async def inspect(_source):
            return {"available_posts": 42, "first_post_date": "2020-01-01"}

        self.service.inspect_source = inspect
        asyncio.run(self.service.record_live_fetch("s1", self._source(), 3))

        _, data, _ = self.recorded[0]
        self.assertEqual(data["available_posts"], 42)
        self.assertTrue(data["inspected"], "only a real measurement may stamp last_inspected_at")

    def test_a_failed_inspection_still_records_the_cheap_half(self):
        """Returning early meant a source whose inspection failed also stopped
        reporting its stored post count, freezing the Archive panel on exactly the
        sources most worth watching."""
        async def boom(_source):
            raise RuntimeError("feed gone")

        self.service.inspect_source = boom
        asyncio.run(self.service.record_live_fetch("s1", self._source(), 5))

        self.assertEqual(len(self.recorded), 1)
        _, data, _ = self.recorded[0]
        self.assertEqual(data["posts_fetched"], 5)
        self.assertNotIn("inspected", data,
                         "a failed inspection must not stamp last_inspected_at, or the "
                         "source would wait a full interval before retrying")


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

        def fake_persist(source_id, posts):
            saved_batches.append([p["url"] for p in posts])
            return {"inserted": len(posts), "updated": 0}

        service._persist_posts = fake_persist
        events = []
        result = await service.archive_source("s1", progress_callback=events.append)

        self.assertEqual(saved_batches, [["u1", "u2"], ["u3"]])
        self.assertEqual(result["posts_fetched"], 3)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["checkpoint"]["collected_posts"], 3)
        self.assertEqual([e["stage"] for e in events], ["planning_complete", "page_fetched", "page_fetched", "completed"])


if __name__ == "__main__":
    unittest.main()
