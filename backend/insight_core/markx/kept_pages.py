"""Kept pages (issue 0198): a page's answer kept as the bytes the API sends, with the stamp of the inputs it was built
from (migration 0136, mx_kept_pages).

A page that changes only when a job writes its inputs is built once and sent many times: the owning module says what
the page reads (its `stamp`: a sha256 of a few indexed reads, taken in the request's own transaction) and builds it
(its own function, the one path); this module only keeps the bytes and gives them back while the stamp is the same.
A request whose stamp has no kept row builds the page as before (never fails, never stale): the kept bytes are the
JSON the route would have answered, byte for byte (`encode`: FastAPI's own encoding of a route's dict).

Nothing is held in a process between requests: the bytes live in Postgres (TOAST-compressed) and a request reads one
row by its primary key.

Issue 0206 (wave 2: the topic tracks' pages, the unread counts, the sources' anatomy, Discover's main source):
  - **A page of no decision run** is kept over `NO_RUN` (its stamp alone says whether it stands).
  - **Kept inputs** (`changes`, migration 0139): the stamp of a page whose inputs many writers write (posts, the read
    state, stories, folders, sources) is a count per input of its committed writing transactions (each logs one row,
    by a trigger; `compact` folds them into a base in the jobs process without changing a count): exact whatever
    order the writes commit in, one indexed read, and no writer ever waits on another for it.
  - **A bound and what a page may lag behind within it**: a row's `until` (as an entity page's clock) and its `loose`
    part (stored, not compared by a request): a page is sent while its stamp is the same and before its `until`; the
    jobs process builds it again when its loose part moved or its `until` comes near (`has(..., loose, until_after)`).
  - **The API keeps what it built** (`kept_or_build`): a request finding nothing kept builds the page as before and
    keeps it when its stamp did not move meanwhile, so the next request (either process) sends it; the jobs process
    builds the pages its views keep before anyone asks.
  - **The newest kept, whatever its stamp** (`newest`): for a page too long to build in a request (Discover's main
    source: 17-20 s on the server), sent with when it was built while the jobs process builds it again.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Callable, List, NamedTuple, Optional, Tuple

_code: Optional[str] = None

NO_RUN = "00000000-0000-0000-0000-000000000000"   # 0206: a page kept over no decision run (its stamp says it all)
COMPACT_AT = 200                                   # 0206: an input's logged changes folded into its base past this


def encode(content: Any) -> bytes:
    """The bytes a FastAPI route answers for `content` (no response model): jsonable_encoder, then JSONResponse."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    return JSONResponse(content=jsonable_encoder(content)).body


def code_stamp() -> str:
    """The sha256 of the backend's Python sources (insight_core, not its tests), read once a process: a kept page of
    other code is never sent, so a deploy builds every kept page again."""
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
    """A page's input stamp: the code's and the page's reads (`parts`, JSON-able), hashed."""
    return hashlib.sha256(json.dumps([code_stamp(), *parts], default=str, separators=(",", ":")).encode()).hexdigest()


def changes(cur: Any, inputs: Any) -> List[List[Any]]:
    """0206: [[input, count]] of these kept inputs (migration 0139: posts, reads, stories, parts, folders, sources),
    each the committed transactions that wrote it so far: a page's stamp part. One indexed read."""
    cur.execute("""SELECT k.input, k.base + (SELECT count(*) FROM kept_input_changes c WHERE c.input = k.input)
                     FROM kept_inputs k WHERE k.input = ANY(%s) ORDER BY k.input""", (sorted(set(inputs)),))
    return [list(r) for r in cur.fetchall()]


def compact(cur: Any, at_least: int = COMPACT_AT) -> int:
    """0206, the jobs process: an input with `at_least` logged changes or more has them folded into its base, in one
    statement an input (the rows it sees deleted and counted into the base, a row still uncommitted stays), so every
    count stays as it was and no kept page is lost to it. The changes folded."""
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


def get(cur: Any, page: str, key: str, run_id: Any, stamp_: str, *, now: Any = None) -> Optional[bytes]:
    """The kept bytes of (page, key) built over `run_id` with this stamp (and, kept with an `until`, `now` before it),
    or None."""
    if run_id is None:
        return None
    cur.execute("""SELECT body FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id = %s AND stamp = %s
                      AND (until IS NULL OR until > COALESCE(%s, now()))""", (page, key, run_id, stamp_, now))
    row = cur.fetchone()
    return bytes(row[0]) if row else None


