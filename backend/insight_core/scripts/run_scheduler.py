#!/usr/bin/env python3
"""
Long-running ingestion scheduler for the ingestion container.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import get_component_logger, setup_logging
from insight_core.scripts.safe_ingest import safe_ingest_posts
from insight_core.services.briefing_service import BriefingService
from insight_core.services.source_config_sync_service import SourceConfigSyncService


RUNNING = True


def _handle_stop(signum, frame):
    global RUNNING
    RUNNING = False


async def run_cycle(logger, db_url: str) -> None:
    if os.getenv("INSIGHT_SYNC_SOURCES_EACH_CYCLE", "true").lower() == "true":
        sync_service = SourceConfigSyncService(db_url)
        sync_result = sync_service.sync_json_to_db(mirror=True)
        logger.info("sources.json -> DB sync result: %s", sync_result)

    ingest_result = await safe_ingest_posts()
    logger.info("safe_ingest result: %s", ingest_result)

    if os.getenv("INSIGHT_GENERATE_DAILY_BRIEFING", "true").lower() != "true":
        return

    briefing_service = BriefingService(db_url)
    today = datetime.now(timezone.utc).date().isoformat()
    daily_result = await briefing_service.generate_daily_briefing(today)
    logger.info("daily briefing result for %s: success=%s", today, daily_result.get("success"))

    if os.getenv("INSIGHT_GENERATE_TOPIC_BRIEFING", "false").lower() == "true":
        topics_result = await briefing_service.generate_daily_briefing_with_topics(today)
        logger.info("topic briefing result for %s: success=%s", today, topics_result.get("success"))


async def main() -> None:
    setup_logging(debug_mode=False)
    logger = get_component_logger("run_scheduler")

    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url

    interval_hours = float(os.getenv("INSIGHT_INGEST_INTERVAL_HOURS", "20"))
    sleep_seconds = max(60, int(interval_hours * 3600))

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    logger.info("Starting scheduler with interval=%ss", sleep_seconds)
    while RUNNING:
        cycle_started = datetime.now(timezone.utc).isoformat()
        logger.info("Scheduler cycle started at %s", cycle_started)
        try:
            await run_cycle(logger, db_url)
        except Exception as exc:
            logger.exception("Scheduler cycle failed: %s", exc)

        if not RUNNING:
            break

        logger.info("Scheduler sleeping for %ss", sleep_seconds)
        for _ in range(sleep_seconds):
            if not RUNNING:
                break
            await asyncio.sleep(1)

    logger.info("Scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
