"""A pass that would change nothing is not run again while nothing it reads changed (issue 0183).

`run(cur, name, tables, key, work)`: a pass is declared by a name, the tables it reads and a key (its settings, code,
the window it computes from the clock). Its stamp is the key plus each table's stamp (`table_stamps`, one aggregate a
table in Postgres; nothing held in Python), taken before and after the pass in its own transaction: equal, the pass
was a no-op on those inputs and the stamp is kept (mx_inc_state); the next pass with that stamp is skipped (None).
Any change makes it differ and the pass runs in full. A key of None: the pass depends on more than it names and
always runs, unstamped.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")
PREFIX = "unchanged:"            # mx_inc_state's rows of the passes (the decision run's own row is 'decide')


# mx_tasks is stamped by its change log (mx_table_changes, appended by triggers), not by scanning the table; pruned
# once a day (`_prune`): a pass after it runs once more
LOGGED = ("mx_tasks",)
PRUNE_AFTER = "1 day"     # the log is pruned when its oldest row is older than this
PRUNE_KEEP = "1 hour"     # ... of everything older than this


def table_stamps(cur: Any, tables: Iterable[str]) -> Dict[str, Tuple]:
    """Each table's stamp: any insert, update or delete since changes it. A table: its rows, newest row version and a
    sum of its row versions' hashes (a new version has a newer xmin, or, in the same transaction, another ctid). A
    LOGGED table: the count, newest and sum of its change log's rows of those kinds (and of a TRUNCATE's '*')."""
    out = {}
    for t in tables:
        name, kinds = of_kinds(t)
        if name in LOGGED:
            cur.execute("""SELECT count(*), max(n), sum(n) FROM mx_table_changes
                            WHERE tbl = %s AND (%s::text[] IS NULL OR kind = ANY(%s::text[]) OR kind = '*')""",
                        (name, list(kinds) or None, list(kinds) or None))
        else:
            cur.execute(f"""SELECT count(*), max(xmin::text::bigint), sum(hashtext(xmin::text || ctid::text)::bigint)
                              FROM {name}{' WHERE kind = ANY(%s)' if kinds else ''}""", (list(kinds),) if kinds else None)
        out[t] = tuple(None if x is None else int(x) for x in cur.fetchone())
    return out


def _prune(cur: Any) -> None:
    """The change log kept small: once its oldest row is PRUNE_AFTER old, every row older than PRUNE_KEEP goes (each
    pass whose kinds lost rows runs once more: a stamp may move for nothing, never stay for a change)."""
    cur.execute(f"""DELETE FROM mx_table_changes WHERE at < now() - interval '{PRUNE_KEEP}'
                     AND (SELECT min(at) FROM mx_table_changes) < now() - interval '{PRUNE_AFTER}'""")


def of_kinds(table: str) -> Tuple[str, Tuple[str, ...]]:
    """A declared input `table[kind,kind]` is that table's rows of those kinds only (its `kind` column), so a pass
    is not woken by another kind's work: `mx_tasks[check]` -> ("mx_tasks", ("check",)); a plain name: every row."""
    if not table.endswith("]") or "[" not in table:
        return table, ()
    name, kinds = table[:-1].split("[", 1)
    return name, tuple(k.strip() for k in kinds.split(",") if k.strip())


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
    if any(of_kinds(t)[0] in LOGGED for t in tables):
        _prune(cur)
    before = stamp(cur, tables, key)
    if kept(cur, name) == before:
        return None
    out = work()
    if stamp(cur, tables, key) == before:
        _keep(cur, name, before)
    return out
