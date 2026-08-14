#!/usr/bin/env python3
"""Regenerate stored daily briefings from already-ingested posts.

Use this to repair briefings that were persisted in a broken state - e.g. the
truncated fragments produced before the MAX_TOKENS gate existed in
gemini_processor._generate_text_sync, or the deterministic string-concat
fallback that fires when generation raises.

This re-runs the LLM and OVERWRITES the stored row (briefings upserts on
subject_key = date). Back up first:

    docker exec insight-db pg_dump -U insight -d insight -t briefings \
      --data-only --column-inserts > briefings_backup.sql

It does NOT re-ingest. Only posts already in the database are used.

Examples
--------
    # Show what is broken, change nothing
    python insight_core/scripts/regenerate_briefings.py --list-defective

    # Repair every defective briefing
    python insight_core/scripts/regenerate_briefings.py --defective

    # Specific dates
    python insight_core/scripts/regenerate_briefings.py 2026-08-13 2026-08-14
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg  # noqa: E402

from insight_core.db.ensure_db import ensure_database  # noqa: E402
from insight_core.services.briefing_service import BriefingService  # noqa: E402

# A healthy briefing is markdown starting with a heading. Fragments begin
# mid-word or mid-list; the fallback emits this distinctive bullet.
DEFECTIVE_SQL = """
    SELECT subject_key, length(content)
    FROM briefings
    WHERE subject_type = 'daily_briefing'
      AND (content LIKE '%%posts collected across%%' OR content NOT LIKE '#%%')
    ORDER BY subject_key
"""


def find_defective(db_url: str) -> list[tuple[str, int]]:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(DEFECTIVE_SQL)
            return [(row[0], row[1]) for row in cur.fetchall()]


async def regenerate(db_url: str, dates: list[str]) -> int:
    service = BriefingService(db_url)
    failures = 0
    for date_str in dates:
        try:
            result = await service.generate_daily_briefing(date_str, refresh=True)
            ok = bool(result.get("success"))
            failures += 0 if ok else 1
            print(
                f"{date_str}  success={ok}  posts={result.get('posts_processed')}"
                f"  {(result.get('error') or '')[:80]}".rstrip(),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{date_str}  EXCEPTION {type(exc).__name__}: {exc}"[:160], flush=True)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", help="Dates to regenerate (YYYY-MM-DD)")
    parser.add_argument("--defective", action="store_true", help="Regenerate every defective briefing")
    parser.add_argument("--list-defective", action="store_true", help="List defective briefings and exit")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL") or ensure_database()

    if args.list_defective:
        rows = find_defective(db_url)
        for key, length in rows:
            print(f"{key}  {length} bytes")
        print(f"{len(rows)} defective briefing(s)")
        return 0

    dates = list(args.dates)
    if args.defective:
        dates.extend(key for key, _ in find_defective(db_url) if key not in dates)

    if not dates:
        parser.error("give one or more dates, or --defective / --list-defective")

    print(f"Regenerating {len(dates)} briefing(s). This calls the LLM and overwrites stored rows.")
    return 1 if asyncio.run(regenerate(db_url, dates)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
