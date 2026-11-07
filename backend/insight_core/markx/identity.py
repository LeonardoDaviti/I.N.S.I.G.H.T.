"""Mark X entity identity (issue 0119 A1, 0090 C): one entity per thing, its versions, merges, the review queue.

The decision run's `entities` stage (`stage`), in the run's one snapshot, writing mx_entity* rows and mx_mentions'
entity_id only:

  1. **Linking** (incremental: the mentions not linked yet, LINK_LIMIT a run, newest first; the nightly full pass
     relinks every mention and must match, `counts.check`):
       - an exact key in the aliases links (`names.key`: the name key with '@' and 'the ' dropped);
       - a known family with a new version or variant creates a provisional child of it;
       - an unknown family creates a provisional family (and its child);
       - the mention's entity_id is the most specific level the post states (the entity of its own key); a merge
         is a redirect read through (`Book.root`), and an owner's split a pin (mx_entity_pins) the run applies.
  2. **Candidates** (experiment 2's pool; 0/80 missed aliases outside it) for the entities new this run, those whose
     name vector arrived, and the posts linked this run: the same family key; a name vector's 10 nearest at cosine
     >= 0.80; squashed equality, word containment at word boundaries, trigram Jaccard >= 0.5; a handle's forms; the
     maker-prefix forms; a shared repository or model address; "X (Y)" inside one post.
  3. **Merging, conservatively** (experiment 2's v2 settings, 0119 A1 as written on 2026-11-06), `decide_pair`:
       - automatic: a rule (squashed equal; the same address; a person's handle or a handle with no extra word; the
         maker prefix when the bare name's maker is stated in a post; the same family, version tuple, variant, size
         and build in Haiku's fields with the parser agreeing and the same maker or one side none), or Haiku `same`
         at >= 0.9; and the guards: version (both parse to one version and variant, an edition year on one side is a
         conflict), type (equal, product~software, or one side `other`), chain (no merge joins two clusters of 2 or
         more names; at most 6 names a cluster);
       - the queue (mx_entity_queue): every other `same`: below 0.9, a one-sided version, a type mismatch, a chain,
         an org's handle with an extra word, "X (Y)", Haiku's fields agreeing but not the parser's, the maker prefix
         with the maker only guessed, a Haiku-parser disagreement on the version; and the collision judge's splits;
       - never automatic: different parsed versions or variants; a bare family and one of its versions.
     Every merge is a redirect (by its rule, Haiku or the owner) and can be undone (`undo`). A pair the owner
     answered, or a merge the owner undid, is never merged again by a rule or Haiku.
  4. **Collisions:** a key whose mentions differ in type or (stated) maker gets the collision judge (`collide`),
     asked COLLIDE_RUNS times; a split two of the runs make is queued as a proposal, never applied.

The owner's answers (`answer`, the API's, in the request's own transaction: mx_entity* and mx_labels only) apply at
once for the pages, which read through redirects and pins; the next run's snapshot sees them.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import errors as psycopg_errors

from insight_core.markx import names as N

log = logging.getLogger(__name__)

LINK_LIMIT = 6000           # mentions linked a run (the rest wait: the 120 s run limit)
PAIR_LIMIT = 200000         # pool pairs decided a run (a safety cap: the 120-day full pass pools about 29,000)
SEED_CHUNK = 1000           # 0128: the full pass's entities pooled and decided at once (its budget is checked between)
EMB_BAR, EMB_TOPK = 0.80, 10
JAC_BAR = 0.50
GRAM_CAP, GRAM_TOP = 400, 60
AUTO_CONF = 0.9             # Haiku `same` at or above: automatic (33/33 test, 25/25 test2)
RULE_CONF = 0.97            # a rule's merge, for the chain guard's order
MAX_CLUSTER = 6
ALIAS_CAP, COLLIDE_CAP = 10000, 1000   # new questions a run adds of each (a pair over it waits for the nightly pass)
COLLIDE_RUNS = 3
COLLIDE_MENTIONS = 8
QUEUE_ONLY = {"paren", "handle_extra_word", "maker_unstated", "fields_parser"}
TYPES_VERSIONED = {"model", "product", "software", "project", "dataset"}
ANCHOR_RE = re.compile(r"(github\.com|huggingface\.co)/([\w.-]+)/([\w.-]+)", re.I)
ANSWERS = ("same", "other_version", "different", "not_entity")


# ---- what identity knows: entities, aliases, redirects, pins ------------------------------------------

@dataclass
class Ent:
    id: str
    type: Optional[str]
    name: str
    key: str
    level: str = "thing"
    parent: Optional[str] = None
    maker: Optional[str] = None
    family_key: Optional[str] = None
    version: Optional[str] = None
    version_key: Optional[Tuple] = None
    variant: Optional[str] = None
    size: Optional[str] = None
    build: Optional[str] = None
    status: str = "provisional"
    first_seen: Optional[datetime] = None
    haiku: Dict[str, Any] = field(default_factory=dict)       # the fields as Haiku gave them (majority mention)

    @property
    def hk(self) -> Tuple:
        return N.fields_key(self.haiku, self.maker)

    @property
    def pk(self) -> Tuple:
        return N.fields_key(N.parse(self.name, self.type, self.maker), self.maker)

    @property
    def sq(self) -> str:
        return N.squash(self.key)


class Book:
    """The entities, aliases, current redirects and pins, read once a run (or once a request)."""

    def __init__(self) -> None:
        self.ents: Dict[str, Ent] = {}
        self.alias: Dict[str, str] = {}
        self.redirect: Dict[str, Tuple[str, bool]] = {}      # from -> (to, automatic)
        self.pins: Dict[Tuple[str, str, int], str] = {}
        self.never: Set[Tuple[str, str]] = set()             # pairs the owner kept apart or whose merge was undone
        self.mentioned: Set[str] = set()                     # the entities a mention names (a maker or family made
                                                             # for the hierarchy alone is never a candidate)

    def root(self, eid: Optional[str]) -> Optional[str]:
        seen = set()
        while eid in self.redirect and eid not in seen:
            seen.add(eid)
            eid = self.redirect[eid][0]
        return eid

    def members(self) -> Dict[str, Set[str]]:
        out: Dict[str, Set[str]] = defaultdict(set)
        for eid in self.ents:
            out[self.root(eid)].add(eid)
        return out

    def by_key(self, k: Optional[str]) -> Optional[str]:
        return self.alias.get(k) if k else None


def load_book(cur: Any) -> Book:
    b = Book()
    cur.execute("""SELECT id::text, type, name, key, level, parent::text, maker, family_key, version, version_key, variant,
                          size, build, status, first_seen FROM mx_entities""")
    for (eid, type_, name, key, level, parent, maker, fam, version, vkey, variant, size, build, status,
         first) in cur.fetchall():
        b.ents[eid] = Ent(eid, type_, name, key, level, parent, maker, fam, version, N.from_json(vkey), variant, size,
                          build, status, first, haiku={"family": fam, "version": version, "variant": variant,
                                                       "size": size, "build": build})
    cur.execute("SELECT key, entity_id::text FROM mx_entity_aliases")
    b.alias = dict(cur.fetchall())
    cur.execute("SELECT from_id::text, to_id::text, automatic FROM mx_entity_redirects WHERE undone_at IS NULL")
    b.redirect = {f: (t, auto) for f, t, auto in cur.fetchall()}
    cur.execute("SELECT post_id::text, guide, n, entity_id::text FROM mx_entity_pins WHERE undone_at IS NULL")
    b.pins = {(p, g, n): e for p, g, n, e in cur.fetchall()}
    cur.execute("""SELECT least(a, b)::text, greatest(a, b)::text FROM mx_entity_queue
                    WHERE kind = 'alias' AND answer IN ('other_version', 'different', 'not_entity')
                   UNION SELECT least(from_id, to_id)::text, greatest(from_id, to_id)::text FROM mx_entity_redirects
                    WHERE undone_at IS NOT NULL AND undone_by = 'owner'""")
    b.never = {(x, y) for x, y in cur.fetchall()}
    cur.execute("SELECT DISTINCT entity_id::text FROM mx_mentions WHERE entity_id IS NOT NULL")
    b.mentioned = {r[0] for r in cur.fetchall()} | set(b.pins.values())
    return b


def pair(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a < b else (b, a)


# ---- linking ---------------------------------------------------------------------------------------

@dataclass
class Mention:
    post_id: str
    guide: str
    n: int
    span: str
    name: str
    type: Optional[str]
    role: Optional[str]
    maker: Optional[str]
    fields: Dict[str, Any]
    entity_id: Optional[str]
    at: Optional[datetime]

    @property
    def key(self) -> str:
        return N.key(self.name)


def _mentions(cur: Any, guide: str, *, unlinked: bool, limit: Optional[int] = None) -> List[Mention]:
    cur.execute(f"""SELECT m.post_id::text, m.guide, m.n, m.span, m.name, m.type, m.role, m.maker, m.family, m.version,
                           m.variant, m.size, m.build, m.entity_id::text,
                           COALESCE(p.published_at, p.fetched_at)
                      FROM mx_mentions m LEFT JOIN posts p ON p.id = m.post_id
                     WHERE m.guide = %s {"AND m.entity_id IS NULL AND m.name_key <> ''" if unlinked else ""}
                     ORDER BY COALESCE(p.published_at, p.fetched_at) DESC NULLS LAST, m.post_id, m.n
                     {"LIMIT %s" if limit else ""}""", (guide, limit) if limit else (guide,))
    return [Mention(p, g, n, span or "", name or "", t, r, mk,
                    {"family": fam, "version": v, "variant": var, "size": sz, "build": bd}, e, at)
            for p, g, n, span, name, t, r, mk, fam, v, var, sz, bd, e, at in cur.fetchall()]


def _majority(ms: Sequence[Mention]) -> Mention:
    """The mention that speaks for a new key: its most common (type, maker, fields), then name, then the earliest."""
    sig = Counter((m.type, m.maker, json.dumps(m.fields, sort_keys=True)) for m in ms)
    names = Counter(m.name for m in ms)
    best = max(sig.items(), key=lambda kv: (kv[1], str(kv[0])))[0]
    pick = [m for m in ms if (m.type, m.maker, json.dumps(m.fields, sort_keys=True)) == best]
    return min(pick, key=lambda m: (-names[m.name], m.at or datetime.max.replace(tzinfo=timezone.utc), m.post_id, m.n))


def _level(hk: Tuple, pk: Tuple) -> str:
    fk = hk if N.has_version(hk) else pk
    if fk[3] or fk[4]:
        return "checkpoint"
    if fk[2]:
        return "variant"
    return "version"


class Writer:
    """New entities and aliases, written as they are made (so the book always holds what the database does)."""

    def __init__(self, cur: Any, book: Book, run_id: Any) -> None:
        self.cur, self.book, self.run_id = cur, book, run_id
        self.made: List[str] = []

    def entity(self, *, type_: Optional[str], name: str, key: str, level: str, parent: Optional[str],
               maker: Optional[str], fields: Dict[str, Any], first_seen: Optional[datetime]) -> str:
        fk = N.fields_key(fields, maker)
        self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, parent, maker, family_key, version, version_key,
                                                     variant, size, build, first_seen, run_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) RETURNING id::text""",
                         (type_, name, key, level, parent, maker, fk[0], fields.get("version"),
                          json.dumps(N.version_json(fk[1])), fields.get("variant"), fields.get("size"),
                          fields.get("build"), first_seen, self.run_id))
        eid = self.cur.fetchone()[0]
        self.book.ents[eid] = Ent(eid, type_, name, key, level, parent, maker, fk[0], fields.get("version"), fk[1],
                                  fields.get("variant"), fields.get("size"), fields.get("build"), "provisional",
                                  first_seen, haiku=dict(fields))
        self.alias(key, eid, name)
        self.made.append(eid)
        return eid

    def alias(self, key: str, eid: str, name: str, source: str = "rule", call_id: Any = None) -> None:
        self.cur.execute("""INSERT INTO mx_entity_aliases (key, entity_id, language, mixed, source, call_id)
                            VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING""",
                         (key, eid, N.language(name), N.mixed_word(name), source, call_id))
        self.book.alias.setdefault(key, eid)


