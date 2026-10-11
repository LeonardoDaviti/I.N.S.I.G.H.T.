"""The ingestion module (spec §A, §5.4, §5.7): every test goes through a public seam.

All fakes, no DB, no network: the runner is assembled with the §A.1 keyword constructor
from in-memory ports (tests/_ingestion_fakes.py), FakeKinds and real FetchGates with no
delays.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.ingestion.inspection import DbInspectionRefresher, inspection_due
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import Inspection
from insight_core.ingestion.kinds.youtube import YOUTUBE_PROFILE
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.schedule import Availability, backoff_delay
from insight_core.ingestion.types import (
    FetchRequest,
    OutcomeStatus,
    RunReport,
    SourceFailure,
    SourceSelector,
    Trigger,
)
from insight_core.services.operations_service import OperationsService
from insight_core.tests._ingestion_fakes import (
    FakeRunLock,
    FixedClock,
    InMemoryFetchStateStore,
    InMemoryPostSaver,
    InMemorySourceCatalog,
    RecordingInspectionRefresher,
    RecordingProgressSink,
    SpyFetchGates,
)
from insight_core.tests._kind_fakes import FakeKind, unavailable

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
ALL_ON = Availability(ytdlp_enabled=True, telegram_credentials=False)
YTDLP_OFF = Availability(ytdlp_enabled=False, telegram_credentials=False)


# --------------------------------------------------------------------------- runner


def _source(handle: str, platform: str = "rss", *, enabled: bool = True, post_count: int = 10,
            priority: int = 999) -> dict:
    return {
        "id": f"id-{handle}", "platform": platform, "handle_or_url": handle, "enabled": enabled,
        "post_count": post_count,
        "settings": {"display_name": handle, "priority": priority, "fetch_delay_seconds": 0,
                     "max_posts_per_fetch": 20},
    }


def _posts_for(count: int):
    def behaviour(source, limit):
        return [{"url": f"{source['handle_or_url']}/p{i}", "title": f"t{i}", "content": "c"}
                for i in range(count)]
    return behaviour


def _ok_row(source: dict, hours_ago: float) -> FetchStateRow:
    return FetchStateRow(source_id=source["id"], last_success_at=NOW - timedelta(hours=hours_ago),
                         last_outcome="healthy")


class _Harness:
    """One runner over in-memory ports; every port is reachable for assertions."""

    def __init__(self, sources, kinds, *, rows=None, folders=None, availability=ALL_ON,
                 saver=None, lock_held=False):
        self.catalog = InMemorySourceCatalog(sources, folders)
        self.state = InMemoryFetchStateStore(rows)
        self.saver = saver or InMemoryPostSaver()
        self.inspections = RecordingInspectionRefresher()
        self.registry = KindRegistry(kinds)
        self.gates = SpyFetchGates()
        self.lock = FakeRunLock(held=lock_held)
        self.clock = FixedClock(NOW)
        self.progress = RecordingProgressSink()
        self.runner = IngestionRunner(
            catalog=self.catalog, state=self.state, saver=self.saver,
            inspections=self.inspections,
            registry=self.registry, gates=self.gates, run_lock=self.lock,
            availability=lambda: availability, clock=self.clock, rand=lambda: 1.0,
        )

    async def run(self, selector=None, trigger=Trigger.SCHEDULER, **kwargs) -> RunReport:
        request = FetchRequest(selector or SourceSelector.all(), trigger, **kwargs)
        return await self.runner.run(request, progress=self.progress)


def _rss_kind(behaviour=None, name="fake_rss"):
    return FakeKind(name, behaviour=behaviour or _posts_for(2),
                    matches=lambda s: s["platform"] == "rss")


def _yt_kind(behaviour=None):
    return FakeKind("fake_youtube", YOUTUBE_PROFILE, behaviour or _posts_for(1),
                    matches=lambda s: s["platform"] == "youtube")


class IngestionRunnerSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_excludes_disabled_sources(self):
        on, off = _source("https://on.test/rss"), _source("https://off.test/rss", enabled=False)
        kind = _rss_kind()
        h = _Harness([on, off], [kind])
        report = await h.run(force=True)
        self.assertEqual(report.sources_considered, 1)
        self.assertEqual([c[0] for c in kind.fetch_calls], ["https://on.test/rss"])

    async def test_source_selector_includes_a_disabled_source(self):
        off = _source("https://off.test/rss", enabled=False)
        kind = _rss_kind()
        h = _Harness([off], [kind])
        report = await h.run(SourceSelector.source(off["id"]), Trigger.MANUAL, force=True)
        self.assertEqual(report.sources_fetched, 1)
        self.assertEqual(report.status, "success")

    async def test_unknown_source_fails_the_run(self):
        h = _Harness([], [_rss_kind()])
        report = await h.run(SourceSelector.source("missing"), Trigger.MANUAL, force=True)
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.failures[0].source_id, "missing")


class IngestionRunnerDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_run_fetches_due_and_skips_not_due(self):
        due, fresh = _source("https://due.test/rss"), _source("https://fresh.test/rss")
        kind = _rss_kind()
        h = _Harness([due, fresh], [kind], rows={due["id"]: _ok_row(due, 25), fresh["id"]: _ok_row(fresh, 2)})
        report = await h.run()
        self.assertEqual([c[0] for c in kind.fetch_calls], ["https://due.test/rss"])
        self.assertEqual(report.decisions, {"fetch_due": 1, "skip_not_due": 1})
        self.assertEqual(sorted(sid for sid, _ in h.state.decisions), sorted([due["id"], fresh["id"]]))
        self.assertEqual(h.state.rows[fresh["id"]].last_decision_kind, "skip_not_due")

    async def test_ytdlp_off_never_calls_youtube_and_is_not_backoff(self):
        channels = [_source(f"https://youtube.com/@c{i}", "youtube") for i in range(3)]
        yt = _yt_kind()
        h = _Harness(channels, [yt], availability=YTDLP_OFF)
        report = await h.run()
        self.assertEqual(yt.fetch_calls, [])
        self.assertEqual(report.decisions["skip_unavailable"], 3)
        self.assertEqual(report.decisions.get("skip_backoff", 0), 0)

    async def test_forced_folder_fetch_still_skips_unavailable_youtube(self):
        """Regression for the P5 bypass: track fetch went straight past the yt-dlp switch."""
        yt_src, rss_src = _source("https://youtube.com/@c", "youtube"), _source("https://a.test/rss")
        yt, rss = _yt_kind(), _rss_kind()
        h = _Harness([yt_src, rss_src], [yt, rss], folders={"f1": [yt_src["id"], rss_src["id"]]},
                     availability=YTDLP_OFF)
        report = await h.run(SourceSelector.folder("f1"), Trigger.MANUAL, force=True)
        self.assertEqual(yt.fetch_calls, [])
        self.assertEqual(len(rss.fetch_calls), 1)
        self.assertEqual(report.decisions, {"skip_unavailable": 1, "fetch_forced": 1})

    async def test_nothing_due_does_not_save(self):
        fresh = _source("https://fresh.test/rss")
        h = _Harness([fresh], [_rss_kind()], rows={fresh["id"]: _ok_row(fresh, 1)})
        report = await h.run()
        self.assertEqual(report.status, "nothing_due")
        self.assertEqual(h.saver.calls, [])


class IngestionRunnerOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_raising_kind_records_an_error_with_deterministic_backoff(self):
        def boom(source, limit):
            if "bad" in source["handle_or_url"]:
                raise RuntimeError("HTTP 500")
            return _posts_for(1)(source, limit)

        bad, good = _source("https://bad.test/rss"), _source("https://good.test/rss")
        h = _Harness([bad, good], [_rss_kind(boom)])
        report = await h.run(force=True)

        row = h.state.rows[bad["id"]]
        self.assertEqual(row.consecutive_failures, 1)
        self.assertEqual(row.next_retry_at, NOW + backoff_delay(1, rand=lambda: 1.0))
        self.assertEqual(h.state.rows[good["id"]].last_outcome, "healthy")
        self.assertEqual(report.status, "partial")
        self.assertEqual(report.sources_failed, 1)
        self.assertEqual(report.failures, [SourceFailure(bad["id"], "https://bad.test/rss", "fetch", "HTTP 500")])

    async def test_an_empty_fetch_is_a_success_and_resets_staleness(self):
        src = _source("https://quiet.test/rss", post_count=0)
        h = _Harness([src], [_rss_kind(_posts_for(0))])
        first = await h.run()
        self.assertEqual(first.decisions, {"fetch_new_source": 1})
        self.assertEqual(h.state.outcomes[0].status, OutcomeStatus.EMPTY)
        self.assertEqual(h.state.rows[src["id"]].last_success_at, NOW)

        h.clock.advance(timedelta(hours=2))
        second = await h.run()
        self.assertEqual(second.decisions, {"skip_not_due": 1})

    async def test_kind_unavailable_at_fetch_time_writes_no_backoff(self):
        src = _source("https://locked.test/rss")
        h = _Harness([src], [_rss_kind(unavailable("no session"))])
        report = await h.run(force=True)
        row = h.state.rows[src["id"]]
        self.assertEqual(row.last_outcome, "unavailable")
        self.assertEqual(row.consecutive_failures, 0)
        self.assertIsNone(row.next_retry_at)
        self.assertEqual(report.sources_failed, 0)

    async def test_save_failures_are_reported_and_the_fetch_stays_healthy(self):
        src = _source("https://many.test/rss")
        failing = {f"https://many.test/rss/p{i}" for i in range(25)}
        h = _Harness([src], [_rss_kind(_posts_for(30))], saver=InMemoryPostSaver(failing))
        report = await h.run(force=True)
        self.assertEqual(report.posts_failed, 25)
        self.assertEqual(report.posts_inserted, 5)
        self.assertLessEqual(len(report.to_payload()["post_failures"]), 20)
        self.assertEqual(h.state.rows[src["id"]].last_outcome, "healthy")
        self.assertEqual(report.status, "partial")

    async def test_a_source_whose_posts_all_failed_to_save_is_a_save_failure(self):
        src = _source("https://doomed.test/rss")
        failing = {f"https://doomed.test/rss/p{i}" for i in range(2)}
        h = _Harness([src], [_rss_kind()], saver=InMemoryPostSaver(failing))
        report = await h.run(force=True)
        self.assertEqual([f.stage for f in report.failures], ["save"])
        # Nothing reached the database, so the source is failing, not healthy: its failure
        # count grows and it is retried on backoff instead of waiting out its cadence.
        row = h.state.rows[src["id"]]
        self.assertEqual(row.last_outcome, "error")
        self.assertEqual(row.consecutive_failures, 1)
        self.assertIn("failed to save", row.last_error)
        self.assertIsNone(row.last_success_at)

    async def test_a_failed_save_batch_marks_every_fetched_source_failing(self):
        class BrokenSaver(InMemoryPostSaver):
            def save(self, drafts):
                raise RuntimeError("db down")

        a, b = _source("https://a.test/rss"), _source("https://b.test/rss")
        h = _Harness([a, b], [_rss_kind()], saver=BrokenSaver())
        report = await h.run(force=True)
        self.assertEqual(report.status, "failed")
        for src in (a, b):
            row = h.state.rows[src["id"]]
            self.assertEqual(row.last_outcome, "error")
            self.assertEqual(row.consecutive_failures, 1)

    async def test_inserted_and_updated_posts_are_counted_apart(self):
        src = _source("https://mixed.test/rss")
        saver = InMemoryPostSaver()
        saver.known["https://mixed.test/rss/p0"] = "already-there"
        h = _Harness([src], [_rss_kind(_posts_for(3))], saver=saver)
        report = await h.run(force=True)
        self.assertEqual(report.posts_inserted, 2)
        self.assertEqual(report.posts_updated, 1)
        self.assertEqual(report.inserted_by_source[0].inserted, 2)

    async def test_inspections_refresh_only_sources_that_fetched_posts(self):
        full, empty = _source("https://full.test/rss"), _source("https://empty.test/rss")
        h = _Harness([full, empty], [_rss_kind(lambda s, n: _posts_for(3 if "full" in s["handle_or_url"] else 0)(s, n))])
        await h.run(force=True)
        self.assertEqual(h.inspections.calls, [(full["id"], "fake_rss", 3)])

    async def test_progress_phases_arrive_in_order(self):
        h = _Harness([_source("https://a.test/rss")], [_rss_kind()])
        await h.run(force=True)
        self.assertEqual(h.progress.phases, ["decided", "fetched", "saved", "inspected"])

    async def test_fetches_run_under_the_gates(self):
        h = _Harness([_source("https://a.test/rss"), _source("https://youtube.com/@c", "youtube")],
                     [_rss_kind(), _yt_kind()])
        await h.run(force=True)
        self.assertEqual(sorted(h.gates.slots), [("host-lock", "a.test"), ("ytdlp", "youtube.com")])


class IngestionRunnerLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_held_run_lock_skips_the_run(self):
        kind = _rss_kind()
        h = _Harness([_source("https://a.test/rss")], [kind], lock_held=True)
        report = await h.run(force=True)
        self.assertEqual(report.status, "skipped_busy")
        self.assertEqual(kind.fetch_calls, [])

    async def test_a_folder_run_does_not_take_the_lock(self):
        src = _source("https://a.test/rss")
        h = _Harness([src], [_rss_kind()], folders={"f": [src["id"]]}, lock_held=True)
        report = await h.run(SourceSelector.folder("f"), Trigger.MANUAL, force=True)
        self.assertEqual(h.lock.entered, 0)
        self.assertEqual(report.status, "success")


class RunReportTests(unittest.IsolatedAsyncioTestCase):
    def _report(self, **fields) -> RunReport:
        base = dict(run_id=None, trigger=Trigger.SCHEDULER, selector=SourceSelector.all(), force=False,
                    status="partial", started_at=NOW, finished_at=NOW + timedelta(seconds=5))
        base.update(fields)
        return RunReport(**base)

    def test_summary_line_format_is_pinned(self):
        report = self._report(sources_considered=75, sources_fetched=12, sources_failed=1,
                              decisions={"fetch_due": 12, "skip_not_due": 63}, posts_inserted=48)
        self.assertEqual(report.summary_line(), "12 due, 63 deferred, 1 failed; 48 new posts")

    async def test_payload_is_compact_and_serialisable(self):
        def boom(source, limit):
            raise RuntimeError("x" * 5000)

        sources = [_source(f"https://h{i}.test/rss") for i in range(30)]
        h = _Harness(sources, [_rss_kind(boom)])
        payload = (await h.run(force=True)).to_payload()
        json.dumps(payload)
        self.assertEqual(payload["sources_failed"], 30)
        for key in ("failures", "post_failures", "inserted_by_source"):
            self.assertLessEqual(len(payload[key]), 20)
        ops = OperationsService("postgresql://unused@localhost/none")
        self.assertEqual(ops._compact_payload(payload), payload)


class _FakeWriter:
    def __init__(self):
        self.records = []

    def record(self, source_id, kind, data, mode):
        self.records.append((source_id, kind.name, dict(data), mode))


class DbInspectionRefresherTests(unittest.IsolatedAsyncioTestCase):
    def _source(self, last_inspected_at=None):
        source = _source("https://a.test/rss")
        source["settings"]["archive"] = {"last_inspected_at": last_inspected_at}
        return source

    def _refresher(self):
        self.writer, self.gates = _FakeWriter(), SpyFetchGates()
        return DbInspectionRefresher(writer=self.writer, gates=self.gates, clock=FixedClock(NOW),
                                     interval_hours=168, enabled=True)

    def _kind(self):
        gates_seen = []

        class _InspectingKind(FakeKind):
            async def inspect(kind_self, source):
                gates_seen.append(self.gates.inside)
                return Inspection(120, 20, "2020-01-01")

        kind = _InspectingKind("fake_rss")
        return kind, gates_seen

    async def test_recently_inspected_source_records_only_the_cheap_half(self):
        refresher = self._refresher()
        kind, gates_seen = self._kind()
        await refresher.refresh(self._source((NOW - timedelta(hours=2)).isoformat()), kind, 4)
        self.assertEqual(gates_seen, [])
        (_, _, data, mode), = self.writer.records
        self.assertEqual(mode, "live")
        self.assertEqual(data, {"source_type": "fake_rss", "posts_fetched": 4})

    async def test_never_inspected_source_is_inspected_inside_the_gates(self):
        refresher = self._refresher()
        kind, gates_seen = self._kind()
        await refresher.refresh(self._source(), kind, 4)
        self.assertEqual(gates_seen, [1])
        self.assertEqual(self.gates.slots, [("host-lock", "a.test")])
        (_, _, data, _), = self.writer.records
        self.assertTrue(data["inspected"])
        self.assertEqual(data["available_posts"], 120)

    async def test_a_failing_inspection_still_records_and_never_raises(self):
        refresher = self._refresher()

        class _Broken(FakeKind):
            async def inspect(self, source):
                raise RuntimeError("timeout")

        await refresher.refresh(self._source(), _Broken("fake_rss"), 2)
        (_, _, data, _), = self.writer.records
        self.assertNotIn("inspected", data)

    async def test_unreadable_timestamp_measures_rather_than_skipping_forever(self):
        refresher = self._refresher()
        kind, gates_seen = self._kind()
        await refresher.refresh(self._source("not-a-date"), kind, 1)
        self.assertEqual(gates_seen, [1])


class InspectionDueTests(unittest.TestCase):
    """The inspection is a SECOND full fetch of a source (a feed re-download, an unbounded
    yt-dlp channel dump). It produces available_posts and first_post_date, which barely
    move, so it runs on one global interval."""

    @staticmethod
    def _source(**archive):
        return {"settings": {"archive": archive}}

    def due(self, source, interval=168):
        return inspection_due(source, NOW, interval)

    def test_never_inspected_is_due(self):
        self.assertTrue(self.due(self._source()))

    def test_inside_and_past_the_interval(self):
        self.assertFalse(self.due(self._source(last_inspected_at=(NOW - timedelta(hours=24)).isoformat())))
        self.assertTrue(self.due(self._source(last_inspected_at=(NOW - timedelta(hours=169)).isoformat())))

    def test_naive_timestamp_is_read_as_utc(self):
        naive = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        self.assertFalse(self.due(self._source(last_inspected_at=naive)))

    def test_last_live_fetch_at_does_not_gate_it(self):
        self.assertTrue(self.due(self._source(last_live_fetch_at=NOW.isoformat())))

    def test_zero_interval_inspects_every_run(self):
        self.assertTrue(self.due(self._source(last_inspected_at=NOW.isoformat()), interval=0))


if __name__ == "__main__":
    unittest.main()
