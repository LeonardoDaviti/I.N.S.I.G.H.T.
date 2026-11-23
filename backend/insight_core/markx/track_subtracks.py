"""Sub-tracks and a reader's stack (Stealth v10.42, migration 0176).

**A sub-track is a track with a parent** (mx_tracks.parent_id): its own folder, description, excludes, labels,
sub-topics and page, one level deep. Its posts are its parent's posts in the track (places track and joined), never
its own sources or the passive scan:
  - **judged** (the default): each parent post is asked the track judge (kind `track`, the parent's guide) under the
    sub-track's own header: its description, excludes, stack and the parent's name. Its `in`s are in the sub-track.
  - **rest** (mx_tracks.rest): it takes the parent's posts that none of its judged siblings holds, with no question
    (its rows copy the parent's verdict: `plan_rest`); a post a sibling takes later leaves it at the next placement.
A post the parent no longer holds leaves its sub-tracks (`scope`); the owner's ✓ on a sub-track keeps it there.

**A stack** (mx_tracks.stack) is the things (mx_entities ids) the reader uses. Any track's judge reads it ("The reader
uses: ..."); a judged sub-track with a stack asks only the parent posts whose mentions (mx_mentions.entity_id) name a
thing of the stack or one under it (`stack_closure`: its versions, products and families by mx_entities.parent, and
the ids merged into one by mx_entity_redirects). Whether the post is something the reader can act on is the judge's,
from the description: no word lists here.

**Order** (mx_tracks.sort): 'newest' (the default), or 'news': a post's place in News (the kept rank of the News rows
holding it, mx_news_rank, significance and coverage only: news_rank.combine without the reader's fit), newest first
among posts News never ranked.

The parent's page lists its sub-tracks (`listing`); the routes set the shape and the stack (`set_shape`,
`set_stack`); a change of either is a new version of the sub-track (its posts asked again, the old verdicts kept).
Only mx_* tables are written.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from psycopg import Cursor

SORTS = ("newest", "news")
STACK_MAX = 50          # things in a stack, at most
LISTING_ITEMS = 5       # the newest posts the parent's page shows of each sub-track


def is_sub(track: Optional[Dict[str, Any]]) -> bool:
    return bool(track and track.get("parent_id"))


def children(cur: Cursor, folder_id: Any) -> List[Dict[str, Any]]:
    """The described sub-tracks of a track, the judged ones first (a rest sub-track reads them)."""
    from insight_core.markx import tracks
    cur.execute(tracks._select("t.parent_id = %s AND t.description IS NOT NULL AND btrim(t.description) <> ''")
                + " ORDER BY t.rest, t.created_at, t.folder_id", (str(folder_id),))
    return [dict(zip(tracks._COLS, r)) for r in cur.fetchall()]


def order(ts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tracks in the order their placements depend on: top tracks, then judged sub-tracks, then rest sub-tracks."""
    return sorted(ts, key=lambda t: (is_sub(t), bool(t.get("rest"))))


# ---- the stack ------------------------------------------------------------------------------------------------

def stack_closure(cur: Cursor, ids: Sequence[str]) -> List[str]:
    """The stack's things and every thing under one (mx_entities.parent, any depth) or made by one (its `maker` is
    the thing's key: a maker's own apps), with the ids redirected into them (a merged duplicate's mentions keep its
    old id)."""
    if not ids:
        return []
    cur.execute("""WITH RECURSIVE base(id) AS (
                       SELECT unnest(%(ids)s::uuid[])
                       UNION SELECT e.id FROM mx_entities e
                              WHERE lower(btrim(e.maker)) IN (SELECT key FROM mx_entities
                                                               WHERE id = ANY(%(ids)s::uuid[]))),
                   down(id) AS (
                       SELECT id FROM base
                       UNION SELECT e.id FROM mx_entities e JOIN down d ON e.parent = d.id)
                   SELECT id::text FROM down
                   UNION SELECT r.from_id::text FROM mx_entity_redirects r JOIN down d ON r.to_id = d.id
                    WHERE r.undone_at IS NULL""",
                {"ids": list(ids)})
    return sorted({r[0] for r in cur.fetchall()})


