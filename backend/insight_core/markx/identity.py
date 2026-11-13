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
     0130 A1-A3: which band and guard is automatic is config (entity_bands.json, the measured table, `bands`). The
     version guard is narrowed (`soft_reason`): a one-sided field is held only when the family has several of it;
     an edition year on one side, or a field the family has one of, goes to the second opinion. The second opinion
     (`alias2`: alias-v1 asked again with two other example posts per name) is asked for every held-back `same`
     whose reasons the config allows; two `same` at >= 0.85 merge ('second', a redirect like any other, undoable)
     and close the pair's open queue item; a disagreement stays queued, marked (`evidence.disagree`).
     Every merge is a redirect (by its rule, Haiku or the owner) and can be undone (`undo`). A pair the owner
     answered, or a merge the owner undid, is never merged again by a rule or Haiku.
  4. **Collisions:** a key whose mentions differ in type or (stated) maker gets the collision judge (`collide`),
     asked COLLIDE_RUNS times; a split two of the runs make is queued as a proposal, never applied.

The owner's answers (`answer`, the API's, in the request's own transaction: mx_entity* and mx_labels only) apply at
once for the pages, which read through redirects and pins; the next run's snapshot sees them.

0164 (entity identity fixes; the repairs of data already made are markx/entity_repair.py's, run first in the stage):
  - the type guard reads clusters too (`org_family`): a cluster holding a product family (Book.sides) and one holding
    an org or person are never merged automatically, whatever the two names' own types (a family's name typed an
    org by Haiku, "Zentra Vela", was the way in); such a merge is queued ('type', reasons org_family);
  - a version's family is never an org (`family_under`): when its family key aliases an org-like cluster ("Zentra 5"
    by Zentra), its family is a `family` entity of that name under the org;
  - two versions of one family cluster stating the same version, variant, size and build merge by the rule
    `family_version` (the families "Vela" and "Zentra Vela" once one: "Vela 5" = "Zentra Vela 5");
  - the name and type a cluster is shown under are its root's shown_name / shown_type (Book.label, shown_type),
    chosen by evidence; `name` and `type` stay what it was made as and decide identity.
  - a product account is not an org (`Book.product_of`): a name typed an org that is its family's maker (or a name of
    the maker's cluster) in front of a known family ("Zentra Vela", the account of the family Vela by Zentra) is made
    with the family's type and merged into the family (rule `product_account`), never the org; Book.sides counts it on
    the family side wherever it is, so the org-family guard and the repair keep it out of the maker's cluster.
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
from functools import cached_property
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import errors as psycopg_errors

from insight_core.markx import names as N

log = logging.getLogger(__name__)

LINK_LIMIT = 6000           # mentions linked a run (the rest wait: the 120 s run limit)
PAIR_LIMIT = 200000         # pool pairs decided a run (a safety cap: the 120-day full pass pools about 29,000)
SEED_CHUNK = 1000           # 0128: the full pass's entities pooled and decided at once (its budget is checked between)
MENTION_CHUNK = 500         # v10.13.9: the mentions an incremental pass links, pools and decides at once (likewise)
RELINK_PAGE = 2000          # v10.13.9: the posts whose mentions the full pass relinks at once (likewise)
EMB_BAR, EMB_TOPK = 0.80, 10
JAC_BAR = 0.50
GRAM_CAP, GRAM_TOP = 400, 60
AUTO_CONF = 0.9             # Haiku `same` at or above: automatic; 0130: the bands in entity_bands.json decide (this is their first row)
RULE_CONF = 0.97            # a rule's merge, for the chain guard's order
MAX_CLUSTER = 6
ALIAS_CAP, COLLIDE_CAP = 10000, 1000   # new questions a run adds of each (a pair over it waits for the nightly pass)
COLLIDE_RUNS = 3
COLLIDE_MENTIONS = 8
QUEUE_ONLY = {"paren", "handle_extra_word", "maker_unstated", "fields_parser"}
TYPES_VERSIONED = {"model", "product", "software", "project", "dataset"}
ANCHOR_RE = re.compile(r"(github\.com|huggingface\.co)/([\w.-]+)/([\w.-]+)", re.I)
ANSWERS = ("same", "other_version", "different", "not_entity")
ALIAS2_CAP = 2000           # 0130 A2: second-opinion questions a run adds


# ---- 0130 A1-A2: the bands, as config (markx/entity_bands.json), measured on labels ----------------------------

BANDS_FILE = Path(__file__).with_name("entity_bands.json")
_BANDS: Dict[str, Any] = {}
# The reasons a Haiku `same` is held back (decide_pair, the first is the one the queue shows): the rules that only
# queue (paren, handle_extra_word, maker_unstated, fields_parser), the version guard (version: held, the family has
# several; version_year: an edition year on one side; version_one_side: a field the family has one of), below_bar
# (the first opinion's bands), type.


def bands() -> Dict[str, Any]:
    """The measured table (entity_bands.json): which band and guard is automatic, by one opinion or two."""
    if not _BANDS:
        _BANDS.update(json.loads(BANDS_FILE.read_text(encoding="utf-8")))
    return _BANDS


def band_of(conf: Optional[float]) -> Optional[str]:
    """The band a confidence falls in: the first of the config's `bands` ([name, lower bound], highest first)."""
    if conf is None:
        return None
    for name, low in bands()["bands"]:
        if float(conf) >= low:
            return name
    return None


def _row(opinion: str, guard: str, band: Optional[str]) -> Optional[Dict[str, Any]]:
    for r in bands()["rows"]:
        if r["opinion"] == opinion and r["guard"] == guard and r["band"] in (band, "any"):
            return r
    return None


def first_auto(conf: float) -> bool:
    """One Haiku `same` with nothing held back: automatic in the bands the config marks (>= 0.9: 86/87)."""
    r = _row("first", "none", band_of(conf))
    return bool(r and r.get("auto"))


def second_asked(reasons: Iterable[str], conf: float) -> bool:
    """A held-back `same` is asked again (alias2) when every reason it is held for has a second-opinion row that is
    on, and the first answer is at least the second opinion's bar."""
    rs = set(reasons)
    so = bands()["second"]
    if not rs or not so.get("on") or conf < so["min_conf"]:
        return False
    return all((_row("second", r, "any") or {}).get("auto") for r in rs)


def second_agrees(second: Optional[Dict[str, Any]]) -> bool:
    return bool(second) and second.get("relation") == "same" and \
        float(second.get("confidence") or 0) >= bands()["second"]["min_conf"]


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
    shown_name: Optional[str] = None     # 0164: the name and type it is shown under (a root's, chosen by evidence;
    shown_type: Optional[str] = None     # entity_repair.shown); None: `name` / `type`. Never decide identity.

    # v10.13.9: worked out once an entity (its name, type, maker and fields never change once made); a pair's rules
    # read them many times (the decisions spent most of their time parsing the same names again)
    @cached_property
    def hk(self) -> Tuple:
        return N.fields_key(self.haiku, self.maker)

    @cached_property
    def pk(self) -> Tuple:
        return N.fields_key(N.parse(self.name, self.type, self.maker), self.maker)

    @cached_property
    def sq(self) -> str:
        return N.squash(self.key)

    @cached_property
    def grams(self) -> Set[str]:
        return N.grams(self.sq)


class Redirects(dict):
    """from -> (to, automatic), counting its changes (0164: the clusters read through it are kept until it changes)."""
    rev = 0

    def __setitem__(self, k: Any, v: Any) -> None:
        self.rev += 1
        super().__setitem__(k, v)

    def __delitem__(self, k: Any) -> None:
        self.rev += 1
        super().__delitem__(k)

    def pop(self, *a: Any) -> Any:
        self.rev += 1
        return super().pop(*a)

    def update(self, *a: Any, **kw: Any) -> None:
        self.rev += 1
        super().update(*a, **kw)


VERSION_LEVELS = ("version", "variant", "checkpoint")
ORGISH = ("org", "person")
PRODUCT_TYPES = ("model", "product", "software")
# the last words of an org's name, never a family's ("Zentra Labs" is an org, not the account of a family "Labs")
CORP_WORDS = frozenset(("ai", "inc", "corporation", "corp", "labs", "lab", "technologies", "holdings", "group",
                        "research", "foundation", "official", "team", "hq", "news", "dev", "devs", "developers",
                        "company", "co", "ltd", "llc", "studio", "studios"))


