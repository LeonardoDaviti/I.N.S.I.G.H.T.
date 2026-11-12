"""Later developments, in Shadow (issue 0163, building 0136; tightened in v10.13.12): a story about one specific paper,
document, dataset, model release or software release keeps gathering the posts that follow it up, at any age, one
source at a time. Shadow: mx_* rows only (mx_later, mx_later_stops, mx_tasks, mx_labels); Mark IX is only read, and
nothing here reaches any News.

  A. **Long-lived stories** (RULE 2, v10.13.12). A Mark IX story of 2+ sources (as back's) whose MAIN subject is one
     specific entity:
       - main: the entity (its root through the merges, a pin first) is the subject mention (role `subject`, the
         current set) of at least MAIN_SHARE of its read members, of 2+ when 2+ were read, and no other subject of
         the story (any type; an unlinked name counts by its name key) is the subject of more members;
       - specific (`specific`): a paper, document, dataset (or method) always; a model or software only when the
         entity is one release (level version / variant / checkpoint, or a version, variant or build named); a
         family, an unversioned name and a `product` never.
     Other stories keep back's once-only trigger. The owner's "Stop following this story" (a row in mx_later_stops,
     reversible) stops both its Later rows and its second waves.
  B. **The follow-up trigger** (no model; one source is enough; no age limit). A post dated after the story's last
     post, not a member, not saved, not a story source's repost of a member's page, is a Later candidate when
       E  its own subject mention is the story's subject: the same entity (root), or the same name key at the same
          version (an unlinked mention, or a duplicate entity not merged yet). A later version of the family is its
          own story, never a development (RULE 1's family match is gone);
       L  it links (or is) one of the story's own pages (back's: members' addresses, pages 2+ members link, the
          origin; hubs out) or an address of the subject entity (mx_entity_addresses, read through the merges, while
          its post still names it). Pages compare by back.norm, and a paper's pages by its identifier.
     and then
       one story: a post that qualifies for several stories of one subject is kept under the best one only (the
          highest main-subject share, then the latest last post, then the id); a member of a long-lived story of the
          subject is under that story already, and is no follow-up of another;
       quiet: at most QUIET_MAX distinct sources named the subject as their subject in the QUIET_DAYS before the post
          (the story's members and the post itself not counted). A subject that never goes quiet never fires. One
          grouped read of the subject's mentions over the run's window, not one per pair.
     V (vectors) alone never: that finds "same topic", which the back judge calls related.
     Incremental: each run reads the posts dated since its last clock less MARGIN, oldest first, at most PER_RUN;
     a run that hits the cap keeps the last post it read, and the next one reads on past it (date, id). The clock
     names its RULE: the first run of a rule (another rule's clock, or none) reads FIRST_SCAN_DAYS back.
  C. **The judge**: the frozen `back` guide (back-v1), its input back.render (the story's 4 earliest posts, then the
     new post), RUNS=3, the majority. Planned after back's own questions under the same cap (Config.back_open:
     open or leased back tasks), rows of the current RULE only. Every asked row's verdict is stored (settle); only
     `development` shows as one.
  D. **Shown** on the story's page ("Later") and the subject's entity page ("Later developments"), newest first,
     with the owner's label buttons: the current RULE's rows, an older rule's only with `all` (kept, never deleted;
     neither counted nor in the precision otherwise). Not on News: NEWS_KEY (an mx_settings flag, off) is what will
     gate it once measured.
  Also: a long-lived story's back trigger may fire again AGAIN after its last mx_back window (back.stories).

Dates are the reader's: COALESCE(surfaced_at, published_at, fetched_at) (back's).
"""
from __future__ import annotations

import bisect
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import back, pairing
from insight_core.markx.back import _date, norm