def stack_things(cur: Cursor, ids: Sequence[str]) -> List[Dict[str, Any]]:
    """The stack as shown: [{id, name, type}] in its order (a thing no longer known is shown by its id)."""
    if not ids:
        return []
    cur.execute("""SELECT id::text, COALESCE(shown_name, name), COALESCE(shown_type, type) FROM mx_entities
                    WHERE id = ANY(%s::uuid[])""", (list(ids),))
    got = {i: (n, t) for i, n, t in cur.fetchall()}
    return [{"id": i, "name": got.get(i, (i, None))[0], "type": got.get(i, (None, None))[1]} for i in ids]


def header_lines(cur: Cursor, track: Dict[str, Any]) -> List[str]:
    """The judge header's part for a sub-track and a stack: the parent's name, the things the reader uses."""
    from insight_core.markx import tracks
    lines = []
    if is_sub(track):
        parent = tracks.get(cur, track["parent_id"])
        if parent:
            lines.append(f"Part of: {parent['name']}")
    things = stack_things(cur, list(track.get("stack") or []))
    if things:
        lines.append("The reader uses: " + "; ".join(t["name"] for t in things))
    return lines


def touching(cur: Cursor, post_ids: Sequence[str], closure: Sequence[str]) -> Set[str]:
    """The posts among `post_ids` whose mentions name a thing of the closure: linked to one, or (a mention the linker
    has not linked yet) by one of its names (its key or an alias's: the entities' own names, no word list here)."""
    if not post_ids or not closure:
        return set()
    cur.execute("""WITH names AS (SELECT key FROM mx_entities WHERE id = ANY(%(c)s::uuid[])
                                  UNION SELECT key FROM mx_entity_aliases WHERE entity_id = ANY(%(c)s::uuid[]))
                   SELECT DISTINCT post_id::text FROM mx_mentions
                    WHERE post_id = ANY(%(p)s::uuid[])
                      AND (entity_id = ANY(%(c)s::uuid[])
                           OR (entity_id IS NULL AND name_key IN (SELECT key FROM names)))""",
                {"p": list(post_ids), "c": list(closure)})
    return {r[0] for r in cur.fetchall()}


# ---- the owner's settings -------------------------------------------------------------------------------------

def _bump(cur: Cursor, folder_id: str) -> None:
    cur.execute("""UPDATE mx_tracks SET version = version + 1, version_at = now(), updated_at = now(),
                          history_at = NULL, history_id = NULL, history_done_at = NULL WHERE folder_id = %s""",
                (folder_id,))


def set_shape(cur: Cursor, folder_id: Any, *, parent: Optional[str], rest: bool = False, sort: str = "newest"
              ) -> Dict[str, Any]:
    """Make a described track a sub-track of `parent` (judged, or `rest`), or a top track again (parent None), and its
    order. A change of parent or rest is a new version. KeyError: no such track; ValueError: a bad shape."""
    from insight_core.markx import tracks
    fid = str(folder_id)
    t = tracks.get(cur, fid)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    if sort not in SORTS:
        raise ValueError(f"sort: one of {', '.join(SORTS)}")
    if parent is not None:
        parent = str(parent)
        p = tracks.get(cur, parent)
        if parent == fid or not tracks.is_topic(p):
            raise ValueError("parent: another described track")
        if is_sub(p):
            raise ValueError("parent: a top track (sub-tracks are one level deep)")
        cur.execute("SELECT 1 FROM mx_tracks WHERE parent_id = %s LIMIT 1", (fid,))
        if cur.fetchone():
            raise ValueError("this track has sub-tracks of its own")
    rest = bool(rest) and parent is not None
    changed = (t.get("parent_id"), bool(t.get("rest"))) != (parent, rest)
    cur.execute("UPDATE mx_tracks SET parent_id = %s, rest = %s, sort = %s, updated_at = now() WHERE folder_id = %s",
                (parent, rest, sort, fid))
    if changed:
        _bump(cur, fid)
    return tracks.get(cur, fid)


def set_stack(cur: Cursor, folder_id: Any, ids: Sequence[str]) -> Dict[str, Any]:
    """The track's stack (entity ids, in the owner's order, duplicates dropped); a change is a new version.
    KeyError: no such track; ValueError: an unknown thing or too many."""
    from insight_core.markx import tracks
    fid = str(folder_id)
    t = tracks.get(cur, fid)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    want = list(dict.fromkeys(str(i) for i in ids))
    if len(want) > STACK_MAX:
        raise ValueError(f"stack: at most {STACK_MAX} things")
    if want:
        cur.execute("SELECT id::text FROM mx_entities WHERE id = ANY(%s::uuid[])", (want,))
        known = {r[0] for r in cur.fetchall()}
        if set(want) - known:
            raise ValueError("stack: no such thing: " + ", ".join(sorted(set(want) - known)))
    if want != list(t.get("stack") or []):
        cur.execute("UPDATE mx_tracks SET stack = %s::uuid[], updated_at = now() WHERE folder_id = %s", (want, fid))
        _bump(cur, fid)
    return tracks.get(cur, fid)


