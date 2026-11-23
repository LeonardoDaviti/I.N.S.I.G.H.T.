"""The reader's sidebar count for a topic track. Read only; 404 when Mark X is off, as every /api/markx path.

GET /api/markx/tracks/counts   {by_track: {folder_id: {unread, discover, count, waiting}}}, topic tracks only

A topic track's count is its unread track items (counted as its Stream lists them, a story with unread posts once)
plus its Discover suggestions not labelled. `unread` is also the toolbar count for the track's Stream; `waiting` its
active sources' posts not judged yet. A plain folder has no entry (the sidebar keeps Mark IX's counts).

Its own router, included before tracks_api's so that "counts" is not read as a track id.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from psycopg import Cursor

from insight_core.db.repo_reader import FeedScope, ReaderRepository
from insight_core.markx import track_brief, track_feed, track_things, tracks

router = APIRouter()

IN_TRACK = track_feed.IN_TRACK


def topic_counts(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """{folder_id: {unread, discover, count, waiting}} for every track that is a topic."""
    out: Dict[str, Dict[str, int]] = {}
    reader = ReaderRepository()
    from insight_core.markx import track_kept
    for t in tracks.described(cur):
        kept = track_kept.counts(cur, t, IN_TRACK)   # the kept placement, else placed live
        if kept is not None:
            inside, discover = kept
        else:
            items = tracks.placed(cur, t, shown=False)["items"]   # only what a place needs
            inside = [it["post_id"] for it in items if it["place"] in IN_TRACK]
            discover = sum(1 for it in items if it["place"] == "discover")
        unread = reader.scope_unread(cur, FeedScope("folder", t["folder_id"], tuple(inside))) if inside else 0
        out[t["folder_id"]] = {"unread": unread, "discover": discover, "count": unread + discover,
                               "waiting": track_feed.waiting(cur, t)}
    return out


@router.get("/tracks/counts")
def mx_track_counts() -> Dict[str, Any]:
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return {"by_track": topic_counts(cur)}
