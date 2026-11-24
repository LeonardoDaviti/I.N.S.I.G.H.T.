"""Kept pages (mx_kept_pages): a page's answer kept as the bytes the API sends, with the stamp of its inputs.

The owning module says what the page reads (`stamp`, taken in the request's transaction) and builds it; this module
keeps the bytes (`encode`: exactly what the route would answer) and hands them back while the stamp is the same, so a
miss just builds the page (never fails, never stale). Entry points: `kept_or_build` (API side), `get`/`has`/`put`
(jobs side), `newest` (a page too slow for a request), `changes`/`compact` (per-input write counts kept by triggers),
`opened`/`most_opened`. A row's `code` is the code stamp it was built with; `any_code` lets a `shaped` key's page
survive a deploy until rebuilt. v10.47: `behind` sends a page's newest row although its stamp moved (it may lag its
inputs until the jobs' next look) and marks it for the jobs to rebuild (`due_behind`), instead of a build in the
request. Nothing is held in process memory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Callable, List, NamedTuple, Optional, Tuple

_code: Optional[str] = None

NO_RUN = "00000000-0000-0000-0000-000000000000"   # a page kept over no decision run
COMPACT_AT = 200                                   # an input's logged changes folded into its base past this


def encode(content: Any) -> bytes:
    """The bytes a FastAPI route answers for `content` (no response model): jsonable_encoder, then JSONResponse."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    return JSONResponse(content=jsonable_encoder(content)).body


def recut(body: bytes, change: Callable[[Any], Any]) -> bytes:
    """Kept bytes read back, `change`d and re-rendered as JSONResponse does (already plain types: no re-encoding)."""
    from fastapi.responses import JSONResponse
    return JSONResponse(content=change(json.loads(body))).body


def code_stamp() -> str:
    """The sha256 of insight_core's Python sources (not tests), once a process: a row's `code`."""
    global _code
    if _code is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        h = hashlib.sha256()
        for d, dirs, files in os.walk(root):
            dirs[:] = sorted(x for x in dirs if x not in ("tests", "__pycache__", "logs"))
            for name in sorted(files):
                if name.endswith(".py"):
                    path = os.path.join(d, name)
                    with open(path, "rb") as f:
                        h.update(os.path.relpath(path, root).encode() + b"\0" + f.read() + b"\0")
        _code = h.hexdigest()
    return _code


def stamp(*parts: Any) -> str:
    """A page's input stamp: its reads (`parts`, JSON-able), hashed."""
    return hashlib.sha256(json.dumps(list(parts), default=str, separators=(",", ":")).encode()).hexdigest()


def shaped(key: str, shape: str) -> str:
    """A key naming its answer's shape, so a row of another shape is never sent (by `any_code` nor `newest`)."""
    return f"{key}#{shape}"


def changes(cur: Any, inputs: Any) -> List[List[Any]]:
    """[[input, count]]: each kept input's committed writing transactions so far (a stamp part). One indexed read."""
    cur.execute("""SELECT k.input, k.base + (SELECT count(*) FROM kept_input_changes c WHERE c.input = k.input)
                     FROM kept_inputs k WHERE k.input = ANY(%s) ORDER BY k.input""", (sorted(set(inputs)),))
    return [list(r) for r in cur.fetchall()]


def compact(cur: Any, at_least: int = COMPACT_AT) -> int:
    """Jobs process: fold an input's logged changes into its base once it has `at_least`; every count stays the same
    (uncommitted rows stay), so no kept page is lost. Returns the changes folded."""
    cur.execute("SELECT input FROM kept_input_changes GROUP BY input HAVING count(*) >= %s ORDER BY input", (at_least,))
    folded = 0
    for (name,) in cur.fetchall():
        cur.execute("""WITH d AS (DELETE FROM kept_input_changes WHERE input = %(i)s RETURNING 1),
                            n AS (SELECT count(*) AS n FROM d)
                       UPDATE kept_inputs SET base = base + n.n FROM n WHERE input = %(i)s RETURNING n.n""",
                    {"i": name})
        row = cur.fetchone()
        folded += int(row[0]) if row else 0
    return folded


def get(cur: Any, page: str, key: str, run_id: Any, stamp_: str, *, now: Any = None,
        any_code: bool = False) -> Optional[bytes]:
    """The kept bytes of (page, key) over `run_id` with this stamp by the current code (and before its `until`), or
    None. `any_code`: also a row built by other code (the previous deploy's)."""
    if run_id is None:
        return None
    cur.execute("""SELECT body FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id = %s AND stamp = %s
                      AND (until IS NULL OR until > COALESCE(%s, now()))
                      AND (code = %s OR %s)""", (page, key, run_id, stamp_, now, code_stamp(), any_code))
    row = cur.fetchone()
    return bytes(row[0]) if row else None


