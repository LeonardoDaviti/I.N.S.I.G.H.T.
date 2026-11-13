"""Tracks as topics (issue 0145, Stealth v10.11): a track in the owner's own words, judged post by post from its active
and passive sources, organised into sub-topics, sharpened by the owner's labels.

**A track is a topic** when its folder has a row in mx_tracks with a description (what belongs, the owner's words)
and, optionally, excludes (what doesn't). Without one it stays a plain folder: nothing here reads it. Its **active
sources** are the folder's sources (source_folders, read when needed: a source made active turns its items into track
items). Every other source is **passive**. The owner's ✓ / ✗ on a post for a track is a label (mx_labels, item kind
`track`, a = the post, b = the folder; answers in / out / undo, the newest counts); labels are the track's examples.

**Who is judged** (`plan`, tasks.PLANNERS["track"], at lease time, at most TASKS_PER_RUN open across tracks):
  1. active sources: every post of the reading window (planned like `read`: newest first; tasks.reading_window);
  2. passive sources, recent: the posts of the last RECENT_DAYS (and since the description's version) the
     prefilter passes, newest first;
  3. passive sources, history: once over every older post when a track is described or its description changes,
     newest first, HISTORY_PAGE posts a call, resumable (a keyset cursor on mx_tracks); it shares the cap and comes
     last (its tasks' priority is HISTORY_PRIORITY + age, so new posts are leased first).
A post may be in several tracks. One row per track, post and version (mx_track_items) records what was asked; a post
whose question repeats another's (a repost) shares that task and its verdict.

**The prefilter** (no model call): the cosine of the post's BGE-M3 vector (mx_embeddings) to the track's **profile**:
the description's vector (an `embed` task, subject 'track', answered by the worker's embedder like a post's) plus the
mean of the ✓ examples' vectors, minus NEG_PULL times the mean of the ✗ examples'; scaled to length 1. A post passes
at or above the track's threshold: until MIN_EXAMPLES ✓ exist, the cosine that passes DEFAULT_PASS_SHARE of the last
SHARE_DAYS' posts, at most DEFAULT_THRESHOLD (the spec's 0.55 alone passed 0-6% of a month and 0-27% of the posts that
belonged, on the server copy: 0145-built.md); then the highest value that keeps
PASS_SHARE of the ✓ examples passing, each ✓ scored against the profile made without it (leave-one-out, so the
examples don't vouch for themselves). Each plan logs passed / scanned per track (mx_tracks.stats).

**The judge** (`track`, guide track-v1, 10 posts a call): per post {in, confidence 0-1, subtopic, why}. Its input is
the track's header (name, what belongs, what doesn't, the locked sub-topics, the 4 newest ✓ and 2 newest ✗ examples,
titles cut) and the post (markx text v1, TEXT_CHARS). Validated like other kinds (validate._track: `why` one line).

**Where a judged post goes** (read when the page is built, so it follows the labels and the precision):
  - an owner ✗: out (kept, counted); an owner ✓: in the track;
  - `in` from an active source: in the track;
  - `in` from a passive source: in Discover, ranked by calibrated precision (the Wilson lower bound of the share of the
    owner's labels that were ✓ among passive `in`s at or above the item's confidence band; by confidence until
    RANK_MIN_LABELS labels); **joined by INSIGHT** (in the track, marked, with ✓ / ✗) when the track's passive `in`s
    at or above some band have JOIN_MIN_LABELS+ labels, JOIN_PRECISION+ of them ✓ and a Wilson lower bound of
    JOIN_LOWER+: those at or above the lowest such band join. When that stops holding they go back to Discover;
  - `out`: kept with its verdict, never shown, counted.

**Sub-topics** (`subtopics`, guide subtopics-v1, one call a track): once a track holds SUBTOPIC_MIN_ITEMS items, and
then weekly when new items came, INSIGHT proposes 1-8 (the guide asks 3-8) from its items' judge subtopics and titles.
Each sub-topic collects judge subtopic strings (`keys`, folded); an item goes to the sub-topic holding its string, or
named like it, else "Other". The owner renames, merges, splits (moves strings to a new one) and locks; an owner edit
locks it. A new proposal replaces the unlocked ones (closed with valid_to) and keeps the locked; the judge is given the
locked names. The track page reads as sections by sub-topic (newest first within), then Discover.

**The track finds its sources**: a passive source with SUGGEST_MIN+ items judged `in` (and not ✗ by the owner) in
SUGGEST_DAYS days is suggested on the track page and on Discover; making it active adds it to the folder (no new source
is added here: a new one comes through the feed finder).

Only mx_* tables are written, except the owner's own "make it active" (the folder's source list, as Sources does).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.markx import finders, pairing, repo, schemas, tasks

log = logging.getLogger(__name__)

KIND = "track"
SUB_KIND = "subtopics"
EMBED_KIND = "embed"
ITEM_KIND = "track"            # mx_labels.item_kind
MODEL = "bge-m3"
DEFAULT_THRESHOLD = 0.55       # the prefilter's bar until MIN_EXAMPLES ✓ exist, at most (and with too few posts to measure)
DEFAULT_PASS_SHARE = 0.30      # ... else the cosine that passes this share of the last SHARE_DAYS' posts, when lower
SHARE_DAYS = 30
SHARE_MIN_POSTS = 100
MIN_EXAMPLES = 5
PASS_SHARE = 0.98              # the share of the ✓ examples the threshold keeps passing
NEG_PULL = 0.5                 # how far the ✗ examples' mean pulls the profile away
TASKS_PER_RUN_ENV = "INSIGHT_TRACK_TASKS_PER_RUN"
TASKS_PER_RUN = 300            # at most this many track tasks open at once, across tracks (the history pass shares it)
HISTORY_PAGE = 2000            # posts the history pass reads a page ...
HISTORY_PAGES = 10             # ... and at most this many pages a call
MAX_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
HISTORY_PRIORITY = 1000        # history tasks come after the new posts' (priority = this + age in days)
RECENT_DAYS = 7                # the passive scan of new posts reads this far back each call
TEXT_CHARS = 1200              # the post's text a question shows
LINKS = 3
EXAMPLE_CHARS = 140            # an example's title (or text) as the header shows it
POS_SHOTS, NEG_SHOTS = 4, 2
CONF_EDGES = (0.9, 0.8, 0.7, 0.6, 0.5, 0.0)   # the confidence bands (their lower edges)
RANK_MIN_LABELS = 10
JOIN_MIN_LABELS = 20
JOIN_PRECISION = 0.90
JOIN_LOWER = 0.85
SUBTOPIC_MIN_ITEMS = 15
SUBTOPIC_EVERY = timedelta(days=7)
SUBTOPIC_ITEMS = 120           # the newest items a proposal reads
SUGGEST_MIN = 3
SUGGEST_DAYS = 30
LABELS = ("in", "out")
ANSWERS = LABELS + ("undo",)
SECTION_ITEMS = 60             # items a section shows (newest first; its count says how many)
DISCOVER_ITEMS = 100
def _date(p: str = "p") -> str:
    """A folder's post date: the post's own (Pairing's ordinary date), as the feed shows it."""
    return pairing.ordinary_date(p)


def tasks_per_run() -> int:
    try:
        return max(0, int(os.environ.get(TASKS_PER_RUN_ENV, TASKS_PER_RUN)))
    except ValueError:
        return TASKS_PER_RUN


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fold_key(s: Optional[str]) -> str:
    """A sub-topic string as it is compared: casefolded, punctuation as spaces, squashed."""
    return re.sub(r"[\W_]+", " ", (s or "").casefold()).strip()


# ---- the track ---------------------------------------------------------------------------------------

_COLS = ("folder_id", "name", "kind", "description", "excludes", "version", "version_at", "v_hash", "has_v",
         "history_at", "history_id", "history_done_at", "stats", "created_at", "updated_at")


def _select(where: str) -> str:
    return f"""SELECT t.folder_id::text, f.name, f.kind, t.description, t.excludes, t.version, t.version_at, t.v_hash,
                      t.v IS NOT NULL, t.history_at, t.history_id::text, t.history_done_at, t.stats, t.created_at,
                      t.updated_at
                 FROM mx_tracks t JOIN folders f ON f.id = t.folder_id WHERE {where}"""


def get(cur: Cursor, folder_id: Any) -> Optional[Dict[str, Any]]:
    """The track's topic row with its folder's name, or None (a plain folder, or none)."""
    cur.execute(_select("t.folder_id = %s"), (str(folder_id),))
    row = cur.fetchone()
    return dict(zip(_COLS, row)) if row else None


def described(cur: Cursor) -> List[Dict[str, Any]]:
    """Every track that is a topic (a description), oldest first."""
    cur.execute(_select("t.description IS NOT NULL AND btrim(t.description) <> ''") + " ORDER BY t.created_at, t.folder_id")
    return [dict(zip(_COLS, r)) for r in cur.fetchall()]


def _clean(s: Optional[str], limit: int = 2000) -> Optional[str]:
    s = re.sub(r"[ \t]+", " ", (s or "")).strip()
    return s[:limit] or None


def material(text: Optional[str]) -> str:
    """0191: what a description says, for "did it change": its words, folded (NFKC, case), without punctuation or
    spacing. An edit that changes none of them (a comma, a capital, a line break) is not a new version."""
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text or "").casefold()))


