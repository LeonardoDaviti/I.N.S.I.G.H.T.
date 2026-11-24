"""The decision run's two entity stages: `entities` (markx/identity.py and its follow-up steps) and `surges`.

Incremental by the database, not process memory: a run links the mentions not linked yet and decides the pairs
answered since the last run; the surges recount only those mentions' days (every day when a merge, undo or split
changed). The first run after NIGHTLY_HOUR, or a forced one, is the full pass (every mention relinked and checked,
every entity pooled, every day recounted), resumable across runs from the counts `unfinished` reads, at night only
(NIGHT_HOURS from NIGHTLY_HOUR, NIGHT_FACTOR x the budget; by day an unfinished pass waits for the next night). The
stage has its own `budget`, spent in order: the run's book, linking the new mentions, the full pass, then the repairs, shown names,
invariants, addresses, renames and handles; each step starts only when its expected seconds (`after_pass`, the last
run's measurement) are left, and what is left is the next run's.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

from insight_core.markx import identity, surges as S

NIGHTLY_HOUR = 4
# v10.47 (0279 A1, owner): the full pass starts and resumes only from NIGHTLY_HOUR for NIGHT_HOURS; by day the runs are
# incremental. Before, an unfinished pass resumed every run all day: on production (11-24) one begun 11-11 was resumed
# by every run with 0 chunks done (the new mentions' linking took the whole 45 s), each run flagged full.
NIGHT_HOURS = 4
NIGHT_FACTOR = 5       # a night run's stage has this times its budget (the jobs' 45 s: 225 s; the run's process dies at 900)
MARGIN = timedelta(minutes=2)


FULL_DEFERRED = "entities_full_deferred"   # mx_settings: {"at": ISO, "why": ...}


def defer_full(cur: Any, why: str) -> None:
    """A run was killed in the entities stage: its full pass is not resumable (rolled back), so it waits for the next
    night instead of killing every run again. Shown on /markx with `why`."""
    from insight_core.markx import repo
    repo.set_setting(cur, FULL_DEFERRED, {"at": datetime.now().astimezone().isoformat(), "why": why})


def full_deferred(cur: Any) -> Optional[Dict[str, Any]]:
    from insight_core.markx import repo
    got = repo.get_setting(cur, FULL_DEFERRED, default=None)
    return got if isinstance(got, dict) and got.get("at") else None


def _night_mark(now: datetime) -> datetime:
    local = now.astimezone()
    mark = local.replace(hour=NIGHTLY_HOUR, minute=0, second=0, microsecond=0)
    if mark > local:
        mark -= timedelta(days=1)
    return mark


def night(now: datetime) -> bool:
    """Within NIGHT_HOURS of tonight's NIGHTLY_HOUR (server time): when the full pass may run."""
    return now.astimezone() - _night_mark(now) < timedelta(hours=NIGHT_HOURS)


def full_due(cur: Any, now: datetime) -> bool:
    """No full pass finished (its last chunk decided) since tonight's NIGHTLY_HOUR, and none deferred since then."""
    mark = _night_mark(now)
    deferred = full_deferred(cur)
    if deferred and datetime.fromisoformat(deferred["at"]) >= mark:
        return False
    cur.execute("""SELECT max((counts->'run'->>'now')::timestamptz) FROM mx_runs
                    WHERE finished_at IS NOT NULL AND counts->'entities'->>'kind' = 'full'
                      AND COALESCE(counts->'entities'->'full'->>'done', 'true') = 'true'""")
    last = cur.fetchone()[0]
    return last is None or last < mark


def _last(cur: Any, part: str) -> Any:
    cur.execute("""SELECT counts->'entities'->%s FROM mx_runs
                    WHERE finished_at IS NOT NULL AND counts ? 'entities'
                    ORDER BY finished_at DESC, started_at DESC LIMIT 1""", (part,))
    row = cur.fetchone()
    return row[0] if row else None


def unfinished(cur: Any) -> Optional[Dict[str, Any]]:
    """The full pass the last finished run left half done ({done: false, phase, after, link_after, ...}), else None
    (phase 'link' resumes at `link_after`, 'pool' at `after`; an old record has `after` only)."""
    got = _last(cur, "full")
    left = isinstance(got, dict) and got.get("done") is False and (got.get("after") or got.get("phase"))
    return got if left else None


def addresses_left(cur: Any) -> Optional[str]:
    """The post the last finished run's addresses sweep stopped after, else None."""
    got = _last(cur, "addresses")
    return got.get("after") if isinstance(got, dict) and got.get("done") is False and got.get("after") else None


