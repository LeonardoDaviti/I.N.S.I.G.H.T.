"""News ranked for the reader: the order of News, owned here (issue 0208).

A row's global place combines two parts in [0, 1] (`combine`: W_SIG, W_COV): its significance
(markx/significance.py; SIG_UNKNOWN until answered) and its coverage (`coverage`: loudness on a log scale). v10.42: the
reader's order ("personal") is that score times the row's personal factor (`personal_score`; markx/personal.py: the
reader's interest in its things, kind and sources); the old fit Shadow is gone.
`rank` also picks the "Notable for you" lane: significant recent rows the coverage order would bury. `keep` runs in
the jobs process (never the API) and writes one mx_news_rank row a News row (a replaced cache, with the row's personal
facts); the API reads them (`read`). `analysis_of` picks a row's expert breakdowns, shown per `analysis_mode`. The
switch `mode` (mx_settings NEWS_RANK): "personal", "ranked" (global only) or "coverage" (the old order); `?order=`
asks for one whatever it says.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from insight_core.markx import reading5

W_SIG, W_COV = 0.6, 0.3                 # measured: plan/issues/0208
SIG_UNKNOWN = 0.4                        # a row whose significance is not answered yet
COVERAGE_FULL = 30.0                     # a score this high (reports + half shares and mentions) is coverage 1
NOTABLE_SIG = 0.7                        # significance a row needs for the lane
NOTABLE_BURIED = 20                      # ... and the coverage order puts it below this place
NOTABLE_DAYS = 7                         # ... and it began within these days
NOTABLE_MAX = 5                          # the lane's rows, at most
NEWS_RANK = "news_rank"                  # mx_settings: {"order": "ranked" | "coverage", "analysis": ...}
ANALYSIS_MAX = 2                         # a row's Analysis posts, at most
ANALYSIS_CHARS = 1000                    # a breakdown's own words, at least (significance.LONG_POST)
ANALYSIS_KINDS = ("commentary",)
_RANK = reading5.rank_sql("r.guide")     # the preferred reading
ANALYSES = ("shown", "shadow")
DEFAULT_ANALYSIS = "shadow"              # under its bar (measured: plan/issues/0208)
ORDERS = ("personal", "ranked", "coverage")   # v10.42: global x personal, global only, coverage only
DEFAULT_ORDER = "personal"               # "ranked" passed its bar (0208); v10.42: x the reader's interest


# ---- the parts --------------------------------------------------------------------------------------------

def coverage(score: float) -> float:
    """A row's score (its loudness) on a log scale, COVERAGE_FULL or more being 1."""
    return round(min(1.0, math.log1p(max(float(score), 0.0)) / math.log1p(COVERAGE_FULL)), 4)


def combine(significance: Optional[float], cov: float, *, weights: Tuple[float, float] = (W_SIG, W_COV)) -> float:
    """The global rank score: the weighed parts, a row with no significance yet at SIG_UNKNOWN."""
    ws, wc = weights
    s = SIG_UNKNOWN if significance is None else significance
    return round(ws * s + wc * cov, 4)


def personal_score(score: float, factor: Optional[float]) -> float:
    """v10.42: the reader's order: the global score times the row's personal factor (markx/personal.py)."""
    return round(score * (factor if factor else 1.0), 4)


@dataclass
class Ranked:
    row_id: str
    significance: Optional[float]
    coverage: float
    score: float
    notable: bool = False
    fit: float = 0.0            # v10.42: the reader's personal p when ranked (markx/personal.py), shown on /markx
    why: Dict[str, Any] = field(default_factory=dict)