class Book:
    """The entities, aliases, current redirects and pins, read once a run (or once a request)."""

    def __init__(self) -> None:
        self.ents: Dict[str, Ent] = {}
        self.alias: Dict[str, str] = {}
        self.redirect: Dict[str, Tuple[str, bool]] = Redirects()   # from -> (to, automatic)
        self.types: Dict[str, Counter] = {}                  # 0164: entity -> its current mentions' types, counted
        self.pins: Dict[Tuple[str, str, int], str] = {}
        self.pin_keys: Dict[Tuple[str, str], Tuple[str, str]] = {}   # 0133: (post, name key): (guide, its pin)
        self.never: Set[Tuple[str, str]] = set()             # pairs the owner kept apart or whose merge was undone
        self.mentioned: Set[str] = set()                     # the entities a mention names (a maker or family made
                                                             # for the hierarchy alone is never a candidate)
        self.subject: Dict[str, int] = {}                    # 0164 B: entity -> its subject mentions typed a product

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

    def prime(self, ids: Iterable[Optional[str]] = (), keys: Iterable[Optional[str]] = ()) -> None:
        """Read ahead the entities (by id) and aliases (by key) a reader is about to ask, in one read each: a whole
        book holds them all already (a page's book, `lazy_book`, reads them now)."""

    def maker_roots(self) -> Set[str]:
        """The clusters some entity names as its maker (its stated maker's alias, read through the merges)."""
        return {r for r in (self.root(self.by_key(N.key(e.maker))) for e in self.ents.values() if e.maker) if r}

    def name_forms(self, keep: Any) -> "NameForms":
        """Each cluster's names squashed (names.squash of the keys of its entities and of the aliases leading to it)
        and, of the roots `keep(root)` admits, which a squashed form names: as the book is now."""
        by_root: Dict[str, Set[str]] = defaultdict(set)
        for k, eid in self.alias.items():
            r = self.root(eid)
            if r:
                by_root[r].add(N.squash(k))
        for eid, e in self.ents.items():
            r = self.root(eid)
            if r:
                by_root[r].add(N.squash(e.key))
        by_form: Dict[str, Set[str]] = defaultdict(set)
        for r, fs in by_root.items():
            if keep(r):
                for f in fs:
                    if f:
                        by_form[f].add(r)
        return NameForms(lambda r: by_root.get(r, set()), lambda f: by_form.get(f, set()))

    # v10.17 (0186): what a page asks of the book besides ids and keys, here so a page's book answers them by query
    def alias_keys(self, root: str) -> List[str]:
        """The keys of the aliases that lead to `root`."""
        return [k for k, eid in self.alias.items() if self.root(eid) == root]

    def with_parent_in(self, root: str) -> List[str]:
        """The entities whose parent leads to `root` (in the book's order)."""
        return [x for x, e in self.ents.items() if e.parent and self.root(e.parent) == root]

    def by_squashed_key(self, forms: Iterable[str]) -> List[str]:
        """The entities whose key squashes (names.squash) to one of `forms` (in the book's order)."""
        forms = set(forms)
        return [x for x, e in self.ents.items() if e.sq in forms]

    def first_with_key(self, key: str) -> Optional[str]:
        """The first entity (in the book's order) whose own key is `key`."""
        return next((x for x, e in self.ents.items() if e.key == key), None)

    def keys_around(self, key: str) -> List[str]:
        """The entities (in the book's order) whose key starts with `key` and a space, or is the start of `key` before
        a space ("acme" and "acme widget")."""
        return [x for x, e in self.ents.items() if e.key and (e.key.startswith(key + " ") or key.startswith(e.key + " "))]

    def cluster_size(self, root: str) -> int:
        """len(members()[root]) without walking every entity (v10.13.9: a merge asked it of the whole book each
        time): the entities whose redirects lead to `root`, read from the current redirects (an undo or a merge in
        between is always seen)."""
        return len(self.cluster(root))

    def _into(self) -> Dict[str, List[str]]:
        """{to: [from]} of the current redirects; kept while they don't change (0164: Redirects counts its changes;
        a plain dict is read again each time)."""
        rev = (id(self.redirect), getattr(self.redirect, "rev", None), len(self.redirect))
        got = self.__dict__.get("_into_cache")
        if got is None or got[0] != rev or rev[1] is None:
            into: Dict[str, List[str]] = defaultdict(list)
            for frm, (to, _) in self.redirect.items():
                into[to].append(frm)
            got = (rev, into)
            self.__dict__["_into_cache"] = got
        return got[1]

    def cluster(self, root: str) -> List[str]:
        """The entities whose redirects lead to `root` (root's own included when it is an entity)."""
        into = self._into()
        seen, todo, out = {root}, [root], []
        while todo:
            x = todo.pop()
            if x in self.ents and self.root(x) == root:
                out.append(x)
            for y in into.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    todo.append(y)
        return out

    def etype(self, eid: str) -> Optional[str]:
        """0164: the type most of an entity's current mentions give (as read: schemas.entity_type), else its own."""
        got = self.types.get(eid)
        if got:
            return schemas_type(max(got.items(), key=lambda kv: (kv[1], str(kv[0])))[0])
        e = self.ents.get(eid)
        return schemas_type(e.type) if e else None

    def version_parents(self) -> Set[str]:
        """0164: the entities some version, variant or checkpoint names as its parent (kept; the Writer adds)."""
        got = self.__dict__.get("_version_parents")
        if got is None:
            got = {e.parent for e in self.ents.values() if e.parent and e.level in VERSION_LEVELS}
            self.__dict__["_version_parents"] = got
        return got

    def kids(self) -> Dict[str, List[str]]:
        """0164 B: {parent: the versions, variants and checkpoints naming it} (kept; the Writer adds)."""
        got = self.__dict__.get("_kids")
        if got is None:
            got = defaultdict(list)
            for e in self.ents.values():
                if e.parent and e.level in VERSION_LEVELS:
                    got[e.parent].append(e.id)
            self.__dict__["_kids"] = got
        return got

    def family_like(self, eid: str) -> bool:
        """0164 B: a product family: a `family` entity or one a version names as its parent, or a name its mentions
        give as their subject typed a model, product or software; its mentions mostly not an org or person."""
        e = self.ents.get(eid)
        if e is None or e.status == "not_entity" or e.level in VERSION_LEVELS:
            return False
        t = self.etype(eid)
        if t in ORGISH:
            return False
        return e.level == "family" or eid in self.version_parents() or \
            (t in PRODUCT_TYPES and self.subject.get(eid, 0) > 0)

    def maker_keys(self, root: str) -> Set[str]:
        """0164 B: the names (keys) of a family cluster's maker: its members' and their versions' stated makers, its
        members' parents' clusters, and each stated maker's cluster ("Zentra AI" stated, merged with Zentra: both)."""
        out: Set[str] = set()
        stated: Set[str] = set()
        kids = self.kids()
        for m in self.cluster(root):
            e = self.ents[m]
            if e.level in VERSION_LEVELS:
                continue
            for x in [e] + [self.ents[k] for k in kids.get(m, ()) if k in self.ents]:
                if x.maker and N.key(x.maker):
                    stated.add(N.key(x.maker))
            if e.parent:
                out |= {self.ents[y].key for y in self.cluster(self.root(e.parent))}
        out |= stated
        for k in stated:
            r = self.root(self.by_key(k))
            if r is not None:
                out |= {self.ents[y].key for y in self.cluster(r)}
        return {k for k in out if k}

    def product_of(self, key: str) -> Optional[str]:
        """0164 B: the family a product account's name names, "<maker> <family>" ("Zentra Vela": the maker Zentra in
        front of the family Vela): <maker> one of the family's maker's names or the first words of one ("Zentra" of
        "Zentra AI"), <family> a known product family (`family_like`). Its id, else None. A name ending in an org's
        word ("Zentra Labs") is never one."""
        words = (key or "").split()
        if len(words) < 2 or words[-1] in CORP_WORDS:
            return None
        for i in range(1, len(words)):
            prefix, rest = " ".join(words[:i]), " ".join(words[i:])
            if len(N.squash(rest)) < 3:
                continue
            for c in dict.fromkeys([self.by_key(rest)] + list(self.families().get(rest, ()))):
                if not c or not self.family_like(c):
                    continue
                makers = self.maker_keys(self.root(c))
                if prefix in makers or any(k.startswith(prefix + " ") for k in makers):
                    return c
        return None

    def families(self) -> Dict[str, List[str]]:
        """0164: {key: the `family` entities made for it} (kept; the Writer adds)."""
        got = self.__dict__.get("_families")
        if got is None:
            got = {}
            for e in self.ents.values():
                if e.level == "family":
                    got.setdefault(e.key, []).append(e.id)
            self.__dict__["_families"] = got
        return got

    def sides(self, members: Iterable[str]) -> Tuple[Set[str], Set[str]]:
        """0164: (a cluster's family side, its org side). The family side: a `family` entity, or one a version names
        as its parent, whose mentions are mostly not an org or person; and a name that is a family name with words
        in front ("Zentra Vela" beside the family "Vela"), whatever its mentions' type. The org side: an org or
        person that is neither."""
        ms = [m for m in members if m in self.ents]
        vp = self.version_parents()
        fam = {m for m in ms if (self.ents[m].level == "family" or m in vp) and self.etype(m) not in ORGISH}
        keys = {self.ents[m].key for m in fam if len(self.ents[m].key) >= 3}
        fam |= {m for m in ms if any(self.ents[m].key.endswith(" " + k) for k in keys)}
        # 0164 B: a product account ("Zentra Vela" typed an org) is on the family side wherever its family is
        fam |= {m for m in ms if m not in fam and self.etype(m) == "org" and " " in self.ents[m].key
                and self.product_of(self.ents[m].key)}
        org = {m for m in ms if m not in fam and self.etype(m) in ORGISH}
        return fam, org

    def org_like(self, root: str) -> bool:
        """0164: a cluster that is an org (or person) and holds no family."""
        fam, org = self.sides(self.cluster(root))
        return bool(org) and not fam

    def label(self, eid: Optional[str]) -> Optional[str]:
        """0164: the name an entity's cluster is shown under (its root's shown name, else its name)."""
        r = self.root(eid)
        e = self.ents.get(r) if r else None
        return None if e is None else (e.shown_name or e.name)

    def shown_type(self, eid: Optional[str]) -> Optional[str]:
        """0164: the type an entity's cluster is shown under (as read)."""
        r = self.root(eid)
        e = self.ents.get(r) if r else None
        return None if e is None else schemas_type(e.shown_type or e.type)


def read_ents(cur: Any, b: "Book", ids: Optional[Iterable[str]] = None) -> None:
    """Read entities into the book: every one, or (v10.16) those of `ids`."""
    cur.execute(f"""SELECT id::text, type, name, key, level, parent::text, maker, family_key, version, version_key, variant,
                          size, build, status, first_seen, shown_name, shown_type FROM mx_entities
                    {"WHERE id = ANY(%s::uuid[])" if ids is not None else ""}""",
                (sorted(set(ids)),) if ids is not None else None)
    for (eid, type_, name, key, level, parent, maker, fam, version, vkey, variant, size, build, status,
         first, shown_name, shown_type) in cur.fetchall():
        b.ents[eid] = Ent(eid, type_, name, key, level, parent, maker, fam, version, N.from_json(vkey), variant, size,
                          build, status, first, haiku={"family": fam, "version": version, "variant": variant,
                                                       "size": size, "build": build},
                          shown_name=shown_name, shown_type=shown_type)


def load_book(cur: Any, *, counts: bool = True) -> Book:
    b = Book()
    read_ents(cur, b)
    cur.execute("SELECT key, entity_id::text FROM mx_entity_aliases")
    b.alias = dict(cur.fetchall())
    cur.execute("SELECT from_id::text, to_id::text, automatic FROM mx_entity_redirects WHERE undone_at IS NULL")
    b.redirect = Redirects({f: (t, auto) for f, t, auto in cur.fetchall()})
    cur.execute("SELECT post_id::text, guide, n, entity_id::text FROM mx_entity_pins WHERE undone_at IS NULL")
    b.pins = {(p, g, n): e for p, g, n, e in cur.fetchall()}
    cur.execute("""SELECT p.post_id::text, m.name, p.guide, p.entity_id::text FROM mx_entity_pins p JOIN mx_mentions m
                     ON m.post_id = p.post_id AND m.guide = p.guide AND m.n = p.n WHERE p.undone_at IS NULL""")
    b.pin_keys = {(pid, N.key(name)): (g, e) for pid, name, g, e in cur.fetchall()}   # 0133: a split carries to a new guide
    cur.execute("""SELECT least(a, b)::text, greatest(a, b)::text FROM mx_entity_queue
                    WHERE kind = 'alias' AND answer IN ('other_version', 'different', 'not_entity')
                   UNION SELECT least(from_id, to_id)::text, greatest(from_id, to_id)::text FROM mx_entity_redirects
                    WHERE undone_at IS NOT NULL AND undone_by = 'owner'""")
    b.never = {(x, y) for x, y in cur.fetchall()}
    if not counts:   # v10.14: the caller reads no type count (types, subject, mentioned stay empty)
        return b
    cur.execute("""SELECT entity_id::text, type, count(*), count(*) FILTER (WHERE role = 'subject') FROM mx_mentions_now
                    WHERE entity_id IS NOT NULL GROUP BY 1, 2""")
    product: Dict[Optional[str], bool] = {}   # v10.14: a type read once, a Counter made once an entity
    for eid, type_, n, subj in cur.fetchall():   # 0164: each entity's mentions' types, counted (one read)
        got = b.types.get(eid)
        if got is None:
            got = b.types[eid] = Counter()
        got[type_] += n
        if subj:
            if type_ not in product:
                product[type_] = schemas_type(type_) in PRODUCT_TYPES
            if product[type_]:   # 0164 B: a product as the subject
                b.subject[eid] = b.subject.get(eid, 0) + subj
    b.mentioned = set(b.types) | set(b.pins.values())
    return b