def entities(cur: Any, *, ask: Any, now: datetime, run_id: Any, since: Optional[datetime],
             full: Optional[bool] = None, budget: Optional[float] = None,
             chunk: int = identity.SEED_CHUNK, book: Any = None) -> Tuple[Dict[str, Any], Optional[Set[date]]]:
    """(the stage's counts, the days the surges recount: None for every day). `budget`: the stage's own seconds (None:
    no limit); a full pass past it stops after a chunk and the next run resumes it (a forced `full` starts again).
    `book`: the entity book as the run read it, else read here."""
    import time
    left = None if full else unfinished(cur)
    # v10.47 (0279 A1, owner): the full pass runs, and resumes, at night only; by day an unfinished pass waits (its
    # place carried in the counts) and the runs are incremental. At night the stage has NIGHT_FACTOR x its budget.
    dark = night(now)
    whole = bool(full) or dark and (left is not None or full_due(cur, now))
    waits = left if left is not None and not whole else None
    if waits is not None:
        left = None
    if whole and not full and budget is not None:
        budget *= NIGHT_FACTOR
    deadline = None if budget is None else time.monotonic() + budget
    # an answer committed by a transaction that began before the last run's start is read again (jobs.MENTIONS_MARGIN)
    since = since - MARGIN if since is not None else None
    book = identity.run_book(cur) if book is None else book
    # the linking, then the full pass (its chunks sized by the pace the last run measured)
    last_full, last_inc = _last(cur, "full"), _last(cur, "incremental")
    kept = after_pass(cur)   # what the repairs, a shown step and the invariants are expected to take
    rate = last_full.get("rate") if isinstance(last_full, dict) else None
    out = identity.stage(cur, ask=ask, now=now, run_id=run_id, full=whole, since=since,
                         after=left.get("after") if left else None, link_after=left.get("link_after") if left else None,
                         phase=left.get("phase") if left else None, deadline=deadline, chunk=chunk, book=book,
                         seed_rate=rate, keep=sum(kept),
                         collide_rate=last_inc.get("collide_rate") if isinstance(last_inc, dict) else None,
                         part_took=last_inc.get("part_took") if isinstance(last_inc, dict) else None)
    if left and "full" in out:
        out["full"]["started"] = left.get("started")
    elif "full" in out:
        out["full"]["started"] = now.isoformat()
    elif waits is not None:   # by day: the unfinished pass's place, for tonight's run to resume (`unfinished`)
        out["full"] = {**waits, "resumed": False, "chunks": 0, "seconds": 0.0, "waits": "night"}
    linked = out.get("posts_linked", [])   # left in the counts: decide.run hands it to the graph stage
    # then the repairs (resumed where the last run stopped) and the sweeps; each leaves the next its expected time
    out["repair"], book = repairs(cur, book, run_id=run_id, full=whole, last=_last(cur, "repair"),
                                  deadline=None if deadline is None else deadline - kept[1] - kept[2])
    out["shown"] = shown(cur, book, whole=whole, since=since, posts=linked,
                         deadline=None if deadline is None else deadline - kept[2])
    out["invariants"] = invariants(cur, book, deadline=deadline, expect=kept[2])
    sweep = whole and not left
    out["addresses"] = addresses(cur, now=now, since=since, full=sweep, after=None if sweep else addresses_left(cur),
                                 deadline=deadline, also=linked, book=book)
    # every entity once a night (the run that finishes the full pass, within the budget), else the run's posts
    every = whole and bool((out.get("full") or {}).get("done")) and (deadline is None or time.monotonic() < deadline)
    out["renames"] = renames(cur, book, ask=ask, run_id=run_id, full=every, since=since, posts=linked, deadline=deadline)
    # the handle rule over the posts not read by it yet, then the questions the pairs raise
    out["handles"] = handles(cur, book, run_id=run_id, deadline=deadline)
    days = {date.fromisoformat(d) for d in out.pop("days", [])}
    out["days_linked"] = len(days)
    if whole or since is None:
        return out, None
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_entity_redirects WHERE at >= %(s)s OR undone_at >= %(s)s)
                       OR EXISTS (SELECT 1 FROM mx_entity_pins WHERE created_at >= %(s)s OR undone_at >= %(s)s)""",
                {"s": since})
    return out, (None if cur.fetchone()[0] else days)


REPAIR_GUESS = 3.0   # seconds kept for a repair step never measured yet (measured: plan/issues/0221)
SHOWN_GUESS = 2.0    # likewise for a step of the shown names' sweep
INVARIANTS_GUESS = 1.0   # likewise for the invariants


def after_pass(cur: Any) -> Tuple[float, float, float]:
    """Expected seconds of the steps after the full pass, as the last run measured them (else a guess): (the repairs'
    next step, a shown-names step, the invariants). The full pass leaves their sum, and each step the later ones'
    share, or a pass lasting days would starve them for good."""
    from insight_core.markx import entity_repair
    rep, sh, inv = _last(cur, "repair"), _last(cur, "shown"), _last(cur, "invariants")
    r = REPAIR_GUESS
    if isinstance(rep, dict):
        nxt = rep.get("next") if rep.get("done") is False else entity_repair.STEPS[0]
        r = float((rep.get("took") or {}).get(nxt) or REPAIR_GUESS)
    s_ = sh["seconds"] / max(1, sh.get("steps") or 1) if isinstance(sh, dict) and sh.get("seconds") else SHOWN_GUESS
    i = float(inv.get("seconds") or INVARIANTS_GUESS) if isinstance(inv, dict) else INVARIANTS_GUESS
    return r, s_, i


def repairs(cur: Any, book: Any, *, run_id: Any, full: bool, deadline: Optional[float],
            last: Any = None) -> Tuple[Dict[str, Any], Any]:
    """entity_repair.repair in a savepoint: (its counts, the book). A failure is logged in the counts and undone
    (the book read again), never the run's. `last`: the last finished run's counts (the step to resume at)."""
    import logging
    from insight_core.markx import entity_repair
    cur.execute("SAVEPOINT entity_repair")
    try:
        got = entity_repair.repair(cur, book, run_id=run_id, full=full, deadline=deadline,
                                   last=last if isinstance(last, dict) else None)
    except Exception as error:  # noqa: BLE001 - a derived step never stops the run
        cur.execute("ROLLBACK TO SAVEPOINT entity_repair")
        logging.getLogger(__name__).exception("Mark X: the entity repairs failed")
        return {"error": str(error)[:200]}, identity.run_book(cur)
    cur.execute("RELEASE SAVEPOINT entity_repair")
    return got, book


def last_invariants(cur: Any) -> Optional[Dict[str, Any]]:
    """The last finished run's invariants ({family_org: {count, held, clusters}}), for /markx's alarm."""
    cur.execute("""SELECT counts->'entities'->'invariants', finished_at FROM mx_runs
                    WHERE finished_at IS NOT NULL AND counts->'entities' ? 'invariants'
                    ORDER BY finished_at DESC, started_at DESC LIMIT 1""")
    row = cur.fetchone()
    return None if row is None else {**(row[0] or {}), "at": row[1]}


def invariants(cur: Any, book: Any, *, deadline: Optional[float] = None, expect: float = 0.0) -> Dict[str, Any]:
    """What must hold after every run, counted for /markx's alarm: `family_org`, clusters holding a product family
    and an org or person (the owner's own merges are `held`). Read only; a failure is logged in the counts, never the
    run's. Skipped when the `expect`ed seconds are not left before `deadline`."""
    import logging
    import time
    from insight_core.markx import entity_repair
    if deadline is not None and time.monotonic() + expect > deadline:
        return {"skipped": "deadline", **({"seconds": expect} if expect else {})}
    at = time.monotonic()
    cur.execute("SAVEPOINT entity_invariants")
    try:
        got = {"family_org": entity_repair.family_org(book, cur)}
    except Exception as error:  # noqa: BLE001 - a check never stops the run
        cur.execute("ROLLBACK TO SAVEPOINT entity_invariants")
        logging.getLogger(__name__).exception("Mark X: the entity invariants failed")
        return {"error": str(error)[:200]}
    cur.execute("RELEASE SAVEPOINT entity_invariants")
    got["seconds"] = round(time.monotonic() - at, 3)
    return got


def shown(cur: Any, book: Any, *, whole: bool, since: Optional[datetime], posts: Any,
          deadline: Optional[float]) -> Dict[str, Any]:
    """The shown names and types (entity_repair.shown) of the clusters this run touched, or of every cluster on a
    full pass or until a sweep is done (resumed at `after`). In a savepoint: a failure never fails the run."""
    import logging
    from insight_core.markx import entity_repair, schemas
    if not entity_repair.config()["shown"]:
        return {"off": True}
    import time
    guide = schemas.mention_guides()
    last = _last(cur, "shown")
    resume = last.get("after") if isinstance(last, dict) and last.get("done") is False else None
    every = whole or resume is not None or not isinstance(last, dict) or since is None
    if every and deadline is not None:
        # the sweep starts only when a step's seconds (as last measured) are left; else it waits where it is
        step = (last.get("seconds") or 0.0) / max(1, last.get("steps") or 1) if isinstance(last, dict) else 0.0
        if time.monotonic() + step > deadline:
            return {"clusters": 0, "names": 0, "types": 0, "done": False, "steps": 0, "skipped": "deadline",
                    "after": None if whole and resume is None else resume,
                    **({"seconds": last["seconds"]} if isinstance(last, dict) and last.get("seconds") else {})}
    at = time.monotonic()
    cur.execute("SAVEPOINT entity_shown")
    try:
        if every:
            got = entity_repair.shown(cur, book, guide, roots=None, after=None if whole and resume is None else resume,
                                      deadline=deadline)
        else:
            cur.execute("""SELECT DISTINCT entity_id::text FROM mx_mentions_now
                            WHERE post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""", (list(posts),))
            roots = {r[0] for r in cur.fetchall()}
            cur.execute("""SELECT from_id::text, to_id::text FROM mx_entity_redirects
                            WHERE at >= %(s)s OR undone_at >= %(s)s""", {"s": since})
            roots |= {x for row in cur.fetchall() for x in row}
            got = {**entity_repair.shown(cur, book, guide, roots=roots), "done": True}
    except Exception as error:  # noqa: BLE001
        cur.execute("ROLLBACK TO SAVEPOINT entity_shown")
        logging.getLogger(__name__).exception("Mark X: the shown names failed")
        return {"error": str(error)[:200], "done": False, "after": resume}
    cur.execute("RELEASE SAVEPOINT entity_shown")
    got["seconds"] = round(time.monotonic() - at, 3)
    return got


def addresses(cur: Any, *, now: datetime, since: Optional[datetime], full: bool, after: Optional[str] = None,
              deadline: Optional[float] = None, also: Any = (), book: Any = None) -> Dict[str, Any]:
    """The entities' addresses of the posts changed since and the posts the run linked (every post on a full sweep,
    resumed at `after`), no request. Derived and idempotent: a failure is undone, never the run's."""
    import logging
    from insight_core.markx import entity_addresses
    cur.execute("SAVEPOINT entity_addresses")
    try:
        got = entity_addresses.stage(cur, now=now, since=since, full=full, after=after, deadline=deadline, also=also,
                                     book=book)
    except Exception as error:  # noqa: BLE001 - a derived stage never stops the run
        cur.execute("ROLLBACK TO SAVEPOINT entity_addresses")
        logging.getLogger(__name__).exception("Mark X: the entity addresses stage failed")
        return {"error": str(error)[:200]}
    cur.execute("RELEASE SAVEPOINT entity_addresses")
    return got


def handles(cur: Any, book: Any, *, run_id: Any, deadline: Optional[float]) -> Dict[str, Any]:
    """markx/handles.stage in a savepoint: a failure is logged in the counts, never the run's."""
    import logging
    from insight_core.markx import handles as H
    cur.execute("SAVEPOINT entity_handles")
    try:
        got = H.stage(cur, book, run_id=run_id, deadline=deadline)
    except Exception as error:  # noqa: BLE001 - a derived step never stops the run
        cur.execute("ROLLBACK TO SAVEPOINT entity_handles")
        logging.getLogger(__name__).exception("Mark X: the handle step failed")
        return {"error": str(error)[:200]}
    cur.execute("RELEASE SAVEPOINT entity_handles")
    return got


def renames(cur: Any, book: Any, *, ask: Any, run_id: Any, full: bool, since: Optional[datetime],
            posts: Any, deadline: Optional[float] = None) -> Dict[str, Any]:
    """The rename questions (markx/rename.py) of the entities the run's posts name (every entity on the full pass).
    In a savepoint: a failure is logged in the counts, never the run's."""
    import logging
    from insight_core.markx import rename, schemas
    cur.execute("SAVEPOINT entity_renames")
    try:
        seeds: Set[str] = set()
        if not full and posts:
            cur.execute("""SELECT DISTINCT entity_id::text FROM mx_mentions_now
                            WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""",
                        (schemas.mention_guides(), list(posts)))
            seeds = {r[0] for r in cur.fetchall()}
        got = rename.stage(cur, book, ask=ask, run_id=run_id, full=full, since=since, seeds=seeds, deadline=deadline)
    except Exception as error:  # noqa: BLE001 - a derived step never stops the run
        cur.execute("ROLLBACK TO SAVEPOINT entity_renames")
        logging.getLogger(__name__).exception("Mark X: the rename step failed")
        return {"error": str(error)[:200]}
    cur.execute("RELEASE SAVEPOINT entity_renames")
    return got


def surges(cur: Any, *, now: datetime, run_id: Any, days: Optional[Set[date]], since: Optional[datetime],
           window_days: int = 30, book: Any = None) -> Dict[str, Any]:
    return S.stage(cur, now=now, run_id=run_id, days=days, window_days=window_days, book=book)
