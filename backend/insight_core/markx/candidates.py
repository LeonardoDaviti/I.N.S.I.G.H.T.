"""Mark X Shadow's candidates (issue 0086 B): the pairs worth a question, found on the server when vectors arrive.

A candidate is a row of mx_candidates (kind, a, b, source, score), written once per source and never deleted
(keep everything). It is keyed by posts, never by a Mark IX story id (the build plan's corrections 2):
  - kind `post_post`: two posts, `a` the earlier (by Mark X's time, then id). S5 asks it as a `join` when one of
    them is in a story then, as a `pair` when neither is;
  - kind `story_story`: two Mark IX stories as they were when found, each by its earliest member post. S5 builds
    the `merge` question from today's members of the stories those posts are in.

The sources, their thresholds (0086 B's, none tuned) and the basics they read are Pairing's (markx/pairing.py, issue 0166:
the relation `same_story`'s row of its policy table); this module is the job that runs them. The four sources:
  - `embedding`: a post's nearest posts by BGE-M3 cosine among other sources within 72 hours, at cosine >= 0.65,
    not already in one Mark IX story. Nearest is the prototype's (cands.py): the 8 nearest of either post, among
    the posts not saved by you. And story pairs whose centroids (the mean of their members' vectors) are at
    cosine >= 0.70, at most 14 days apart (by their first posts).
  - `link`: Mark IX's own joins (story_posts' parent edges: a link, a citation, a quote, a thread, a copy), the
    check's input. Read, never changed.
  - `entity`: posts of other sources within 72 hours sharing a specific main subject: an ent-v3 mention with role
    `subject`, the same name key and the same version (none on both, or equal), of a type that names one thing
    (model, product, software, paper, dataset), never an org or a person alone (0090: 7 of 8 right so limited,
    7 of 11 without the limit). Not already in one Mark IX story.
  - `burst`: 0089's late bursts (experiment W): posts of different places linking the same page within 72 hours
    of each other, both more than 72 hours after the page's first linker, so Mark IX's link window (measured from
    the first linker) can't join them. Read as Mark IX reads links (kept links, a stored post's link and a home
    page are not pages; a roundup counts its first link only). Not already in one Mark IX story. 23 of 35 such
    pairs were one story or a follow-up: a question, never a rule.

When (markx/jobs.py): `jobs.pending.note(post_ids)` after vectors are stored (POST /api/markx/embeddings) collects the posts, and the
job runs DEBOUNCE seconds after the last upload, in a thread with a transaction of its own (`run`). Every source
is idempotent, so running a post twice adds nothing. Entities arrive later than vectors (they are Haiku's): the
job also takes the posts whose mentions were written since its last run (the first run in a process: the last
day), so S5's hourly decision job can call `run` too. Mark IX's tables are only read.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from psycopg import Cursor

from insight_core.markx import pairing, schemas

log = logging.getLogger(__name__)

# The sources, their gates and the basics are Pairing's (markx/pairing.py, issue 0166); these names stay for callers.
MODEL = pairing.MODEL
POST_POST, STORY_STORY = pairing.POST_POST, pairing.STORY_STORY
SPECIFIC_TYPES = pairing.SPECIFIC_TYPES
ROUNDUP_ANCHORS = pairing.ROUNDUP_ANCHORS
NOT_VOICE = tuple(pairing.NOT_VOICE)
ENTITY_GUIDE = "ent-v3"       # 0133: the default arm; the subjects are read from the current set (mx_mentions_now)
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
    the happening candidates of all of these and of the posts read since). A post's embedding neighbours, links and bursts
    were found when its vector came, so its new mentions only ask the entity source (0121 Decided 7, 0116's pattern:
    the review measured 75 s, 35 s of CPU, finding every mentioned post's neighbours again for 0 new candidates)."""
    ids = set(map(str, post_ids))
    out = find(cur, ids, model=model)
    mentioned: set = set()
    if since is not None:
        mentioned = set(mentioned_since(cur, since)) - ids
        out.update(find(cur, mentioned, model=model, sources=("entity",)))
    if pairing.happening_on(cur):   # 0166: the happening source, off by default (a reading or mentions change a key)
        read = set(read_since(cur, since)) if since is not None else set()
        out.update(find(cur, ids | mentioned | read, model=model, sources=("happening",)))
    return out


def read_since(cur: Cursor, since: datetime) -> List[str]:
    """Posts whose read-v2 reading was written since (their call's time)."""
    cur.execute("""SELECT DISTINCT r.post_id::text FROM mx_readings r JOIN mx_calls c ON c.id = r.call_id
                    WHERE r.guide = 'read-v2' AND c.created_at >= %s""", (since,))
    return [r[0] for r in cur.fetchall()]


# ---- the story window's backfill (0144 A2) ------------------------------------------------------------

_UNFOUND = """FROM posts p
               WHERE COALESCE(p.surfaced_at, p.published_at, p.fetched_at) >= %(since)s
                 AND EXISTS (SELECT 1 FROM mx_embeddings e WHERE e.post_id = p.id AND e.model = %(model)s)
                 AND NOT EXISTS (SELECT 1 FROM mx_candidate_posts c WHERE c.post_id = p.id AND c.found_at IS NOT NULL)"""


def unfound(cur: Cursor, since: datetime, limit: int, model: str = MODEL) -> List[str]:
    """The embedded posts since `since` the finder never read (no mx_candidate_posts row found), newest first."""
    cur.execute(f"""SELECT p.id::text {_UNFOUND}
                     ORDER BY COALESCE(p.surfaced_at, p.published_at, p.fetched_at) DESC, p.id LIMIT %(limit)s""",
                {"since": since, "model": model, "limit": limit})
    return [r[0] for r in cur.fetchall()]


def unfound_count(cur: Cursor, since: datetime, model: str = MODEL) -> int:
    cur.execute(f"SELECT count(*) {_UNFOUND}", {"since": since, "model": model})
    return cur.fetchone()[0]


def backfill(cur: Cursor, now: datetime, *, limit: Optional[int] = None, model: str = MODEL) -> Dict[str, Any]:
    """0144 A2: while the story window reaches past 30 days, the candidates of the posts one step past the decision
    window (story_window.next_since) that the finder never read, `limit` (CANDIDATE_PAGE) a run, newest first, by the
    same four sources and rules; each is then marked found (mx_candidate_posts). Resumable: the next run takes the
    posts still unread. {} when the window is 30 days or less."""
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

