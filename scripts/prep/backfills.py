"""The standard backfills of a prepared copy (scripts/prepared-db.sh), run inside a backend image with some version's
backend at /app (PYTHONPATH=/app). Each step is that version's own resumable code, run until nothing is left, so a
step whose rows are already done costs one query: `refresh` runs them all again and only the new work is done.

    python /prep/backfills.py [--only a,b] [--skip a,b]

Steps (each skipped when the version has no such code):
  post_refs   the refs of every post (backfill_post_refs, issue 0125)
  search      the search vectors of posts stored before search or by an older rule; Mark X's English layer
  handles     the 0168 handle scan of every pending post
  happenings  the stored happening keys of every read post (0175)
  units       the round-up split of every post (0181), its recheck once
  stories     the start's story job (stored bodies to the reader's rules, then the incremental story job)

Prints one JSON object on its last line: {step: {"seconds", "result"} | {"skipped": why} | {"error"}}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from typing import Any, Callable, Dict

STEPS = ["post_refs", "search", "handles", "happenings", "units", "stories"]


def _loop(step: Callable[[Any], Dict[str, Any]], left_key: str = "left", most: int = 100000) -> Dict[str, Any]:
    """Call a resumable step (a transaction each) until it reports nothing left; sum its counts."""
    from insight_core.db import database
    total: Dict[str, Any] = {}
    for _ in range(most):
        with database.transaction(os.environ["DATABASE_URL"]) as cur:
            got = step(cur) or {}
        for k, v in got.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k != left_key:
                total[k] = total.get(k, 0) + v
        total[left_key] = got.get(left_key)
        if not got.get(left_key):
            break
    return total


def post_refs() -> Any:
    try:
        from insight_core.db.repo_post_refs import PostRefsRepository  # noqa: F401
        from insight_core.scripts import backfill_post_refs
    except ImportError:
        return None
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        backfill_post_refs.main(["--db", os.environ["DATABASE_URL"]])
    out = buf.getvalue().strip().splitlines()
    return json.loads(out[-1]) if out else {}


def search() -> Any:
    import main  # the API's own functions, as the start runs them
    reader = main.services().reader
    got = {"posts": reader.fill_search_vectors()}
    if hasattr(reader, "fill_markx_search"):
        got["markx_english"] = reader.fill_markx_search()
    return got


def handles() -> Any:
    try:
        from insight_core.markx import handles as h
    except ImportError:
        return None
    if not hasattr(h, "scan_pending"):
        return None

    def step(cur):
        got = h.scan_pending(cur, limit=5000)
        return {**{k: v for k, v in got.items() if k != "done"}, "left": 0 if got.get("done") else 1}
    return _loop(step)


def happenings() -> Any:
    try:
        from insight_core.markx import happening
    except ImportError:
        return None
    if not hasattr(happening, "backfill"):
        return None
    return _loop(lambda cur: happening.backfill(cur, limit=5000, sweep=0))


def units() -> Any:
    try:
        from insight_core.markx import units as u
    except ImportError:
        return None
    if not hasattr(u, "backfill"):
        return None
    got = _loop(lambda cur: u.backfill(cur, limit=5000, recheck=0))
    with __import__("insight_core.db.database", fromlist=["x"]).transaction(os.environ["DATABASE_URL"]) as cur:
        got["rechecked"] = u.backfill(cur, limit=0).get("rechecked", 0)
    return got


def stories() -> Any:
    import main
    if not hasattr(main, "recompute_stories"):
        return None
    from insight_core.services import stories_service
    # to the end in one go: no step budget (a yield would leave the queue for a next run), no stepping aside for a
    # decision run a copy's mx_jobs says is wanted, no rest after an earlier yield
    for name, value in (("STEP_BUDGET_S", 1e12), ("DECISION_WAIT_S", 1e12), ("REST_AFTER_YIELD_S", 0.0)):
        if hasattr(stories_service, name):
            setattr(stories_service, name, value)
    svc = main.services()
    changed = svc.posts.catch_up_stored_bodies() if hasattr(svc.posts, "catch_up_stored_bodies") else None
    summary = svc.stories.recompute_safely()
    return {"bodies": changed, "job": summary}


def main_() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    args = ap.parse_args()
    only = [s for s in args.only.split(",") if s]
    skip = set(s for s in args.skip.split(",") if s)
    sys.path.insert(0, "/app")
    import logging
    logging.basicConfig(level=logging.WARNING)
    out: Dict[str, Any] = {}
    failed = False
    for name in STEPS:
        if (only and name not in only) or name in skip:
            continue
        t = time.monotonic()
        print(f"[backfills] {time.strftime('%H:%M:%S')} {name}", file=sys.stderr, flush=True)
        try:
            got = globals()[name]()
        except Exception as exc:  # a step's failure is reported; the others still run
            traceback.print_exc()
            out[name] = {"error": str(exc)[:300], "seconds": round(time.monotonic() - t, 1)}
            failed = True
            continue
        out[name] = {"skipped": "not in this version"} if got is None else \
            {"seconds": round(time.monotonic() - t, 1), "result": got}
    print(json.dumps(out, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main_())
