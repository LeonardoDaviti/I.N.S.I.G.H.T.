#!/usr/bin/env python3
"""
Long-running scheduler for the ingestion container.

Its loop runs: the ingestion tick (every scheduler_config.ingest_tick_minutes, floor 15: one run_ingestion;
cadence decides which sources are due); daily work (prune job_runs, spend answered Mark X inputs, refresh
cadence; gated on system_settings.scheduler_state.last_daily_work_at); waiting and queued archives, continued
in this process so their pages share the host limiter with the hourly fetches; channel profiles after each
tick; the Operations page's data repair asks (services/data_repairs.py) and the first read of a source just added
(read_new_sources), looked for with the archives. In
threads of their own: the API watchdog (INSIGHT_API_WATCHDOG), Mark X's job runner (candidate finder,
decision runs, kept views; with Mark X off, the reader's kept views only) and the source stats job.

tick() is the testable unit: it takes its collaborators as arguments.
"""
from __future__ import annotations

import asyncio
import gc
import os
import signal
import sys
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import FetchRequest, SourceSelector, Trigger  # noqa: E402
from insight_core.ingestion.ports import JobProgressSink  # noqa: E402
from insight_core.logs.core.logger_config import get_component_logger, setup_logging  # noqa: E402
from insight_core.utils.env import env_int  # noqa: E402

logger = get_component_logger("run_scheduler")

RUNNING = True
TICK_MINUTES_FLOOR = 15
ARCHIVE_POLL_SECONDS = 30


async def profiles_after_tick(db_url: str, run: Optional[Callable[[str], Awaitable[Any]]] = None) -> Optional[Any]:
    """The channel profiles due, a few a tick, after the tick's fetches (services/profiles_service.py). Never
    raises: profiles never stop ingestion."""
    try:
        if run is None:
            from insight_core.services.profiles_service import run_after_tick as run
        return await run(db_url)
    except Exception:  # noqa: BLE001
        logger.exception("Channel profiles failed (the next tick tries again)")
        return None


def _handle_stop(signum, frame):
    global RUNNING
    RUNNING = False


def _parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SchedulerState:
    """Persisted in system_settings['scheduler_state']; served by GET /api/operations/scheduler."""

    last_tick_at: Optional[datetime] = None
    next_tick_at: Optional[datetime] = None
    last_daily_work_at: Optional[datetime] = None
    next_daily_work_at: Optional[datetime] = None

    @staticmethod
    def from_dict(data: Optional[Dict[str, Any]]) -> "SchedulerState":
        data = data or {}
        return SchedulerState(**{f.name: _parse(data.get(f.name)) for f in fields(SchedulerState)})

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {key: value.isoformat() if value else None for key, value in asdict(self).items()}


def _tick_interval(config: Dict[str, Any]) -> timedelta:
    try:
        minutes = float(config.get("ingest_tick_minutes", 60))
    except (TypeError, ValueError):
        minutes = 60.0
    return timedelta(minutes=max(TICK_MINUTES_FLOOR, minutes))


def _daily_interval(config: Dict[str, Any]) -> timedelta:
    try:
        hours = float(config.get("interval_hours", 20))
    except (TypeError, ValueError):
        hours = 20.0
    return timedelta(hours=max(0.25, hours))


async def ingestion_job(request: FetchRequest, *, ingest: Callable[..., Awaitable[Any]], ops: Any,
                        name: str) -> Optional[Any]:
    """One ingestion run as an ingestion_run job, finished in every case (a raise marks it failed); a run with
    nothing due made no request: its job is deleted. The report, or None when the run raised."""
    job_id = None
    try:
        job_id = ops.start_job("ingestion_run", trigger="scheduler",
                               payload={"selector": request.selector.as_dict(), "force": request.force})
    except Exception:  # noqa: BLE001
        logger.exception("Could not start the ingestion_run job (running untracked)")
    status, message, payload, nothing_due, report = "failed", "Ingestion run did not finish", {}, False, None
    try:
        report = await ingest(request, progress=JobProgressSink(ops, job_id))
        status, message, payload = report.job_status, report.summary_line(), report.to_payload()
        # a read of new sources a full run held off is nothing either: the full run reads them
        nothing_due = report.status == "nothing_due" or (request.selector.kind == "new"
                                                          and report.status == "skipped_busy")
        logger.info("Ingestion %s: %s", name, message)
    except Exception as exc:  # noqa: BLE001
        message = f"Ingestion run failed: {exc}"
        logger.exception("Ingestion %s failed", name)
    finally:
        if job_id:
            try:
                if nothing_due:
                    ops.discard_job(job_id)
                else:
                    ops.finish_job(job_id, status=status, message=message, payload=payload, compact=True)
            except Exception:  # noqa: BLE001
                logger.exception("Could not finish the ingestion_run job")
    return report


