"""News ranked for the reader (issue 0208, Stealth v10.19): the order of News, owned here.

News was ordered by loudness alone (`score`: reports + half the shares and roundup mentions): the week's big launch
repeated by twenty sources stayed on top, and a new method two expert sources took apart sat 100 rows down. A row's
place is now made of three things, each in [0, 1]:

  - **significance** (markx/significance.py): what kind of event it is and how big its effect is on the work of
    people in its field, the worker's answer to one question a row. A row not answered yet counts as SIG_UNKNOWN (the
    middle: it neither rises nor sinks on it);
  - **coverage**: its score as before, on a log scale (`coverage`: COVERAGE_FULL points or more is 1), so loudness
    still counts, but once;
  - **fit** with this reader (`Profile`, `fit`), from what they actually do: the posts they read, kept or put in Later
    over PROFILE_DAYS (their sources, read more than the sources' share of all posts, and the things those posts are
    about) and the posts their topic tracks hold. Nothing is asked of a model for it.

`combine` weighs them (W_SIG, W_COV, W_FIT). Fit is computed, kept and shown on /markx but weighs 0: on the blind
labels it moved nothing (a generic reader's labels cannot test a personal fit), so it is a Shadow (plan/issues/0208).

**Notable for you** (`rank`): up to NOTABLE_MAX rows of the last NOTABLE_DAYS whose significance is NOTABLE_SIG or more
and that the order by coverage alone puts below NOTABLE_BURIED: the significant items loudness would bury, shown in
their own lane at the top of News.

**Where it runs.** `keep` in the jobs process (jobs.Jobs.news, before the kept pages are built), never in the API: it
reads the newest written run's rows of News' window, their significance answers, the reader's profile, and writes one
mx_news_rank row a row (a cache of a derived order, replaced when ranked again). The API reads those rows by id
(`read`), a few hundred small rows, and orders by them (`order`).

**Analysis** (`analysis_of`): a row's expert breakdowns, shown apart from its reports: the posts its significance
answer names as breakdowns (significance-v2's `breakdowns`) that Mark X reads as commentary, with ANALYSIS_CHARS+
characters of their own, at most
ANALYSIS_MAX, kept in the rank's `why`. The reader's News shows them only when `analysis_mode` says "shown" (the bar: a
point 97% and a Wilson lower bound 90% of them real breakdowns on blind labels, plan/issues/0208); else a Shadow, shown
on /markx only.

**The switch** (`mode`, mx_settings NEWS_RANK): `order` "ranked" (News in this order, the lane on) or "coverage" (News in
the old order; the ranks are kept and shown on /markx, a Shadow). `?order=coverage` on /api/news asks for the old order
whatever the switch says; Mark IX's News (`?mark=ix`) keeps its own order.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

W_SIG, W_COV, W_FIT = 0.6, 0.3, 0.0     # 0208: sig and cov chosen before the measure; fit showed no gain (a Shadow)
SIG_UNKNOWN = 0.4                        # a row whose significance is not answered yet
COVERAGE_FULL = 30.0                     # a score this high (reports + half shares and mentions) is coverage 1
NOTABLE_SIG = 0.7                        # significance a row needs for the lane
NOTABLE_BURIED = 20                      # ... and the coverage order puts it below this place
NOTABLE_DAYS = 7                         # ... and it began within these days
NOTABLE_MAX = 5                          # the lane's rows, at most
PROFILE_DAYS = 90                        # the reader's actions read
SOURCE_PRIOR = 100.0                     # a source's read share is smoothed toward the overall share by this many posts
LIFT_FULL = 8.0                          # a source read this many times its share of posts is fit 1
ENTITY_HALF = 2.0                        # a thing the reader read this many posts about is fit 0.5
FIT_PARTS = {"entity": 0.45, "source": 0.35, "track": 0.20}
NEWS_RANK = "news_rank"                  # mx_settings: {"order": "ranked" | "coverage", "analysis": ...}
ANALYSIS_MAX = 2                         # a row's Analysis posts, at most
ANALYSIS_CHARS = 1000                    # a breakdown's own words, at least (significance.LONG_POST)
ANALYSIS_KINDS = ("commentary",)         # the reading kinds a breakdown has (read-v3, else read-v2)
ANALYSES = ("shown", "shadow")
DEFAULT_ANALYSIS = "shadow"              # 0208: measured 9 of 12 real (Wilson .47-.91): under the bar, a Shadow
ORDERS = ("ranked", "coverage")
DEFAULT_ORDER = "ranked"                 # 0208: passed its bar on a held-out window (P@20 .50 -> .75)


# ---- the parts --------------------------------------------------------------------------------------------

def coverage(score: float) -> float:
    """A row's score (its loudness) on a log scale, COVERAGE_FULL or more being 1."""
    return round(min(1.0, math.log1p(max(float(score), 0.0)) / math.log1p(COVERAGE_FULL)), 4)


