"""0145 (Stealth v10.11)'s routes: tracks as topics (Shadow; no bearer: the app's own; 404 when Mark X is off, as every
/api/markx path). Included into markx/api.py's router.

GET  /api/markx/tracks                         [{id, name, kind, topic, description, version}] every folder
GET  /api/markx/tracks/suggestions             [{track, track_name, source_id, source, n}] (Discover's line)
GET  /api/markx/tracks/{id}                    the track page (markx/tracks.page)
PUT  /api/markx/tracks/{id}                    {description, excludes} -> the page (an empty description: a folder)
POST /api/markx/tracks/{id}/labels             {post, answer: in | out | undo} -> {id, label}
POST /api/markx/tracks/{id}/subtopics          {action: rename | merge | split | lock | unlock | add, id, ids, name,
                                               definition, keys} -> [sub-topics]
POST /api/markx/tracks/{id}/sources/{source}   make a suggested passive source active -> {added}
"""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_core.markx import tracks

router = APIRouter()


def _id(value: Any) -> str:
    from insight_core.markx.api import _uuid
    u = _uuid(value)
    if u is None:
        raise HTTPException(status_code=404, detail="No such track")
    return str(u)


class TopicIn(BaseModel):
    description: Optional[str] = None
    excludes: Optional[str] = None


class TrackLabelIn(BaseModel):
    post: Any = None
    answer: str
    note: Optional[str] = None


class SubtopicEdit(BaseModel):
    action: str
    id: Optional[str] = None
    ids: List[str] = []
    name: Optional[str] = None
    definition: Optional[str] = None
    keys: List[str] = []


@router.get("/tracks")
def mx_tracks():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return tracks.list_tracks(cur)


@router.get("/tracks/suggestions")
def mx_track_suggestions():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return tracks.suggestions(cur)


@router.get("/tracks/{track_id}")
def mx_track_page(track_id: str):
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            return tracks.page(cur, tid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.put("/tracks/{track_id}")
def mx_track_topic(track_id: str, body: TopicIn):
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            tracks.set_topic(cur, tid, description=body.description, excludes=body.excludes)
            return tracks.page(cur, tid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.post("/tracks/{track_id}/labels")
def mx_track_label(track_id: str, body: TrackLabelIn):
    from insight_core.markx.api import _uuid, transaction
    tid = _id(track_id)
    post = _uuid(body.post)
    if post is None:
        raise HTTPException(status_code=404, detail="No such post")
    with transaction() as cur:
        try:
            return tracks.label(cur, tid, post=str(post), answer=body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track or post")


@router.post("/tracks/{track_id}/subtopics")
def mx_track_subtopics(track_id: str, body: SubtopicEdit):
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            return tracks.edit_subtopics(cur, tid, action=body.action, id=body.id, ids=body.ids, name=body.name,
                                         definition=body.definition, keys=body.keys)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such sub-topic")


@router.post("/tracks/{track_id}/sources/{source_id}")
def mx_track_activate(track_id: str, source_id: str):
    from insight_core.markx.api import _uuid, transaction
    tid = _id(track_id)
    sid = _uuid(source_id)
    if sid is None:
        raise HTTPException(status_code=404, detail="No such source")
    with transaction() as cur:
        try:
            return {"added": tracks.activate(cur, tid, str(sid))}
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track or source")
