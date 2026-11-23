"""Mark X's candidate finder: the pairs worth a question, found on the server when vectors arrive (issue 0086 B).

A candidate is a row of mx_candidates (kind, a, b, source, score), written once per source and never deleted, keyed by
posts, never by a Mark IX story id: `post_post` (two posts, `a` the earlier; asked as a join or a pair) or
`story_story` (two Mark IX stories, each by its earliest member post; asked as a merge). The sources, their
thresholds and gates are Pairing's (markx/pairing.py, relation `same_story`); this module is the job that runs them
(`run`, from markx/jobs.py): every source over the newly embedded posts, and the entity source over posts whose
mentions were written since. Every source is idempotent. Mark IX's tables are only read.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from psycopg import Cursor

from insight_core.markx import pairing, schemas

log = logging.getLogger(__name__)

# the sources, their gates and the basics are Pairing's (markx/pairing.py); these names stay for callers
MODEL = pairing.MODEL
POST_POST, STORY_STORY = pairing.POST_POST, pairing.STORY_STORY
SPECIFIC_TYPES = pairing.SPECIFIC_TYPES
ROUNDUP_ANCHORS = pairing.ROUNDUP_ANCHORS
Posts = pairing.Posts
document_key = pairing.document_key
_SAME = pairing.POLICIES[pairing.SAME_STORY]
WINDOW, EMBEDDING_MIN, NEAREST = _SAME.window, _SAME.cosine, _SAME.nearest
STORY_MIN, STORY_DAYS, BURST_GAP = _SAME.story_cosine, _SAME.story_window, _SAME.late_after
spans = pairing.spans


# ---- the job ---------------------------------------------------------------------------------------

def find(cur: Cursor, post_ids: Iterable[str], *, model: str = MODEL,
         sources: Sequence[str] = ("embedding", "link", "entity", "burst")) -> Counter:
    """The candidates of these posts, every source: {source: pairs added} (story pairs as `embedding:story`).
    Pairing's same-story sources; `embedding` is the post pairs and the story centroids' pairs."""
    new = sorted({str(p) for p in post_ids})
    out: Counter = Counter()
    if not new:
        return out
    named = [x for s in sources for x in (("embedding", "centroid") if s == "embedding" else (s,))]
    got = pairing.find(cur, pairing.SAME_STORY, new, sources=named, model=model)
    for s in named:
        out["embedding:story" if s == "centroid" else s] += got[s]
    return out


def mentioned_since(cur: Cursor, since: datetime) -> List[str]:
    """Posts whose ent-v3 mentions were written since (their call's time)."""
    cur.execute("""SELECT DISTINCT m.post_id::text FROM mx_mentions_now m JOIN mx_calls c ON c.id = m.call_id
                    WHERE m.guide = ANY(%s) AND c.created_at >= %s""", (schemas.mention_guides(), since))
    return [r[0] for r in cur.fetchall()]


def run(cur: Cursor, post_ids: Iterable[str] = (), *, since: Optional[datetime] = None, model: str = MODEL) -> Counter:
    """One run: every source's candidates of `post_ids` (the posts embedded since the last run), and the entity
    candidates of the posts whose mentions were written since `since` (and, while Pairing's happening source is on,
    the happening candidates of these and of the posts read since). A post's other sources were found when its vector
    came, so its new mentions only ask the entity source."""
    ids = set(map(str, post_ids))
    out = find(cur, ids, model=model)
    mentioned: set = set()
    if since is not None:
        mentioned = set(mentioned_since(cur, since)) - ids
        out.update(find(cur, mentioned, model=model, sources=("entity",)))
    if pairing.happening_on(cur):   # the happening source, off by default (a reading or mentions change a key)
        read = set(read_since(cur, since)) if since is not None else set()
        out.update(find(cur, ids | mentioned | read, model=model, sources=("happening",)))
    return out


def read_since(cur: Cursor, since: datetime) -> List[str]:
    """Posts whose read-v2 reading (or ent-v5's, while its switch is on) was written since (their call's time)."""
    from insight_core.markx import reading5
    cur.execute("""SELECT DISTINCT r.post_id::text FROM mx_readings r JOIN mx_calls c ON c.id = r.call_id
                    WHERE r.guide = ANY(%s) AND c.created_at >= %s""", (reading5.guides(cur, "read-v2"), since))
    return [r[0] for r in cur.fetchall()]


# ---- the story window's backfill -------------------------------------------------------------------------

_UNFOUND = f"""FROM posts p
               WHERE {pairing.ordinary_date('p')} >= %(since)s
                 AND EXISTS (SELECT 1 FROM mx_embeddings e WHERE e.post_id = p.id AND e.model = %(model)s)
                 AND NOT EXISTS (SELECT 1 FROM mx_candidate_posts c WHERE c.post_id = p.id AND c.found_at IS NOT NULL)"""


def unfound(cur: Cursor, since: datetime, limit: int, model: str = MODEL) -> List[str]:
    """The embedded posts since `since` the finder never read (no mx_candidate_posts row found), newest first."""
    cur.execute(f"""SELECT p.id::text {_UNFOUND}
                     ORDER BY {pairing.ordinary_date('p')} DESC, p.id LIMIT %(limit)s""",
                {"since": since, "model": model, "limit": limit})
    return [r[0] for r in cur.fetchall()]


def unfound_count(cur: Cursor, since: datetime, model: str = MODEL) -> int:
    cur.execute(f"SELECT count(*) {_UNFOUND}", {"since": since, "model": model})
    return cur.fetchone()[0]


def backfill(cur: Cursor, now: datetime, *, limit: Optional[int] = None, model: str = MODEL) -> Dict[str, Any]:
    """While the story window reaches past 30 days, the candidates of the posts one step past the decision window
    (story_window.next_since) the finder never read, `limit` (CANDIDATE_PAGE) a run, newest first, by the same sources;
    each is then marked found (mx_candidate_posts). Resumable. {} when the window is 30 days or less."""
    from insight_core.markx import story_window
    since = story_window.next_since(cur, now)
    if since is None:
        return {}
    ids = unfound(cur, since, story_window.CANDIDATE_PAGE if limit is None else limit, model)
    counts = find(cur, ids, model=model) if ids else Counter()
    if ids:
        cur.execute("""INSERT INTO mx_candidate_posts (post_id, noted_at, found_at)
                       SELECT unnest(%s::uuid[]), %s, %s
                       ON CONFLICT (post_id) DO UPDATE SET found_at = EXCLUDED.found_at""", (ids, now, now))
    return {"since": since.isoformat(), "posts": len(ids), "counts": dict(counts),
            "left": unfound_count(cur, since, model)}