@dataclass
class Profile:
    """What the reader did over PROFILE_DAYS: the posts they read (or kept, or put in Later) of each source among all
    that source's posts, the things those posts are about (entity ids, else name keys: how many read posts each),
    and the posts their topic tracks hold."""
    reads: int = 0
    posts: int = 0
    sources: Dict[str, Tuple[int, int]] = field(default_factory=dict)   # source -> (read, posts)
    entities: Dict[str, int] = field(default_factory=dict)
    tracked: Set[str] = field(default_factory=set)

    @property
    def rate(self) -> float:
        return self.reads / self.posts if self.posts else 0.0


def source_fit(p: Profile, source: str) -> float:
    """How much more than its share the reader reads a source: log(lift) / log(LIFT_FULL) in [0, 1], the share
    smoothed toward the overall one by SOURCE_PRIOR posts (a source of 2 posts and 1 read is not a favourite)."""
    if not p.reads or p.rate <= 0:
        return 0.0
    read, posts = p.sources.get(source, (0, 0))
    share = (read + SOURCE_PRIOR * p.rate) / (posts + SOURCE_PRIOR)
    lift = share / p.rate
    return round(min(1.0, max(0.0, math.log(lift) / math.log(LIFT_FULL))), 4) if lift > 1 else 0.0


def entity_fit(p: Profile, things: Iterable[str]) -> Tuple[float, Optional[str]]:
    """The thing of the row the reader read most about: (reads / (reads + ENTITY_HALF), that thing)."""
    best, which = 0, None
    for t in things:
        n = p.entities.get(t, 0)
        if n > best:
            best, which = n, t
    return (round(best / (best + ENTITY_HALF), 4) if best else 0.0), which


def fit(p: Profile, *, sources: Iterable[str], things: Iterable[str], posts: Iterable[str]) -> Tuple[float, Dict[str, Any]]:
    """A row's fit with the reader in [0, 1] and what made it: FIT_PARTS of its best-read source, the thing of it the
    reader read most about, and whether a topic track holds one of its posts."""
    src = max((source_fit(p, s) for s in set(sources)), default=0.0)
    ent, which = entity_fit(p, things)
    track = 1.0 if p.tracked & set(posts) else 0.0
    value = FIT_PARTS["entity"] * ent + FIT_PARTS["source"] * src + FIT_PARTS["track"] * track
    return round(value, 4), {"source": src, "entity": ent, "thing": which, "track": bool(track)}


def combine(significance: Optional[float], cov: float, fit_: float, *,
            weights: Tuple[float, float, float] = (W_SIG, W_COV, W_FIT)) -> float:
    """The rank score: the weighed parts, a row with no significance yet at SIG_UNKNOWN."""
    ws, wc, wf = weights
    s = SIG_UNKNOWN if significance is None else significance
    return round(ws * s + wc * cov + wf * fit_, 4)


@dataclass
class Ranked:
    row_id: str
    significance: Optional[float]
    fit: float
    coverage: float
    score: float
    notable: bool = False
    why: Dict[str, Any] = field(default_factory=dict)


def rank(rows: Sequence[Dict[str, Any]], significance: Dict[str, Optional[float]], fits: Dict[str, Tuple[float, Dict]],
         now: datetime, *, weights: Tuple[float, float, float] = (W_SIG, W_COV, W_FIT)) -> List[Ranked]:
    """The rows ranked (best first) and the lane picked. Pure. `rows`: {id, score, first_at}; `significance`: {row
    id: [0, 1] or None}; `fits`: {row id: (fit, why)}. The lane: rows of the last NOTABLE_DAYS with significance
    NOTABLE_SIG+ that the coverage order puts below NOTABLE_BURIED, the best NOTABLE_MAX."""
    by_cov = sorted(rows, key=lambda r: (-float(r["score"]), -r["first_at"].timestamp(), str(r["id"])))
    place = {str(r["id"]): n for n, r in enumerate(by_cov)}
    out = []
    for r in rows:
        rid = str(r["id"])
        sig = significance.get(rid)
        f, fwhy = fits.get(rid, (0.0, {}))
        cov = coverage(r["score"])
        out.append(Ranked(rid, sig, f, cov, combine(sig, cov, f, weights=weights),
                          why={"fit": fwhy, "coverage_place": place[rid] + 1}))
    out.sort(key=lambda x: (-x.score, -(x.significance or 0), x.row_id))
    first = {str(r["id"]): r["first_at"] for r in rows}
    lane = [x for x in out if x.significance is not None and x.significance >= NOTABLE_SIG
            and place[x.row_id] >= NOTABLE_BURIED and first[x.row_id] >= now - timedelta(days=NOTABLE_DAYS)]
    for x in sorted(lane, key=lambda x: (-x.significance, -x.score, x.row_id))[:NOTABLE_MAX]:
        x.notable = True
    return out


# ---- the database side (the jobs process) ------------------------------------------------------------------

