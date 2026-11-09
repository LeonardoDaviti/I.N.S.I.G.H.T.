"""v10.12.1: a topic track's reading views list only the posts in the track (0145), not every post of its sources.

The owner (2026-11-10): "I added some sources in the track, but it fetches all the posts from those sources into the
track, but I want only posts relevant to that track." While Mark X is on, a track with a description reads, in Stream,
By source, Unread, All, Later, Kept and History, only its items: active sources' posts judged in, posts joined by
INSIGHT, and the posts the owner marked ✓ (`tracks.placed`, places `track` and `joined`). The reader asks with
`all_sources=1` for the folder's every post, as before. A plain folder, or Mark X off: no restriction.

The reader's query stays Mark IX's: this module only names the post ids (FeedScope.only). Read-only.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional

from psycopg import Cursor

from insight_core.db.repo_reader import NOT_ALBUM_PIECE, NOT_STORY_ONLY, FeedScope

IN_TRACK = ("track", "joined")


def enabled() -> bool:
    """Whether Mark X is on (INSIGHT_MARKX, as markx/api.enabled reads it); Mark X's modules are imported only then."""
    return os.getenv("INSIGHT_MARKX", "off").strip().lower() in ("on", "1", "true", "yes")


def track_posts(cur: Cursor, folder_id: Any) -> Optional[List[str]]:
    """The posts in a topic track (newest verdict in, or the owner's ✓; not ✗), or None: a plain folder."""
    from insight_core.markx import tracks
    t = tracks.get(cur, folder_id)
    if not tracks.is_topic(t):
        return None
    return [it["post_id"] for it in tracks.placed(cur, t)["items"] if it["place"] in IN_TRACK]


def restrict(cur: Cursor, scope: FeedScope, *, all_sources: bool = False) -> FeedScope:
    """The scope the reader lists: a topic track's folder scope restricted to its items, while Mark X is on and
    `all_sources` is not asked; any other scope as it came."""
    if all_sources or scope.kind != "folder" or scope.only is not None or not enabled():
        return scope
    ids = track_posts(cur, scope.id)
    return scope if ids is None else FeedScope(scope.kind, scope.id, tuple(ids))


def waiting(cur: Cursor, track: dict) -> int:
    """Its active sources' posts the judge has not answered yet and will (the planner's reading window): the
    reader's quiet "N posts from its sources are still being judged". A row as a feed lists it (no album piece, no
    page shown only inside its story)."""
    from insight_core.markx import tasks, tracks
    days = tasks.reading_window(cur)
    cur.execute(f"""SELECT count(*) FROM posts p
                     WHERE p.source_id IN (SELECT source_id FROM source_folders WHERE folder_id = %(t)s)
                       AND {NOT_ALBUM_PIECE} AND {NOT_STORY_ONLY}
                       AND (%(days)s::int IS NULL OR {tracks._date()} >= now() - make_interval(days => %(days)s))
                       AND NOT EXISTS (SELECT 1 FROM mx_track_items i
                                        WHERE i.track_id = %(t)s AND i.post_id = p.id AND i.verdict IS NOT NULL)""",
                {"t": track["folder_id"], "days": days})
    return int(cur.fetchone()[0])
