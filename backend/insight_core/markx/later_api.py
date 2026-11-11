"""0163 (Stealth v10.13.11)'s routes: later developments on the Mark X story and entity pages (Shadow; no bearer: the
app's own; 404 when Mark X is off, as every /api/markx path). Included into markx/api.py's router.

GET  /api/markx/later?story=<id>       a story page's "Later" (markx/later.of_story): {stories [{story, headline,
                                       long_lived, following, subjects}], items, counts, precision, news, rule}; the
                                       id is a Mark IX story's or a Mark X story's
GET  /api/markx/entities/{id}/later    an entity page's "Later developments" (later.of_entity): {entity, items, counts,
                                       rule}
     both: the current rule's rows (v10.13.12); `&all=1` every rule's, the older loose rule's rows as well
POST /api/markx/labels/later           {row, answer: development | retold | related | unrelated | undo} -> {id, answer,
                                       label, precision}
POST /api/markx/later/follow           {story, following: false (Stop following this story) | true (Follow again)}
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictBool

from insight_core.markx import later

router = APIRouter()


class LaterLabelIn(BaseModel):
    row: Any = None
    answer: str
    note: Optional[str] = None


class FollowIn(BaseModel):
    story: Any = None
    following: StrictBool
    note: Optional[str] = None


@router.get("/later")
def mx_later_story(story: str, all: bool = False):
    from insight_core.markx.api import _uuid, transaction
    found = _uuid(story)
    if found is None:
        raise HTTPException(status_code=404, detail="No such story")
    with transaction() as cur:
        return later.of_story(cur, str(found), all=all)


@router.get("/entities/{entity_id}/later")
def mx_later_entity(entity_id: str, all: bool = False):
    from insight_core.markx.api import _uuid, transaction
    found = _uuid(entity_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such entity")
    with transaction() as cur:
        return later.of_entity(cur, str(found), all=all)


@router.post("/labels/later")
def mx_label_later(body: LaterLabelIn):
    from insight_core.markx.api import _uuid, transaction
    row = _uuid(body.row)
    if row is None:
        raise HTTPException(status_code=404, detail="No such row")
    with transaction() as cur:
        try:
            return later.label(cur, row=str(row), answer=body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such row")


@router.post("/later/follow")
def mx_later_follow(body: FollowIn):
    from insight_core.markx.api import _uuid, transaction
    story = _uuid(body.story)
    if story is None:
        raise HTTPException(status_code=404, detail="No such story")
    with transaction() as cur:
        try:
            return later.follow(cur, story=str(story), following=body.following, note=body.note)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such story")