@dataclass(frozen=True)
class NameForms:
    """`of(root)`: the cluster's squashed names; `roots(form)`: the admitted clusters one of whose names squashes to
    `form` (Book.name_forms)."""
    of: Any
    roots: Any


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class _Reads(dict):
    """A dict that reads what it is asked and doesn't hold yet (`read(keys) -> {key: value}`), and remembers what
    isn't there. It cannot be walked: what it holds is only what was asked (TypeError)."""

    def __init__(self, read: Any) -> None:
        super().__init__()
        self._read, self._absent = read, set()

    def want(self, keys: Iterable[Any]) -> None:
        todo = {k for k in keys if k is not None and not dict.__contains__(self, k) and k not in self._absent}
        if todo:
            got = self._read(sorted(todo))
            dict.update(self, got)
            self._absent |= todo - set(got)

    def get(self, k: Any, default: Any = None) -> Any:
        self.want((k,))
        return dict.get(self, k, default)

    def __contains__(self, k: Any) -> bool:
        self.want((k,))
        return dict.__contains__(self, k)

    def __getitem__(self, k: Any) -> Any:
        self.want((k,))
        return dict.__getitem__(self, k)

    def _whole(self, *_a: Any, **_k: Any) -> Any:
        raise TypeError("a page's book (identity.lazy_book) holds only what was asked: read the whole book (load_book)")

    __iter__ = __len__ = keys = values = items = _whole


class _Has:
    """A set that answers `x in it` by asking (`has(x)`, remembered; `many(xs) -> the xs in it` answers several in
    one go, `want(xs)`); it cannot be walked (TypeError)."""

    def __init__(self, has: Any, many: Any = None) -> None:
        self._has, self._many, self._got = has, many, {}

    def want(self, xs: Iterable[Any]) -> None:
        todo = sorted({x for x in xs if x is not None and x not in self._got})
        if todo and self._many is not None:
            yes = set(self._many(todo))
            self._got.update({x: x in yes for x in todo})

    def __contains__(self, x: Any) -> bool:
        if x not in self._got:
            self._got[x] = bool(self._has(x))
        return self._got[x]

    def _whole(self, *_a: Any, **_k: Any) -> Any:
        raise TypeError("a page's book (identity.lazy_book) holds only what was asked: read the whole book (load_book)")

    __iter__ = __len__ = _whole


class LazyBook(Book):
    """A page's book (v10.17, issue 0186): the merges and pins read whole (they are few), each entity and alias read
    when first asked (`ents.get(id)`, `id in ents`, `alias.get(key)`; `prime` reads many in one go) and kept for the
    request. It answers what a whole book answers by id and key (root, label, by_key, cluster, the maker's names, an
    entity's mention counts, its versions and families, the entities under a cluster, those of a squashed key); it
    cannot be walked (iterating `ents`, `alias`, `types` raises TypeError; `members()` too). A page's request reads
    a few hundred entities, not the whole book (250k on the server, read in full by every News, post and entity page
    before)."""

    def __init__(self, cur: Any) -> None:
        super().__init__()
        self._cur = cur
        self.ents = _Reads(self._ents_of)
        self.alias = _Reads(self._aliases_of)
        cur.execute("SELECT from_id::text, to_id::text, automatic FROM mx_entity_redirects WHERE undone_at IS NULL")
        self.redirect = Redirects({f: (t, auto) for f, t, auto in cur.fetchall()})
        cur.execute("SELECT post_id::text, guide, n, entity_id::text FROM mx_entity_pins WHERE undone_at IS NULL")
        self.pins = {(p, g, n): e for p, g, n, e in cur.fetchall()}
        # the mention counts (load_book's types / subject / mentioned), read per entity asked
        self._counted_ids: Set[str] = set()
        self._types_got: Dict[str, Counter] = {}
        self._subject_got: Dict[str, int] = {}
        self.types = _Reads(lambda ids: self._counted(ids)[0])
        self.subject = _Reads(lambda ids: self._counted(ids)[1])
        pinned = set(self.pins.values())
        self.mentioned = _Has(lambda x: x in self.types or x in pinned)

    def _counted(self, ids: Sequence[str]) -> Tuple[Dict[str, Counter], Dict[str, int]]:
        todo = [i for i in ids if isinstance(i, str) and _UUID.match(i) and i not in self._counted_ids]
        if todo:   # as load_book counts them, for these entities
            self._cur.execute("""SELECT entity_id::text, type, count(*), count(*) FILTER (WHERE role = 'subject')
                                   FROM mx_mentions_now WHERE entity_id = ANY(%s::uuid[]) GROUP BY 1, 2""", (todo,))
            product: Dict[Optional[str], bool] = {}
            for eid, type_, n, subj in self._cur.fetchall():
                self._types_got.setdefault(eid, Counter())[type_] += n
                if subj:
                    if type_ not in product:
                        product[type_] = schemas_type(type_) in PRODUCT_TYPES
                    if product[type_]:
                        self._subject_got[eid] = self._subject_got.get(eid, 0) + subj
            self._counted_ids.update(todo)
        return ({i: self._types_got[i] for i in ids if i in self._types_got},
                {i: self._subject_got[i] for i in ids if i in self._subject_got})

    def _ordered_ids(self, where: str, args: Any) -> List[str]:
        """Entity ids by a condition, in the table's order (the whole book's order: load_book reads it unordered)."""
        self._cur.execute(f"SELECT id::text FROM mx_entities WHERE {where} ORDER BY ctid", args)
        got = [i for (i,) in self._cur.fetchall()]
        self.ents.want(got)
        return got

    def _names_versions(self, x: Any) -> bool:
        if not (isinstance(x, str) and _UUID.match(x)):
            return False
        self._cur.execute("SELECT EXISTS (SELECT 1 FROM mx_entities WHERE parent = %s::uuid AND level = ANY(%s))",
                          (x, list(VERSION_LEVELS)))
        return bool(self._cur.fetchone()[0])

    def version_parents(self) -> Any:
        got = self.__dict__.get("_version_parents")
        if got is None:
            got = self.__dict__["_version_parents"] = _Has(self._names_versions)
        return got

    def kids(self) -> Dict[str, List[str]]:
        def read(parents: Sequence[str]) -> Dict[str, List[str]]:
            ps = [p for p in parents if isinstance(p, str) and _UUID.match(p)]
            out: Dict[str, List[str]] = {}
            for x in self._ordered_ids("parent = ANY(%s::uuid[]) AND level = ANY(%s)", (ps, list(VERSION_LEVELS))) if ps else []:
                out.setdefault(self.ents[x].parent, []).append(x)
            return out
        got = self.__dict__.get("_kids")
        if got is None:
            got = self.__dict__["_kids"] = _Reads(read)
        return got

    def families(self) -> Dict[str, List[str]]:
        def read(keys: Sequence[str]) -> Dict[str, List[str]]:
            out: Dict[str, List[str]] = {}
            for x in self._ordered_ids("key = ANY(%s) AND level = 'family'", (list(keys),)):
                out.setdefault(self.ents[x].key, []).append(x)
            return out
        got = self.__dict__.get("_families")
        if got is None:
            got = self.__dict__["_families"] = _Reads(read)
        return got

    def alias_keys(self, root: str) -> List[str]:
        ids = [i for i in self._leading_to(root) if _UUID.match(i)]
        self._cur.execute("SELECT key, entity_id::text FROM mx_entity_aliases WHERE entity_id = ANY(%s::uuid[])", (ids,))
        return [k for k, eid in self._cur.fetchall() if self.root(eid) == root]

    def with_parent_in(self, root: str) -> List[str]:
        ids = [i for i in self._leading_to(root) if _UUID.match(i)]
        return [x for x in self._ordered_ids("parent = ANY(%s::uuid[])", (ids,))
                if self.root(self.ents[x].parent) == root] if ids else []

    def by_squashed_key(self, forms: Iterable[str]) -> List[str]:
        forms = sorted(set(forms))
        return self._ordered_ids(f"{N.SQUASH_SQL} = ANY(%s)", (forms,)) if forms else []

    def first_with_key(self, key: str) -> Optional[str]:
        got = self._ordered_ids("key = %s", (key,))
        return got[0] if got else None

    def keys_around(self, key: str) -> List[str]:
        like = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + " %"
        starts = [" ".join(key.split(" ")[:i]) for i in range(1, len(key.split(" ")))]
        return [x for x in self._ordered_ids("key LIKE %s ESCAPE '\\' OR key = ANY(%s)", (like, starts))
                if (k := self.ents[x].key) and (k.startswith(key + " ") or key.startswith(k + " "))]

    def _ents_of(self, ids: Sequence[str]) -> Dict[str, Ent]:
        b = Book()
        ids = [i for i in ids if isinstance(i, str) and _UUID.match(i)]
        if ids:
            read_ents(self._cur, b, ids)
        return b.ents

    def _aliases_of(self, keys: Sequence[str]) -> Dict[str, str]:
        self._cur.execute("SELECT key, entity_id::text FROM mx_entity_aliases WHERE key = ANY(%s)", (list(keys),))
        return dict(self._cur.fetchall())

    def prime(self, ids: Iterable[Optional[str]] = (), keys: Iterable[Optional[str]] = ()) -> None:
        ids = list(ids)
        self.ents.want(ids + [self.root(i) for i in ids])
        self.alias.want(keys)

    def maker_roots(self) -> Set[str]:
        self._cur.execute("SELECT DISTINCT maker FROM mx_entities WHERE maker IS NOT NULL AND maker <> ''")
        keys = {N.key(m) for (m,) in self._cur.fetchall()}
        self.alias.want(k for k in keys if k)
        return {r for r in (self.root(self.by_key(k)) for k in keys) if r}

    def _leading_to(self, root: str) -> List[str]:
        """Every id the merges lead to `root` (root's own included), entity or not."""
        into = self._into()
        seen, todo, out = {root}, [root], []
        while todo:
            x = todo.pop()
            if self.root(x) == root:
                out.append(x)
            for y in into.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    todo.append(y)
        return out

    def name_forms(self, keep: Any) -> NameForms:
        """As Book.name_forms, read per root and per form (migration 0127's indexes on names.SQUASH_SQL)."""
        cur, of_memo, roots_memo = self._cur, {}, {}

        def of(root: Optional[str]) -> Set[str]:
            if root not in of_memo:
                ids = [i for i in self._leading_to(root) if _UUID.match(i)] if root else []
                cur.execute("""SELECT key FROM mx_entity_aliases WHERE entity_id = ANY(%(ids)s::uuid[])
                               UNION ALL SELECT key FROM mx_entities WHERE id = ANY(%(ids)s::uuid[])""", {"ids": ids})
                of_memo[root] = {N.squash(k) for (k,) in cur.fetchall()} if ids else set()
            return of_memo[root]

        def roots(form: str) -> Set[str]:
            if form not in roots_memo:
                got: Set[str] = set()
                if form:
                    cur.execute(f"""SELECT entity_id::text FROM mx_entity_aliases WHERE {N.SQUASH_SQL} = %(f)s
                                    UNION SELECT id::text FROM mx_entities WHERE {N.SQUASH_SQL} = %(f)s""", {"f": form})
                    got = {r for r in (self.root(i) for (i,) in cur.fetchall()) if r}
                roots_memo[form] = {r for r in got if keep(r)}
            return roots_memo[form]

        return NameForms(of, roots)


