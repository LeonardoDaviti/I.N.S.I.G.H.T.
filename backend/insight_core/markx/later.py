"""Long-lived stories (issue 0163 A): a story whose MAIN subject is one specific entity (a paper, document, dataset,
method, or one model or software release). Back in the news (back.py: a long-lived story may fire again AGAIN after
its last window) and the anchors engine (anchors.py: an anchor's subject) read it here.

  - main: the entity (its root through the merges, a pin first) is the subject mention (role `subject`, the current
    set) of at least MAIN_SHARE of the story's read members, of 2+ when 2+ were read, and no other subject of the
    story (any type; an unlinked name counts by its name key) is the subject of more members;
  - specific (`specific`): a paper, document, dataset (or method) always; a model or software only when the entity is
    one release (level version / variant / checkpoint, or a version, variant or build named); a family, an
    unversioned name and a `product` never.
The owner's "Stop following this story" rows (mx_later_stops) still stop a story (`stopped`).

Later developments (0163 B-D: the follow-up trigger, its back-judge questions, the Later rows on the story and entity
pages, their labels and the follow switch, and the anchors engine's Later half) were dropped in v10.18 (0203: 4 of 7
shown rows right, 6 of 167 candidates a development). mx_later keeps every row it ever wrote (keep everything).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import back, pairing
from insight_core.markx.back import _date

# 0180: the gates are Pairing's `develops` row (back.DEVELOPS); named here as before.
ALWAYS_TYPES = back.DEVELOPS.always_types       # specific by their type (method: once 0151's types add it)
RELEASE_TYPES = back.DEVELOPS.release_types     # specific only as one release (see `specific`)
LONG_TYPES = ALWAYS_TYPES + RELEASE_TYPES
RELEASE_LEVELS = back.DEVELOPS.release_levels   # an entity level that is one release
MAIN_SHARE = back.DEVELOPS.main_share   # provisional: the main subject is the subject of at least this share of members
AGAIN = back.DEVELOPS.again       # a long-lived story's back trigger may fire again this long after its last window


# ---- entities through the merges ----------------------------------------------------------------------------

class _Ids:
    """The current redirects and the pins of some posts: a mention's entity is its pin's, else its own, then its root."""

    def __init__(self, cur: Any) -> None:
        cur.execute("SELECT from_id::text, to_id::text FROM mx_entity_redirects WHERE undone_at IS NULL")
        self.redirect = dict(cur.fetchall())
        self.pins: Dict[Tuple[str, str, int], str] = {}

    def pin(self, cur: Any, post_ids: Sequence[str]) -> None:
        if post_ids:
            cur.execute("""SELECT post_id::text, guide, n, entity_id::text FROM mx_entity_pins
                            WHERE undone_at IS NULL AND post_id = ANY(%s::uuid[])""", (list(post_ids),))
            self.pins.update({(p, g, n): e for p, g, n, e in cur.fetchall()})

    def root(self, eid: Optional[str]) -> Optional[str]:
        seen: Set[str] = set()
        while eid in self.redirect and eid not in seen:
            seen.add(eid)
            eid = self.redirect[eid]
        return eid

    def of(self, post: str, guide: str, n: int, eid: Optional[str]) -> Optional[str]:
        return self.root(self.pins.get((post, guide, n), eid))

    def members(self, roots: Iterable[str]) -> Dict[str, str]:
        """{entity: its root} of the entities whose root is one of `roots` (the roots themselves too)."""
        roots = set(roots)
        out = {r: r for r in roots}
        for frm in self.redirect:
            r = self.root(frm)
            if r in roots:
                out[frm] = r
        return out


class _Ent:
    __slots__ = ("id", "type", "status", "name", "key", "level", "version", "variant", "build")

    def __init__(self, id: str, type: Optional[str], status: str, name: str, key: Optional[str], level: Optional[str],
                 version: Optional[str], variant: Optional[str], build: Optional[str]) -> None:
        self.id, self.type, self.status, self.name, self.key = id, type, status, name, key
        self.level, self.version, self.variant, self.build = level, version, variant, build


def _ents(cur: Any, ids: Iterable[str]) -> Dict[str, _Ent]:
    from insight_core.markx import schemas
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    cur.execute("""SELECT id::text, type, status, name, key, level, version, variant, build FROM mx_entities
                    WHERE id = ANY(%s::uuid[])""", (ids,))
    return {r[0]: _Ent(r[0], schemas.entity_type(r[1]), *r[2:]) for r in cur.fetchall()}


def specific(e: Optional[_Ent], mention_type: Optional[str] = None) -> bool:
    """Whether an entity is specific enough to keep a story listening (v10.13.12): a paper, a document, a dataset or
    a method always; a model or software only as one release: level version, variant or checkpoint, or a version, a
    variant or a build named (a family, an unversioned product or family name: never); any other type (product, org,
    person, event, ...) never. An entity marked not one is none. `mention_type`: the type its mentions give it, when
    the entity row has none."""
    if e is None:
        return False
    return pairing.specific(back.DEVELOPS, e.type or mention_type, level=e.level, version=e.version,
                            variant=e.variant, build=e.build, status=e.status)   # 0180: the develops row's gate


def _same_version(a: Optional[_Ent], b: Optional[_Ent]) -> bool:
    """Two entities of one name key at the same version (a duplicate not merged yet): their version, variant and build
    agree (none named on both counts as agreeing)."""
    if a is None or b is None or a.status == "not_entity":
        return False

    def f(v: Optional[str]) -> str:
        return (v or "").strip().casefold()
    return (f(a.version), f(a.variant), f(a.build)) == (f(b.version), f(b.variant), f(b.build))


# ---- the stories that keep listening ------------------------------------------------------------------------

class Long:
    """A long-lived story: its members (back._P), its main subject (a root entity), the share of its read members
    that subject is the subject of, the name keys that name it, its pages."""

    def __init__(self, id: str, members: List[Any], origin: Optional[str]) -> None:
        self.id, self.origin = id, origin
        self.members = sorted(members, key=lambda p: (p.at, p.id))
        self.first, self.last = self.members[0].at, self.members[-1].at
        self.sources = {p.src for p in self.members}
        self.mids = {p.id for p in self.members}
        self.subject: Optional[str] = None     # the main subject's root entity
        self.share = 0.0                       # the share of the read members it is the subject of
        self.keys: Set[str] = set()            # the name keys naming it (its own key, its members' mentions of it)
        self.pages: Set[str] = set()           # page keys (back's pages, by paper identifier where one)
        self.addresses: Set[str] = set()       # its subject's addresses, as page keys
        self.own: Set[str] = set()             # its members' own addresses (norm): a story source's repost of one

    @property
    def roots(self) -> Set[str]:
        return {self.subject} if self.subject else set()


page_key = pairing.page_key      # 'paper <ref>' for a paper's page, else back.norm: Pairing's page key (0166)


def _subject_rows(cur: Any, ids: Sequence[str]) -> List[Tuple]:
    """The subject mentions of `ids` in their current sets: (post, guide, n, entity, name key, type)."""
    from insight_core.markx import schemas
    if not ids:
        return []
    cur.execute("""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.name_key, m.name, m.type FROM mx_mentions_now m
                    WHERE m.post_id = ANY(%s::uuid[]) AND m.guide = ANY(%s) AND m.role = 'subject'""",
                (list(ids), schemas.mention_guides()))
    from insight_core.markx import tasks
    return [(p, g, n, e, k or tasks.name_key(name), schemas.entity_type(t)) for p, g, n, e, k, name, t in cur.fetchall()]


def stopped(cur: Any, story_ids: Optional[Sequence[str]] = None) -> Set[str]:
    """The stories the owner stopped following (their latest mx_later_stops row says stopped)."""
    where, params = ("WHERE story = ANY(%s::uuid[])", (list(story_ids),)) if story_ids is not None else ("", ())
    cur.execute(f"""SELECT DISTINCT ON (story) story::text, stopped FROM mx_later_stops {where}
                     ORDER BY story, created_at DESC, id DESC""", params)
    return {s for s, stop in cur.fetchall() if stop}


def long_lived(cur: Any, *, story_ids: Optional[Sequence[str]] = None, ids: Optional[_Ids] = None
               ) -> Dict[str, Long]:
    """{story: Long} of Mark IX's stories of 2+ sources whose main subject is one specific entity (the module's A; of
    `story_ids`, else all; stopped ones too: the caller drops them)."""
    where, params = ("WHERE sp.story_id = ANY(%s::uuid[])", (list(story_ids),)) if story_ids is not None else ("", ())
    if story_ids is not None and not story_ids:
        return {}
    cur.execute(f"""SELECT sp.story_id::text, p.id::text, p.source_id::text, {_date()}, p.url, st.origin_url,
                           s.platform = 'saved'
                      FROM story_posts sp JOIN stories st ON st.id = sp.story_id JOIN posts p ON p.id = sp.post_id
                      JOIN sources s ON s.id = p.source_id {where}""",
                params)
    by: Dict[str, List[Any]] = defaultdict(list)
    origin: Dict[str, Optional[str]] = {}
    for sid, pid, src, at, url, o, saved in cur.fetchall():
        if at is not None:
            by[sid].append(back._P(pid, src, at, url, bool(saved)))   # 0189: a saved page is no voice of the story
            origin[sid] = o
    by = {sid: ms for sid, ms in by.items() if back.sources(ms) >= back.MIN_SOURCES}
    return mains(cur, by, origin, ids=ids)


def mains(cur: Any, by: Dict[str, List[Any]], origin: Dict[str, Optional[str]], *, ids: Optional[_Ids] = None
          ) -> Dict[str, Long]:
    """{story: Long} of the stories `by` ({id: its members, back._P}) whose main subject is one specific entity (the
    module's A, whatever the story is: 0180's anchors give Mark X stories too). `origin`: {id: its origin page}."""
    if not by:
        return {}
    mids = sorted({m.id for ms in by.values() for m in ms})
    ids = ids or _Ids(cur)
    ids.pin(cur, mids)
    cur.execute("SELECT DISTINCT post_id::text FROM mx_mention_sets WHERE post_id = ANY(%s::uuid[])", (mids,))
    read = {r[0] for r in cur.fetchall()}
    subj: Dict[str, List[Tuple[Optional[str], Optional[str], Optional[str]]]] = defaultdict(list)   # post: (root, key, type)
    for pid, g, n, eid, key, t in _subject_rows(cur, mids):
        subj[pid].append((ids.of(pid, g, n, eid), key or None, t))
    ents = _ents(cur, {r for xs in subj.values() for r, _, _ in xs if r})
    out: Dict[str, Long] = {}
    for sid, ms in by.items():
        n_read = sum(m.id in read for m in ms)
        if not n_read:
            continue
        key_root: Dict[str, str] = {}      # a name some member's mention links to an entity: that entity, unlinked too
        for m in ms:
            for r, k, _t in subj.get(m.id, ()):
                if r and k:
                    key_root.setdefault(k, r)
        count: Counter = Counter()
        keys_of: Dict[str, Set[str]] = defaultdict(set)
        type_of: Dict[str, Optional[str]] = {}
        for m in ms:
            names: Set[str] = set()
            for r, k, t in subj.get(m.id, ()):
                r = r or (key_root.get(k) if k else None)
                ident = r or (f"key {k}" if k else None)
                if not ident:
                    continue
                names.add(ident)
                if r:
                    type_of.setdefault(r, t)
                    if k:
                        keys_of[r].add(k)
            count.update(names)
        if not count:
            continue
        top = max(count.values())
        need = max(math.ceil(MAIN_SHARE * n_read), 2 if n_read >= 2 else 1)
        mains = [r for r, c in count.items() if c == top and c >= need and not r.startswith("key ")
                 and specific(ents.get(r), type_of.get(r))]
        if not mains:
            continue
        # ties among specific subjects: a paper, document, dataset or method before a release, then the id
        r = min(mains, key=lambda x: ((ents[x].type or type_of.get(x)) not in ALWAYS_TYPES, x))
        s = Long(sid, ms, origin.get(sid))
        s.subject, s.share = r, top / n_read
        s.keys = keys_of[r] | ({ents[r].key} if ents[r].key else set())
        out[sid] = s
    return out
