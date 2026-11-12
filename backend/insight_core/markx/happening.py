"""The Happening (issue 0166 step 2): a post's reading as a key, so two posts the model read as one happening can be
paired whatever their words, their language or their entity types. Pairing's fifth source (`happening`), off unless
mx_settings `pairing_happening` is on (pairing.HAPPENING_KEY), until E1 sets its bars.

`key(reading, mentions)` is a pure function of the read-v2 reading's main {action, actors, object, numbers, date} and
the post's ent-v3 mentions (each {name, span, name_key, type, role, root}: root the entity's root through merges and
pins, or None when the mention is not linked yet):
  - group: the action's group, from read-v2's ACTIONS (schemas.ACTIONS) and a few verbs the model writes outside it
    (SYNONYMS): release, deal, funding, legal, people, pricing, research, announcement. `reported` and `other`
    name no happening: no key.
  - parties: the resolved entities the happening is between, unordered (so "A acquired B" and "B joins A" are one):
    a name resolves to the post's mention whose name key it is, or else the mention whose name key is a run of its
    words (the earliest, then the longest: "Acme's acquisition of Widget Co" -> Acme); a party is the mention's root
    entity, else "name:<name key>". Which parties count is the group's (PARTIES): a release is its thing (the
    object), a deal its organisations (2+), a round its raiser (the first actor), a people move its person and an
    organisation. An object that does not resolve is free text: no key (a funding round's object, "$100M Series A",
    is the one free text dropped).
  - stage: where the action says it (announced, rumored, released, closed), else None. Not compared: a later stage of
    one happening is a development, for the judge to tell.
  - date: the reading's stated date when it is a day (YYYY-MM-DD), else None.
  - numbers: the money amounts among the reading's numbers (a currency named), in units.
A roundup has no key (it is many happenings: until Pairing compares units). The headline and the language are never
read: a Russian and an English post with the same main have the same key.

Two keys are one happening (`same`) when their groups and parties are equal, and neither their money amounts (when
both name one: one pair within MONEY_TOLERANCE) nor their stated dates (when both state one: within the group's
window) disagree. `pairs(cur, posts, new)` is the source: the posts whose keys are one happening with a `new` post's,
of another source and both voices, dated within the group's window (Pairing's policy row), not already in one Mark IX
story; stored as mx_candidates (post_post, source 'happening').
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

THING_TYPES = frozenset({"model", "product", "software", "dataset", "document", "paper"})
PERSON_TYPES = frozenset({"person"})

# read-v2's ACTIONS -> (group, stage). `announced` and `leaked` are a release's when their object is a thing.
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
    "acquires": ("deal", "announced"), "joined": ("people", "announced"), "joins": ("people", "announced"),
    "completed": ("deal", "closed"), "closed": ("deal", "closed"),
    "invested": ("funding", "closed"),
    "filed": ("legal", "announced"), "charged": ("legal", "announced"), "ruled": ("legal", "closed"),
    "fined": ("legal", "closed"), "settled": ("legal", "closed"), "arrested": ("legal", "announced"),
    "hired": ("people", "announced"), "appointed": ("people", "announced"), "left": ("people", "announced"),
    "resigned": ("people", "announced"), "departed": ("people", "announced"),
}
GROUPS = ("release", "deal", "funding", "legal", "people", "pricing", "research", "announcement")
MONEY_TOLERANCE = 0.10      # two amounts are one when within 10% of the larger
_EXACT = "exact"


@dataclass(frozen=True)
class Party:
    id: str                    # the root entity, else "name:<name key>"
    type: Optional[str]


@dataclass(frozen=True)
class Happening:
    group: str
    parties: FrozenSet[str]
    stage: Optional[str]
    date: Optional[date]
    numbers: Tuple[float, ...]

    def index(self) -> Tuple[str, FrozenSet[str]]:
        return self.group, self.parties


# ---- names to parties ------------------------------------------------------------------------------------------

def _key(name: Optional[str]) -> str:
    from insight_core.markx.tasks import name_key
    return name_key(name)


def resolve(name: Optional[str], mentions: Sequence[Mapping[str, Any]]) -> Optional[Party]:
    """The post's mention a name is: its name key equal to one of a mention's (name or span), else the mention whose
    name key is a run of the name's words, the earliest, then the longest. None: free text."""
    k = _key(name)
    if not k:
        return None
    words = k.split()
    best: Optional[Tuple[Tuple[int, int], Mapping[str, Any]]] = None
    for m in mentions:
        keys = {x for x in (m.get("name_key"), _key(m.get("name")), _key(m.get("span"))) if x}
        if k in keys:
            return _party(m)
        for mk in keys:
            mw = mk.split()
            for at in range(len(words) - len(mw) + 1):
                if words[at:at + len(mw)] == mw:
                    rank = (at, -len(mw))
                    if best is None or rank < best[0]:
                        best = (rank, m)
                    break
    return _party(best[1]) if best else None


