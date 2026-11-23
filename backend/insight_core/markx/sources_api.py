"""The source analysis page's routes (the app's own; 404 when Mark X is off). They read source_stats rows only:
nothing is computed here. Included into markx/api.py's router.

GET  /api/markx/sources                 one row per voice and per source with no voice: {rows, columns, formulas,
                                        computed_at, job}; no overall score
GET  /api/markx/sources/{id}            a voice's or a source's page: {subject, tabs, computed_at}; 404 for neither
POST /api/markx/sources/stance/label    {task, pattern, answer: right | wrong | undo} -> {labels {pattern: answer}}
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