def find_things(cur: Cursor, q: str, *, limit: int = 12) -> List[Dict[str, Any]]:
    """The entity picker: current things whose name starts with (else contains) `q`, the most mentioned first."""
    q = " ".join((q or "").split())
    if len(q) < 2:
        return []
    cur.execute("""SELECT e.id::text, COALESCE(e.shown_name, e.name), COALESCE(e.shown_type, e.type), e.level,
                          (SELECT count(*) FROM mx_mentions m WHERE m.entity_id = e.id) n
                     FROM mx_entities e
                    WHERE COALESCE(e.shown_name, e.name) ILIKE %(like)s
                      AND NOT EXISTS (SELECT 1 FROM mx_entity_redirects r WHERE r.from_id = e.id AND r.undone_at IS NULL)
                    ORDER BY COALESCE(e.shown_name, e.name) ILIKE %(prefix)s DESC, n DESC, 2 LIMIT %(limit)s""",
                {"like": f"%{q}%", "prefix": f"{q}%", "limit": limit})
    return [{"id": i, "name": n, "type": t, "level": lv, "mentions": c} for i, n, t, lv, c in cur.fetchall()]


# ---- planning -------------------------------------------------------------------------------------------------

def parent_posts(cur: Cursor, track: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The parent's posts in the track ({post_id, at, ...}: track_subtopics.in_track), newest first."""
    from insight_core.markx import track_subtopics, tracks
    parent = tracks.get(cur, track["parent_id"])
    if not tracks.is_topic(parent):
        return []
    epoch = datetime.min
    rows = track_subtopics.in_track(cur, parent)
    return sorted(rows, key=lambda r: (r["at"].replace(tzinfo=None) if r["at"] else epoch, r["post_id"]), reverse=True)


def candidates(cur: Cursor, track: Dict[str, Any], *, limit: int) -> List[Tuple[str, Optional[datetime]]]:
    """A judged sub-track's next questions: its parent's posts with no row of this version (with a stack: those whose
    mentions touch it), newest first, at most `limit`."""
    from insight_core.markx import tracks
    if limit <= 0:
        return []
    rows = parent_posts(cur, track)
    have = tracks._has_item(cur, track, [r["post_id"] for r in rows])
    rows = [r for r in rows if r["post_id"] not in have]
    stack = list(track.get("stack") or [])
    if stack:
        hit = touching(cur, [r["post_id"] for r in rows], stack_closure(cur, stack))
        rows = [r for r in rows if r["post_id"] in hit]
    return [(r["post_id"], r["at"]) for r in rows[:limit]]


def plan_rest(cur: Cursor, track: Dict[str, Any]) -> int:
    """A rest sub-track's rows: one for each parent post in the track with none of this version, copying the parent's
    newest verdict (its task, call, confidence, sub-topic string, why): no question is asked. How many were added."""
    rows = parent_posts(cur, track)
    if not rows:
        return 0
    cur.execute("""INSERT INTO mx_track_items (track_id, post_id, version, task_id, origin, cos, verdict, confidence,
                                               subtopic, why, call_id, answered_at)
                   SELECT %(t)s, i.post_id, %(v)s, i.task_id, 'active', NULL, true, i.confidence, i.subtopic, i.why,
                          i.call_id, COALESCE(i.answered_at, now())
                     FROM (SELECT DISTINCT ON (post_id) * FROM mx_track_items
                            WHERE track_id = %(p)s AND post_id = ANY(%(ids)s::uuid[]) AND verdict IS NOT NULL
                            ORDER BY post_id, version DESC) i
                   ON CONFLICT DO NOTHING""",
                {"t": track["folder_id"], "v": track["version"], "p": track["parent_id"],
                 "ids": [r["post_id"] for r in rows]})
    return cur.rowcount


# ---- placement ------------------------------------------------------------------------------------------------

def scope(cur: Cursor, track: Dict[str, Any]) -> Optional[Tuple[Set[str], Set[str]]]:
    """(the parent's posts in the track, the posts a judged sibling holds: a rest sub-track's only) or None (a top
    track)."""
    if not is_sub(track):
        return None
    from insight_core.markx import track_subtopics
    inside = {r["post_id"] for r in parent_posts(cur, track)}
    taken: Set[str] = set()
    if track.get("rest"):
        for s in children(cur, track["parent_id"]):
            if s["folder_id"] != track["folder_id"] and not s.get("rest"):
                taken |= {r["post_id"] for r in track_subtopics.in_track(cur, s)}
    return inside, taken


def place(items: Sequence[Dict[str, Any]], track: Dict[str, Any], got: Tuple[Set[str], Set[str]]) -> None:
    """A sub-track's places over tracks.placed's: every row came from the parent (active); a post the parent no
    longer holds, or (rest) one a judged sibling holds, is out; a rest sub-track holds the others; the owner's ✓ / ✗
    stand."""
    inside, taken = got
    for it in items:
        if it["label"] in ("in", "out"):
            continue
        holds = it["post_id"] in inside and it["post_id"] not in taken
        if track.get("rest"):
            it["place"] = "track" if holds else "out"
        elif not holds:
            it["place"] = "out"


# ---- the page -------------------------------------------------------------------------------------------------

def news_rank(cur: Cursor, post_ids: Sequence[str]) -> Dict[str, float]:
    """{post: the best kept News rank of a row holding it}, significance and coverage only (no reader's fit)."""
    from insight_core.markx import news_rank as nr
    if not post_ids:
        return {}
    cur.execute("""SELECT m.p->>'post_id', r.significance, r.coverage FROM mx_news_rank r
                     JOIN mx_news n ON n.id = r.row_id AND n.run_id = r.run_id
                     CROSS JOIN LATERAL jsonb_array_elements(n.posts) AS m(p)
                    WHERE m.p->>'post_id' = ANY(%s)""", (list(post_ids),))
    out: Dict[str, float] = {}
    for pid, sig, cov in cur.fetchall():
        v = nr.combine(sig, cov or 0.0, 0.0)
        out[pid] = max(out.get(pid, 0.0), v)
    return out


def sorter(cur: Cursor, track: Dict[str, Any], items: Sequence[Dict[str, Any]]):
    """The key a section's items sort by (reverse=True): the date, or (sort 'news') News' rank, then the date."""
    epoch = float("-inf")
    if (track.get("sort") or "newest") != "news":
        return lambda it: it["at"].timestamp() if it["at"] else epoch
    ranks = news_rank(cur, [it["post_id"] for it in items])
    return lambda it: (ranks.get(it["post_id"], -1.0), it["at"].timestamp() if it["at"] else epoch)


def shape(cur: Cursor, track: Dict[str, Any]) -> Dict[str, Any]:
    """The page's part of a track's shape: its parent, rest, order and stack."""
    from insight_core.markx import tracks
    parent = tracks.get(cur, track["parent_id"]) if is_sub(track) else None
    return {"parent": {"id": parent["folder_id"], "name": parent["name"]} if parent else None,
            "rest": bool(track.get("rest")), "sort": track.get("sort") or "newest",
            "stack": stack_things(cur, list(track.get("stack") or []))}


def listing(cur: Cursor, track: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The parent's page's sub-tracks: [{id, name, description, rest, sort, stack, count, items: the first
    LISTING_ITEMS in its order}]."""
    from insight_core.markx import track_kept, track_subtopics, tracks
    out = []
    for s in children(cur, track["folder_id"]):
        rows = track_subtopics.in_track(cur, s)
        key = sorter(cur, s, rows)
        top = sorted(rows, key=key, reverse=True)[:LISTING_ITEMS]
        shown = [{"post_id": r["post_id"], "at": tracks._iso(r["at"])} for r in top]
        filled = [dict(r) for r in top]
        track_kept.fill(cur, s, filled)
        for a, b in zip(shown, filled):
            a.update({k: b.get(k) for k in ("title", "url", "source")})
        out.append({"id": s["folder_id"], "name": s["name"], "description": s["description"],
                    "rest": bool(s.get("rest")), "sort": s.get("sort") or "newest",
                    "stack": stack_things(cur, list(s.get("stack") or [])), "count": len(rows), "items": shown})
    return out