def set_topic(cur: Cursor, folder_id: Any, *, description: Optional[str], excludes: Optional[str] = None
              ) -> Dict[str, Any]:
    """Describe a track (or change it): a new description or excludes is a new version (its posts judged again, the
    history pass started again, the description embedded again; the old verdicts kept). An empty description makes it
    a plain folder again (its rows kept). 0191: an edit that changes no word (material: punctuation, case, spacing)
    keeps the version and its history pass; only the text shown (and its vector) follows it. KeyError: no such
    folder."""
    cur.execute("SELECT 1 FROM folders WHERE id = %s", (str(folder_id),))
    if cur.fetchone() is None:
        raise KeyError(folder_id)
    description, excludes = _clean(description), _clean(excludes)
    cur.execute("SELECT description, excludes FROM mx_tracks WHERE folder_id = %s", (str(folder_id),))
    was = cur.fetchone()
    if (was is not None and description and was[0] and (was[0], was[1]) != (description, excludes)
            and (material(was[0]), material(was[1])) == (material(description), material(excludes))):
        cur.execute("UPDATE mx_tracks SET description = %s, excludes = %s, updated_at = now() WHERE folder_id = %s",
                    (description, excludes, str(folder_id)))
        return get(cur, folder_id)
    cur.execute("""INSERT INTO mx_tracks (folder_id, description, excludes) VALUES (%s, %s, %s)
                   ON CONFLICT (folder_id) DO UPDATE
                      SET description = EXCLUDED.description, excludes = EXCLUDED.excludes,
                          version = mx_tracks.version + 1, version_at = now(), updated_at = now(),
                          history_at = NULL, history_id = NULL, history_done_at = NULL
                    WHERE (mx_tracks.description, mx_tracks.excludes)
                          IS DISTINCT FROM (EXCLUDED.description, EXCLUDED.excludes)""",
                (str(folder_id), description, excludes))
    return get(cur, folder_id)


def is_topic(track: Optional[Dict[str, Any]]) -> bool:
    return bool(track and (track.get("description") or "").strip())


# ---- the description's vector ------------------------------------------------------------------------

def embed_text(track: Dict[str, Any]) -> str:
    """What the description's `embed` task asks: the track's name and what belongs, on one line."""
    return re.sub(r"\s+", " ", f"{track['name']}: {track.get('description') or ''}").strip()


def plan_vectors(cur: Cursor, **_kw: Any) -> int:
    """An `embed` task (subject 'track', a = the folder, leased first) for each described track whose description
    has no vector yet: how many were added. A text another task already embedded gets its vector copied."""
    schemas.ensure_guides(cur)
    guide = schemas.KINDS[EMBED_KIND].guide
    added = 0
    for t in described(cur):
        text = embed_text(t)
        h = _sha(text)
        if t["has_v"] and t["v_hash"] == h:
            continue
        task_id, new = repo.add_task(cur, kind=EMBED_KIND, guide=guide, subject_kind="track", input=text,
                                     a=t["folder_id"], priority=-1)
        if new:
            added += 1
            continue
        task = repo.get_task(cur, task_id)
        if task["status"] != "answered":
            continue
        if task["subject_kind"] == "track":     # another track with the same words
            cur.execute("""UPDATE mx_tracks SET v = s.v, v_hash = s.v_hash FROM mx_tracks s
                            WHERE mx_tracks.folder_id = %s AND s.v_hash = %s AND s.v IS NOT NULL""", (t["folder_id"], h))
        else:                                   # a post with the same text
            cur.execute("""UPDATE mx_tracks SET v = e.v, v_hash = %s FROM mx_embeddings e
                            WHERE mx_tracks.folder_id = %s AND e.post_id = %s AND e.model = %s""",
                        (h, t["folder_id"], task["a"], MODEL))
    return added


def store_vector(cur: Cursor, task: Dict[str, Any], vector: Sequence[float]) -> None:
    """An embed task of subject 'track' answered (embed.store): the description's vector, for the text it asked."""
    cur.execute("UPDATE mx_tracks SET v = %s::halfvec, v_hash = %s WHERE folder_id = %s",
                (repo.vector_text(vector), task["input_hash"], task["a"]))


# ---- vectors (plain Python: a profile reads a few vectors) ---------------------------------------------

def _parse(text: Optional[str]) -> Optional[List[float]]:
    if not text:
        return None
    return [float(x) for x in text.strip("[]").split(",")]


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _unit(v: Sequence[float]) -> Optional[List[float]]:
    n = _norm(v)
    return [x / n for x in v] if n > 1e-9 else None


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _mean(vs: Sequence[Sequence[float]]) -> List[float]:
    n = len(vs)
    return [sum(col) / n for col in zip(*vs)]


def combine(desc: Optional[Sequence[float]], pos: Sequence[Sequence[float]], neg: Sequence[Sequence[float]]
            ) -> Optional[List[float]]:
    """The profile: the description's vector + the ✓ mean - NEG_PULL x the ✗ mean, scaled to length 1 (None when
    there is neither a description vector nor a ✓ example)."""
    if desc is None and not pos:
        return None
    dims = len(desc) if desc is not None else len(pos[0])
    u = list(desc) if desc is not None else [0.0] * dims
    if pos:
        u = [a + b for a, b in zip(u, _mean(pos))]
    if neg:
        u = [a - NEG_PULL * b for a, b in zip(u, _mean(neg))]
    return _unit(u)