def new_sources_waiting(db_url: str) -> bool:
    """Whether a source just added waits for its first read (SourcesRepository.has_never_read). Never raises."""
    try:
        from insight_core.db import database
        from insight_core.db.repo_sources import SourcesRepository
        with database.transaction(db_url) as cur:
            return SourcesRepository(db_url).has_never_read(cur)
    except Exception:  # noqa: BLE001 - the next tick reads it
        logger.exception("Could not look for sources never read")
        return False


def read_new_sources(db_url: str, running: Optional[Any], *, ingest: Callable[..., Awaitable[Any]],
                     ops: Any) -> Optional[Any]:
    """A source just added is read at once, not at the next tick: when one waits (new_sources_waiting) and no such
    read is running, one ingestion run of the sources never read (SourceSelector.new) as a task of its own, so a
    long first read never holds the loop. Returns the task (or the one still running)."""
    if running is not None and not running.done():
        return running
    if not new_sources_waiting(db_url):
        return None
    return asyncio.get_running_loop().create_task(ingestion_job(
        FetchRequest(SourceSelector.new(), Trigger.SCHEDULER), ingest=ingest, ops=ops, name="of new sources"))


async def tick(
    now: datetime,
    state: SchedulerState,
    config: Dict[str, Any],
    *,
    ingest: Callable[..., Awaitable[Any]],
    daily_work: Callable[[Dict[str, Any]], Awaitable[Any]],
    ops: Any,
) -> SchedulerState:
    """One scheduler wake-up: an ingestion run, then daily work when it is due."""
    last_daily = state.last_daily_work_at
    if last_daily is None:
        try:
            last_daily = _parse(ops.latest_successful_job_finished_at("scheduler_cycle"))
        except Exception:  # noqa: BLE001
            logger.exception("Could not seed the daily-work gate; daily work runs now")
            last_daily = None

    # 1. The ingestion run; the scheduler state records the tick whatever it did.
    await ingestion_job(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER), ingest=ingest, ops=ops, name="tick")

    # 2. Daily work, gated on interval_hours since it last ran.
    daily_interval = _daily_interval(config)
    if last_daily is None or now - last_daily >= daily_interval:
        cycle_job_id = None
        try:
            cycle_job_id = ops.start_job("scheduler_cycle", trigger="scheduler", message="Daily work started",
                                         payload={"scheduler": config})
        except Exception:  # noqa: BLE001
            logger.exception("Could not start the scheduler_cycle job")
        cycle_status, cycle_message = "failed", "Daily work did not finish"
        cycle_payload: Dict[str, Any] = {"scheduler": config}
        try:
            await daily_work(config)
            cycle_status, cycle_message = "success", "Daily work completed"
        except Exception as exc:  # noqa: BLE001
            cycle_message = str(exc)
            logger.exception("Daily work failed")
        finally:
            if cycle_job_id:
                try:
                    ops.finish_job(cycle_job_id, status=cycle_status, message=cycle_message,
                                   payload=cycle_payload)
                except Exception:  # noqa: BLE001
                    logger.exception("Could not finish the scheduler_cycle job")
        # Advanced even when it failed: a broken step must not retry every tick.
        last_daily = now

    new_state = SchedulerState(
        last_tick_at=now,
        next_tick_at=now + _tick_interval(config),
        last_daily_work_at=last_daily,
        next_daily_work_at=last_daily + daily_interval,
    )
    try:
        ops.set_scheduler_state(new_state.as_dict())
    except Exception:  # noqa: BLE001
        logger.exception("Could not persist the scheduler state")
    return new_state


