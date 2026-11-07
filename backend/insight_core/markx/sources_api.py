"""0132 B (Stealth v10.6)'s routes, the source analysis page's (no bearer: the app's own; 404 when Mark X is off, as
every /api/markx path). Both pages read source_stats rows only (markx/source_stats.py): nothing is computed here.

GET  /api/markx/sources                 one row per voice and per source with no voice: {rows [{kind, id, name, platform,
                                        enabled, channels, stats {signal: {value, n, too_few}}}], columns, formulas,
                                        computed_at, job (the stats job's last run)}; no overall score
GET  /api/markx/sources/{id}            a voice's or a source's page: {subject, tabs [{kind, id, name, platform, computed,
                                        cards [{card, title, experimental, signals [{signal, value, n, min, counts,
                                        too_few, formula, evidence}]}]}], computed_at}; 404 for neither
POST /api/markx/sources/stance/label    {task, pattern, answer: right | wrong | undo}: the owner's label on a
                                        stance pattern (mx_labels, item kind stance) -> {labels {pattern: answer}}

Included into markx/api.py's router (its prefix and its switch).
"""
from __future__ import annotations


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_core.markx import source_stats

router = APIRouter()


class StanceLabelIn(BaseModel):
    task: str
    pattern: int
    answer: str


def _id(value: str) -> str:
    from insight_core.markx.api import _uuid
    got = _uuid(value)
    if got is None:
        raise HTTPException(status_code=404, detail="No such source")
    return str(got)


@router.get("/sources")
def mx_sources():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return {**source_stats.list_view(cur), "job": source_stats.job_state(cur).get("last")}


@router.get("/sources/{subject_id}")
def mx_source(subject_id: str):
    from insight_core.markx.api import transaction
    sid = _id(subject_id)
    with transaction() as cur:
        try:
            return source_stats.subject_view(cur, sid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such source")


@router.post("/sources/stance/label")
def mx_stance_label(body: StanceLabelIn):
    from insight_core.markx.api import transaction
    task = _id(body.task)
    with transaction() as cur:
        try:
            return {"labels": source_stats.label_stance(cur, task_id=task, pattern=body.pattern, answer=body.answer)}
        except KeyError:
            raise HTTPException(status_code=404, detail="No such stance question")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
