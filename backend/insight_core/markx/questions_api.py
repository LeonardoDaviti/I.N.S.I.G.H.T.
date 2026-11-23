"""The routes of questions with citations on the search page (markx/questions.py), included into markx/api.py's
router (404 when Mark X is off, and while `search.answers` is off). The page polls a question while its `status` is
"waiting".
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from insight_core.markx import questions

router = APIRouter()


def _on() -> None:
    if not questions.on():
        raise HTTPException(status_code=404, detail="Questions are off")


@router.post("/questions")
def mx_question_ask(body: Dict[str, Any]):
    from insight_core.markx.api import transaction
    _on()
    with transaction() as cur:
        try:
            qid = questions.ask(cur, str((body or {}).get("q") or ""))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return questions.view(cur, qid)


@router.get("/questions/on")
def mx_questions_on():
    """Whether the search page shows its question box (`search.answers`)."""
    return {"on": questions.on()}


@router.get("/questions/{question_id}")
def mx_question(question_id: str):
    from insight_core.markx.api import transaction
    import uuid
    _on()
    try:
        uuid.UUID(question_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such question")
    with transaction() as cur:
        got = questions.view(cur, question_id)
    if got is None:
        raise HTTPException(status_code=404, detail="No such question")
    return got
