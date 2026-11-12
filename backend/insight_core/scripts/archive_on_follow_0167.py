"""Fetch the archives a follow did not (issue 0167): the sources followed before following fetched them.

    python -m insight_core.scripts.archive_on_follow_0167                 # dry run: lists them, queues nothing
    python -m insight_core.scripts.archive_on_follow_0167 --apply         # queues their archives
    python -m insight_core.scripts.archive_on_follow_0167 --source <id>   # one source, on demand (with --apply)

A source is listed when following it would queue its archive now (services/follow_archive.plan: an enabled website
feed or Substack publication the archive accepts) and it holds nothing older than the follow horizon
(follow_archive.horizon): its oldest stored post is newer, and no archive of it ever ran. --source takes the one
source whatever it holds. Each is queued as a follow queues it (ArchiveJobs.enqueue, back to the horizon); the
ingestion process runs them in their turn, one per lane, inside the host gates and budgets. Nothing is fetched here.
Resumable: a source queued (or archived) is not listed again. Prints the list as JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.services import follow_archive  # noqa: E402


def candidates(db_url: str, until: str, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The enabled sources with no archive job ever and no post older than `until` (or the one source)."""
    with db.connection(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT s.id::text, COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url),
                      (SELECT min(COALESCE(p.published_at, p.fetched_at)) FROM posts p WHERE p.source_id = s.id)
                 FROM sources s
                WHERE s.enabled AND (%(one)s::uuid IS NULL OR s.id = %(one)s::uuid)
                  AND (%(one)s::uuid IS NOT NULL OR (
                       NOT EXISTS (SELECT 1 FROM job_runs j WHERE j.job_type = 'archive_source' AND j.source_id = s.id)
                       AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.source_id = s.id
                                         AND COALESCE(p.published_at, p.fetched_at) < %(until)s::date)))
                ORDER BY s.created_at DESC, s.id""", {"one": source_id, "until": until})
        return [{"source_id": sid, "name": name, "oldest": oldest.isoformat() if oldest else None}
                for sid, name, oldest in cur.fetchall()]


def run(services: Any, jobs: Any, db_url: str, *, apply: bool = False, source_id: Optional[str] = None) -> Dict[str, Any]:
    until = follow_archive.horizon(db_url)
    listed, left = [], []
    for row in candidates(db_url, until, source_id):
        planned = follow_archive.plan(services, row["source_id"])
        if not planned["queue"]:
            left.append({**row, "reason": planned["reason"]})
            continue
        if apply:
            row.update(follow_archive.queue_on_follow(services, lambda: jobs, row["source_id"]))
        listed.append(row)
    return {"dry_run": not apply, "until": until, "sources": listed, "left": left}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--apply", action="store_true", help="queue the archives (default: a dry run)")
    ap.add_argument("--source", help="one source id, whatever it holds")
    args = ap.parse_args(argv)
    from insight_core.services import registry
    from insight_core.services.archive_jobs import ArchiveJobs

    db_url = args.db
    if not db_url:
        from insight_core.db.ensure_db import ensure_database
        db_url = ensure_database()
    services = registry.build_services(db_url)
    jobs = ArchiveJobs(services.operations, services.source_fetch, trigger="manual")
    print(json.dumps(run(services, jobs, db_url, apply=args.apply, source_id=args.source), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