def threshold_for(scores: Sequence[float], default: float = DEFAULT_THRESHOLD) -> float:
    """The bar that keeps PASS_SHARE of the ✓ examples' scores passing (default until MIN_EXAMPLES)."""
    if len(scores) < MIN_EXAMPLES:
        return default
    s = sorted(scores)
    k = int(math.floor((1 - PASS_SHARE) * len(s) + 1e-9))
    return math.floor(s[k] * 10000) / 10000


def loo_scores(desc: Optional[Sequence[float]], pos: Sequence[Sequence[float]], neg: Sequence[Sequence[float]]
               ) -> List[float]:
    """Each ✓ example's cosine to the profile made without it."""
    out = []
    for i, p in enumerate(pos):
        prof = combine(desc, [q for j, q in enumerate(pos) if j != i], neg)
        if prof is not None:
            out.append(_dot(_unit(p) or p, prof))
    return out


# ---- the owner's labels (the examples) ---------------------------------------------------------------

def labels(cur: Cursor, folder_id: Any) -> Dict[str, Tuple[str, datetime]]:
    """{post id: (in | out, when)}: the owner's newest label per post for this track (an undo takes it back)."""
    cur.execute("""SELECT DISTINCT ON (a) a::text, answer, created_at FROM mx_labels
                    WHERE item_kind = %s AND labeller = 'owner' AND b = %s
                    ORDER BY a, created_at DESC, ctid DESC""", (ITEM_KIND, str(folder_id)))
    return {a: (ans, at) for a, ans, at in cur.fetchall() if ans in LABELS}


def examples(cur: Cursor, folder_id: Any) -> Dict[str, List[str]]:
    """{"in": [post ids], "out": [post ids]}, newest label first."""
    got = sorted(labels(cur, folder_id).items(), key=lambda kv: kv[1][1], reverse=True)
    return {"in": [p for p, (a, _) in got if a == "in"], "out": [p for p, (a, _) in got if a == "out"]}


def _vectors(cur: Cursor, ids: Sequence[str]) -> Dict[str, List[float]]:
    if not ids:
        return {}
    cur.execute("SELECT post_id::text, v::text FROM mx_embeddings WHERE model = %s AND post_id = ANY(%s::uuid[])",
                (MODEL, list(ids)))
    return {p: _parse(v) for p, v in cur.fetchall()}


