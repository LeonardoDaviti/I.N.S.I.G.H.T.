"""0130 D (Stealth v10.5): translation, 0086 F5 (Haiku kept all the meaning in 87%, misled in 2%: Russian tech slang).

**The kind** is 0086's `translate` (schemas.KINDS: its guide, the answer {title_en, text_en}; validate._translate: the
post's numbers survive, the length stays within 0.5-2x; tasks.translate_input: the title and the first 2,500 characters).
Its answer is the task's valid call (mx_calls.answer); nothing else is stored.

**Asked two ways:**
  - on request: POST /api/markx/posts/{id}/translate (the "Translate" button on a non-English post) adds the task at
    priority -1, so the next worker run leases it first; asking again is the same task (an existing one is raised to
    -1; one that failed three times is opened again, because the owner asked);
  - for Mark X News leads: `plan` (tasks.PLANNERS["translate"], run when a worker leases `translate` and fewer than its
    limit are open, as the read and read3 planners are) adds one for each non-English lead (the row's first post) of the
    newest written Mark X News run inside News' window, once a post. At lease time rather than as a stage of the decision
    run: no stage, no job state and no change to decide.py; the leads are read from the rows the last run wrote, and a
    translation is only ever needed by a worker that is about to answer it.

**A post's language:** its newest Mark X reading's `lang` when it names one, else posts.language_code ('und' and ''
name none); a post is non-English when that is known and not `en` (en-GB is en). The reading comes first because the
feed's field mislabels posts (the prototype found English READMEs that list "Русский" marked ru).

**The owner's ✓ / ✗** (POST /api/markx/posts/{id}/translation/label {answer: right | wrong | undo, note?}) is a label
like the others (mx_labels, item kind `translation`, migration 0078): a = the translate task, b = the post; the newest
counts, an undo takes it back. GET /api/markx/translations/score counts them by guide.

Only mx_* tables are written; Mark IX's are read.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_core.markx import repo, schemas, tasks

KIND = "translate"
ITEM_KIND = "translation"
ASKED = -1                    # a request's priority: leased before the planned ones (0)
ANSWERS = ("right", "wrong", "undo")
F5 = {"meaning_kept": 0.87, "misleading": 0.02, "set": "150 Russian posts, Opus-labelled", "date": "2026-11-04"}

# The post's language, as SQL over `p` (posts): the newest reading's lang, else the feed's language_code.
LANG_SQL = """lower(split_part(COALESCE(
                (SELECT r.lang FROM mx_readings r
                  WHERE r.post_id = p.id AND NULLIF(btrim(r.lang), '') IS NOT NULL AND lower(r.lang) <> 'und'
                  ORDER BY r.guide DESC LIMIT 1),
                NULLIF(NULLIF(btrim(p.language_code), ''), 'und')), '-', 1))"""


def guide() -> str:
    return schemas.KINDS[KIND].guide


def foreign(lang: Optional[str]) -> bool:
    return bool(lang) and lang != "en"


def language(cur: Any, post_id: str) -> Optional[str]:
    """The post's language (above), or None when nothing names one (or there is no such post)."""
    cur.execute(f"SELECT {LANG_SQL} FROM posts p WHERE p.id = %s", (post_id,))
    row = cur.fetchone()
    return row[0] if row else None


def ask(cur: Any, post_id: str) -> Dict[str, Any]:
    """The owner asked: the post's translate task, added (or found, raised to ASKED, opened again if it failed)."""
    task_id, new = tasks.translate_task(cur, post_id, priority=ASKED)
    if not new:
        cur.execute("""UPDATE mx_tasks SET priority = LEAST(priority, %s),
                              status = CASE WHEN status = 'failed' THEN 'open' ELSE status END,
                              attempts = CASE WHEN status = 'failed' THEN 0 ELSE attempts END
                        WHERE id = %s""", (ASKED, task_id))
    return {"task_id": str(task_id), "new": new}


def _task(cur: Any, post_id: str) -> Optional[Dict[str, Any]]:
    """The task that shows: the newest answered one, else the newest asked."""
    cur.execute("""SELECT * FROM mx_tasks WHERE kind = %s AND a = %s
                    ORDER BY (status = 'answered') DESC, COALESCE(answered_at, created_at) DESC, created_at DESC, id
                    LIMIT 1""", (KIND, post_id))
    rows = repo._rows(cur)
    return rows[0] if rows else None


def latest_label(cur: Any, task_id: Any, labeller: str = "owner") -> Optional[str]:
    cur.execute("""SELECT answer FROM mx_labels WHERE item_kind = %s AND a = %s AND labeller = %s
                    ORDER BY created_at DESC, ctid DESC LIMIT 1""", (ITEM_KIND, task_id, labeller))
    row = cur.fetchone()
    return None if row is None or row[0] == "undo" else row[0]


def view(cur: Any, post_id: str) -> Dict[str, Any]:
    """What the post page shows: {post_id, lang, foreign, task {id, status, guide, error} | null,
    translation {title_en, text_en, guide, model, at} | null, label right | wrong | null}."""
    cur.execute("SELECT 1 FROM posts WHERE id = %s", (post_id,))
    if cur.fetchone() is None:
        raise KeyError(post_id)
    lang = language(cur, post_id)
    t = _task(cur, post_id)
    out: Dict[str, Any] = {"post_id": post_id, "lang": lang, "foreign": foreign(lang), "task": None,
                           "translation": None, "label": None}
    if t is None:
        return out
    out["task"] = {"id": str(t["id"]), "status": t["status"], "guide": t["guide"],
                   "error": t["last_error"] if t["status"] == "failed" else None}
    if t["status"] == "answered":
        c = repo.valid_call(cur, t["id"])
        if c is not None:
            a = c["answer"] or {}
            out["translation"] = {"title_en": a.get("title_en") or "", "text_en": a.get("text_en") or "",
                                  "guide": t["guide"], "model": c["model"], "at": c["created_at"]}
            out["label"] = latest_label(cur, t["id"])
    return out