def rank(rows: Sequence[Dict[str, Any]], significance: Dict[str, Optional[float]], now: datetime, *,
         weights: Tuple[float, float] = (W_SIG, W_COV)) -> List[Ranked]:
    """The rows ranked (best first) and the lane picked. Pure. `rows`: {id, score, first_at}; `significance`: {row
    id: [0, 1] or None}. The lane: rows of the last NOTABLE_DAYS with significance
    NOTABLE_SIG+ that the coverage order puts below NOTABLE_BURIED, the best NOTABLE_MAX."""
    by_cov = sorted(rows, key=lambda r: (-float(r["score"]), -r["first_at"].timestamp(), str(r["id"])))
    place = {str(r["id"]): n for n, r in enumerate(by_cov)}
    out = []
    for r in rows:
        rid = str(r["id"])
        sig = significance.get(rid)
        cov = coverage(r["score"])
        out.append(Ranked(rid, sig, cov, combine(sig, cov, weights=weights), why={"coverage_place": place[rid] + 1}))
    out.sort(key=lambda x: (-x.score, -(x.significance or 0), x.row_id))
    first = {str(r["id"]): r["first_at"] for r in rows}
    lane = [x for x in out if x.significance is not None and x.significance >= NOTABLE_SIG
            and place[x.row_id] >= NOTABLE_BURIED and first[x.row_id] >= now - timedelta(days=NOTABLE_DAYS)]
    for x in sorted(lane, key=lambda x: (-x.significance, -x.score, x.row_id))[:NOTABLE_MAX]:
        x.notable = True
    return out


# ---- the database side (the jobs process) ------------------------------------------------------------------

def ranks_of(cur: Any, rows: Sequence[Dict[str, Any]], now: datetime) -> List[Ranked]:
    """The rows ranked from the database: their significance answers, their coverage; v10.42: each row's personal
    facts (its things, kind, sources: markx/personal.py) kept in its `why`, the reader's learned weights learned
    again, and the row's personal p at this time kept as `fit`."""
    from insight_core.markx import personal, significance as S
    ids = [str(r["id"]) for r in rows]
    answers = S.answers(cur, ids)
    sig = {rid: (answers.get(rid) or {}).get("score") for rid in ids}
    out = rank(rows, sig, now)
    facts = personal.row_facts(cur, rows, {rid: (answers.get(rid) or {}).get("event") for rid in ids})
    personal.learn(cur, now, facts, rows)
    ws = personal.weights(cur, [k for f in facts.values() for k in personal.keys_of(f)])
    for x in out:
        x.why["personal"] = facts.get(x.row_id)
        x.fit = personal.score(ws, facts.get(x.row_id))["p"]
    analysis = analysis_of(cur, answers)
    for x in out:
        a = answers.get(x.row_id)
        if a:
            x.why.update({k: a.get(k) for k in ("event", "usable", "shipped_in", "adoption", "coverage", "effect",
                                                "scope", "why")})
            x.why["analysis"] = analysis.get(x.row_id, [])
    return out