async def daily_work(db_url: str, operations_service: Any, scheduler_config: Dict[str, Any]) -> None:
    """The upkeep: prune job_runs, spend answered Mark X inputs, refresh source cadence. sources.json is never read
    here: the database is the truth."""
    from insight_core.ingestion.ports import DbFetchStateStore

    try:
        pruned = operations_service.prune_job_runs(env_int("INSIGHT_JOB_RUNS_RETAIN_DAYS", 30))
        if pruned:
            logger.info("Pruned %s job_runs rows older than the retention window", pruned)
    except Exception:  # noqa: BLE001
        logger.exception("job_runs prune failed (continuing with the daily work)")

    # the inputs of answered Mark X questions nothing reads again, spent 14 days after the answer
    from insight_core.markx import api as markx_api
    if markx_api.enabled():
        try:
            from insight_core.markx import tasks as markx_tasks
            spent = await asyncio.to_thread(markx_tasks.spend_all, db_url)
            logger.info("Spent %s answered Mark X task inputs", spent)
        except Exception:  # noqa: BLE001
            logger.exception("Spending Mark X task inputs failed (continuing with the daily work)")

    # Once a day: new sources leave probation and mean gaps follow the posts.
    try:
        refreshed = await asyncio.to_thread(DbFetchStateStore(db_url).refresh_cadence)
        logger.info("Cadence refreshed for %s sources", refreshed)
    except Exception:  # noqa: BLE001
        logger.exception("Cadence refresh failed (continuing with stored tiers)")


async def _heartbeat() -> None:
    """A heartbeat every BEAT_SECONDS (utils/heartbeat.py) with this process's own memory and CPU, read by the
    container's healthcheck and /api/status. A task of its own, so a long tick doesn't read as a dead loop; a
    loop blocked by a stuck call does."""
    from insight_core.utils import heartbeat, peak
    while True:
        heartbeat.beat("scheduler", stats=peak.own())
        await asyncio.sleep(heartbeat.BEAT_SECONDS)


def startup_repairs(db_url: str) -> None:
    """The start's one-off repairs, each in its own thread, in a spawned process."""
    import threading

    setup_logging(debug_mode=False)
    from insight_core.scripts import repair_0135, repair_0137, repair_full_text, rerun_archives_0143
    from insight_core.scripts.repair_normalized_urls import repair_safely
    from insight_core.services import data_repairs
    threads = [threading.Thread(target=job, args=(db_url,)) for job in (
        data_repairs.run_safely,             # the registered repairs, once per version (the Operations page)
        repair_safely,                       # posts stored without a normalized address
        repair_0135.repair_safely,           # Telegram dates, transcripts
        repair_0137.repair_safely,           # collapsed feeds, author lines, bridge dates
        repair_full_text.repair_safely,      # teasers left short, read again
        rerun_archives_0143.rerun_safely)]   # capped feeds planned again
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def repair_asks(db_url: str, running: Optional[Any]) -> Optional[Any]:
    """The Operations page's data repair asks (services/data_repairs.py): when one waits and none is being run,
    `data_repairs.job` in a process of its own; returns the run's future (or the one still running). Never raises."""
    if running is not None and not running.done():
        return running
    try:
        from insight_core.db import database
        from insight_core.services import data_repairs
        with database.transaction(db_url) as cur:
            if not data_repairs.has_requests(cur):
                return None
        from insight_core.services.stories_service import in_own_process
        return asyncio.get_running_loop().run_in_executor(None, in_own_process, data_repairs.job, db_url)
    except Exception:  # noqa: BLE001 - the repairs never stop ingestion
        logger.exception("Could not look for data repair asks")
        return None