def has(cur: Any, page: str, key: str, run_id: Any, stamp_: str, *, loose: Optional[str] = None,
        until_after: Any = None) -> bool:
    """Whether (page, key) is kept over `run_id` with this stamp by the current code (True before any run). With
    `loose`, also that loose part; with `until_after`, its bound lies after that moment (else rebuild in time)."""
    if run_id is None:
        return True
    cur.execute("""SELECT 1 FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id = %s AND stamp = %s
                      AND code = %s
                      AND (%s::text IS NULL OR loose IS NOT DISTINCT FROM %s::text)
                      AND (%s::timestamptz IS NULL OR until IS NULL OR until > %s::timestamptz)""",
                (page, key, run_id, stamp_, code_stamp(), loose, loose, until_after, until_after))
    return cur.fetchone() is not None


def newest(cur: Any, page: str, key: str) -> Optional[Tuple[bytes, Any, str]]:
    """(body, built_at, stamp) of (page, key)'s newest kept row, whatever its stamp and code, or None."""
    cur.execute("""SELECT body, built_at, stamp FROM mx_kept_pages WHERE page = %s AND key = %s
                    ORDER BY built_at DESC LIMIT 1""", (page, key))
    row = cur.fetchone()
    return (bytes(row[0]), row[1], row[2]) if row else None


def behind(cur: Any, page: str, key: str, runs: List[Any]) -> Optional[bytes]:
    """v10.47 (0279 B4, owner: serve the kept page, rebuild behind): the body of (page, key)'s newest row built over
    one of `runs` (any code; a `shaped` key keeps the shape), sent although its stamp moved; its `until` is set past
    so the jobs' next look rebuilds it (`due_behind`). None: no such row (the caller builds). In a savepoint: a
    failure to mark answers None (the caller builds)."""
    if not runs:
        return None
    try:
        with cur.connection.transaction():
            cur.execute("""UPDATE mx_kept_pages k SET until = to_timestamp(0)   -- due: the jobs rebuild it
                             FROM (SELECT run_id FROM mx_kept_pages WHERE page = %(p)s AND key = %(k)s
                                      AND run_id = ANY(%(r)s::uuid[]) ORDER BY built_at DESC LIMIT 1) n
                            WHERE k.page = %(p)s AND k.key = %(k)s AND k.run_id = n.run_id
                        RETURNING k.body""", {"p": page, "k": key, "r": [str(r) for r in runs]})
            row = cur.fetchone()
    except Exception:   # noqa: BLE001 - a cache: the caller builds the page
        logging.getLogger(__name__).exception("kept pages: sending %s %s behind failed", page, key)
        return None
    return bytes(row[0]) if row else None


def due_behind(cur: Any, page: str, *, now: Any = None, opened_within: float = 3600.0, limit: int = 50) -> List[str]:
    """The keys of `page` whose newest row's `until` has passed (sent `behind`, or past its clock) and that were opened
    in the last `opened_within` seconds, most recently opened first: what the jobs rebuild. One read."""
    cur.execute("""SELECT k.key FROM (SELECT DISTINCT ON (key) key, until FROM mx_kept_pages WHERE page = %(p)s
                                       ORDER BY key, built_at DESC) k
                     JOIN mx_page_opens o ON o.page = %(p)s AND o.key = split_part(k.key, '#', 1)
                    WHERE k.until IS NOT NULL AND k.until <= COALESCE(%(now)s, now())
                      AND o.last_at >= COALESCE(%(now)s, now()) - make_interval(secs => %(w)s)
                    ORDER BY o.last_at DESC, k.key LIMIT %(n)s""",
                {"p": page, "now": now, "w": opened_within, "n": limit})
    return [k for (k,) in cur.fetchall()]


class Inputs(NamedTuple):
    """What a page reads: `strict` is stamped (sent only while it is the same); `loose` is stored, and the jobs
    process rebuilds when it moved (what the page may lag behind within its `until`)."""
    strict: Any
    loose: Optional[str]


