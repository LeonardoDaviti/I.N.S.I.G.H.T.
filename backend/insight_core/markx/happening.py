"""The Happening (issue 0166 step 2): a post's reading as a key, so two posts the model read as one happening can be
paired whatever their words, their language or their entity types. Pairing's fifth source (`happening`), off unless
mx_settings `pairing_happening` is on (pairing.HAPPENING_KEY). Its defaults are E1's measured rules
(plan/research/exp-2026-11-12/e1: company keys sharing 2+ separate parties were right 49 of 52, 94%; with one
participant 8 of 21, so one participant makes no key).

`key(reading, mentions)` is a pure function of the read-v2 reading's main {action, actors, object, numbers, date} and
the post's ent-v3 mentions (each {name, span, name_key, type, role, maker, root}: root the entity's root through
merges and pins, or None while the mention is not linked):
  - group: the action's group, through the event-type seam (markx/event_types.action_group: read-v2's ACTIONS and
    a few verbs the model writes outside them, SYNONYMS): release, deal, funding, legal, people, pricing, research,
    announcement. Announcing or leaking a thing is its release; a people move with no person in it ("B joins A") is a deal. `reported` and `other` name no
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

**Stored** (issue 0175, mx_happenings): every read post's key is kept with the basis it was computed from (the code's
version, the reading's call, each current mention's guide, number and root); `keys(cur, ids)` reads the stored keys and
computes again only the posts whose basis moved (a new reading or mention set, a merge, a pin, a relink) or that have
none, so it returns what `compute` (the recompute) returns. A changed key adds a row, old rows stay; readers take the
newest. Written when a reading or a post's mentions land (`note`, from tasks.record), and by `backfill`, a resumable
step of the candidates job (posts never keyed by this code, newest first; then the longest-unchecked rows again).
`stored(cur, ids)` reads the newest rows as they are. The mentions are read in (guide, n) order (0166 read them in the
table's order, which is the insertion order, n's).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from insight_core.markx import event_types

THING_TYPES = frozenset({"model", "product", "software", "dataset", "document", "paper"})
PERSON_TYPES = frozenset({"person"})
NOT_PARTY_TYPES = frozenset({"place"})       # where it happened is no party to it
NOT_PARTY_ROLES = frozenset({"venue"})       # nor where it appeared
MIN_PARTIES = 2

# The action -> (group, stage) mapping is the event-type seam's (markx/event_types.py, 0175): named here for callers.
ACTION_GROUPS = event_types.ACTION_GROUPS
SYNONYMS = event_types.SYNONYMS
GROUPS = event_types.GROUPS
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
    return event_types.action_group(action)


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


# ---- stored keys (0175) -----------------------------------------------------------------------------------------
#
# mx_happenings (migration 0118) keeps each read post's key with the `basis` it was computed from: the code's version,
# the reading's call and each current mention's (guide, n, root). A reading is never changed once written and a
# mention set's rows are written once, so those name every input of `key`; a root moves with a merge, a pin or a
# relink, and the basis with it. `keys` (every caller's) reads the stored row and computes again only the posts whose
# basis moved or that have none: what it returns is what `compute` (the recompute) returns, by construction
# (tests/test_markx_happenings_stored.py). `stored` reads the newest rows as they are, for a reader that can take a key
# one backfill step old.

KEY_VERSION = "happening-v1"   # bump with any change to what a key is made of outside this module and the seam
                               # (tasks.name_key, schemas.entity_type, schemas.mention_guides)
BACKFILL_PAGE = 2000           # read posts never keyed by this code, a candidates run, newest first
SWEEP_PAGE = 500               # stored rows checked again a run, the longest unchecked first (merges, pins, relinks)

_version: Optional[str] = None


def version() -> str:
    """KEY_VERSION and the sha256 of this module's and the event-type seam's code: a change keys every post again."""
    global _version
    if _version is None:
        import hashlib
        h = hashlib.sha256(KEY_VERSION.encode())
        for path in (__file__, event_types.__file__):
            with open(path, "rb") as f:
                h.update(f.read())
        _version = KEY_VERSION + ":" + h.hexdigest()[:16]
    return _version


def _roots(cur: Any, eids: Iterable[str]) -> Any:
    """later._Ids with the current redirects reachable from these entities only (its root walk, unchanged)."""
    from insight_core.markx.later import _Ids
    ids = _Ids.__new__(_Ids)
    ids.pins, ids.redirect = {}, {}
    eids = sorted({e for e in eids if e})
    if eids:
        cur.execute("""WITH RECURSIVE walk(id) AS (
                           SELECT unnest(%s::uuid[])
                           UNION SELECT r.to_id FROM mx_entity_redirects r JOIN walk w ON r.from_id = w.id
                                  WHERE r.undone_at IS NULL)
                       SELECT r.from_id::text, r.to_id::text FROM mx_entity_redirects r JOIN walk w ON r.from_id = w.id
                        WHERE r.undone_at IS NULL""", (eids,))
        ids.redirect = dict(cur.fetchall())
    return ids


def _inputs(cur: Any, ids: Sequence[str]) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, Any]]]]:
    """({post: its reading's call} of the posts with a READING_GUIDE reading, {post: its current mentions as `key`
    reads them, the root resolved (a pin's entity, else the mention's, through the redirects), in (guide, n) order})."""
    from insight_core.markx import schemas
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if not ids:
        return {}, out
    cur.execute("SELECT post_id::text, call_id::text FROM mx_readings WHERE guide = %s AND post_id = ANY(%s::uuid[])",
                (READING_GUIDE, list(ids)))
    read = dict(cur.fetchall())
    if not read:
        return read, out
    cur.execute("""SELECT m.post_id::text, m.guide, m.n, COALESCE(pin.entity_id, m.entity_id)::text, m.name, m.span,
                          m.name_key, m.type, m.role, m.maker
                     FROM mx_mentions_now m
                     LEFT JOIN mx_entity_pins pin ON pin.post_id = m.post_id AND pin.guide = m.guide AND pin.n = m.n
                                                 AND pin.undone_at IS NULL
                    WHERE m.post_id = ANY(%s::uuid[]) AND m.guide = ANY(%s)
                    ORDER BY m.post_id, m.guide, m.n""", (sorted(read), schemas.mention_guides()))
    rows = cur.fetchall()
    roots = _roots(cur, [r[3] for r in rows])
    for pid, g, n, eid, name, span, nk, t, role, maker in rows:
        out[pid].append({"guide": g, "n": n, "name": name, "span": span, "name_key": nk, "type": t, "role": role,
                         "maker": maker, "root": roots.root(eid)})
    return read, out


def _basis(call: str, mentions: Sequence[Mapping[str, Any]]) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps([version(), READING_GUIDE, call, [[m["guide"], m["n"], m["root"]] for m in mentions]])
                          .encode()).hexdigest()


def _row_key(grp: Optional[str], parties_: Sequence[str], stage: Optional[str], at: Optional[date],
             amounts: Sequence[float]) -> Optional[Happening]:
    return None if grp is None else Happening(grp, frozenset(parties_), stage, at, tuple(amounts))


def _newest(cur: Any, ids: Sequence[str]) -> Dict[str, Tuple]:
    """{post: (row id, guide, version, basis, read_group, key or None)} of the posts' newest stored rows."""
    if not ids:
        return {}
    cur.execute("""SELECT post_id::text, id, guide, version, basis, read_group, grp, parties, stage, at, money
                     FROM mx_happenings_now WHERE post_id = ANY(%s::uuid[])""", (list(ids),))
    return {r[0]: (r[1], r[2], r[3], r[4], r[5], _row_key(*r[6:])) for r in cur.fetchall()}


