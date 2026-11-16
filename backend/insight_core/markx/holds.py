"""The re-ask guard (issue 0210): a planner that adds more of a kind's tasks in a day than the day's allowance has the
rest held, so a backfill or a guide change that re-asks the archive can no longer spend a week's model use in a night.

Measured 2026-11-14: the worker answered ~125,000 questions in one night (about $85 at API prices), mostly a one-off
re-read of long posts' later windows across the archive (entities 61,659 answers, alias 28,096, track 10,900),
while the steady state is about 1,000 new posts a day. Nothing told the owner before it was spent.

The rule (repo.add_task asks `hold_for` before every insert; one decision, one place):
  - A kind's tasks planned today (UTC) count against `reask_guard_per_day` (mx_settings; default PER_DAY, null: no
    guard). New posts' tasks (a post fetched or surfaced in the last tasks.FRESH_HOURS and dated in the last week:
    tasks.fresh_sql, the fresh lane's rule) never count and are never held; nor the embedder's kinds (FREE_KINDS: asked
    on the owner's device, no model cost).
  - Past the allowance, a new task is born held: mx_tasks.hold = '<kind>:<day>' (no row written anywhere else, so a
    planner's long transaction shares no lock with a lease).
  - A held task is leased only after every other task of the kinds a lease asks for (low priority: the excess is
    asked when nothing else waits; nothing is dropped). The owner may stop a hold (none of its tasks is leased) or
    release it (its tasks are leased as any other, and the rest of that kind's excess that day is not held):
    mx_holds, POST /api/markx/holds. /markx shows each hold with its open tasks and their estimated API price
    (`view`).

Counting is per process and cheap: the day's count is read from the database (the (kind, created_at) index) at most
every RECOUNT_SECONDS a kind, and again when the cached count reaches the allowance; between reads each new task adds
one. A post's freshness is read only once a kind is past its allowance.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from psycopg import Cursor

SETTING = "reask_guard_per_day"   # mx_settings: a kind's tasks a day before the rest is held (an int; null: no guard)
PER_DAY = 2000
RECOUNT_SECONDS = 30.0
FREE_KINDS = ("embed", "embed_name")   # the embedder's (llama.cpp on the owner's device): no model cost, never held
STATES = ("low", "stopped", "released")
SAMPLE_TASKS = 300                     # the newest answered tasks of a kind its price per task is read from
PER_MILLION = (0.10, 0.50)             # Haiku 5.5's API price, $ per million tokens in and out (news.HAIKU_PER_MILLION)

KIND_WORDS = {"entities": "entities readings (long posts' windows among them)", "read": "readings",
              "alias": "entity name pairs", "alias2": "entity name pairs (second opinions)", "track": "track verdicts",
              "relate": "post relations", "rename": "rename questions", "pair": "same-story pairs",
              "connect": "story connections", "join": "story joins", "cite": "citation readings",
              "collide": "name collisions", "back": "back-in-the-news questions"}


@dataclass
class _Count:
    base: int                 # the day's counted tasks when last read
    local: int                # new tasks this process added since (not held)
    at: float                 # when read (monotonic)
    limit: Optional[int]      # the allowance then (None: no guard)
    state: str                # the hold's state then (low when no row)
    confirmed: bool = False   # past the allowance on the database's own count (read, not only this process's)


_LOCK = threading.Lock()
_COUNTS: Dict[str, _Count] = {}


def forget() -> None:
    """Drop this process's counts (tests; a setting changed here is read at the next add anyway)."""
    with _LOCK:
        _COUNTS.clear()


def key_of(kind: str, day: date) -> str:
    return f"{kind}:{day.isoformat()}"


def per_day(cur: Cursor) -> Optional[int]:
    from insight_core.markx import repo
    got = repo.get_setting(cur, SETTING, default=PER_DAY)
    try:
        return None if got is None else max(0, int(got))
    except (TypeError, ValueError):
        return PER_DAY


def set_per_day(cur: Cursor, n: Optional[int]) -> Optional[int]:
    from insight_core.markx import repo
    repo.set_setting(cur, SETTING, None if n is None else max(0, int(n)))
    forget()
    return n


def _day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _fresh(alias: str) -> str:
    from insight_core.markx import tasks
    return f"COALESCE({tasks.fresh_sql(alias, '%(fresh)s')}, false)"


def _read(cur: Cursor, kind: str, day: date) -> _Count:
    """The day's count of the kind's tasks that count against the allowance (not held, not a new post's), the
    allowance and the hold's state, from the database."""
    from insight_core.markx import tasks
    limit = per_day(cur)
    key = key_of(kind, day)
    cur.execute("SELECT state FROM mx_holds WHERE key = %s", (key,))
    row = cur.fetchone()
    state = row[0] if row else "low"
    base = 0
    if limit is not None and state != "released":
        cur.execute(f"""SELECT count(*) FROM mx_tasks t
                          LEFT JOIN posts pa ON pa.id = t.a LEFT JOIN posts pb ON pb.id = t.b
                         WHERE t.kind = %(kind)s AND t.created_at >= %(start)s AND t.hold IS NULL
                           AND NOT {_fresh('pa')} AND NOT {_fresh('pb')}""",
                    {"kind": kind, "start": _day_start(day), "fresh": tasks.fresh_since()})
        base = cur.fetchone()[0]
    return _Count(base=base, local=0, at=time.monotonic(), limit=limit, state=state,
                  confirmed=limit is not None and state != "released" and base >= limit)


