"""A topic track's sub-topics, found from its posts and kept as the topic moves (issue 0207, Stealth v10.18).

This module owns a track's sub-topics: which exist, which posts are in each, their names, their digests, the reader's
looks and the owner's edits. tracks.py places a track's posts (in the track, joined, Discover, out); this module groups
the posts in the track (places `track` and `joined`) and nothing else.

**Found from the data** (`refresh`, the jobs process's "tracks" job, before the pages are kept; never the API). The
posts' BGE-M3 vectors (mx_embeddings; tracks.plan_member_vectors embeds the posts in a track whatever the reading
window) propose the sub-topics; every distance is computed by Postgres (pgvector), Python holds only ids:
  1. Kept as they are: the owner's pins (a merge or split, `by` owner), Haiku's placements (`by` haiku, below) while
     their sub-topic stands, and a post Haiku placed in none of them until a sub-topic newer than that answer exists;
     a post whose judge string is one of a locked sub-topic's `keys` goes there (the owner's rename, split and add).
  2. **The same sub-topic keeps its id**: the current centroids are the start; Lloyd's rounds (ROUNDS at most) put
     each other post at its nearest centroid and each centroid at the mean of its posts, so a rebuild moves few posts.
  3. **New ones appear**: while a track holds fewer than its target (about sqrt(posts / PER), K_MIN to K_MAX), a new
     sub-topic is seeded by the post with the most neighbours (SEED) among the worst-served posts, with them (MIN_SIZE
     at least); past the target, only from the posts no centroid serves (under STRAY) or Haiku found no home for. One
     left with fewer than MIN_SIZE posts dissolves; a post further than FLOOR from every centroid is Other.
  4. Two sub-topics whose centroids are MERGE or closer become one while the younger is still provisional (named by
     its judge string); one left with no member is closed (`valid_to`). **Quiet ones fade**: a sub-topic whose newest
     member is older than FADE_DAYS is `quiet` (shown last, folded) until a new post joins it.
A track whose inputs (its posts in the track, how many have a vector, the owner's and Haiku's settings) are as at its
last clustering (mx_tracks.subtopics_hash) is not read again.

**Named by the worker** (`plan_names`, kind `subtopics`, guide subtopics-v2, one call a track): the provisional
sub-topics and those whose members changed by NAME_DRIFT or more since Haiku named them, each shown by up to NAME_ITEMS
member lines. A locked or owner-named one is never renamed.

**Placed by the worker** (`plan_place`, kind `subtopic_place`, guide subtopic-place-v1, PLACE_ITEMS posts a question):
the vectors alone put 59% of the posts in the right sub-topic (100 blind-labelled rows, 0207-built); Haiku reads each
post and the named sub-topics and places it in one, or in none (Other). Its placements stay (step 1).

**A digest per sub-topic** (`plan_digests`, kind `digest`, guide digest-v1): two to four sentences that synthesise its
newest DIGEST_ITEMS members, each citing the posts it rests on ([n], checked against the question's posts). Asked
again only when those members changed (the same members are the same question: repo.add_task's (kind, guide, input)
is one task), at most once every DIGEST_EVERY a sub-topic. The page shows the newest valid digest, `stale` when its
members changed since.

**Shadow** (MEASURED): sub-topics and digests are shown, labelled with their blind-labelled measure, and act on
nothing, until a sample passes BAR with a Wilson lower bound of LOWER.

**New since you looked** (`seen` / `look`): the reader's last look at a track and at each sub-topic (mx_track_seen).
The page carries, per section, when each member joined the track (`joined`, its verdict's time), so the reader counts
what is new since its look without the kept page depending on the look.

Only mx_* tables are written.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import Cursor

log = logging.getLogger(__name__)

MODEL = "bge-m3"
PER = 8              # a track holds about sqrt(posts / PER) sub-topics ...
K_MIN, K_MAX = 3, 12  # ... from K_MIN to K_MAX ...
MIN_POSTS = 8        # ... and none under this many posts with vectors
ROUNDS = 10          # Lloyd's rounds at most (they stop when no post moves)
WORST = 0.25         # a new sub-topic is sought among this share of the posts, the worst served by the centroids
SEED = 0.62          # two posts at this cosine or more are neighbours when a new sub-topic is seeded
FLOOR = 0.50         # a post further than this from every centroid is Other
STRAY = 0.60         # past the target, a new sub-topic only from posts no centroid serves at this cosine
MIN_SIZE = 4         # a new sub-topic has at least this many posts
MERGE = 0.96         # two unlocked sub-topics whose centroids are this close become one (a mean of many posts sits
                     # near 0.9 to a neighbouring mean: measured, 0207)
SEED_POOL = 600      # a new sub-topic is sought among this many posts at most (its neighbours are counted pairwise)
FADE_DAYS = 30       # a sub-topic whose newest member is older than this is quiet
NEW_DAYS = 7         # a sub-topic made this recently is shown as new
NAME_KIND, NAME_GUIDE = "subtopics", "subtopics-v2"
NAME_ITEMS = 8       # member lines a naming question shows per sub-topic
NAME_DRIFT = 0.5     # renamed when fewer than this share of its members are those it was named with
NAME_MAX = 12        # sub-topics a naming question names at most
PLACE_KIND, PLACE_GUIDE = "subtopic_place", "subtopic-place-v1"
PLACE_ITEMS = 20     # posts a placement question places
PLACE_TASKS = 10     # placement questions a track has waiting at most
PLACE_TEXT = 300     # characters of each post a placement question shows
DIGEST_KIND, DIGEST_GUIDE = "digest", "digest-v1"
DIGEST_MIN = 3       # a sub-topic with fewer members has no digest
DIGEST_ITEMS = 8     # the newest members a digest reads
DIGEST_TEXT = 500    # characters of each post a digest question shows
DIGEST_EVERY = timedelta(hours=12)
IN_TRACK = ("track", "joined")
# 0207: Shadow (shown, labelled, never acted on) until a blind-labelled sample passes BAR with its Wilson lower bound at
# LOWER: the sub-topics' members (two labellers, 200 rows, after Haiku's placement) and the digests' points (88)
BAR, LOWER = 0.97, 0.90
MEASURED = {"subtopics": {"what": "posts in the right sub-topic", "right": 157, "of": 200, "lower": 0.723},
            "digests": {"what": "digest points their posts support", "right": 73, "of": 88, "lower": 0.738}}
LINE_CHARS = 140
_KEY = re.compile(r"^\[(g\d{1,2})\] ", re.M)
_POST = re.compile(r"^\[(\d{1,2})\] ", re.M)


def fold_key(s: Optional[str]) -> str:
    """A judge sub-topic string as it is compared: casefolded, punctuation as spaces, squashed."""
    return re.sub(r"[\W_]+", " ", (s or "").casefold()).strip()


def _clean(s: Optional[str], limit: int) -> Optional[str]:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:limit] or None


def _hash(ids: Iterable[str]) -> str:
    return hashlib.md5(",".join(sorted(ids)).encode()).hexdigest()


def _title(raw: Optional[str]) -> str:
    s = re.sub(r"\s+", " ", raw or "").strip()
    return (s[:1].upper() + s[1:])[:80] if s else "Untitled"


# ---- the sub-topics and their members ------------------------------------------------------------------

_SUB_COLS = ("id", "name", "definition", "keys", "locked", "made_by", "created_at", "named_by", "last_member_at",
             "named_members")


def current(cur: Cursor, folder_id: Any) -> List[Dict[str, Any]]:
    """The track's current sub-topics (oldest first)."""
    cur.execute("""SELECT id::text, name, definition, keys, locked, made_by, created_at, named_by, last_member_at,
                          named_members::text[]
                     FROM mx_track_subtopics WHERE track_id = %s AND valid_to IS NULL
                    ORDER BY created_at, lower(name), id""", (str(folder_id),))
    out = []
    for r in cur.fetchall():
        d = dict(zip(_SUB_COLS, r))
        d["keys"] = list(d["keys"] or [])
        d["named_members"] = list(d["named_members"] or [])
        out.append(d)
    return out