def lazy_book(cur: Any) -> LazyBook:
    """A page's book (LazyBook): what it is asked, read when asked."""
    return LazyBook(cur)


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
    ref: Optional[str] = None        # 0133: the citation rule's identifier (arXiv, DOI, a document link)
    by_name: Optional[str] = None    # 0133: a document's publisher or author, as written
    call_id: Optional[str] = None

    @cached_property
    def key(self) -> str:
        return N.key(self.name)


def _mentions(cur: Any, guide: Any, *, unlinked: bool, limit: Optional[int] = None,
              posts: Optional[Sequence[str]] = None) -> List[Mention]:
    """The current mentions (0133: mx_mentions_now, each post's newest valid entities answer, of `guide`'s guides);
    `posts`: only those posts' (v10.13.9: the full pass's pages)."""
    params: List[Any] = [guide] + ([list(posts)] if posts is not None else []) + ([limit] if limit else [])
    cur.execute(f"""SELECT m.post_id::text, m.guide, m.n, m.span, m.name, m.type, m.role, m.maker, m.family, m.version,
                           m.variant, m.size, m.build, m.entity_id::text,
                           COALESCE(p.published_at, p.fetched_at), m.ref, m.by_name, m.call_id::text
                      FROM mx_mentions_now m LEFT JOIN posts p ON p.id = m.post_id
                     WHERE m.guide = ANY(%s) {"AND m.entity_id IS NULL AND m.name_key <> ''" if unlinked else ""}
                           {"AND m.post_id = ANY(%s::uuid[])" if posts is not None else ""}
                     ORDER BY COALESCE(p.published_at, p.fetched_at) DESC NULLS LAST, m.post_id, m.n
                     {"LIMIT %s" if limit else ""}""", params)
    return [Mention(p, g, n, span or "", name or "", t, r, mk,
                    {"family": fam, "version": v, "variant": var, "size": sz, "build": bd}, e, at, ref, by, call)
            for p, g, n, span, name, t, r, mk, fam, v, var, sz, bd, e, at, ref, by, call in cur.fetchall()]


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
        if parent and level in VERSION_LEVELS:
            self.book.version_parents().add(parent)
            self.book.kids()[parent].append(eid)
        if level == "family":
            self.book.families().setdefault(key, []).append(eid)
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
        fam = w.book.product_of(key) if schemas_type(m.type) == "org" else None
        if fam is not None:
            return product_account(w, key, m, fam, first)
        parent = _maker_entity(w, maker, first) if maker and N.key(maker) != key else None
        return w.entity(type_=m.type, name=m.name, key=key, level="thing", parent=parent, maker=maker,
                        fields=dict(N.NONE), first_seen=first)
    fam_key = hk[0] if N.has_version(hk) and hk[0] else pk[0]
    parent = None
    if fam_key and fam_key != key:
        parent = w.book.root(w.book.by_key(fam_key))
        if parent is not None and w.book.org_like(parent):
            # 0164: an org (or person) is never a version's family: the family entity of that name under it
            parent = family_under(w, parent, fam_key, m.type, maker, first,
                                  (m.fields.get("family") or "").strip() if N.has_version(hk) else "")
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


def product_type(book: Book, fam: str) -> str:
    """0164 B: the type a product account takes: its family's (as its mentions give it), else a model."""
    for t in (book.etype(fam), schemas_type(book.ents[fam].type)):
        if t and t not in ORGISH:
            return t
    return "model"


def product_account(w: Writer, key: str, m: Mention, fam: str, first: Optional[datetime]) -> str:
    """0164 B: a product account's entity ("Zentra Vela" typed an org, the family Vela's account): made with its
    family's type and merged into the family (rule `product_account`, a redirect like any other, undoable), unless
    the family's cluster holds an org (the owner's to settle) or the owner kept them apart."""
    eid = w.entity(type_=product_type(w.book, fam), name=m.name, key=key, level="thing", parent=None,
                   maker=(m.maker or "").strip() or None, fields=dict(N.NONE), first_seen=first)
    book = w.book
    r = book.root(fam)
    if not book.sides(book.cluster(r))[1] and pair(eid, r) not in book.never:
        merge(w.cur, book, eid, r, by="rule:product_account", automatic=True, run_id=w.run_id,
              evidence={"rules": ["product_account"], "confidence": RULE_CONF, "family": book.ents[fam].name,
                        "typed": m.type})
    return eid


def maker_root(book: Book, maker: Optional[str]) -> Optional[str]:
    """0164: the cluster a stated maker's name aliases (None: no entity of that name)."""
    k = N.key(maker)
    return book.root(book.by_key(k)) if k else None


def same_maker(book: Book, x: Optional[str], y: Optional[str]) -> bool:
    """0164: two stated makers name one maker: the same key, or keys of one cluster ("Zentra AI" merged into Zentra)."""
    kx, ky = N.key(x), N.key(y)
    if kx == ky:
        return True
    rx, ry = maker_root(book, x), maker_root(book, y)
    return rx is not None and rx == ry


def family_under(w: Writer, org: str, fam_key: str, type_: Optional[str], maker: Optional[str],
                 first: Optional[datetime], fam_name: str = "") -> str:
    """0164: the family a version names when its family's name is an org's ("Zentra 5" by Zentra, the org Zentra):
    a `family` entity of that key outside any org cluster, else one made under the org (parent the org; its key's
    alias stays the org's, so the org's own mentions stay the org's)."""
    book = w.book
    for eid in book.families().get(fam_key, ()):
        r = book.root(eid)
        e = book.ents[eid]
        if e.status == "not_entity" or book.org_like(r):
            continue
        if maker and e.maker and not same_maker(book, maker, e.maker):   # another maker's family of that name
            continue
        return r
    o = book.ents[org]
    if not fam_name or N.key(fam_name) != fam_key:
        fam_name = next((book.ents[x].name for x in book.cluster(org) if book.ents[x].key == fam_key), fam_key)
    t = type_ if schemas_type(type_) not in ORGISH else "model"
    return w.entity(type_=t, name=fam_name, key=fam_key, level="family", parent=org, maker=maker or o.name,
                    fields=dict(N.NONE), first_seen=first)


def resolve_mention(book: Book, m: Mention) -> Optional[str]:
    """The entity a mention links to now: its pin, else its key's alias (before redirects; reads go through them)."""
    pin = book.pins.get((m.post_id, m.guide, m.n))
    if not pin:   # 0133: the owner's pin of the same name in the post's earlier guide's set (never within one guide)
        g, e = book.pin_keys.get((m.post_id, m.key), (None, None))
        pin = e if g is not None and g != m.guide else None
    if pin:
        return pin
    comp = book.__dict__.get("components")   # 0165 A: a span naming a product's component (markx/components.py)
    if comp:
        got = comp.get((m.post_id, m.guide, m.n))
        if got:
            return got
    return book.by_key(m.key)


def link_components(cur: Any, book: Book, w: Writer, ms: Sequence[Mention]) -> Optional[Dict[str, int]]:
    """0165 A: the components among the mentions about to be linked (markx/components.py), when the switch is on:
    their entities made under their products before the keys' own entities are, and the span-only mentions sent to
    them. None when off."""
    from insight_core.markx import components
    if not components.config()["components"]:
        return None
    return components.make(cur, book, w, components.plan(cur, book, ms), run_id=w.run_id)


def _join_refs(w: Writer, refs: Sequence[Mention]) -> None:
    """0133: a document the citation rule read an identifier for (arXiv, DOI, a document link) is one entity whatever
    name each post gives it: its name's key and its identifier's key alias one entity (whichever came first)."""
    for m in refs:
        rk = N.key(m.ref)
        if not rk or rk == m.key:
            continue
        by_ref, by_name = w.book.by_key(rk), w.book.by_key(m.key)
        if by_ref and not by_name:
            w.alias(m.key, by_ref, m.name)
        elif by_name and not by_ref:
            w.alias(rk, by_name, m.ref)


def published(cur: Any, book: Book, w: Writer, ms: Sequence[Mention]) -> int:
    """0133: each linked document mention naming its publisher or author (`by`) as a `published` edge (0131's
    mx_connections, a_kind = b_kind = 'entity', rule 'mention_by'): publisher -> document. The publisher is the
    entity its name's key aliases, made a provisional org (or the type a mention in the same post gives that name)
    when there is none. One current edge a pair (keep everything: never deleted). How many were added."""
    added = 0
    said: Dict[Tuple[str, str], Optional[str]] = {}   # v10.13.9: (post, key) -> the first org/person type, read once
    for x in ms:                                       # (was a scan of every mention for each document mention)
        if x.type in ("org", "person"):
            said.setdefault((x.post_id, x.key), x.type)
    for m in ms:
        if not (m.by_name and m.entity_id and schemas_type(m.type) == "document"):
            continue
        k = N.key(m.by_name)
        if not k or k == m.key:
            continue
        pub = book.by_key(k)
        if pub is None:
            typ = said.get((m.post_id, k)) or "org"
            pub = w.entity(type_=typ, name=m.by_name.strip(), key=k, level="thing", parent=None, maker=None,
                           fields=dict(N.NONE), first_seen=m.at)
        cur.execute("""INSERT INTO mx_connections (a_kind, a, b_kind, b, relation, call_id, rule, evidence)
                       VALUES ('entity', %s, 'entity', %s, 'published', %s, 'mention_by', %s::jsonb)
                       ON CONFLICT DO NOTHING""",
                    (pub, m.entity_id, m.call_id,
                     json.dumps({"post": m.post_id, "guide": m.guide, "n": m.n, "by": m.by_name})))
        added += cur.rowcount
    return added


