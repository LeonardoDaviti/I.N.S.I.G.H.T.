#!/usr/bin/env python3
"""
Long-running scheduler for the ingestion container (Mark IX).

Two clocks:
- the ingestion tick, every scheduler_config.ingest_tick_minutes (default 60, floor 15):
  one run_ingestion over all enabled sources. Cadence decides which are due, so a tick only
  touches the sources whose fetch interval has elapsed (or whose backoff has expired).
- daily work, once interval_hours have passed since system_settings.scheduler_state
  .last_daily_work_at: prune job_runs, refresh source cadence and sync sources.json. On
  the first tick after deploy last_daily_work_at is seeded from the newest successful
  scheduler_cycle job, so a deploy does not run the daily work twice.

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

logger = get_component_logger("run_scheduler")

RUNNING = True
TICK_MINUTES_FLOOR = 15


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
    #    instead of leaving it "running" (E5).
    request = FetchRequest(SourceSelector.all(), Trigger.SCHEDULER)
    job_id = None
    try:
        job_id = ops.start_job("ingestion_run", trigger="scheduler",
                               payload={"selector": request.selector.as_dict(), "force": request.force})
    except Exception:  # noqa: BLE001
        logger.exception("Could not start the ingestion_run job (running untracked)")
    status, message, payload = "failed", "Ingestion run did not finish", {}
    try:
        report = await ingest(request, progress=JobProgressSink(ops, job_id))
        status, message, payload = report.job_status, report.summary_line(), report.to_payload()
        logger.info("Ingestion tick: %s", message)
    except Exception as exc:  # noqa: BLE001
        message = f"Ingestion run failed: {exc}"
        logger.exception("Ingestion tick failed")
    finally:
        if job_id:
            try:
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
    """The upkeep: prune job_runs, refresh source cadence, sync sources.json -> DB."""
    from insight_core.ingestion.ports import DbFetchStateStore
    from insight_core.services.source_config_sync_service import SourceConfigSyncService

    try:
        pruned = operations_service.prune_job_runs(int(os.environ.get("INSIGHT_JOB_RUNS_RETAIN_DAYS", "30")))
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

    if scheduler_config.get("sync_sources_each_cycle", True):
        sync_service = SourceConfigSyncService(db_url)
        sync_result = sync_service.sync_json_to_db(mirror=True)
        logger.info("sources.json -> DB sync result: %s", sync_result)


async def main() -> None:
    from insight_core.db.ensure_db import ensure_database
    from insight_core.ingestion import run_ingestion
    from insight_core.services.operations_service import OperationsService

    setup_logging(debug_mode=False)
    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url
    operations_service = OperationsService(db_url)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    logger.info("Starting scheduler")
    try:
        state = SchedulerState.from_dict(operations_service.get_scheduler_state())
    except Exception:  # noqa: BLE001
        logger.exception("Could not read the scheduler state; starting fresh")
        state = SchedulerState()

    while RUNNING:
        now = datetime.now(timezone.utc)
        if state.next_tick_at is None or now >= state.next_tick_at:
            config = operations_service.get_scheduler_config()

            async def daily(cfg: Dict[str, Any]) -> None:
                await daily_work(db_url, operations_service, cfg)

            state = await tick(now, state, config, ingest=run_ingestion, daily_work=daily, ops=operations_service)
            logger.info("Next ingestion tick at %s", state.next_tick_at.isoformat() if state.next_tick_at else "?")
        # Sleep in 1s steps so SIGTERM is honoured promptly.
        await asyncio.sleep(1)

    logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
