"""v10.12.1: the reader's sidebar count for a track that is a topic (0145). Shadow; 404 when Mark X is off, as every
/api/markx path. Read-only: no row is written.

GET /api/markx/tracks/counts   {by_track: {folder_id: {unread, discover, count, waiting}}}, topic tracks only

A topic track's count is its unread track items (in the track or joined by INSIGHT, whose post is unread; counted as
its Stream lists them, a story with unread posts once, v10.12.1) plus its Discover suggestions (not labelled: a label
moves a suggestion out of Discover). `unread` is also the reader's toolbar count for the track's Stream, which lists
only its items (markx/track_feed); `waiting` its active sources' posts not judged yet ("still being judged"). A plain
folder has no entry; the sidebar keeps its sources' unread count (Mark IX's /api/reader counts) as before.

Its own router, included before tracks_api's so that "counts" is not read as a track id.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from psycopg import Cursor

from insight_core.db.repo_reader import FeedScope, ReaderRepository
from insight_core.markx import track_feed, tracks

router = APIRouter()

IN_TRACK = track_feed.IN_TRACK


def topic_counts(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """{folder_id: {unread, discover, count, waiting}} for every track that is a topic."""
    out: Dict[str, Dict[str, int]] = {}
    reader = ReaderRepository()
    from insight_core.markx import track_kept
    for t in tracks.described(cur):
        kept = track_kept.counts(cur, t, IN_TRACK)   # issue 0195: the kept placement, else placed live
        if kept is not None:
            inside, discover = kept
        else:
            items = tracks.placed(cur, t, shown=False)["items"]   # v10.14: only what a place needs
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
