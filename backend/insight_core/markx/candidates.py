"""Mark X Shadow's candidates (issue 0086 B): the pairs worth a question, found on the server when vectors arrive.

A candidate is a row of mx_candidates (kind, a, b, source, score), written once per source and never deleted
(keep everything). It is keyed by posts, never by a Mark IX story id (the build plan's corrections 2):
  - kind `post_post`: two posts, `a` the earlier (by Mark X's time, then id). S5 asks it as a `join` when one of
    them is in a story then, as a `pair` when neither is;
  - kind `story_story`: two Mark IX stories as they were when found, each by its earliest member post. S5 builds
    the `merge` question from today's members of the stories those posts are in.

The four sources, at 0086 B's thresholds (none tuned here):
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

import bisect
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import Cursor

from insight_core.markx import repo
from insight_core.utils.post_links import is_home, source_kind

log = logging.getLogger(__name__)

MODEL = "bge-m3"
WINDOW = timedelta(hours=72)
EMBEDDING_MIN = 0.65
NEAREST = 8                       # the prototype's k (cands.py)
STORY_MIN = 0.70
STORY_DAYS = timedelta(days=14)
BURST_GAP = timedelta(hours=72)   # Mark IX's link window (story_rules.LINK_WITHIN), measured from the first linker
ROUNDUP_ANCHORS = 3               # story_rules.ROUNDUP_ANCHORS: a post with 3+ links is about its first only
ENTITY_GUIDE = "ent-v3"
SPECIFIC_TYPES = ("model", "product", "software", "paper", "dataset")
NOT_VOICE = ("saved",)
POST_POST, STORY_STORY = "post_post", "story_story"


# ---- what every source reads -----------------------------------------------------------------------

class Posts:
    """Mark X's time, source and kind of the embedded posts (and of any post loaded), and their Mark IX stories."""

    def __init__(self, cur: Cursor, model: str = MODEL, extra: Iterable[str] = ()) -> None:
        self.cur = cur
        cur.execute("SELECT post_id::text FROM mx_embeddings WHERE model = %s", (model,))
        self.embedded: Set[str] = {r[0] for r in cur.fetchall()}
        self.source: Dict[str, str] = {}
        self.at: Dict[str, datetime] = {}
        self.kind: Dict[str, str] = {}
        self.load(self.embedded | set(extra))
        cur.execute("SELECT post_id::text, story_id::text FROM story_posts")
        self.story: Dict[str, str] = dict(cur.fetchall())
        self.order = sorted((self.at[p], p) for p in self.embedded if p in self.at)
        self.times = [t for t, _ in self.order]

    def load(self, ids: Iterable[str]) -> None:
        ids = [i for i in ids if i not in self.at]
        if not ids:
            return
        self.cur.execute("""SELECT p.id::text, p.source_id::text, COALESCE(p.surfaced_at, p.published_at, p.fetched_at),
                                   s.platform, s.handle_or_url
                              FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""", (ids,))
        for pid, source, at, platform, handle in self.cur.fetchall():
            if at is not None:
                self.source[pid], self.at[pid], self.kind[pid] = source, at, source_kind(platform, handle)

    def voice(self, pid: str) -> bool:
        return pid in self.at and self.kind[pid] not in NOT_VOICE

    def one_story(self, a: str, b: str) -> bool:
        sa = self.story.get(a)
        return sa is not None and sa == self.story.get(b)

    def ordered(self, a: str, b: str) -> Tuple[str, str]:
        return tuple(sorted((a, b), key=lambda p: (self.at[p], p)))  # type: ignore[return-value]

    def window(self, pid: str) -> List[str]:
        """The embedded voices of other sources within 72 hours of `pid` (Mark X's time)."""
        t = self.at[pid]
        lo, hi = bisect.bisect_left(self.times, t - WINDOW), bisect.bisect_right(self.times, t + WINDOW)
        return [q for _, q in self.order[lo:hi] if q != pid and self.source[q] != self.source[pid] and self.voice(q)]


def _add(cur: Cursor, kind: str, a: str, b: str, source: str, score: Optional[float]) -> bool:
    return repo.add_candidate(cur, kind=kind, a=a, b=b, source=source,
                              score=None if score is None else round(float(score), 4))


# ---- embedding -------------------------------------------------------------------------------------

def _cosines(cur: Cursor, pid: str, others: Sequence[str], model: str) -> Dict[str, float]:
    if not others:
        return {}
    cur.execute("""SELECT e.post_id::text, 1 - (e.v <=> q.v) FROM mx_embeddings e,
                          (SELECT v FROM mx_embeddings WHERE post_id = %s AND model = %s) q
                    WHERE e.model = %s AND e.post_id = ANY(%s::uuid[])""", (pid, model, model, list(others)))
    return {q: float(c) for q, c in cur.fetchall()}


