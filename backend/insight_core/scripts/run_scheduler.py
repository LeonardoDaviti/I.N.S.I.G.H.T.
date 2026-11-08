#!/usr/bin/env python3
"""
Long-running scheduler for the ingestion container (Mark IX).

Two clocks:
- the ingestion tick, every scheduler_config.ingest_tick_minutes (default 60, floor 15):
  one run_ingestion over all enabled sources. Cadence decides which are due, so a tick only
  touches the sources whose fetch interval has elapsed (or whose backoff has expired).
- daily work, once interval_hours have passed since system_settings.scheduler_state
  .last_daily_work_at: prune job_runs and refresh source cadence. On
  the first tick after deploy last_daily_work_at is seeded from the newest successful
  scheduler_cycle job, so a deploy does not run the daily work twice.
- waiting archives, every ARCHIVE_POLL_SECONDS: an archive a host's limit stopped waits for the
  window (issue 0107); once its time has come the scheduler continues it from its checkpoint, on
  the same job, in this process (so its pages and the hourly fetches of that host share one
  host limiter). A continuation runs as its own task beside the ticks; one that comes due during a
  tick starts after it, which leaves the hourly fetches the host first.
- The API watchdog (issue 0117), when INSIGHT_API_WATCHDOG is on (compose sets it): services/api_watchdog.py's
  Watchdog, in a thread of its own, asks the API every 30 s and asks its container to restart after 2 minutes of
  no answer, 3 times an hour at most.
- Mark X's jobs (issue 0112 Decided 10), when INSIGHT_MARKX is on: markx/jobs.py's Runner, in a thread of its own,
  looks every 30 s for the work the API marked and runs the candidate finder or a decision run in a child process.
- Channel profiles (issue 0132 C2), after each tick: a few sources' profile pages a tick, monthly, on the same
  gates (services/profiles_service.py; its switch is on by default).
- The source stats job (issue 0132 B), when INSIGHT_MARKX is on: markx/source_stats.py's Runner, in a thread of its
  own, looks every 5 minutes and runs the stats nightly and after a regroup, in a child process.

tick() is the testable unit: it takes its collaborators as arguments.
"""
from __future__ import annotations

import asyncio
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
    """0132 C2: the channel profiles due, a few a tick (services/profiles_service.py: monthly, capped, behind its
    switch, on by default), after the tick's fetches, on the same gates. Never raises: profiles never stop ingestion."""
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

    # 1. The ingestion run. The job is finished in every case: a raise marks it failed
    #    instead of leaving it "running" (E5). A tick with nothing due made no request: its
    #    job is deleted, not listed; the scheduler state below still records the tick (0021).
    request = FetchRequest(SourceSelector.all(), Trigger.SCHEDULER)
    job_id = None
    try:
        job_id = ops.start_job("ingestion_run", trigger="scheduler",
                               payload={"selector": request.selector.as_dict(), "force": request.force})
    except Exception:  # noqa: BLE001
        logger.exception("Could not start the ingestion_run job (running untracked)")
    status, message, payload, nothing_due = "failed", "Ingestion run did not finish", {}, False
    try:
        report = await ingest(request, progress=JobProgressSink(ops, job_id))
        status, message, payload = report.job_status, report.summary_line(), report.to_payload()
        nothing_due = report.status == "nothing_due"
        logger.info("Ingestion tick: %s", message)
    except Exception as exc:  # noqa: BLE001
        message = f"Ingestion run failed: {exc}"
        logger.exception("Ingestion tick failed")
    finally:
        if job_id:
            try:
                if nothing_due:
                    ops.discard_job(job_id)
                else:
                    ops.finish_job(job_id, status=status, message=message, payload=payload, compact=True)
            except Exception:  # noqa: BLE001
                logger.exception("Could not finish the ingestion_run job")

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
    """The upkeep: prune job_runs, refresh source cadence. sources.json is never read here: the
    database is the truth (issue 0071)."""
    from insight_core.ingestion.ports import DbFetchStateStore

    try:
        pruned = operations_service.prune_job_runs(env_int("INSIGHT_JOB_RUNS_RETAIN_DAYS", 30))
        if pruned:
            logger.info("Pruned %s job_runs rows older than the retention window", pruned)
    except Exception:  # noqa: BLE001
        logger.exception("job_runs prune failed (continuing with the daily work)")

    # Once a day: new sources leave probation and mean gaps follow the posts.
    try:
        refreshed = await asyncio.to_thread(DbFetchStateStore(db_url).refresh_cadence)
        logger.info("Cadence refreshed for %s sources", refreshed)
    except Exception:  # noqa: BLE001
        logger.exception("Cadence refresh failed (continuing with stored tiers)")