def has(cur: Any, page: str, key: str, run_id: Any, stamp_: str, *, loose: Optional[str] = None,
        until_after: Any = None) -> bool:
    """Whether (page, key) is kept over `run_id` with this stamp (True before any run: nothing to keep). 0206: with
    `loose`, kept with that loose part too (else it lags: the jobs process builds it again); with `until_after`, sent
    until after that moment (a row whose bound comes first is built again in time)."""
    if run_id is None:
        return True
    cur.execute("""SELECT 1 FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id = %s AND stamp = %s
                      AND (%s::text IS NULL OR loose IS NOT DISTINCT FROM %s::text)
                      AND (%s::timestamptz IS NULL OR until IS NULL OR until > %s::timestamptz)""",
                (page, key, run_id, stamp_, loose, loose, until_after, until_after))
    return cur.fetchone() is not None


def newest(cur: Any, page: str, key: str) -> Optional[Tuple[bytes, Any, str]]:
    """0206: (body, built_at, stamp) of (page, key)'s newest kept row, whatever its stamp, or None. A key that names
    the code (the caller's) never hands another code's page."""
    cur.execute("""SELECT body, built_at, stamp FROM mx_kept_pages WHERE page = %s AND key = %s
                    ORDER BY built_at DESC LIMIT 1""", (page, key))
    row = cur.fetchone()
    return (bytes(row[0]), row[1], row[2]) if row else None


class Inputs(NamedTuple):
    """What a page reads, split (0206): `strict`, stamped (a request sends the kept page only while it is the same),
    and `loose`, stored with the page (the jobs process builds it again when it moved: what the page may lag behind
    within its `until`)."""
    strict: Any
    loose: Optional[str]


def kept_or_build(cur: Any, page: str, key: str, inputs: Callable[[], Any], build: Callable[[], Any], *,
                  run_id: Any = NO_RUN, until: Any = None, now: Any = None) -> bytes:
    """0206, the API's side of a kept page: the bytes kept for (page, key) while the stamp of `inputs()` (the owning
    module's few reads; an `Inputs`: its strict part) is the same and before the row's `until`; else `build()` (the
    route's answer, the page's one path) encoded and kept (with `until` and the loose part read before the build) when
    `inputs()` read again after the build is the same (a page built while an input changed is answered, not kept).
    Kept in a savepoint of the caller's transaction, committed with it; a failure to keep still answers."""
    def read() -> Tuple[str, Optional[str]]:
        got = inputs()
        if isinstance(got, Inputs):
            return stamp(page, key, got.strict), got.loose
        return stamp(page, key, got), None
    st, loose = read()
    got = get(cur, page, key, run_id, st, now=now)
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
    """Keep `body` as (page, key)'s answer over `run_id` (one row a run: a rebuild within the run replaces it), sent
    only before `until` when given; `loose` (0206): what it may lag behind, for the jobs process (`has`).
    `replace_older`: the key's rows of other runs go (an entity's page keeps one)."""
    if run_id is None:
        return
    if replace_older:
        cur.execute("DELETE FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id <> %s", (page, key, run_id))
    cur.execute("""INSERT INTO mx_kept_pages (page, key, run_id, stamp, body, bytes, seconds, until, loose)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (page, key, run_id) DO UPDATE
                      SET stamp = EXCLUDED.stamp, body = EXCLUDED.body, bytes = EXCLUDED.bytes,
                          seconds = EXCLUDED.seconds, until = EXCLUDED.until, loose = EXCLUDED.loose,
                          built_at = now()""",
                (page, key, run_id, stamp_, body, len(body), seconds, until, loose))


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


def owner_marks(cur: Any) -> list:
    """What the owner (or an answer applied at once) changed between decision runs that the pages read: the labels
    (every one-tap answer: News flags, folds, entity answers, ...), the merges and their undoing, the pins, an
    entity's sources and handles, the identity fixes. Each a count and its newest time (and the undone ones'): a
    write that commits after a newer one still changes a count."""
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
