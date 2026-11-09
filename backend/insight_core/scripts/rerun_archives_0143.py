"""Re-run what was called archived (issue 0143), once: the feeds capped at their feed, through the smart archiver.

    python -m insight_core.scripts.rerun_archives_0143 [--db DSN] [--dry-run]

A feed source (generic RSS) is selected when its archive says `archived` but never ran (`last_archived_at` empty:
the plan measured the feed alone and a live fetch called it archived), or its stored count is about its feed's
(stored >= what the feed lists - 1: a feed that lists its latest 10 to 30 posts and nothing more was read). Each is
planned again (the ladder: its platform, every strategy's probe, the site's estimate), one source at a time,
PLAN_GAP_S apart; where a strategy finds more, an archive is queued (one per host lane, 0107's waits and gates).
Telegram, X and every other kind are untouched. Each source is marked `settings.archive.rerun_0143` {at, outcome}:
a later start finds nothing to plan, and the run resumes where a stop left it.

The ingestion process runs it at each start (`rerun_safely`, a thread, logged); this runs it by hand. Its summary
(system_settings `archive_rerun_0143`): selected, planned, queued, nothing more, errors, the platforms, the reasons
of the ones left partial, the requests the plans spent, and how many went from capped to full (their archive since
says archived). Nothing when INSIGHT_DISCOVER_READS=0 (a machine that must not fetch) or INSIGHT_ARCHIVE_RERUN=0.
No post or row is removed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

logger = logging.getLogger("insight.rerun_archives_0143")

MARK = "rerun_0143"
SUMMARY_KEY = "archive_rerun_0143"
PLAN_GAP_S = 2.0
FEED_KIND = "generic_rss"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def capped(archive: Mapping[str, Any], stored: int) -> Optional[str]:
    """Why a feed's archive looks capped at its feed ("never_ran", "at_feed"), or None."""
    if archive.get("status") == "archived" and not archive.get("last_archived_at"):
        return "never_ran"
    available = _int(archive.get("available_posts"))
    if available is not None and available > 0 and stored + 1 >= available:
        return "at_feed"
    return None


def select(sources: Iterable[Mapping[str, Any]], kind_of: Callable[[Mapping[str, Any]], str]) -> List[Dict[str, Any]]:
    """The feed sources to plan again: enabled, of the feed kind, not marked yet, capped (`capped`).
    [{id, why}] in the sources' order."""
    chosen = []
    for source in sources:
        if not source.get("enabled"):
            continue
        settings = source.get("settings") or {}
        archive = settings.get("archive") or {}
        if not isinstance(archive, Mapping) or isinstance(archive.get(MARK), Mapping):
            continue
        try:
            if kind_of(source) != FEED_KIND:
                continue
        except LookupError:
            continue
        stored = _int(archive.get("stored_posts")) or _int(source.get("post_count")) or 0
        why = capped(archive, stored)
        if why:
            chosen.append({"id": str(source["id"]), "why": why})
    return chosen