def schemas_type(t: Optional[str]) -> Optional[str]:
    from insight_core.markx import schemas
    return schemas.entity_type(t)


def link(cur: Any, book: Book, w: Writer, ms: Sequence[Mention]) -> Dict[str, int]:
    """Each mention's entity, made when its key has none; entity_id written where it changes."""
    make_entities(book, w, ms)
    return {**relink(cur, book, ms), "entities_made": len(w.made)}


def make_entities(book: Book, w: Writer, ms: Sequence[Mention]) -> None:
    """The entity of each key the mentions name that has none yet, made from all of its mentions here (v10.13.9:
    before a run links its mentions in chunks, so a key's first seen and majority read every mention the run has)."""
    by_key: Dict[str, List[Mention]] = defaultdict(list)
    for m in ms:
        if m.key:
            by_key[m.key].append(m)
    for k in sorted(by_key):
        refs = [m for m in by_key[k] if m.ref]   # 0133: a key whose document's identifier names an entity joins it
        if book.by_key(k) is None:
            known = next((book.by_key(N.key(m.ref)) for m in refs if book.by_key(N.key(m.ref))), None)
            if known:
                w.alias(k, known, by_key[k][0].name)
            else:
                entity_for(w, k, by_key[k])
        _join_refs(w, refs)


def relink(cur: Any, book: Book, ms: Sequence[Mention]) -> Dict[str, int]:
    """Each mention's entity_id written where the book links it otherwise now."""
    changes = []
    for m in ms:
        eid = resolve_mention(book, m) if m.key else None
        if eid and eid != m.entity_id:
            changes.append((eid, m.post_id, m.guide, m.n))
            m.entity_id = eid
    if changes:
        cur.executemany("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s AND guide = %s AND n = %s", changes)
    return {"mentions": len(ms), "linked": len(changes)}


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


def family_values(book: Book) -> Dict[str, List[Set[Any]]]:
    """{family key: [the versions, variants, sizes, builds its entities state]} (Haiku's fields and the parser's),
    read once a book (the narrowed version guard's 'the family has several')."""
    got = getattr(book, "_family_values", None)
    if got is None:
        got = defaultdict(lambda: [set(), set(), set(), set()])
        for e in book.ents.values():
            if e.status == "not_entity":
                continue
            for fk in (e.hk, e.pk):
                if not fk or not fk[0]:
                    continue
                for i, v in enumerate(N.version_part(fk)):
                    if v is not None:
                        got[N.squash(fk[0])][i].add(v)
        book._family_values = got
    return got


def soft_reason(book: Book, a: Ent, b: Ent, literal: bool = False) -> str:
    """0130 A3, the version guard narrowed, for a soft conflict (one side states what the other lacks):
    'version' (held: the stated field is one the family has several of, so the bare side may be another member);
    'version_year' (only an edition year on one side); 'version_one_side' (a field the family has only one of).
    Both sides stating different versions is 'strong' (kept apart, vconflict) and never comes here."""
    # the families: each side's family field, and each name itself (a bare "Nimbus" is the family of "Nimbus 5")
    fams = {N.squash(fk[0]) for e in (a, b) for fk in (e.hk, e.pk) if fk and fk[0]} | {e.sq for e in (a, b) if e.sq}
    vals = family_values(book)
    fields = False
    for ka, kb in (((a.pk, b.pk),) if literal else ((a.hk, b.hk), (a.pk, b.pk))):
        for i, (x, y) in enumerate(zip(N.version_part(ka), N.version_part(kb))):
            if (x is None) == (y is None):
                continue
            fields = True
            if any(len(vals[f][i]) >= 2 for f in fams if f in vals):
                return "version"
    return "version_one_side" if fields else "version_year"


def strong_only_one(a: Ent, b: Ent) -> bool:
    """A strong version conflict in Haiku's fields or the parser's, not both: a Haiku-parser disagreement."""
    def strong(ka, kb):
        return any(x is not None and y is not None and not (N.ver_eq(x, y) if i == 0 else x == y)
                   for i, (x, y) in enumerate(zip(N.version_part(ka), N.version_part(kb))))
    return strong(a.hk, b.hk) != strong(a.pk, b.pk) and not (N.years(a.key) and N.years(b.key) and N.years(a.key) != N.years(b.key))


def types_ok(a: Optional[str], b: Optional[str]) -> bool:
    a, b = schemas_type(a), schemas_type(b)   # 0133: ent-v3's paper is a document
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


def _index(book: Book, name: str, empty: Any, add: Any) -> Any:
    """An index over the live entities, kept for the book (0128: the full pass's chunks share it). v10.13.9: grown
    with the entities that became live since it was last read (`add(index, entity)`), never rebuilt: the live set only
    grows within a run (a run's chunks link new mentions), and a merge changes roots, which no index holds."""
    cache = book.__dict__.setdefault("_indexes", {})
    if name not in cache:
        cache[name] = [empty(), set(), None]
    got = cache[name]
    index, have = got[0], got[1]
    if got[2] != (len(book.ents), len(book.mentioned)):
        for e in _live(book):
            if e.id not in have:
                have.add(e.id)
                add(index, e)
        got[2] = (len(book.ents), len(book.mentioned))
    return index


def _string_add(index: Any, e: Ent) -> None:
    by_gram, by_sq = index
    by_sq[e.sq].append(e.id)
    for g in e.grams:
        by_gram[g].append(e.id)


def _strings(book: Book):
    return _index(book, "strings", lambda: (defaultdict(list), defaultdict(list)), _string_add)


def pool_strings(pool: Pool, book: Book, seeds: Iterable[str]) -> None:
    """Squashed equality, word containment (4+ letters), trigram Jaccard >= 0.5: blocked on shared grams."""
    by_gram, by_sq = _strings(book)
    for sid in seeds:
        e = book.ents.get(sid)
        if e is None or not e.sq:
            continue
        for o in by_sq.get(e.sq, ()):
            pool.add(e.id, o, "str", "squash")
        cands: Counter = Counter()
        for g in e.grams:
            got = by_gram.get(g, ())
            if len(got) < GRAM_CAP:
                cands.update(got)
        for oid, _ in cands.most_common(GRAM_TOP):
            if oid == e.id:
                continue
            o = book.ents[oid]
            a, b = e.sq, o.sq
            # N.jaccard(a, b), on the grams each entity keeps
            if a == b or (min(len(a), len(b)) >= 4 and N.word_contains(e.key, o.key)) or \
                    len(e.grams & o.grams) / max(1, len(e.grams | o.grams)) >= JAC_BAR:
                pool.add(e.id, oid, "str")


def pool_family(pool: Pool, book: Book, seeds: Iterable[str]) -> None:
    """The same family key, another surface form."""
    def add(by_fam: Dict[str, List[str]], e: Ent) -> None:
        for f in {e.hk[0], e.pk[0]} - {None}:
            by_fam[f].append(e.id)
    by_fam = _index(book, "family", lambda: defaultdict(list), add)
    for sid in seeds:
        e = book.ents.get(sid)
        if e is None:
            continue
        for f in {e.hk[0], e.pk[0]} - {None}:
            for o in by_fam.get(f, ()):
                pool.add(sid, o, "family")


def pool_makers(pool: Pool, book: Book, seeds: Iterable[str]) -> None:
    """The maker-prefix forms ("Zeta Z200" / "Z200")."""
    def add(index: Any, e: Ent) -> None:
        mk = N.key(e.maker or "")
        if mk and e.key.startswith(mk + " "):
            index[N.squash(e.key[len(mk) + 1:])].append(e.id)
    by_sq = _strings(book)[1]
    prefixed = _index(book, "makers", lambda: defaultdict(list), add)
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


def handles(cur: Any, guide: str, post_ids: Optional[Sequence[str]] = None,
            into: Optional[Dict[str, Dict[str, bool]]] = None) -> Dict[str, Dict[str, bool]]:
    """{entity: {squashed handle form: drops a word}} from the handles its mentions were written as. v10.13.9:
    `post_ids` reads only those posts' mentions, folded `into` what was read before (a run's later chunks)."""
    cur.execute(f"""SELECT DISTINCT entity_id::text, span FROM mx_mentions_now
                     WHERE guide = ANY(%s) AND entity_id IS NOT NULL AND (span LIKE '@%%' OR span LIKE '%%\\_%%')
                     {"AND post_id = ANY(%s::uuid[])" if post_ids is not None else ""}""",
                (guide, list(post_ids)) if post_ids is not None else (guide,))
    out: Dict[str, Dict[str, bool]] = into if into is not None else defaultdict(dict)
    for eid, span in cur.fetchall():
        if N.is_handle(span):
            for f, extra in N.handle_forms(span).items():
                out[eid][f] = out[eid].get(f, True) and extra
    return out


def pool_handles(pool: Pool, book: Book, hf: Dict[str, Dict[str, bool]], seeds: Set[str]) -> Dict[Tuple[str, str], bool]:
    """Handle pairs: {pair: the handle form drops a word (an org's "acmeai" for "acme")}."""
    by_sq = _strings(book)[1]
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


def anchors(cur: Any, book: Book, guide: str, post_ids: Optional[Sequence[str]] = None,
            into: Optional[Dict[str, Set[str]]] = None) -> Dict[str, Set[str]]:
    """{entity: repository / model addresses} its subject posts link, when the address names it. v10.13.9:
    `post_ids` reads only those posts, added `into` what was read before."""
    cur.execute(f"""SELECT DISTINCT m.entity_id::text, l.target_url FROM mx_mentions_now m
                      JOIN post_links l ON l.post_id = m.post_id
                     WHERE m.guide = ANY(%s) AND m.role = 'subject' AND m.entity_id IS NOT NULL
                       AND (l.target_url ILIKE '%%github.com/%%' OR l.target_url ILIKE '%%huggingface.co/%%')
                       {"AND m.post_id = ANY(%s::uuid[])" if post_ids is not None else ""}""",
                (guide, list(post_ids)) if post_ids is not None else (guide,))
    out: Dict[str, Set[str]] = into if into is not None else defaultdict(set)
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
    return {p_ for got in paren_by_post(cur, book, guide, post_ids).values() for p_ in got}


