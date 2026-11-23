"""The jobs' resources on the check's copy: each job's own peak memory and seconds, as the jobs process runs it (a
spawned process of its own, markx/jobs.py `_job_main`), for the base and the head; the report fails a head over its
budget or more than WORSE_BY worse than the base.

    python -m insight_core.checks.resources --db <scratch dsn> [--now ISO] [--json resources.json]

The jobs, each in a fresh process (its peak is its own high-water, utils/peak): `decide_full` (the first decision run,
full; compared, no budget), `decide` (the next, incremental), `stories` (Mark IX's story job, its web reads left out),
`discover` (its web reads off), then `plan` (the background planners) and the kept views `news`, `entities` and
`tracks` after those runs (0279 C3: each derived view has its own budget, so a rebuild that grows shows by name). The decision runs' clock is the copy's (`--now`). A version without a job is "not
measured" for it, never a failure. BUDGETS (overridable with RESOURCE_BUDGETS JSON) are at the server's size; the
check's copy is smaller, so a head over them is over at any size. Differences under FLOOR_MB / FLOOR_S never fail."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

JOBS = ("decide_full", "decide", "stories", "discover", "plan", "news", "entities", "tracks")
# the kept views' and the plan job's: about 2x a run on the server (2026-11-23, its last runs: plan 15.5 CPU s / 232 MB,
# news 13.5 / 204, entities 34.8 / 405, tracks 14.4 / 225; 0279 A)
BUDGETS: Dict[str, Dict[str, float]] = {"decide": {"peak_mb": 600.0, "seconds": 90.0},
                                         "stories": {"peak_mb": 300.0},
                                         "discover": {"peak_mb": 300.0},
                                         "plan": {"peak_mb": 400.0, "cpu_s": 30.0},
                                         "news": {"peak_mb": 400.0, "cpu_s": 30.0},
                                         "entities": {"peak_mb": 600.0, "cpu_s": 70.0},
                                         "tracks": {"peak_mb": 400.0, "cpu_s": 30.0}}
WORSE_BY = 0.20        # a head this much above the base (peak MB, CPU seconds) fails
FLOOR_MB = 50.0        # ... unless the difference is under these
FLOOR_S = 5.0
TIMEOUT_S = 1800.0     # a job that runs longer is stopped and recorded (the copy is scratch)


def budgets() -> Dict[str, Dict[str, float]]:
    """BUDGETS, each job's values replaced by RESOURCE_BUDGETS' (JSON) where it gives them."""
    out = {job: dict(v) for job, v in BUDGETS.items()}
    extra = os.environ.get("RESOURCE_BUDGETS")
    if extra:
        for job, v in json.loads(extra).items():
            out.setdefault(job, {}).update({k: float(x) for k, x in v.items()})
    return out


def _child(db_url: str, job: str, now_iso: Optional[str], out: Any) -> None:
    """One job in this fresh process: its own peak (utils/peak, from its start), wall and CPU seconds."""
    os.environ["DATABASE_URL"] = db_url
    os.environ["INSIGHT_MARKX"] = "on"
    os.environ["INSIGHT_DISCOVER_READS"] = "0"
    got: Dict[str, Any] = {}
    try:
        from insight_core.utils import peak
        from insight_core.markx import jobs as J
        now = datetime.fromisoformat(now_iso) if now_iso else None
        if now is not None:
            from insight_core.markx import decide
            decide._now = lambda: now
        runner = J.Jobs(db_url, **({"clock": (lambda: now)} if now is not None else {}))
        if job.startswith("decide"):
            run = runner.decide
        elif job == "stories":
            J.want_stories(db_url)
            J.Jobs.after_stories = lambda self: {"ok": True, "skipped": "the real-data check reads no web"}
            run = runner.stories
        else:
            run = getattr(runner, job, None)
            if run is None:
                out.put({"not_measured": f"this version has no {job} job"})
                return
        peak.reset()
        t0, c0 = time.monotonic(), time.process_time()
        result = run() or {}
        got = {"peak_mb": peak.mb(), "seconds": round(time.monotonic() - t0, 1),
               "cpu_s": round(time.process_time() - c0, 1)}
        if job.startswith("decide"):
            r = result.get("run") if isinstance(result.get("run"), dict) else {}
            got["kind"] = r.get("kind")
            got["skipped"] = result.get("skipped")
            last = runner.last("decide").get("last") or {}
            if not last.get("ok"):   # stopped over its limit, or failed: what its record says
                got["not_finished"] = str(last.get("error") or "no record")[:300]
    except ImportError as error:   # a version without the jobs module
        got = {"not_measured": f"this version has no {job} job ({error})"}
    except Exception as error:  # noqa: BLE001 - recorded, the report says it
        got = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
    out.put(got)


def measure(db_url: str, job: str, now: Optional[datetime], timeout: float = TIMEOUT_S) -> Dict[str, Any]:
    """One job in a spawned process, as the jobs process runs it: {peak_mb, seconds, cpu_s} (or not_measured, error)."""
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_child, args=(db_url, job, now.isoformat() if now else None, q), name=f"check-{job}")
    t0 = time.monotonic()
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.kill()
        p.join(10)
        return {"error": f"stopped after {timeout:.0f} s", "seconds": round(time.monotonic() - t0, 1)}
    try:
        return q.get(timeout=5)
    except Exception:  # noqa: BLE001
        return {"error": f"the job's process ended with code {p.exitcode} and no result"}


def run_all(db_url: str, now: Optional[datetime], jobs: List[str] = list(JOBS)) -> Dict[str, Any]:
    return {job: measure(db_url, job, now) for job in jobs}


def compare(base: Optional[Dict[str, Any]], head: Optional[Dict[str, Any]],
            limits: Optional[Dict[str, Dict[str, float]]] = None) -> List[Dict[str, Any]]:
    """Each job's row: base and head peak MB, seconds and CPU seconds, its budget, and what fails it (`problems`): the
    head over a budget, or more than WORSE_BY above the base's peak MB or CPU seconds (past FLOOR_MB / FLOOR_S)."""
    limits = budgets() if limits is None else limits
    base, head = base or {}, head or {}
    rows = []
    for job in dict.fromkeys([*JOBS, *head, *base]):
        b, h = base.get(job) or {}, head.get(job) or {}
        problems: List[str] = []
        budget = limits.get(job, {})
        if h.get("error"):
            problems.append(f"{job}: {h['error']}")
        if h.get("not_finished"):
            problems.append(f"{job}: not finished ({h['not_finished']})")
        for k, lim in budget.items():
            v = h.get(k)
            if isinstance(v, (int, float)) and v > lim:
                problems.append(f"{job}: {k} {v:g} over its budget {lim:g}")
        for k, floor in (("peak_mb", FLOOR_MB), ("cpu_s", FLOOR_S)):
            bv, hv = b.get(k), h.get(k)
            if isinstance(bv, (int, float)) and isinstance(hv, (int, float)) and hv > bv * (1 + WORSE_BY) \
                    and hv - bv > floor:
                problems.append(f"{job}: {k} {hv:g} is {100 * (hv / bv - 1):.0f}% above the base's {bv:g}")
        rows.append({"job": job, "base": b, "head": h, "budget": budget, "problems": problems})
    return rows


