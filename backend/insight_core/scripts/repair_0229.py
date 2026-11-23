"""Read every post's entity addresses again with the 0229 rules, once, by hand.

    python -m insight_core.scripts.repair_0229 [--seconds-a-chunk 20] [--dry-run]

A row an older rule wrote as an entity's own page becomes kind `cited` when its post, read again, cites it
(entity_addresses.stage). CHUNK posts a transaction, each committed; no row is removed. Prints each chunk's
counts and the totals as JSON lines.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from insight_core.db.migrate import get_conn
from insight_core.markx import entity_addresses as EA
from insight_core.markx import identity as I


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--seconds-a-chunk", type=float, default=20.0)
    ap.add_argument("--dry-run", action="store_true", help="roll every chunk back")
    args = ap.parse_args()
    after, totals = None, {"posts": 0, "added": 0, "changed": 0}
    with get_conn() as conn:
        while True:
            with conn.cursor() as cur:
                got = EA.stage(cur, now=datetime.now(timezone.utc), since=None, full=True, after=after,
                               deadline=time.monotonic() + args.seconds_a_chunk, book=I.run_book(cur))
            conn.rollback() if args.dry_run else conn.commit()
            for k in totals:
                totals[k] += got.get(k, 0)
            print(json.dumps({k: got.get(k) for k in ("posts", "added", "changed", "after", "done")}), flush=True)
            if got["done"] or not got["after"] or got["after"] == after:
                break
            after = got["after"]
    print(json.dumps({"totals": totals, "dry_run": args.dry_run}))


if __name__ == "__main__":
    main()