def _maker_entity(w: Writer, maker: Optional[str], at: Optional[datetime]) -> Optional[str]:
    """The entity a stated maker names (its alias), made as a provisional org when there is none."""
    mk = N.key(maker)
    if not mk:
        return None
    got = w.book.by_key(mk)
    if got:
        return w.book.root(got)
    return w.entity(type_="org", name=maker.strip(), key=mk, level="thing", parent=None, maker=None,
                    fields=dict(N.NONE), first_seen=at)


def entity_for(w: Writer, key: str, ms: Sequence[Mention]) -> str:
    """The entity of a key with no alias yet, made from its mentions (0090 C: a known family's new version is its
    provisional child; an unknown family is made provisional too)."""
    m = _majority(ms)
    first = min((x.at for x in ms if x.at), default=None)
    hk = N.fields_key(m.fields, m.maker)
    pk = N.fields_key(N.parse(m.name, m.type, m.maker), m.maker)
    versioned = m.type in TYPES_VERSIONED and (N.has_version(hk) or N.has_version(pk))
    maker = (m.maker or "").strip() or None
    if not versioned:
        parent = _maker_entity(w, maker, first) if maker and N.key(maker) != key else None
        return w.entity(type_=m.type, name=m.name, key=key, level="thing", parent=parent, maker=maker,
                        fields=dict(N.NONE), first_seen=first)
    fam_key = hk[0] if N.has_version(hk) and hk[0] else pk[0]
    parent = None
    if fam_key and fam_key != key:
        parent = w.book.root(w.book.by_key(fam_key))
        if parent is None:
            fam_name = (m.fields.get("family") or "").strip() if N.has_version(hk) else ""
            if not fam_name or N.key(fam_name) != fam_key:
                fam_name = fam_key
            up = _maker_entity(w, maker, first) if maker and N.key(maker) != fam_key else None
            parent = w.entity(type_=m.type, name=fam_name, key=fam_key, level="family", parent=up, maker=maker,
                              fields=dict(N.NONE), first_seen=first)
    fields = dict(m.fields) if N.has_version(hk) else dict(N.parse(m.name, m.type, m.maker))
    return w.entity(type_=m.type, name=m.name, key=key, level=_level(hk, pk), parent=parent, maker=maker,
                    fields=fields, first_seen=first)


def resolve_mention(book: Book, m: Mention) -> Optional[str]:
    """The entity a mention links to now: its pin, else its key's alias (before redirects; reads go through them)."""
    pin = book.pins.get((m.post_id, m.guide, m.n))
    if pin:
        return pin
    return book.by_key(m.key)


def link(cur: Any, book: Book, w: Writer, ms: Sequence[Mention]) -> Dict[str, int]:
    """Each mention's entity, made when its key has none; entity_id written where it changes."""
    by_key: Dict[str, List[Mention]] = defaultdict(list)
    for m in ms:
        if m.key:
            by_key[m.key].append(m)
    for k in sorted(by_key):
        if book.by_key(k) is None:
            entity_for(w, k, by_key[k])
    changes = []
    for m in ms:
        eid = resolve_mention(book, m) if m.key else None
        if eid and eid != m.entity_id:
            changes.append((eid, m.post_id, m.guide, m.n))
            m.entity_id = eid
    if changes:
        cur.executemany("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND guide = %s AND n = %s", changes)
    return {"mentions": len(ms), "linked": len(changes), "entities_made": len(w.made)}


