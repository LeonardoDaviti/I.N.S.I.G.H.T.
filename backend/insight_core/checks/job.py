"""The story job on a scratch copy, on the copy's clock (issue 0075 C: each version's code over its own
copy). Never on a copy that matters: realdata-check.sh gives it a scratch database only.

    python -m insight_core.checks.job --db <scratch dsn> [--now ISO]

Prints the job's summary as one JSON line. Runs in this process (not in_own_process): the check's
container ends with it."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict

from insight_core.checks.session import copy_now, open_copy


PROTECTED = {"insight", "insight_lab", "insight_server_copy", "insight_preview", "postgres"}
# A scratch copy's name says so: …_test, …_check_a/_b (realdata-check.sh), …_<issue>a/b (an issue's own copies).
SCRATCH_RE = re.compile(r".+(?:_test|_check_[ab]|_\d{4}[ab])$")


def scratch_only(db_url: str) -> None:
    """Refuse a database whose name doesn't say it's a scratch copy."""
    name = db_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if name in PROTECTED or not SCRATCH_RE.fullmatch(name):
        raise SystemExit(f"refusing to write {name!r}: not a scratch copy (…_test, …_check_a/b, …_<nnnn>a/b)")


def run_full(db_url: str, now: datetime) -> Dict[str, Any]:
    """A full rebuild: every post regrouped, News, Classics and Discover's counts refreshed."""
    from insight_core.services.news_service import NewsService
    from insight_core.services.stories_service import StoriesService
    clock = lambda: now   # noqa: E731
    return StoriesService(db_url, clock=clock, news=NewsService(db_url, clock=clock)).recompute(full=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--now")
    args = ap.parse_args(argv)
    scratch_only(args.db)
    with open_copy(args.db, writable=True) as conn, conn.cursor() as cur:
        now = copy_now(cur, args.now)
    started = time.monotonic()
    summary = run_full(args.db, now)
    print(json.dumps({"now": now.isoformat(), "wall_seconds": round(time.monotonic() - started, 1), **summary}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
