"""v10.47 (issue 0280 B1, B4): a source just added is read at once by the jobs process (SourceSelector.new, the
scheduler's read_new_sources), and a saved search's first read keeps its whole answer, past the per-fetch cap, as
its backlog."""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import BACKLOG_KEY
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.generic_rss import GenericRssKind
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.schedule import Availability, DecisionKind, FetchDecision
from insight_core.ingestion.types import FetchRequest, RunReport, SourceSelector, Trigger
from insight_core.scripts import run_scheduler
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._ingestion_fakes import (
    FakeRunLock,
    FixedClock,
    InMemoryFetchStateStore,
    InMemoryPostSaver,
    RecordingInspectionRefresher,
    SpyFetchGates,
)
from insight_core.tests._kind_fakes import FakeHttp, FakeKind

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
SEARCH = "https://export.arxiv.org/api/query?search_query=au:%22Some+One%22&sortBy=submittedDate&max_results=300"
BLOG = "https://blog.example/feed"


def run(coro):
    return asyncio.run(coro)


def _atom(title: str, n: int) -> str:
    entries = "".join(
        f"<entry><id>https://papers.example/abs/{i}</id><title>Paper {i}</title>"
        f'<link href="https://papers.example/abs/{i}"/><published>2026-{12 - i // 30:02d}-{1 + i % 28:02d}T00:00:00Z'
        f"</published><summary>Abstract {i}</summary></entry>" for i in range(n))
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>{title}</title>{entries}</feed>'


def _source(url: str, post_count) -> dict:
    return {"id": "s1", "platform": "rss", "handle_or_url": url, "post_count": post_count,
            "settings": {"display_name": "S", "fetch_full_content": False}}


class SavedSearchFirstRead(unittest.TestCase):
    """B1: LeCun's arXiv query listed 242 papers in one read and stored 20 until archived by hand."""

    def _fetch(self, url: str, title: str, post_count, items: int = 60):
        kind = GenericRssKind(FakeHttp({url: _atom(title, items)}))
        return run(kind.fetch_latest(_source(url, post_count), 20))

    def test_a_saved_searchs_first_read_keeps_its_whole_answer_the_older_items_as_backlog(self):
        fetched = self._fetch(SEARCH, 'arXiv Query: search_query=au:"Some One"', 0)
        self.assertEqual(len(fetched), 60)
        self.assertEqual([bool(p.get(BACKLOG_KEY)) for p in fetched], [False] * 20 + [True] * 40)

    def test_later_reads_keep_the_cap(self):
        self.assertEqual(len(self._fetch(SEARCH, 'arXiv Query: search_query=au:"Some One"', 60)), 20)

    def test_a_sites_own_feed_keeps_the_cap_on_its_first_read(self):
        # its follow archive (follow_archive) reads its older posts, paced, in the jobs process
        self.assertEqual(len(self._fetch(BLOG, "Some Blog", 0)), 20)

    def test_a_read_with_no_stored_count_keeps_the_cap(self):
        # a test read (feed_finder.test_read) or an archive's source carries no post_count
        self.assertEqual(len(self._fetch(SEARCH, 'arXiv Query: search_query=au:"Some One"', None)), 20)


class _State(InMemoryFetchStateStore):
    def __init__(self):
        super().__init__()
        self.kept = 0

    def keep_derived(self):
        self.kept += 1


class _NewCatalog:
    def __init__(self, sources):
        self.sources = sources

    def load(self, selector):
        assert selector.kind == "new"
        return list(self.sources)


def _runner(sources, *, held=False):
    state, lock = _State(), FakeRunLock(held=held)
    kind = FakeKind("fake_rss", behaviour=lambda s, n: [{"url": f"{s['handle_or_url']}/p1", "title": "t", "content": "c"}])
    runner = IngestionRunner(catalog=_NewCatalog(sources), state=state, saver=InMemoryPostSaver(),
                             inspections=RecordingInspectionRefresher(), registry=KindRegistry([kind]),
                             gates=SpyFetchGates(), run_lock=lock,
                             availability=lambda: Availability(ytdlp_enabled=True, telegram_credentials=False),
                             clock=FixedClock(NOW), rand=lambda: 1.0)
    return runner, state, lock, kind


class NewSourcesRun(unittest.IsolatedAsyncioTestCase):
    """B4: @ylecun had 0 posts 5 minutes after it was added; its first posts came with the next tick."""

    NEW = {"id": "n1", "platform": "rss", "handle_or_url": "https://new.test/rss", "enabled": True, "post_count": 0,
           "settings": {"display_name": "New", "fetch_delay_seconds": 0, "max_posts_per_fetch": 20}}

    async def test_a_new_source_is_read_as_a_new_source(self):
        runner, state, lock, kind = _runner([self.NEW])
        report = await runner.run(FetchRequest(SourceSelector.new(), Trigger.SCHEDULER))
        self.assertEqual(report.decisions, {DecisionKind.FETCH_NEW_SOURCE.value: 1})
        self.assertEqual(report.posts_inserted, 1)
        self.assertEqual((lock.entered, state.kept), (1, 1))

    async def test_none_waiting_keeps_nothing_derived(self):
        runner, state, _, kind = _runner([])
        report = await runner.run(FetchRequest(SourceSelector.new(), Trigger.SCHEDULER))
        self.assertEqual((report.status, state.kept, kind.fetch_calls), ("nothing_due", 0, []))

    async def test_never_beside_a_full_run(self):
        runner, state, _, kind = _runner([self.NEW], held=True)
        report = await runner.run(FetchRequest(SourceSelector.new(), Trigger.SCHEDULER))
        self.assertEqual((report.status, state.kept, kind.fetch_calls), ("skipped_busy", 0, []))


