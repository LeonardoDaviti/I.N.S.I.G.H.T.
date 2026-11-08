"""Put right what the new spheres showed stored wrong (issue 0135), once.

    python -m insight_core.scripts.repair_0135 [--db DSN] [--dry-run] [--dates] [--transcripts] [--limit N]

Dates: a Telegram bridge post dated by its edit (posted 2 Sep, shown 20 Sep). Within each bridge source
(telegram_rss.TELEGRAM_RSS_HOSTS, /rss/<channel>) a post dated after a post numbered after it takes the
earliest date of those, as a fetch now reads it (telegram_rss.message_order_dates): `published_at`
moves, the old date is kept in metadata.bridge_date. Nothing is fetched; a second run finds nothing.

Transcripts: a stored video whose transcript is YouTube's machine translation (an automatic track in
another language than the video's: metadata.video_language, else its title's) or raw caption markup
("<?xml…><transcript>"). Each is read again through the normal path (YouTubeService._build_video_post:
the video's own track, as plain text) and its text replaced in place; the track it replaced is kept in
metadata.transcript_repair_0135 {from, chars, at, result}. Once each: a post tried is marked, whatever
came back, except a bot check, which stops the run and leaves the rest for the next one. Within budgets:
at most --limit videos a run (TRANSCRIPTS_PER_START at a start), PACE_S apart, never with yt-dlp off.

The ingestion process runs it at each start (logged; the dates once, the transcripts a budget at a time
until none is left); this runs it by hand. Prints the summary as JSON. No post or row is removed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.ingestion.kinds.telegram_rss import TELEGRAM_RSS_HOSTS  # noqa: E402
from insight_core.services.youtube_service import VTT_RE, base_language, plain_transcript, skip_reason  # noqa: E402
from insight_core.utils.language_detection import detect_language  # noqa: E402

logger = logging.getLogger("insight.repair_0135")

MARK = "transcript_repair_0135"
TRANSCRIPTS_PER_START = 10
PACE_S = 3.0               # yt-dlp's start spacing (kinds/youtube.py's pool)
# Caption markup stored as text: an XML caption document, or WebVTT's marks (VTT_RE).
MARKUP_RE = re.compile(r"^\s*<(?:\?xml|transcript|timedtext|tt\b|text\b)", re.IGNORECASE)


# --------------------------------------------------------------------------- dates


def bridge_sources(cur) -> List[tuple]:
    """(id, handle) of every source read through a Telegram RSS bridge."""
    cur.execute("SELECT id, handle_or_url FROM sources WHERE handle_or_url ~* '^https?://[^/]+/rss/[^/?]+'")
    return [(str(sid), handle) for sid, handle in cur.fetchall()
            if (urllib.parse.urlparse(handle or "").hostname or "").lower() in TELEGRAM_RSS_HOSTS]


def date_fixes(rows: Sequence[tuple]) -> List[tuple]:
    """(post id, old date, new date) for the posts dated after a post numbered after them. rows: (id,
    external_id, published_at) of one source."""
    fixes, floor = [], None
    for post_id, _, published in sorted((r for r in rows if str(r[1] or "").isdigit()),
                                        key=lambda r: int(r[1]), reverse=True):
        if published is None:
            continue
        if floor is not None and published > floor:
            fixes.append((post_id, published, floor))
            continue
        floor = published
    return fixes


def repair_dates(db_url: str, *, dry_run: bool = False) -> Dict[str, Any]:
    found = fixed = 0
    with db.connection(db_url) as conn, conn.cursor() as cur:
        for source_id, handle in bridge_sources(cur):
            cur.execute("SELECT id, external_id, published_at FROM posts WHERE source_id = %s", (source_id,))
            fixes = date_fixes(cur.fetchall())
            found += len(fixes)
            if dry_run or not fixes:
                continue
            for post_id, old, new in fixes:
                cur.execute(
                    "UPDATE posts SET published_at = %s, metadata = coalesce(metadata, '{}'::jsonb) || %s::jsonb,"
                    " updated_at = now() WHERE id = %s",
                    (new, json.dumps({"bridge_date": old.isoformat(), "date_from": "message_order"}), post_id))
            fixed += len(fixes)
            logger.info("Telegram dates: %s: %s posts dated by their edit put back in message order", handle, len(fixes))
        if not dry_run:
            conn.commit()
    return {"edit_dated": found, "fixed": fixed}


# --------------------------------------------------------------------------- transcripts


def needs_transcript(post: Dict[str, Any]) -> Optional[str]:
    """Why the stored transcript is wrong: "markup", "translation", else None."""
    meta = post.get("metadata") or {}
    content = post.get("content") or ""
    if (MARKUP_RE.match(content) or VTT_RE.search(content)) and plain_transcript(content) != content.strip():
        return "markup"
    source = str(meta.get("transcript_source") or "")
    if not source.startswith("automatic_captions:"):
        return None
    track = base_language(source.split(":", 1)[1])
    video = base_language(meta.get("video_language"))
    if not video:
        # Only a title's script tells its language: the stopword guess reads English titles as Portuguese
        # (44 of 54 stored "translations" on the server's copy were English videos so misread).
        detected = detect_language(post.get("title") or "")
        script = (detected.get("signals") or {}).get("script")
        video = base_language(str(detected["language_code"])) if script in ("cyrillic", "georgian") else ""
    return "translation" if video and track and video != track else None


def transcript_candidates(cur, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    cur.execute(
        f"""SELECT p.id, p.external_id, p.url, p.title, p.content, p.metadata, s.handle_or_url
              FROM posts p JOIN sources s ON s.id = p.source_id
             WHERE (s.platform = 'youtube' OR p.metadata ->> 'kind' = 'youtube_video')
               AND NOT coalesce(p.metadata, '{{}}'::jsonb) ? '{MARK}'
               AND (p.metadata ->> 'transcript_source' LIKE 'automatic_captions:%%' OR p.content ~ '^\\s*<')
             ORDER BY p.published_at DESC NULLS LAST, p.id""")
    posts = [{"id": str(r[0]), "external_id": r[1], "url": r[2], "title": r[3], "content": r[4],
              "metadata": r[5] or {}, "handle": r[6]} for r in cur.fetchall()]
    due = [{**post, "why": why} for post in posts if (why := needs_transcript(post))]
    return due[:limit] if limit is not None else due


def repair_transcripts(db_url: str, *, dry_run: bool = False, limit: Optional[int] = None,
                       service: Any = None, sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    from insight_core.db.repo_posts import PostsRepository

    with db.connection(db_url) as conn, conn.cursor() as cur:
        due = transcript_candidates(cur)
    summary: Dict[str, Any] = {"due": len(due), "markup": sum(p["why"] == "markup" for p in due),
                               "translation": sum(p["why"] == "translation" for p in due), "replaced": 0,
                               "unchanged": 0, "failed": 0, "stopped": None}
    if dry_run or not due:
        return summary
    if service is None:
        from insight_core.services.youtube_service import YouTubeService
        service = YouTubeService(db_url)
    posts = PostsRepository(db_url)
    for index, post in enumerate(due[:limit] if limit is not None else due):
        if index:
            sleep(PACE_S)
        mark = {"from": (post["metadata"] or {}).get("transcript_source"), "why": post["why"],
                "chars": len(post["content"] or ""), "at": datetime.now(timezone.utc).isoformat()}
        try:
            fresh = service._build_video_post(post["external_id"] or post["url"], post["handle"])
        except Exception as exc:  # noqa: BLE001 - one video never stops the others, a bot check does
            if skip_reason(exc) == "the bot check":
                summary["stopped"] = "the bot check"
                logger.warning("Transcripts: YouTube asks to confirm we're not a bot; the rest wait for the next run")
                break
            summary["failed"] += 1
            fresh = None
            logger.info("Transcripts: %s could not be read again (%s)", post["url"], str(exc)[:200])
        with db.connection(db_url) as conn, conn.cursor() as cur:
            meta = (fresh or {}).get("metadata") or {}
            # Another track, or the same one now read as plain text (it was stored as markup).
            if (fresh and meta.get("transcript_source") and fresh.get("content")
                    and (meta["transcript_source"] != mark["from"] or post["why"] == "markup")):
                posts.save_full_text(cur, post["id"], {**fresh, "metadata": {**meta, MARK: {**mark, "result": "replaced"}}})
                summary["replaced"] += 1
            else:
                result = "failed" if fresh is None else "unchanged"
                summary["unchanged"] += fresh is not None
                posts.merge_metadata(cur, post["id"], {MARK: {**mark, "result": result}})
            conn.commit()
    logger.info("Transcripts: %s", summary)
    return summary


# --------------------------------------------------------------------------- the start


def repair_safely(db_url: str) -> Optional[Dict[str, Any]]:
    """The ingestion process's start: the dates, then a budget of transcripts (yt-dlp on); logged, never raises."""
    result: Dict[str, Any] = {}
    try:
        result["dates"] = repair_dates(db_url)
        if result["dates"]["fixed"]:
            logger.info("Telegram dates: %s posts put back in message order", result["dates"]["fixed"])
    except Exception:  # noqa: BLE001 - the repair is never worth the start
        logger.exception("Telegram dates: could not be put back in message order")
    if str(os.getenv("INSIGHT_YTDLP_ENABLED", "1")).strip().lower() in ("0", "false", "no", "off"):
        return result
    try:
        result["transcripts"] = repair_transcripts(db_url, limit=TRANSCRIPTS_PER_START)
    except Exception:  # noqa: BLE001
        logger.exception("Transcripts: could not be read again")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dates", action="store_true", help="only the Telegram dates")
    ap.add_argument("--transcripts", action="store_true", help="only the transcripts")
    ap.add_argument("--limit", type=int, default=None, help="at most this many videos read again")
    args = ap.parse_args(argv)
    if not args.db:
        ap.error("--db or DATABASE_URL is needed")
    both = not (args.dates or args.transcripts)
    out: Dict[str, Any] = {}
    if args.dates or both:
        out["dates"] = repair_dates(args.db, dry_run=args.dry_run)
    if args.transcripts or both:
        out["transcripts"] = repair_transcripts(args.db, dry_run=args.dry_run, limit=args.limit)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