def _write(cur: Any, pid: str, call: str, basis: str, read_group: Optional[str], k: Optional[Happening],
           was: Optional[Tuple]) -> None:
    """A changed key (or a post's first): a new row. The same key from a new basis: that row's basis, in place."""
    if was is not None and was[1] == READING_GUIDE and was[4] == read_group and was[5] == k:
        cur.execute("""UPDATE mx_happenings SET basis = %s, version = %s, reading_call = %s, checked_at = clock_timestamp()
                        WHERE id = %s""", (basis, version(), call, was[0]))
        return
    cur.execute("""INSERT INTO mx_happenings (post_id, guide, reading_call, version, basis, read_group, grp, parties,
                                              stage, at, money)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (pid, READING_GUIDE, call, version(), basis, read_group, k.group if k else None,
                 sorted(k.parties) if k else [], k.stage if k else None, k.date if k else None,
                 list(k.numbers) if k else []))


def keys(cur: Any, ids: Sequence[str]) -> Dict[str, Happening]:
    """{post: its happening} of the posts with a reading that names one: the stored key, computed again (and stored)
    for a post whose basis moved or that has none. Equal to `compute(cur, ids)`."""
    from insight_core.markx import repo
    read, ments = _inputs(cur, sorted({str(i) for i in ids}))
    have = _newest(cur, sorted(read))
    out: Dict[str, Happening] = {}
    stale: Dict[str, str] = {}
    for pid, call in read.items():
        basis = _basis(call, ments.get(pid, []))
        was = have.get(pid)
        if was is not None and was[3] == basis:
            if was[5] is not None:
                out[pid] = was[5]
        else:
            stale[pid] = basis
    if stale:
        readings = {str(k): v["reading"] for k, v in repo.readings(cur, sorted(stale), READING_GUIDE).items()}
        for pid, basis in stale.items():
            r = readings[pid]
            k = key(r, ments.get(pid, []))
            _write(cur, pid, read[pid], basis, event_types.from_reading(r, READING_GUIDE).group, k, have.get(pid))
            if k is not None:
                out[pid] = k
    return out


def note(cur: Any, ids: Iterable[str]) -> None:
    """A post's reading or its mentions landed (tasks.record): its key stored now."""
    keys(cur, list(ids))


def compute(cur: Any, ids: Sequence[str]) -> Dict[str, Happening]:
    """{post: its happening} computed from the readings and the mentions now, nothing read from or written to
    mx_happenings (0166's `keys`; what `keys` equals)."""
    from insight_core.markx import repo
    readings = {str(k): v["reading"] for k, v in repo.readings(cur, list(ids), READING_GUIDE).items()}
    _calls, ments = _inputs(cur, sorted(readings))
    out = {}
    for pid, r in readings.items():
        k = key(r, ments.get(pid, []))
        if k is not None:
            out[pid] = k
    return out


def stored(cur: Any, ids: Iterable[str]) -> Dict[str, Happening]:
    """{post: its newest stored key}, as stored: a merge, a pin or a relink since is in it once `keys` or `backfill`
    checked the post."""
    return {p: v[5] for p, v in _newest(cur, sorted({str(i) for i in ids})).items() if v[5] is not None}


def backfill(cur: Any, *, limit: int = BACKFILL_PAGE, sweep: int = SWEEP_PAGE) -> Dict[str, int]:
    """One resumable step (the candidates job's, each run): `limit` read posts with no stored row by this code, newest
    first, keyed; then `sweep` stored rows, the longest unchecked first, checked again. {keyed, checked, left}: `left`
    the read posts still not keyed by this code."""
    from insight_core.markx import pairing
    missing = """FROM mx_readings r JOIN posts p ON p.id = r.post_id
                 LEFT JOIN LATERAL (SELECT h.version FROM mx_happenings h WHERE h.post_id = r.post_id
                                     ORDER BY h.id DESC LIMIT 1) h ON true
                WHERE r.guide = %(g)s AND h.version IS DISTINCT FROM %(v)s"""
    params = {"g": READING_GUIDE, "v": version()}
    todo: List[str] = []
    if limit:
        cur.execute(f"SELECT r.post_id::text {missing} ORDER BY {pairing.post_date()} DESC, r.post_id LIMIT %(n)s",
                    {**params, "n": limit})
        todo = [r[0] for r in cur.fetchall()]
        keys(cur, todo)
    checked: List[str] = []
    if sweep:
        cur.execute("""SELECT post_id::text FROM mx_happenings_now WHERE version = %s AND NOT post_id = ANY(%s::uuid[])
                        ORDER BY checked_at, post_id LIMIT %s""", (version(), todo, sweep))
        checked = [r[0] for r in cur.fetchall()]
        if checked:
            keys(cur, checked)
            cur.execute("""UPDATE mx_happenings h SET checked_at = clock_timestamp()
                             FROM (SELECT DISTINCT ON (post_id) id FROM mx_happenings WHERE post_id = ANY(%s::uuid[])
                                    ORDER BY post_id, id DESC) n WHERE h.id = n.id""", (checked,))
    cur.execute(f"SELECT count(*) {missing}", params)
    return {"keyed": len(todo), "checked": len(checked), "left": cur.fetchone()[0]}


# ---- the source --------------------------------------------------------------------------------------------------

def _pool_groups(groups: Iterable[str]) -> List[str]:
    """The reading groups (event_types' group of the main action) whose keys may be of these groups: an announced
    thing is a release, a people move with no person a deal."""
    gs = set(groups)
    gs |= ({"announcement"} if "release" in gs else set()) | ({"people"} if "deal" in gs else set())
    return sorted(gs)


def pairs(cur: Any, posts: Any, new: Iterable[str]) -> int:
    """Pairing's `happening` source: post pairs of one happening touching a `new` post (pairing.Posts `posts`). Keys
    are the stored ones (`keys`); the pool is the read posts in the window whose stored reading group may make a key of
    these groups, and the read posts not yet keyed by this code (keyed then)."""
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
                      LEFT JOIN LATERAL (SELECT h.version, h.read_group FROM mx_happenings h WHERE h.post_id = r.post_id
                                          ORDER BY h.id DESC LIMIT 1) h ON true
                     WHERE r.guide = %s AND COALESCE(r.kind, '') <> 'roundup'
                       AND (h.version IS DISTINCT FROM %s OR h.read_group = ANY(%s))
                       AND {pairing.post_date()} BETWEEN %s AND %s""",
                (READING_GUIDE, version(), _pool_groups({k.group for k in mine.values()}), lo, hi))
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
