"""Kept pages (issue 0198): a page's answer kept as the bytes the API sends, with the stamp of the inputs it was built
from (migration 0135, mx_kept_pages).

A page that changes only when a job writes its inputs is built once and sent many times: the owning module says what
the page reads (its `stamp`: a sha256 of a few indexed reads, taken in the request's own transaction) and builds it
(its own function, the one path); this module only keeps the bytes and gives them back while the stamp is the same.
A request whose stamp has no kept row builds the page as before (never fails, never stale): the kept bytes are the
JSON the route would have answered, byte for byte (`encode`: FastAPI's own encoding of a route's dict).

Nothing is held in a process between requests: the bytes live in Postgres (TOAST-compressed) and a request reads one
row by its primary key.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

_code: Optional[str] = None


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


def get(cur: Any, page: str, key: str, run_id: Any, stamp_: str, *, now: Any = None) -> Optional[bytes]:
    """The kept bytes of (page, key) built over `run_id` with this stamp (and, kept with an `until`, `now` before it),
    or None."""
    if run_id is None:
        return None
    cur.execute("""SELECT body FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id = %s AND stamp = %s
                      AND (until IS NULL OR until > COALESCE(%s, now()))""", (page, key, run_id, stamp_, now))
    row = cur.fetchone()
    return bytes(row[0]) if row else None


def has(cur: Any, page: str, key: str, run_id: Any, stamp_: str) -> bool:
    """Whether (page, key) is kept over `run_id` with this stamp (True before any run: nothing to keep)."""
    if run_id is None:
        return True
    cur.execute("SELECT 1 FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id = %s AND stamp = %s",
                (page, key, run_id, stamp_))
    return cur.fetchone() is not None


def put(cur: Any, page: str, key: str, run_id: Any, stamp_: str, body: bytes, *, seconds: Optional[float] = None,
        until: Any = None, replace_older: bool = False) -> None:
    """Keep `body` as (page, key)'s answer over `run_id` (one row a run: a rebuild within the run replaces it), sent
    only before `until` when given. `replace_older`: the key's rows of other runs go (an entity's page keeps one)."""
    if run_id is None:
        return
    if replace_older:
        cur.execute("DELETE FROM mx_kept_pages WHERE page = %s AND key = %s AND run_id <> %s", (page, key, run_id))
    cur.execute("""INSERT INTO mx_kept_pages (page, key, run_id, stamp, body, bytes, seconds, until)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (page, key, run_id) DO UPDATE
                      SET stamp = EXCLUDED.stamp, body = EXCLUDED.body, bytes = EXCLUDED.bytes,
                          seconds = EXCLUDED.seconds, until = EXCLUDED.until, built_at = now()""",
                (page, key, run_id, stamp_, body, len(body), seconds, until))


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
