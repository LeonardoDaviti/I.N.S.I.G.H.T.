"""The Happening (issue 0166 step 2): a post's reading as a key, so two posts the model read as one happening can be
paired whatever their words, their language or their entity types. Pairing's fifth source (`happening`), off unless
mx_settings `pairing_happening` is on (pairing.HAPPENING_KEY). Its defaults are E1's measured rules
(plan/research/exp-2026-11-12/e1: company keys sharing 2+ separate parties were right 49 of 52, 94%; with one
participant 8 of 21, so one participant makes no key).

`key(reading, mentions)` is a pure function of the read-v2 reading's main {action, actors, object, numbers, date} and
the post's ent-v3 mentions (each {name, span, name_key, type, role, maker, root}: root the entity's root through
merges and pins, or None while the mention is not linked):
  - group: the action's group, from read-v2's ACTIONS (schemas.ACTIONS) and a few verbs the model writes outside it
    (SYNONYMS): release, deal, funding, legal, people, pricing, research, announcement. Announcing or leaking a thing
    is its release; a people move with no person in it ("B joins A") is a deal. `reported` and `other` name no
    happening: no key. (E1: grouping on the verb alone misses happenings read under another verb, a filing read as
    filed, published or announced; the fix is a closed event type in the read guide, never a word list: 0166's next
    step.)
  - parties: the actors and the object resolved to the post's mentions (`resolve`: the mention whose name key the
    name is, else the one whose name key is a run of its words, the earliest, then the longest), unordered, so
    "A acquired B" and "B joins A" have one set. A party is the mention's root entity, else "name:<name key>". A name
    resolving to no mention is free text, no party; a place and a venue (where it appeared) are no party; a thing
    (model, product, software, ...) whose maker is another party is that party (a company and its own product are
    one: E1's three wrong pairs of 52). Fewer than 2 separate parties: no key (one maker's release has one; the
    72-hour sources keep it).
  - stage: where the action says it (rumored, announced, released, closed), else None. Not compared: a later stage of
    one happening is a development, for the judge to tell.
  - date: the reading's stated date when it is a day (YYYY-MM-DD), else None.
  - numbers: the money amounts among the reading's numbers (a currency named), in units.
A roundup has no key (it is many happenings: until Pairing compares units). The headline and the language are never
read: a Russian and an English post with the same main have the same key.

Two keys are one happening (`same`) when their groups are one, they share 2+ parties, and neither their money amounts
(when both name some: no pair within MONEY_TOLERANCE, E1's 30%) nor their stated days (when both state one: farther
apart than the group's window) disagree. `pairs(cur, posts, new)` is the source: the posts whose keys are one
happening with a `new` post's, of another source and both voices, dated within the group's window (Pairing's policy
row: deal 30 days, people 14, legal 7, every other group 72 hours), not already in one Mark IX story; stored as
mx_candidates (post_post, source 'happening'), a question for the judge, never a rule. Only the groups E1 measured
are paired (the policy's happening_groups: deal, funding, legal, people); the other groups' keys wait for theirs.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

THING_TYPES = frozenset({"model", "product", "software", "dataset", "document", "paper"})
PERSON_TYPES = frozenset({"person"})
NOT_PARTY_TYPES = frozenset({"place"})       # where it happened is no party to it
NOT_PARTY_ROLES = frozenset({"venue"})       # nor where it appeared
MIN_PARTIES = 2

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
GROUPS = ("release", "deal", "funding", "legal", "people", "pricing", "research", "announcement")
MONEY_TOLERANCE = 0.30      # E1: amounts more than ~30% apart are two happenings


@dataclass(frozen=True)
class Party:
    id: str                       # the root entity, else "name:<name key>"
    type: Optional[str]
    role: Optional[str] = None
    maker: Optional[str] = None   # the maker the mention names (a thing's), as written


@dataclass(frozen=True)
class Happening:
    group: str
    parties: FrozenSet[str]
    stage: Optional[str]
    date: Optional[date]
    numbers: Tuple[float, ...]

    def indexes(self) -> List[Tuple[str, FrozenSet[str]]]:
        """(group, two of its parties): a key one happening with this one shares one of these."""
        return [(self.group, frozenset(c)) for c in combinations(sorted(self.parties), MIN_PARTIES)]


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
                 schemas.entity_type(m.get("type")), m.get("role"), m.get("maker"))


def parties(names: Iterable[Any], mentions: Sequence[Mapping[str, Any]]) -> Dict[str, Party]:
    """{id: party} of the separate parties these names are: resolved, no place or venue, a thing whose maker is
    another party folded into it."""
    ps = {}
    for n in names:
        p = resolve(n, mentions) if isinstance(n, str) else None
        if p is not None and p.type not in NOT_PARTY_TYPES and p.role not in NOT_PARTY_ROLES:
            ps.setdefault(p.id, p)
    out = dict(ps)
    for pid, p in ps.items():
        if p.type in THING_TYPES and p.maker:
            maker = resolve(p.maker, mentions)
            if maker is not None and maker.id != pid and maker.id in ps:
                out.pop(pid, None)             # a company and its own product are one party
    return out


# ---- numbers and dates ------------------------------------------------------------------------------------------

_CURRENCY = re.compile(r"[$€£¥₽]|\b(?:usd|eur|gbp|dollars?|euros?|долл\w*|евро|руб\w*)\b", re.I)
_AMOUNT = re.compile(r"(\d[\d,\s]*(?:\.\d+)?)\s*(k|thousand|тыс\w*|m|mn|million|млн|b|bn|billion|млрд|t|tn|trillion|трлн)?\b",
                     re.I)
_SCALE = {"k": 1e3, "thousand": 1e3, "тыс": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "млн": 1e6,
          "b": 1e9, "bn": 1e9, "billion": 1e9, "млрд": 1e9, "t": 1e12, "tn": 1e12, "trillion": 1e12, "трлн": 1e12}


def money(x: Any) -> Optional[float]:
    """An amount of money a number names ("$7B", "7 млрд долларов", "€1.5 billion", "$12,930,300,000"), in units;
    None when it names no currency or no amount."""
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
    """The happening a reading's main names, or None (no main, a roundup, an action that names none, fewer than 2
    separate parties)."""
    if not reading or reading.get("kind") == "roundup":
        return None
    main = reading.get("main") or {}
    group, stage = _group(main.get("action"))
    if group is None:
        return None
    obj = (main.get("object") or "").strip()
    if group == "announcement" and obj:
        o = resolve(obj, mentions)
        if o is not None and o.type in THING_TYPES:
            group = "release"                  # announcing or leaking a model, a product: its release
    ps = parties(list(main.get("actors") or []) + ([obj] if obj else []), mentions)
    if group == "people" and not any(p.type in PERSON_TYPES for p in ps.values()):
        group = "deal"                         # "B joins A", two organisations: a deal
    if len(ps) < MIN_PARTIES:
        return None
    amounts = tuple(sorted({v for v in (money(n) for n in (main.get("numbers") or [])) if v}))
    return Happening(group, frozenset(ps), stage, _day(main.get("date")), amounts)


def same(a: Happening, b: Happening, window: timedelta) -> bool:
    """Whether two keys are one happening: one group, 2+ shared parties, no disagreeing money amounts or days."""
    if a.group != b.group or len(a.parties & b.parties) < MIN_PARTIES:
        return False
    if a.numbers and b.numbers and not any(abs(x - y) <= MONEY_TOLERANCE * max(x, y) for x in a.numbers for y in b.numbers):
        return False
    if a.date and b.date and abs(a.date - b.date) > window:
        return False
    return True


# ---- the source --------------------------------------------------------------------------------------------------

READING_GUIDE = "read-v2"


def _verbs(groups: Iterable[str]) -> List[str]:
    """The reading actions whose keys may be of these groups."""
    gs = set(groups)
    gs |= ({"announcement"} if "release" in gs else set()) | ({"people"} if "deal" in gs else set())
    return sorted(a for a, (g, _s) in {**ACTION_GROUPS, **SYNONYMS}.items() if g in gs)


def _mentions(cur: Any, ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    from insight_core.markx import schemas
    from insight_core.markx.later import _Ids
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not ids:
        return out
    roots = _Ids(cur)
    roots.pin(cur, list(ids))
    cur.execute("""SELECT post_id::text, guide, n, entity_id::text, name, span, name_key, type, role, maker
                     FROM mx_mentions_now WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s)""",
                (list(ids), schemas.mention_guides()))
    for pid, g, n, eid, name, span, nk, t, role, maker in cur.fetchall():
        out[pid].append({"name": name, "span": span, "name_key": nk, "type": t, "role": role, "maker": maker,
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
    mine = {p: k for p, k in mine.items() if posts.voice(p) and k.group in pol.happening_groups}
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
        for x in k.indexes():
            index[x].append(p)
    added = 0
    for i, k in mine.items():
        window = pol.happening_span(k.group)
        for q in sorted({q for x in k.indexes() for q in index.get(x, ())}):
            if q == i or q not in posts.at or not posts.independent(i, q) or abs(posts.at[q] - posts.at[i]) > window \
                    or posts.one_story(i, q) or not same(k, pool[q], window):
                continue
            a, b = posts.ordered(i, q)
            added += pairing._add(cur, pairing.POST_POST, a, b, "happening", None)
    return added