def members(cur: Cursor, folder_id: Any) -> Dict[str, str]:
    """{post id: its sub-topic id} of the track (not the posts Haiku placed in none of them)."""
    cur.execute("""SELECT post_id::text, subtopic_id::text FROM mx_track_subtopic_members
                    WHERE track_id = %s AND subtopic_id IS NOT NULL""",
                (str(folder_id),))
    return dict(cur.fetchall())


def locked_names(cur: Cursor, folder_id: Any) -> List[str]:
    """The names the judge is given (the locked sub-topics')."""
    cur.execute("""SELECT name FROM mx_track_subtopics WHERE track_id = %s AND valid_to IS NULL AND locked
                    ORDER BY lower(name), name""", (str(folder_id),))
    return [n for (n,) in cur.fetchall()]


def in_track(cur: Cursor, track: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The track's posts in the track (places track and joined), each {post_id, at, subtopic (the judge's string),
    answered_at}: the kept placement, else placed live."""
    from insight_core.markx import track_kept, tracks
    if track_kept.calibration(cur, track["folder_id"]) is not None:   # kept: only the rows in the track are read
        cur.execute(f"""SELECT k.post_id::text, {tracks._date()}, k.subtopic, k.answered_at FROM mx_track_places k
                          JOIN posts p ON p.id = k.post_id
                         WHERE k.track_id = %s AND k.place = ANY(%s) ORDER BY k.post_id""",
                    (track["folder_id"], list(IN_TRACK)))
        return [{"post_id": p, "at": at, "subtopic": raw, "answered_at": ans} for p, at, raw, ans in cur.fetchall()]
    got = None
    items = tracks.placed(cur, track, shown=False)["items"]
    if got is None:   # the live placement's narrow read carries no judge string nor date: read them for these posts
        ids = [it["post_id"] for it in items if it["place"] in IN_TRACK]
        cur.execute(f"""SELECT DISTINCT ON (i.post_id) i.post_id::text, i.subtopic, i.answered_at, {tracks._date()}
                          FROM mx_track_items i JOIN posts p ON p.id = i.post_id
                         WHERE i.track_id = %s AND i.post_id = ANY(%s::uuid[]) AND i.verdict IS NOT NULL
                         ORDER BY i.post_id, i.version DESC""", (track["folder_id"], ids))
        more = {pid: (raw, ans, at) for pid, raw, ans, at in cur.fetchall()}
        for it in items:
            raw, ans, at = more.get(it["post_id"], (None, None, None))
            it.setdefault("subtopic", raw)
            it.setdefault("answered_at", ans)
            it.setdefault("at", at)
    return [{"post_id": it["post_id"], "at": it.get("at"), "subtopic": it.get("subtopic"),
             "answered_at": it.get("answered_at")} for it in items if it["place"] in IN_TRACK]


# ---- the clustering (the jobs process) ------------------------------------------------------------------

def refresh(cur: Cursor, *, now: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
    """Every topic track whose in-track posts changed since its last clustering, clustered again (`refresh_track`):
    {track: its counts}. The caller commits."""
    from insight_core.markx import tracks
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Any] = {}
    for t in tracks.described(cur):
        items = in_track(cur, t)
        stamp = lambda: _inputs_stamp(cur, t["folder_id"], [it["post_id"] for it in items])   # noqa: E731
        cur.execute("SELECT subtopics_hash FROM mx_tracks WHERE folder_id = %s", (t["folder_id"],))
        row = cur.fetchone()
        if not force and row is not None and row[0] == stamp():
            continue
        out[t["folder_id"]] = refresh_track(cur, t, items, now=now)
        # what it read, kept with the track (the next pass with the same inputs reads nothing again)
        cur.execute("UPDATE mx_tracks SET subtopics_hash = %s WHERE folder_id = %s", (stamp(), t["folder_id"]))
    return out


def _inputs_stamp(cur: Cursor, folder_id: str, ids: Sequence[str]) -> str:
    """What a track's clustering reads: its posts in the track, how many of them have a vector, the owner's edits."""
    cur.execute("SELECT count(*) FROM mx_embeddings WHERE model = %s AND post_id = ANY(%s::uuid[])", (MODEL, list(ids)))
    return f"{_hash(ids)}:{cur.fetchone()[0]}:{_edits_stamp(cur, folder_id)}"


def _edits_stamp(cur: Cursor, folder_id: str) -> str:
    """What the owner and Haiku set on the sub-topics (names, keys, locks, pins, placements): a change clusters again."""
    cur.execute("""SELECT md5(COALESCE(string_agg(concat_ws(':', id, name, locked, keys::text, valid_to), ','
                                                  ORDER BY id), '')) FROM mx_track_subtopics
                    WHERE track_id = %s AND (made_by = 'owner' OR named_by = 'owner' OR locked)""", (folder_id,))
    a = cur.fetchone()[0]
    cur.execute("""SELECT count(*), max(since) FROM mx_track_subtopic_members WHERE track_id = %s AND by IN ('owner', 'haiku')""",
                (folder_id,))
    return f"{a}:{cur.fetchone()}"


def refresh_track(cur: Cursor, track: Dict[str, Any], items: Sequence[Dict[str, Any]], *,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """One track clustered (the module's rule, above): its members replaced, its sub-topics' centroids, hashes and
    dates updated, new ones added, merged or emptied ones closed. Counts {posts, kept, moved, new, merged, closed,
    other, unembedded}."""
    now = now or datetime.now(timezone.utc)
    fid = track["folder_id"]
    by_id = {it["post_id"]: it for it in items}
    ids = list(by_id)
    cur.execute("DROP TABLE IF EXISTS _ts_items")
    cur.execute("""CREATE TEMP TABLE _ts_items (post_id uuid PRIMARY KEY, v halfvec(1024), sub uuid,
                                               left_ boolean NOT NULL DEFAULT false,
                                               pinned boolean NOT NULL DEFAULT false) ON COMMIT DROP""")
    cur.execute("""INSERT INTO _ts_items (post_id, v)
                   SELECT x, e.v FROM unnest(%s::uuid[]) x LEFT JOIN mx_embeddings e ON e.post_id = x AND e.model = %s""",
                (ids, MODEL))
    subs = {s["id"]: s for s in current(cur, fid)}
    was = members(cur, fid)
    # the owner's pins and Haiku's placements stay while their sub-topic does; a post Haiku placed in none of them
    # stays out (Other) until a sub-topic newer than that answer exists
    newest_sub = max((s["created_at"] for s in subs.values() if s["created_at"]), default=None)
    cur.execute("""SELECT post_id::text, subtopic_id::text, by, since FROM mx_track_subtopic_members
                    WHERE track_id = %s AND by IN ('owner', 'haiku')""", (fid,))
    got: Dict[str, Tuple[str, Optional[float], str]] = {}
    none: set = set()
    for p, sid, by, since in cur.fetchall():
        if p not in by_id:
            continue
        if sid is None and by == "haiku" and (newest_sub is None or since >= newest_sub):
            none.add(p)
        elif sid in subs:
            got[p] = (sid, None, by)
    # 1. the owner's keys: a locked sub-topic holds the posts whose judge string is one of its keys
    keyed = {k: s["id"] for s in subs.values() if s["locked"] for k in s["keys"]}
    for p, it in by_id.items():
        if p not in got and p not in none and fold_key(it["subtopic"]) in keyed:
            got[p] = (keyed[fold_key(it["subtopic"])], None, "cluster")
    # 1b. a sub-topic with no centroid yet (made before 0207) holds its keys' posts, once: then it has a centroid
    cur.execute("SELECT id::text FROM mx_track_subtopics WHERE track_id = %s AND valid_to IS NULL AND centroid IS NULL",
                (fid,))
    bare_subs = {i for (i,) in cur.fetchall()}
    bare_keys = {k: s["id"] for s in subs.values() if not s["locked"] and s["id"] in bare_subs for k in s["keys"]}
    boot = {p: (bare_keys[fold_key(it["subtopic"])], None, "cluster") for p, it in by_id.items()
            if p not in got and fold_key(it["subtopic"]) in bare_keys}
    counts = Counter()
    pinned = dict(got)
    cur.execute("SELECT count(*) FROM _ts_items WHERE v IS NOT NULL")
    n = cur.fetchone()[0]
    k = target(n)
    # 2. the current centroids (each sub-topic keeps its id), the pinned posts' groups too (and a sub-topic made
    #    before 0207 starts from its keys' posts)
    _mark(cur, {**boot, **pinned})
    for sid in {g[0] for g in pinned.values()} | {g[0] for g in boot.values()}:
        _centroid(cur, sid)
    _mark(cur, pinned, reset=True)
    cur.execute("UPDATE _ts_items SET pinned = (post_id = ANY(%s::uuid[]))", (list(pinned),))
    live = _live(cur, fid)
    # 3. new ones appear where the posts are served worst: while fewer than the target, the post with the most
    #    neighbours (SEED) among the worst-served WORST share seeds a sub-topic of itself and those neighbours; past the
    #    target (up to K_MAX), only a dense group among the posts no centroid serves (best cosine under STRAY): a topic
    #    that is new, not a finer cut of an old one
    while k and len(live) < K_MAX:
        seed = _seed(cur, fid, live, below=None if len(live) < k else STRAY, among=None if len(live) < k else none)
        if seed is None:
            break
        name = _judge_name([by_id[q]["subtopic"] for q in seed])
        cur.execute("""INSERT INTO mx_track_subtopics (track_id, name, keys, named_by)
                       VALUES (%s, %s, '{}', 'judge') RETURNING id::text""", (fid, name))
        sid = cur.fetchone()[0]
        subs[sid] = {"id": sid, "name": name, "locked": False, "keys": [], "named_by": "judge", "created_at": now,
                     "made_by": "insight"}
        cur.execute("""UPDATE mx_track_subtopics SET centroid = (SELECT avg(v) FROM _ts_items
                                                                WHERE post_id = ANY(%s::uuid[])) WHERE id = %s""",
                    (seed, sid))
        live.append(sid)
        none.difference_update(seed)   # posts Haiku found no home for, now a sub-topic of their own: placed again
        counts["new"] += 1
    # 4. Lloyd's rounds from those centroids: each post to its nearest, each centroid the mean of its posts; a
    #    sub-topic left with fewer than MIN_SIZE posts (not locked, not the owner's) is dissolved and its posts go on
    got = dict(pinned)
    for _round in range(ROUNDS):
        moved = _nearest(cur, fid, {**pinned, **{q: None for q in none}}, got)
        small = _small(cur, fid, subs, got)
        for sid in small:
            cur.execute("UPDATE mx_track_subtopics SET centroid = NULL WHERE id = %s", (sid,))
        for sid in {g[0] for g in got.values()}:
            _centroid(cur, sid)
        if not moved and not small:
            break
    # posts far from every centroid are Other
    for q in [q for q, g in got.items() if q not in pinned and g[1] is not None and g[1] < FLOOR]:
        del got[q]
    _mark(cur, got, reset=True)
    # posts with no vector: the sub-topic holding most posts with their judge string
    cur.execute("SELECT post_id::text FROM _ts_items WHERE v IS NULL")
    bare = {q for (q,) in cur.fetchall()}
    by_key: Dict[str, Counter] = defaultdict(Counter)
    for q, (sid, _s, _b) in got.items():
        kk = fold_key(by_id[q]["subtopic"])
        if kk:
            by_key[kk][sid] += 1
    for q in bare:
        if q not in got:
            c = by_key.get(fold_key(by_id[q]["subtopic"]))
            if c:
                got[q] = (c.most_common(1)[0][0], None, "cluster")
    counts["unembedded"] = len(bare)
    # 4. centroids again, merges, the emptied ones closed
    groups: Dict[str, List[str]] = defaultdict(list)
    for p, (sid, _s, _b) in got.items():
        groups[sid].append(p)
    for young, old in _merges(cur, fid, subs):
        for q in groups.pop(young, []):
            got[q] = (old, got[q][1], got[q][2])
            groups[old].append(q)
        cur.execute("UPDATE mx_track_subtopics SET valid_to = %s, merged_into = %s WHERE id = %s", (now, old, young))
        _mark(cur, {q: got[q] for q in groups[old]})
        _centroid(cur, old)
        counts["merged"] += 1
    for sid, s in subs.items():
        if sid not in groups and not s["locked"] and s.get("made_by") != "owner":
            cur.execute("UPDATE mx_track_subtopics SET valid_to = %s WHERE id = %s AND valid_to IS NULL", (now, sid))
            counts["closed"] += cur.rowcount
    for sid, ps in groups.items():
        last = max((by_id[p]["at"] for p in ps if by_id[p]["at"]), default=None)
        cur.execute("UPDATE mx_track_subtopics SET members_hash = %s, last_member_at = %s WHERE id = %s",
                    (_hash(ps), last, sid))
    # the members replaced: a post that stays in its sub-topic keeps its `since`
    rows = [(p, sid, sim, by) for p, (sid, sim, by) in got.items()]
    cur.execute("DELETE FROM mx_track_subtopic_members WHERE track_id = %s AND NOT (post_id = ANY(%s::uuid[]))",
                (fid, [r[0] for r in rows] + sorted(none)))   # Haiku's "none of them" rows stay as they are
    cur.execute("""INSERT INTO mx_track_subtopic_members (track_id, post_id, subtopic_id, by, sim, since)
                   SELECT %s, x.p, x.s, x.b, x.sim, %s FROM unnest(%s::uuid[], %s::uuid[], %s::text[], %s::real[])
                          AS x(p, s, b, sim)
                   ON CONFLICT (track_id, post_id) DO UPDATE
                      SET subtopic_id = EXCLUDED.subtopic_id, by = EXCLUDED.by, sim = EXCLUDED.sim,
                          since = CASE WHEN mx_track_subtopic_members.subtopic_id = EXCLUDED.subtopic_id
                                       THEN mx_track_subtopic_members.since ELSE EXCLUDED.since END""",
                (fid, now, [r[0] for r in rows], [r[1] for r in rows], [r[3] for r in rows], [r[2] for r in rows]))
    counts["kept"] = sum(1 for p, (sid, _s, _b) in got.items() if was.get(p) == sid)
    counts["moved"] = sum(1 for p, (sid, _s, _b) in got.items() if p in was and was[p] != sid)
    counts["posts"] = len(ids)
    counts["other"] = len(ids) - len(got)
    return dict(counts)


def target(n: int) -> int:
    """How many sub-topics n posts with vectors hold: about sqrt(n / PER), from K_MIN to K_MAX; none under MIN_POSTS."""
    if n < MIN_POSTS:
        return 0
    return max(K_MIN, min(K_MAX, int(round(math.sqrt(n / PER)))))


def _mark(cur: Cursor, got: Dict[str, Tuple[str, Optional[float], str]], *, reset: bool = False) -> None:
    """The working table's sub-topic of each placed post (`reset`: the others' cleared)."""
    if reset:
        cur.execute("UPDATE _ts_items SET sub = NULL WHERE sub IS NOT NULL")
    if got:
        cur.execute("""UPDATE _ts_items i SET sub = x.s FROM unnest(%s::uuid[], %s::uuid[]) AS x(p, s)
                        WHERE i.post_id = x.p""", ([q for q in got], [g[0] for g in got.values()]))


def _live(cur: Cursor, fid: str) -> List[str]:
    cur.execute("""SELECT id::text FROM mx_track_subtopics WHERE track_id = %s AND valid_to IS NULL AND centroid IS NOT NULL
                    ORDER BY created_at, id""", (fid,))
    return [i for (i,) in cur.fetchall()]


def _seed(cur: Cursor, fid: str, live: Sequence[str], below: Optional[float] = None,
          among: Optional[Iterable[str]] = None) -> Optional[List[str]]:
    """A new sub-topic's first posts: among the WORST share of posts by their cosine to the nearest centroid (every
    post when there is none; `below`: the posts whose best cosine is under it, and the posts `among`: those Haiku
    placed in none of the sub-topics), the one with the most neighbours
    (SEED) there, with them; None when it has fewer than MIN_SIZE - 1."""
    if live:
        cur.execute("""WITH s AS (SELECT i.post_id, (SELECT max(1 - (i.v <=> c.centroid)) FROM mx_track_subtopics c
                                                    WHERE c.track_id = %(t)s AND c.valid_to IS NULL
                                                      AND c.centroid IS NOT NULL) AS best
                                    FROM _ts_items i WHERE i.v IS NOT NULL AND NOT i.pinned)
                       UPDATE _ts_items SET left_ = (post_id IN (
                           SELECT post_id FROM s WHERE %(below)s::float8 IS NULL OR best < %(below)s
                                                       OR post_id = ANY(%(among)s::uuid[])
                            ORDER BY best, post_id
                            LIMIT CASE WHEN %(below)s::float8 IS NULL
                                       THEN LEAST(%(pool)s, GREATEST(1, (SELECT count(*) FROM s) * %(worst)s))::int
                                       ELSE %(pool)s END))""",
                    {"t": fid, "worst": WORST, "below": below, "among": sorted(among or ()), "pool": SEED_POOL})
    else:
        cur.execute("""UPDATE _ts_items SET left_ = post_id IN (SELECT post_id FROM _ts_items WHERE v IS NOT NULL AND NOT pinned
                                                                ORDER BY post_id LIMIT %s)""", (SEED_POOL,))
    cur.execute("""SELECT a.post_id::text, array_agg(b.post_id::text ORDER BY b.post_id) FROM _ts_items a
                     JOIN _ts_items b ON b.left_ AND b.post_id <> a.post_id AND (a.v <=> b.v) <= %s
                    WHERE a.left_ GROUP BY a.post_id ORDER BY count(*) DESC, a.post_id LIMIT 1""", (1 - SEED,))
    row = cur.fetchone()
    if row is None or len(row[1]) + 1 < MIN_SIZE:
        return None
    return [row[0]] + list(row[1])


def _nearest(cur: Cursor, fid: str, pinned: Dict[str, Any], got: Dict[str, Tuple[str, Optional[float], str]]) -> int:
    """Each post not pinned to its nearest current centroid (`got`): how many changed."""
    cur.execute("""SELECT i.post_id::text, n.id::text, n.sim FROM _ts_items i
                     CROSS JOIN LATERAL (SELECT c.id, 1 - (i.v <=> c.centroid) AS sim FROM mx_track_subtopics c
                                          WHERE c.track_id = %s AND c.valid_to IS NULL AND c.centroid IS NOT NULL
                                          ORDER BY i.v <=> c.centroid, c.id LIMIT 1) n
                    WHERE i.v IS NOT NULL""", (fid,))
    moved = 0
    new = {}
    for q, sid, sim in cur.fetchall():
        if q in pinned:
            continue
        if got.get(q, (None,))[0] != sid:
            moved += 1
        new[q] = (sid, float(sim), "cluster")
    got.update(new)
    _mark(cur, got, reset=True)
    return moved


def _small(cur: Cursor, fid: str, subs: Dict[str, Dict[str, Any]], got: Dict[str, Tuple[str, Optional[float], str]]
           ) -> List[str]:
    """The sub-topics with fewer than MIN_SIZE posts that may dissolve (not locked, not the owner's): their posts are
    taken off them (`got`)."""
    size = Counter(g[0] for g in got.values())
    small = [sid for sid in _live(cur, fid) if size.get(sid, 0) < MIN_SIZE
             and not subs.get(sid, {}).get("locked") and subs.get(sid, {}).get("made_by") != "owner"]
    for q in [q for q, g in got.items() if g[0] in small]:
        del got[q]
    return small


def _centroid(cur: Cursor, sid: str) -> None:
    """A sub-topic's centroid: the mean vector of its posts in the working table (none: NULL)."""
    cur.execute("""UPDATE mx_track_subtopics SET centroid = (SELECT avg(v) FROM _ts_items WHERE sub = %s AND v IS NOT NULL)
                    WHERE id = %s""", (sid, sid))


def _merges(cur: Cursor, fid: str, subs: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str]]:
    """[(younger, older)]: current sub-topics whose centroids are MERGE or closer, the younger still named by its judge
    string (not locked, not the owner's, not yet named and placed into by Haiku), each merged once."""
    cur.execute("""SELECT a.id::text, b.id::text FROM mx_track_subtopics a JOIN mx_track_subtopics b
                      ON b.track_id = a.track_id AND (b.created_at, b.id) < (a.created_at, a.id)
                   WHERE a.track_id = %s AND a.valid_to IS NULL AND b.valid_to IS NULL AND NOT a.locked
                     AND a.named_by IS DISTINCT FROM 'haiku' AND a.named_by IS DISTINCT FROM 'owner'
                     AND a.made_by <> 'owner' AND a.centroid IS NOT NULL AND b.centroid IS NOT NULL
                     AND (a.centroid <=> b.centroid) <= %s
                   ORDER BY a.created_at DESC, a.id, (a.centroid <=> b.centroid)""", (fid, 1 - MERGE))
    out, gone = [], set()
    for young, old in cur.fetchall():
        if young in gone or old in gone:
            continue
        out.append((young, old))
        gone.add(young)
    return out


