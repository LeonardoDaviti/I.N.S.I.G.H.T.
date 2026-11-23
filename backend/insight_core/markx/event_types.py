"""The event-type seam: what kind of happening a post reports, whichever guide read it.

Every module that asks "what type of event is this post (or story)?" asks here, never the readings' raw fields, so a
read guide can change without touching a consumer. Entry points: `of_posts` ({post: EventType}: `type`, `origin`,
`group`, `stage`, `subtype`: the type's finer kind from ent-v6, None before it), `of_stories`, `types_of`, `typed_sql` (a SQL condition for a window too wide to fetch), the pure
`action_group` and `from_reading`, `of_units` / `unit_is_news` (a round-up's items), `main_objects`, and the type lists
made from schemas.EVENT_TYPES (NEWS_TYPES, LEAK, ANNOUNCED, UNIT_NEWS). `type` / `origin` come from the first of
TYPE_GUIDES with a reading; `group` / `stage` from GROUP_GUIDE's main.action (ACTION_GROUPS, SYNONYMS). A new guide is
one entry here. Readings are never changed once written, so a post's EventType changes only when a new reading lands.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from insight_core.markx import pairing, schemas

TYPE_GUIDES: Tuple[str, ...] = ("read-v3",)   # readings with a closed event type, preferred first
GROUP_GUIDE = "read-v2"                       # the reading whose main action names the happening group
V5 = "ent-v5"                                 # ent-v5's reading carries both (read-v3's type, read-v2's main)


def type_guides(cur: Any) -> List[str]:
    """TYPE_GUIDES through reading5's one preference list (ent-v5 first while its switch is on)."""
    from insight_core.markx import reading5
    return reading5.guides(cur, *TYPE_GUIDES)


def group_guides(cur: Any) -> List[str]:
    from insight_core.markx import reading5
    return reading5.guides(cur, GROUP_GUIDE)
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
# are a story's kind, too coarse for a happening).
TYPE_GROUPS: Dict[str, Tuple[Optional[str], Optional[str]]] = {}


# The type lists every consumer reads, each made here from the closed types (schemas.EVENT_TYPES).
LEAK = "leak_rumour"              # a reported, unconfirmed happening
RELEASES = frozenset({"model_release", "product_release"})   # a release itself (news.launch_order)
NOT_HAPPENINGS = ("opinion_analysis", "tutorial_explainer", "digest", "community_post", "other")
# A confirmed happening's types: what makes a story News (folds.story_type, built), in EVENT_TYPES' order.
NEWS_TYPES: Tuple[str, ...] = tuple(t for t in schemas.EVENT_TYPES if t != LEAK and t not in NOT_HAPPENINGS)
# Discover's main source: a happening its actor announces itself, never a lawsuit's or a regulator's.
ANNOUNCED: FrozenSet[str] = frozenset(NEWS_TYPES) - {"policy_legal"}
# a round-up item's types (schemas.UNIT_TYPES) and those an own round-up keeps: the News types (promotion_event
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
    subtype: Optional[str] = None  # v10.42: the type's finer kind (schemas.SUBTYPES), with the type; None: none given


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
    if guide in TYPE_GUIDES or guide == V5:
        typ, origin = reading.get("event_type"), reading.get("origin")
    subtype = reading.get("subtype") if guide == V5 else None
    group, stage = TYPE_GROUPS.get(typ or "", (None, None))
    if group is None and guide in (GROUP_GUIDE, V5):
        group, stage = action_group((reading.get("main") or {}).get("action"))
    return EventType(typ, origin, group, stage, subtype)


def of_posts(cur: Any, post_ids: Iterable[str]) -> Dict[str, EventType]:
    """{post: EventType} of the posts with a reading under TYPE_GUIDES or GROUP_GUIDE (one query)."""
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return {}
    types, groups = type_guides(cur), group_guides(cur)
    guides = sorted(set(types) | set(groups))
    cur.execute("""SELECT post_id::text, guide, reading->>'event_type', reading->>'origin', reading->'main'->>'action',
                          reading->>'subtype' FROM mx_readings WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s)""", (ids, guides))
    got: Dict[str, Dict[str, Tuple]] = {}
    for pid, guide, typ, origin, action, subtype in cur.fetchall():
        got.setdefault(pid, {})[guide] = (typ, origin, action, subtype)
    out = {}
    for pid, by in got.items():
        typ = origin = subtype = None
        for g in types:
            if g in by:
                typ, origin, subtype = by[g][0], by[g][1], by[g][3]
                break
        group, stage = TYPE_GROUPS.get(typ or "", (None, None))
        for g in groups:
            if group is None and g in by:
                group, stage = action_group(by[g][2])
                break
        out[pid] = EventType(typ, origin, group, stage, subtype)
    return out


