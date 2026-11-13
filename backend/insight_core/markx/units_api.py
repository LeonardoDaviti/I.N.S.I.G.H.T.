"""0181 (Stealth v10.16)'s routes: own round-ups (no bearer: the app's own; 404 when Mark X is off, as every
/api/markx path). Included into markx/api.py's router. No route builds a round-up (owner 2026-11-12: never in the
API): the stored issues are built by the candidates job's step (units.issues_step), in its own process; the routes
read stored rows.

GET /api/markx/roundups/of?posts=<id>,<id>         the round-ups carrying these posts as an item ("also in
                                                   round-ups"): [{post, source, title, url, at, n, item, carries}]
GET  /api/markx/roundups/issues                    the stored own round-ups (units.issues): {daily, weekly (the
                                                   latest of each, with items), past: [...], tz_offset_minutes}
GET  /api/markx/roundups/issues/{id}               one stored issue with its items
GET|POST /api/markx/roundups/settings              {tz_offset_minutes}: where the issues' days and weeks begin
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictInt

from insight_core.markx import units

router = APIRouter()


@router.get("/roundups/of")
def mx_roundups_of(posts: str = ""):
    from insight_core.markx.api import _uuid, transaction
    ids = [str(u) for u in (_uuid(p.strip()) for p in posts.split(",") if p.strip()) if u]
    with transaction() as cur:
        return {"roundups": units.also_in(cur, ids[:200])}


@router.get("/roundups/issues")
def mx_roundup_issues(limit: int = 30):
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return units.issues(cur, limit=max(1, min(limit, 200)))


@router.get("/roundups/issues/{issue_id}")
def mx_roundup_issue(issue_id: int):
    from insight_core.markx.api import transaction
    with transaction() as cur:
        got = units.issue(cur, issue_id)
    if got is None:
        raise HTTPException(status_code=404, detail="No such round-up issue")
    return got


class RoundupSettingsIn(BaseModel):
    tz_offset_minutes: StrictInt


@router.get("/roundups/settings")
def mx_roundup_settings():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return {"tz_offset_minutes": int(units.tz_offset(cur).total_seconds() // 60)}


@router.post("/roundups/settings")
def mx_roundup_set_settings(body: RoundupSettingsIn):
    """The offset from UTC the issues' days and weeks begin at (minutes; the owner's UTC+4 is 240). Issues already
    built keep their periods; the next built use the new boundary."""
    from insight_core.markx import repo
    from insight_core.markx.api import transaction
    if not -14 * 60 <= body.tz_offset_minutes <= 14 * 60:
        raise HTTPException(status_code=400, detail="tz_offset_minutes: from -840 to 840")
    with transaction() as cur:
        repo.set_setting(cur, units.TZ_KEY, body.tz_offset_minutes)
        return {"tz_offset_minutes": int(units.tz_offset(cur).total_seconds() // 60)}
