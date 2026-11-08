"""Put right what the second round of new spheres showed stored wrong (issue 0137), once.

    python -m insight_core.scripts.repair_0137 [--db DSN] [--dry-run] [--collapsed] [--authors] [--telegram]

Collapsed feeds (B1): a feed whose items had no link of their own were all stored as one post at the
feed's own address (a podcast of 282 episodes as 1 post). Each source holding a post at its own address
has its conditional validators dropped, so its next fetch reads the feed in full: the items are stored
again, each at its identity (parsing.item_identity). Nothing is fetched here. The collapsed post is kept,
marked metadata.collapsed_repair_0137 {at, source}: a source is re-read once, a second run finds nothing.

Authors (B7): a stored author line that holds affiliations or identifiers ("Sam B. KimDepartment of
Psychology…", "…https://ror.org/…") is read again by parsing.clean_authors; the old list is kept in
metadata.authors_repair_0137. No request; a second run finds nothing (each is marked).

Telegram dates (A4): a bridge post whose channel is also followed through MTProto (Telegram's own message
date) takes that message's date; the bridge's is kept in metadata.bridge_date, date_from "mtproto". The
measured widening of 0135's message-order cap to every post (interpolating between neighbours) is not
applied: on the 179 posts checked against t.me it made wrong-day posts 18 -> 19..36 (plan/issues/0137-built.md).

The ingestion process runs it at each start (logged); this runs it by hand. Prints the summary as JSON.
No post or row is removed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.ingestion.kinds.parsing import clean_authors, path_segments  # noqa: E402
from insight_core.ingestion.kinds.telegram_rss import TELEGRAM_RSS_HOSTS  # noqa: E402
from insight_core.utils.url_normalization import normalize_url  # noqa: E402

logger = logging.getLogger("insight.repair_0137")

COLLAPSED_MARK = "collapsed_repair_0137"
AUTHORS_MARK = "authors_repair_0137"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- collapsed feeds


def collapsed_posts(cur) -> List[tuple]:
    """(post id, source id, source address) of the unmarked posts stored at their own feed's address (a
    followed page, page watch, posts its own page by design: not one)."""
    cur.execute("""SELECT id, handle_or_url FROM sources WHERE handle_or_url ~* '^https?://' AND platform = 'rss'
                     AND jsonb_typeof(coalesce(settings, '{}'::jsonb) -> 'page_watch') IS DISTINCT FROM 'object'""")
    found: List[tuple] = []
    for source_id, handle in cur.fetchall():
        normalized = normalize_url(handle) or handle
        cur.execute(
            f"""SELECT id FROM posts WHERE source_id = %s AND (url = %s OR normalized_url = %s)
                  AND NOT coalesce(metadata, '{{}}'::jsonb) ? '{COLLAPSED_MARK}'""",
            (source_id, handle, normalized))
        found += [(str(row[0]), str(source_id), handle) for row in cur.fetchall()]
    return found


def repair_collapsed(db_url: str, *, dry_run: bool = False) -> Dict[str, Any]:
    with db.connection(db_url) as conn, conn.cursor() as cur:
        found = collapsed_posts(cur)
        sources = sorted({source for _, source, _ in found})
        if not dry_run:
            for post_id, source_id, handle in found:
                cur.execute("UPDATE posts SET metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb WHERE id = %s",
                            (json.dumps({COLLAPSED_MARK: {"at": _now(), "source": handle}}), post_id))
            for source_id in sources:
                # Its next fetch reads the feed in full (no 304): every item stored at its identity.
                cur.execute("DELETE FROM source_fetch_validators WHERE source_id = %s", (source_id,))
            conn.commit()
            for handle in sorted({handle for _, _, handle in found}):
                logger.info("Collapsed feed: %s is read again in full at its next fetch", handle)
    return {"collapsed_posts": len(found), "sources": len(sources)}


# --------------------------------------------------------------------------- authors


def author_fixes(rows: Sequence[tuple]) -> List[tuple]:
    """(post id, old authors, new authors) for rows (id, metadata) whose author list reads differently."""
    fixes = []
    for post_id, metadata in rows:
        old = (metadata or {}).get("authors")
        if not isinstance(old, list) or AUTHORS_MARK in (metadata or {}):
            continue
        new = clean_authors(old)
        if new != old:
            fixes.append((str(post_id), old, new))
    return fixes


def repair_authors(db_url: str, *, dry_run: bool = False) -> Dict[str, Any]:
    with db.connection(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, metadata FROM posts WHERE jsonb_typeof(metadata -> 'authors') = 'array'")
        fixes = author_fixes(cur.fetchall())
        if not dry_run:
            for post_id, old, new in fixes:
                cur.execute(
                    "UPDATE posts SET metadata = metadata || %s::jsonb, updated_at = now() WHERE id = %s",
                    (json.dumps({"authors": new, AUTHORS_MARK: {"from": old, "at": _now()}}), post_id))
            conn.commit()
    return {"glued_authors": len(fixes)}


# --------------------------------------------------------------------------- Telegram dates


def bridge_channels(cur) -> Dict[str, List[str]]:
    """channel (lower case) -> the ids of the sources reading it through a Telegram RSS bridge."""
    cur.execute("SELECT id, handle_or_url FROM sources WHERE handle_or_url ~* '^https?://[^/]+/rss/[^/?]+'")
    channels: Dict[str, List[str]] = {}
    for source_id, handle in cur.fetchall():
        if (urllib.parse.urlparse(handle or "").hostname or "").lower() in TELEGRAM_RSS_HOSTS:
            channels.setdefault(path_segments(handle)[1].lower(), []).append(str(source_id))
    return channels


def repair_telegram(db_url: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """Bridge posts take the message date of the same message read through MTProto (A4)."""
    moved = 0
    with db.connection(db_url) as conn, conn.cursor() as cur:
        channels = bridge_channels(cur)
        cur.execute("SELECT id, handle_or_url FROM sources WHERE platform = 'telegram' AND handle_or_url !~ '://'")
        both = [(str(sid), channels[handle.lstrip("@").lower()]) for sid, handle in cur.fetchall()
                if handle and handle.lstrip("@").lower() in channels]
        for mtproto, bridges in both:
            cur.execute(
                """SELECT b.id, b.published_at, m.published_at FROM posts b
                     JOIN posts m ON m.source_id = %s AND m.external_id = b.external_id
                    WHERE b.source_id = ANY(%s::uuid[]) AND m.published_at IS NOT NULL
                      AND b.published_at IS DISTINCT FROM m.published_at""", (mtproto, bridges))
            rows = cur.fetchall()
            moved += len(rows)
            if dry_run:
                continue
            for post_id, old, new in rows:
                cur.execute(
                    "UPDATE posts SET published_at = %s, metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,"
                    " updated_at = now() WHERE id = %s",
                    (new, json.dumps({"bridge_date": old.isoformat() if old else None, "date_from": "mtproto"}), post_id))
        if not dry_run:
            conn.commit()
    return {"channels_on_both": len(both), "dated_by_mtproto": moved}


# --------------------------------------------------------------------------- the start


def repair_safely(db_url: str) -> Optional[Dict[str, Any]]:
    """The ingestion process's start: each part, logged; never raises."""
    result: Dict[str, Any] = {}
    for name, part in (("collapsed", repair_collapsed), ("authors", repair_authors), ("telegram", repair_telegram)):
        try:
            result[name] = part(db_url)
        except Exception:  # noqa: BLE001 - the repair is never worth the start
            logger.exception("Repair 0137: %s could not be put right", name)
    if any(any(value for value in part.values()) for part in result.values()):
        logger.info("Repair 0137: %s", result)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--collapsed", action="store_true", help="only the collapsed feeds")
    ap.add_argument("--authors", action="store_true", help="only the author lines")
    ap.add_argument("--telegram", action="store_true", help="only the Telegram dates")
    args = ap.parse_args(argv)
    if not args.db:
        ap.error("--db or DATABASE_URL is needed")
    every = not (args.collapsed or args.authors or args.telegram)
    out: Dict[str, Any] = {}
    if args.collapsed or every:
        out["collapsed"] = repair_collapsed(args.db, dry_run=args.dry_run)
    if args.authors or every:
        out["authors"] = repair_authors(args.db, dry_run=args.dry_run)
    if args.telegram or every:
        out["telegram"] = repair_telegram(args.db, dry_run=args.dry_run)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