async def main() -> None:
    from insight_core.db.ensure_db import ensure_database
    from insight_core.ingestion import run_ingestion
    from insight_core.services.archive_jobs import ArchiveJobs
    from insight_core.services.operations_service import OperationsService
    from insight_core.services.source_fetch_service import archive_service

    setup_logging(debug_mode=False)
    from insight_core.db import database
    database.use_role("jobs")   # the job timeouts, here and in the job processes it spawns
    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url
    operations_service = OperationsService(db_url)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    logger.info("Starting scheduler")
    try:   # the archives it was continuing carry on by themselves
        requeued = operations_service.requeue_interrupted_archives("scheduler", datetime.now(timezone.utc))
        if requeued:
            logger.info("%s archives a restart stopped continue shortly", requeued)
    except Exception:  # noqa: BLE001
        logger.exception("Could not requeue the archives a restart stopped")
    try:   # the queued archives it was running go back in the queue, to resume from their checkpoints
        from insight_core.services.archive_jobs import ArchiveQueue

        queued_again = ArchiveQueue(db_url).requeue("scheduler")
        if queued_again:
            logger.info("%s queued archives a restart stopped are queued again", queued_again)
    except Exception:  # noqa: BLE001
        logger.exception("Could not queue again the archives a restart stopped")
    # the start's repairs in a process of their own, so their memory high-water leaves with it
    from insight_core.services.stories_service import in_own_process
    asyncio.get_running_loop().run_in_executor(None, in_own_process, startup_repairs, db_url)
    try:   # the scheduler's runs a restart ended mid-run
        closed = operations_service.close_interrupted_jobs("scheduler")
        if closed:
            logger.info("Marked %s scheduler jobs left running by a restart interrupted", closed)
    except Exception:  # noqa: BLE001
        logger.exception("Could not close the scheduler jobs a restart interrupted")
    try:
        state = SchedulerState.from_dict(operations_service.get_scheduler_state())
    except Exception:  # noqa: BLE001
        logger.exception("Could not read the scheduler state; starting fresh")
        state = SchedulerState()

    # Mark X's jobs run here, never in the API, each in a process of its own; the API only marks that work arrived.
    # With INSIGHT_MARKX off, only the reader's kept views (unread counts, Discover).
    from insight_core.markx.jobs import Runner as MarkxJobs
    from insight_core.utils import heartbeat
    heartbeat.clear("markx")   # written again only while its loop runs
    markx_jobs = MarkxJobs(db_url)
    try:
        markx_jobs.start()
    except Exception:  # noqa: BLE001 - Mark X never stops ingestion
        logger.exception("Could not start Mark X's jobs")
    # the source stats job (markx/source_stats.py), nightly and after a regroup; nothing when INSIGHT_MARKX is off
    from insight_core.markx.source_stats import Runner as SourceStats
    source_stats = SourceStats(db_url)
    try:
        source_stats.start()
    except Exception:  # noqa: BLE001 - the stats never stop ingestion
        logger.exception("Could not start the source stats job")

    # the API watchdog: restarts an API that stopped answering, through its container's door
    from insight_core.services import api_watchdog
    if api_watchdog.enabled():
        try:
            api_watchdog.Watchdog(operations_service, url=os.getenv("INSIGHT_API_WATCHDOG_URL") or api_watchdog.URL).start()
        except Exception:  # noqa: BLE001 - the watchdog never stops ingestion
            logger.exception("Could not start the API watchdog")

    archives = ArchiveJobs(operations_service, archive_service(db_url), trigger="scheduler")
    last_archive_poll = 0.0
    repairs_running = None   # the page's data repair asks, run in a process of their own
    new_reads = None         # the first read of the sources just added, a task of its own
    loop = asyncio.get_running_loop()
    beating = loop.create_task(_heartbeat())   # what the container's healthcheck reads
    from insight_core.utils.idle_trim import libc_trim
    trim = libc_trim()

    while RUNNING:
        now = datetime.now(timezone.utc)
        if loop.time() - last_archive_poll >= ARCHIVE_POLL_SECONDS:
            last_archive_poll = loop.time()
            repairs_running = repair_asks(db_url, repairs_running)
            new_reads = read_new_sources(db_url, new_reads, ingest=run_ingestion, ops=operations_service)
            try:
                for job_id in await archives.continue_due():
                    logger.info("Continuing archive job %s after its wait", job_id)
            except Exception:  # noqa: BLE001
                logger.exception("Could not continue the waiting archives")
            try:   # the queued archives whose lane is free (one Telegram, one Nitter at a time)
                for job_id in await archives.start_queued():
                    logger.info("Starting queued archive job %s", job_id)
            except Exception:  # noqa: BLE001
                logger.exception("Could not start the queued archives")
        if state.next_tick_at is None or now >= state.next_tick_at:
            if new_reads is not None and not new_reads.done():
                await asyncio.wait([new_reads])   # it holds the run lock: the tick would be skipped
            config = operations_service.get_scheduler_config()

            async def daily(cfg: Dict[str, Any]) -> None:
                await daily_work(db_url, operations_service, cfg)

            state = await tick(now, state, config, ingest=run_ingestion, daily_work=daily, ops=operations_service)
            await profiles_after_tick(db_url)
            gc.collect()   # the tick's freed memory goes back to the OS
            if trim is not None:
                trim()
            logger.info("Next ingestion tick at %s", state.next_tick_at.isoformat() if state.next_tick_at else "?")
        # Sleep in 1s steps so SIGTERM is honoured promptly.
        await asyncio.sleep(1)

    beating.cancel()
    markx_jobs.stop.set()
    source_stats.stop.set()
    logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
