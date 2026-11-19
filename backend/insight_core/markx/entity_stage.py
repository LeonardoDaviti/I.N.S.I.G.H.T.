"""The decision run's two entity stages (issue 0119 A1-A2): `entities` (markx/identity.py) and `surges`
(markx/surges.py), each logged with its duration under the run's limit (0112 Decided 12).

Incremental by the database, not by a process's memory (each job runs in a process of its own): a run links the
mentions not linked yet (entity_id null) and decides the pairs whose answers came since the last run; the surges
recount only the days those mentions fall on, or every day of the window when a merge, an undo or a split changed
since the last run. The first run after NIGHTLY_HOUR (server time), or a forced full run, is the full pass: every
mention relinked and checked against what was stored (`entities.check`), every entity pooled, every day recounted.

0128: **the stage's own budget.** The decision run gives it `budget` seconds (jobs.ENTITY_BUDGET), which don't count
towards the run's limit, so a long full pass can't starve the other stages. The full pass decides its entities in
chunks (identity.SEED_CHUNK) and stops after the chunk that passes the budget; the run's counts keep where
(`entities.full`: done, after), and the next run resumes it there. The night's pass is done only when its last chunk
is (`full_due`).

v10.13.9: **both passes keep to it.** The incremental pass links, pools and decides its mentions in chunks and stops
after the chunk that passes the budget; the mentions it leaves stay unlinked, so the next run takes them. The full pass
relinks in pages of posts (`full.phase` 'link', `link_after`) before its entity chunks (phase 'pool', `after`), and the
addresses' sweep of every post stops likewise (`addresses`: done, after) and goes on in the next runs. The book is read
once a run, for both.

v10.22 (0216): **and they share it.** A run with a full pass half done gives the linking of the new mentions
identity.LINK_SHARE of the budget, the full pass the rest, each at least one step: the server's full pass stood still
for five days, its runs' first linking part taking the whole budget and the pass waiting for the linking to finish.
The linking pools as an incremental pass does (the full pass's chunks ask every seed's nearest names), and the book
holds about half what it did (identity.read_ents, load_book).

v10.23 (0218): **the book is read by need** (identity.RunBook): the entities and aliases the run touches, the mention
counts and versions as a snapshot in the run's transaction, the pool's indexes from one read of every row (none
kept), the repairs' walks row by row. The same rows as with the whole book (the server-sized copy: every mx_* table);
the stage's peak 317 MB instead of 694 MB there (+99 MB above its start, was +344).

v10.24 (0221): **one budget, spent in the order of what matters**, nothing started that the time left can't hold:
the run's book, then the linking of the new mentions (every part until they are linked), then the full pass, then
the identity repairs (markx/entity_repair.py; `repair`, a step at a time, resumed at the step the last run left),
the shown names and types (`shown`: the run's touched clusters, then the sweep over every cluster, resumed by
`after`), the invariants, the addresses, the rename questions, and the handle rule over the posts it has not read
(markx/handles.py; `handles`). Each starts only when the seconds it is expected to take are left; what is left is
the next run's. On the server (v10.23) the repairs ran first in a quarter of the budget and overran it (13.8-17.0 s),
the linking then did 1 part of 13, and the stage ran 55-87 s against its 45.
0164 C: the invariants (`invariants.family_org`: the clusters holding a family and an org, 0 after the repair).

v10.25 (0226): a linking part is expected to take a plain part's seconds (identity.stage `part_took`, the last run's
until this run measures one), not the first part's, which also decides the pairs answered since and the open items'
backlog once a run; the counts say where the linking's seconds went (`incremental.timing`, `reading`,
`part_seconds`, `pairs`).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

from insight_core.markx import identity, surges as S

NIGHTLY_HOUR = 4
MARGIN = timedelta(minutes=2)


FULL_DEFERRED = "entities_full_deferred"   # mx_settings: {"at": ISO, "why": ...} (v10.13.4)


def defer_full(cur: Any, why: str) -> None:
    """v10.13.4: a decision run was killed in the entities stage. Its first full-pass run is not resumable (a killed
    run rolls back, so `unfinished` finds nothing), and the next run would start it again and be killed again, so
    no decision run finishes: the full pass waits for the next night (full_due), and the runs between are
    incremental. Shown on /markx with `why`."""
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


def full_due(cur: Any, now: datetime) -> bool:
    """No full pass finished (its last chunk decided) since the night's NIGHTLY_HOUR, and none deferred since then
    (v10.13.4: a full pass killed tonight waits for the next night)."""
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
    (v10.13.9: phase 'link' with `link_after`, or 'pool' with `after`; a record from before has `after` only)."""
    got = _last(cur, "full")
    left = isinstance(got, dict) and got.get("done") is False and (got.get("after") or got.get("phase"))
    return got if left else None


def addresses_left(cur: Any) -> Optional[str]:
    """v10.13.9: the post the last finished run's addresses sweep stopped after, else None."""
    got = _last(cur, "addresses")
    return got.get("after") if isinstance(got, dict) and got.get("done") is False and got.get("after") else None