def label(cur: Any, post_id: str, answer: str, note: Optional[str] = None, labeller: str = "owner") -> Dict[str, Any]:
    """The owner's ✓ (right) / ✗ (wrong) / undo on the post's translation, stored as a label: the view after."""
    if answer not in ANSWERS:
        raise ValueError(f"answer must be one of {', '.join(ANSWERS)}")
    t = _task(cur, post_id)
    if t is None or t["status"] != "answered":
        raise KeyError(post_id)
    repo.add_label(cur, item_kind=ITEM_KIND, a=t["id"], b=post_id, answer=answer,
                   note=(note or "").strip() or None, labeller=labeller)
    return view(cur, post_id)


def score(cur: Any, labeller: str = "owner") -> Dict[str, Any]:
    """The owner's labels by guide, each translation counted by its newest label (an undo counts nothing):
    {guides: {guide: {labelled, right, wrong, precision, interval}}, asked, answered, f5}."""
    from insight_core.markx.labels import wilson
    cur.execute("""SELECT t.guide, l.answer FROM (
                     SELECT DISTINCT ON (a) a, answer FROM mx_labels WHERE item_kind = %s AND labeller = %s
                      ORDER BY a, created_at DESC, ctid DESC) l
                   JOIN mx_tasks t ON t.id = l.a WHERE l.answer <> 'undo'""", (ITEM_KIND, labeller))
    by: Dict[str, List[int]] = {}
    for g, ans in cur.fetchall():
        n = by.setdefault(g, [0, 0])
        n[0 if ans == "right" else 1] += 1
    guides = {}
    for g, (right, wrong) in sorted(by.items()):
        lo, hi = wilson(right, right + wrong)
        guides[g] = {"labelled": right + wrong, "right": right, "wrong": wrong,
                     "precision": round(right / (right + wrong), 3), "interval": [round(lo, 3), round(hi, 3)]}
    cur.execute("SELECT status, count(*) FROM mx_tasks WHERE kind = %s GROUP BY status", (KIND,))
    counts = dict(cur.fetchall())
    return {"guides": guides, "tasks": counts, "guide": guide(), "f5": F5}


# ---- the planner: Mark X News leads (tasks.PLANNERS["translate"]) ----------------------------------------------

def plan(cur: Any, *, limit: int = tasks.PLAN_LIMIT, now: Optional[datetime] = None, **_kw: Any) -> int:
    """A translate task for each non-English lead of the newest written Mark X News run inside News' window that has
    none (of any guide, in any state: once a post), highest score first: how many were added."""
    from insight_core.markx import news
    from insight_core.utils.news_rules import NEWS_DAYS
    run = news.last_written(cur)
    if run is None:
        return 0
    since = (now or datetime.now(timezone.utc)) - timedelta(days=NEWS_DAYS)
    cur.execute(f"""SELECT p.id::text FROM mx_news n JOIN posts p ON p.id = n.id
                     WHERE n.run_id = %s AND n.first_at >= %s
                       AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %s AND t.a = p.id)
                       AND {LANG_SQL} <> 'en'
                     ORDER BY n.score DESC, n.first_at DESC, p.id LIMIT %s""", (run, since, KIND, limit))
    added = 0
    for (pid,) in cur.fetchall():
        try:
            if tasks.translate_task(cur, pid)[1]:
                added += 1
        except LookupError:
            continue
    return added


# ---- the routes (included into markx/api.py's router: its prefix and its switch; no bearer: the app's own) ---------
# GET  /api/markx/posts/{id}/translation          the view above (404: no such post)
# POST /api/markx/posts/{id}/translate            asks for it: {task_id, new, view}; 400 when the post is English
# POST /api/markx/posts/{id}/translation/label    {answer: right | wrong | undo, note?} -> the view; 404: no translation
# GET  /api/markx/translations/score              the owner's labels by guide

router = APIRouter()


class LabelIn(BaseModel):
    answer: str
    note: Optional[str] = None


def _post(post_id: str) -> str:
    from insight_core.markx.api import _uuid
    found = _uuid(post_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such post")
    return str(found)


@router.get("/posts/{post_id}/translation")
def mx_translation(post_id: str):
    from insight_core.markx.api import transaction
    pid = _post(post_id)
    with transaction() as cur:
        try:
            return view(cur, pid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such post")


@router.post("/posts/{post_id}/translate")
def mx_translate(post_id: str):
    from insight_core.markx.api import transaction
    pid = _post(post_id)
    with transaction() as cur:
        try:
            current = view(cur, pid)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such post")
        if not current["foreign"]:
            raise HTTPException(status_code=400, detail="The post is in English, or its language is unknown")
        try:
            got = ask(cur, pid)
        except LookupError:
            raise HTTPException(status_code=404, detail="No such post")
        return {**got, "view": view(cur, pid)}


@router.post("/posts/{post_id}/translation/label")
def mx_translation_label(post_id: str, body: LabelIn):
    from insight_core.markx.api import transaction
    pid = _post(post_id)
    with transaction() as cur:
        try:
            return label(cur, pid, body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No translation of this post")


@router.get("/translations/score")
def mx_translation_score():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return score(cur)