async def main() -> None:
    from insight_core.db.ensure_db import ensure_database
    from insight_core.ingestion import run_ingestion
    from insight_core.services.archive_jobs import ArchiveJobs
    from insight_core.services.operations_service import OperationsService
    from insight_core.services.source_fetch_service import archive_service

    setup_logging(debug_mode=False)
    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url
    operations_service = OperationsService(db_url)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    logger.info("Starting scheduler")
    try:   # the archives it was continuing carry on by themselves (issue 0107)
        requeued = operations_service.requeue_interrupted_archives("scheduler", datetime.now(timezone.utc))
        if requeued:
            logger.info("%s archives a restart stopped continue shortly", requeued)
    except Exception:  # noqa: BLE001
        logger.exception("Could not requeue the archives a restart stopped")
    try:   # the queued archives it was running go back in the queue, to resume from their checkpoints (issue 0130)
        from insight_core.services.archive_jobs import ArchiveQueue

        queued_again = ArchiveQueue(db_url).requeue("scheduler")
        if queued_again:
            logger.info("%s queued archives a restart stopped are queued again", queued_again)
    except Exception:  # noqa: BLE001
        logger.exception("Could not queue again the archives a restart stopped")
    # The posts stored without a normalized address get one (issue 0130 E1): once, at the deploy's first start;
    # resumable, and nothing at a later start. In a thread: the scheduler's first tick does not wait for it.
    from insight_core.scripts.repair_normalized_urls import repair_safely
    asyncio.get_running_loop().run_in_executor(None, repair_safely, db_url)
    # Issue 0135: Telegram bridge posts dated by their edit, and transcripts stored as a translation or as
    # caption markup, put right: the dates once, the transcripts a small budget per start; resumable, logged.
    from insight_core.scripts import repair_0135
    asyncio.get_running_loop().run_in_executor(None, repair_0135.repair_safely, db_url)
    try:   # the scheduler's runs a restart ended mid-run (issue 0070)
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

    # Mark X's jobs (0112 Decided 10): the candidate finder and the decision run, here and never in the API, each
    # in a process of its own; the API only marks that work arrived. Nothing when INSIGHT_MARKX is off.
    from insight_core.markx.jobs import Runner as MarkxJobs
    markx_jobs = MarkxJobs(db_url)
    try:
        markx_jobs.start()
    except Exception:  # noqa: BLE001 - Mark X never stops ingestion
        logger.exception("Could not start Mark X's jobs")
    # 0132 B: the source analysis page's stats job (markx/source_stats.py), nightly and after a regroup, in a process
    # of its own; nothing when INSIGHT_MARKX is off.
    from insight_core.markx.source_stats import Runner as SourceStats
    source_stats = SourceStats(db_url)
    try:
        source_stats.start()
    except Exception:  # noqa: BLE001 - the stats never stop ingestion
        logger.exception("Could not start the source stats job")

    # The API watchdog (issue 0117): restarts an API that stopped answering, through its container's door.
    from insight_core.services import api_watchdog
    if api_watchdog.enabled():
        try:
            api_watchdog.Watchdog(operations_service, url=os.getenv("INSIGHT_API_WATCHDOG_URL") or api_watchdog.URL).start()
        except Exception:  # noqa: BLE001 - the watchdog never stops ingestion
            logger.exception("Could not start the API watchdog")

    archives = ArchiveJobs(operations_service, archive_service(db_url), trigger="scheduler")
    last_archive_poll = 0.0
    loop = asyncio.get_running_loop()

    while RUNNING:
        now = datetime.now(timezone.utc)
        if loop.time() - last_archive_poll >= ARCHIVE_POLL_SECONDS:
            last_archive_poll = loop.time()
            try:
                for job_id in await archives.continue_due():
                    logger.info("Continuing archive job %s after its wait", job_id)
            except Exception:  # noqa: BLE001
                logger.exception("Could not continue the waiting archives")
            try:   # the queued archives whose lane is free (issue 0130: one Telegram, one Nitter at a time)
                for job_id in await archives.start_queued():
                    logger.info("Starting queued archive job %s", job_id)
            except Exception:  # noqa: BLE001
                logger.exception("Could not start the queued archives")
        if state.next_tick_at is None or now >= state.next_tick_at:
            config = operations_service.get_scheduler_config()

            async def daily(cfg: Dict[str, Any]) -> None:
                await daily_work(db_url, operations_service, cfg)

            state = await tick(now, state, config, ingest=run_ingestion, daily_work=daily, ops=operations_service)
            await profiles_after_tick(db_url)
            logger.info("Next ingestion tick at %s", state.next_tick_at.isoformat() if state.next_tick_at else "?")
        # Sleep in 1s steps so SIGTERM is honoured promptly.
        await asyncio.sleep(1)

    markx_jobs.stop.set()
    source_stats.stop.set()
    logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
