"""0148 (Stealth v10.14)'s routes: the track scout (Shadow; the app's own; 404 when Mark X is off, as every /api/markx
path). Included into markx/api.py's router.

GET  /api/markx/tracks/{id}/scout                 the Topic view's "Sources for this track" block (markx/scout.page);
                                                  a run with reads or judge questions due is advanced in the background
POST /api/markx/tracks/{id}/scout                 the owner's "Find sources for this track": a run started, its reads in
                                                  the background -> {id, candidates}
GET  /api/markx/scout/suggestions                 every track's suggested sources (Discover's rows under the track's name)
POST /api/markx/scout/candidates/{id}/follow      {as: active | passive} -> {source_id, as} (the add path's address)
POST /api/markx/scout/candidates/{id}/not         "Not this one" -> {answer}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, BackgroundTasks, HTTPException

from insight_core.markx import scout

log = logging.getLogger(__name__)
router = APIRouter()
_advancing: Set[str] = set()   # runs this process is advancing now (the database claim decides; this saves a query)


def _id(value: Any, what: str = "track") -> str:
    from insight_core.markx.api import _uuid
    u = _uuid(value)
    if u is None:
        raise HTTPException(status_code=404, detail=f"No such {what}")
    return str(u)


async def advance_in_background(run_id: str) -> None:
    from insight_core.markx.api import db_url
    if run_id in _advancing:
        return
    _advancing.add(run_id)
    try:
        await scout.advance(db_url(), run_id)
    except Exception:  # noqa: BLE001 - the next look or the ingestion tick advances it again
        log.exception("Scout run %s: the background advance failed", run_id)
    finally:
        _advancing.discard(run_id)


def _kick(cur: Any, background: BackgroundTasks, folder_id: Optional[str] = None) -> None:
    cur.execute("""SELECT id::text FROM mx_scout_runs WHERE status IN ('running', 'waiting') AND trigger <> 'research'
                     AND (%s::uuid IS NULL OR track_id = %s::uuid) AND (busy_until IS NULL OR busy_until < now())""",
                (folder_id, folder_id))
    for (run_id,) in cur.fetchall():
        if run_id not in _advancing and scout.needs_advance(cur, run_id):
            background.add_task(advance_in_background, run_id)


@router.get("/tracks/{track_id}/scout")
def mx_track_scout(track_id: str, background: BackgroundTasks):
    from insight_core.markx import tracks
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        if tracks.get(cur, tid) is None:
            raise HTTPException(status_code=404, detail="No such track")
        _kick(cur, background, tid)
        return scout.page(cur, tid)


@router.post("/tracks/{track_id}/scout")
def mx_track_scout_start(track_id: str, background: BackgroundTasks):
    from insight_core.markx.api import transaction
    tid = _id(track_id)
    with transaction() as cur:
        try:
            run = scout.start(cur, tid, trigger="tap")
        except KeyError:
            raise HTTPException(status_code=404, detail="No such track")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    background.add_task(advance_in_background, run["id"])
    return run


@router.get("/scout/suggestions")
def mx_scout_suggestions():
    """Discover's rows: each track's suggested sources, under its name."""
    from insight_core.markx import tracks
    from insight_core.markx.api import transaction
    with transaction() as cur:
        got = scout.suggestions(cur)["suggested"]
        names = {t["folder_id"]: t["name"] for t in tracks.described(cur)}
    return [dict(row, track_name=names.get(row["track"], "")) for row in got if row["track"] in names]


def _follow_as(body: Dict[str, Any]) -> str:
    value = str((body or {}).get("as") or "active")
    if value not in ("active", "passive"):
        raise HTTPException(status_code=400, detail="as: active or passive")
    return value


@router.post("/scout/candidates/{candidate_id}/follow")
def mx_scout_follow(candidate_id: str, body: Dict[str, Any]):
    from insight_core.markx.api import transaction
    cid = _id(candidate_id, "candidate")
    as_ = _follow_as(body)
    with transaction() as cur:
        try:
            return scout.follow(cur, cid, as_)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such candidate")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/scout/candidates/{candidate_id}/not")
def mx_scout_not(candidate_id: str):
    from insight_core.markx.api import transaction
    cid = _id(candidate_id, "candidate")
    with transaction() as cur:
        try:
            return scout.not_this(cur, cid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such candidate")
