"""v10.42's routes, the reader's interest (markx/personal.py; no bearer: the app's own; 404 when Mark X is off):

POST /api/markx/interests                {dim: thing | kind | source, key, answer: more | less | none | undo, name?,
                                         row?, post?}: one tap, kept (mx_interests) -> the tap; News orders by it at
                                         once (the API reads the taps on every News answer)
GET  /api/markx/interests                the taps in force, newest first, and the learned weights, largest first
GET  /api/markx/interests/find?q=      the "Your interests" add box's picker: things by name (v10.43)
GET  /api/markx/posts/{id}/interest     the post page's teach panel: its things, its News row's kind, its source

Included into markx/api.py's router (its prefix and its switch).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_core.markx import personal

router = APIRouter()
LEARNED_SHOWN = 60


class InterestIn(BaseModel):
    dim: str
    key: str
    answer: str
    name: Optional[str] = None
    row: Optional[str] = None
    post: Optional[str] = None


@router.post("/interests")
def mx_teach(body: InterestIn):
    from insight_core.markx.api import _uuid, transaction
    row, post = (str(_uuid(v)) if v and _uuid(v) else None for v in (body.row, body.post))
    with transaction() as cur:
        try:
            return personal.teach(cur, dim=body.dim, key=body.key, answer=body.answer, name=body.name, row=row,
                                  post=post)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.get("/interests")
def mx_interests():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        taps = sorted(personal.taught(cur).items(), key=lambda kv: kv[1]["at"], reverse=True)
        cur.execute("SELECT dim, key, weight, name, why FROM mx_interest_weights ORDER BY abs(weight) DESC, dim, key "
                    "LIMIT %s", (LEARNED_SHOWN,))
        learned = [{"dim": d, "key": k, "weight": w, "name": n, "why": why} for d, k, w, n, why in cur.fetchall()]
    return {"taught": [{"dim": d, "key": k, **{**t, "at": t["at"].isoformat()}} for (d, k), t in taps],
            "learned": learned}


@router.get("/interests/find")
def mx_interests_find(q: str = ""):
    """v10.43: the "Your interests" add box's picker (the stack picker's search)."""
    from insight_core.markx import track_subtracks
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return track_subtracks.find_things(cur, q)


@router.get("/posts/{post_id}/interest")
def mx_post_interest(post_id: str):
    from insight_core.markx.api import _uuid, transaction
    pid = _uuid(post_id)
    if pid is None:
        raise HTTPException(status_code=404, detail="No such post")
    with transaction() as cur:
        try:
            return personal.post_facts(cur, str(pid))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such post")