def summary_of(sources: Iterable[Mapping[str, Any]], previous: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The re-run's summary from the marked sources: what each plan found, and how many are full now (their
    archive says archived, an archive having run since the mark)."""
    outcomes: Counter = Counter()
    platforms: Counter = Counter()
    reasons: Counter = Counter()
    requests = full = partial = 0
    for source in sources:
        archive = (source.get("settings") or {}).get("archive") or {}
        mark = archive.get(MARK) if isinstance(archive, Mapping) else None
        if not isinstance(mark, Mapping):
            continue
        outcomes[str(mark.get("outcome"))] += 1
        smart = archive.get("smart") if isinstance(archive.get("smart"), Mapping) else {}
        if smart.get("platform"):
            platforms[str(smart["platform"])] += 1
        requests += int(mark.get("requests") or 0)
        if mark.get("outcome") != "queued":
            continue
        ran = str(archive.get("last_archived_at") or "") >= str(mark.get("at") or "~")
        if ran and archive.get("status") == "archived":
            full += 1
        elif ran:
            partial += 1
            for name, outcome in (smart.get("outcomes") or {}).items():
                if not str(outcome).startswith("more"):
                    reasons[f"{name}:{outcome}"] += 1
    return {
        **{key: value for key, value in (previous or {}).items() if key in ("started_at",)},
        "selected": sum(outcomes.values()),
        "queued": outcomes.get("queued", 0),
        "nothing_more": outcomes.get("nothing_more", 0),
        "errors": sum(count for outcome, count in outcomes.items() if outcome.startswith("error")),
        "platforms": dict(platforms.most_common()),
        "capped_to_full": full,
        "still_partial": partial,
        "partial_reasons": dict(reasons.most_common()),
        "plan_requests": requests,
        "at": _now(),
    }


class Rerun:
    """`service` plans (SourceFetchService.plan_archive), `enqueue(source_id)` queues an archive (ArchiveJobs),
    `sources` reads every source with its settings and `mark(source_id, mark)` merges archive.rerun_0143."""

    def __init__(self, *, service: Any, enqueue: Callable[[str], Any], sources: Callable[[], List[Dict[str, Any]]],
                 kind_of: Callable[[Mapping[str, Any]], str], mark: Callable[[str, Dict[str, Any]], None],
                 sleep: Callable[[float], Any] = asyncio.sleep, gap_s: float = PLAN_GAP_S) -> None:
        self.service, self.enqueue, self.sources, self.kind_of, self.mark = service, enqueue, sources, kind_of, mark
        self.sleep, self.gap_s = sleep, gap_s

    async def run(self, *, dry_run: bool = False) -> Dict[str, Any]:
        chosen = select(await asyncio.to_thread(self.sources), self.kind_of)
        if dry_run:
            return {"selected": len(chosen), "why": dict(Counter(item["why"] for item in chosen))}
        for index, item in enumerate(chosen):
            if index:
                await self.sleep(self.gap_s)
            mark: Dict[str, Any] = {"at": _now(), "why": item["why"]}
            try:
                plan = await self.service.plan_archive(item["id"])
                smart = plan.get("smart") if isinstance(plan.get("smart"), dict) else {}
                mark.update(platform=smart.get("platform"), strategy=smart.get("strategy"),
                            requests=smart.get("requests") or 0)
                if smart.get("found_more"):
                    await asyncio.to_thread(self.enqueue, item["id"])
                    mark["outcome"] = "queued"
                else:
                    mark["outcome"] = "nothing_more"
            except Exception as exc:  # noqa: BLE001 - one source failing is its outcome
                logger.info("Archive re-run: %s could not be planned (%s): %s", item["id"], type(exc).__name__,
                            str(exc)[:200])
                mark["outcome"] = f"error:{type(exc).__name__}"
            await asyncio.to_thread(self.mark, item["id"], mark)
        return summary_of(await asyncio.to_thread(self.sources))


def _rerun(db_url: str) -> Rerun:
    from insight_core.services.archive_jobs import ArchiveJobs
    from insight_core.services.operations_service import OperationsService
    from insight_core.services.source_fetch_service import archive_service

    service = archive_service(db_url)
    jobs = ArchiveJobs(OperationsService(db_url), service, trigger="scheduler")
    sources = service.sources_service
    return Rerun(service=service, enqueue=lambda source_id: jobs.enqueue(source_id, resume=True),
                 sources=sources.get_all_sources_with_settings, kind_of=lambda source: service.kinds.resolve(source).name,
                 mark=lambda source_id, mark: sources.merge_source_settings(source_id, {"archive": {MARK: mark}}))


def _keep_summary(db_url: str, summary: Dict[str, Any]) -> None:
    from insight_core.db import database as db
    from insight_core.db.repo_operations import SystemSettingsRepository

    with db.transaction(db_url) as cur:
        SystemSettingsRepository.upsert(cur, SUMMARY_KEY, summary)


def rerun_safely(db_url: str) -> Optional[Dict[str, Any]]:
    """The ingestion process's start (issue 0143): the capped feeds planned again once and their archives queued,
    logged, the summary kept; resumable. Never raises."""
    if os.getenv("INSIGHT_DISCOVER_READS", "1") == "0" or os.getenv("INSIGHT_ARCHIVE_RERUN", "1") == "0":
        return None
    try:
        summary = asyncio.run(_rerun(db_url).run())
        _keep_summary(db_url, summary)
    except Exception:  # noqa: BLE001 - the re-run is never worth the start
        logger.exception("Archive re-run (0143): could not run")
        return None
    if summary.get("selected"):
        logger.info("Archive re-run (0143): %s", json.dumps(summary))
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="say what would be planned; no request")
    args = parser.parse_args(argv)
    if not args.db:
        parser.error("no database: --db or DATABASE_URL")
    summary = asyncio.run(_rerun(args.db).run(dry_run=args.dry_run))
    if not args.dry_run:
        _keep_summary(args.db, summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