# a reading's kind and main action as a closed type, for a consumer that has a reading but no closed type (read-v2):
# a round-up a digest, a commentary an opinion, a tool an explainer; a report by its action's happening group, an
# announcement still rumoured a leak.
KIND_TYPES = {"roundup": "digest", "commentary": "opinion_analysis", "tool": "tutorial_explainer"}
GROUP_TYPES = {"release": "model_release", "pricing": "product_release", "deal": "business_event",
               "funding": "business_event", "legal": "policy_legal", "people": "public_statement",
               "research": "research_result"}


def reading_type(kind: Optional[str], action: Optional[str]) -> Optional[str]:
    """The closed event type a reading's kind and main action say (pure; None: no happening named)."""
    if kind in KIND_TYPES:
        return KIND_TYPES[kind]
    group, stage = action_group(action)
    if group == "announcement":
        return LEAK if stage == "rumored" else None
    return GROUP_TYPES.get(group or "")


def reading_types(cur: Any, post_ids: Iterable[str]) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """{post: (reading_type of its preferred reading, that reading's kind)} of the posts with a reading (one query;
    the preferred reading as the post panel picks it, reading5.rank_sql)."""
    from insight_core.markx import reading5
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return {}
    rank = reading5.rank_sql("guide")
    cur.execute(f"""SELECT DISTINCT ON (post_id) post_id::text, kind, reading->'main'->>'action' FROM mx_readings
                     WHERE post_id = ANY(%s::uuid[]) AND {rank} IS NOT NULL ORDER BY post_id, {rank}""", (ids,))
    return {pid: (reading_type(kind, action), kind) for pid, kind, action in cur.fetchall()}


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


def typed_sql(post: str, types: str, guides: Sequence[str] = TYPE_GUIDES) -> str:
    """A SQL condition: the post (the column `post`) has one of the event types the parameter `types` names (a
    text[] placeholder, e.g. "%(types)s"), by the same guide order as `of_posts`. For a query over many posts (a
    window of stories) that can't fetch every post's type first."""
    conds = []
    for n, g in enumerate(guides):   # `guides` = type_guides(cur) at the caller (ent-v5 first when on)
        earlier = "".join(f" AND NOT EXISTS (SELECT 1 FROM mx_readings e WHERE e.post_id = {post} AND e.guide = '{h}')"
                          for h in guides[:n])
        conds.append(f"EXISTS (SELECT 1 FROM mx_readings t WHERE t.post_id = {post} AND t.guide = '{g}'"
                     f" AND t.reading->>'event_type' = ANY({types})){earlier}")
    return "(" + " OR ".join(conds) + ")"


def main_objects(cur: Any, post_ids: Iterable[str]) -> Dict[str, str]:
    """{post: the object of its main action} under GROUP_GUIDE (posts with none absent)."""
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return {}
    order = group_guides(cur)
    cur.execute("""SELECT DISTINCT ON (post_id) post_id::text, reading->'main'->>'object' FROM mx_readings
                    WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s)
                    ORDER BY post_id, array_position(%s::text[], guide)""", (ids, order, order))
    return {pid: o for pid, o in cur.fetchall() if o}


def verbs(groups: Iterable[str]) -> List[str]:
    """The main actions whose group is one of these (lower case)."""
    gs = set(groups)
    return sorted(a for a, (g, _s) in {**ACTION_GROUPS, **SYNONYMS}.items() if g in gs)


__all__ = ["ACTION_GROUPS", "ANNOUNCED", "EventType", "GROUPS", "GROUP_GUIDE", "LEAK", "NEWS_TYPES", "NOT_HAPPENINGS",
           "SYNONYMS", "TYPE_GUIDES", "UNIT_NEWS", "UNIT_TYPES", "UnitType", "action_group", "typed_sql",
           "from_reading", "main_objects", "of_posts", "of_stories", "of_units", "reading_type", "reading_types", "types_of", "unit_is_news", "verbs"]