def entities(cur: Any, *, ask: Any, now: datetime, run_id: Any, since: Optional[datetime],
             full: Optional[bool] = None, budget: Optional[float] = None,
             chunk: int = identity.SEED_CHUNK, book: Any = None) -> Tuple[Dict[str, Any], Optional[Set[date]]]:
    """(the stage's counts, the days the surges recount: None for every day). `budget`: the stage's own seconds (None:
    no limit); a full pass past it stops after a chunk and the next run resumes it (a forced `full` starts again).
    `book`: the entity book as the run read it (v10.16: decide.run reads it once), else read here."""
    import time
    deadline = None if budget is None else time.monotonic() + budget
    left = None if full else unfinished(cur)
    whole = bool(full) or left is not None or full_due(cur, now)
    # an answer committed by a transaction that began before the last run's start is read again (jobs.MENTIONS_MARGIN)
    since = since - MARGIN if since is not None else None
    book = identity.run_book(cur) if book is None else book   # v10.23 (0218): read by need, once a run (shared)
    # v10.24 (0221): the linking, then the full pass (its chunks sized by the pace the last run measured)
    last_full, last_inc = _last(cur, "full"), _last(cur, "incremental")
    kept = after_pass(cur)   # v10.24: what the repairs, a shown step and the invariants are expected to take
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
    linked = out.get("posts_linked", [])   # v10.25 (0227): left in the counts: decide.run hands it to the graph stage
    # v10.24 (0221): then the repairs (a step at a time, from where the last run's stopped) and the sweeps, with what
    # is left (0164: they ran first, in a quarter of the budget they overran); each leaves the next its expected time
    out["repair"], book = repairs(cur, book, run_id=run_id, full=whole, last=_last(cur, "repair"),
                                  deadline=None if deadline is None else deadline - kept[1] - kept[2])
    out["shown"] = shown(cur, book, whole=whole, since=since, posts=linked,
                         deadline=None if deadline is None else deadline - kept[2])
    out["invariants"] = invariants(cur, book, deadline=deadline, expect=kept[2])
    sweep = whole and not left
    out["addresses"] = addresses(cur, now=now, since=since, full=sweep, after=None if sweep else addresses_left(cur),
                                 deadline=deadline, also=linked, book=book)
    # 0165 B: every thing once a night (the run that finishes the full pass, within the budget), else the run's posts
    every = whole and bool((out.get("full") or {}).get("done")) and (deadline is None or time.monotonic() < deadline)
    out["renames"] = renames(cur, book, ask=ask, run_id=run_id, full=every, since=since, posts=linked, deadline=deadline)
    # 0168: the handle rule over the posts not read by it yet (newest first), then the questions the pairs raise
    out["handles"] = handles(cur, book, run_id=run_id, deadline=deadline)
    days = {date.fromisoformat(d) for d in out.pop("days", [])}
    out["days_linked"] = len(days)
    if whole or since is None:
        return out, None
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_entity_redirects WHERE at >= %(s)s OR undone_at >= %(s)s)
                       OR EXISTS (SELECT 1 FROM mx_entity_pins WHERE created_at >= %(s)s OR undone_at >= %(s)s)""",
                {"s": since})
    return out, (None if cur.fetchone()[0] else days)


REPAIR_GUESS = 3.0   # v10.24 (0221): the seconds kept for a repair step never measured yet (the server's: 1-5 s)
SHOWN_GUESS = 2.0    # v10.24: likewise for a step of the shown names' sweep
INVARIANTS_GUESS = 1.0   # v10.24: likewise for the invariants


def after_pass(cur: Any) -> Tuple[float, float, float]:
    """v10.24 (0221): the seconds the steps after the full pass are expected to take this run, as the last run
    measured them: (the repairs' next step, a step of the shown names' sweep, the invariants), a guess for what was
    never measured. The full pass leaves their sum (identity.stage `keep`), and each step leaves the ones after it
    theirs: a pass half done lasts days on the server and every run is "whole" meanwhile, so the pass would take
    every second the linking leaves, and the repairs would take the sweep's, for good."""
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
    """0164: entity_repair.repair in a savepoint: (its counts, the book). A failure is logged in the counts and
    undone (the book read again), never the run's. `last`: the last finished run's counts of it (v10.24: the step
    to resume at, and each step's seconds)."""
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
    """0164 C: the last finished run's invariants ({family_org: {count, held, clusters}}), for /markx's alarm."""
    cur.execute("""SELECT counts->'entities'->'invariants', finished_at FROM mx_runs
                    WHERE finished_at IS NOT NULL AND counts->'entities' ? 'invariants'
                    ORDER BY finished_at DESC, started_at DESC LIMIT 1""")
    row = cur.fetchone()
    return None if row is None else {**(row[0] or {}), "at": row[1]}


def invariants(cur: Any, book: Any, *, deadline: Optional[float] = None, expect: float = 0.0) -> Dict[str, Any]:
    """0164 C: what must hold after every run, counted, with an alarm on /markx when it doesn't: `family_org`, the
    clusters holding a product family and an org or person (0 after the repair; the owner's own merges are `held`).
    Read only; a failure is logged in the counts, never the run's. v10.22.2: past the stage's `deadline`, not counted
    (`{"skipped": "deadline"}`; the next run counts them). v10.24 (0221): nor when the seconds they took the last
    time (`expect`) are not left."""
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
    """0164: the shown names and types (entity_repair.shown): the clusters this run touched (its posts' entities, the
    merges and undos since), and every cluster on a full pass or until one is done (resumed where the last run's
    stopped, `after`). In a savepoint: a failure is logged in the counts, never the run's."""
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
        # v10.24 (0221): the sweep starts only when a step's seconds are left (the last run's seconds a step, its
        # reads of every cluster's root included); else it waits where it is
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
    """0138 A: the entities' addresses of the posts whose current set came since and of the posts the run linked
    (every post on the full pass's first chunk run, a sweep that resumes `after` where the last run's stopped), no
    request. Derived and idempotent: a failure is logged in the counts and undone, never the run's."""
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
    """0168: markx/handles.stage (the deterministic handle rule over pending posts' full text, then the owner questions
    the "Name (@handle)" pairs raise). In a savepoint: a failure is logged in the counts, never the run's."""
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
    """0165 B: the rename questions (markx/rename.py) of the entities the run's posts name (every thing on the full
    pass), and Haiku's `renamed` answers queued for the owner. In a savepoint: a failure is logged in the counts,
    never the run's."""
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