def _judge_name(raws: Sequence[Optional[str]]) -> str:
    """A new group's name until Haiku names it: its members' most common judge string."""
    c = Counter(fold_key(r) for r in raws if fold_key(r))
    if not c:
        return "Untitled"
    key = c.most_common(1)[0][0]
    shown = next(r for r in raws if fold_key(r) == key)
    return _title(shown)


# ---- naming (the worker) ---------------------------------------------------------------------------------

def _lines(cur: Cursor, track: Dict[str, Any], ps: Sequence[str], n: int, sid: Optional[str] = None) -> List[str]:
    """Up to n member lines: the title (or the text) and the judge's why; the most typical first (nearest the
    sub-topic's centroid, `sid`: a name read from the newest alone named a broad group by its latest corner), else the
    newest."""
    cur.execute(f"""SELECT DISTINCT ON (i.post_id) i.post_id::text, COALESCE(NULLIF(btrim(p.title), ''), left(p.content, 200)),
                           i.why, {_date()},
                           (SELECT 1 - (e.v <=> s.centroid) FROM mx_embeddings e, mx_track_subtopics s
                             WHERE e.post_id = i.post_id AND e.model = %s AND s.id = %s::uuid)
                      FROM mx_track_items i JOIN posts p ON p.id = i.post_id
                     WHERE i.track_id = %s AND i.post_id = ANY(%s::uuid[]) AND i.verdict IS NOT NULL
                     ORDER BY i.post_id, i.version DESC""", (MODEL, sid, track["folder_id"], list(ps)))
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    rows = sorted(cur.fetchall(), key=lambda r: (r[4] if r[4] is not None else -1.0, r[3] or epoch, r[0]),
                  reverse=True)[:n]
    return [f"- {_clean(t, LINE_CHARS) or '(no title)'} — {_clean(w, 160) or ''}" for _p, t, w, _at, _sim in rows]


