"""One-time data repairs that run themselves after a deploy (Stealth v10.43), reported on the Operations page.

A repair is registered here (`REPAIRS`): a name, a version, words for the page, and a function `(db_url, dry_run)`
that calls its script's own code (insight_core/scripts/*: each idempotent, nothing deleted, each change's old value
kept in the row's metadata) and returns {counts: {what: n}, sample: [{label, url?, post_id?, source_id?, track_id?}]}.

**When it runs.** In the jobs (scheduler) process, never in the API: `run_due` after every start (startup_repairs in
scripts/run_scheduler.py, a process of its own) runs each repair whose recorded version is not its version, once; a
run that fails is recorded with its error and tried again at the next start, and never stops the others. The
Operations page asks for a run again or a preview (`request`: data_repairs.requested); the scheduler's loop sees an
ask (`has_requests`, one small query) and runs `job` in a process of its own, which takes each ask (`run_requested`).
A repair runs once at a time (`_claim`: data_repairs.running; a claim older than STALE_HOURS is a dead process's).

**What it keeps** (migration 0177, table data_repairs): the last real run and the last preview, each {at, version,
dry_run, counts, sample, seconds, error?}. A preview is a dry run: every transaction rolled back, nothing changed.
No undo: the scripts record the old values, but none records the whole way back simply (a hidden listing page's rule,
a retitled page's date precision, a moved page's story-only mark), so the way back stays a hand job.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import psycopg

logger = logging.getLogger(__name__)

SAMPLE = 10
STALE_HOURS = 6
MODES = ("run", "preview")


@dataclass(frozen=True)
class Repair:
    name: str
    version: str
    title: str
    about: str
    fn: Callable[[str, bool], Dict[str, Any]]


def _connect(db_url: str) -> psycopg.Connection:
    return psycopg.connect(db_url)


# ---- the registered repairs: each calls its script's code ------------------------------------------------------

def _hide_listing_pages(db_url: str, dry_run: bool) -> Dict[str, Any]:
    from insight_core.scripts import hide_listing_pages
    with _connect(db_url) as conn:
        out = hide_listing_pages.run(conn, dry_run=dry_run, source_id=None)
    counts = {"listing pages": out["posts"], "sources": len(out["sources"])}
    if not dry_run:
        counts["hidden"] = sum(s.get("hidden", 0) for s in out["sources"])
    sample = [{"label": f"{s['name']}: {url}", "url": url, "source_id": s["source"]}
              for s in out["sources"] for url in s["samples"]]
    return {"counts": counts, "sample": sample}


def _repair_track_rows(db_url: str, dry_run: bool) -> Dict[str, Any]:
    from insight_core.markx import api as markx_api
    from insight_core.scripts import repair_track_rows
    ask = markx_api.enabled()   # the catalog posts' questions queued for the worker (mx_tasks); never waited on
    with _connect(db_url) as conn:
        lines = repair_track_rows.run(conn, dry_run=dry_run, ask=ask)
    counts = {k: sum(line[k] for line in lines) for k in ("splits", "split_off", "rejoined", "catalogs", "asked")}
    counts["tracks"] = len(lines)
    sample = [{"label": f"{b['name']}: {b['posts']} posts, {b['groups']} things", "track_id": line["track"]}
              for line in lines for b in line["biggest"]]
    return {"counts": counts, "sample": sample}


def _repair_saved_titles(db_url: str, dry_run: bool) -> Dict[str, Any]:
    from insight_core.scripts import repair_saved_titles
    with _connect(db_url) as conn:
        out = repair_saved_titles.run(conn, dry_run=dry_run, db_url=db_url)
    sample = [{"label": f"“{c['title'][0]}” → “{c['title'][1]}”", "url": c["url"],
               "post_id": c["post_id"]} for c in out["changes"]]
    return {"counts": {"retitled": out["changed"]}, "sample": sample}


def _repair_foreign_pages(db_url: str, dry_run: bool) -> Dict[str, Any]:
    from insight_core.scripts import repair_foreign_pages
    with _connect(db_url) as conn:
        try:
            out = repair_foreign_pages.run(conn, dry_run=dry_run, source_id=None)
        except SystemExit as e:   # its "no Saved source" stop, a failure of this repair only
            raise RuntimeError(str(e)) from None
    sample = [{"label": f"{s['name']}: {url}", "url": url, "source_id": s["source"]}
              for s in out["sources"] for url in s["samples"]]
    return {"counts": {"pages moved to Saved": out["posts"], "sources": len(out["sources"]),
                       "sources skipped (feed unreadable)": len(out["skipped"])}, "sample": sample}


REPAIRS: Sequence[Repair] = (
    Repair("hide_listing_pages", "v10.35", "Hide stored listing pages",
           "Tag, category and author listing pages stored as posts are hidden through their source's item filter.",
           _hide_listing_pages),
    Repair("repair_track_rows", "v10.44", "One row a thing in topic tracks",
           "Track rows that absorbed reports of different things (v10.44: also one name with a disagreeing key, a model "
           "on two machines) are split; catalog posts are asked again.",
           _repair_track_rows),
    Repair("repair_saved_titles", "v10.42", "Title saved pages again",
           "Unreadable saved pages titled by a link's words (“here”) get a real title and their address's date.",
           _repair_saved_titles),
    Repair("repair_foreign_pages", "v10.42", "Move another site's pages out of a source",
           "Pages of another site stored as a source's posts move to Saved (one feed read a source affected).",
           _repair_foreign_pages),
)


def by_name(name: str, repairs: Sequence[Repair] = REPAIRS) -> Optional[Repair]:
    return next((r for r in repairs if r.name == name), None)


# ---- running (the jobs process) --------------------------------------------------------------------------------

def _claim(conn: psycopg.Connection, name: str, mode: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO data_repairs (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
        cur.execute(f"""UPDATE data_repairs SET running = %s, running_since = now(), updated_at = now()
                         WHERE name = %s AND (running IS NULL
                                              OR running_since < now() - interval '{STALE_HOURS} hours')
                        RETURNING name""", (mode, name))
        got = cur.fetchone() is not None
    conn.commit()
    return got


def run_one(db_url: str, repair: Repair, *, dry_run: bool) -> Optional[Dict[str, Any]]:
    """Run `repair` (a dry run: a preview) and record its result; None when it is running already. Never raises."""
    mode = "preview" if dry_run else "run"
    with _connect(db_url) as conn:
        if not _claim(conn, repair.name, mode):
            return None
    started = time.monotonic()
    result: Dict[str, Any] = {"at": datetime.now(timezone.utc).isoformat(), "version": repair.version,
                              "dry_run": dry_run}
    try:
        got = repair.fn(db_url, dry_run)
        result["counts"] = dict(got.get("counts") or {})
        result["sample"] = list(got.get("sample") or [])[:SAMPLE]
    except BaseException as e:  # noqa: BLE001 - one repair's failure is its own (a script's SystemExit too)
        if isinstance(e, KeyboardInterrupt):
            raise
        logger.exception("Data repair %s failed", repair.name)
        result["error"] = f"{type(e).__name__}: {e}"[:500]
    result["seconds"] = round(time.monotonic() - started, 1)
    column = "last_preview" if dry_run else "last_run"
    done = not dry_run and "error" not in result
    with _connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(f"""UPDATE data_repairs SET {column} = %s::jsonb, running = NULL, running_since = NULL,
                               version = CASE WHEN %s THEN %s ELSE version END, updated_at = now()
                         WHERE name = %s""", (json.dumps(result, default=str), done, repair.version, repair.name))
    logger.info("Data repair %s (%s): %s", repair.name, mode, {k: result.get(k) for k in ("counts", "error")})
    return result


def due(cur: Any, repairs: Sequence[Repair] = REPAIRS) -> List[Repair]:
    """The repairs whose version has not run for real yet."""
    cur.execute("SELECT name, version FROM data_repairs")
    ran = dict(cur.fetchall())
    return [r for r in repairs if ran.get(r.name) != r.version]


def run_due(db_url: str, repairs: Sequence[Repair] = REPAIRS) -> Dict[str, Any]:
    """After a start: each repair not yet run at its version, once, one after another. Never raises."""
    out: Dict[str, Any] = {}
    try:
        with _connect(db_url) as conn, conn.cursor() as cur:
            todo = due(cur, repairs)
    except Exception:  # noqa: BLE001 - the repairs are never worth the start
        logger.exception("Data repairs: could not read which are due")
        return out
    for repair in todo:
        out[repair.name] = run_one(db_url, repair, dry_run=False)
    return out


def has_requests(cur: Any) -> bool:
    cur.execute("SELECT EXISTS (SELECT 1 FROM data_repairs WHERE requested IS NOT NULL AND running IS NULL)")
    return bool(cur.fetchone()[0])


def run_requested(db_url: str, repairs: Sequence[Repair] = REPAIRS) -> Dict[str, Any]:
    """The page's asks, each taken once (a repair running now keeps its ask for the next look). Never raises."""
    out: Dict[str, Any] = {}
    try:
        with _connect(db_url) as conn, conn.cursor() as cur:
            cur.execute("""WITH asks AS (SELECT name, requested FROM data_repairs
                                           WHERE requested IS NOT NULL AND running IS NULL FOR UPDATE SKIP LOCKED)
                           UPDATE data_repairs d SET requested = NULL, requested_at = NULL, updated_at = now()
                             FROM asks WHERE d.name = asks.name RETURNING d.name, asks.requested""")
            asks = cur.fetchall()
    except Exception:  # noqa: BLE001
        logger.exception("Data repairs: could not take the asks")
        return out
    for name, mode in asks:
        repair = by_name(name, repairs)
        if repair is None:
            continue
        out[name] = run_one(db_url, repair, dry_run=mode == "preview")
        if out[name] is None:   # it started elsewhere in the meantime: the ask waits for the next look
            try:
                with _connect(db_url) as conn, conn.cursor() as cur:
                    request(cur, name, mode, repairs)
            except Exception:  # noqa: BLE001
                logger.exception("Data repairs: could not keep the ask for %s", name)
    return out