def analysis_of(cur: Any, answers: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """{row: its Analysis posts}: the posts its answer names as breakdowns that Mark X's newest reading calls
    commentary (ANALYSIS_KINDS) and that have ANALYSIS_CHARS+ characters of their own, in the answer's order, at most
    ANALYSIS_MAX (the reading's kind and length matter: measured, 0208)."""
    named = {rid: a.get("breakdown_posts") or [] for rid, a in answers.items()}
    ids = sorted({p for ps in named.values() for p in ps})
    if not ids:
        return {}
    cur.execute("""SELECT p.id::text, char_length(btrim(COALESCE(p.content, ''))) - CASE
                          WHEN COALESCE(p.title, '') <> '' AND btrim(COALESCE(p.content, '')) LIKE p.title || '%%'
                          THEN char_length(p.title) ELSE 0 END,
                          (SELECT r.kind FROM mx_readings r WHERE r.post_id = p.id AND """ + _RANK + """ IS NOT NULL
                            ORDER BY """ + _RANK + """ LIMIT 1)
                     FROM posts p WHERE p.id = ANY(%s::uuid[])""", (ids,))
    ok = {pid for pid, own, kind in cur.fetchall() if (own or 0) >= ANALYSIS_CHARS and kind in ANALYSIS_KINDS}
    return {rid: [p for p in ps if p in ok][:ANALYSIS_MAX] for rid, ps in named.items()}


def keep(cur: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """In the jobs process: the newest written run's rows of News' window ranked and kept (mx_news_rank, one row a
    News row, replaced). {run, rows, answered, notable}."""
    from insight_core.markx import news_sections
    now = now or datetime.now(timezone.utc)
    run, rows = news_sections.current_rows(cur, now)
    if run is None or not rows:
        return {"run": run, "rows": 0}
    ranked = ranks_of(cur, rows, now)
    cur.executemany("""INSERT INTO mx_news_rank (row_id, run_id, significance, fit, coverage, score, notable, why,
                                                 ranked_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                       ON CONFLICT (row_id) DO UPDATE SET run_id = EXCLUDED.run_id,
                           significance = EXCLUDED.significance, fit = EXCLUDED.fit, coverage = EXCLUDED.coverage,
                           score = EXCLUDED.score, notable = EXCLUDED.notable, why = EXCLUDED.why,
                           ranked_at = EXCLUDED.ranked_at""",
                    [(x.row_id, run, x.significance, x.fit, x.coverage, x.score, x.notable,
                      json.dumps(x.why, default=str), now) for x in ranked])
    return {"run": run, "rows": len(ranked), "answered": sum(1 for x in ranked if x.significance is not None),
            "notable": sum(1 for x in ranked if x.notable)}


def read(cur: Any, row_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{row id: its kept rank {significance, fit, coverage, score, notable, why}} (rows never ranked are absent)."""
    ids = sorted({str(r) for r in row_ids})
    if not ids:
        return {}
    cur.execute("""SELECT row_id::text, significance, fit, coverage, score, notable, why FROM mx_news_rank
                    WHERE row_id = ANY(%s::uuid[])""", (ids,))
    return {rid: {"significance": s, "fit": f, "coverage": c, "score": sc, "notable": n, "why": w or {}}
            for rid, s, f, c, sc, n, w in cur.fetchall()}


def mode(cur: Any) -> str:
    """The switch: "ranked" or "coverage" (mx_settings NEWS_RANK; DEFAULT_ORDER without a row)."""
    from insight_core.markx import repo
    value = repo.get_setting(cur, NEWS_RANK, default=None) or {}
    got = value.get("order") if isinstance(value, dict) else None
    return got if got in ORDERS else DEFAULT_ORDER


def set_mode(cur: Any, order: str) -> str:
    if order not in ORDERS:
        raise ValueError(f"order must be one of {', '.join(ORDERS)}")
    from insight_core.markx import repo
    value = repo.get_setting(cur, NEWS_RANK, default=None) or {}
    repo.set_setting(cur, NEWS_RANK, {**(value if isinstance(value, dict) else {}), "order": order})
    return order


def analysis_mode(cur: Any) -> str:
    """Whether the reader's News shows a row's Analysis ("shown") or only /markx does ("shadow")."""
    from insight_core.markx import repo
    value = repo.get_setting(cur, NEWS_RANK, default=None) or {}
    got = value.get("analysis") if isinstance(value, dict) else None
    return got if got in ANALYSES else DEFAULT_ANALYSIS


def set_analysis_mode(cur: Any, how: str) -> str:
    if how not in ANALYSES:
        raise ValueError(f"analysis must be one of {', '.join(ANALYSES)}")
    from insight_core.markx import repo
    value = repo.get_setting(cur, NEWS_RANK, default=None) or {}
    repo.set_setting(cur, NEWS_RANK, {**(value if isinstance(value, dict) else {}), "analysis": how})
    return how


def stamp(cur: Any, now: datetime) -> List[Any]:
    """What `keep` reads beside the rows (news.page_inputs holds the rows): the significance answers, and the hour
    of the reader's newest action (reads move the fit at most hourly: the jobs process ranks again then)."""
    from insight_core.markx import significance as S
    cur.execute("""SELECT date_trunc('hour', max(GREATEST(read_at, starred_at, later_at))) FROM post_reader_state
                    WHERE GREATEST(read_at, starred_at, later_at) >= %s""", (now - timedelta(days=1),))
    hour = cur.fetchone()[0]
    return S.stamp(cur) + [hour]
