"""v10.12.1: the reader's sidebar count for a track that is a topic (0145). Shadow; 404 when Mark X is off, as every
/api/markx path. Read-only: no row is written.

GET /api/markx/tracks/counts   {by_track: {folder_id: {unread, discover, count}}}, topic tracks only

A topic track's count is its unread track items (in the track or joined by INSIGHT, whose post is unread) plus its
Discover suggestions (not labelled: a label moves a suggestion out of Discover). A plain folder has no entry; the
sidebar keeps its sources' unread count (Mark IX's /api/reader counts) as before.

Its own router, included before tracks_api's so that "counts" is not read as a track id.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from psycopg import Cursor

from insight_core.db.repo_reader import UNREAD_SQL
from insight_core.markx import tracks

router = APIRouter()

IN_TRACK = ("track", "joined")


def topic_counts(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """{folder_id: {unread, discover, count}} for every track that is a topic."""
    out: Dict[str, Dict[str, int]] = {}
    for t in tracks.described(cur):
        items = tracks.placed(cur, t)["items"]
        inside = [it["post_id"] for it in items if it["place"] in IN_TRACK]
        unread = 0
        if inside:
            cur.execute(f"SELECT count(*) FROM posts p WHERE p.id = ANY(%s::uuid[]) AND {UNREAD_SQL}", (inside,))
            unread = int(cur.fetchone()[0])
        discover = sum(1 for it in items if it["place"] == "discover")
        out[t["folder_id"]] = {"unread": unread, "discover": discover, "count": unread + discover}
    return out


@router.get("/tracks/counts")
def mx_track_counts() -> Dict[str, Any]:
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return {"by_track": topic_counts(cur)}