def _top(cos: Dict[str, float], k: int = NEAREST) -> List[str]:
    return [q for q, _ in sorted(cos.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def embedding_pairs(cur: Cursor, posts: Posts, new: Iterable[str], model: str = MODEL) -> int:
    """Post pairs: (i, q) when q is among i's 8 nearest or i among q's, at cosine >= 0.65, i one of `new`."""
    added = 0
    near_of: Dict[str, List[str]] = {}

    def nearest_of(q: str) -> List[str]:
        if q not in near_of:
            near_of[q] = _top(_cosines(cur, q, posts.window(q), model))
        return near_of[q]

    for i in new:
        if i not in posts.embedded or not posts.voice(i):
            continue
        cos = _cosines(cur, i, posts.window(i), model)
        top = set(_top(cos))
        for q, c in cos.items():
            if c < EMBEDDING_MIN or posts.one_story(i, q):
                continue
            if q in top or i in nearest_of(q):
                a, b = posts.ordered(i, q)
                added += _add(cur, POST_POST, a, b, "embedding", c)
    return added


def story_pairs(cur: Cursor, posts: Posts, new: Iterable[str], model: str = MODEL) -> int:
    """Story pairs: Mark IX's stories holding a `new` post against every other story whose centroid is at cosine
    >= 0.70, their first posts at most 14 days apart. Each story by its earliest member post (Mark X's time)."""
    cur.execute(
        """WITH m AS (SELECT sp.story_id, sp.post_id, e.v::vector AS v,
                             COALESCE(p.surfaced_at, p.published_at, p.fetched_at) AS at
                        FROM story_posts sp JOIN mx_embeddings e ON e.post_id = sp.post_id AND e.model = %(model)s
                        JOIN posts p ON p.id = sp.post_id),
                c AS (SELECT story_id, avg(v) AS v, min(at) AS first_at,
                             (array_agg(post_id::text ORDER BY at, post_id))[1] AS first_post
                        FROM m GROUP BY story_id),
                t AS (SELECT DISTINCT story_id FROM story_posts WHERE post_id = ANY(%(new)s::uuid[]))
           SELECT x.first_post, x.first_at, y.first_post, y.first_at, 1 - (x.v <=> y.v)
             FROM c x JOIN c y ON y.story_id <> x.story_id
                              AND y.first_at BETWEEN x.first_at - %(days)s AND x.first_at + %(days)s
            WHERE x.story_id IN (SELECT story_id FROM t) AND 1 - (x.v <=> y.v) >= %(min)s""",
        {"model": model, "new": list(new), "days": STORY_DAYS, "min": STORY_MIN})
    added = 0
    for pa, ta, pb, tb, c in cur.fetchall():
        (a, _), (b, _) = sorted([(pa, ta), (pb, tb)], key=lambda x: (x[1], x[0]))
        added += _add(cur, STORY_STORY, a, b, "embedding", c)
    return added


# ---- link ------------------------------------------------------------------------------------------

def link_pairs(cur: Cursor, posts: Posts, new: Iterable[str]) -> int:
    """Mark IX's joins (parent edges) touching a `new` post, as they are now."""
    cur.execute("""SELECT parent_id::text, post_id::text FROM story_posts
                    WHERE parent_id IS NOT NULL AND (post_id = ANY(%(n)s::uuid[]) OR parent_id = ANY(%(n)s::uuid[]))""",
                {"n": list(new)})
    edges = cur.fetchall()
    posts.load({p for edge in edges for p in edge})
    added = 0
    for parent, child in edges:
        if parent in posts.at and child in posts.at and parent != child:
            a, b = posts.ordered(parent, child)
            added += _add(cur, POST_POST, a, b, "link", None)
    return added


# ---- entity ----------------------------------------------------------------------------------------

def _subjects(cur: Cursor, where: str, params: Dict[str, Any]) -> Dict[str, Set[Tuple[str, str]]]:
    cur.execute(f"""SELECT post_id::text, name_key, lower(COALESCE(version, '')) FROM mx_mentions
                     WHERE guide = %(guide)s AND role = 'subject' AND type = ANY(%(types)s) AND name_key <> ''
                       AND {where}""", {"guide": ENTITY_GUIDE, "types": list(SPECIFIC_TYPES), **params})
    out: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for pid, key, version in cur.fetchall():
        out[pid].add((key, version))
    return out


def entity_pairs(cur: Cursor, posts: Posts, new: Iterable[str]) -> int:
    """Post pairs sharing a specific main subject (name key and version) within 72 hours, other sources."""
    mine = _subjects(cur, "post_id = ANY(%(n)s::uuid[])", {"n": list(new)})
    keys = sorted({k for s in mine.values() for k, _ in s})
    if not keys:
        return 0
    theirs = _subjects(cur, "name_key = ANY(%(k)s)", {"k": keys})
    posts.load(theirs)
    by_subject: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for pid, s in theirs.items():
        for subject in s:
            by_subject[subject].append(pid)
    added = 0
    for i, s in mine.items():
        if not posts.voice(i):
            continue
        for subject in s:
            for q in by_subject[subject]:
                if q == i or not posts.voice(q) or posts.source[q] == posts.source[i] \
                        or abs(posts.at[q] - posts.at[i]) > WINDOW or posts.one_story(i, q):
                    continue
                a, b = posts.ordered(i, q)
                added += _add(cur, POST_POST, a, b, "entity", None)
    return added


# ---- burst -----------------------------------------------------------------------------------------

def _targets(links: Sequence[Tuple[str, Optional[str]]]) -> List[str]:
    """The pages a post links, as the story rules count them for a shared link."""
    considered = links[:1] if len(links) >= ROUNDUP_ANCHORS else links
    return [t for t, stored in considered if not stored and not is_home(t)]


def burst_pairs(cur: Cursor, posts: Posts, new: Iterable[str]) -> int:
    """Late-burst pairs on the pages a `new` post links (0089, experiment W's window_bursts)."""
    from insight_core.db.repo_stories import SourceFacts, StoriesRepository
    from insight_core.services.stories_service import StoriesService

    new = list(new)
    cur.execute("SELECT DISTINCT target_url FROM post_links WHERE NOT boilerplate AND post_id = ANY(%s::uuid[])", (new,))
    pages = [r[0] for r in cur.fetchall() if not is_home(r[0])]
    if not pages:
        return 0
    # Only posts Mark IX has read (post_parts), so load_posts never parses one: Mark X writes no Mark IX table.
    cur.execute("""SELECT DISTINCT pl.post_id::text FROM post_links pl
                    WHERE NOT pl.boilerplate AND pl.target_url = ANY(%s)
                      AND EXISTS (SELECT 1 FROM post_parts pp WHERE pp.post_id = pl.post_id)""", (pages,))
    ids = [r[0] for r in cur.fetchall()]
    posts.load(ids)
    sources = SourceFacts(cur)
    linkers: Dict[str, List[Any]] = defaultdict(list)
    for row in StoriesRepository.load_posts(cur, sources, ids):
        p = StoriesService._story_post(row, sources)
        for target in _targets(p.links):
            linkers[target].append(p)
    added = 0
    for target in pages:
        ps = sorted(linkers.get(target, []), key=lambda p: (p.t, p.id))
        if len({p.place for p in ps}) < 2:
            continue
        late = [p for p in ps if p.t - ps[0].t > BURST_GAP]
        for n, b in enumerate(late):
            for a in late[:n]:
                if a.place != b.place and b.t - a.t <= BURST_GAP and not posts.one_story(a.id, b.id):
                    x, y = posts.ordered(a.id, b.id) if a.id in posts.at and b.id in posts.at else (a.id, b.id)
                    added += _add(cur, POST_POST, x, y, "burst", None)
    return added


# ---- the job ---------------------------------------------------------------------------------------

def find(cur: Cursor, post_ids: Iterable[str], *, model: str = MODEL,
         sources: Sequence[str] = ("embedding", "link", "entity", "burst")) -> Counter:
    """The candidates of these posts, every source: {source: pairs added} (story pairs as `embedding:story`)."""
    new = sorted({str(p) for p in post_ids})
    out: Counter = Counter()
    if not new:
        return out
    posts = Posts(cur, model, extra=new)
    if "embedding" in sources:
        out["embedding"] += embedding_pairs(cur, posts, new, model)
        out["embedding:story"] += story_pairs(cur, posts, new, model)
    if "link" in sources:
        out["link"] += link_pairs(cur, posts, new)
    if "entity" in sources:
        out["entity"] += entity_pairs(cur, posts, new)
    if "burst" in sources:
        out["burst"] += burst_pairs(cur, posts, new)
    return out


def mentioned_since(cur: Cursor, since: datetime) -> List[str]:
    """Posts whose ent-v3 mentions were written since (their call's time)."""
    cur.execute("""SELECT DISTINCT m.post_id::text FROM mx_mentions m JOIN mx_calls c ON c.id = m.call_id
                    WHERE m.guide = %s AND c.created_at >= %s""", (ENTITY_GUIDE, since))
    return [r[0] for r in cur.fetchall()]


def run(cur: Cursor, post_ids: Iterable[str] = (), *, since: Optional[datetime] = None, model: str = MODEL) -> Counter:
    """One run: the candidates of `post_ids` (new vectors) and of the posts with mentions written since `since`."""
    ids = set(map(str, post_ids))
    if since is not None:
        ids |= set(mentioned_since(cur, since))
    return find(cur, ids, model=model)