def profile(cur: Cursor, track: Dict[str, Any], ex: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """{vector (None: no profile yet), threshold, pos, neg, description (whether its vector is in)}."""
    ex = ex if ex is not None else examples(cur, track["folder_id"])
    desc = None
    if track.get("has_v") and track.get("v_hash") == _sha(embed_text(track)):
        cur.execute("SELECT v::text FROM mx_tracks WHERE folder_id = %s", (track["folder_id"],))
        desc = _parse(cur.fetchone()[0])
    vs = _vectors(cur, ex["in"] + ex["out"])
    pos = [vs[p] for p in ex["in"] if p in vs]
    neg = [vs[p] for p in ex["out"] if p in vs]
    vec = combine(desc, pos, neg)
    thr = DEFAULT_THRESHOLD
    if vec is not None:
        default = share_threshold(cur, vec) if len(pos) < MIN_EXAMPLES else DEFAULT_THRESHOLD
        thr = threshold_for(loo_scores(desc, pos, neg), default=default)
    return {"vector": vec, "threshold": thr, "pos": len(pos), "neg": len(neg), "description": desc is not None}


def share_threshold(cur: Cursor, vec: Sequence[float], *, share: float = DEFAULT_PASS_SHARE,
                    now: Optional[datetime] = None) -> float:
    """The default bar (measured on the server copy, 0145-built.md: 0.55 passed 0-6% of 30 days and 0-27% of the posts
    that belonged): the cosine at which `share` of the last SHARE_DAYS' embedded posts pass, at most DEFAULT_THRESHOLD;
    DEFAULT_THRESHOLD with fewer than SHARE_MIN_POSTS posts to measure."""
    cur.execute(f"""SELECT count(*), percentile_disc(%s) WITHIN GROUP (ORDER BY 1 - (e.v <=> %s::halfvec))
                      FROM posts p JOIN mx_embeddings e ON e.post_id = p.id AND e.model = %s
                     WHERE {_date()} >= COALESCE(%s, now()) - make_interval(days => %s)""",
                (1 - share, repo.vector_text(vec), MODEL, now, SHARE_DAYS))
    n, cut = cur.fetchone()
    if n < SHARE_MIN_POSTS or cut is None:
        return DEFAULT_THRESHOLD
    return min(DEFAULT_THRESHOLD, math.floor(float(cut) * 10000) / 10000)


# ---- the question ------------------------------------------------------------------------------------

def _example_line(p: tasks.Post) -> str:
    t = p.title or p.text
    t = re.sub(r"\s+", " ", t or "").strip()
    return "- " + (t[:EXAMPLE_CHARS] + ("…" if len(t) > EXAMPLE_CHARS else ""))


def locked_names(cur: Cursor, folder_id: Any) -> List[str]:
    cur.execute("""SELECT name FROM mx_track_subtopics WHERE track_id = %s AND valid_to IS NULL AND locked
                    ORDER BY lower(name), name""", (str(folder_id),))
    return [n for (n,) in cur.fetchall()]


def header(cur: Cursor, track: Dict[str, Any], ex: Optional[Dict[str, List[str]]] = None) -> str:
    """The track's part of a question: name, what belongs, what doesn't, the locked sub-topics, the newest examples."""
    ex = ex if ex is not None else examples(cur, track["folder_id"])
    pos, neg = ex["in"][:POS_SHOTS], ex["out"][:NEG_SHOTS]
    posts = tasks.load_posts(cur, pos + neg)
    lines = [f"TRACK: {track['name']}", f"Belongs: {track['description']}"]
    if track.get("excludes"):
        lines.append(f"Not: {track['excludes']}")
    subs = locked_names(cur, track["folder_id"])
    if subs:
        lines.append("Sub-topics: " + "; ".join(subs))
    shown_pos = [posts[p] for p in pos if p in posts]
    shown_neg = [posts[p] for p in neg if p in posts]
    if shown_pos:
        lines.append("Marked in by the reader:")
        lines += [_example_line(p) for p in shown_pos]
    if shown_neg:
        lines.append("Marked out by the reader:")
        lines += [_example_line(p) for p in shown_neg]
    return "\n".join(lines)


def track_input(head: str, p: tasks.Post) -> str:
    return head + "\n\nPOST\n" + tasks.post_block(p, LINKS, TEXT_CHARS)


def one_line(text: str) -> bool:
    return "\n" not in (text or "").strip()


# ---- planning ----------------------------------------------------------------------------------------

def _age(at: Optional[datetime], now: datetime) -> int:
    if at is None:
        return 0
    return max(0, int((now - at).total_seconds() // 86400))


def _answered_verdict(cur: Cursor, task_id: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
    cur.execute("""SELECT id, answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at, ctid LIMIT 1""",
                (task_id,))
    row = cur.fetchone()
    return (row[0], row[1] or {}) if row else None


def _fill(cur: Cursor, where: str, params: Sequence[Any], call_id: Any, answer: Dict[str, Any]) -> int:
    cur.execute(f"""UPDATE mx_track_items SET verdict = %s, confidence = %s, subtopic = %s, why = %s, call_id = %s,
                                             answered_at = now()
                     WHERE verdict IS NULL AND {where}""",
                (bool(answer.get("in")), float(answer.get("confidence") or 0), _clean(answer.get("subtopic"), 80),
                 _clean(answer.get("why"), schemas.TRACK_WHY_CHARS), call_id, *params))
    return cur.rowcount


def _ask(cur: Cursor, track: Dict[str, Any], head: str, p: tasks.Post, *, origin: str, cos: Optional[float],
         priority: int, found_by: Optional[Sequence[str]] = None, score: Optional[float] = None) -> bool:
    """One post's question for the track, and its row (a passive one with the finders that found it, 0147): whether a
    task was added."""
    schemas.ensure_guides(cur)
    task_id, new = repo.add_task(cur, kind=KIND, guide=schemas.KINDS[KIND].guide, subject_kind="post_track",
                                 input=track_input(head, p), a=p.id, b=track["folder_id"], priority=priority)
    cur.execute("""INSERT INTO mx_track_items (track_id, post_id, version, task_id, origin, cos, found_by, score)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (track["folder_id"], p.id, track["version"], task_id, origin, cos,
                 list(found_by) if found_by else None, score))
    if not new:
        got = _answered_verdict(cur, task_id)
        if got:
            _fill(cur, "track_id = %s AND post_id = %s AND version = %s", (track["folder_id"], p.id, track["version"]),
                  got[0], got[1])
    return new


def open_tasks(cur: Cursor) -> int:
    # 0148: a scout's test-read items (subject 'scout_item') have their own budget, never this cap's
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = %s AND status IN ('open', 'leased') AND subject_kind = 'post_track'",
                (KIND,))
    return cur.fetchone()[0]


def _active_rows(cur: Cursor, track: Dict[str, Any], *, days: Optional[int], limit: int, now: datetime):
    cur.execute(f"""SELECT p.id::text, {_date()} FROM posts p
                     WHERE p.source_id IN (SELECT source_id FROM source_folders WHERE folder_id = %(t)s)
                       AND (%(days)s::int IS NULL OR {_date()} >= %(now)s - make_interval(days => %(days)s))
                       AND NOT EXISTS (SELECT 1 FROM mx_track_items i
                                        WHERE i.track_id = %(t)s AND i.post_id = p.id AND i.version = %(v)s)
                     ORDER BY {_date()} DESC, p.id DESC LIMIT %(limit)s""",
                {"t": track["folder_id"], "days": days, "now": now, "v": track["version"], "limit": limit})
    return cur.fetchall()


def _recent(cur: Cursor, track: Dict[str, Any], prep: Dict[str, Any], *, limit: int, now: datetime):
    """The passive posts of the last RECENT_DAYS: (scanned, passed: a finder fired, [scored post] to ask, in the
    union's order: finders.order_key). It overlaps the history pass (which starts at the version's start) on purpose:
    a post dated before it but stored after is still read."""
    rows = finders.score(cur, track, prep, since=now - timedelta(days=RECENT_DAYS), until=now)
    hits = [d for d in rows if d["fired"]]
    have = _has_item(cur, track, [d["post_id"] for d in hits]) | finders.labelled(prep)
    todo = sorted((d for d in hits if d["post_id"] not in have), key=finders.order_key, reverse=True)
    return len(rows), len(hits), todo[:max(0, limit)]


def _history_page(cur: Cursor, track: Dict[str, Any]):
    """The history pass's next page: [(id, at, has a vector, active)], newest first, before the cursor (or the
    version's start)."""
    at, pid = track.get("history_at"), track.get("history_id")
    cur.execute(f"""SELECT p.id::text, {_date()}, e.post_id IS NOT NULL,
                           p.source_id IN (SELECT source_id FROM source_folders WHERE folder_id = %(t)s)
                      FROM posts p LEFT JOIN mx_embeddings e ON e.post_id = p.id AND e.model = %(model)s
                     WHERE {_date()} IS NOT NULL
                       AND ({_date()}, p.id) < (%(at)s::timestamptz, %(id)s::uuid)
                     ORDER BY {_date()} DESC, p.id DESC LIMIT %(limit)s""",
                {"t": track["folder_id"], "model": MODEL, "at": at or track["version_at"],
                 "id": pid if at else MAX_UUID, "limit": HISTORY_PAGE})
    return cur.fetchall()


def _has_item(cur: Cursor, track: Dict[str, Any], ids: Sequence[str]) -> set:
    if not ids:
        return set()
    cur.execute("SELECT post_id::text FROM mx_track_items WHERE track_id = %s AND version = %s AND post_id = ANY(%s::uuid[])",
                (track["folder_id"], track["version"], list(ids)))
    return {r[0] for r in cur.fetchall()}


def _history(cur: Cursor, t: Dict[str, Any], prep: Dict[str, Any], head: str, *, budget: int, now: datetime
             ) -> Tuple[int, int, int, int]:
    """The history pass's next stretch: at most `budget` tasks and HISTORY_PAGES pages, the cursor kept after each
    post read (so a stop at the cap resumes there); done when a page comes back short. A post is asked when a finder
    fires for it (0147). (planned, scanned, passed, posts with no vector yet: not read again by this pass)."""
    n = scanned = passed = unembedded = 0
    for _page in range(HISTORY_PAGES):
        page = _history_page(cur, t)
        scored = {d["post_id"]: d for d in finders.score(cur, t, prep, ids=[r[0] for r in page if r[2] and not r[3]])}
        hits = [pid for pid, d in scored.items() if d["fired"]]
        have = _has_item(cur, t, hits) | finders.labelled(prep)
        posts = tasks.load_posts(cur, [p for p in hits if p not in have])
        last, full = None, False
        for pid, at, embedded, active in page:
            if n >= budget:
                full = True
                break
            scanned += 1
            unembedded += not embedded
            d = scored.get(pid)
            if d is not None and d["fired"]:
                passed += 1
                p = posts.get(pid)
                if pid not in have and p is not None and _ask(
                        cur, t, head, p, origin="passive", cos=d["desc"], priority=HISTORY_PRIORITY + _age(at, now),
                        found_by=d["fired"], score=d["probe"]):
                    n += 1
            last = (at, pid)
        if last:
            t["history_at"], t["history_id"] = last
            cur.execute("UPDATE mx_tracks SET history_at = %s, history_id = %s WHERE folder_id = %s",
                        (last[0], last[1], t["folder_id"]))
        if full:
            break
        if len(page) < HISTORY_PAGE:
            cur.execute("UPDATE mx_tracks SET history_done_at = now() WHERE folder_id = %s", (t["folder_id"],))
            t["history_done_at"] = now
            break
    return n, scanned, passed, unembedded


def _stat(acc: Dict[str, Any], phase: str, **counts: int) -> None:
    d = acc.setdefault(phase, {})
    for k, v in counts.items():
        d[k] = d.get(k, 0) + v


def plan(cur: Cursor, *, cap: Optional[int] = None, now: Optional[datetime] = None, days: Any = tasks.SETTING,
         **_kw: Any) -> int:
    """The track tasks to ask (tasks.PLANNERS["track"]): active posts, then passive recent ones, then the history pass,
    while fewer than `cap` (TASKS_PER_RUN) track tasks are open; each phase shares what is left among the tracks.
    How many tasks were added. Each track's counts go to mx_tracks.stats (`last`, and running totals)."""
    now = now or datetime.now(timezone.utc)
    cap = tasks_per_run() if cap is None else cap
    room = cap - open_tasks(cur)
    ts = described(cur)
    if room <= 0 or not ts:
        return 0
    if days is tasks.SETTING:
        days = tasks.reading_window(cur)
    added = 0
    stats: Dict[str, Dict[str, Any]] = {t["folder_id"]: {} for t in ts}
    heads: Dict[str, str] = {}
    profs: Dict[str, Dict[str, Any]] = {}
    exs = {t["folder_id"]: examples(cur, t["folder_id"]) for t in ts}
    cache: Dict[Any, int] = {}   # v10.16: the window's counts, read once for every track's ✓ items
    finders.prefetch(cur, {p for ex in exs.values() for p in ex.get("in") or []}, now=now, cache=cache)
    for t in ts:
        ex = exs[t["folder_id"]]
        heads[t["folder_id"]] = header(cur, t, ex)
        profs[t["folder_id"]] = finders.prepare(cur, t, ex, now=now, cache=cache)   # 0147: the finders, their bar, the classifier

    def share(left: int, k: int) -> int:
        return max(1, -(-left // max(1, k)))

    # 1. active: the reading window, newest first
    for k, t in enumerate(ts):
        left = room - added
        if left <= 0:
            break
        rows = _active_rows(cur, t, days=days, limit=share(left, len(ts) - k), now=now)
        posts = tasks.load_posts(cur, [r[0] for r in rows])
        n = 0
        for pid, at in rows:
            p = posts.get(pid)
            if p is not None and _ask(cur, t, heads[t["folder_id"]], p, origin="active", cos=None, priority=_age(at, now)):
                n += 1
        added += n
        _stat(stats[t["folder_id"]], "active", planned=n)
    # 2. passive, recent
    for k, t in enumerate(ts):
        prof = profs[t["folder_id"]]
        if not prof["ready"]:
            continue
        left = room - added
        scanned, passed, rows = _recent(cur, t, prof, limit=max(0, share(left, len(ts) - k)) if left > 0 else 0, now=now)
        posts = tasks.load_posts(cur, [d["post_id"] for d in rows])
        n = 0
        for d in rows:
            p = posts.get(d["post_id"])
            if p is not None and _ask(cur, t, heads[t["folder_id"]], p, origin="passive", cos=d["desc"],
                                      priority=_age(d["at"], now), found_by=d["fired"], score=d["probe"]):
                n += 1
        added += n
        _stat(stats[t["folder_id"]], "recent", scanned=scanned, passed=passed, planned=n)
    # 3. passive, history (once a version, resumable)
    for k, t in enumerate(ts):
        prof = profs[t["folder_id"]]
        if not prof["ready"] or t.get("history_done_at") is not None:
            continue
        budget = share(room - added, len(ts) - k) if room - added > 0 else 0
        if budget <= 0:
            break
        n, scanned, passed, unembedded = _history(cur, t, prof, heads[t["folder_id"]], budget=budget, now=now)
        added += n
        _stat(stats[t["folder_id"]], "history", scanned=scanned, passed=passed, planned=n, unembedded=unembedded)
    for t in ts:
        s = stats[t["folder_id"]]
        if not s:
            continue
        cur.execute("SELECT stats FROM mx_tracks WHERE folder_id = %s", (t["folder_id"],))
        old = cur.fetchone()[0] or {}
        totals = old.get("totals") or {}
        for phase, d in s.items():
            for key, v in d.items():
                totals[f"{phase}_{key}"] = totals.get(f"{phase}_{key}", 0) + v
        new = {"last": {"at": now.isoformat(), "threshold": profs[t["folder_id"]]["bar"], **s}, "totals": totals}
        cur.execute("UPDATE mx_tracks SET stats = %s::jsonb WHERE folder_id = %s",
                    (json.dumps(new), t["folder_id"]))
        log.info("track %s: %s", t["folder_id"], s)
    return added


# ---- answers -----------------------------------------------------------------------------------------

def after_answer(cur: Cursor, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> None:
    """tasks.record's part: a track verdict fills its items (every post sharing the task); a sub-topic proposal is
    applied."""
    if task["kind"] == KIND:
        _fill(cur, "task_id = %s", (task["id"],), call_id, answer)
    elif task["kind"] == SUB_KIND:
        apply_proposal(cur, task, answer)


# ---- sub-topics --------------------------------------------------------------------------------------

def subtopics(cur: Cursor, folder_id: Any) -> List[Dict[str, Any]]:
    """The track's current sub-topics (oldest first)."""
    cur.execute("""SELECT id::text, name, definition, keys, locked, made_by, created_at FROM mx_track_subtopics
                    WHERE track_id = %s AND valid_to IS NULL ORDER BY created_at, lower(name), id""", (str(folder_id),))
    return [{"id": i, "name": n, "definition": d, "keys": list(k or []), "locked": lk, "made_by": m, "created_at": at}
            for i, n, d, k, lk, m, at in cur.fetchall()]


def assign(subs: Sequence[Dict[str, Any]], raw: Optional[str]) -> Optional[str]:
    """The sub-topic an item's judge subtopic goes to: the one holding its string, else the one named like it."""
    key = fold_key(raw)
    if not key:
        return None
    for s in subs:
        if key in s["keys"]:
            return s["id"]
    for s in subs:
        if key == fold_key(s["name"]):
            return s["id"]
    return None


_ITEM_RE = re.compile(r"^\[(\d+)\] \((.*?)\) ", re.M)


def subtopics_input(track: Dict[str, Any], items: Sequence[Dict[str, Any]], locked: Sequence[str]) -> str:
    lines = [f"TRACK: {track['name']}", f"Belongs: {track['description']}"]
    if locked:
        lines.append("Locked: " + "; ".join(locked))
    lines.append("")
    lines.append("ITEMS:")
    for n, it in enumerate(items, 1):
        title = re.sub(r"\s+", " ", it.get("title") or "").strip()[:EXAMPLE_CHARS]
        why = re.sub(r"\s+", " ", it.get("why") or "").strip()[:160]
        lines.append(f"[{n}] ({it.get('subtopic') or '-'}) {title} — {why}")
    return "\n".join(lines)


def numbered(input: str) -> Dict[int, str]:
    """{item number: its judge subtopic} of a sub-topics question."""
    return {int(n): raw for n, raw in _ITEM_RE.findall(input)}


def plan_subtopics(cur: Cursor, *, now: Optional[datetime] = None, **_kw: Any) -> int:
    """A `subtopics` task for each track with SUBTOPIC_MIN_ITEMS+ items and no proposal in SUBTOPIC_EVERY (or none
    yet) and none open: how many were added."""
    now = now or datetime.now(timezone.utc)
    schemas.ensure_guides(cur)
    added = 0
    for t in described(cur):
        cur.execute("""SELECT max(created_at) FILTER (WHERE status = 'answered'),
                              count(*) FILTER (WHERE status IN ('open', 'leased'))
                         FROM mx_tasks WHERE kind = %s AND a = %s""", (SUB_KIND, t["folder_id"]))
        last, pending = cur.fetchone()
        if pending or (last is not None and now - last < SUBTOPIC_EVERY):
            continue
        items = [it for it in placed(cur, t)["items"] if it["place"] in ("track", "joined")]
        if len(items) < SUBTOPIC_MIN_ITEMS:
            continue
        if last is not None and not any(it["answered_at"] and it["answered_at"] > last for it in items):
            continue
        items = sorted(items, key=lambda it: it["at"] or now, reverse=True)[:SUBTOPIC_ITEMS]
        text = subtopics_input(t, items, locked_names(cur, t["folder_id"]))
        if repo.add_task(cur, kind=SUB_KIND, guide=schemas.KINDS[SUB_KIND].guide, subject_kind="track", input=text,
                         a=t["folder_id"])[1]:
            added += 1
    return added


def apply_proposal(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> int:
    """A proposal's sub-topics: the unlocked current ones closed, the proposed ones added (a name a locked one has
    gives its strings to that one). Each judge subtopic string goes to the proposed sub-topic most of its items went
    to. How many were added."""
    folder = str(task["a"])
    raw = numbered(task["input"])
    votes: Dict[str, Counter] = defaultdict(Counter)
    proposed = []
    for k, s in enumerate(answer.get("subtopics") or []):
        name = _clean(s.get("name"), 80)
        if not name:
            continue
        proposed.append((k, name, _clean(s.get("definition"), 300)))
        for n in s.get("items") or []:
            key = fold_key(raw.get(n))
            if key and key != "-":
                votes[key][k] += 1
    keys: Dict[int, List[str]] = defaultdict(list)
    for key, c in votes.items():
        keys[c.most_common(1)[0][0]].append(key)
    current = subtopics(cur, folder)
    locked = {fold_key(s["name"]): s for s in current if s["locked"]}
    cur.execute("UPDATE mx_track_subtopics SET valid_to = now() WHERE track_id = %s AND valid_to IS NULL AND NOT locked",
                (folder,))
    added = 0
    for k, name, definition in proposed:
        ks = sorted(set(keys.get(k, [])) | {fold_key(name)})
        same = locked.get(fold_key(name))
        if same is not None:
            cur.execute("UPDATE mx_track_subtopics SET keys = %s WHERE id = %s",
                        (sorted(set(same["keys"]) | set(ks)), same["id"]))
            continue
        cur.execute("""INSERT INTO mx_track_subtopics (track_id, name, definition, keys, task_id)
                       VALUES (%s, %s, %s, %s, %s)""", (folder, name, definition, ks, task["id"]))
        added += 1
    return added


def _replace(cur: Cursor, sub: Dict[str, Any], **change: Any) -> str:
    """A sub-topic changed by the owner: the old row closed, the new one (locked, the owner's) added: its id."""
    row = {**sub, **change}
    cur.execute("UPDATE mx_track_subtopics SET valid_to = now() WHERE id = %s", (sub["id"],))
    cur.execute("""INSERT INTO mx_track_subtopics (track_id, name, definition, keys, locked, made_by)
                   VALUES (%s, %s, %s, %s, true, 'owner') RETURNING id::text""",
                (row["track_id"], row["name"], row.get("definition"), sorted(set(row["keys"]))))
    return cur.fetchone()[0]


def edit_subtopics(cur: Cursor, folder_id: Any, *, action: str, id: Optional[str] = None, ids: Sequence[str] = (),
                   name: Optional[str] = None, definition: Optional[str] = None, keys: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """The owner's edit: rename (id, name[, definition]), merge (ids into id), split (id, name, keys: its strings
    that go to the new one), lock / unlock (id), add (name[, definition]). An edit locks what it makes. The current
    sub-topics after it. ValueError: a bad edit; KeyError: no such sub-topic."""
    folder = str(folder_id)
    subs = {s["id"]: dict(s, track_id=folder) for s in subtopics(cur, folder)}

    def one(i: Optional[str]) -> Dict[str, Any]:
        if not i or i not in subs:
            raise KeyError(i)
        return subs[i]

    name = _clean(name, 80)
    if action == "rename":
        s = one(id)
        if not name:
            raise ValueError("name: the new name")
        _replace(cur, s, name=name, definition=_clean(definition, 300) or s.get("definition"),
                 keys=set(s["keys"]) | {fold_key(s["name"])})
    elif action == "merge":
        target = one(id)
        others = [one(i) for i in ids if i != id]
        if not others:
            raise ValueError("ids: the sub-topics to merge into this one")
        ks = set(target["keys"])
        for o in others:
            ks |= set(o["keys"]) | {fold_key(o["name"])}
        new_id = _replace(cur, target, keys=ks)
        for o in others:
            cur.execute("UPDATE mx_track_subtopics SET valid_to = now(), merged_into = %s WHERE id = %s", (new_id, o["id"]))
    elif action == "split":
        s = one(id)
        moved = {fold_key(k) for k in keys if fold_key(k)}
        if not name or not moved:
            raise ValueError("name and keys: the new sub-topic and the strings it takes")
        if not moved <= set(s["keys"]):
            raise ValueError("keys: strings of this sub-topic")
        _replace(cur, s, keys=set(s["keys"]) - moved)
        cur.execute("""INSERT INTO mx_track_subtopics (track_id, name, definition, keys, locked, made_by)
                       VALUES (%s, %s, %s, %s, true, 'owner')""", (folder, name, _clean(definition, 300), sorted(moved)))
    elif action in ("lock", "unlock"):
        s = one(id)
        cur.execute("UPDATE mx_track_subtopics SET locked = %s WHERE id = %s", (action == "lock", s["id"]))
    elif action == "add":
        if not name:
            raise ValueError("name: the new sub-topic's name")
        cur.execute("""INSERT INTO mx_track_subtopics (track_id, name, definition, keys, locked, made_by)
                       VALUES (%s, %s, %s, %s, true, 'owner')""", (folder, name, _clean(definition, 300), [fold_key(name)]))
    else:
        raise ValueError("action: rename, merge, split, lock, unlock or add")
    return subtopics(cur, folder)


# ---- where each item goes: precision, ranking, auto-join -----------------------------------------------

def wilson(k: int, n: int) -> float:
    from insight_core.markx.labels import wilson as _w
    return _w(k, n)[0]


def band(conf: Optional[float]) -> float:
    c = conf or 0.0
    return next(e for e in CONF_EDGES if c >= e - 1e-9)


def calibrate(labelled: Sequence[Tuple[float, bool]]) -> Dict[str, Any]:
    """From the owner's labels on passive `in`s, [(confidence, ✓)]: {labels, right, precision, lower, bands: [{edge,
    labels, right, precision, lower}] (at or above each edge), join_edge (the lowest edge that passes the auto-join
    bar, or None)}."""
    n, k = len(labelled), sum(1 for _, ok in labelled if ok)
    bands, join_edge, above = [], None, 0
    for e in CONF_EDGES:
        got = [ok for c, ok in labelled if (c or 0) >= e - 1e-9]
        bn, bk = len(got), sum(got)
        lo = wilson(bk, bn) if bn else 0.0
        bands.append({"edge": e, "labels": bn, "right": bk, "precision": round(bk / bn, 4) if bn else None,
                      "lower": round(lo, 4)})
        # a band joins only on labels of its own: one with none would borrow the bands above's precision
        if bn > above and bn >= JOIN_MIN_LABELS and bk / bn >= JOIN_PRECISION and lo >= JOIN_LOWER:
            join_edge = e
        above = bn
    return {"labels": n, "right": k, "precision": round(k / n, 4) if n else None,
            "lower": round(wilson(k, n), 4) if n else None, "bands": bands, "join_edge": join_edge,
            "bar": {"precision": JOIN_PRECISION, "lower": JOIN_LOWER, "labels": JOIN_MIN_LABELS}}


def rank_of(cal: Dict[str, Any], conf: Optional[float]) -> float:
    """A Discover suggestion's rank: its band's calibrated precision (Wilson lower bound at or above the band), or its
    confidence until RANK_MIN_LABELS labels."""
    if cal["labels"] < RANK_MIN_LABELS:
        return float(conf or 0)
    e = band(conf)
    b = next(b for b in cal["bands"] if b["edge"] == e)
    return float(b["lower"])


def _items(cur: Cursor, folder_id: Any, *, shown: bool = True) -> List[Dict[str, Any]]:
    """The track's judged posts: each post's newest verdict (any version). v10.14: `shown` False reads only what a
    place needs (post, verdict, confidence, source), for the sidebar's counts: a quarter of the time (the scale copy)."""
    if not shown:
        cur.execute("""SELECT DISTINCT ON (i.post_id) i.post_id::text, i.verdict, i.confidence, p.source_id::text
                         FROM mx_track_items i JOIN posts p ON p.id = i.post_id
                        WHERE i.track_id = %s AND i.verdict IS NOT NULL
                        ORDER BY i.post_id, i.version DESC""", (str(folder_id),))
        return [dict(zip(("post_id", "verdict", "confidence", "source_id"), r)) for r in cur.fetchall()]
    cur.execute(f"""SELECT DISTINCT ON (i.post_id) i.post_id::text, i.verdict, i.confidence, i.subtopic, i.why, i.origin,
                           i.cos, i.answered_at, i.version, i.found_by, p.title, p.url, {_date()}, p.source_id::text,
                           COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                    s.handle_or_url)
                      FROM mx_track_items i JOIN posts p ON p.id = i.post_id JOIN sources s ON s.id = p.source_id
                     WHERE i.track_id = %s AND i.verdict IS NOT NULL
                     ORDER BY i.post_id, i.version DESC""", (str(folder_id),))
    cols = ("post_id", "verdict", "confidence", "subtopic", "why", "origin", "cos", "answered_at", "version", "found_by",
            "title", "url", "at", "source_id", "source")
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def active_sources(cur: Cursor, folder_id: Any) -> List[Dict[str, Any]]:
    cur.execute("""SELECT s.id::text, COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''),
                                               NULLIF(btrim(s.settings->>'name'), ''), s.handle_or_url)
                     FROM source_folders sf JOIN sources s ON s.id = sf.source_id WHERE sf.folder_id = %s
                    ORDER BY 2""", (str(folder_id),))
    return [{"id": i, "name": n} for i, n in cur.fetchall()]


def placed(cur: Cursor, track: Dict[str, Any], *, shown: bool = True) -> Dict[str, Any]:
    """Every judged post of the track with its place (track, joined, discover, off, out) and rank: {items, calibration}.
    `off` (issue 0200): Haiku's in from a passive source the owner switched off (repo_stories.switched_off), which is
    never suggested: neither in Discover nor joined. Its calibration is unchanged (the owner's labels count).
    `shown` False: the items carry only their post, verdict, confidence, source and place (the counts' read)."""
    from insight_core.db.repo_stories import switched_off
    folder = track["folder_id"]
    off = switched_off(cur)
    active = {s["id"] for s in active_sources(cur, folder)}
    marks = labels(cur, folder)
    items = _items(cur, folder, shown=shown)
    for it in items:
        it["active"] = it["source_id"] in active
        it["label"] = marks.get(it["post_id"], (None,))[0]
    cal = calibrate([(it["confidence"], it["label"] == "in") for it in items
                     if it["verdict"] and not it["active"] and it["label"]])
    for it in items:
        if it["label"] == "out":
            it["place"] = "out"
        elif it["label"] == "in" or (it["verdict"] and it["active"]):
            it["place"] = "track"
        elif it["verdict"] and it["source_id"] in off:
            it["place"] = "off"
        elif it["verdict"]:
            joins = cal["join_edge"] is not None and (it["confidence"] or 0) >= cal["join_edge"] - 1e-9
            it["place"] = "joined" if joins else "discover"
        else:
            it["place"] = "out"
        it["rank"] = rank_of(cal, it["confidence"])
        it["calibrated"] = cal["labels"] >= RANK_MIN_LABELS
    return {"items": items, "calibration": cal}


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _shown(it: Dict[str, Any]) -> Dict[str, Any]:
    return {"post_id": it["post_id"], "title": it["title"], "url": it["url"], "at": _iso(it["at"]),
            "source": it["source"], "source_id": it["source_id"],
            "confidence": None if it["confidence"] is None else round(it["confidence"], 3),
            "subtopic": it["subtopic"], "why": it["why"], "origin": "active" if it["active"] else "passive",
            "place": it["place"], "label": it["label"], "rank": round(it["rank"], 4), "calibrated": it["calibrated"],
            "found_by": list(it.get("found_by") or [])}


def suggestions(cur: Cursor, folder_id: Optional[Any] = None, *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Passive sources with SUGGEST_MIN+ items judged `in` (not ✗ by the owner) in SUGGEST_DAYS days, per track:
    [{track, track_name, source_id, source, n}], most first. Never a source switched off (issue 0200)."""
    from insight_core.db.repo_stories import switched_off
    now = now or datetime.now(timezone.utc)
    off = switched_off(cur)
    out = []
    for t in described(cur):
        if folder_id is not None and t["folder_id"] != str(folder_id):
            continue
        from insight_core.markx import track_kept
        kept = track_kept.suggestible(cur, t)   # issue 0195: the kept placement's suggestible items, else placed live
        got = kept if kept is not None else [it for it in placed(cur, t)["items"]
                                             if (it["verdict"] or it["label"] == "in") and it["label"] != "out"
                                             and not it["active"] and it["source_id"] not in off]
        c: Counter = Counter()
        names = {}
        for it in got:
            if it["at"] and it["at"] >= now - timedelta(days=SUGGEST_DAYS):
                c[it["source_id"]] += 1
                names[it["source_id"]] = it["source"]
        for sid, n in c.most_common():
            if n >= SUGGEST_MIN:
                out.append({"track": t["folder_id"], "track_name": t["name"], "source_id": sid, "source": names[sid], "n": n})
    return sorted(out, key=lambda x: -x["n"])


def activate(cur: Cursor, folder_id: Any, source_id: Any) -> bool:
    """The owner's "make it active": the source joins the folder (as Sources adds one). Whether it was added."""
    from insight_core.db.repo_folders import FoldersRepository
    cur.execute("SELECT 1 FROM sources WHERE id = %s", (str(source_id),))
    if cur.fetchone() is None or get(cur, folder_id) is None:
        raise KeyError(source_id)
    return FoldersRepository("").add_source_to_folder(cur, str(folder_id), str(source_id))


def footer(cur: Cursor, folder_id: Any, items: Sequence[Dict[str, Any]], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """What the track costs and brings: {cost_usd (all), cost_per_day and items_per_day (the last 7 days), tasks}."""
    now = now or datetime.now(timezone.utc)
    cur.execute("""WITH t AS (SELECT DISTINCT task_id FROM mx_track_items WHERE track_id = %(f)s
                              UNION SELECT id FROM mx_tasks WHERE kind = %(sub)s AND a = %(f)s)
                   SELECT COALESCE(sum(c.cost_usd), 0), COALESCE(sum(c.cost_usd) FILTER (WHERE c.created_at >= %(since)s), 0),
                          (SELECT count(*) FROM t)
                     FROM mx_calls c WHERE c.task_id IN (SELECT task_id FROM t)""",
                {"f": str(folder_id), "sub": SUB_KIND, "since": now - timedelta(days=7)})
    total, week, n = cur.fetchone()
    recent = sum(1 for it in items if it["place"] in ("track", "joined") and it["answered_at"]
                 and it["answered_at"] >= now - timedelta(days=7))
    return {"cost_usd": round(float(total), 4), "cost_per_day": round(float(week) / 7, 4),
            "items_per_day": round(recent / 7, 2), "tasks": n}


def page(cur: Cursor, folder_id: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The track page (GET /api/markx/tracks/{id}). KeyError: no such folder."""
    cur.execute("SELECT name, kind FROM folders WHERE id = %s", (str(folder_id),))
    f = cur.fetchone()
    if f is None:
        raise KeyError(folder_id)
    t = get(cur, folder_id)
    base = {"id": str(folder_id), "name": f[0], "kind": f[1], "topic": is_topic(t),
            "description": t["description"] if t else None, "excludes": t["excludes"] if t else None,
            "sources": active_sources(cur, folder_id)}
    if not is_topic(t):
        return {"track": base, "sections": [], "discover": [], "counts": {}, "calibration": None, "suggestions": [],
                "examples": {"in": [], "out": []}, "subtopics": [], "footer": None, "prefilter": None}
    from insight_core.markx import track_kept
    got = track_kept.placed(cur, t)   # issue 0195: the kept placement (its shown items filled below), else live
    kept = got is not None
    got = got if kept else placed(cur, t)
    items, cal = got["items"], got["calibration"]
    subs = subtopics(cur, folder_id)
    groups: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for it in items:
        if it["place"] in ("track", "joined"):
            groups[assign(subs, it["subtopic"])].append(it)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    if kept:   # the items the page shows get their title, address, source and why
        track_kept.fill(cur, t, [it for g in groups.values()
                                 for it in sorted(g, key=lambda it: it["at"] or epoch, reverse=True)[:SECTION_ITEMS]]
                        + sorted((it for it in items if it["place"] == "discover"),
                                 key=lambda it: (-it["rank"], -(it["confidence"] or 0),
                                                 -(it["at"] or epoch).timestamp()))[:DISCOVER_ITEMS])
    sections = []
    for s in sorted(subs, key=lambda s: -len(groups.get(s["id"], []))):
        its = sorted(groups.get(s["id"], []), key=lambda it: it["at"] or epoch, reverse=True)
        sections.append({"id": s["id"], "name": s["name"], "definition": s["definition"], "locked": s["locked"],
                         "made_by": s["made_by"], "keys": s["keys"], "count": len(its),
                         "items": [_shown(it) for it in its[:SECTION_ITEMS]]})
    other = sorted(groups.get(None, []), key=lambda it: it["at"] or epoch, reverse=True)
    if other:
        sections.append({"id": None, "name": "Other" if subs else "In this track", "definition": None, "locked": False,
                         "made_by": None, "keys": [], "count": len(other), "items": [_shown(it) for it in other[:SECTION_ITEMS]]})
    disc = sorted((it for it in items if it["place"] == "discover"),
                  key=lambda it: (-it["rank"], -(it["confidence"] or 0), -(it["at"] or epoch).timestamp()))
    counts = Counter(it["place"] for it in items)
    cur.execute("""SELECT count(*) FILTER (WHERE verdict IS NULL) FROM mx_track_items WHERE track_id = %s AND version = %s""",
                (t["folder_id"], t["version"]))
    counts["waiting"] = cur.fetchone()[0]
    counts["judged"] = len(items)
    ex = examples(cur, folder_id)
    shown_ex = tasks.load_posts(cur, ex["in"][:20] + ex["out"][:20])
    prof = profile(cur, t, ex)
    probes = finders.probe_rows(cur, folder_id, t["version"])
    stats = t.get("stats") or {}
    return {"track": {**base, "version": t["version"], "version_at": _iso(t["version_at"])},
            "sections": sections, "discover": [_shown(it) for it in disc[:DISCOVER_ITEMS]],
            "counts": dict(counts), "calibration": cal, "suggestions": suggestions(cur, folder_id, now=now),
            "examples": {k: [{"post_id": p, "title": shown_ex[p].title or shown_ex[p].text[:EXAMPLE_CHARS]}
                             for p in ex[k][:20] if p in shown_ex] for k in ("in", "out")},
            "subtopics": [{**s, "created_at": _iso(s["created_at"]), "count": len(groups.get(s["id"], []))} for s in subs],
            "footer": footer(cur, folder_id, items, now=now),
            "prefilter": {"threshold": prof["threshold"], "ready": prof["vector"] is not None, "pos": prof["pos"],
                          "neg": prof["neg"], "description": prof["description"], "last": stats.get("last"),
                          "totals": stats.get("totals"),
                          "history": {"done": _iso(t["history_done_at"]), "at": _iso(t["history_at"])},
                          # 0147: the example posts of this version and how many items each finder found
                          "probes": sum(1 for r in probes if not r["near"]), "near_misses": sum(1 for r in probes if r["near"]),
                          "found_by": dict(Counter(f for it in items for f in (it.get("found_by") or [])))}}


def label(cur: Cursor, folder_id: Any, *, post: Any, answer: str, note: Optional[str] = None) -> Dict[str, Any]:
    """The owner's ✓ / ✗ on a post for the track (in, out or undo). ValueError: another answer; KeyError: no such
    track or post."""
    if answer not in ANSWERS:
        raise ValueError(f"answer: one of {', '.join(ANSWERS)}")
    if not is_topic(get(cur, folder_id)):
        raise KeyError(folder_id)
    cur.execute("SELECT 1 FROM posts WHERE id = %s", (str(post),))
    if cur.fetchone() is None:
        raise KeyError(post)
    lid = repo.add_label(cur, item_kind=ITEM_KIND, a=str(post), b=str(folder_id), answer=answer,
                         note=(note or "").strip() or None)
    return {"id": str(lid), "label": None if answer == "undo" else answer}


def list_tracks(cur: Cursor) -> List[Dict[str, Any]]:
    """Every folder, with whether it is a topic (GET /api/markx/tracks)."""
    cur.execute("""SELECT f.id::text, f.name, f.kind, t.description, t.version FROM folders f
                    LEFT JOIN mx_tracks t ON t.folder_id = f.id ORDER BY f.sort_order, f.name""")
    return [{"id": i, "name": n, "kind": k, "topic": bool((d or "").strip()), "description": d, "version": v}
            for i, n, k, d, v in cur.fetchall()]