def kept_or_build(cur: Any, page: str, key: str, inputs: Callable[[], Any], build: Callable[[], Any], *,
                  run_id: Any = NO_RUN, until: Any = None, now: Any = None, any_code: bool = False) -> bytes:
    """The API side: the kept bytes while `inputs()`'s stamp is the same, else `build()` encoded, and kept only when
    `inputs()` read again after the build is unchanged. Kept in a savepoint of the caller's transaction; a failure to
    keep still answers. `any_code` as in `get`."""
    def read() -> Tuple[str, Optional[str]]:
        got = inputs()
        if isinstance(got, Inputs):
            return stamp(page, key, got.strict), got.loose
        return stamp(page, key, got), None
    st, loose = read()
    got = get(cur, page, key, run_id, st, now=now, any_code=any_code)
    if got is not None:
        return got
    t0 = time.monotonic()
    body = encode(build())
    seconds = round(time.monotonic() - t0, 3)
    if read()[0] == st:
        try:
            with cur.connection.transaction():
                put(cur, page, key, run_id, st, body, seconds=seconds, until=until, loose=loose)
        except Exception:   # noqa: BLE001 - a cache: the page is answered all the same
            logging.getLogger(__name__).exception("kept pages: keeping %s %s failed", page, key)
    return body


def put(cur: Any, page: str, key: str, run_id: Any, stamp_: str, body: bytes, *, seconds: Optional[float] = None,
        until: Any = None, replace_older: bool = False, loose: Optional[str] = None) -> None:
    """Keep `body` as (page, key)'s answer over `run_id` (one row a run), sent only before `until`; `loose` as in
    `has`. `replace_older`: the key's rows of other runs go."""
    if run_id is None:
        return
    if replace_older:
        cur.execute("DELETE FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id <> %s", (page, key, run_id))
    cur.execute("""INSERT INTO mx_kept_pages (page, key, run_id, stamp, body, bytes, seconds, until, loose, code)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (page, key, run_id) DO UPDATE
                      SET stamp = EXCLUDED.stamp, body = EXCLUDED.body, bytes = EXCLUDED.bytes,
                          seconds = EXCLUDED.seconds, until = EXCLUDED.until, loose = EXCLUDED.loose,
                          code = EXCLUDED.code, built_at = now()""",
                (page, key, run_id, stamp_, body, len(body), seconds, until, loose, code_stamp()))


def prune_runs(cur: Any, page: str, keep: int) -> int:
    """A page's rows of all but its newest `keep` runs (by their newest build) go."""
    cur.execute("""DELETE FROM mx_kept_pages k WHERE k.page = %(page)s AND k.run_id NOT IN (
                       SELECT run_id FROM mx_kept_pages WHERE page = %(page)s
                        GROUP BY run_id ORDER BY max(built_at) DESC LIMIT %(keep)s)""", {"page": page, "keep": keep})
    return cur.rowcount


def prune_rows(cur: Any, page: str, keep: int) -> int:
    """A page's rows but its `keep` newest built go."""
    cur.execute("""DELETE FROM mx_kept_pages k WHERE k.page = %(page)s AND (k.key, k.run_id) NOT IN (
                       SELECT key, run_id FROM mx_kept_pages WHERE page = %(page)s
                        ORDER BY built_at DESC LIMIT %(keep)s)""", {"page": page, "keep": keep})
    return cur.rowcount


def opened(cur: Any, page: str, key: str) -> None:
    """Count one open of (page, key) in a savepoint: a failed count never fails the page."""
    try:
        with cur.connection.transaction():
            cur.execute("""INSERT INTO mx_page_opens AS o (page, key, opens) VALUES (%s, %s, 1)
                           ON CONFLICT (page, key) DO UPDATE SET opens = o.opens + 1, last_at = now()""", (page, key))
    except Exception:   # noqa: BLE001 - a count: the page is answered all the same
        logging.getLogger(__name__).exception("kept pages: counting an open of %s %s failed", page, key)


def most_opened(cur: Any, page: str, n: int, *, days: int = 14) -> List[str]:
    """The `n` keys of `page` most opened among those opened in the last `days`."""
    cur.execute("""SELECT key FROM mx_page_opens WHERE page = %s AND last_at >= now() - make_interval(days => %s)
                    ORDER BY opens DESC, last_at DESC, key LIMIT %s""", (page, days, n))
    return [k for (k,) in cur.fetchall()]


def owner_marks(cur: Any) -> list:
    """A stamp part for the owner's changes between runs (labels, merges and undos, pins, entity sources and handles,
    fixes): counts plus newest times, so a write committing out of order still changes it."""
    cur.execute("""SELECT (SELECT json_build_array(count(*), max(created_at)) FROM mx_labels),
                          (SELECT json_build_array(count(*), count(undone_at), max(at), max(undone_at))
                             FROM mx_entity_redirects),
                          (SELECT json_build_array(count(*), count(undone_at), max(created_at), max(undone_at))
                             FROM mx_entity_pins),
                          (SELECT json_build_array(count(*), max(created_at)) FROM mx_entity_sources),
                          (SELECT json_build_array(count(*), max(created_at)) FROM mx_entity_handles),
                          (SELECT json_build_array(count(*), count(undone_at), max(at), max(undone_at))
                             FROM mx_entity_fixes)""")
    return list(cur.fetchone())
