"""Make every topic track's rows one a thing again, once (services/data_repairs.py runs it after a deploy; by hand too).

    python -m insight_core.scripts.repair_track_rows [--track <folder id>] [--no-ask] [--dry-run]

track_things.repair splits each row that absorbed reports of different things by strong identity (nothing is
deleted), rejoins split-off things to an older row of their identity, merges fields again, and asks each
catalog post again under track-things-v3. A transaction a track; `--dry-run` rolls each back and prints the
plan. Prints one JSON line a track.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional, Sequence

from insight_core.db.migrate import get_conn
from insight_core.markx import track_things as TT
from insight_core.markx import tracks


def run(conn, *, dry_run: bool, ask: bool = True, track_ids: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Each track repaired in a transaction of its own (`dry_run`: rolled back): one summary a track."""
    with conn.cursor() as cur:
        ids = list(track_ids or [t["folder_id"] for t in tracks.described(cur)])
    conn.rollback()
    out = []
    for tid in ids:
        with conn.cursor() as cur:
            rows = len(TT.current(cur, tid))
            got = TT.repair(cur, tid, dry_run=dry_run, ask=ask)
        conn.rollback() if dry_run else conn.commit()
        out.append({"track": tid, "rows": rows, "splits": len(got["splits"]),
                    "split_off": sum(len(s["groups"]) for s in got["splits"]),
                    "biggest": sorted(({"thing": s["thing"], "name": s["name"], "posts": s["posts"],
                                        "groups": len(s["groups"])} for s in got["splits"]),
                                      key=lambda s: -s["groups"])[:5],
                    "rejoined": got.get("rejoined", 0), "catalogs": len(got["catalogs"]),
                    "asked": got.get("asked", 0), "dry_run": dry_run})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--track", action="append", help="a track's folder id (default: every described track)")
    ap.add_argument("--no-ask", action="store_true", help="split only: do not ask the catalog posts again")
    ap.add_argument("--dry-run", action="store_true", help="the plan only, every transaction rolled back")
    args = ap.parse_args()
    with get_conn() as conn:
        for line in run(conn, dry_run=args.dry_run, ask=not args.no_ask, track_ids=args.track):
            print(json.dumps(line, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