def _date() -> str:
    from insight_core.markx import pairing
    return pairing.ordinary_date("p")


def names_input(cur: Cursor, track: Dict[str, Any], subs: Sequence[Dict[str, Any]], groups: Dict[str, List[str]],
                others: Sequence[Dict[str, Any]]) -> str:
    """The naming question: the track, the names already in use (kept), and each sub-topic to name (keyed g1..gK)."""
    lines = [f"TRACK: {track['name']}", f"Belongs: {track['description']}"]
    if others:
        lines.append("Names in use: " + "; ".join(s["name"] for s in others))
    lines.append("")
    lines.append("GROUPS:")
    for k, s in enumerate(subs, 1):
        lines.append(f"[g{k}] {len(groups.get(s['id'], []))} posts")
        lines += _lines(cur, track, groups.get(s["id"], []), NAME_ITEMS, s["id"])
    return "\n".join(lines)


def keys_of(input: str) -> List[str]:
    """The group keys (g1..gK) of a naming question."""
    return _KEY.findall(input)


def _drifted(s: Dict[str, Any], ps: Sequence[str]) -> bool:
    if s["named_by"] != "haiku":
        return False
    named = set(s["named_members"] or [])
    return bool(ps) and len(named & set(ps)) < NAME_DRIFT * len(ps)