# ---- the pool ---------------------------------------------------------------------------------------

def vconflict(a: Ent, b: Ent, literal: bool = False) -> Optional[str]:
    """'strong': both name a version, variant, size or build and they differ; 'soft': one names one the other lacks
    (or an edition year on one side only); None. `literal`: the two names are one string once the maker and the
    separators go, so only the parser's split counts (the lab's vconflict)."""
    worst = None
    ya, yb = N.years(a.key), N.years(b.key)
    if ya != yb and not literal:
        if ya and yb:
            return "strong"
        worst = "soft"
    for ka, kb in (((a.pk, b.pk),) if literal else ((a.hk, b.hk), (a.pk, b.pk))):
        for i, (x, y) in enumerate(zip(N.version_part(ka), N.version_part(kb))):
            if (N.ver_eq(x, y) if i == 0 else x == y):
                continue
            if x is not None and y is not None:
                return "strong"
            worst = "soft"
    return worst


def strong_only_one(a: Ent, b: Ent) -> bool:
    """A strong version conflict in Haiku's fields or the parser's, not both: a Haiku-parser disagreement."""
    def strong(ka, kb):
        return any(x is not None and y is not None and not (N.ver_eq(x, y) if i == 0 else x == y)
                   for i, (x, y) in enumerate(zip(N.version_part(ka), N.version_part(kb))))
    return strong(a.hk, b.hk) != strong(a.pk, b.pk) and not (N.years(a.key) and N.years(b.key) and N.years(a.key) != N.years(b.key))


def types_ok(a: Optional[str], b: Optional[str]) -> bool:
    return a == b or "other" in (a, b) or {a, b} == {"product", "software"}


def family_link(a: Ent, b: Ent) -> bool:
    """A bare family and a version of it: parent and child, never an alias."""
    for x, y in ((a, b), (b, a)):
        has_x = N.has_version(x.hk) or N.has_version(x.pk)
        has_y = N.has_version(y.hk) or N.has_version(y.pk)
        if not has_x and has_y and y.hk[0] and (N.squash(y.hk[0]) == x.sq or N.squash(y.pk[0] or "") == x.sq):
            return True
    return False


def maker_prefix(x: Ent, y: Ent) -> bool:
    """x is y with its maker in front ("zeta z 200" = maker Zeta + "z 200"); y names no other maker."""
    for m in {N.key(x.maker or ""), N.key(y.maker or "")} - {""}:
        if x.key.startswith(m + " ") and N.squash(x.key[len(m) + 1:]) == y.sq and (not y.maker or N.key(y.maker) == m):
            return True
    return False


def fields_rule(a: Ent, b: Ent) -> Optional[str]:
    """'auto': the same family, version tuple, variant, size and build in Haiku's fields, the parser's version,
    variant, size and build agreeing, and the same maker or one side none (22/22 unseen); 'queue': only Haiku's
    fields agree (34/39); None. Family + version + variant alone is never a merge (3/59)."""
    if not (N.has_version(a.hk) and a.hk == b.hk and a.hk[0]):
        return None
    if a.maker and b.maker and N.key(a.maker) != N.key(b.maker):
        return None
    return "auto" if N.version_part(a.pk) == N.version_part(b.pk) else "queue"


@dataclass
class Pooled:
    a: str
    b: str
    why: Set[str] = field(default_factory=set)
    rules: Set[str] = field(default_factory=set)


class Pool:
    def __init__(self, book: Book) -> None:
        self.book = book
        self.pairs: Dict[Tuple[str, str], Pooled] = {}

    def add(self, a: str, b: str, why: str, rule: Optional[str] = None) -> None:
        if a == b or a not in self.book.mentioned or b not in self.book.mentioned:
            return
        x, y = pair(a, b)
        p = self.pairs.setdefault((x, y), Pooled(x, y))
        p.why.add(why)
        if rule:
            p.rules.add(rule)


def _live(book: Book) -> List[Ent]:
    return [e for e in book.ents.values() if e.status != "not_entity" and e.id in book.mentioned]


def _index(book: Book, name: str, build: Any) -> Any:
    """An index over the live entities, built once a book (0128: the full pass's chunks share it). The live set is
    fixed once a run has linked its mentions; a merge changes roots, which no index holds."""
    cache = book.__dict__.setdefault("_indexes", {})
    key = (name, len(book.mentioned), len(book.ents))
    if key not in cache:
        cache[key] = build()
    return cache[key]


def _string_index(book: Book):
    by_gram: Dict[str, List[str]] = defaultdict(list)
    by_sq: Dict[str, List[str]] = defaultdict(list)
    for e in _live(book):
        by_sq[e.sq].append(e.id)
        for g in N.grams(e.sq):
            by_gram[g].append(e.id)
    return by_gram, by_sq


def pool_strings(pool: Pool, book: Book, seeds: Iterable[str]) -> None:
    """Squashed equality, word containment (4+ letters), trigram Jaccard >= 0.5: blocked on shared grams."""
    by_gram, by_sq = _index(book, "strings", lambda: _string_index(book))
    for sid in seeds:
        e = book.ents.get(sid)
        if e is None or not e.sq:
            continue
        for o in by_sq.get(e.sq, ()):
            pool.add(e.id, o, "str", "squash")
        cands: Counter = Counter()
        for g in N.grams(e.sq):
            if len(by_gram[g]) < GRAM_CAP:
                cands.update(by_gram[g])
        for oid, _ in cands.most_common(GRAM_TOP):
            if oid == e.id:
                continue
            o = book.ents[oid]
            a, b = e.sq, o.sq
            if a == b or (min(len(a), len(b)) >= 4 and N.word_contains(e.key, o.key)) or N.jaccard(a, b) >= JAC_BAR:
                pool.add(e.id, oid, "str")


def pool_family(pool: Pool, book: Book, seeds: Iterable[str]) -> None:
    """The same family key, another surface form."""
    def build():
        by_fam: Dict[str, List[str]] = defaultdict(list)
        for e in _live(book):
            for f in {e.hk[0], e.pk[0]} - {None}:
                by_fam[f].append(e.id)
        return by_fam
    by_fam = _index(book, "family", build)
    for sid in seeds:
        e = book.ents.get(sid)
        if e is None:
            continue
        for f in {e.hk[0], e.pk[0]} - {None}:
            for o in by_fam.get(f, ()):
                pool.add(sid, o, "family")


def pool_makers(pool: Pool, book: Book, seeds: Iterable[str]) -> None:
    """The maker-prefix forms ("Zeta Z200" / "Z200")."""
    def build():
        by_sq: Dict[str, List[str]] = defaultdict(list)
        prefixed: Dict[str, List[str]] = defaultdict(list)
        for e in _live(book):
            by_sq[e.sq].append(e.id)
            mk = N.key(e.maker or "")
            if mk and e.key.startswith(mk + " "):
                prefixed[N.squash(e.key[len(mk) + 1:])].append(e.id)
        return by_sq, prefixed
    by_sq, prefixed = _index(book, "makers", build)
    for sid in seeds:
        e = book.ents.get(sid)
        if e is None:
            continue
        mk = N.key(e.maker or "")
        if mk and e.key.startswith(mk + " "):
            for o in by_sq.get(N.squash(e.key[len(mk) + 1:]), ()):
                pool.add(sid, o, "maker")
        for o in prefixed.get(e.sq, ()):
            pool.add(sid, o, "maker")


