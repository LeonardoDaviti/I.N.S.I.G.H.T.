"""The routes of topic tracks (markx/tracks.py, track_things.py, track_brief.py), included into markx/api.py's router:
no bearer (the app's own), 404 when Mark X is off. Pages, suggestions and weekly issues are sent kept (built by the
jobs process); every item a track page shows carries its `byline`.
"""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from insight_core.markx import track_brief, track_fields, track_subtopics, track_things, track_why, tracks

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
    """Kept (tracks.kept_page), built by the jobs process."""
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return Response(tracks.kept_page(cur, None), media_type="application/json")


@router.get("/tracks/{track_id}")
def mx_track_page(track_id: str):
    """Kept (tracks.kept_page), built by the jobs process; built here only when the owner changed what it shows since
    (then kept) or nothing is kept yet."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            return Response(tracks.kept_page(cur, tid), media_type="application/json")
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.get("/tracks/{track_id}/why")
def mx_track_why(track_id: str, post: str = ""):
    """Where one post stands in the track and why: read only, stored rows."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        pid = track_why.find_post(cur, post)
        if pid is None:
            raise HTTPException(status_code=404, detail="No such post")
        try:
            return track_why.why(cur, tid, pid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.put("/tracks/{track_id}")
def mx_track_topic(track_id: str, body: TopicIn):
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            tracks.set_topic(cur, tid, description=body.description, excludes=body.excludes)
            return tracks.shown_page(cur, tid)
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


class LookIn(BaseModel):
    subtopic: Optional[str] = None


@router.get("/tracks/{track_id}/seen")
def mx_track_seen(track_id: str):
    """The reader's last looks at the track and its sub-topics (the page counts what is new since)."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        return track_subtopics.seen(cur, tid)


@router.post("/tracks/{track_id}/seen")
def mx_track_look(track_id: str, body: LookIn):
    """The reader looked at the track (or one sub-topic) now: {before, now}."""
    from insight_core.markx.api import _uuid, transaction
    tid = _id(track_id)
    sub = None
    if body.subtopic:
        u = _uuid(body.subtopic)
        if u is None:
            raise HTTPException(status_code=404, detail="No such sub-topic")
        sub = str(u)
    with transaction() as cur:
        try:
            return track_subtopics.look(cur, tid, sub)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track or sub-topic")


# ---- the general track briefer (markx/track_things.py, markx/track_brief.py; entity_bands.json tracks.briefs) -------

class SchemaIn(BaseModel):
    kinds: List[Any] = []


@router.get("/tracks/{track_id}/schema")
def mx_track_schema(track_id: str):
    """The track's kinds and fields (its newest version): {on, version, by, track_version, stale, schema}."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            return track_things.schema_view(cur, tid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.put("/tracks/{track_id}/schema")
def mx_track_schema_edit(track_id: str, body: SchemaIn):
    """The owner's kinds and fields, a new version (the general practice kind is added by code); its posts are read
    again under it."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            return track_things.set_schema(cur, tid, body.kinds)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


class DismissIn(BaseModel):
    kind: str
    name: str


@router.get("/tracks/{track_id}/schema/suggestions")
def mx_track_field_suggestions(track_id: str):
    """The fields INSIGHT suggests the track's records add (track_fields; never applied)."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            return track_fields.suggestions(cur, tid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.post("/tracks/{track_id}/schema/suggestions/dismiss")
def mx_track_field_dismiss(track_id: str, body: DismissIn):
    """The owner dismissed a suggested field (never suggested again): the suggestions left."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            return track_fields.dismiss(cur, tid, body.kind, body.name)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.get("/tracks/{track_id}/brief")
def mx_track_brief(track_id: str, week: Optional[str] = None, since: Optional[str] = None):
    """?week=<a day of it> the week's issue (kept, built by the jobs process); ?since=seen (the reader's last look) or
    ?since=<ISO time> the quick look; neither: the quick look since the last look."""
    from datetime import datetime
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            if week:
                try:
                    w = track_brief.parse_week(week)
                except ValueError:
                    raise HTTPException(status_code=400, detail="week: a date, YYYY-MM-DD")
                return Response(track_brief.kept_issue(cur, tid, w), media_type="application/json")
            at = None
            if since and since != "seen":
                try:
                    at = datetime.fromisoformat(since.replace("Z", "+00:00"))
                except ValueError:
                    raise HTTPException(status_code=400, detail="since: seen or an ISO time")
                if at.tzinfo is None:
                    raise HTTPException(status_code=400, detail="since: an ISO time with its zone")
            else:
                look = track_subtopics.seen(cur, tid)["track"]
                at = datetime.fromisoformat(look) if look else None
            return track_brief.quick_look(cur, tid, at)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


@router.get("/tracks/{track_id}/things")
def mx_track_things(track_id: str, request: Request, kind: str = "", limit: int = 100, offset: int = 0):
    """A kind's table, filtered by its own fields (<number|money field>.min / .max, <money field>.currency,
    <enum field>=a,b, <text field>=words, <link field>=any), `q` words and named entities."""
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    params = request.query_params
    filters = {k: v for k, v in params.items() if k not in ("kind", "limit", "offset") + track_brief.SEARCH_PARAMS}
    with transaction() as cur:
        try:
            return track_brief.table(cur, tid, kind, filters, limit=max(1, min(limit, 500)), offset=max(0, offset),
                                     q=params.get("q", ""), entity=params.get("entity", ""),
                                     entity_type=params.get("entity_type", ""))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")


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
