"""The tools a track's practitioners use or build: which tools a topic track's posts are about, counted by distinct
voices and recency. Read by the track page's "Tools in use" panel (`panel`) and the track's `tool` finder (finders.py,
`finder_ids`).

What counts (`rows`): the entities of the track's posts placed in it (never a Discover suggestion, an owner's ✗ or a
switched-off source's) whose kind is a tool (entity_facts' kind, else the entity's type, in TOOL_KINDS), never a
generic word or a non-entity. Each tool: its posts, voices (Mark X's voice rule), newest post, recent posts, and how
specific it is to the track (`share` at least SPECIFIC: a platform every post names is no track's tool). The panel:
MIN_VOICES+ voices and a STRONG_ROLES post at least; the finder: FINDER_MIN_VOICES+ voices, the top FINDER_MAX.
Read only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from psycopg import Cursor

TOOL_KINDS = ("product", "software", "project")
MIN_VOICES = 2          # a tool on the panel is discussed by at least this many voices of the track
SPECIFIC = 0.25         # ... and at least this share of all the posts naming it are the track's (measured, 0207)
STRONG_ROLES = ("subject", "actor", "compared")   # the panel: the subject of one post at least, not only named in passing
RECENT_DAYS = 30
PANEL_MAX = 24
FINDER_MIN_VOICES = 2
FINDER_MAX = 60
# the panel is Shadow (shown, labelled) until a blind-labelled sample passes its bar (0207)
MEASURED = {"what": "tools right for the track", "right": 23, "of": 27, "lower": 0.675}
POSTS_READ = 40         # the newest posts of a tool read for its voices


def judged_in(items: Sequence[Dict[str, Any]]) -> List[str]:
    """The track's posts a tool can come from: placed in the track or joined (the owner's ✓, an active source's in, a
    join); not out, not off, never Discover's (a suggestion not decided yet)."""
    return [it["post_id"] for it in items if it.get("place") in ("track", "joined")]


def rows(cur: Cursor, posts: Sequence[str], in_track: Sequence[str] = (), *, now: Optional[datetime] = None,
         min_posts: int = 1) -> List[Dict[str, Any]]:
    """Every tool the posts name (`min_posts` of them at least): [{id, name, kind, what, posts, voices, last_at, recent,
    in_track}], most voices first. The tool kinds and the post minimum are the query's own conditions (so it never
    returns every name's posts)."""
    from insight_core.markx import entity_facts, pairing, tasks
    now = now or datetime.now(timezone.utc)
    if not posts:
        return []
    etype = "COALESCE(e.shown_type, e.type)"
    if entity_facts.on():   # a current fact's kind is the entity's kind, a generic one is no tool (as below)
        facts_join = "LEFT JOIN mx_entity_facts f ON f.entity_id = e.id AND f.superseded_at IS NULL"
        tool = (f"COALESCE(NULLIF(f.kind, ''), {etype}) = ANY(%(kinds)s) AND f.generic IS NOT TRUE")
    else:
        facts_join, tool = "", f"{etype} = ANY(%(kinds)s)"
    cur.execute(f"""SELECT m.entity_id::text, COALESCE(e.shown_name, e.name), {etype},
                           array_agg(DISTINCT m.post_id::text), max({pairing.ordinary_date('p')}),
                           count(DISTINCT m.post_id) FILTER (WHERE {pairing.ordinary_date('p')} >= %(recent)s),
                           count(DISTINCT m.post_id) FILTER (WHERE m.role = ANY(%(strong)s))
                      FROM mx_mentions_now m JOIN mx_entities e ON e.id = m.entity_id {facts_join}
                      JOIN posts p ON p.id = m.post_id
                     WHERE m.post_id = ANY(%(posts)s::uuid[]) AND m.entity_id IS NOT NULL AND e.status <> 'not_entity'
                       AND {tool}
                     GROUP BY m.entity_id, COALESCE(e.shown_name, e.name), {etype}
                    HAVING count(DISTINCT m.post_id) >= %(min)s""",
                {"recent": now - timedelta(days=RECENT_DAYS), "strong": list(STRONG_ROLES), "posts": list(posts),
                 "kinds": list(TOOL_KINDS), "min": min_posts})
    got = cur.fetchall()
    # how specific each is to the track: its posts here over all its posts (a platform or a language every post names
    # is not this track's tool)
    cur.execute("""SELECT entity_id::text, count(DISTINCT post_id) FROM mx_mentions_now
                    WHERE entity_id = ANY(%s::uuid[]) GROUP BY 1""", ([r[0] for r in got],))
    everywhere = dict(cur.fetchall())
    facts = entity_facts.read(cur, [r[0] for r in got])
    cand = []
    for eid, name, etype, ps, last, recent, strong in got:
        f = facts.get(eid)
        kind = (f.kind if f and f.kind else etype)
        if kind not in TOOL_KINDS or (f is not None and f.generic):
            continue
        share = len(ps) / max(len(ps), int(everywhere.get(eid) or 0))
        if share < SPECIFIC - 1e-9:
            continue
        cand.append({"id": eid, "name": name, "kind": kind, "what": f.what if f else None, "post_ids": list(ps),
                     "last_at": last, "recent": int(recent or 0), "share": round(share, 3), "strong": int(strong or 0)})
    if not cand:
        return []
    inside = set(in_track)
    # the voices: Mark X's voice of each post (its followed author's, else its feed's), from its newest posts
    want = {p for c in cand for p in c["post_ids"]}
    loaded = tasks.load_posts(cur, sorted(want)) if len(want) <= 5000 else {}
    for c in cand:
        ps = c.pop("post_ids")
        newest = sorted((p for p in ps if p in loaded), key=lambda p: loaded[p].at, reverse=True)[:POSTS_READ]
        c["voices"] = len({loaded[p].voice for p in newest}) if loaded else len(ps)
        c["posts"] = len(ps)
        c["in_track"] = sum(1 for p in ps if p in inside)
    return sorted(cand, key=lambda c: (-c["voices"], -(c["last_at"] or now).timestamp(), c["name"]))


def panel(cur: Cursor, items: Sequence[Dict[str, Any]], *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The page's "Tools in use": tools with MIN_VOICES+ voices, at most PANEL_MAX, each {id, name, kind, what, posts,
    voices, last_at (ISO), recent, in_track}."""
    got = rows(cur, judged_in(items), [it["post_id"] for it in items if it.get("place") in ("track", "joined")],
               now=now, min_posts=MIN_VOICES)   # a tool's voices are never more than its posts
    out = []
    for c in got:
        if c["voices"] < MIN_VOICES or not c["strong"]:
            continue
        out.append({**c, "last_at": c["last_at"].isoformat() if c["last_at"] else None})
        if len(out) >= PANEL_MAX:
            break
    return out


def finder_ids(cur: Cursor, items: Sequence[Dict[str, Any]], *, now: Optional[datetime] = None) -> List[str]:
    """The tool finder's entities: tools FINDER_MIN_VOICES+ voices of the track discuss, at most FINDER_MAX."""
    got = rows(cur, judged_in(items), now=now, min_posts=FINDER_MIN_VOICES)
    return [c["id"] for c in got if c["voices"] >= FINDER_MIN_VOICES][:FINDER_MAX]