class _Ops:
    def __init__(self):
        self.started, self.finished, self.discarded = [], [], []

    def start_job(self, job_type, **kwargs):
        self.started.append((job_type, kwargs))
        return f"job-{len(self.started)}"

    def finish_job(self, job_id, **kwargs):
        self.finished.append(job_id)

    def discard_job(self, job_id):
        self.discarded.append(job_id)

    def append_job_event(self, job_id, **kwargs):
        pass


class _Ingest:
    def __init__(self, status):
        self.status, self.requests = status, []

    async def __call__(self, request, *, progress=None):
        self.requests.append(request)
        return RunReport(run_id="r", trigger=request.trigger, selector=request.selector, force=False,
                         status=self.status, started_at=NOW, finished_at=NOW)


class SchedulerReadsNewSources(unittest.IsolatedAsyncioTestCase):
    async def test_a_waiting_source_is_read_in_a_task_of_its_own(self):
        ops, ingest = _Ops(), _Ingest("success")
        with mock.patch.object(run_scheduler, "new_sources_waiting", return_value=True):
            task = run_scheduler.read_new_sources("db", None, ingest=ingest, ops=ops)
            self.assertIs(run_scheduler.read_new_sources("db", task, ingest=ingest, ops=ops), task,
                          "one such read at a time")
            await task
        self.assertEqual([r.selector for r in ingest.requests], [SourceSelector.new()])
        self.assertEqual((ops.started[0][1]["payload"]["selector"], ops.finished), ({"kind": "new"}, ["job-1"]))

    async def test_none_waiting_starts_nothing(self):
        ops, ingest = _Ops(), _Ingest("success")
        with mock.patch.object(run_scheduler, "new_sources_waiting", return_value=False):
            self.assertIsNone(run_scheduler.read_new_sources("db", None, ingest=ingest, ops=ops))
        self.assertEqual((ingest.requests, ops.started), ([], []))

    async def test_a_read_a_full_run_held_off_leaves_no_job(self):
        ops = _Ops()
        await run_scheduler.ingestion_job(FetchRequest(SourceSelector.new(), Trigger.SCHEDULER),
                                          ingest=_Ingest("skipped_busy"), ops=ops, name="of new sources")
        self.assertEqual((ops.discarded, ops.finished), (["job-1"], []))

    async def test_a_skipped_full_tick_still_leaves_its_job(self):
        ops = _Ops()
        await run_scheduler.ingestion_job(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER),
                                          ingest=_Ingest("skipped_busy"), ops=ops, name="tick")
        self.assertEqual((ops.discarded, ops.finished), ([], ["job-1"]))


@requires_test_db
class NeverReadCatalog(unittest.TestCase):
    """SourcesRepository.NEVER_READ_SQL over the real tables."""

    def setUp(self):
        import psycopg

        from insight_core.db.repo_sources import SourcesRepository
        from insight_core.ingestion.ports import DbFetchStateStore, DbSourceCatalog

        self.url = db_url()
        self.psycopg = psycopg
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.new = insert_scratch_source(cur, enabled=True)
            self.off = insert_scratch_source(cur)
            conn.commit()
        self.catalog, self.state, self.repo = DbSourceCatalog(self.url), DbFetchStateStore(self.url), SourcesRepository(self.url)

    def tearDown(self):
        with self.psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _new_ids(self):
        return {s["id"] for s in self.catalog.load(SourceSelector.new())}

    def _decide(self, kind: DecisionKind):
        decision = FetchDecision(kind=kind, fetch=kind.fetches, post_limit=20, interval=timedelta(hours=1),
                                 interval_basis="tier",
                                 next_due_at=None, next_retry_at=None, detail="")
        self.state.record_decisions([(self.new, decision)], now=NOW)

    def test_an_enabled_source_never_read_is_new_until_its_first_read(self):
        from insight_core.ingestion.types import FetchOutcome

        self.assertIn(self.new, self._new_ids())
        self.assertNotIn(self.off, self._new_ids(), "a disabled source waits for nothing")
        with self.psycopg.connect(self.url) as conn, conn.cursor() as cur:
            self.assertTrue(self.repo.has_never_read(cur))
        self._decide(DecisionKind.SKIP_HOST_BUSY)
        self.assertIn(self.new, self._new_ids(), "its host's share of a run was spent: still waiting")
        self.state.record_outcome(FetchOutcome.from_fetch(self.new, fetched=1, error=None, duration_s=0.1),
                                  trigger=Trigger.SCHEDULER, now=NOW)
        self.assertNotIn(self.new, self._new_ids())

    def test_a_source_its_kind_cannot_read_now_is_left_to_the_ticks(self):
        self._decide(DecisionKind.SKIP_UNAVAILABLE)
        self.assertNotIn(self.new, self._new_ids())


if __name__ == "__main__":
    unittest.main()