KIND = back.KIND
RULE = 2                          # v10.13.12's tightened rule; the rows v10.13.11's loose one found are rule 1 (0103)
ALWAYS_TYPES = ("paper", "document", "dataset", "method")   # specific by their type (method: once 0151's types add it)
RELEASE_TYPES = ("model", "software")                       # specific only as one release (see `specific`)
LONG_TYPES = ALWAYS_TYPES + RELEASE_TYPES
RELEASE_LEVELS = ("version", "variant", "checkpoint")       # an entity level that is one release
MAIN_SHARE = 0.5                  # provisional: the main subject is the subject of at least this share of read members
QUIET_DAYS = 14                   # provisional: in the days before a post ...
QUIET_MAX = 2                     # ... at most this many distinct sources named the subject as their subject
QUIET_FOR_LINKS = True            # provisional: the quiet rule holds for L hits too (a popular release's page is linked
                                  # about as often as it is named)
AGAIN = timedelta(days=30)        # a long-lived story's back trigger may fire again this long after its last window
FIRST_SCAN_DAYS = 30              # the first run of a rule reads this far back ...
PER_RUN = 5000                    # ... and every run at most this many posts, oldest first
MARGIN = timedelta(hours=1)
SETTLE = 500                      # the answered rows a run stores verdicts of, at most
SINCE_KEY = "later_since"
NEWS_KEY = "later_news"           # 0163 D: Later on News, off until measured (nothing reads it as on yet)
LABELS = back.LABELS
ANSWERS = back.ANSWERS
TRIG_ORDER = ("E", "L")


def on_news(cur: Any) -> bool:
    """Whether Later rows may reach News (NEWS_KEY; off by default, and nothing shows them there yet)."""
    from insight_core.markx import repo
    return bool(repo.get_setting(cur, NEWS_KEY, default=False))


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


def _blank(v: Optional[str]) -> bool:
    return not (v or "").strip()


def specific(e: Optional[_Ent], mention_type: Optional[str] = None) -> bool:
    """Whether an entity is specific enough to keep a story listening (v10.13.12): a paper, a document, a dataset or
    a method always; a model or software only as one release: level version, variant or checkpoint, or a version, a
    variant or a build named (a family, an unversioned product or family name: never); any other type (product, org,
    person, event, ...) never. An entity marked not one is none. `mention_type`: the type its mentions give it, when
    the entity row has none."""
    if e is None or e.status == "not_entity":
        return False
    t = e.type or mention_type
    if t in ALWAYS_TYPES:
        return True
    if t not in RELEASE_TYPES or e.level == "family":
        return False
    return e.level in RELEASE_LEVELS or not (_blank(e.version) and _blank(e.variant) and _blank(e.build))


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


def long_lived(cur: Any, *, story_ids: Optional[Sequence[str]] = None, ids: Optional[_Ids] = None,
               with_pages: bool = False) -> Dict[str, Long]:
    """{story: Long} of Mark IX's stories of 2+ sources whose main subject is one specific entity (the module's A; of
    `story_ids`, else all; stopped ones too: the caller drops them). `with_pages`: their pages and their subjects'
    addresses as well."""
    where, params = ("WHERE sp.story_id = ANY(%s::uuid[])", (list(story_ids),)) if story_ids is not None else ("", ())
    if story_ids is not None and not story_ids:
        return {}
    cur.execute(f"""SELECT sp.story_id::text, p.id::text, p.source_id::text, {_date()}, p.url, st.origin_url
                      FROM story_posts sp JOIN stories st ON st.id = sp.story_id JOIN posts p ON p.id = sp.post_id {where}""",
                params)
    by: Dict[str, List[Any]] = defaultdict(list)
    origin: Dict[str, Optional[str]] = {}
    for sid, pid, src, at, url, o in cur.fetchall():
        if at is not None:
            by[sid].append(back._P(pid, src, at, url, False))
            origin[sid] = o
    by = {sid: ms for sid, ms in by.items() if len({m.src for m in ms}) >= back.MIN_SOURCES}
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
    if with_pages and out:
        _pages(cur, out, ids)
    return out


