"""0127 (v10.3)'s routes, the fold's (no bearer: the app's own; 404 when Mark X is off, as every /api/markx path):

GET  /api/markx/stories/{id}/folds   the story's members in published order, each {id, role (the rule's), state (head |
                                     folded | shown | null), head, by (rule | owner), answer}: 0119 B6's story view
POST /api/markx/folds/answer         {story, post, answer: same | not_same | undo, note?}: applied at once and stored as a
                                     label (mx_labels, item kind fold) -> the post's fold now
GET  /api/markx/folds/score          the owner's count: {answered, folded {n, right, precision, interval}, missed, lab}

Included into markx/api.py's router (its prefix and its switch).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_core.markx import folds

router = APIRouter()


class FoldAnswerIn(BaseModel):
    story: str
    post: str
    answer: str
    note: Optional[str] = None


def _ids(*values: str):
    from insight_core.markx.api import _uuid
    out = [_uuid(v) for v in values]
    if any(v is None for v in out):
        raise HTTPException(status_code=404, detail="No such member")
    return [str(v) for v in out]


@router.get("/stories/{story_id}/folds")
def mx_story_folds(story_id: str):
    from insight_core.markx.api import transaction
    sid, = _ids(story_id)
    with transaction() as cur:
        try:
            return folds.story_view(cur, sid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such story")


@router.post("/folds/answer")
def mx_fold_answer(body: FoldAnswerIn):
    from insight_core.markx.api import transaction
    story, post = _ids(body.story, body.post)
    with transaction() as cur:
        try:
            return folds.answer(cur, story=story, post=post, answer=body.answer, note=body.note)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such member")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.get("/folds/score")
def mx_fold_score():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return {**folds.score(cur), "lab": folds.LAB}