def _party(m: Mapping[str, Any]) -> Party:
    from insight_core.markx import schemas
    root = m.get("root")
    return Party(str(root) if root else "name:" + (m.get("name_key") or _key(m.get("name"))),
                 schemas.entity_type(m.get("type")))


# ---- numbers and dates ------------------------------------------------------------------------------------------

_CURRENCY = re.compile(r"[$€£¥₽]|\b(?:usd|eur|gbp|dollars?|euros?|долл\w*|евро|руб\w*)\b", re.I)
_AMOUNT = re.compile(r"(\d[\d,\s]*(?:\.\d+)?)\s*(k|thousand|тыс\w*|m|mn|million|млн|b|bn|billion|млрд|t|tn|trillion|трлн)?\b",
                     re.I)
_SCALE = {"k": 1e3, "thousand": 1e3, "тыс": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "млн": 1e6,
          "b": 1e9, "bn": 1e9, "billion": 1e9, "млрд": 1e9, "t": 1e12, "tn": 1e12, "trillion": 1e12, "трлн": 1e12}


def money(x: Any) -> Optional[float]:
    """An amount of money a number names ("$7B", "7 млрд долларов", "€1.5 billion"), in units; None when it names no
    currency or no amount."""
    s = str(x or "")
    if not _CURRENCY.search(s):
        return None
    m = _AMOUNT.search(s)
    if not m:
        return None
    digits = m.group(1).strip()
    if re.fullmatch(r"\d+,\d{1,2}", digits):
        digits = digits.replace(",", ".")      # a decimal comma ("1,5 млрд")
    try:
        v = float(re.sub(r"[,\s]", "", digits))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    scale = next((f for u, f in _SCALE.items() if unit == u or (unit.startswith(u) and len(u) > 2)), 1.0)
    return v * scale