def handles(cur: Any, guide: str) -> Dict[str, Dict[str, bool]]:
    """{entity: {squashed handle form: drops a word}} from the handles its mentions were written as."""
    cur.execute("""SELECT DISTINCT entity_id::text, span FROM mx_mentions
                    WHERE guide = %s AND entity_id IS NOT NULL AND (span LIKE '@%%' OR span LIKE '%%\\_%%')""", (guide,))
    out: Dict[str, Dict[str, bool]] = defaultdict(dict)
    for eid, span in cur.fetchall():
        if N.is_handle(span):
            for f, extra in N.handle_forms(span).items():
                out[eid][f] = out[eid].get(f, True) and extra
    return out


def pool_handles(pool: Pool, book: Book, hf: Dict[str, Dict[str, bool]], seeds: Set[str]) -> Dict[Tuple[str, str], bool]:
    """Handle pairs: {pair: the handle form drops a word (an org's "acmeai" for "acme")}."""
    by_sq: Dict[str, List[str]] = defaultdict(list)
    for e in _live(book):
        by_sq[e.sq].append(e.id)
    out: Dict[Tuple[str, str], bool] = {}
    for eid, forms in hf.items():
        for f, extra in forms.items():
            for o in by_sq.get(f, ()):
                if o == eid or not ({eid, o} & seeds):
                    continue
                p = pair(eid, o)
                out[p] = out.get(p, True) and extra
                pool.add(eid, o, "handle")
    return out


def anchors(cur: Any, book: Book, guide: str) -> Dict[str, Set[str]]:
    """{entity: repository / model addresses} its subject posts link, when the address names it."""
    cur.execute("""SELECT DISTINCT m.entity_id::text, l.target_url FROM mx_mentions m
                     JOIN post_links l ON l.post_id = m.post_id
                    WHERE m.guide = %s AND m.role = 'subject' AND m.entity_id IS NOT NULL
                      AND (l.target_url ILIKE '%%github.com/%%' OR l.target_url ILIKE '%%huggingface.co/%%')""", (guide,))
    out: Dict[str, Set[str]] = defaultdict(set)
    for eid, url in cur.fetchall():
        e = book.ents.get(eid)
        mm = ANCHOR_RE.search(url or "")
        if e is None or not mm:
            continue
        # the address names it: the repository's name is its name (a build tag after it dropped: "-GGUF"). Not a name
        # inside a longer one: the lab's containment test merged a maker's product into a repository of its tool.
        words = N.tokens(mm.group(3).replace(".", " "))
        while len(words) > 1 and N.BUILD.match(words[-1]):
            words = words[:-1]
        repo = N.squash(" ".join(words))
        if e.sq and len(repo) >= 4 and (e.sq == repo or e.sq == N.squash(mm.group(3).casefold())):
            out[eid].add(f"{mm.group(1).lower()}/{mm.group(2).lower()}/{mm.group(3).lower()}")
    return out


def pool_anchors(pool: Pool, an: Dict[str, Set[str]], seeds: Set[str]) -> Set[Tuple[str, str]]:
    by: Dict[str, Set[str]] = defaultdict(set)
    for eid, xs in an.items():
        for x in xs:
            by[x].add(eid)
    out = set()
    for ks in by.values():
        for a, b in itertools.combinations(sorted(ks), 2):
            if {a, b} & seeds:
                out.add(pair(a, b))
                pool.add(a, b, "anchor")
    return out


def fold(s: Optional[str]) -> str:
    return re.sub(r"[\W_]+", " ", (s or "").lower().replace("ё", "е")).strip()


def paren_pairs(cur: Any, book: Book, guide: str, post_ids: Sequence[str]) -> Set[Tuple[str, str]]:
    """"X (Y)" written inside one post, X and Y both entities of the post (same type, not a place or person)."""
    if not post_ids:
        return set()
    from insight_core.markx import tasks
    posts = tasks.load_posts(cur, post_ids)
    cur.execute("""SELECT post_id::text, span, type, entity_id::text FROM mx_mentions
                    WHERE guide = %s AND post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""", (guide, list(post_ids)))
    by: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for pid, span, type_, eid in cur.fetchall():
        by[pid].append((fold(span), type_, eid))
    out = set()
    for pid, es in by.items():
        p = posts.get(pid)
        if p is None:
            continue
        text = bracket_fold(p.title + "\n" + p.text)
        for (sa, ta, ea), (sb, tb, eb) in itertools.permutations(es, 2):
            if ea != eb and sa and sb and ta == tb and ta not in ("place", "person") and f"{sa} ({sb})" in text:
                out.add(pair(ea, eb))
    return out