def paren_by_post(cur: Any, book: Book, guide: str, post_ids: Sequence[str]) -> Dict[str, Set[Tuple[str, str]]]:
    """paren_pairs by post, {post: its pairs} for every post asked (v10.13.9: the full pass's chunks read a post
    once)."""
    if not post_ids:
        return {}
    from insight_core.markx import tasks
    posts = tasks.load_posts(cur, post_ids)
    cur.execute("""SELECT post_id::text, span, type, entity_id::text FROM mx_mentions_now
                    WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""", (guide, list(post_ids)))
    by: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for pid, span, type_, eid in cur.fetchall():
        by[pid].append((fold(span), type_, eid))
    out: Dict[str, Set[Tuple[str, str]]] = {pid: set() for pid in post_ids}
    for pid, es in by.items():
        p = posts.get(pid)
        if p is None:
            continue
        text = bracket_fold(p.title + "\n" + p.text)
        for (sa, ta, ea), (sb, tb, eb) in itertools.permutations(es, 2):
            if ea != eb and sa and sb and ta == tb and ta not in ("place", "person") and f"{sa} ({sb})" in text:
                out[pid].add(pair(ea, eb))
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
    reasons: Tuple[str, ...] = ()          # 0130: every reason a `same` is held back for (reason is the first)
    second: Optional[Dict[str, Any]] = None   # 0130 A2: the second opinion's answer
    second_call: Optional[str] = None
    ask2: bool = False                      # 0130 A2: the second opinion is to be asked


_STATED: Dict[Tuple[int, str, str], bool] = {}