def plan_names(cur: Cursor, **_kw: Any) -> int:
    """A `subtopics` (naming) task for each track with sub-topics named by their judge string or drifted from their
    name, none waiting: how many were added."""
    from insight_core.markx import repo, schemas, tracks
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        cur.execute("""SELECT count(*) FROM mx_tasks WHERE kind = %s AND guide = %s AND a = %s
                          AND status IN ('open', 'leased')""", (NAME_KIND, NAME_GUIDE, t["folder_id"]))
        if cur.fetchone()[0]:
            continue
        subs = current(cur, t["folder_id"])
        mem = members(cur, t["folder_id"])
        groups: Dict[str, List[str]] = defaultdict(list)
        for p, sid in mem.items():
            groups[sid].append(p)
        todo = [s for s in subs if groups.get(s["id"]) and not s["locked"] and s["named_by"] != "owner"
                and (s["named_by"] in (None, "judge") or _drifted(s, groups[s["id"]]))][:NAME_MAX]
        if not todo:
            continue
        others = [s for s in subs if s not in todo and groups.get(s["id"])]
        text = names_input(cur, t, todo, groups, others)
        task_id, new = repo.add_task(cur, kind=NAME_KIND, guide=NAME_GUIDE, subject_kind="track", input=text,
                                     a=t["folder_id"])
        cur.execute("""INSERT INTO mx_track_subtopic_asks (task_id, track_id, kind, subtopic_ids)
                       VALUES (%s, %s, 'names', %s::uuid[]) ON CONFLICT DO NOTHING""",
                    (task_id, t["folder_id"], [s["id"] for s in todo]))
        if new:
            added += 1
        else:   # the same question answered before (the same groups): its answer applies again
            got = _valid_answer(cur, task_id)
            if got is not None:
                apply_names(cur, repo.get_task(cur, task_id), got)
    return added


def _valid_answer(cur: Cursor, task_id: Any) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at DESC, ctid DESC LIMIT 1",
                (task_id,))
    row = cur.fetchone()
    return row[0] if row else None