def bracket_fold(s: str) -> str:
    """Text folded as spans are (fold), its round brackets kept: "Acme Box (Kernel)" -> "acme box (kernel)"."""
    s = re.sub(r"[^\w()]+|_", " ", s.lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", s.replace("(", " (").replace(")", ") ")).replace("( ", "(").replace(" )", ")").strip()


def vector_neighbours(cur: Any, book: Book, seeds: Sequence[str], model: str = "bge-m3") -> List[Tuple[str, str, float]]:
    """A name's EMB_TOPK nearest names at cosine >= EMB_BAR (mx_entity_vectors, the embed_name kind)."""
    if not seeds:
        return []
    cur.execute("""SELECT s.entity_id::text, n.entity_id::text, 1 - (n.v <=> s.v)
                     FROM mx_entity_vectors s
                     CROSS JOIN LATERAL (SELECT entity_id, v FROM mx_entity_vectors o
                                          WHERE o.model = s.model AND o.entity_id <> s.entity_id
                                          ORDER BY o.v <=> s.v LIMIT %s) n
                    WHERE s.model = %s AND s.entity_id = ANY(%s::uuid[])""", (EMB_TOPK, model, list(seeds)))
    return [(a, b, float(c)) for a, b, c in cur.fetchall() if c is not None and float(c) >= EMB_BAR]


# ---- the decision per pair --------------------------------------------------------------------------

@dataclass
class Decision:
    pair: Tuple[str, str]
    tier: str                      # auto, queue, apart, ask (waiting for Haiku)
    reason: str                    # the rule, or why it is queued or kept apart
    conf: float = 0.0
    call_id: Optional[str] = None
    judge: Optional[Dict[str, Any]] = None
    rules: Tuple[str, ...] = ()


_STATED: Dict[Tuple[int, str, str], bool] = {}


def stated_maker(cur: Any, bare: Ent, maker: str, guide: str) -> bool:
    """The bare name's maker is written in one of its posts (not only guessed: the maker-prefix rule's condition).
    Remembered for the cursor's transaction (one run)."""
    from insight_core.markx import tasks, validate
    k = (id(cur), bare.id, maker)
    if k not in _STATED:
        if len(_STATED) > 50000:
            _STATED.clear()
        cur.execute("SELECT DISTINCT post_id::text FROM mx_mentions WHERE guide = %s AND entity_id = %s LIMIT 20",
                    (guide, bare.id))
        posts = tasks.load_posts(cur, [r[0] for r in cur.fetchall()])
        _STATED[k] = any(validate.occurs(maker, p.title + "\n" + p.text) for p in posts.values())
    return _STATED[k]


def rules_of(cur: Any, book: Book, p: Pooled, handle_extra: Dict[Tuple[str, str], bool],
             anchored: Set[Tuple[str, str]], parens: Set[Tuple[str, str]], guide: str) -> Tuple[Set[str], Set[str]]:
    """(the automatic rules that fire, the rules that send the pair to the queue)."""
    a, b = book.ents[p.a], book.ents[p.b]
    auto, queue = set(), set()
    if a.sq and a.sq == b.sq:
        auto.add("squash")
    if "squash" not in auto:
        for x, y in ((a, b), (b, a)):
            if maker_prefix(x, y):
                maker = x.maker or y.maker or ""
                (auto if stated_maker(cur, y, maker, guide) else queue).add(
                    "maker_prefix" if stated_maker(cur, y, maker, guide) else "maker_unstated")
                break
    k = (p.a, p.b)
    if k in handle_extra:
        person = "person" in (a.type, b.type)
        (queue if handle_extra[k] and not person else auto).add("handle_extra_word" if handle_extra[k] and not person
                                                                  else "handle")
    if k in anchored:
        auto.add("anchor")
    if k in parens:
        queue.add("paren")
    fr = fields_rule(a, b)
    if fr == "auto":
        auto.add("fields")
    elif fr == "queue":
        queue.add("fields_parser")
    return auto, queue


def decide_pair(book: Book, p: Pooled, auto: Set[str], queue: Set[str], judge: Optional[Dict[str, Any]],
                call_id: Optional[str]) -> Decision:
    """0119 A1's merge rules for one pool pair, before the chain guard. tier 'ask': Haiku hasn't answered yet."""
    a, b = book.ents[p.a], book.ents[p.b]
    k = (p.a, p.b)
    literal = bool({"squash", "maker_prefix"} & auto)
    vc = vconflict(a, b, literal=literal)
    if family_link(a, b) and not auto:
        return Decision(k, "apart", "family")
    if vc == "strong":
        # two stated versions that differ, in Haiku's fields or the parser's: kept apart, never asked (the guard kept
        # 135/135 labelled version pairs apart). A disagreement that changes a merge is the fields rule's queue.
        return Decision(k, "apart", "version" if not strong_only_one(a, b) else "version_one_parse")
    if auto and vc is None and not queue:
        if not types_ok(a.type, b.type):
            return Decision(k, "queue", "type", RULE_CONF, None, judge, tuple(sorted(auto)))
        return Decision(k, "auto", "rule:" + sorted(auto)[0], RULE_CONF, None, judge, tuple(sorted(auto)))
    if judge is None:
        return Decision(k, "ask", "unasked")
    if judge["relation"] != "same":
        return Decision(k, "apart", "judge", judge["confidence"], call_id, judge)
    conf = float(judge["confidence"])
    if queue:
        return Decision(k, "queue", sorted(queue)[0], conf, call_id, judge)
    if vc == "soft" or auto and vc is not None:
        return Decision(k, "queue", "version", conf, call_id, judge)
    if conf < AUTO_CONF:
        return Decision(k, "queue", "below_bar", conf, call_id, judge)
    if not types_ok(a.type, b.type):
        return Decision(k, "queue", "type", conf, call_id, judge)
    return Decision(k, "auto", "haiku", conf, call_id, judge)


def chain_guard(book: Book, decisions: List[Decision]) -> None:
    """No automatic merge joins two clusters that already hold 2 or more names; a cluster holds at most MAX_CLUSTER
    names. The rejected ones go to the queue ('chain'), in order of confidence."""
    members = book.members()
    size = {r: len(ms) for r, ms in members.items()}
    parent: Dict[str, str] = {}

    def f(x: str) -> str:
        x = book.root(x)
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    for d in sorted((d for d in decisions if d.tier == "auto"), key=lambda d: (-d.conf, d.pair)):
        ra, rb = f(d.pair[0]), f(d.pair[1])
        if ra == rb:
            d.tier, d.reason = "same_cluster", d.reason
            continue
        sa, sb = size.get(ra, 1), size.get(rb, 1)
        if (sa >= 2 and sb >= 2) or sa + sb > MAX_CLUSTER:
            d.tier, d.reason = "queue", "chain"
            continue
        parent[rb] = ra
        size[ra] = sa + sb


# ---- the Haiku questions ----------------------------------------------------------------------------

def _ctx(p: Any, span: str, before: int = 140, after: int = 220) -> str:
    from insight_core.markx import tasks
    t = tasks._squash(p.title + "\n" + p.text)
    j = fold(t).find(fold(span)) if span else -1
    # fold() keeps word positions only roughly; find the raw span first, then the folded one
    raw = t.lower().find((span or "").lower()) if span else -1
    j = raw if raw >= 0 else j
    win = t[max(0, j - before): j + after] if j >= 0 else t[:before + after]
    return f'[{p.kind}, {p.iso[:10]}] "{p.title[:110]}" … {win}'


def examples(cur: Any, guide: str, eids: Sequence[str], n: int = 2) -> Dict[str, List[str]]:
    """Up to n example posts of each entity: distinct sources, subjects first, picked by a seed of its key (stable)."""
    from insight_core.markx import tasks
    if not eids:
        return {}
    cur.execute("""SELECT m.entity_id::text, m.post_id::text, m.span, m.role, p.source_id::text FROM mx_mentions m
                     JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = %s AND m.entity_id = ANY(%s::uuid[])""", (guide, list(eids)))
    by: Dict[str, List[Tuple[str, str, str, str]]] = defaultdict(list)
    for eid, pid, span, role, src in cur.fetchall():
        by[eid].append((pid, span or "", role or "", src))
    picks: Dict[str, List[Tuple[str, str]]] = {}
    for eid, ms in by.items():
        ms = sorted(set(ms))
        rnd = random.Random(int(hashlib.md5(eid.encode()).hexdigest(), 16) % 100000)
        rnd.shuffle(ms)
        ms.sort(key=lambda m: m[2] != "subject")
        seen, out = set(), []
        srcs = {m[3] for m in ms}
        for pid, span, role, src in ms:
            if src in seen and len(seen) < len(srcs):
                continue
            seen.add(src)
            out.append((pid, span))
            if len(out) >= n:
                break
        picks[eid] = out
    posts = tasks.load_posts(cur, {pid for xs in picks.values() for pid, _ in xs})
    return {eid: [_ctx(posts[pid], span) for pid, span in xs if pid in posts] for eid, xs in picks.items()}


def spans(cur: Any, guide: str, eids: Sequence[str]) -> Dict[str, List[str]]:
    cur.execute("""SELECT entity_id::text, span, count(*) FROM mx_mentions WHERE guide = %s AND entity_id = ANY(%s::uuid[])
                    GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2""", (guide, list(eids)))
    out: Dict[str, List[str]] = defaultdict(list)
    for eid, span, _ in cur.fetchall():
        out[eid].append(span)
    return out


def counts_of(cur: Any, guide: str, eids: Sequence[str]) -> Dict[str, int]:
    cur.execute("SELECT entity_id::text, count(DISTINCT post_id) FROM mx_mentions WHERE guide = %s AND entity_id = ANY(%s::uuid[]) "
                "GROUP BY 1", (guide, list(eids)))
    return dict(cur.fetchall())


def show(e: Ent, written: Sequence[str], n_posts: int, ex: Sequence[str]) -> str:
    fields = {f: e.haiku.get(f) for f in N.FIELDS}
    head = (f'name "{e.name}" (written: {", ".join(repr(s) for s in written[:3])}) | type {e.type} | maker {e.maker} | '
            f"version fields {fields} | {n_posts} posts")
    return head + "\n" + "\n".join(f"  example: {x}" for x in ex)


def alias_input(a: str, b: str) -> str:
    return f"A: {a}\nB: {b}"


def odd(ms: Sequence[Tuple[str, Optional[str], Optional[str]]]) -> bool:
    """A key whose mentions (one per post) differ in type or in a stated maker."""
    return len({t for _, t, _ in ms}) > 1 or len({m for _, _, m in ms if m}) > 1


def collide_sample(eid: str, ms: Sequence[Tuple[str, str, Optional[str], Optional[str]]]) -> List[Tuple]:
    """Up to COLLIDE_MENTIONS mentions from distinct posts: one per (type, maker) first, then the rest (the lab's
    sample, seeded by the entity)."""
    rnd = random.Random(int(hashlib.md5(eid.encode()).hexdigest(), 16) % 100000)
    ms = sorted(ms)
    rnd.shuffle(ms)
    pick, seen = [], set()
    for m in ms:
        g = (m[2], m[3])
        if g not in seen:
            seen.add(g)
            pick.append(m)
    for m in ms:
        if len(pick) >= COLLIDE_MENTIONS:
            break
        if m not in pick:
            pick.append(m)
    pick = pick[:COLLIDE_MENTIONS]
    rnd.shuffle(pick)
    return pick


def collide_input(e: Ent, n_posts: int, pick: Sequence[Tuple], posts: Dict[str, Any]) -> str:
    lines = [f'NAME "{e.name}" ({n_posts} posts; {len(pick)} mentions shown)']
    for n, (pid, span, type_, maker) in enumerate(pick, 1):
        p = posts.get(pid)
        lines.append(f'{n}. written "{span}" | type {type_} | maker guess {maker or "none"}\n   '
                     + (_ctx(p, span, 170, 250) if p else ""))
    return "\n".join(lines)


def pairrel(o: Dict[str, Any], n: int) -> Dict[Tuple[int, int], str]:
    """{(i, j): same|part|different|unclear} for mentions 1..n (the lab's pairrel): senses joined through `related`
    links are 'part'; senses with no path between them are different things sharing a name."""
    where = {}
    for si, s in enumerate(o.get("senses") or [], 1):
        for x in s.get("m") or []:
            where[int(x)] = si
    par: Dict[int, int] = {}

    def f(x: int) -> int:
        while par.get(x, x) != x:
            x = par[x]
        return x
    for r in o.get("related") or []:
        try:
            a, b = f(int(r[0])), f(int(r[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if a != b:
            par[a] = b
    out = {}
    for i, j in itertools.combinations(range(1, n + 1), 2):
        if i not in where or j not in where:
            out[(i, j)] = "unclear"
        elif where[i] == where[j]:
            out[(i, j)] = "same"
        else:
            out[(i, j)] = "part" if f(where[i]) == f(where[j]) else "different"
    return out


def vote(rels: Sequence[str]) -> str:
    """Majority over the runs for one mention pair; no majority: 'same' (no split)."""
    top, n = Counter(rels).most_common(1)[0]
    return top if n * 2 > len(rels) else "same"


def split_of(answers: Sequence[Dict[str, Any]], n: int) -> Optional[Dict[str, Any]]:
    """The split two of the runs make (a mention pair most runs call different), or None. The proposal: the senses of
    the first run that splits, with the pairs the majority calls different."""
    rels = [pairrel(a, n) for a in answers]
    maj = {p: vote([r[p] for r in rels]) for p in rels[0]} if rels else {}
    apart = sorted(p for p, v in maj.items() if v == "different")
    if not apart:
        return None
    first = next(a for a, r in zip(answers, rels) if any(r[p] == "different" for p in apart))
    return {"senses": first.get("senses"), "related": first.get("related") or [], "unclear": first.get("unclear") or [],
            "apart": [list(p) for p in apart], "runs": len(answers),
            "split_runs": sum(1 for r in rels if any(v == "different" for v in r.values()))}


# ---- the stage ---------------------------------------------------------------------------------------

def _savepoint(cur: Any, sql: str, params: Sequence[Any]) -> Optional[Any]:
    """One write another transaction may race (the API's answers): skipped when it does."""
    try:
        with cur.connection.transaction():
            cur.execute(sql, params)
            return cur.fetchone() if cur.description else True
    except (psycopg_errors.SerializationFailure, psycopg_errors.UniqueViolation):
        return None


def queue_item(cur: Any, *, kind: str, a: str, b: Optional[str], proposal: str, reason: str, conf: Optional[float],
               evidence: Dict[str, Any], call_id: Optional[str], run_id: Any) -> bool:
    """An open review item, unless the pair has one open or answered (an answer is never asked again)."""
    cur.execute("""SELECT 1 FROM mx_entity_queue WHERE kind = %s AND a = %s AND COALESCE(b, a) = COALESCE(%s::uuid, %s::uuid)
                    AND (answer IS NOT NULL OR closed_at IS NULL) LIMIT 1""", (kind, a, b, a))
    if cur.fetchone():
        return False
    got = _savepoint(cur, """INSERT INTO mx_entity_queue (kind, a, b, proposal, reason, confidence, evidence, call_id, run_id)
                             VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING id""",
                     (kind, a, b, proposal, reason, conf, json.dumps(evidence, default=str), call_id, run_id))
    return got is not None


def merge(cur: Any, book: Book, a: str, b: str, *, by: str, automatic: bool, call_id: Any = None, queue_id: Any = None,
          run_id: Any = None, evidence: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """One merge: the smaller cluster's root redirects into the larger's (more names, then older). The redirect's id."""
    ra, rb = book.root(a), book.root(b)
    if ra == rb:
        return None
    members = book.members()
    def weight(r: str):
        e = book.ents[r]
        return (len(members.get(r, ())), -(e.first_seen.timestamp() if e.first_seen else 0), r)
    to, frm = (ra, rb) if weight(ra) >= weight(rb) else (rb, ra)
    got = _savepoint(cur, """INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic, call_id, queue_id, run_id, evidence)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id::text""",
                     (frm, to, by, automatic, call_id, queue_id, run_id, json.dumps(evidence or {}, default=str)))
    if got is None:
        return None
    book.redirect[frm] = (to, automatic)
    return got[0]


@dataclass
class Asked:
    alias: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)   # pair -> (task id, status)
    collide: Dict[str, Tuple[str, str, str]] = field(default_factory=dict)         # entity -> (task id, status, input)


def asked(cur: Any) -> Asked:
    out = Asked()
    cur.execute("SELECT id::text, a::text, b::text, status, input FROM mx_tasks WHERE kind IN ('alias', 'collide') ORDER BY created_at")
    for tid, a, b, status, text in cur.fetchall():
        if b is not None:
            out.alias[pair(a, b)] = (tid, status)
        elif a is not None:
            out.collide[a] = (tid, status, text)
    return out


def valid_answers(cur: Any, task_ids: Sequence[str]) -> Dict[str, List[Tuple[str, Dict[str, Any]]]]:
    if not task_ids:
        return {}
    cur.execute("""SELECT task_id::text, id::text, answer FROM mx_calls WHERE valid AND task_id = ANY(%s::uuid[])
                    ORDER BY created_at, ctid""", (list(task_ids),))
    out: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    for tid, cid, ans in cur.fetchall():
        out[tid].append((cid, ans or {}))
    return out


def stage(cur: Any, *, ask: Any, now: datetime, run_id: Any, full: bool, since: Optional[datetime] = None,
          link_limit: int = LINK_LIMIT, embedded_since: Optional[datetime] = None, after: Optional[str] = None,
          deadline: Optional[float] = None, chunk: int = SEED_CHUNK) -> Dict[str, Any]:
    """The decision run's entities stage. `full`: the nightly pass (every mention relinked and checked, every entity
    pooled); else the mentions not linked yet and the pairs whose answers came since `since`. Returns its counts;
    `days` the days whose mentions it linked (the surges recount them).

    0128: the full pass pools and decides its entities in chunks of `chunk` seeds, in id order. Past `deadline` (a
    time.monotonic() value: the stage's own budget) it stops after a chunk; `full` in the counts says where
    ({done, after: the last seed decided, chunks, of}) and the next run resumes it with `after`: it links only the
    mentions not linked yet (as an incremental pass does), adds the run's new entities and answered pairs to its
    first chunk, then goes on from `after`. Collisions run with the last chunk. Without a deadline nothing stops."""
    from insight_core.markx import schemas
    import time as _time
    t0 = _time.monotonic()
    guide = schemas.KINDS["entities"].guide
    _STATED.clear()
    book = load_book(cur)
    w = Writer(cur, book, run_id)
    resume = full and after is not None
    out: Dict[str, Any] = {"kind": "full" if full else "incremental"}
    if hasattr(ask, "caps"):   # identity's questions are cheap and each waits otherwise for the nightly pass
        ask.caps.setdefault("alias", ALIAS_CAP)
        ask.caps.setdefault("collide", COLLIDE_CAP)
    ms = _mentions(cur, guide, unlinked=not full or resume, limit=None if full and not resume else link_limit)
    if (not full or resume) and book.pins:   # the owner's splits since: the pinned mentions the run hasn't moved yet
        cur.execute("""SELECT m.post_id::text, m.n FROM mx_mentions m JOIN mx_entity_pins p ON p.post_id = m.post_id
                         AND p.guide = m.guide AND p.n = m.n AND p.undone_at IS NULL
                        WHERE m.guide = %s AND m.entity_id IS DISTINCT FROM p.entity_id""", (guide,))
        moved = {(p, n) for p, n in cur.fetchall()}
        if moved:
            have = {(m.post_id, m.n) for m in ms}
            ms += [m for m in _mentions(cur, guide, unlinked=False) if (m.post_id, m.n) in moved - have]
    before = {(m.post_id, m.n): m.entity_id for m in ms}
    out["link"] = link(cur, book, w, ms)
    book.mentioned |= {m.entity_id for m in ms if m.entity_id}
    if full and not resume:
        moved = sum(1 for m in ms if before.get((m.post_id, m.n)) and before[(m.post_id, m.n)] != m.entity_id)
        out["check"] = {"same": moved == 0, "relinked": moved}
    touched_days = {m.at.astimezone(timezone.utc).date() for m in ms
                    if m.at and before.get((m.post_id, m.n)) != m.entity_id}
    # the pool's seeds: the entities made or newly linked (every entity on a full pass), vectors that came
    new: Set[str] = set(w.made) | {m.entity_id for m in ms if m.entity_id}
    if full:
        rest = sorted(e for e in book.ents if after is None or e > after)
        chunks = [rest[k:k + chunk] for k in range(0, len(rest), max(1, chunk))] or [[]]
        if resume:
            chunks[0] = sorted(set(chunks[0]) | (new - set(rest)))
    else:
        chunks = [sorted(new)]
    if full and not resume:
        cur.execute("SELECT entity_id::text FROM mx_entity_vectors")
    else:   # the names whose vector came since the last run (and, resuming, every vector of the seeds to come)
        cur.execute("""SELECT t.a::text FROM mx_tasks t WHERE t.kind = 'embed_name' AND t.status = 'answered'
                          AND t.answered_at >= %s""", (embedded_since or since or now,))
    vec_seeds = {r[0] for r in cur.fetchall()} & set(book.ents)
    if resume:
        cur.execute("SELECT entity_id::text FROM mx_entity_vectors WHERE entity_id::text > %s", (after,))
        vec_seeds |= {r[0] for r in cur.fetchall()} & set(book.ents)
    hf = handles(cur, guide)
    an = anchors(cur, book, guide)
    # the pairs whose Haiku answer came since the last run are decided again (with the first chunk)
    got = asked(cur)
    answered_pairs: Set[Tuple[str, str]] = set()
    if since is not None and (not full or resume):
        cur.execute("""SELECT DISTINCT t.a::text, t.b::text FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                        WHERE t.kind = 'alias' AND c.created_at >= %s""", (since,))
        answered_pairs = {pair(a, b) for a, b in cur.fetchall()}
    if full:
        cur.execute("SELECT DISTINCT post_id::text FROM mx_mentions WHERE guide = %s AND entity_id IS NOT NULL", (guide,))
    else:   # the posts linked now, and those naming both ends of an answered pair
        cur.execute("""SELECT post_id::text FROM mx_mentions WHERE guide = %s AND post_id = ANY(%s::uuid[])
                       UNION SELECT a.post_id::text FROM mx_mentions a JOIN mx_mentions b ON b.post_id = a.post_id
                              AND b.guide = a.guide
                        WHERE a.guide = %s AND (a.entity_id, b.entity_id) IN (SELECT x, y FROM unnest(%s::uuid[], %s::uuid[]) u(x, y))""",
                    (guide, sorted({m.post_id for m in ms if m.entity_id}), guide,
                     [p_[0] for p_ in answered_pairs], [p_[1] for p_ in answered_pairs]))
    parens = paren_pairs(cur, book, guide, [r[0] for r in cur.fetchall()])
    by: Counter = Counter()
    tiers: Counter = Counter()
    asks_by: Counter = Counter()
    reasons: Counter = Counter()
    decided: Set[Tuple[str, str]] = set()
    pooled: Set[Tuple[str, str]] = set()
    added = merged = queued = n_pairs = 0
    done_chunks, last = 0, after
    for k, seeds_list in enumerate(chunks):
        seeds = set(seeds_list)
        pool = Pool(book)
        pool_strings(pool, book, seeds)
        pool_family(pool, book, seeds)
        pool_makers(pool, book, seeds)
        hextra = pool_handles(pool, book, hf, seeds)
        anchored = pool_anchors(pool, an, seeds)
        for a, b, c in vector_neighbours(cur, book, sorted(vec_seeds & seeds)):
            pool.add(a, b, "emb")
        if k == 0:
            for a, b in sorted(answered_pairs):
                pool.add(a, b, "answered")
            if answered_pairs:   # the rules' facts hold for every pair decided, not only the seeds'
                ends = {x for p_ in answered_pairs for x in p_}
                hextra.update(pool_handles(Pool(book), book, hf, ends))
                anchored |= pool_anchors(Pool(book), an, ends)
        for a, b in parens:
            if {a, b} & seeds:
                pool.add(a, b, "paren")
        for key_, p in pool.pairs.items():
            if key_ not in pooled:
                by.update(p.why)
        pooled |= set(pool.pairs)
        pairs = [p for p in sorted(pool.pairs.values(), key=lambda p: (p.a, p.b)) if (p.a, p.b) not in decided]
        pairs = pairs[:max(0, PAIR_LIMIT - n_pairs)]
        n_pairs += len(pairs)
        decided |= {(p.a, p.b) for p in pairs}
        answers = valid_answers(cur, [got.alias[(p.a, p.b)][0] for p in pairs if (p.a, p.b) in got.alias])
        decisions: List[Decision] = []
        for p in pairs:
            if (p.a, p.b) in book.never or book.ents[p.a].status == "not_entity" or book.ents[p.b].status == "not_entity":
                continue
            if book.root(p.a) == book.root(p.b):
                continue
            auto, queue = rules_of(cur, book, p, hextra, anchored, parens, guide)
            judge = call = None
            task = got.alias.get((p.a, p.b))
            if task and answers.get(task[0]):
                call, judge = answers[task[0]][0]
            decisions.append(decide_pair(book, p, auto, queue, judge, call))
        chain_guard(book, decisions)
        tiers.update(d.tier for d in decisions)
        asks_by.update(w_ for d in decisions if d.tier == "ask" for w_ in pool.pairs[d.pair].why)
        reasons.update(f"{d.tier}:{d.reason}" for d in decisions)
        # Haiku's questions for the pairs no rule decides
        need = [d for d in decisions if d.tier == "ask" and d.pair not in got.alias]
        if need:
            ids = sorted({x for d in need for x in d.pair})
            ex, written, nposts = examples(cur, guide, ids), spans(cur, guide, ids), counts_of(cur, guide, ids)
            for d in need:
                a, b = (book.ents[x] for x in d.pair)
                text = alias_input(show(a, written.get(a.id, [a.name]), nposts.get(a.id, 0), ex.get(a.id, [])),
                                   show(b, written.get(b.id, [b.name]), nposts.get(b.id, 0), ex.get(b.id, [])))
                if ask.added["alias"] >= ALIAS_CAP:
                    ask.waiting["alias"] += 1
                    continue
                ask.answer("alias", text, a=d.pair[0], b=d.pair[1])
                added += 1
        for d in decisions:
            if d.tier == "auto":
                if merge(cur, book, d.pair[0], d.pair[1], by=d.reason, automatic=True, call_id=d.call_id, run_id=run_id,
                         evidence={"rules": list(d.rules), "confidence": d.conf, "judge": d.judge}):
                    merged += 1
            elif d.tier == "queue":
                ev = {"rules": list(d.rules), "judge": d.judge}
                if queue_item(cur, kind="alias", a=d.pair[0], b=d.pair[1], proposal="same", reason=d.reason, conf=d.conf,
                              evidence=ev, call_id=d.call_id, run_id=run_id):
                    queued += 1
        done_chunks = k + 1
        if full and rest:
            tail = [s for s in seeds_list if s in set(rest)]
            last = max(tail) if tail else last
        if deadline is not None and k + 1 < len(chunks) and _time.monotonic() > deadline:
            break
    out["pool"] = {"pairs": len(pooled), "by": dict(by)}
    out["decisions"] = dict(tiers)
    out["asks_by"] = dict(asks_by)
    out["reasons"] = dict(reasons)
    out["alias_asked"] = added
    out["merged"], out["queued"] = merged, queued
    done = done_chunks == len(chunks)
    if full:
        out["full"] = {"done": done, "after": None if done else last, "chunks": done_chunks, "of": len(chunks),
                       "resumed": resume}
    collide_seeds: Optional[Set[str]] = None
    if not (full and done):
        collide_seeds = {m.entity_id for m in ms if m.entity_id}
        if since is not None:   # the keys whose collision answers came since the last run
            cur.execute("""SELECT DISTINCT t.a::text FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                            WHERE t.kind = 'collide' AND c.created_at >= %s""", (since,))
            collide_seeds |= {r[0] for r in cur.fetchall()}
    out["collide"] = collisions(cur, book, ask=ask, guide=guide, run_id=run_id, got=got, seeds=collide_seeds)
    out["entities_made"] = len(w.made)
    out["seconds"] = round(_time.monotonic() - t0, 3)
    out["days"] = sorted(d.isoformat() for d in touched_days)
    return out


def collisions(cur: Any, book: Book, *, ask: Any, guide: str, run_id: Any, got: Asked,
               seeds: Optional[Set[str]]) -> Dict[str, int]:
    """The collision judge: keys (entities) whose mentions differ in type or stated maker, asked COLLIDE_RUNS times;
    a split two runs make goes to the queue. `seeds` None: every entity."""
    from insight_core.markx import tasks
    cur.execute(f"""SELECT entity_id::text, post_id::text, span, type, maker FROM mx_mentions
                     WHERE guide = %s AND entity_id IS NOT NULL
                     {"AND entity_id = ANY(%s::uuid[])" if seeds is not None else ""}
                     ORDER BY entity_id, post_id, n""", (guide, sorted(seeds)) if seeds is not None else (guide,))
    by: Dict[str, Dict[str, Tuple]] = defaultdict(dict)
    for eid, pid, span, type_, maker in cur.fetchall():
        by[eid].setdefault(pid, (pid, span or "", type_, maker))
    out: Counter = Counter({k: 0 for k in ("odd", "asked", "asked_again", "waiting", "one_thing", "queued")})
    want = {eid: list(ms.values()) for eid, ms in by.items()
            if len(ms) >= 2 and odd([(p, t, mk) for p, _, t, mk in ms.values()])
            and book.ents.get(eid) and book.ents[eid].status != "not_entity"}
    out["odd"] = len(want)
    answers = valid_answers(cur, [got.collide[e][0] for e in want if e in got.collide])
    new = []
    for eid, ms in sorted(want.items()):
        task = got.collide.get(eid)
        if task is None:
            new.append((eid, ms))
            continue
        tid, status, text = task
        calls = answers.get(tid) or []
        if status != "answered" or not calls:
            out["waiting"] += 1
            continue
        from insight_core.markx import validate
        n = validate.collide_mentions(text)
        # the third run is asked only when the first two disagree on a pair: two that agree are the majority already
        settled = len(calls) == COLLIDE_RUNS - 1 and pairrel(calls[0][1], n) == pairrel(calls[1][1], n)
        if len(calls) < COLLIDE_RUNS and not settled:
            if status == "answered" and _savepoint(cur, "UPDATE mx_tasks SET status = 'open', lease_until = NULL, "
                                                        "leased_by = NULL WHERE id = %s AND status = 'answered'", (tid,)):
                out["asked_again"] += 1
            continue
        prop = split_of([a for _, a in calls[:COLLIDE_RUNS]], n)
        if prop is None:
            out["one_thing"] += 1
            continue
        prop["mentions"] = _sample_rows(text)
        found = match_pick(cur, guide, eid, text)
        for row in prop["mentions"]:
            row["posts"] = [list(x) for x in found.get(row["n"], [])]
        if queue_item(cur, kind="collision", a=eid, b=None, proposal="split", reason="collision",
                      conf=None, evidence=prop, call_id=calls[0][0], run_id=run_id):
            out["queued"] += 1
    if new:
        new = new[:max(0, COLLIDE_CAP - ask.added["collide"])]
        picks = {eid: collide_sample(eid, ms) for eid, ms in new}
        posts = tasks.load_posts(cur, {m[0] for pick in picks.values() for m in pick})
        nposts = counts_of(cur, guide, list(picks))
        for eid, pick in picks.items():
            ask.answer("collide", collide_input(book.ents[eid], nposts.get(eid, len(pick)), pick, posts), a=eid)
            out["asked"] += 1
    return dict(out)


def match_pick(cur: Any, guide: str, eid: str, text: str) -> Dict[int, List[Tuple[str, int]]]:
    """A collision question's numbered mentions found again among the entity's mentions: {number: [(post, n)]} (the
    input names no ids; each line's span, type, maker and its post's title and date say which post it is)."""
    from insight_core.markx import tasks
    cur.execute("SELECT post_id::text, n, span, type, maker FROM mx_mentions WHERE guide = %s AND entity_id = %s",
                (guide, eid))
    rows = cur.fetchall()
    posts = tasks.load_posts(cur, {r[0] for r in rows})
    blocks = re.split(r"\n(?=\d+\. written )", text)
    out: Dict[int, List[Tuple[str, int]]] = {}
    for block in blocks[1:]:
        m = re.match(r'(\d+)\. written "(.*)" \| type (\S+) \| maker guess (.*)\n\s+\[[^\]]*, (\d{4}-\d\d-\d\d)\] "(.*?)" …',
                     block)
        if not m:
            continue
        num, span, type_, maker, day, title = m.groups()
        maker = None if maker == "none" else maker
        hits = [(pid, n) for pid, n, s, t, mk in rows
                if (s or "") == span and str(t) == type_ and (mk or None) == maker and pid in posts
                and posts[pid].iso[:10] == day and posts[pid].title[:110] == title]
        if hits:
            out[int(num)] = hits
    return out


_SAMPLE_LINE = re.compile(r'^(\d+)\. written "(.*)" \| type (\S+) \| maker guess (.*)$', re.M)


def _sample_rows(text: str) -> List[Dict[str, Any]]:
    return [{"n": int(n), "span": span, "type": t, "maker": None if mk == "none" else mk}
            for n, span, t, mk in _SAMPLE_LINE.findall(text)]