def _raw_links(cur: Any, ids: Sequence[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = defaultdict(list)
    if ids:
        cur.execute("SELECT post_id::text, target_url FROM post_links WHERE NOT boilerplate AND post_id = ANY(%s::uuid[])",
                    (list(ids),))
        for pid, u in cur.fetchall():
            out[pid].append(u)
    return out


def _pages(cur: Any, stories: Dict[str, Long], ids: _Ids) -> None:
    """Each story's pages (back's rule, compared by page_key) and its subject's current addresses."""
    mids = sorted({m.id for s in stories.values() for m in s.members})
    links = _raw_links(cur, mids)
    for s in stories.values():
        count: Counter = Counter()
        for m in s.members:
            count.update({k for k in map(page_key, links.get(m.id, ())) if k})
        s.own = {n for n in (norm(m.url) for m in s.members) if n}
        own = {page_key(m.url) for m in s.members} | {page_key(s.origin)}
        s.pages = {k for k in own | {k for k, c in count.items() if c >= 2} if k}
    roots = {r for s in stories.values() for r in s.roots}
    if not roots:
        return
    members = ids.members(roots)
    cur.execute("SELECT entity_id::text, url, post_id::text FROM mx_entity_addresses WHERE entity_id = ANY(%s::uuid[])",
                (sorted(members),))
    rows = cur.fetchall()
    posts = sorted({p for _, _, p in rows if p})
    named: Set[Tuple[str, str]] = set()
    if posts:   # an address counts while its post still names the entity in its current set (entity_addresses' rule)
        from insight_core.markx import schemas
        ids.pin(cur, posts)
        cur.execute("""SELECT post_id::text, guide, n, entity_id::text FROM mx_mentions_now
                        WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""",
                    (schemas.mention_guides(), posts))
        named = {(p, ids.of(p, g, n, e)) for p, g, n, e in cur.fetchall()}
    addr: Dict[str, Set[str]] = defaultdict(set)
    for eid, url, pid in rows:
        root = members.get(eid)
        if root and (not pid or (pid, root) in named):
            k = page_key(url)
            if k:
                addr[root].add(k)
    for s in stories.values():
        s.addresses = set(addr.get(s.subject, set())) if s.subject else set()


# ---- the trigger ---------------------------------------------------------------------------------------------

def _recent(cur: Any, since: datetime, now: datetime, limit: int,
            after: Optional[str] = None) -> Tuple[List[Any], bool]:
    """The posts dated in [since, now] (past post `after` at `since` itself when given: a capped run's resume),
    oldest first, at most `limit` (and whether there were more)."""
    from insight_core.utils.post_links import source_kind
    resume = f"AND ({_date()}, p.id) > (%s::timestamptz, %s::uuid)" if after else ""
    params = (since, now) + ((since, after) if after else ()) + (limit + 1,)
    cur.execute(f"""SELECT p.id::text, p.source_id::text, {_date()} AS at, p.url, s.platform, s.handle_or_url
                      FROM posts p JOIN sources s ON s.id = p.source_id
                     WHERE {_date()} >= %s AND {_date()} <= %s {resume} ORDER BY at, p.id LIMIT %s""", params)
    rows = cur.fetchall()
    more = len(rows) > limit
    return [back._P(pid, src, at, url, source_kind(pl, h) == "saved") for pid, src, at, url, pl, h in rows[:limit]], more


def _namings(cur: Any, ids: _Ids, subjects: Dict[str, Set[str]], lo: datetime, hi: datetime
             ) -> Dict[str, List[Tuple[datetime, str, str]]]:
    """{subject root: [(date, post, source)], sorted} of the posts dated in [lo, hi) whose current subject mention
    names it (by entity through the merges and pins, or, unlinked, by one of its name keys `subjects[root]`): one
    grouped read for the whole run (the quiet rule)."""
    from insight_core.markx import schemas
    if not subjects:
        return {}
    members = ids.members(subjects)
    key_of: Dict[str, Set[str]] = defaultdict(set)
    for r, ks in subjects.items():
        for k in ks:
            key_of[k].add(r)
    cur.execute("SELECT DISTINCT post_id::text FROM mx_entity_pins WHERE undone_at IS NULL AND entity_id = ANY(%s::uuid[])",
                (sorted(members),))
    pinned = [r[0] for r in cur.fetchall()]
    cur.execute(f"""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.name_key, p.source_id::text, {_date()}
                      FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                     WHERE m.role = 'subject' AND m.guide = ANY(%s)
                       AND (m.entity_id = ANY(%s::uuid[]) OR (m.entity_id IS NULL AND m.name_key = ANY(%s))
                            OR m.post_id = ANY(%s::uuid[]))
                       AND {_date()} >= %s AND {_date()} < %s""",
                (schemas.mention_guides(), sorted(members), sorted(key_of), pinned, lo, hi))
    rows = cur.fetchall()
    ids.pin(cur, sorted({r[0] for r in rows}))
    out: Dict[str, Set[Tuple[datetime, str, str]]] = defaultdict(set)
    for pid, g, n, eid, key, src, at in rows:
        r = ids.of(pid, g, n, eid)
        for x in ({r} if r in subjects else (key_of.get(key, set()) if r is None and key else set())):
            out[x].add((at, pid, src))
    return {r: sorted(v) for r, v in out.items()}


def quiet(namings: Sequence[Tuple[datetime, str, str]], at: datetime, post: str, skip: Set[str]) -> bool:
    """Whether at most QUIET_MAX distinct sources named the subject in the QUIET_DAYS before `at` (`namings` sorted
    [(date, post, source)]; `post` itself and the posts of `skip`, the story's members, not counted)."""
    lo = bisect.bisect_left(namings, (at - timedelta(days=QUIET_DAYS),))
    hi = bisect.bisect_left(namings, (at,))
    return len({src for _t, pid, src in namings[lo:hi] if pid != post and pid not in skip}) <= QUIET_MAX


def _rank(s: Long) -> Tuple:
    """The order among the stories of one subject (one story per post and subject): the highest main-subject share,
    the latest last post, the id."""
    return (-s.share, -s.last.timestamp(), s.id)


def find(cur: Any, *, now: datetime, since: datetime, limit: int = PER_RUN,
         after: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The Later candidates the posts dated in [since, now] make (at most `limit` posts, oldest first; past `after`
    at `since` when resuming): ([{story, post, members, entity, trig, post_at, last_at}], the clock the next run
    reads from: {at, after, rule} — `after` the last post read when the cap stopped it, else None). Nothing is
    written."""
    recent, more = _recent(cur, since, now, limit, after)
    clock = ({"at": recent[-1].at.isoformat(), "after": recent[-1].id} if more
             else {"at": now.isoformat(), "after": None})
    clock["rule"] = RULE
    recent = [p for p in recent if not p.saved]
    if not recent:
        return [], clock
    ids = _Ids(cur)
    st = long_lived(cur, ids=ids, with_pages=True)
    for sid in stopped(cur, sorted(st)):
        st.pop(sid, None)
    if not st:
        return [], clock
    first_last = min(s.last for s in st.values())
    recent = [p for p in recent if p.at > first_last]
    if not recent:
        return [], clock
    rids = [p.id for p in recent]
    ids.pin(cur, rids)
    p_subj: Dict[str, List[Tuple[Optional[str], Optional[str]]]] = defaultdict(list)
    for pid, g, n, eid, key, _t in _subject_rows(cur, rids):
        p_subj[pid].append((ids.of(pid, g, n, eid), key or None))
    by_root: Dict[str, Set[str]] = defaultdict(set)
    by_key: Dict[str, Set[str]] = defaultdict(set)
    by_page: Dict[str, Set[str]] = defaultdict(set)      # story pages (hubs to take out)
    by_addr: Dict[str, Set[str]] = defaultdict(set)      # subject addresses
    for s in st.values():
        by_root[s.subject].add(s.id)
        for k in s.keys:
            by_key[k].add(s.id)
        for k in s.pages:
            by_page[k].add(s.id)
        for k in s.addresses:
            by_addr[k].add(s.id)
    dupes = {r for xs in p_subj.values() for r, k in xs if r and r not in by_root and k in by_key}
    ents = _ents(cur, dupes | set(by_root))
    links = _raw_links(cur, rids)
    hits: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    page_hits: Dict[Tuple[str, str], Set[str]] = defaultdict(set)   # (story, post): the story pages it matched
    for p in recent:
        for r, k in p_subj.get(p.id, ()):
            for sid in by_root.get(r, ()) if r else ():
                hits[(sid, p.id)].add("E")
            for sid in by_key.get(k, ()) if k else ():   # its name key: unlinked, or a duplicate at the same version
                if r is None or (r != st[sid].subject and _same_version(ents.get(r), ents.get(st[sid].subject))):
                    hits[(sid, p.id)].add("E")
        for k in {k for k in map(page_key, [p.url] + links.get(p.id, [])) if k}:
            for sid in by_addr.get(k, ()):
                hits[(sid, p.id)].add("L")
            for sid in by_page.get(k, ()):
                page_hits[(sid, p.id)].add(k)
    if page_hits:   # back's hubs: a page linked in HUB_WEEKS+ weeks is no story page (its forms as back reads them)
        plain = {k for ks in page_hits.values() for k in ks if not k.startswith("paper ")}
        hub = back.hubs(cur, plain)
        for (sid, pid), ks in page_hits.items():
            if ks - hub:
                hits[(sid, pid)].add("L")
    at = {p.id: p for p in recent}
    housed = {(m, s.subject) for s in st.values() for m in s.mids if m in at}   # posts in a story of the subject already
    best: Dict[Tuple[str, str], Tuple[str, Set[str]]] = {}   # (post, subject): its one story, and the triggers
    for (sid, pid), trig in hits.items():
        s, p = st[sid], at[pid]
        if p.at <= s.last or pid in s.mids or (pid, s.subject) in housed:
            continue   # one story per post and subject: a member of a story of this subject has its story
        if p.src in s.sources and (norm(p.url) in s.own or s.own & {norm(u) for u in links.get(pid, ())}):
            continue   # the story's own source again carrying a member's page: a retelling, not a follow-up
        k = (pid, s.subject)
        if k not in best or _rank(s) < _rank(st[best[k][0]]):
            best[k] = (sid, trig)
    if not best:
        return [], clock

    def checked(trig: Set[str]) -> bool:
        return QUIET_FOR_LINKS or "E" in trig

    need = {r: st[sid].keys for (_pid, r), (sid, trig) in best.items() if checked(trig)}
    times = [at[pid].at for (pid, _r) in best]
    named = _namings(cur, ids, need, min(times) - timedelta(days=QUIET_DAYS), max(times)) if need else {}
    out = []
    for (pid, r), (sid, trig) in sorted(best.items(), key=lambda kv: (at[kv[0][0]].at, kv[1][0], kv[0][0])):
        s, p = st[sid], at[pid]
        if checked(trig) and not quiet(named.get(r, []), p.at, pid, s.mids):
            continue   # the subject is not quiet before it: chatter, not a follow-up (a popular subject never fires)
        out.append({"story": sid, "post": pid, "members": [m.id for m in s.members], "entity": r,
                    "trig": [t for t in TRIG_ORDER if t in trig], "post_at": p.at, "last_at": s.last})
    return out, clock


def write(cur: Any, found: Sequence[Dict[str, Any]], *, run_id: Any = None, now: Optional[datetime] = None) -> int:
    """The new Later rows of the current RULE (one a story, post and rule): how many were new."""
    added = 0
    for c in found:
        cur.execute("""INSERT INTO mx_later (story, post, rule, members, entity, trig, post_at, last_at, run_id, found_at)
                       VALUES (%s, %s, %s, %s::uuid[], %s, %s, %s, %s, %s, COALESCE(%s, now()))
                       ON CONFLICT (story, post, rule) DO NOTHING""",
                    (c["story"], c["post"], RULE, c["members"], c["entity"], c["trig"], c["post_at"], c["last_at"],
                     run_id, now))
        added += cur.rowcount
    return added


# ---- the judge -----------------------------------------------------------------------------------------------

def plan(cur: Any, *, open_cap: int = back.OPEN, now: Optional[datetime] = None, **_kw: Any) -> int:
    """A back question for each Later row of the current RULE with none, the newest post first, while fewer than
    `open_cap` back tasks wait (open or leased; back's cap, shared). An older rule's rows are never planned. How many
    were added."""
    from insight_core.markx import tasks
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = %s AND status IN ('open', 'leased')", (KIND,))
    room = open_cap - cur.fetchone()[0]
    if room <= 0:
        return 0
    cur.execute("""SELECT id::text, story::text, members::text[], post::text, post_at FROM mx_later
                    WHERE task_id IS NULL AND rule = %s ORDER BY post_at DESC, id LIMIT %s""", (RULE, room))
    picks = cur.fetchall()
    if not picks:
        return 0
    posts = tasks.load_posts(cur, {x for _, _, ms, p, _ in picks for x in list(ms) + [p]})
    now = now or datetime.now(timezone.utc)
    added = 0
    for lid, story, ms, pid, at in picks:
        old = sorted((posts[m] for m in ms if m in posts), key=lambda p: (p.at, p.id))
        if not old or pid not in posts:
            continue
        age = max(0, int((now - at).total_seconds() // 86400))
        tid, new_task = tasks.add(cur, KIND, back.render(old, [posts[pid]]), a=story, priority=age)
        cur.execute("UPDATE mx_later SET task_id = %s WHERE id = %s", (tid, lid))
        added += bool(new_task)
    return added


def settle(cur: Any, *, now: Optional[datetime] = None, limit: int = SETTLE) -> int:
    """Store the verdict of each asked row whose task has RUNS valid answers (at most `limit`; an older rule's asked
    rows too: their answers are kept): how many."""
    cur.execute("""SELECT id::text, task_id::text FROM mx_later WHERE task_id IS NOT NULL AND verdict IS NULL
                    ORDER BY post_at DESC LIMIT %s""", (limit,))
    rows = cur.fetchall()
    answers = back._answers(cur, sorted({t for _, t in rows}))
    n = 0
    for lid, tid in rows:
        v = back.verdict(answers.get(tid, []))
        if v is not None:
            cur.execute("UPDATE mx_later SET verdict = %s, runs = %s, judged_at = COALESCE(%s, now()) WHERE id = %s",
                        (v["relation"], v["runs"], now, lid))
            n += 1
    return n


# ---- the decision run's stage ----------------------------------------------------------------------------------

def stage(cur: Any, *, now: datetime, run_id: Any = None, open_cap: int = back.OPEN,
          limit: int = PER_RUN) -> Dict[str, Any]:
    """The decision run's part (after back's): the Later rows of the posts since the last clock (less MARGIN; a
    capped run's resume reads on past its last post, no margin; a clock of another RULE, or none, is a first run:
    FIRST_SCAN_DAYS back), the back questions for them under back's cap, the verdicts answered since. Its counts."""
    from insight_core.markx import repo
    t0 = time.monotonic()
    last = repo.get_setting(cur, SINCE_KEY, default=None) or {}
    if last.get("rule") != RULE:
        last = {}
    after = last.get("after")
    if last.get("at"):
        since = datetime.fromisoformat(last["at"]) - (timedelta(0) if after else MARGIN)
    else:
        since = now - timedelta(days=FIRST_SCAN_DAYS)
    found, clock = find(cur, now=now, since=since, limit=limit, after=after)
    out = {"rule": RULE, "since": since.isoformat(), "clock": clock, "found": len(found),
           "added": write(cur, found, run_id=run_id, now=now), "planned": plan(cur, open_cap=open_cap, now=now),
           "settled": settle(cur, now=now)}
    repo.set_setting(cur, SINCE_KEY, clock)
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out


# ---- the rows shown (Shadow) ------------------------------------------------------------------------------------

def _labels(cur: Any, ids: Sequence[str]) -> Dict[str, Optional[str]]:
    if not ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (a) a::text, answer FROM mx_labels
                    WHERE item_kind = 'later' AND labeller = 'owner' AND a = ANY(%s::uuid[])
                    ORDER BY a, created_at DESC, ctid DESC""", (list(ids),))
    return {a: (None if ans == "undo" else ans) for a, ans in cur.fetchall()}


def precision(cur: Any, *, all: bool = False) -> Dict[str, Any]:
    """The owner's labels on Later rows of the current RULE (`all`: of every rule): {labelled, development,
    precision (None before the first)}."""
    cur.execute("""SELECT DISTINCT ON (l.a) l.a::text, l.answer FROM mx_labels l JOIN mx_later r ON r.id = l.a
                    WHERE l.item_kind = 'later' AND l.labeller = 'owner' AND (%s OR r.rule = %s)
                    ORDER BY l.a, l.created_at DESC, l.ctid DESC""", (all, RULE))
    marks = [ans for _, ans in cur.fetchall() if ans != "undo"]
    dev = sum(a == "development" for a in marks)
    return {"labelled": len(marks), "development": dev, "precision": round(dev / len(marks), 4) if marks else None}


_COLS = "id::text, story::text, post::text, entity::text, trig, post_at, last_at, task_id::text, verdict, runs, rule"


def _items(cur: Any, rows: Sequence[Tuple]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Rows (_COLS) as shown, newest post first, with live verdicts for answered rows not yet settled."""
    late = back._answers(cur, sorted({r[7] for r in rows if r[7] and r[8] is None}))
    shown = back._shown_posts(cur, {r[2] for r in rows} | {r[1] for r in rows})
    names = {e.id: e.name for e in _ents(cur, {r[3] for r in rows if r[3]}).values()}
    marks = _labels(cur, [r[0] for r in rows])
    counts: Counter = Counter(candidates=len(rows))
    items = []
    for lid, story, pid, ent, trig, at, last, tid, verdict, runs, rule in rows:
        if verdict is None and tid:
            v = back.verdict(late.get(tid, []))
            verdict, runs = (v["relation"], v["runs"]) if v else (None, None)
        counts[verdict or "waiting"] += 1
        p = shown.get(pid) or {}
        items.append({"id": lid, "story": story, "headline": (shown.get(story) or {}).get("title"), "post": pid,
                      "title": p.get("title"), "url": p.get("url"), "source": p.get("source"), "at": back._iso(at),
                      "days_after": max(0, (at - last).days), "trig": list(trig), "entity": ent,
                      "entity_name": names.get(ent), "verdict": verdict, "runs": list(runs or []),
                      "label": marks.get(lid), "rule": rule})
    return items, dict(counts)


def _ix_stories(cur: Any, story_id: str) -> List[str]:
    """The Mark IX stories a story page stands for: the id itself when it is one, and, for a Mark X story, the Mark
    IX stories of its current members."""
    cur.execute("SELECT id::text FROM stories WHERE id = %s", (story_id,))
    out = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT DISTINCT sp.story_id::text FROM mx_story_posts m JOIN story_posts sp ON sp.post_id = m.post_id
                    WHERE m.story_id = %s AND m.valid_to IS NULL""", (story_id,))
    out |= {r[0] for r in cur.fetchall()}
    return sorted(out)


def of_story(cur: Any, story_id: str, *, all: bool = False) -> Dict[str, Any]:
    """A story page's "Later": {stories [{story, headline, long_lived, following, subjects [{id, name}]}], items
    [the current RULE's Later rows (`all`: every rule's), newest first, with their verdicts], counts, precision,
    news}. `story_id` is a Mark IX story or a Mark X story (then the Mark IX stories of its members)."""
    six = _ix_stories(cur, story_id)
    lived = long_lived(cur, story_ids=six) if six else {}
    stops = stopped(cur, six) if six else set()
    heads = back._shown_posts(cur, six)
    ents = _ents(cur, {r for s in lived.values() for r in s.roots})
    stories = [{"story": sid, "headline": (heads.get(sid) or {}).get("title"), "long_lived": sid in lived,
                "following": sid in lived and sid not in stops,
                "subjects": [{"id": r, "name": ents[r].name if r in ents else None} for r in sorted(lived[sid].roots)]
                if sid in lived else []} for sid in six]
    rows: List[Tuple] = []
    if six:
        cur.execute(f"""SELECT {_COLS} FROM mx_later WHERE story = ANY(%s::uuid[]) AND (%s OR rule = %s)
                         ORDER BY post_at DESC, id""", (six, all, RULE))
        rows = cur.fetchall()
    items, counts = _items(cur, rows)
    return {"stories": stories, "items": items, "counts": counts, "precision": precision(cur, all=all),
            "news": on_news(cur), "rule": RULE}


def of_entity(cur: Any, entity_id: str, *, limit: int = 200, all: bool = False) -> Dict[str, Any]:
    """An entity page's "Later developments": the current RULE's Later rows (`all`: every rule's) found for it (or an
    entity merged into it), newest first: {entity, items, counts, rule}."""
    ids = _Ids(cur)
    root = ids.root(entity_id)
    members = sorted(ids.members([root])) if root else []
    rows: List[Tuple] = []
    if members:
        cur.execute(f"""SELECT {_COLS} FROM mx_later WHERE entity = ANY(%s::uuid[]) AND (%s OR rule = %s)
                         ORDER BY post_at DESC, id LIMIT %s""", (members, all, RULE, limit))
        rows = cur.fetchall()
    items, counts = _items(cur, rows)
    return {"entity": root, "items": items, "counts": counts, "rule": RULE}


def label(cur: Any, *, row: str, answer: str, note: Optional[str] = None) -> Dict[str, Any]:
    """The owner's label on a Later row (one of LABELS, or undo). ValueError: another answer; KeyError: no such row."""
    from insight_core.markx import repo
    if answer not in ANSWERS:
        raise ValueError(f"answer: one of {', '.join(ANSWERS)}")
    cur.execute("SELECT post FROM mx_later WHERE id = %s", (row,))
    got = cur.fetchone()
    if got is None:
        raise KeyError(row)
    lid = repo.add_label(cur, item_kind="later", a=row, b=got[0], answer=answer, note=(note or "").strip() or None)
    return {"id": str(lid), "answer": answer, "label": None if answer == "undo" else answer, "precision": precision(cur)}


def follow(cur: Any, *, story: str, following: bool, note: Optional[str] = None) -> Dict[str, Any]:
    """The owner's "Stop following this story" (following False) or "Follow again" (True): a row, never deleted.
    KeyError: no such Mark IX story."""
    cur.execute("SELECT 1 FROM stories WHERE id = %s", (story,))
    if cur.fetchone() is None:
        raise KeyError(story)
    cur.execute("INSERT INTO mx_later_stops (story, stopped, note) VALUES (%s, %s, %s)",
                (story, not following, (note or "").strip() or None))
    return {"story": story, "following": following}


__all__ = ["AGAIN", "LONG_TYPES", "MAIN_SHARE", "NEWS_KEY", "QUIET_DAYS", "QUIET_MAX", "RULE", "find", "follow", "label",
           "long_lived", "of_entity", "of_story", "on_news", "page_key", "plan", "precision", "quiet", "settle",
           "specific", "stage", "stopped", "write"]
