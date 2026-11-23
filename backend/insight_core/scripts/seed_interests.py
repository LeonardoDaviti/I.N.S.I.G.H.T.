"""Seed the reader's stated interests, once, by hand (Stealth v10.42).

    python -m insight_core.scripts.seed_interests "GrapheneOS" "Brave" "Arch Linux" [--dry-run]

Each name becomes a seed tap (mx_interests, origin seed: "More" of that thing, markx/personal.SEED), on the entity of
that name with the most mentions; a name no entity has is skipped and said. A later tap of the reader on the same
thing replaces the seed; "undo" takes it back. Prints one JSON line: seeded, skipped.
"""
from __future__ import annotations

import argparse
import json

from insight_core.db.migrate import get_conn
from insight_core.markx import personal


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("names", nargs="+", help="a thing's name, as its entity page names it")
    ap.add_argument("--dry-run", action="store_true", help="say what would be seeded, roll back")
    args = ap.parse_args()
    with get_conn() as conn:
        with conn.cursor() as cur:
            got = personal.seed(cur, args.names)
        conn.rollback() if args.dry_run else conn.commit()
    seeded = {g["key"] for g in got}
    print(json.dumps({"seeded": got, "skipped": len(args.names) - len(seeded), "dry_run": args.dry_run},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