def _new_post(cur: Cursor, ids: Sequence[Any]) -> bool:
    """Whether one of `ids` is a new post (the fresh lane's rule)."""
    from insight_core.markx import tasks
    ids = [str(i) for i in ids if i is not None]
    if not ids:
        return False
    cur.execute(f"SELECT EXISTS (SELECT 1 FROM posts p WHERE p.id = ANY(%(ids)s::uuid[]) AND {_fresh('p')})",
                {"ids": ids, "fresh": tasks.fresh_since()})
    return bool(cur.fetchone()[0])


def hold_for(cur: Cursor, kind: str, a: Any = None, b: Any = None, *, now: Optional[datetime] = None) -> Optional[str]:
    """The hold a task about to be added is born in, or None (asked in its turn). repo.add_task's decision."""
    if kind in FREE_KINDS:
        return None
    day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    key = key_of(kind, day)
    with _LOCK:
        c = _COUNTS.get(key)
    if c is None or time.monotonic() - c.at > RECOUNT_SECONDS:
        c = _read(cur, kind, day)
        with _LOCK:
            _COUNTS[key] = c
    if c.limit is None or c.state == "released" or c.base + c.local < c.limit:
        return None
    if not c.confirmed:   # reached on this process's own count: read the day's once before holding anything
        c = _read(cur, kind, day)
        with _LOCK:
            _COUNTS[key] = c
        if not c.confirmed:
            return None
    if _new_post(cur, (a, b)):
        return None
    return key


def note_added(kind: str, hold: Optional[str], *, now: Optional[datetime] = None) -> None:
    """A new task was added: it counts against the day's allowance unless held."""
    if hold is not None or kind in FREE_KINDS:
        return
    key = key_of(kind, (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date())
    with _LOCK:
        c = _COUNTS.get(key)
        if c is not None:
            c.local += 1


# ---- the owner's word and the page -------------------------------------------------------------------------------

def set_state(cur: Cursor, key: str, state: str) -> Dict[str, Any]:
    """The owner's word on a hold: low (leased last), stopped (not leased) or released (leased as any task)."""
    if state not in STATES:
        raise ValueError(f"state: one of {', '.join(STATES)}")
    kind, _, day = key.rpartition(":")
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise ValueError("key: <kind>:<YYYY-MM-DD>") from None
    if not kind:
        raise ValueError("key: <kind>:<YYYY-MM-DD>")
    cur.execute("""INSERT INTO mx_holds (key, kind, day, state) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (key) DO UPDATE SET state = EXCLUDED.state, changed_at = now()""", (key, kind, d, state))
    forget()
    return {"key": key, "kind": kind, "day": d.isoformat(), "state": state}


def price_per_task(cur: Cursor, kinds: Sequence[str]) -> Dict[str, Optional[float]]:
    """{kind: the API price of one task, every call it took (Haiku 5.5's list price on the stored tokens)}, from the
    kind's newest SAMPLE_TASKS answered tasks; None when the kind has none."""
    out: Dict[str, Optional[float]] = {}
    for kind in kinds:
        cur.execute("""SELECT count(DISTINCT t.id), COALESCE(sum(c.tokens_in), 0), COALESCE(sum(c.tokens_out), 0)
                         FROM (SELECT id FROM mx_tasks WHERE kind = %s AND status = 'answered'
                                ORDER BY created_at DESC LIMIT %s) t
                         JOIN mx_calls c ON c.task_id = t.id""", (kind, SAMPLE_TASKS))
        n, ti, to = cur.fetchone()
        out[kind] = (int(ti) * PER_MILLION[0] + int(to) * PER_MILLION[1]) / 1e6 / n if n else None
    return out


def view(cur: Cursor) -> Dict[str, Any]:
    """/markx's holds: {per_day, holds: [{key, kind, day, state, open, leased, est_usd, reason}]}: the holds with tasks
    still to answer, newest day first."""
    cur.execute("""SELECT hold, kind, count(*) FILTER (WHERE status = 'open'), count(*) FILTER (WHERE status = 'leased')
                     FROM mx_tasks WHERE hold IS NOT NULL AND status IN ('open', 'leased') GROUP BY 1, 2""")
    rows = cur.fetchall()
    keys = [r[0] for r in rows]
    cur.execute("SELECT key, state FROM mx_holds WHERE key = ANY(%s)", (keys,))
    states = dict(cur.fetchall())
    price = price_per_task(cur, sorted({r[1] for r in rows}))
    limit = per_day(cur)
    holds: List[Dict[str, Any]] = []
    for key, kind, n_open, n_leased in rows:
        each = price.get(kind)
        est = None if each is None else round(each * (n_open + n_leased), 2)
        reason = f"held: {n_open + n_leased:,} {KIND_WORDS.get(kind, kind + ' questions')}"
        if est is not None:
            reason += f", est. ${est:,.2f}"
        holds.append({"key": key, "kind": kind, "day": key.rpartition(":")[2], "state": states.get(key, "low"),
                      "open": n_open, "leased": n_leased, "est_usd": est, "reason": reason})
    holds.sort(key=lambda h: (h["day"], h["kind"]), reverse=True)
    return {"per_day": limit, "default": PER_DAY, "holds": holds}