def _day(s: Any) -> Optional[date]:
    m = re.fullmatch(r"\s*(\d{4})-(\d{2})-(\d{2})\s*", str(s or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---- the key ---------------------------------------------------------------------------------------------------

def _group(action: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    a = (action or "").strip().lower()
    return ACTION_GROUPS.get(a) or SYNONYMS.get(a) or (None, None)


def key(reading: Optional[Mapping[str, Any]], mentions: Sequence[Mapping[str, Any]]) -> Optional[Happening]:
    """The happening a reading's main names, or None (no main, a roundup, an action that names none, a free-text
    object, too few resolved parties for its group)."""
    if not reading or reading.get("kind") == "roundup":
        return None
    main = reading.get("main") or {}
    group, stage = _group(main.get("action"))
    if group is None:
        return None
    actors = [resolve(a, mentions) for a in (main.get("actors") or []) if isinstance(a, str)]
    obj_text = (main.get("object") or "").strip()
    obj = resolve(obj_text, mentions) if obj_text else None
    if group == "announcement" and obj is not None and obj.type in THING_TYPES:
        group = "release"                      # announcing or leaking a model, a product: its release
    if obj_text and obj is None and group != "funding":
        return None                            # a free-text object: no key
    if group in ("release", "research", "pricing", "announcement"):
        parties = {obj.id} if obj else set()
    elif group == "deal":
        parties = {p.id for p in actors + [obj] if p and p.type not in PERSON_TYPES}
        if len(parties) < 2:
            return None
    elif group == "funding":
        raiser = actors[0] if actors else None
        parties = {raiser.id} if raiser and raiser.type not in PERSON_TYPES else set()
    elif group == "people":
        ps = [p for p in actors + [obj] if p]
        if not any(p.type in PERSON_TYPES for p in ps) or not any(p.type not in PERSON_TYPES for p in ps):
            group, parties = "deal", {p.id for p in ps if p.type not in PERSON_TYPES}   # "B joins A": two orgs
            if len(parties) < 2:
                return None
        else:
            parties = {p.id for p in ps}
    else:                                      # legal
        parties = {p.id for p in actors + [obj] if p}
    if not parties:
        return None
    amounts = tuple(sorted({v for v in (money(n) for n in (main.get("numbers") or [])) if v}))
    return Happening(group, frozenset(parties), stage, _day(main.get("date")), amounts)


def same(a: Happening, b: Happening, window: timedelta) -> bool:
    """Whether two keys are one happening: one group and the same parties, no disagreeing money amounts or days."""
    if a.index() != b.index():
        return False
    if a.numbers and b.numbers and not any(abs(x - y) <= MONEY_TOLERANCE * max(x, y) for x in a.numbers for y in b.numbers):
        return False
    if a.date and b.date and abs(a.date - b.date) > window:
        return False
    return True


# ---- the source --------------------------------------------------------------------------------------------------

READING_GUIDE = "read-v2"


def _verbs(groups: Iterable[str]) -> List[str]:
    gs = set(groups) | ({"announcement"} if "release" in groups else set()) | ({"people"} if "deal" in groups else set())
    return sorted(a for a, (g, _s) in {**ACTION_GROUPS, **SYNONYMS}.items() if g in gs)


def _mentions(cur: Any, ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    from insight_core.markx import schemas
    from insight_core.markx.later import _Ids
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not ids:
        return out
    roots = _Ids(cur)
    roots.pin(cur, list(ids))
    cur.execute("""SELECT post_id::text, guide, n, entity_id::text, name, span, name_key, type, role FROM mx_mentions_now
                    WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s)""", (list(ids), schemas.mention_guides()))
    for pid, g, n, eid, name, span, nk, t, role in cur.fetchall():
        out[pid].append({"name": name, "span": span, "name_key": nk, "type": t, "role": role,
                         "root": roots.of(pid, g, n, eid)})
    return out


def keys(cur: Any, ids: Sequence[str]) -> Dict[str, Happening]:
    """{post: its happening} of the posts with a reading that names one."""
    from insight_core.markx import repo
    readings = {str(k): v["reading"] for k, v in repo.readings(cur, list(ids), READING_GUIDE).items()}
    ments = _mentions(cur, sorted(readings))
    out = {}
    for pid, r in readings.items():
        k = key(r, ments.get(pid, []))
        if k is not None:
            out[pid] = k
    return out


def pairs(cur: Any, posts: Any, new: Iterable[str]) -> int:
    """Pairing's `happening` source: post pairs of one happening touching a `new` post (pairing.Posts `posts`)."""
    from insight_core.markx import pairing
    pol = posts.pol
    mine = keys(cur, sorted(set(new)))
    posts.load(mine)
    mine = {p: k for p, k in mine.items() if posts.voice(p)}
    if not mine:
        return 0
    span = max(pol.happening_span(k.group) for k in mine.values())
    lo, hi = min(posts.at[p] for p in mine) - span, max(posts.at[p] for p in mine) + span
    cur.execute(f"""SELECT r.post_id::text FROM mx_readings r JOIN posts p ON p.id = r.post_id
                     WHERE r.guide = %s AND COALESCE(r.kind, '') <> 'roundup'
                       AND lower(r.reading->'main'->>'action') = ANY(%s)
                       AND {pairing.post_date()} BETWEEN %s AND %s""",
                (READING_GUIDE, _verbs({k.group for k in mine.values()}), lo, hi))
    pool = keys(cur, [r[0] for r in cur.fetchall()])
    posts.load(pool)
    index: Dict[Tuple[str, FrozenSet[str]], List[str]] = defaultdict(list)
    for p, k in pool.items():
        index[k.index()].append(p)
    added = 0
    for i, k in mine.items():
        window = pol.happening_span(k.group)
        for q in index.get(k.index(), ()):
            if q == i or not posts.independent(i, q) or abs(posts.at[q] - posts.at[i]) > window \
                    or posts.one_story(i, q) or not same(k, pool[q], window):
                continue
            a, b = posts.ordered(i, q)
            added += pairing._add(cur, pairing.POST_POST, a, b, "happening", None)
    return added
