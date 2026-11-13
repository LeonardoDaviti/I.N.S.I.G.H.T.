"""The event-type seam (issue 0175, v10.16 slice H): what kind of happening a post reports, whichever guide read it.

Every module that asks "what type of event is this post (or this story)?" asks here, never the readings' raw fields,
so a read guide can change (a closed event-type field, 0166's next step) without touching a consumer.

The interface (what a caller must know):
  - `of_posts(cur, post_ids) -> {post: EventType}`: the posts with a reading under any guide this seam reads (a post
    with none is absent). `EventType` has
      - `type`: the post's closed event type (schemas.EVENT_TYPES), None when no reading gave one;
      - `origin`: who tells it (maker, relay, other), from the same reading as `type`;
      - `group` and `stage`: the happening group of the reading's main action (release, deal, funding, legal, people,
        pricing, research, announcement; None for reported / other / no main) and its stage (rumored, announced,
        released, closed). A happening's parties may refine the group (happening.key): the seam gives the action's.
  - `of_stories(cur, {story: [post ids]}) -> {story: type or None}`: the story's kind of happening (folds.story_type
    over its posts' types, in their own-date order: the most common news type, a tie to the first).
  - `types_of(cur, post_ids) -> {post: (type, origin)}`: every post asked, (None, None) when none read.
  - `typed_sql(post_column, types_placeholder)`: a SQL condition "this post has one of these types", for a query over
    a window too wide to fetch every post's type first.
  - `action_group(action) -> (group, stage)` and `from_reading(reading, guide) -> EventType`: the pure mapping, for a
    caller that already holds a reading (happening.key).
  - A round-up's items (units, markx/units.py) are typed by their own question (kind `unit_types`): `of_units(cur,
    post_ids) -> {(post, text sha): UnitType}` (type, headline, continues) and `UNIT_NEWS` / `unit_is_news`: the types
    an own round-up keeps (the News types: no promotion, opinion, explainer, community post, promo or other).
  - The type lists (v10.17, 0190), each made from schemas.EVENT_TYPES: `NEWS_TYPES` (a confirmed happening: what
    makes a story News), `LEAK`, `ANNOUNCED` (Discover's main source: an actor's own announcement) and `UNIT_NEWS`.
  - `main_objects(cur, post_ids) -> {post: object}`: the thing the main action is about, as GROUP_GUIDE's reading
    says it (components reads it to tell a component from its product).

Which guide gives what (the adapters; a new guide is one entry here, its consumers unchanged):
  - `type` / `origin`: the first of TYPE_GUIDES with a reading (today read-v3's `event_type` and `origin`, asked of
    Mark X stories' members only).
  - `group` / `stage`: GROUP_GUIDE's main.action (today read-v2's) through ACTION_GROUPS and SYNONYMS (verbs the model
    writes outside read-v2's list). A future closed type would map to a group in TYPE_GROUPS, preferred over the verb.
Readings are never changed once written (repo.add_reading: the first stays), so a post's EventType changes only when a
new reading lands.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from insight_core.markx import pairing, schemas

TYPE_GUIDES: Tuple[str, ...] = ("read-v3",)   # readings with a closed event type, preferred first
GROUP_GUIDE = "read-v2"                       # the reading whose main action names the happening group
GROUPS = ("release", "deal", "funding", "legal", "people", "pricing", "research", "announcement")

# read-v2's ACTIONS -> (group, stage).
ACTION_GROUPS: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "released": ("release", "released"), "launched": ("release", "released"), "updated": ("release", "released"),
    "announced": ("announcement", "announced"), "leaked": ("announcement", "rumored"),
    "delayed": ("release", None), "priced": ("pricing", "announced"),
    "acquired": ("deal", "announced"), "raised": ("funding", "closed"), "sued": ("legal", "announced"),
    "published": ("research", "released"), "found": ("research", None),
    "reported": (None, None), "other": (None, None),
}
# Verbs the model writes outside read-v2's list (seen on the server copy), as their ACTIONS kin.
SYNONYMS: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "introduced": ("release", "released"), "shipped": ("release", "released"), "open-sourced": ("release", "released"),
    "bought": ("deal", "announced"), "merged": ("deal", "announced"), "sold": ("deal", "announced"),
    "acquires": ("deal", "announced"), "completed": ("deal", "closed"), "closed": ("deal", "closed"),
    "invested": ("funding", "closed"),
    "filed": ("legal", "announced"), "charged": ("legal", "announced"), "ruled": ("legal", "closed"),
    "fined": ("legal", "closed"), "settled": ("legal", "closed"), "arrested": ("legal", "announced"),
    "joined": ("people", "announced"), "joins": ("people", "announced"), "hired": ("people", "announced"),
    "appointed": ("people", "announced"), "left": ("people", "announced"), "resigned": ("people", "announced"),
    "departed": ("people", "announced"),
}
# A closed event type -> its happening group, once a guide's type is trusted to name one (none yet: read-v3's types
# are a story's kind, too coarse for a happening; 0166's guide change fills this, measured first).
TYPE_GROUPS: Dict[str, Tuple[Optional[str], Optional[str]]] = {}


# The type lists every consumer reads, each made here from the closed types (schemas.EVENT_TYPES; v10.17, 0190: they
# were three hand-written copies in folds, event_types and Discover's main source).
LEAK = "leak_rumour"              # a reported, unconfirmed happening
NOT_HAPPENINGS = ("opinion_analysis", "tutorial_explainer", "digest", "community_post", "other")
# A confirmed happening's types: what makes a story News (folds.story_type, built), in EVENT_TYPES' order.
NEWS_TYPES: Tuple[str, ...] = tuple(t for t in schemas.EVENT_TYPES if t != LEAK and t not in NOT_HAPPENINGS)
# Discover's main source (0170): a happening its actor announces itself, never a lawsuit's or a regulator's.
ANNOUNCED: FrozenSet[str] = frozenset(NEWS_TYPES) - {"policy_legal"}
# 0181: a round-up item's types (schemas.UNIT_TYPES) and those an own round-up keeps: the News types (promotion_event
# is no unit type: an item's promotion is `promo`) and LEAK.
UNIT_TYPES: Tuple[str, ...] = tuple(schemas.UNIT_TYPES)
UNIT_NEWS: Tuple[str, ...] = tuple(t for t in NEWS_TYPES if t != "promotion_event") + (LEAK,)


@dataclass(frozen=True)
class UnitType:
    type: str
    headline: Optional[str]
    continues: bool


def unit_is_news(t: Optional[str]) -> bool:
    return t in UNIT_NEWS


def of_units(cur: Any, post_ids: Iterable[str]) -> Dict[Tuple[str, str], UnitType]:
    """{(round-up post, sha256 of the item's text): its UnitType} of these round-ups' typed items (mx_unit_types: the
    first valid answer for an item's text; a new split of the same words keeps its type)."""
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return {}
    cur.execute("""SELECT post_id::text, text_sha, type, headline, continues FROM mx_unit_types
                    WHERE post_id = ANY(%s::uuid[])""", (ids,))
    return {(p, sha): UnitType(t, h, bool(c)) for p, sha, t, h, c in cur.fetchall()}


@dataclass(frozen=True)
class EventType:
    type: Optional[str] = None     # the closed event type, None: no reading gave one
    origin: Optional[str] = None   # maker / relay / other, with the type
    group: Optional[str] = None    # the happening group of the main action, None: names none
    stage: Optional[str] = None


NONE = EventType()


def action_group(action: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(group, stage) of a reading's main action; (None, None) when it names no happening."""
    a = (action or "").strip().lower()
    return ACTION_GROUPS.get(a) or SYNONYMS.get(a) or (None, None)


def from_reading(reading: Optional[Mapping[str, Any]], guide: str) -> EventType:
    """The EventType one reading gives (pure): its type and origin when its guide carries them, its action's group."""
    if not reading:
        return NONE
    typ = origin = None
    if guide in TYPE_GUIDES:
        typ, origin = reading.get("event_type"), reading.get("origin")
    group, stage = TYPE_GROUPS.get(typ or "", (None, None))
    if group is None and guide == GROUP_GUIDE:
        group, stage = action_group((reading.get("main") or {}).get("action"))
    return EventType(typ, origin, group, stage)


def of_posts(cur: Any, post_ids: Iterable[str]) -> Dict[str, EventType]:
    """{post: EventType} of the posts with a reading under TYPE_GUIDES or GROUP_GUIDE (one query)."""
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return {}
    guides = list(TYPE_GUIDES) + [GROUP_GUIDE]
    cur.execute("""SELECT post_id::text, guide, reading->>'event_type', reading->>'origin', reading->'main'->>'action'
                     FROM mx_readings WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s)""", (ids, guides))
    got: Dict[str, Dict[str, Tuple]] = {}
    for pid, guide, typ, origin, action in cur.fetchall():
        got.setdefault(pid, {})[guide] = (typ, origin, action)
    out = {}
    for pid, by in got.items():
        typ = origin = None
        for g in TYPE_GUIDES:
            if g in by:
                typ, origin = by[g][0], by[g][1]
                break
        group, stage = TYPE_GROUPS.get(typ or "", (None, None))
        if group is None and GROUP_GUIDE in by:
            group, stage = action_group(by[GROUP_GUIDE][2])
        out[pid] = EventType(typ, origin, group, stage)
    return out


def types_of(cur: Any, post_ids: Iterable[str]) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """{post: (type, origin)} of every post asked ((None, None) when none read): the members' view folds and built
    read."""
    ids = [str(p) for p in post_ids if p]
    got = of_posts(cur, ids)
    return {p: (got[p].type, got[p].origin) if p in got else (None, None) for p in ids}


def of_stories(cur: Any, stories: Mapping[str, Sequence[str]]) -> Dict[str, Optional[str]]:
    """{story: its kind of happening}: folds.story_type over its posts that have a type, each at its own date
    (published, else surfaced, else fetched); None when none has one."""
    from insight_core.markx import folds
    ids = sorted({str(p) for ps in stories.values() for p in ps})
    if not ids:
        return {s: None for s in stories}
    types = of_posts(cur, ids)
    cur.execute(f"""SELECT id::text, {pairing.published_date('')} FROM posts
                    WHERE id = ANY(%s::uuid[])""", (ids,))
    at: Dict[str, datetime] = dict(cur.fetchall())
    got = {p: folds.Member(id=p, at=at[p], event_type=t.type, origin=t.origin)
           for p, t in types.items() if t.type and p in at}
    return {s: folds.story_type([got[p] for p in ps if p in got]) for s, ps in stories.items()}


def typed_sql(post: str, types: str) -> str:
    """A SQL condition: the post (the column `post`) has one of the event types the parameter `types` names (a
    text[] placeholder, e.g. "%(types)s"), by the same guide order as `of_posts`. For a query over many posts (a
    window of stories) that can't fetch every post's type first."""
    conds = []
    for n, g in enumerate(TYPE_GUIDES):
        earlier = "".join(f" AND NOT EXISTS (SELECT 1 FROM mx_readings e WHERE e.post_id = {post} AND e.guide = '{h}')"
                          for h in TYPE_GUIDES[:n])
        conds.append(f"EXISTS (SELECT 1 FROM mx_readings t WHERE t.post_id = {post} AND t.guide = '{g}'"
                     f" AND t.reading->>'event_type' = ANY({types})){earlier}")
    return "(" + " OR ".join(conds) + ")"


def main_objects(cur: Any, post_ids: Iterable[str]) -> Dict[str, str]:
    """{post: the object of its main action} under GROUP_GUIDE (posts with none absent)."""
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return {}
    cur.execute("""SELECT post_id::text, reading->'main'->>'object' FROM mx_readings
                    WHERE post_id = ANY(%s::uuid[]) AND guide = %s""", (ids, GROUP_GUIDE))
    return {pid: o for pid, o in cur.fetchall() if o}


def verbs(groups: Iterable[str]) -> List[str]:
    """The main actions whose group is one of these (lower case)."""
    gs = set(groups)
    return sorted(a for a, (g, _s) in {**ACTION_GROUPS, **SYNONYMS}.items() if g in gs)


__all__ = ["ACTION_GROUPS", "ANNOUNCED", "EventType", "GROUPS", "GROUP_GUIDE", "LEAK", "NEWS_TYPES", "NOT_HAPPENINGS",
           "SYNONYMS", "TYPE_GUIDES", "UNIT_NEWS", "UNIT_TYPES", "UnitType", "action_group", "typed_sql",
           "from_reading", "main_objects", "of_posts", "of_stories", "of_units", "types_of", "unit_is_news", "verbs"]
