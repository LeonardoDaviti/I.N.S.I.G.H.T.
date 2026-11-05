"""The story job on a scratch copy, on the copy's clock (issue 0075 C: each version's code over its own
copy). Never on a copy that matters: realdata-check.sh gives it a scratch database only.

    python -m insight_core.checks.job --db <scratch dsn> [--now ISO] [--deploy-json out]

Prints the job's summary as one JSON line. Runs in this process (not in_own_process): the check's
container ends with it.

With `--deploy-json`, first what a deploy's first start runs (issue 0110): the incremental job over the copy
as stored, step by step to the end; a copy whose rows are of other rules than this code's runs the rule
change's rebuild (keys, threads, names, then every post in batches), as the server did after v9.17. Then the
full job, and the rows the deploy's start left unlike it: `story.deploy_start` (1 when it raised),
`story.deploy_identity`, `story.deploy_lost` and `story.dangling`, read by the report with the other invariants."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

from insight_core.checks import table_rows
from insight_core.checks.session import copy_now, open_copy


PROTECTED = {"insight", "insight_lab", "insight_server_copy", "insight_preview", "postgres"}
# A scratch copy's name says so: …_test, …_check_a/_b (realdata-check.sh), …_<issue>a/b (an issue's own copies).
SCRATCH_RE = re.compile(r".+(?:_test|_check_[ab]|_check_\d+_[ab]|_\d{4}[ab])$")


def scratch_only(db_url: str) -> None:
    """Refuse a database whose name doesn't say it's a scratch copy."""
    name = db_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if name in PROTECTED or not SCRATCH_RE.fullmatch(name):
        raise SystemExit(f"refusing to write {name!r}: not a scratch copy (…_test, …_check_a/b, …_check_<pid>_a/b, …_<nnnn>a/b)")


def run_full(db_url: str, now: datetime) -> Dict[str, Any]:
    """A full rebuild: every post regrouped, News, Classics and Discover's counts refreshed."""
    from insight_core.services.news_service import NewsService
    from insight_core.services.stories_service import StoriesService
    clock = lambda: now   # noqa: E731
    return StoriesService(db_url, clock=clock, news=NewsService(db_url, clock=clock)).recompute(full=True)


def run_deploy_start(db_url: str, now: datetime) -> Dict[str, Any]:
    """The incremental job as a deploy's first start runs it (StoriesService.recompute, each step its own
    transaction), on the copy as stored. Returns what it did, and the error if it raised."""
    from insight_core.db.repo_operations import SystemSettingsRepository
    from insight_core.services.news_service import NewsService
    from insight_core.services.stories_service import SETTINGS_KEY, StoriesService, rules_stamp
    clock = lambda: now   # noqa: E731
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        stored = (SystemSettingsRepository.get(cur, SETTINGS_KEY) or ({}, None))[0] or {}
    out: Dict[str, Any] = {"rules_change": stored.get("rules") != rules_stamp(), "rebuild_before": stored.get("rebuild")}
    started = time.monotonic()
    try:
        summary = StoriesService(db_url, clock=clock, news=NewsService(db_url, clock=clock)).recompute()
        out["summary"] = {k: summary.get(k) for k in ("batches", "posts", "changed", "full") if k in summary}
    except Exception as error:  # noqa: BLE001 - the check reports it
        out["error"] = "".join(traceback.format_exception_only(type(error), error)).strip()[:600]
        out["where"] = traceback.format_exc().strip().splitlines()[-3:-1]
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


def story_rows(cur: Any) -> Dict[str, Any]:
    """What the story tables say of themselves: the rows naming a story not stored (none: the foreign keys
    refuse them, but a cascade drops rows silently), and the posts in a story."""
    cur.execute("SELECT count(*) FROM story_posts sp LEFT JOIN stories s ON s.id = sp.story_id WHERE s.id IS NULL")
    dangling = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM story_mentions m LEFT JOIN stories s ON s.id = m.story_id WHERE s.id IS NULL")
    dangling += cur.fetchone()[0]
    cur.execute("SELECT post_id::text FROM story_posts")
    return {"dangling": dangling, "in_story": {r[0] for r in cur.fetchall()}}


def deploy_found(start: Dict[str, Any], after: Any, full: Any, seconds: float,
                 rows_after: Dict[str, Any], rows_full: Dict[str, Any]) -> List[Any]:
    from insight_core.checks.invariants import EXAMPLES, Found
    lost = sorted(rows_full["in_story"] - rows_after["in_story"])
    what = "a rule change's rebuild" if start["rules_change"] or start["rebuild_before"] else "the queue"
    note = json.dumps({k: v for k, v in start.items() if k not in ("error", "where")}, default=str)
    counts = table_rows.by_table(after, full)
    return [
        Found("story.deploy_start", "stories", f"a deploy's first start (the incremental job: {what}) raised",
              1 if start.get("error") else 0, 1, [start["error"], *start.get("where", [])] if start.get("error") else [],
              start["seconds"], note=note),
        Found("story.deploy_identity", "stories", "rows a deploy's first start leaves unlike the full rebuild after it",
              sum(counts.values()), sum(len(rows) for rows in full.values()),
              [f"{t}: -{x} +{y}" for t, (x, y) in table_rows.differences(after, full).items()][:EXAMPLES], seconds,
              note=json.dumps({"by_table": counts}) if counts else ""),
        Found("story.deploy_lost", "stories", "posts in a story after the full rebuild but in none after a deploy's first start",
              len(lost), len(rows_full["in_story"]), lost[:EXAMPLES]),
        Found("story.dangling", "stories", "story_posts and story_mentions rows naming no stored story, after a deploy's first start",
              rows_after["dangling"], 0),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--now")
    ap.add_argument("--deploy-json", help="first run a deploy's first start, and write what it left here")
    args = ap.parse_args(argv)
    scratch_only(args.db)
    with open_copy(args.db, writable=True) as conn, conn.cursor() as cur:
        now = copy_now(cur, args.now)
    start = after = rows_after = None
    if args.deploy_json:
        # A moment before the full job: the stamp Discover keeps its counts by holds the last run's time, so on
        # one frozen clock the full job would keep the counts the start left rather than count (a deploy's clock moves).
        start = run_deploy_start(args.db, now - timedelta(milliseconds=1))
        print(json.dumps({"deploy_start": start}, default=str), file=sys.stderr)
        with open_copy(args.db, writable=True) as conn, conn.cursor() as cur:
            after, rows_after = table_rows.read_tables(cur), story_rows(cur)
    started = time.monotonic()
    summary = run_full(args.db, now)
    wall = round(time.monotonic() - started, 1)
    if args.deploy_json:
        with open_copy(args.db, writable=True) as conn, conn.cursor() as cur:
            full, rows_full = table_rows.read_tables(cur), story_rows(cur)
        found = deploy_found(start, after, full, wall, rows_after, rows_full)
        with open(args.deploy_json, "w", encoding="utf-8") as fh:
            json.dump({"now": now.isoformat(), "found": [asdict(f) for f in found]}, fh, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({"now": now.isoformat(), "wall_seconds": wall, **summary}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
