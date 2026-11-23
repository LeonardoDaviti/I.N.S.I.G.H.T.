"""Make every topic track's rows one a thing again, once, by hand.

    python -m insight_core.scripts.repair_track_rows [--track <folder id>] [--no-ask] [--dry-run]

track_things.repair splits each row that absorbed reports of different things by strong identity (nothing is
deleted), rejoins split-off things to an older row of their identity, merges fields again, and asks each
catalog post again under track-things-v3. A transaction a track; `--dry-run` rolls each back and prints the
plan. Prints one JSON line a track.
"""
from __future__ import annotations

import argparse
import json

from insight_core.db.migrate import get_conn
from insight_core.markx import track_things as TT
from insight_core.markx import tracks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--track", action="append", help="a track's folder id (default: every described track)")
    ap.add_argument("--no-ask", action="store_true", help="split only: do not ask the catalog posts again")
    ap.add_argument("--dry-run", action="store_true", help="the plan only, every transaction rolled back")
    args = ap.parse_args()
    with get_conn() as conn:
        with conn.cursor() as cur:
            ids = args.track or [t["folder_id"] for t in tracks.described(cur)]
        conn.rollback()
        for tid in ids:
            with conn.cursor() as cur:
                rows = len(TT.current(cur, tid))
                got = TT.repair(cur, tid, dry_run=args.dry_run, ask=not args.no_ask)
            conn.rollback() if args.dry_run else conn.commit()
            print(json.dumps({"track": tid, "rows": rows, "splits": len(got["splits"]),
                              "split_off": sum(len(s["groups"]) for s in got["splits"]),
                              "biggest": sorted(({"thing": s["thing"], "name": s["name"], "posts": s["posts"],
                                                  "groups": len(s["groups"])} for s in got["splits"]),
                                                key=lambda s: -s["groups"])[:5],
                              "rejoined": got.get("rejoined", 0), "catalogs": len(got["catalogs"]),
                              "asked": got.get("asked", 0), "dry_run": args.dry_run}, ensure_ascii=False),
                  flush=True)


if __name__ == "__main__":
    main()