def stated_maker(cur: Any, bare: Ent, maker: str, guide: str) -> bool:
    """The bare name's maker is written in one of its posts (not only guessed: the maker-prefix rule's condition).
    Remembered for the cursor's transaction (one run)."""
    from insight_core.markx import tasks, validate
    k = (id(cur), bare.id, maker)
    if k not in _STATED:
        if len(_STATED) > 50000:
            _STATED.clear()
        cur.execute("SELECT DISTINCT post_id::text FROM mx_mentions_now WHERE guide = ANY(%s) AND entity_id = %s LIMIT 20",
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
    if family_version(book, a, b):
        auto.add("family_version")
    return auto, queue


def _vsig(e: Ent) -> Tuple:
    return N.version_part(e.hk) if N.has_version(e.hk) else N.version_part(e.pk)


def family_version(book: Book, a: Ent, b: Ent) -> bool:
    """0164: two versions of one family (their families' clusters are one: "Vela 5" of the family Vela and "Zentra
    Vela 5" of the family Zentra Vela once those merged) stating the same version, variant, size and build, in Haiku's
    fields and the parser's, and the same maker or one side none."""
    if a.level not in VERSION_LEVELS or b.level not in VERSION_LEVELS or not a.parent or not b.parent:
        return False
    if book.root(a.parent) != book.root(b.parent):
        return False
    if a.maker and b.maker and not same_maker(book, a.maker, b.maker):
        return False
    va, vb = _vsig(a), _vsig(b)
    return any(x is not None for x in va) and va == vb and N.version_part(a.pk) == N.version_part(b.pk)


def decide_pair(book: Book, p: Pooled, auto: Set[str], queue: Set[str], judge: Optional[Dict[str, Any]],
                call_id: Optional[str], second: Optional[Dict[str, Any]] = None,
                second_call: Optional[str] = None) -> Decision:
    """0119 A1's merge rules for one pool pair, before the chain guard. tier 'ask': Haiku hasn't answered yet.
    0130 A2: a held-back `same` whose reasons all have a second opinion on (entity_bands.json) is asked again
    (`ask2`); two agreeing `same` at or above the second opinion's bar merge ('second'), a disagreement stays queued
    with the second answer (`second`) for the queue to mark.
    0164: an org (or person) and a product family are never merged automatically, read on their clusters
    (`org_family`): such a merge goes to the queue ('type')."""
    d = _decide_pair(book, p, auto, queue, judge, call_id, second, second_call)
    if d.tier == "auto" and org_family(book, p.a, p.b):
        d.tier, d.reason = "queue", "type"
        d.reasons = tuple(dict.fromkeys(("type", "org_family") + tuple(d.reasons)))
    return d


def org_family(book: Book, a: str, b: str) -> bool:
    """0164: one side's cluster holds a product family and the other's an org or person (Book.sides)."""
    fa, oa = book.sides(book.cluster(book.root(a)))
    fb, ob = book.sides(book.cluster(book.root(b)))
    return bool((fa and ob) or (oa and fb))


def _decide_pair(book: Book, p: Pooled, auto: Set[str], queue: Set[str], judge: Optional[Dict[str, Any]],
                 call_id: Optional[str], second: Optional[Dict[str, Any]] = None,
                 second_call: Optional[str] = None) -> Decision:
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
    # every reason the `same` is held back for (0130: the first is the one shown; all of them decide the second opinion)
    reasons = sorted(queue)
    if vc is not None:
        reasons.append(soft_reason(book, a, b, literal=literal))
    if not first_auto(conf):
        reasons.append("below_bar")
    if not types_ok(a.type, b.type):
        reasons.append("type")
    if not reasons:
        return Decision(k, "auto", "haiku", conf, call_id, judge)
    d = Decision(k, "queue", reasons[0], conf, call_id, judge, reasons=tuple(reasons))
    if second_asked(reasons, conf):
        d.second = second
        if second is None:
            d.ask2 = True
        elif second_agrees(second):
            d.tier, d.reason, d.conf = "auto", "second", min(conf, float(second["confidence"]))
            d.second_call = second_call
        else:
            d.second_call = second_call
    return d


def chain_guard(book: Book, decisions: List[Decision]) -> None:
    """No automatic merge joins two clusters that already hold 2 or more names; a cluster holds at most MAX_CLUSTER
    names. The rejected ones go to the queue ('chain'), in order of confidence."""
    size: Dict[str, int] = {}
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
        for r in (ra, rb):
            if r not in size:   # a cluster's names before this chunk's merges (book.members(), one root at a time)
                size[r] = book.cluster_size(r) or 1
        sa, sb = size[ra], size[rb]
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


def _pick(eid: str, ms: Sequence[Tuple[str, str, str, str]], n: int, salt: int = 0,
          skip: Set[str] = frozenset()) -> List[Tuple[str, str]]:
    """Up to n (post, span) of one entity's mentions: distinct sources, subjects first, seeded by the entity."""
    ms = sorted(set(m for m in ms if m[0] not in skip))
    rnd = random.Random(int(hashlib.md5(eid.encode()).hexdigest(), 16) % 100000 + salt)
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
    return out


def examples(cur: Any, guide: str, eids: Sequence[str], n: int = 2, other: bool = False) -> Dict[str, List[str]]:
    """Up to n example posts of each entity: distinct sources, subjects first, picked by a seed of its key (stable).
    `other` (0130 A2, the second opinion): n other posts than the first question's, topped up with the first's when
    the entity has fewer."""
    from insight_core.markx import tasks
    if not eids:
        return {}
    cur.execute("""SELECT m.entity_id::text, m.post_id::text, m.span, m.role, p.source_id::text FROM mx_mentions_now m
                     JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = ANY(%s) AND m.entity_id = ANY(%s::uuid[])""", (guide, list(eids)))
    by: Dict[str, List[Tuple[str, str, str, str]]] = defaultdict(list)
    for eid, pid, span, role, src in cur.fetchall():
        by[eid].append((pid, span or "", role or "", src))
    picks: Dict[str, List[Tuple[str, str]]] = {}
    for eid, ms in by.items():
        first = _pick(eid, ms, n)
        if other:
            again = _pick(eid, ms, n, salt=1, skip={pid for pid, _ in first})
            first = again + [x for x in first if x[0] not in {pid for pid, _ in again}][:max(0, n - len(again))]
        picks[eid] = first
    posts = tasks.load_posts(cur, {pid for xs in picks.values() for pid, _ in xs})
    return {eid: [_ctx(posts[pid], span) for pid, span in xs if pid in posts] for eid, xs in picks.items()}


def spans(cur: Any, guide: str, eids: Sequence[str]) -> Dict[str, List[str]]:
    cur.execute("""SELECT entity_id::text, span, count(*) FROM mx_mentions_now WHERE guide = ANY(%s) AND entity_id = ANY(%s::uuid[])
                    GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2""", (guide, list(eids)))
    out: Dict[str, List[str]] = defaultdict(list)
    for eid, span, _ in cur.fetchall():
        out[eid].append(span)
    return out


def counts_of(cur: Any, guide: str, eids: Sequence[str]) -> Dict[str, int]:
    cur.execute("SELECT entity_id::text, count(DISTINCT post_id) FROM mx_mentions_now WHERE guide = ANY(%s) AND entity_id = ANY(%s::uuid[]) "
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


def close_queued(cur: Any, p: Tuple[str, str], note: Dict[str, Any]) -> int:
    """0130 A2: the open queue item of a pair the second opinion merged is closed (kept, with why), never deleted."""
    got = _savepoint(cur, """UPDATE mx_entity_queue SET closed_at = now(), evidence = COALESCE(evidence, '{}'::jsonb) || %s::jsonb
                              WHERE kind = 'alias' AND a = %s AND b = %s AND answer IS NULL AND closed_at IS NULL
                          RETURNING id""", (json.dumps(note, default=str), p[0], p[1]))
    return 0 if got is None or got is True else 1


def mark_second(cur: Any, p: Tuple[str, str], ev: Dict[str, Any]) -> bool:
    """0130 A2: an open queue item gets its second opinion (and whether it disagrees) when the answer comes later."""
    note = {k: ev.get(k) for k in ("second", "second_call", "disagree", "reasons", "band")}
    got = _savepoint(cur, """UPDATE mx_entity_queue SET evidence = COALESCE(evidence, '{}'::jsonb) || %s::jsonb
                              WHERE kind = 'alias' AND a = %s AND b = %s AND answer IS NULL AND closed_at IS NULL
                                AND NOT COALESCE(evidence, '{}'::jsonb) ? 'second'
                          RETURNING id""", (json.dumps(note, default=str), p[0], p[1]))
    return got is not None and got is not True


def merge(cur: Any, book: Book, a: str, b: str, *, by: str, automatic: bool, call_id: Any = None, queue_id: Any = None,
          run_id: Any = None, evidence: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """One merge: the smaller cluster's root redirects into the larger's (more names, then older). The redirect's id."""
    ra, rb = book.root(a), book.root(b)
    if ra == rb:
        return None
    def weight(r: str):
        e = book.ents[r]
        return (book.cluster_size(r), -(e.first_seen.timestamp() if e.first_seen else 0), r)
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
    alias2: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)  # 0130 A2: the second opinions


def asked(cur: Any) -> Asked:
    out = Asked()
    cur.execute("SELECT id::text, kind, a::text, b::text, status, input FROM mx_tasks WHERE kind IN ('alias', 'alias2', 'collide') "
                "ORDER BY created_at")
    for tid, kind, a, b, status, text in cur.fetchall():
        if kind == "alias2" and b is not None:
            out.alias2[pair(a, b)] = (tid, status)
        elif b is not None:
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


def _parts(ms: Sequence[Mention], size: int) -> List[List[Mention]]:
    """The mentions in chunks of about `size`, a post's mentions always in one chunk, in the order the posts first
    come (at least one chunk, maybe empty)."""
    by_post: Dict[str, List[Mention]] = {}
    for m in ms:
        by_post.setdefault(m.post_id, []).append(m)
    out: List[List[Mention]] = [[]]
    for got in by_post.values():
        if out[-1] and len(out[-1]) + len(got) > max(1, size):
            out.append([])
        out[-1].extend(got)
    return out


def stage(cur: Any, *, ask: Any, now: datetime, run_id: Any, full: bool, since: Optional[datetime] = None,
          link_limit: int = LINK_LIMIT, embedded_since: Optional[datetime] = None, after: Optional[str] = None,
          deadline: Optional[float] = None, chunk: int = SEED_CHUNK, link_after: Optional[str] = None,
          phase: Optional[str] = None, book: Optional[Book] = None, mention_chunk: Optional[int] = None,
          relink_page: Optional[int] = None) -> Dict[str, Any]:
    """The decision run's entities stage. `full`: the nightly pass (every mention relinked and checked, every entity
    pooled); else the mentions not linked yet and the pairs whose answers came since `since`. Returns its counts;
    `days` the days whose mentions it linked (the surges recount them), `posts_linked` the posts whose mentions it
    linked.

    Past `deadline` (a time.monotonic() value: the stage's own budget) it stops after the chunk it is in, on either
    pass, and what it leaves is the next run's (none of it is redone):
      - v10.13.9, the incremental pass (and a resumed full pass's first part) links, pools and decides the mentions not
        linked yet in chunks of about `mention_chunk` (a post's mentions in one chunk); the mentions it leaves stay
        unlinked, so the next run takes them (`incremental`: {done, parts, of, left}). The entities of every new key
        are made first, from all of the run's mentions of it; the answered pairs go with the first chunk, and the
        collisions of what the chunks linked (and of the answers since) come after the chunks.
      - the full pass relinks every mention in pages of `relink_page` posts in post id order (v10.13.9: `phase`
        'link', `link_after` the last post relinked), then (0128) pools and decides every entity in chunks of
        `chunk` seeds in id order, each chunk with its own "X (Y)" posts and collisions (phase 'pool', `after` the
        last seed decided). `full` in the counts says where ({done, phase, after, link_after, chunks, of}) and the
        next run resumes it there: it first links the mentions not linked yet, as an incremental pass does (with
        the answered pairs), then goes on. Without a deadline nothing stops."""
    from insight_core.markx import schemas
    import time as _time
    t0 = _time.monotonic()
    mention_chunk, relink_page = mention_chunk or MENTION_CHUNK, relink_page or RELINK_PAGE
    timing: Counter = Counter()

    def tick(step: str, since_t: float) -> float:
        t = _time.monotonic()
        timing[step] += t - since_t
        return t

    def past() -> bool:
        return deadline is not None and _time.monotonic() > deadline
    guide = schemas.mention_guides()   # 0133: the current set (mx_mentions_now), whichever guide it is
    _STATED.clear()
    t = _time.monotonic()
    book = book if book is not None else load_book(cur)
    w = Writer(cur, book, run_id)
    resume = full and (after is not None or link_after is not None or phase is not None)
    if full and not resume:
        phase = "link"
    elif full:
        phase = phase or ("pool" if after is not None else "link")
    out: Dict[str, Any] = {"kind": "full" if full else "incremental"}
    if hasattr(ask, "caps"):   # identity's questions are cheap and each waits otherwise for the nightly pass
        ask.caps.setdefault("alias", ALIAS_CAP)
        ask.caps.setdefault("alias2", ALIAS2_CAP)
        ask.caps.setdefault("collide", COLLIDE_CAP)
    got = asked(cur)
    answered_pairs: Set[Tuple[str, str]] = set()
    collide_since: Set[str] = set()
    if since is not None and (not full or resume):
        # the pairs whose Haiku answer came since the last run are decided again (with the first chunk)
        cur.execute("""SELECT DISTINCT t.a::text, t.b::text FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                        WHERE t.kind IN ('alias', 'alias2') AND c.created_at >= %s""", (since,))
        answered_pairs = {pair(a, b) for a, b in cur.fetchall()}
        # the keys whose collision answers came since the last run
        cur.execute("""SELECT DISTINCT t.a::text FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                        WHERE t.kind = 'collide' AND c.created_at >= %s""", (since,))
        collide_since = {r[0] for r in cur.fetchall()}
    vec_seeds: Set[str] = set()
    if not full or resume:   # the names whose vector came since the last run
        cur.execute("""SELECT t.a::text FROM mx_tasks t WHERE t.kind = 'embed_name' AND t.status = 'answered'
                          AND t.answered_at >= %s""", (embedded_since or since or now,))
        vec_seeds = {r[0] for r in cur.fetchall()}
    if full:   # every vector of the seeds to come
        cur.execute("SELECT entity_id::text FROM mx_entity_vectors WHERE %s::text IS NULL OR entity_id::text > %s",
                    (after if phase == "pool" else None,) * 2)
        vec_seeds |= {r[0] for r in cur.fetchall()}
    t = tick("load", t)

    link_out: Counter = Counter({"mentions": 0, "linked": 0, "entities_made": 0, "published": 0})
    touched_days: Set[Any] = set()
    posts_linked: Set[str] = set()
    facts: Dict[str, Any] = {"hf": None, "an": None}

    def link_part(ms: List[Mention]) -> Dict[Tuple[str, int], Optional[str]]:
        """Link a chunk's mentions (their keys' entities made already): what each was linked to before."""
        nonlocal t
        before = {(m.post_id, m.guide, m.n): m.entity_id for m in ms}
        got_ = relink(cur, book, ms)
        link_out["mentions"] += got_["mentions"]
        link_out["linked"] += got_["linked"]
        link_out["published"] += published(cur, book, w, ms)   # 0133: a document's `by`
        book.mentioned |= {m.entity_id for m in ms if m.entity_id}
        for m in ms:
            if before.get((m.post_id, m.guide, m.n)) != m.entity_id:
                posts_linked.add(m.post_id)
                if m.at:
                    touched_days.add(m.at.astimezone(timezone.utc).date())
        t = tick("link", t)
        return before

    def facts_for(post_ids: Optional[Sequence[str]]) -> None:
        """The handles and repository addresses the rules read: every post's once a run (after the run's first
        linking), then the posts each later chunk links, folded in."""
        nonlocal t
        if facts["hf"] is None or post_ids is None:
            facts["hf"], facts["an"] = handles(cur, guide), anchors(cur, book, guide)
        elif post_ids:
            handles(cur, guide, post_ids, into=facts["hf"])
            anchors(cur, book, guide, post_ids, into=facts["an"])
        t = tick("facts", t)

    by: Counter = Counter()
    tiers: Counter = Counter()
    asks_by: Counter = Counter()
    reasons: Counter = Counter()
    collide_out: Counter = Counter()
    decided: Set[Tuple[str, str]] = set()
    pooled: Set[Tuple[str, str]] = set()
    n = {"added": 0, "merged": 0, "queued": 0, "pairs": 0, "added2": 0, "cleared": 0, "marked": 0}

    seeded: Set[str] = set()
    collided: Set[str] = set()

    def decide_chunk(seeds: Set[str], parens: Set[Tuple[str, str]], first: bool, collide: Set[str]) -> None:
        """Pool the seeds' candidates, decide the pairs, ask what no rule decides; then the seeds' collisions. A seed
        an earlier chunk of the run pooled by its name is not pooled by its name again (an entity linked since finds
        it from its own side); its handles, addresses and "X (Y)" are (a chunk's posts may add some)."""
        nonlocal t
        hf, an = facts["hf"], facts["an"]
        named = seeds - seeded
        seeded.update(named)
        pool = Pool(book)
        pool_strings(pool, book, named)
        pool_family(pool, book, named)
        pool_makers(pool, book, named)
        hextra = pool_handles(pool, book, hf, seeds)
        anchored = pool_anchors(pool, an, seeds)
        t = tick("pool", t)
        for a, b, c in vector_neighbours(cur, book, sorted(s_ for s_ in vec_seeds & named if s_ in book.ents)):
            pool.add(a, b, "emb")
        t = tick("vectors", t)
        if first:
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
        pooled.update(pool.pairs)
        pairs = [p for p in sorted(pool.pairs.values(), key=lambda p: (p.a, p.b)) if (p.a, p.b) not in decided]
        pairs = pairs[:max(0, PAIR_LIMIT - n["pairs"])]
        n["pairs"] += len(pairs)
        decided.update((p.a, p.b) for p in pairs)
        answers = valid_answers(cur, [got.alias[(p.a, p.b)][0] for p in pairs if (p.a, p.b) in got.alias] +
                                [got.alias2[(p.a, p.b)][0] for p in pairs if (p.a, p.b) in got.alias2])
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
            second = call2 = None
            task2 = got.alias2.get((p.a, p.b))
            if task2 and answers.get(task2[0]):
                call2, second = answers[task2[0]][0]
            decisions.append(decide_pair(book, p, auto, queue, judge, call, second, call2))
        chain_guard(book, decisions)
        tiers.update(d.tier for d in decisions)
        asks_by.update(w_ for d in decisions if d.tier == "ask" for w_ in pool.pairs[d.pair].why)
        reasons.update(f"{d.tier}:{d.reason}" for d in decisions)
        t = tick("decide", t)
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
                n["added"] += 1
        # 0130 A2: the second opinions (alias-v1 with two other example posts) for the held-back `same` the bands allow
        need2 = [d for d in decisions if d.ask2 and d.pair not in got.alias2]
        if need2:
            ids = sorted({x for d in need2 for x in d.pair})
            ex, written, nposts = examples(cur, guide, ids, other=True), spans(cur, guide, ids), counts_of(cur, guide, ids)
            for d in need2:
                a, b = (book.ents[x] for x in d.pair)
                text = alias_input(show(a, written.get(a.id, [a.name]), nposts.get(a.id, 0), ex.get(a.id, [])),
                                   show(b, written.get(b.id, [b.name]), nposts.get(b.id, 0), ex.get(b.id, [])))
                if ask.added["alias2"] >= ALIAS2_CAP:
                    ask.waiting["alias2"] += 1
                    continue
                ask.answer("alias2", text, a=d.pair[0], b=d.pair[1])
                n["added2"] += 1
        t = tick("ask", t)
        for d in decisions:
            if d.tier == "auto":
                ev = {"rules": list(d.rules), "confidence": d.conf, "judge": d.judge}
                if d.reason == "second":
                    ev.update(second=d.second, second_call=d.second_call, reasons=list(d.reasons))
                rid = merge(cur, book, d.pair[0], d.pair[1], by=d.reason, automatic=True, call_id=d.call_id,
                            run_id=run_id, evidence=ev)
                if rid:
                    n["merged"] += 1
                    if d.reason == "second":
                        n["cleared"] += close_queued(cur, d.pair, {"closed_by": "second", "redirect": rid})
            elif d.tier == "queue":
                ev = {"rules": list(d.rules), "judge": d.judge, "reasons": list(d.reasons),
                      "band": band_of(d.conf) if d.judge else None}
                if d.second is not None:
                    ev.update(second=d.second, second_call=d.second_call, disagree=not second_agrees(d.second))
                elif d.ask2:
                    ev["second_asked"] = True
                if queue_item(cur, kind="alias", a=d.pair[0], b=d.pair[1], proposal="same", reason=d.reason, conf=d.conf,
                              evidence=ev, call_id=d.call_id, run_id=run_id):
                    n["queued"] += 1
                elif d.second is not None and mark_second(cur, d.pair, ev):
                    n["marked"] += 1
        t = tick("write", t)
        decide_collisions(collide)

    def decide_collisions(collide: Set[str]) -> None:
        nonlocal t
        collide = collide - collided   # an entity's collisions once a run
        collided.update(collide)
        if collide:
            collide_out.update(collisions(cur, book, ask=ask, guide=guide, run_id=run_id, got=got, seeds=collide))
        t = tick("collide", t)

    stopped = False
    comp_out: List[Optional[Dict[str, int]]] = []   # 0165 A: what the components rule did, a call a part
    # 1. the mentions not linked yet (the incremental pass; a resumed full pass's first part), in chunks
    if not full or resume:
        ms = _mentions(cur, guide, unlinked=True, limit=link_limit)
        if book.pins:   # the owner's splits since: the pinned mentions the run hasn't moved yet (first)
            cur.execute("""SELECT m.post_id::text, m.n FROM mx_mentions_now m JOIN mx_entity_pins p ON p.post_id = m.post_id
                             AND p.guide = m.guide AND p.n = m.n AND p.undone_at IS NULL
                            WHERE m.guide = ANY(%s) AND m.entity_id IS DISTINCT FROM p.entity_id""", (guide,))
            moved = {(p, n_) for p, n_ in cur.fetchall()}
            if moved:
                have = {(m.post_id, m.n) for m in ms}
                ms = [m for m in _mentions(cur, guide, unlinked=False) if (m.post_id, m.n) in moved - have] + ms
        t = tick("load", t)
        comp_out.append(link_components(cur, book, w, ms))   # 0165 A: components first (off until measured)
        make_entities(book, w, ms)   # every new key's entity, from all of the run's mentions of it
        link_out["entities_made"] += len(w.made)
        t = tick("link", t)
        parts = _parts(ms, mention_chunk)
        linked_seeds: Set[str] = set()
        done_parts = 0
        for k, part in enumerate(parts):
            link_part(part)
            facts_for(sorted({m.post_id for m in part}))
            paren_posts = sorted({m.post_id for m in part if m.entity_id})
            if k == 0 and answered_pairs:   # the posts naming both ends of an answered pair
                cur.execute("""SELECT DISTINCT a.post_id::text FROM mx_mentions_now a JOIN mx_mentions_now b
                                 ON b.post_id = a.post_id AND b.guide = a.guide
                                WHERE a.guide = ANY(%s) AND (a.entity_id, b.entity_id) IN
                                      (SELECT x, y FROM unnest(%s::uuid[], %s::uuid[]) u(x, y))""",
                            (guide, [p_[0] for p_ in answered_pairs], [p_[1] for p_ in answered_pairs]))
                paren_posts = sorted(set(paren_posts) | {r[0] for r in cur.fetchall()})
            parens = paren_pairs(cur, book, guide, paren_posts)
            t = tick("paren", t)
            seeds = {m.entity_id for m in part if m.entity_id}
            decide_chunk(seeds, parens, k == 0, set())
            linked_seeds |= seeds
            done_parts = k + 1
            if k + 1 < len(parts) and past():
                stopped = True
                break
        # the collisions of the entities linked (once their chunks are all linked), and of the answers since
        decide_collisions(linked_seeds | collide_since)
        left = sum(len(p_) for p_ in parts[done_parts:])
        out["incremental"] = {"done": not stopped, "parts": done_parts, "of": len(parts), "left": left}
    # 2. the full pass: every mention relinked, in pages of posts (post id order)
    moved_n = None
    if full and not stopped and phase == "link":
        moved_n = 0
        if link_after is None:   # the pass's start: every new key's entity from all of its mentions, as one link did
            made_before = len(w.made)
            make_entities(book, w, _mentions(cur, guide, unlinked=True))
            link_out["entities_made"] += len(w.made) - made_before
            t = tick("link", t)
        while True:
            cur.execute("""SELECT DISTINCT post_id::text FROM mx_mentions_now WHERE guide = ANY(%s)
                              AND (%s::uuid IS NULL OR post_id > %s::uuid) ORDER BY 1 LIMIT %s""",
                        (guide, link_after, link_after, relink_page + 1))
            ids = [r[0] for r in cur.fetchall()]
            more = len(ids) > relink_page
            ids = ids[:relink_page]
            ms = _mentions(cur, guide, unlinked=False, posts=ids)
            t = tick("load", t)
            made_before = len(w.made)
            comp_out.append(link_components(cur, book, w, ms))   # 0165 A
            make_entities(book, w, ms)
            link_out["entities_made"] += len(w.made) - made_before
            before = link_part(ms)
            moved_n += sum(1 for m in ms if before.get((m.post_id, m.guide, m.n))
                           and before[(m.post_id, m.guide, m.n)] != m.entity_id)
            link_after = ids[-1] if ids else link_after
            if not more:
                phase, after = "pool", None
            if past() or not more:
                stopped = past()   # the pages left (or the pool) are the next run's
                break
        out["check"] = {"same": moved_n == 0, "relinked": moved_n}
    # 3. the full pass: every entity pooled and decided, in chunks of seeds (id order)
    done_chunks, n_chunks, last = 0, None, after
    if full and not stopped:
        if moved_n is not None or facts["hf"] is None:
            facts_for(None)   # read after the relinking (it may move a mention to another entity)
        rest = sorted(e for e in book.ents if after is None or e > after)
        chunks = [rest[k:k + chunk] for k in range(0, len(rest), max(1, chunk))] or [[]]
        n_chunks = len(chunks)
        paren_of: Dict[str, Set[Tuple[str, str]]] = {}   # a post's "X (Y)" pairs, read once over the chunks
        for k, seeds_list in enumerate(chunks):
            seeds = set(seeds_list)
            posts: Set[str] = set()
            if seeds:   # the posts naming a seed
                cur.execute("""SELECT DISTINCT post_id::text FROM mx_mentions_now
                                WHERE guide = ANY(%s) AND entity_id = ANY(%s::uuid[])""", (guide, seeds_list))
                posts = {r[0] for r in cur.fetchall()}
                paren_of.update(paren_by_post(cur, book, guide, sorted(posts - set(paren_of))))
            parens = {p_ for pid in posts for p_ in paren_of.get(pid, ())}
            t = tick("paren", t)
            decide_chunk(seeds, parens, k == 0 and not resume, seeds)
            done_chunks = k + 1
            last = max(seeds_list) if seeds_list else last
            if k + 1 < len(chunks) and past():
                stopped = True
                break
    out["link"] = dict(link_out)
    out["pool"] = {"pairs": len(pooled), "by": dict(by)}
    out["decisions"] = dict(tiers)
    out["asks_by"] = dict(asks_by)
    out["reasons"] = dict(reasons)
    out["alias_asked"] = n["added"]
    out["second"] = {"asked": n["added2"], "cleared": n["cleared"], "marked": n["marked"]}
    out["merged"], out["queued"] = n["merged"], n["queued"]
    if full:
        done = not stopped
        out["full"] = {"done": done, "phase": None if done else phase,
                       "after": None if done or phase != "pool" else last,
                       "link_after": None if done or phase != "link" else link_after,
                       "chunks": done_chunks, "of": n_chunks, "resumed": resume}
    out["collide"] = {k: collide_out.get(k, 0) for k in ("odd", "asked", "asked_again", "waiting", "one_thing", "queued")}
    out["entities_made"] = len(w.made)
    got_comp = [c for c in comp_out if c is not None]
    out["components"] = ({k: sum(c.get(k, 0) for c in got_comp) for k in ("mentions", "made", "reparented", "by_span")}
                         if got_comp else {"off": True})
    out["timing"] = {k: round(v, 2) for k, v in sorted(timing.items())}
    out["seconds"] = round(_time.monotonic() - t0, 3)
    out["days"] = sorted(d.isoformat() for d in touched_days)
    out["posts_linked"] = sorted(posts_linked)
    return out


def collisions(cur: Any, book: Book, *, ask: Any, guide: str, run_id: Any, got: Asked,
               seeds: Optional[Set[str]]) -> Dict[str, int]:
    """The collision judge: keys (entities) whose mentions differ in type or stated maker, asked COLLIDE_RUNS times;
    a split two runs make goes to the queue. `seeds` None: every entity."""
    from insight_core.markx import tasks
    cur.execute(f"""SELECT entity_id::text, post_id::text, span, type, maker FROM mx_mentions_now
                     WHERE guide = ANY(%s) AND entity_id IS NOT NULL
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
    cur.execute("SELECT post_id::text, n, span, type, maker FROM mx_mentions_now WHERE guide = ANY(%s) AND entity_id = %s",
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
