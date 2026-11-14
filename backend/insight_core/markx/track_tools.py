"""The tools a track's practitioners use or build (issue 0207, Stealth v10.18).

One decision, owned here: which tools and products a topic track's posts are about, counted by the distinct voices
(practitioners) that discuss them and how recently. Two readers: the track page's "Tools in use" panel (`panel`) and
the track's `tool` finder (finders.py: a passive post naming one of these tools is put up for judging, `finder_ids`).

**What counts** (`rows`): the entities of the track's judged-in posts (Haiku's in, or the owner's ✓; never a post the
owner marked ✗ nor a switched-off source's) whose kind is a tool: the current identity facts' kind (0184,
entity_facts.read, when on) else the entity's type, one of TOOL_KINDS; never a generic word (facts `generic`) nor a
name the book marked not an entity. Each tool: its posts, its voices (Mark X's voice rule: a post counts as its
followed author's, else its feed's, `tasks.Post.voice`), its newest post, its posts in RECENT_DAYS, its posts in the
track itself (not only Discover), and how specific it is to the track (`share`: its posts among the track's judged-in
posts over every post naming it, SPECIFIC at least: a platform, a language or an OS that every kind of post names is
no track's tool).

**The panel** (`panel`): tools with MIN_VOICES+ voices, the subject (or the actor, or compared) of one of the posts at
least (STRONG_ROLES: not only named in passing), most voices first, then the newest; each linked to its entity
page. **The finder** (`finder_ids`): the same tools when FINDER_MIN_VOICES+ voices in the track discuss them; the most
FINDER_MAX by voices.

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
# 0207: the panel is Shadow (shown, labelled) until a blind-labelled sample passes 97% with a Wilson lower bound of 0.90
MEASURED = {"what": "tools right for the track", "right": 23, "of": 27, "lower": 0.675}
POSTS_READ = 40         # the newest posts of a tool read for its voices


def judged_in(items: Sequence[Dict[str, Any]]) -> List[str]:
    """The track's posts a tool can come from: placed in the track, joined or in Discover (Haiku's in, or the owner's
    ✓); not out, not off."""
    return [it["post_id"] for it in items if it.get("place") in ("track", "joined", "discover")]


def rows(cur: Cursor, posts: Sequence[str], in_track: Sequence[str] = (), *, now: Optional[datetime] = None
         ) -> List[Dict[str, Any]]:
    """Every tool the posts name: [{id, name, kind, what, posts, voices, last_at, recent, in_track}], most voices
    first."""
    from insight_core.markx import entity_facts, pairing, tasks
    now = now or datetime.now(timezone.utc)
    if not posts:
        return []
    cur.execute(f"""SELECT m.entity_id::text, COALESCE(e.shown_name, e.name), COALESCE(e.shown_type, e.type),
                           array_agg(DISTINCT m.post_id::text), max({pairing.ordinary_date('p')}),
                           count(DISTINCT m.post_id) FILTER (WHERE {pairing.ordinary_date('p')} >= %s),
                           count(DISTINCT m.post_id) FILTER (WHERE m.role = ANY(%s))
                      FROM mx_mentions_now m JOIN mx_entities e ON e.id = m.entity_id JOIN posts p ON p.id = m.post_id
                     WHERE m.post_id = ANY(%s::uuid[]) AND m.entity_id IS NOT NULL AND e.status <> 'not_entity'
                     GROUP BY m.entity_id, COALESCE(e.shown_name, e.name), COALESCE(e.shown_type, e.type)""",
                (now - timedelta(days=RECENT_DAYS), list(STRONG_ROLES), list(posts)))
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
               now=now)
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
    got = rows(cur, judged_in(items), now=now)
    return [c["id"] for c in got if c["voices"] >= FINDER_MIN_VOICES][:FINDER_MAX]
