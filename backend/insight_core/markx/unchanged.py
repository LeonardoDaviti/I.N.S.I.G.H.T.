"""A pass that would change nothing is not run again while nothing it reads changed (v10.16, issue 0183).

Mark X's background work runs on a clock: the planners every 5 minutes (jobs.PLAN_EVERY), the decision run at least
hourly. Overnight, with no worker and no upload, the server's planners still read every post, every story and every
track each time (container peaks of 6.6 GiB every 5 minutes, CPU at 100%), to plan nothing.

**One rule for every such pass** (`run`): a pass is declared by a name, the tables it reads and a key (the values it
depends on besides those tables: its settings, its code, the window it computes from the clock). Its inputs' stamp is
the key plus each table's stamp (`table_stamps`: rows, newest row version and a sum of the row versions' hashes, one
aggregate a table in Postgres: any insert, update or delete since changes it; nothing is held in Python).

  - The stamp is taken before the pass and again after it, in the pass's own transaction. When they are equal the pass
    wrote nothing it reads and no other transaction changed any of it meanwhile: the pass was a **no-op on those
    inputs**, and the stamp is kept (mx_inc_state, row `name`).
  - The next pass whose stamp equals the kept one is that same no-op on the same inputs: it is **skipped** (`run`
    returns None). Any change (a post, a task, an answer, a label, a setting, a deploy, the window's day) makes the
    stamp differ and the pass runs in full, exactly as before.

So a skipped pass is, by construction, a pass that would have planned nothing. A pass whose output depends on the clock
beyond what its key names says so with a key of None: it always runs, and nothing is stamped. The
declarations (tables and key) are each pass's own (tasks.background_inputs for the planners).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")
PREFIX = "unchanged:"            # mx_inc_state's rows of the passes (the decision run's own row is 'decide')


def table_stamps(cur: Any, tables: Iterable[str]) -> Dict[str, Tuple]:
    """Each table's rows, newest row version and a sum of its row versions' hashes (transaction and place): any insert,
    update or delete since changes it (a new version has a newer xmin, or, in the same transaction, another ctid)."""
    out = {}
    for t in tables:
        cur.execute(f"SELECT count(*), max(xmin::text::bigint), sum(hashtext(xmin::text || ctid::text)::bigint) FROM {t}")
        out[t] = tuple(None if x is None else int(x) for x in cur.fetchone())
    return out


_code: Dict[Tuple[str, ...], str] = {}


def code_stamp(modules: Sequence[str]) -> str:
    """The sha256 of these modules' source files (a deploy that changes one makes the next pass run)."""
    key = tuple(modules)
    if key not in _code:
        import importlib
        h = hashlib.sha256()
        for name in modules:
            with open(importlib.import_module(name).__file__, "rb") as f:
                h.update(name.encode() + b"\0" + f.read() + b"\0")
        _code[key] = h.hexdigest()
    return _code[key]


def stamp(cur: Any, tables: Sequence[str], key: Any) -> str:
    """The inputs' stamp: the key and each table's stamp, as one sha256."""
    body = json.dumps([key, sorted(table_stamps(cur, sorted(set(tables))).items())], sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def kept(cur: Any, name: str) -> Optional[str]:
    cur.execute("SELECT key FROM mx_inc_state WHERE name = %s", (PREFIX + name,))
    row = cur.fetchone()
    return row[0] if row else None


def _keep(cur: Any, name: str, value: str) -> None:
    cur.execute("""INSERT INTO mx_inc_state (name, key, stamps, saved_at) VALUES (%s, %s, '{}'::jsonb, now())
                   ON CONFLICT (name) DO UPDATE SET key = EXCLUDED.key, saved_at = now()""", (PREFIX + name, value))


def run(cur: Any, name: str, tables: Sequence[str], key: Any, work: Callable[[], T]) -> Optional[T]:
    """`work()` (its result), or None without running it when its inputs are those of its last no-op pass. A pass that
    wrote nothing it reads, while nothing it reads changed, keeps its stamp (on the caller's transaction). A key of
    None: the pass depends on more than it can name (the clock itself) and always runs, unstamped."""
    if key is None:
        return work()
    before = stamp(cur, tables, key)
    if kept(cur, name) == before:
        return None
    out = work()
    if stamp(cur, tables, key) == before:
        _keep(cur, name, before)
    return out
