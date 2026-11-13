"""0162 (Stealth v10.14)'s routes: research (Shadow; the app's own; 404 when Mark X is off, as every /api/markx path).
Included into markx/api.py's router. A run starts only on the owner's tap (POST /research); nothing here starts one by
itself.

POST /api/markx/research                                   {seed, kind?} -> {id, seed_kind, held}; its steps in the background
GET  /api/markx/research                                   the latest runs
GET  /api/markx/research/settings                          {paper_index: openalex | off, web_search: provider | null}
PUT  /api/markx/research/settings                          {paper_index}
GET  /api/markx/research/{id}                              the research page (markx/research.view); a run that can go on
                                                           is advanced in the background
POST /api/markx/research/{id}/rerun                        a new run of the same seed (what this one found is not new)
POST /api/markx/research/{id}/watch                        "Watch this": a track from the run -> {track_id, made}
POST /api/markx/research/{id}/channels/{candidate}/follow  -> {source_id, as} (0148's add path, provenance 'research')
POST /api/markx/research/{id}/channels/{candidate}/not     -> {answer}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from insight_core.markx import research, scout
from insight_core.markx import research_web as W

log = logging.getLogger(__name__)
router = APIRouter()
_advancing: Set[str] = set()


def _id(value: Any, what: str = "research run") -> str:
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
        await research.advance(db_url(), run_id)
    except Exception:  # noqa: BLE001 - the next look or the ingestion tick goes on
        log.exception("Research run %s: the background advance failed", run_id)
    finally:
        _advancing.discard(run_id)


class ResearchIn(BaseModel):
    seed: Optional[str] = None
    kind: Optional[str] = None


class SettingsIn(BaseModel):
    paper_index: Optional[str] = None


@router.post("/research")
def mx_research_start(body: ResearchIn, background: BackgroundTasks):
    from insight_core.markx.api import transaction
    with transaction() as cur:
        try:
            run = research.start(cur, body.seed or "", kind=body.kind)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    background.add_task(advance_in_background, run["id"])
    return run


@router.get("/research")
def mx_research_runs():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return research.runs_of(cur)


@router.get("/research/settings")
def mx_research_settings():
    from insight_core.markx import repo
    from insight_core.markx.api import transaction
    provider = W.web_search()
    with transaction() as cur:
        return {"paper_index": repo.get_setting(cur, W.PAPER_INDEX_SETTING, default="openalex"),
                "web_search": getattr(provider, "name", None)}


@router.put("/research/settings")
def mx_research_settings_put(body: SettingsIn):
    from insight_core.markx import repo
    from insight_core.markx.api import transaction
    if body.paper_index not in ("openalex", "off"):
        raise HTTPException(status_code=400, detail="paper_index: openalex or off")
    with transaction() as cur:
        repo.set_setting(cur, W.PAPER_INDEX_SETTING, body.paper_index)
    return mx_research_settings()


@router.get("/research/{run_id}")
def mx_research_page(run_id: str, background: BackgroundTasks):
    from insight_core.markx.api import transaction
    rid = _id(run_id)
    with transaction() as cur:
        got = research.view(cur, rid)
        if got is None:
            raise HTTPException(status_code=404, detail="No such research run")
        cur.execute("SELECT busy_until IS NULL OR busy_until < now() FROM mx_research_runs WHERE id = %s", (rid,))
        free = cur.fetchone()[0]
    if free and got["run"]["status"] in ("running", "waiting") and rid not in _advancing:
        background.add_task(advance_in_background, rid)
    return got


@router.post("/research/{run_id}/rerun")
def mx_research_rerun(run_id: str, background: BackgroundTasks):
    from insight_core.markx.api import transaction
    rid = _id(run_id)
    with transaction() as cur:
        try:
            run = research.rerun(cur, rid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such research run")
    background.add_task(advance_in_background, run["id"])
    return run


@router.post("/research/{run_id}/watch")
def mx_research_watch(run_id: str, background: BackgroundTasks):
    from insight_core.markx.api import transaction
    rid = _id(run_id)
    with transaction() as cur:
        try:
            got = research.watch(cur, rid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such research run")
    background.add_task(advance_in_background, rid)
    return got


@router.post("/research/{run_id}/channels/{candidate_id}/follow")
def mx_research_follow(run_id: str, candidate_id: str):
    from insight_core.markx.api import transaction
    rid, cid = _id(run_id), _id(candidate_id, "channel")
    with transaction() as cur:
        try:
            return research.follow(cur, rid, cid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such channel in this run")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/research/{run_id}/channels/{candidate_id}/not")
def mx_research_not(run_id: str, candidate_id: str):
    from insight_core.markx.api import transaction
    _id(run_id)
    cid = _id(candidate_id, "channel")
    with transaction() as cur:
        try:
            return scout.not_this(cur, cid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such channel")