def profile(cur: Any, now: datetime) -> Profile:
    """The reader's Profile over PROFILE_DAYS (above): their reads, keeps and Laters, and every open."""
    since = now - timedelta(days=PROFILE_DAYS)
    from insight_core.markx import pairing
    cur.execute(f"""WITH yours AS (
                        SELECT post_id FROM post_reader_state
                         WHERE GREATEST(read_at, starred_at, later_at) >= %(since)s
                        UNION SELECT post_id FROM post_interactions
                         WHERE interaction_type IN ('opened', 'reading_session') AND created_at >= %(since)s)
                    SELECT p.source_id::text, count(*) FILTER (WHERE y.post_id IS NOT NULL), count(*)
                      FROM posts p LEFT JOIN yours y ON y.post_id = p.id
                     WHERE {pairing.ix_date('p')} >= %(since)s OR y.post_id IS NOT NULL
                     GROUP BY 1""", {"since": since})
    sources = {s: (int(r), int(n)) for s, r, n in cur.fetchall()}
    cur.execute("""WITH yours AS (
                       SELECT post_id FROM post_reader_state
                        WHERE GREATEST(read_at, starred_at, later_at) >= %(since)s
                       UNION SELECT post_id FROM post_interactions
                        WHERE interaction_type IN ('opened', 'reading_session') AND created_at >= %(since)s)
                   SELECT COALESCE(m.entity_id::text, m.name_key), count(DISTINCT m.post_id)
                     FROM mx_mentions_now m JOIN yours y ON y.post_id = m.post_id
                    WHERE m.role IN ('subject', 'actor') AND COALESCE(m.entity_id::text, m.name_key) IS NOT NULL
                    GROUP BY 1""", {"since": since})
    entities = {k: int(n) for k, n in cur.fetchall()}
    cur.execute("""SELECT DISTINCT i.post_id::text FROM mx_track_items i
                    WHERE i.verdict AND i.created_at >= %s""", (since,))
    tracked = {r[0] for r in cur.fetchall()}
    return Profile(reads=sum(r for r, _ in sources.values()), posts=sum(n for _, n in sources.values()),
                   sources=sources, entities=entities, tracked=tracked)


def _row_facts(cur: Any, rows: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """({row: its posts' sources}, {row: the things its posts are about: subjects and actors})."""
    of_post: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        for p in r.get("posts") or []:
            of_post[p["post_id"]].append(str(r["id"]))
    ids = sorted(of_post)
    sources: Dict[str, List[str]] = defaultdict(list)
    things: Dict[str, List[str]] = defaultdict(list)
    if not ids:
        return sources, things
    cur.execute("SELECT id::text, source_id::text FROM posts WHERE id = ANY(%s::uuid[])", (ids,))
    for pid, sid in cur.fetchall():
        for rid in of_post[pid]:
            sources[rid].append(sid)
    cur.execute("""SELECT post_id::text, COALESCE(entity_id::text, name_key) FROM mx_mentions_now
                    WHERE post_id = ANY(%s::uuid[]) AND role IN ('subject', 'actor')""", (ids,))
    for pid, key in cur.fetchall():
        if key:
            for rid in of_post[pid]:
                things[rid].append(key)
    return sources, things


def ranks_of(cur: Any, rows: Sequence[Dict[str, Any]], now: datetime) -> List[Ranked]:
    """The rows ranked from the database: their significance answers, the reader's profile, their coverage."""
    from insight_core.markx import significance as S
    ids = [str(r["id"]) for r in rows]
    answers = S.answers(cur, ids)
    sig = {rid: (answers.get(rid) or {}).get("score") for rid in ids}
    p = profile(cur, now)
    sources, things = _row_facts(cur, rows)
    fits = {str(r["id"]): fit(p, sources=sources.get(str(r["id"]), ()), things=things.get(str(r["id"]), ()),
                              posts=[x["post_id"] for x in r.get("posts") or []]) for r in rows}
    out = rank(rows, sig, fits, now)
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
    commentary (ANALYSIS_KINDS) and that have ANALYSIS_CHARS+ characters of their own (the text beyond the title), in
    the answer's order, at most ANALYSIS_MAX. Measured blind (0208): the answer's names alone 26 of 49 real breakdowns
    (reports and makers' announcements named too); with the reading's kind and the length 9 of 12."""
    named = {rid: a.get("breakdown_posts") or [] for rid, a in answers.items()}
    ids = sorted({p for ps in named.values() for p in ps})
    if not ids:
        return {}
    cur.execute("""SELECT p.id::text, char_length(btrim(COALESCE(p.content, ''))) - CASE
                          WHEN COALESCE(p.title, '') <> '' AND btrim(COALESCE(p.content, '')) LIKE p.title || '%%'
                          THEN char_length(p.title) ELSE 0 END,
                          (SELECT r.kind FROM mx_readings r WHERE r.post_id = p.id ORDER BY r.guide DESC LIMIT 1)
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
