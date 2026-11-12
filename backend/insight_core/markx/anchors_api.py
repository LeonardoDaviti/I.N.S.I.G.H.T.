"""0180 (Stealth v10.16)'s routes: the anchors engine in Shadow (no bearer: the app's own; 404 when Mark X is off, as
every /api/markx path). Included into markx/api.py's router.

GET  /api/markx/anchors/compare?which=later|back   the old engine's rows against the anchors engine's
                                                    (markx/anchors.compare): {which, counts, only_old, only_new, both,
                                                    shown}
GET  /api/markx/anchors/shown                       {engine: old | anchors}: whose rows the Back and Later pages show
POST /api/markx/anchors/shown {engine}              set it (old by default)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_core.markx import anchors

router = APIRouter()


class ShownIn(BaseModel):
    engine: str


@router.get("/anchors/compare")
def mx_anchors_compare(which: str = "later"):
    from insight_core.markx.api import transaction
    if which not in ("back", "later"):
        raise HTTPException(status_code=400, detail="which: back or later")
    with transaction() as cur:
        return anchors.compare(cur, which)


@router.get("/anchors/shown")
def mx_anchors_shown():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return {"engine": anchors.shown(cur)}


@router.post("/anchors/shown")
def mx_anchors_set_shown(body: ShownIn):
    from insight_core.markx import repo
    from insight_core.markx.api import transaction
    if body.engine not in (anchors.OLD, anchors.ENGINE):
        raise HTTPException(status_code=400, detail=f"engine: {anchors.OLD} or {anchors.ENGINE}")
    with transaction() as cur:
        repo.set_setting(cur, anchors.SHOWN_KEY, body.engine)
        return {"engine": anchors.shown(cur)}