def apply_names(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> int:
    """A naming answer: each named sub-topic (still current, not locked nor named by the owner) takes its name and
    definition, and remembers the members it was named with. How many were named."""
    cur.execute("SELECT subtopic_ids::text[] FROM mx_track_subtopic_asks WHERE task_id = %s", (task["id"],))
    row = cur.fetchone()
    if row is None:
        return 0
    keyed = dict(zip(keys_of(task["input"]), row[0]))
    n = 0
    for got in answer.get("names") or []:
        sid = keyed.get(got.get("key"))
        name = _clean(got.get("name"), 80)
        if not sid or not name:
            continue
        cur.execute("""UPDATE mx_track_subtopics s
                          SET name = %s, definition = %s, named_by = 'haiku', task_id = %s,
                              named_hash = s.members_hash,
                              named_members = ARRAY(SELECT post_id FROM mx_track_subtopic_members WHERE subtopic_id = s.id)
                        WHERE s.id = %s AND s.valid_to IS NULL AND NOT s.locked
                          AND s.named_by IS DISTINCT FROM 'owner'""",
                    (name, _clean(got.get("definition"), 300), task["id"], sid))
        n += cur.rowcount
    return n


# ---- digests (the worker) --------------------------------------------------------------------------------

def digest_input(cur: Cursor, track: Dict[str, Any], sub: Dict[str, Any], ps: Sequence[str]) -> Tuple[str, List[str]]:
    """A digest question: the track, the sub-topic and its newest DIGEST_ITEMS members numbered [1]..[n] (byline,
    date, title, text): (the question, the posts in their order)."""
    from insight_core.markx import tasks
    posts = tasks.load_posts(cur, list(ps))
    order = sorted((p for p in ps if p in posts), key=lambda p: (posts[p].at is not None, posts[p].at, p),
                   reverse=True)[:DIGEST_ITEMS]
    lines = [f"TRACK: {track['name']}", f"SUB-TOPIC: {sub['name']}"]
    if sub.get("definition"):
        lines.append(f"About: {sub['definition']}")
    lines.append("")
    lines.append("POSTS:")
    for n, p in enumerate(order, 1):
        post = posts[p]
        when = post.at.date().isoformat() if post.at else "undated"
        title = _clean(post.title, LINE_CHARS)
        text = _clean(post.text, DIGEST_TEXT) or ""
        if title and text.startswith(title):
            text = text[len(title):].strip()
        lines.append(f"[{n}] {post.who or 'unknown'}, {when}: {title or '(no title)'}" + (f" — {text}" if text else ""))
    return "\n".join(lines), order


def numbered(input: str) -> int:
    """How many posts a digest question shows."""
    return len(_POST.findall(input))


def plan_digests(cur: Cursor, *, now: Optional[datetime] = None, **_kw: Any) -> int:
    """A `digest` task for each current sub-topic with DIGEST_MIN+ members whose newest members differ from its last
    digest's, and no digest asked in DIGEST_EVERY: how many were added."""
    from insight_core.markx import repo, schemas, tracks
    now = now or datetime.now(timezone.utc)
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        mem = members(cur, t["folder_id"])
        groups: Dict[str, List[str]] = defaultdict(list)
        for p, sid in mem.items():
            groups[sid].append(p)
        cur.execute("""SELECT DISTINCT ON (a.subtopic_ids[1]) a.subtopic_ids[1]::text, a.post_ids::text[], a.created_at,
                              k.status
                         FROM mx_track_subtopic_asks a JOIN mx_tasks k ON k.id = a.task_id
                        WHERE a.track_id = %s AND a.kind = 'digest'
                        ORDER BY a.subtopic_ids[1], a.created_at DESC""", (t["folder_id"],))
        last = {sid: (ps, at, st) for sid, ps, at, st in cur.fetchall()}
        for s in current(cur, t["folder_id"]):
            ps = groups.get(s["id"], [])
            if len(ps) < DIGEST_MIN:
                continue
            was = last.get(s["id"])
            if was is not None and (was[2] in ("open", "leased") or now - was[1] < DIGEST_EVERY):
                continue
            text, order = digest_input(cur, t, s, ps)
            if was is not None and list(was[0]) == order:
                continue
            task_id, new = repo.add_task(cur, kind=DIGEST_KIND, guide=DIGEST_GUIDE, subject_kind="track", input=text,
                                         a=t["folder_id"], b=s["id"])
            cur.execute("""INSERT INTO mx_track_subtopic_asks (task_id, track_id, kind, subtopic_ids, post_ids)
                           VALUES (%s, %s, 'digest', ARRAY[%s::uuid], %s::uuid[]) ON CONFLICT DO NOTHING""",
                        (task_id, t["folder_id"], s["id"], order))
            added += new
    return added


def digests(cur: Cursor, folder_id: Any) -> Dict[str, Dict[str, Any]]:
    """{sub-topic id: its newest valid digest {points: [{text, cites: [post ids]}], at, posts: [post ids]}}."""
    cur.execute("""SELECT DISTINCT ON (a.subtopic_ids[1]) a.subtopic_ids[1]::text, a.post_ids::text[], c.answer,
                          c.created_at
                     FROM mx_track_subtopic_asks a JOIN mx_calls c ON c.task_id = a.task_id AND c.valid
                    WHERE a.track_id = %s AND a.kind = 'digest'
                    ORDER BY a.subtopic_ids[1], c.created_at DESC, a.created_at DESC""", (str(folder_id),))
    out = {}
    for sid, ps, answer, at in cur.fetchall():
        points = []
        for pt in (answer or {}).get("points") or []:
            cites = [ps[n - 1] for n in pt.get("cites") or [] if isinstance(n, int) and 1 <= n <= len(ps)]
            if pt.get("text") and cites:
                points.append({"text": pt["text"], "cites": list(dict.fromkeys(cites))})
        if points:
            out[sid] = {"points": points, "at": at, "posts": list(ps)}
    return out


# ---- placement (the worker) ---------------------------------------------------------------------------------

_SUB_KEY = re.compile(r"^\[(s\d{1,2})\] ", re.M)
_POST_KEY = re.compile(r"^\[(p\d{1,3})\] ", re.M)


def place_input(cur: Cursor, track: Dict[str, Any], subs: Sequence[Dict[str, Any]], ps: Sequence[str]) -> str:
    """A placement question: the track, its sub-topics keyed s1..sK (name and definition) and the posts keyed p1..pN
    (title, the judge's why, the start of the text)."""
    from insight_core.markx import tasks
    posts = tasks.load_posts(cur, list(ps))
    cur.execute("""SELECT DISTINCT ON (post_id) post_id::text, why FROM mx_track_items
                    WHERE track_id = %s AND post_id = ANY(%s::uuid[]) AND verdict IS NOT NULL
                    ORDER BY post_id, version DESC""", (track["folder_id"], list(ps)))
    why = dict(cur.fetchall())
    lines = [f"TRACK: {track['name']}", f"Belongs: {track['description']}", "", "SUB-TOPICS:"]
    for k, s in enumerate(subs, 1):
        lines.append(f"[s{k}] {s['name']}" + (f" — {s['definition']}" if s.get("definition") else ""))
    lines += ["", "POSTS:"]
    for k, p in enumerate(ps, 1):
        post = posts.get(p)
        title = _clean(post.title if post else None, LINE_CHARS) or "(no title)"
        text = _clean(post.text if post else None, PLACE_TEXT) or ""
        if text.startswith(title):
            text = text[len(title):].strip()
        lines.append(f"[p{k}] {title} — {_clean(why.get(p), 160) or ''}" + (f" — {text}" if text else ""))
    return "\n".join(lines)


def place_keys(input: str) -> Tuple[List[str], List[str]]:
    """(the sub-topic keys, the post keys) of a placement question."""
    return _SUB_KEY.findall(input), _POST_KEY.findall(input)


def plan_place(cur: Cursor, **_kw: Any) -> int:
    """`subtopic_place` tasks for each topic track: its posts in the track that neither Haiku nor the owner placed (a
    post placed in none of them again once a newer sub-topic exists), newest first, PLACE_ITEMS a question, at most
    PLACE_TASKS questions a track waiting at once: how many were added."""
    from insight_core.markx import repo, schemas, tracks
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        subs = [s for s in current(cur, t["folder_id"]) if s["named_by"] in ("haiku", "owner")]
        if not subs:
            continue
        newest = max(s["created_at"] for s in subs)
        cur.execute("""SELECT count(*) FROM mx_track_subtopic_asks a JOIN mx_tasks k ON k.id = a.task_id
                        WHERE a.track_id = %s AND a.kind = 'place' AND k.status IN ('open', 'leased')""", (t["folder_id"],))
        room = PLACE_TASKS - cur.fetchone()[0]
        if room <= 0:
            continue
        cur.execute("""SELECT post_id::text FROM mx_track_subtopic_members
                        WHERE track_id = %s AND (by = 'owner' OR (by = 'haiku' AND (subtopic_id IS NOT NULL OR since >= %s)))
                       UNION SELECT unnest(a.post_ids)::text FROM mx_track_subtopic_asks a JOIN mx_tasks k ON k.id = a.task_id
                        WHERE a.track_id = %s AND a.kind = 'place' AND k.status IN ('open', 'leased')""",
                    (t["folder_id"], newest, t["folder_id"]))
        done = {p for (p,) in cur.fetchall()}
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        todo = [it["post_id"] for it in sorted(in_track(cur, t), key=lambda it: (it["at"] or epoch, it["post_id"]),
                                               reverse=True) if it["post_id"] not in done]
        for k in range(0, min(len(todo), room * PLACE_ITEMS), PLACE_ITEMS):
            batch = todo[k:k + PLACE_ITEMS]
            text = place_input(cur, t, subs, batch)
            task_id, new = repo.add_task(cur, kind=PLACE_KIND, guide=PLACE_GUIDE, subject_kind="track", input=text,
                                         a=t["folder_id"])
            cur.execute("""INSERT INTO mx_track_subtopic_asks (task_id, track_id, kind, subtopic_ids, post_ids)
                           VALUES (%s, %s, 'place', %s::uuid[], %s::uuid[]) ON CONFLICT DO NOTHING""",
                        (task_id, t["folder_id"], [s["id"] for s in subs], batch))
            if new:
                added += 1
            else:
                got = _valid_answer(cur, task_id)
                if got is not None:
                    apply_place(cur, repo.get_task(cur, task_id), got)
    return added


def apply_place(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> int:
    """A placement answer: each post (still in the track's placement asked) in its sub-topic (still current), or in
    none of them (subtopic_id NULL); never over the owner's pin. How many were placed."""
    cur.execute("SELECT track_id::text, subtopic_ids::text[], post_ids::text[] FROM mx_track_subtopic_asks WHERE task_id = %s",
                (task["id"],))
    row = cur.fetchone()
    if row is None:
        return 0
    fid, sids, pids = row
    skeys, pkeys = place_keys(task["input"])
    subs = dict(zip(skeys, sids))
    posts = dict(zip(pkeys, pids))
    cur.execute("SELECT id::text FROM mx_track_subtopics WHERE track_id = %s AND valid_to IS NULL", (fid,))
    live = {i for (i,) in cur.fetchall()}
    n = 0
    for got in answer.get("placements") or []:
        p = posts.get(got.get("post"))
        key = got.get("subtopic")
        sid = None if key == "none" else subs.get(key)
        if p is None or (key != "none" and sid not in live):
            continue
        cur.execute("""INSERT INTO mx_track_subtopic_members (track_id, post_id, subtopic_id, by, since)
                       VALUES (%s, %s, %s, 'haiku', now())
                       ON CONFLICT (track_id, post_id) DO UPDATE
                          SET subtopic_id = EXCLUDED.subtopic_id, by = 'haiku', sim = NULL,
                              since = CASE WHEN mx_track_subtopic_members.subtopic_id IS NOT DISTINCT FROM EXCLUDED.subtopic_id
                                           THEN mx_track_subtopic_members.since ELSE now() END
                        WHERE mx_track_subtopic_members.by <> 'owner'""", (fid, p, sid))
        n += cur.rowcount
    return n


def after_answer(cur: Cursor, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> None:
    """tasks.record's part: a naming or placement answer applied (a digest is read from its call when the page is
    built)."""
    if task["kind"] == NAME_KIND and task["guide"] == NAME_GUIDE:
        apply_names(cur, task, answer)
    elif task["kind"] == PLACE_KIND:
        apply_place(cur, task, answer)


# ---- the page's sections -----------------------------------------------------------------------------------

def sections(cur: Cursor, track: Dict[str, Any], items: Sequence[Dict[str, Any]], *,
             now: Optional[datetime] = None) -> Tuple[List[Dict[str, Any]], Dict[Optional[str], List[Dict[str, Any]]]]:
    """The track page's sub-topics over its placed items: ([{id, name, definition, locked, made_by, named_by, keys,
    state, created_at, last_member_at, digest}], {sub-topic id or None (Other): its in-track items}). `state` is new
    (made in NEW_DAYS), quiet (no member in FADE_DAYS) or active; a digest says whether its members changed since."""
    now = now or datetime.now(timezone.utc)
    subs = current(cur, track["folder_id"])
    mem = members(cur, track["folder_id"])
    known = {s["id"] for s in subs}
    groups: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for it in items:
        if it["place"] in IN_TRACK:
            sid = mem.get(it["post_id"])
            groups[sid if sid in known else None].append(it)
    ds = digests(cur, track["folder_id"])
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    out = []
    for s in subs:
        its = groups.get(s["id"], [])
        if not its and s["made_by"] != "owner":
            continue
        newest = sorted(its, key=lambda it: it["at"] or epoch, reverse=True)[:DIGEST_ITEMS]
        d = ds.get(s["id"])
        last = s["last_member_at"]
        state = ("new" if s["created_at"] and now - s["created_at"] < timedelta(days=NEW_DAYS) else
                 "quiet" if last is None or now - last > timedelta(days=FADE_DAYS) else "active")
        keys = sorted({fold_key(it.get("subtopic")) for it in its if fold_key(it.get("subtopic"))} | set(s["keys"]))
        out.append({**{k: s[k] for k in ("id", "name", "definition", "locked", "made_by", "named_by")}, "keys": keys,
                    "state": state, "created_at": s["created_at"], "last_member_at": last,
                    "digest": None if d is None else {
                        "points": d["points"], "at": d["at"],
                        "stale": d["posts"] != [it["post_id"] for it in newest]}})
    return out, groups


def joined_at(it: Dict[str, Any]) -> Optional[datetime]:
    """When a post joined the track: its verdict's time (an owner's ✓ without one: the post's date)."""
    return it.get("answered_at") or it.get("at")


# ---- seen: "new since you looked" ---------------------------------------------------------------------------

def seen(cur: Cursor, folder_id: Any) -> Dict[str, Any]:
    """{track: the last look at the track (ISO) or None, subtopics: {id: ISO}}."""
    cur.execute("SELECT subtopic_id::text, seen_at FROM mx_track_seen WHERE track_id = %s", (str(folder_id),))
    out: Dict[str, Any] = {"track": None, "subtopics": {}}
    for sid, at in cur.fetchall():
        if sid is None:
            out["track"] = at.isoformat()
        else:
            out["subtopics"][sid] = at.isoformat()
    return out


def look(cur: Cursor, folder_id: Any, subtopic: Optional[str] = None, *, now: Optional[datetime] = None
         ) -> Dict[str, Any]:
    """The reader looked at the track (or one of its sub-topics) now: the look before this one and the new state.
    KeyError: no such track or sub-topic."""
    from insight_core.markx import tracks
    now = now or datetime.now(timezone.utc)
    if not tracks.is_topic(tracks.get(cur, folder_id)):
        raise KeyError(folder_id)
    if subtopic is not None:
        cur.execute("SELECT 1 FROM mx_track_subtopics WHERE id = %s AND track_id = %s", (subtopic, str(folder_id)))
        if cur.fetchone() is None:
            raise KeyError(subtopic)
    before = seen(cur, folder_id)
    cur.execute("""INSERT INTO mx_track_seen (track_id, subtopic_id, seen_at) VALUES (%s, %s, %s)
                   ON CONFLICT (track_id, COALESCE(subtopic_id, '00000000-0000-0000-0000-000000000000'::uuid))
                   DO UPDATE SET seen_at = EXCLUDED.seen_at""", (str(folder_id), subtopic, now))
    return {"before": before, "now": seen(cur, folder_id)}


# ---- the owner's edits -------------------------------------------------------------------------------------

def edit(cur: Cursor, folder_id: Any, *, action: str, id: Optional[str] = None, ids: Sequence[str] = (),
         name: Optional[str] = None, definition: Optional[str] = None, keys: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """The owner's edit: rename (id, name[, definition]), merge (ids into id: their members pinned there), split (id,
    name, keys: its members whose judge string is one of `keys` move to a new sub-topic), lock / unlock (id), add
    (name[, definition]: it holds the posts whose judge string is its name). An edit locks what it makes or renames;
    the clustering never moves a pinned member, renames or closes a locked sub-topic. The current sub-topics after it.
    ValueError: a bad edit; KeyError: no such sub-topic."""
    fid = str(folder_id)
    subs = {s["id"]: s for s in current(cur, fid)}

    def one(i: Optional[str]) -> Dict[str, Any]:
        if not i or i not in subs:
            raise KeyError(i)
        return subs[i]

    name = _clean(name, 80)
    if action == "rename":
        s = one(id)
        if not name:
            raise ValueError("name: the new name")
        cur.execute("""UPDATE mx_track_subtopics SET name = %s, definition = COALESCE(%s, definition), locked = true,
                              named_by = 'owner', keys = %s WHERE id = %s""",
                    (name, _clean(definition, 300), sorted(set(s["keys"]) | {fold_key(s["name"])}), s["id"]))
    elif action == "merge":
        target = one(id)
        others = [one(i) for i in ids if i != id]
        if not others:
            raise ValueError("ids: the sub-topics to merge into this one")
        ks = set(target["keys"])
        for o in others:
            ks |= set(o["keys"]) | {fold_key(o["name"])}
            cur.execute("""UPDATE mx_track_subtopic_members SET subtopic_id = %s, by = 'owner'
                            WHERE track_id = %s AND subtopic_id = %s""", (target["id"], fid, o["id"]))
            cur.execute("UPDATE mx_track_subtopics SET valid_to = now(), merged_into = %s WHERE id = %s",
                        (target["id"], o["id"]))
        cur.execute("UPDATE mx_track_subtopic_members SET by = 'owner' WHERE subtopic_id = %s", (target["id"],))
        cur.execute("UPDATE mx_track_subtopics SET keys = %s, locked = true WHERE id = %s", (sorted(ks), target["id"]))
    elif action == "split":
        s = one(id)
        moved = {fold_key(k) for k in keys if fold_key(k)}
        if not name or not moved:
            raise ValueError("name and keys: the new sub-topic and the strings it takes")
        cur.execute("""INSERT INTO mx_track_subtopics (track_id, name, definition, keys, locked, made_by, named_by)
                       VALUES (%s, %s, %s, %s, true, 'owner', 'owner') RETURNING id::text""",
                    (fid, name, _clean(definition, 300), sorted(moved)))
        new_id = cur.fetchone()[0]
        cur.execute(f"""UPDATE mx_track_subtopic_members m SET subtopic_id = %s, by = 'owner'
                          FROM (SELECT DISTINCT ON (post_id) post_id, subtopic FROM mx_track_items WHERE track_id = %s
                                 ORDER BY post_id, version DESC) i
                         WHERE m.track_id = %s AND m.subtopic_id = %s AND i.post_id = m.post_id
                           AND btrim(regexp_replace(lower(COALESCE(i.subtopic, '')), '[\\W_]+', ' ', 'g')) = ANY(%s)""",
                    (new_id, fid, fid, s["id"], sorted(moved)))
        cur.execute("UPDATE mx_track_subtopics SET keys = %s, locked = true WHERE id = %s",
                    (sorted(set(s["keys"]) - moved), s["id"]))
    elif action in ("lock", "unlock"):
        s = one(id)
        cur.execute("UPDATE mx_track_subtopics SET locked = %s WHERE id = %s", (action == "lock", s["id"]))
    elif action == "add":
        if not name:
            raise ValueError("name: the new sub-topic's name")
        cur.execute("""INSERT INTO mx_track_subtopics (track_id, name, definition, keys, locked, made_by, named_by)
                       VALUES (%s, %s, %s, %s, true, 'owner', 'owner')""",
                    (fid, name, _clean(definition, 300), [fold_key(name)]))
    else:
        raise ValueError("action: rename, merge, split, lock, unlock or add")
    return [{**{k: s[k] for k in ("id", "name", "definition", "keys", "locked", "made_by")},
             "created_at": s["created_at"]} for s in current(cur, fid)]
