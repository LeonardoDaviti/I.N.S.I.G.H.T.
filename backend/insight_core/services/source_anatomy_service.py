"""Source anatomy (issue 0054): for every source at once, how it is read and what it gives.

How it is read comes from what INSIGHT already stores (nothing is fetched): its kind as the
runner resolves it, its address, full text, change watching (0039), conditional fetching
(0044) and its schedule and last fetch, the health row's own fields (so this view and source
health never disagree). What it gives is counted by repo_source_anatomy over the last
WINDOW_DAYS and all time: posts and how many you read, the stories it is in and how many it
reported first (0050), the classics it cited (0051) and the outside links it gave (0050).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Sequence

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.db import database as db
from insight_core.db.repo_fetch_state import FetchStateRepository
from insight_core.db.repo_source_anatomy import SourceAnatomyRepository
from insight_core.ingestion import full_text
from insight_core.services.operations_service import OperationsService, health_row

WINDOW_DAYS = 30

# How a source is read, by the name of the kind that reads it. A site adapter (Gwern,
# LessWrong, ...) is a site reader whatever its name.
KIND_OF = {
    "generic_rss": "feed",
    "substack": "feed",
    "page_watch": "page_watch",
    "telegram_rss": "telegram",
    "telegram_mtproto": "telegram",
    "nitter_rss": "x",
    "reddit_subreddit": "reddit",
    "youtube_channel": "youtube",
    "saved": "saved",
}
# Kinds whose posts are the pages themselves: each page is read whole.
READS_PAGES = ("page_watch", "site_reader", "saved")
_GROUPS = {"posts": ("posts", "read"), "stories": ("stories", "first"), "classics": ("classics",), "links": ("links",)}


def anatomy_kind(kind: Any) -> str:
    name = getattr(kind, "name", "")
    if name in KIND_OF:
        return KIND_OF[name]
    return "site_reader" if isinstance(kind, BaseSourceAdapter) else "feed"


def full_text_mode(kind_key: str, kind: Any, source: Dict[str, Any], pages_read: bool) -> str:
    """on: it reads each post's article page (a feed with full text on that needed it, or a kind
    whose posts are pages); off: a feed with full text switched off; feed: the feed or platform
    carries the whole post (a feed whose posts never needed their page, Telegram, X, Reddit,
    YouTube)."""
    if kind_key in READS_PAGES:
        return "on"
    if getattr(kind, "name", "") == "generic_rss":
        if not full_text.full_page_enabled(source):
            return "off"
        return "on" if pages_read else "feed"
    return "feed"


def anatomy_row(source: Dict[str, Any], kind: Any, health: Dict[str, Any], reading: Dict[str, Any],
                counts: Dict[str, Dict[str, Sequence[int]]]) -> Dict[str, Any]:
    """One row: `source` is the schedule view row, `health` its health row, `reading` its
    repo_source_anatomy.reading() entry, `counts` every column group by source id."""
    sid = source["id"]
    key = anatomy_kind(kind)
    name = str((source.get("settings") or {}).get("display_name") or "").strip()
    recent: Dict[str, int] = {}
    total: Dict[str, int] = {}
    for group, columns in _GROUPS.items():
        values = counts.get(group, {}).get(sid) or (0,) * (2 * len(columns))
        for i, column in enumerate(columns):
            total[column], recent[column] = int(values[2 * i]), int(values[2 * i + 1])
    return {
        "source_id": sid,
        "display_name": name or None,
        "address": source.get("handle_or_url"),
        "platform": source.get("platform"),
        "enabled": health["enabled"],
        "kind": key,
        "full_text": full_text_mode(key, kind, source, bool(reading.get("pages_read"))),
        # null: its kind cannot do it.
        "watch_changes": health["watch_changes"] if health["watchable"] else None,
        "watched_pages": int(reading.get("watched_pages") or 0),
        # 0138 F2: its pages other posts linked that its feed never carried, read once as its posts
        "feed_misses": int(reading.get("feed_misses") or 0),
        "validators": bool(reading.get("validators")) if getattr(kind, "conditional", False) else None,
        "status": health["status"],
        "interval_hours": health["interval_hours"],
        "interval_basis": health["interval_basis"],
        "next_due_at": health["next_due_at"],
        "last_attempt_at": health["last_attempt_at"],
        "last_outcome": health["last_outcome"],
        "last_error": health["last_error"],
        "last_error_at": health["last_error_at"],
        "recent": recent,
        "all": total,
    }


class SourceAnatomyService:
    def __init__(self, db_url: str, operations: OperationsService):
        self.db_url = db_url
        self.operations = operations

    def anatomy(self) -> Dict[str, Any]:
        """{window_days, generated_at, rows}: one row per source (anatomy_row), most posts in the
        window first, then most posts, then by address."""
        ops = self.operations
        now = ops.clock()
        view, reading, counts = self._load(now - timedelta(days=WINDOW_DAYS))
        availability = ops.availability()
        rows = []
        for source in view:
            kind = ops.kinds.resolve(source)
            health = health_row(source, kind, availability, now)
            rows.append(anatomy_row(source, kind, health, reading.get(source["id"], {}), counts))
        rows.sort(key=lambda r: (-r["recent"]["posts"], -r["all"]["posts"], str(r["address"] or "")))
        return {"success": True, "window_days": WINDOW_DAYS, "generated_at": now.isoformat(), "rows": rows}

    def _load(self, since: Any) -> tuple:
        """The schedule view (as source health reads it) and every column group, in one read-only
        transaction (JIT is off for every pooled connection: db.database)."""
        repo = SourceAnatomyRepository
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            view = FetchStateRepository().load_schedule_view(cur)
            reading = repo.reading(cur)
            cur.execute("SELECT source_id::text, count(*) FROM story_originals WHERE kind = 'missed' "
                        "AND source_id IS NOT NULL GROUP BY 1")
            for sid, n in cur.fetchall():   # 0138 F2
                reading.setdefault(sid, {})["feed_misses"] = n
            counts: Dict[str, Dict[str, Sequence[int]]] = {
                "posts": repo.posts(cur, since),
                "stories": repo.stories(cur, since),
                "classics": repo.classics(cur, since),
                "links": repo.links(cur, since),
            }
        return view, reading, counts