def run_safely(db_url: str) -> Dict[str, Any]:
    """startup_repairs' part: the due repairs, then any ask waiting."""
    return {"due": run_due(db_url), "requested": run_requested(db_url)}


def job(db_url: str) -> None:
    """The scheduler loop's job for the page's asks, in a process of its own (stories_service.in_own_process)."""
    from insight_core.logs.core.logger_config import setup_logging
    setup_logging(debug_mode=False)
    run_requested(db_url)


# ---- the page (the API: reads and asks only) ----------------------------------------------------------------

def request(cur: Any, name: str, mode: str, repairs: Sequence[Repair] = REPAIRS) -> Dict[str, Any]:
    """Ask the jobs process to run `name` again (`run`) or preview it (`preview`). KeyError: no such repair."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    if by_name(name, repairs) is None:
        raise KeyError(name)
    cur.execute("""INSERT INTO data_repairs (name, requested, requested_at) VALUES (%s, %s, now())
                   ON CONFLICT (name) DO UPDATE SET requested = EXCLUDED.requested, requested_at = now(),
                                                    updated_at = now()""", (name, mode))
    return listing(cur, repairs, only=name)[0]


def listing(cur: Any, repairs: Sequence[Repair] = REPAIRS, *, only: Optional[str] = None) -> List[Dict[str, Any]]:
    cur.execute("""SELECT name, version, last_run, last_preview, requested, requested_at, running, running_since
                     FROM data_repairs""")
    rows = {r[0]: r[1:] for r in cur.fetchall()}
    out = []
    for r in repairs:
        if only is not None and r.name != only:
            continue
        version, last_run, last_preview, requested, requested_at, running, running_since = \
            rows.get(r.name, (None,) * 7)
        out.append({"name": r.name, "title": r.title, "about": r.about, "version": r.version,
                    "ran_version": version, "due": version != r.version, "last_run": last_run,
                    "last_preview": last_preview, "requested": requested,
                    "requested_at": requested_at.isoformat() if requested_at else None, "running": running,
                    "running_since": running_since.isoformat() if running_since else None, "undo": False})
    return out
