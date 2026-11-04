"""The stored parts of each post (issue 0076, migration 0060): written here, from the one parser
(utils/post_parser.py), at save and by the catch-up; read by every page and the story job through
the SQL and the helpers below, never by parsing again.

The catch-up (`catch_up`, in a process of its own: StoriesService.recompute runs it first) parses
the posts with no row (the first start after 0060: every post), then, when the parser's stamp
changed, every post again, a batch a transaction, writing only the rows whose digest changed.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.db import database as db
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.utils.post_parts import Body, shown

logger = logging.getLogger(__name__)

SETTINGS_KEY = "post_parts"   # {"stamp": the parser's stamp every row is at, "redo": {"stamp", "after"}}
BATCH = 500                   # posts a transaction (their bodies are read whole); not measured

# The title every place shows (post_parser: post_fields.post_title at save), one column; the stored
# title until the post is parsed (a post saved by a path that doesn't parse, until the catch-up does).
def shown_title(p: str = "p") -> str:
    return f"COALESCE((SELECT pp.title FROM post_parts pp WHERE pp.post_id = {p}.id), {p}.title)"


PARTS_JOIN = "LEFT JOIN post_parts pp ON pp.post_id = p.id"
# A body's columns, in Body's order, for the text and the HTML (`body`).
BODY_COLUMNS = ("pp.text_cut, pp.text_decode_entities, pp.text_cut_leaves_break, pp.text_copy, "
                "pp.html_cut, pp.html_decode_entities, pp.html_cut_leaves_break, pp.html_copy")


def body(raw: Optional[str], columns: Sequence[Any]) -> Optional[str]:
    """A shown body from its raw column and its four stored columns (BODY_COLUMNS' text or HTML half)."""
    cut, decode, brk, copy = columns
    return shown(raw, Body(cut=cut, decode_entities=bool(decode), cut_leaves_break=bool(brk), copy=copy))


_COLUMNS = ("post_id", "title", "title_from", "lead", "text_cut", "text_decode_entities", "text_cut_leaves_break",
            "text_copy", "html_cut", "html_decode_entities", "html_cut_leaves_break", "html_copy", "quoted",
            "quote_only", "folded", "counts", "link_target", "link_kind", "reply_to", "author", "words",
            "quoted_words", "warnings", "parse_stamp", "digest")
_UPSERT = (f"INSERT INTO post_parts ({', '.join(_COLUMNS)}) VALUES ({', '.join(['%s'] * len(_COLUMNS))}) "
           f"ON CONFLICT (post_id) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in _COLUMNS[1:])}, parsed_at = now()")


def _row(post_id: Any, parts: Any, digest: str, stamp: str) -> Tuple[Any, ...]:
    jsonb = lambda v: json.dumps(v, ensure_ascii=False) if v else None   # noqa: E731
    return (post_id, parts.title, parts.title_from, parts.lead,
            parts.text.cut, parts.text.decode_entities, parts.text.cut_leaves_break, parts.text.copy,
            parts.html.cut, parts.html.decode_entities, parts.html.cut_leaves_break, parts.html.copy,
            parts.quoted, parts.quote_only, jsonb(parts.folded), jsonb(parts.counts), parts.link_target, parts.link_kind,
            parts.reply_to, parts.author, parts.words, jsonb(parts.quoted_words), parts.warnings or None, stamp, digest)


class PostPartsRepository:
    @staticmethod
    def write(cur: Cursor, ids: Iterable[str]) -> int:
        """Parse these stored posts and write the rows that changed (a new post's always). Returns how many.
        A post the parser can't read is logged and keeps its raw title and bodies, so it isn't tried
        again until its stamp changes."""
        from insight_core.utils.post_parser import Parts, parse, parse_stamp

        ids = list(ids)
        if not ids:
            return 0
        stamp = parse_stamp()
        cur.execute("""SELECT p.id, p.title, p.content, p.content_html, p.url, pp.digest
                       FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id WHERE p.id = ANY(%s::uuid[])""", (ids,))
        rows = []
        for post_id, title, content, html, url, old in cur.fetchall():
            try:
                parts = parse(title, content, html, url)
            except Exception as e:  # noqa: BLE001 - one post the rules can't read costs only its parts
                logger.exception("Post parts: post %s could not be parsed", post_id)
                parts = Parts(title=title or "", title_from="feed field", lead="", warnings=[f"parse failed: {type(e).__name__}"])
            digest = parts.digest()
            if digest != old:
                rows.append(_row(post_id, parts, digest, stamp))
        if rows:
            cur.executemany(_UPSERT, rows)
        return len(rows)

    @staticmethod
    def unparsed(cur: Cursor, limit: int) -> List[str]:
        """Posts with no parts, the newest first (the first start: the feed's top reads its titles first)."""
        cur.execute("SELECT p.id FROM posts p WHERE NOT EXISTS (SELECT 1 FROM post_parts pp WHERE pp.post_id = p.id) "
                    "ORDER BY p.fetched_at DESC, p.id LIMIT %s", (limit,))
        return [str(r[0]) for r in cur.fetchall()]


def catch_up(db_url: str) -> Dict[str, int]:
    """Parse the posts with no parts, then every post again if the parser's stamp changed (resuming
    where a stopped run left off), a batch a transaction. Returns {"parsed", "written"}."""
    from insight_core.utils.post_parser import parse_stamp

    stamp = parse_stamp()
    parsed = written = 0
    while True:
        with db.transaction(db_url) as cur:
            ids = PostPartsRepository.unparsed(cur, BATCH)
            written += PostPartsRepository.write(cur, ids)
        parsed += len(ids)
        if len(ids) < BATCH:
            break
    with db.transaction(db_url) as cur:
        state = (SystemSettingsRepository.get(cur, SETTINGS_KEY) or ({}, None))[0] or {}
        if not state:   # the first parse: every row is at this stamp
            SystemSettingsRepository.upsert(cur, SETTINGS_KEY, {"stamp": stamp})
            return {"parsed": parsed, "written": written}
    if state.get("stamp") == stamp:
        return {"parsed": parsed, "written": written}
    after = (state.get("redo") or {}).get("after") if (state.get("redo") or {}).get("stamp") == stamp else None
    while True:
        with db.transaction(db_url) as cur:
            cur.execute("SELECT id FROM posts WHERE %(after)s::uuid IS NULL OR id > %(after)s::uuid ORDER BY id LIMIT %(n)s",
                        {"after": after, "n": BATCH})
            ids = [str(r[0]) for r in cur.fetchall()]
            written += PostPartsRepository.write(cur, ids)
            parsed += len(ids)
            after = ids[-1] if ids else after
            done = len(ids) < BATCH
            SystemSettingsRepository.upsert(cur, SETTINGS_KEY,
                                            {"stamp": stamp} if done else {**state, "redo": {"stamp": stamp, "after": after}})
        if done:
            return {"parsed": parsed, "written": written}


def catch_up_safely(db_url: str) -> Optional[Dict[str, int]]:
    """The catch-up, logged and never raising: the pages read the stored title until a post is parsed."""
    try:
        done = catch_up(db_url)
        if done["parsed"]:
            logger.info("Post parts: %s", done)
        return done
    except Exception:  # noqa: BLE001 - derived; the next run parses what is left
        logger.exception("Post parts: the catch-up failed")
        return None


__all__ = ["PostPartsRepository", "catch_up", "catch_up_safely", "shown_title", "body", "PARTS_JOIN", "BODY_COLUMNS"]