def lines(rows: List[Dict[str, Any]], labels=("main", "branch")) -> List[str]:
    def cell(x: Dict[str, Any]) -> str:
        if not x:
            return "-"
        if x.get("not_measured"):
            return "not measured"
        if x.get("error"):
            return "error"
        kind = f" ({x['kind']})" if x.get("kind") else ""
        stopped = f", not finished: {x['not_finished']}" if x.get("not_finished") else ""
        return f"{x.get('peak_mb', '-')} MB, {x.get('seconds', '-')} s, CPU {x.get('cpu_s', '-')} s{kind}{stopped}"
    out = [f"| job | {labels[0]} | {labels[1]} | budget | verdict |", "|---|---|---|---|---|"]
    for r in rows:
        budget = ", ".join(f"{k} {v:g}" for k, v in r["budget"].items()) or "-"
        verdict = "**FAILS**: " + "; ".join(r["problems"]) if r["problems"] else "ok"
        out.append(f"| `{r['job']}` | {cell(r['base'])} | {cell(r['head'])} | {budget} | {verdict} |")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--now")
    ap.add_argument("--json")
    ap.add_argument("--jobs", default=",".join(JOBS))
    args = ap.parse_args(argv)
    from insight_core.checks.job import scratch_only
    from insight_core.checks.session import copy_now, open_copy
    scratch_only(args.db)
    with open_copy(args.db, writable=True) as conn, conn.cursor() as cur:
        now = copy_now(cur, args.now)
    got = run_all(args.db, now, [j for j in args.jobs.split(",") if j])
    for job, v in got.items():
        print(f"{job:<12} {json.dumps(v, default=str)}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"now": now.isoformat(), "jobs": got}, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
