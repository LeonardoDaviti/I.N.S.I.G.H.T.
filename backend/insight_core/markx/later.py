"""Later developments, in Shadow (issue 0163, building 0136): a story about a paper, a document, a model, software or
a dataset keeps gathering the posts that follow it up, at any age, one source at a time. Shadow: mx_* rows only
(mx_later, mx_later_stops, mx_tasks, mx_labels); Mark IX is only read, and nothing here reaches any News.

  A. **Long-lived stories.** A Mark IX story of 2+ sources (as back's) whose subject is of a type that outlives an
     event (LONG_TYPES). Its subject is back's E subject: the subject mention (role `subject`, the current set) of
     2+ of its posts, of 1 when only one of them was read; counted by entity (its root through the merges, a pin
     first) and by name key. Other stories keep back's once-only trigger. The owner's "Stop following this story"
     (a row in mx_later_stops, reversible) stops both its Later rows and its second waves.
  B. **The follow-up trigger** (no model; one source is enough; no age limit). A post dated after the story's last
     post, not a member, not saved, not a story source's repost of a member's page, is a Later candidate when
       E  its own subject mention is the story's subject: the same entity (root), the same name key, or, when the
          subject names a version, a later or the same version of its family (the family key, the version tuple);
       L  it links (or is) one of the story's own pages (back's: members' addresses, pages 2+ members link, the
          origin; hubs out) or an address of the subject entity (mx_entity_addresses, read through the merges, while
          its post still names it). Pages compare by back.norm, and a paper's pages by its identifier (the arXiv
          abs / html / pdf / vN forms are one paper: entity_originals.paper_ref).
     V (vectors) alone never: that finds "same topic", which the back judge calls related.
     Incremental: each run reads the posts dated since its last clock less MARGIN, oldest first, at most PER_RUN;
     a run that hits the cap keeps the last post it read, and the next one reads on past it (date, id), so a
     backlog is read over several runs and never stalls on many posts of one date. The
     first run reads FIRST_SCAN_DAYS back (production's first run reads its 30 days over a few runs, never all at
     once).
  C. **The judge**: the frozen `back` guide (back-v1), its input back.render (the story's 4 earliest posts, then the
     new post), RUNS=3, the majority. Planned after back's own questions under the same cap (Config.back_open:
     open or leased back tasks). Every verdict is stored (settle); only `development` shows as one.
  D. **Shown** on the story's page ("Later") and the subject's entity page ("Later developments"), newest first,
     with the owner's label buttons. Not on News: NEWS_KEY (an mx_settings flag, off) is what will gate it once
     measured.
  Also: a long-lived story's back trigger may fire again AGAIN after its last mx_back window (back.stories).

Dates are the reader's: COALESCE(surfaced_at, published_at, fetched_at) (back's).
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import back
from insight_core.markx.back import _date, norm

KIND = back.KIND
LONG_TYPES = ("paper", "document", "model", "software", "dataset", "method")   # method: once 0151's types add it
AGAIN = timedelta(days=30)        # a long-lived story's back trigger may fire again this long after its last window
FIRST_SCAN_DAYS = 30              # the first run reads this far back ...
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
    __slots__ = ("id", "type", "family", "version", "status", "name")

    def __init__(self, id: str, type: Optional[str], family: Optional[str], version: Optional[Tuple], status: str,
                 name: str) -> None:
        self.id, self.type, self.family, self.version, self.status, self.name = id, type, family, version, status, name


def _ents(cur: Any, ids: Iterable[str]) -> Dict[str, _Ent]:
    from insight_core.markx import names as N
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    cur.execute("""SELECT id::text, type, family_key, version_key, status, name FROM mx_entities
                    WHERE id = ANY(%s::uuid[])""", (ids,))
    return {i: _Ent(i, t, f, N.from_json(v), s, n) for i, t, f, v, s, n in cur.fetchall()}


def later_or_same(a: Optional[Tuple], b: Optional[Tuple]) -> bool:
    """Version tuple `a` is `b` or a later one (3.1 >= 3; 3 < 3.1; 4 > 3.9; words must agree: "pro" vs "mini" is
    neither)."""
    if not a or not b:
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return x > y
        return False
    return len(a) >= len(b)


def family_follows(post: Optional[_Ent], subject: Optional[_Ent]) -> bool:
    """A post's subject entity is a later version (or the same) of the story's subject's family: both of one family
    key, the subject naming a version and the post's version at or after it. A subject with no version: never by
    family (only its own entity and name)."""
    if post is None or subject is None or post.status == "not_entity" or not subject.family or not subject.version:
        return False
    return post.family == subject.family and later_or_same(post.version, subject.version)


# ---- the stories that keep listening ------------------------------------------------------------------------

class Long:
    """A long-lived story: its members (back._P), subject roots and name keys, the entity rows shown it, its pages."""

    def __init__(self, id: str, members: List[Any], origin: Optional[str]) -> None:
        self.id, self.origin = id, origin
        self.members = sorted(members, key=lambda p: (p.at, p.id))
        self.first, self.last = self.members[0].at, self.members[-1].at
        self.sources = {p.src for p in self.members}
        self.mids = {p.id for p in self.members}
        self.roots: Set[str] = set()
        self.keys: Set[str] = set()
        self.primary: Optional[str] = None     # the subject root most of its posts name (ties: the id)
        self.pages: Set[str] = set()           # page keys (back's pages, by paper identifier where one)
        self.addresses: Set[str] = set()       # its subject's addresses, as page keys
        self.own: Set[str] = set()             # its members' own addresses (norm): a story source's repost of one


def page_key(u: Optional[str]) -> Optional[str]:
    """A page's compared form: 'paper <ref>' for a paper's page (any of its forms and versions), else back.norm."""
    if not u:
        return None
    from insight_core.utils.entity_originals import paper_ref
    try:
        ref = paper_ref(u.strip())
    except Exception:   # an address the paper rules can't read is compared as a page
        ref = None
    return f"paper {ref}" if ref else norm(u)


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
    """{story: Long} of Mark IX's stories of 2+ sources whose subject is of LONG_TYPES (of `story_ids`, else all;
    stopped ones too: the caller drops them). `with_pages`: their pages and their subjects' addresses as well."""
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
    rows = _subject_rows(cur, mids)
    cur.execute("SELECT DISTINCT post_id::text FROM mx_mention_sets WHERE post_id = ANY(%s::uuid[])", (mids,))
    read = {r[0] for r in cur.fetchall()}
    long_t = set(LONG_TYPES)
    roots_of: Dict[str, Set[str]] = defaultdict(set)
    keys_of: Dict[str, Set[str]] = defaultdict(set)
    for pid, g, n, eid, key, t in rows:
        if t not in long_t:
            continue
        r = ids.of(pid, g, n, eid)
        if r:
            roots_of[pid].add(r)
        if key:
            keys_of[pid].add(key)
    out: Dict[str, Long] = {}
    for sid, ms in by.items():
        need = 2 if sum(m.id in read for m in ms) >= 2 else 1
        rc: Counter = Counter()
        kc: Counter = Counter()
        for m in ms:
            rc.update(roots_of.get(m.id, ()))
            kc.update(keys_of.get(m.id, ()))
        roots = {r for r, k in rc.items() if k >= need}
        keys = {k for k, c in kc.items() if c >= need}
        if not roots and not keys:
            continue
        s = Long(sid, ms, origin.get(sid))
        s.roots, s.keys = roots, keys
        s.primary = min(roots, key=lambda r: (-rc[r], r)) if roots else None
        out[sid] = s
    if out:
        ents = _ents(cur, {r for s in out.values() for r in s.roots})
        for s in out.values():   # an entity marked not one is no subject
            s.roots = {r for r in s.roots if r not in ents or ents[r].status != "not_entity"}
            if s.primary not in s.roots:
                s.primary = min(s.roots) if s.roots else None
        out = {sid: s for sid, s in out.items() if s.roots or s.keys}
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
    """Each story's pages (back's rule, compared by page_key) and its subjects' current addresses."""
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
        s.addresses = set().union(*(addr.get(r, set()) for r in s.roots)) if s.roots else set()


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


def find(cur: Any, *, now: datetime, since: datetime, limit: int = PER_RUN,
         after: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The Later candidates the posts dated in [since, now] make (at most `limit` posts, oldest first; past `after`
    at `since` when resuming): ([{story, post, members, entity, trig, post_at, last_at}], the clock the next run
    reads from: {at, after} — `after` the last post read when the cap stopped it, else None). Nothing is written."""
    recent, more = _recent(cur, since, now, limit, after)
    clock = {"at": recent[-1].at.isoformat(), "after": recent[-1].id} if more else {"at": now.isoformat(), "after": None}
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
    p_roots: Dict[str, Set[str]] = defaultdict(set)
    p_keys: Dict[str, Set[str]] = defaultdict(set)
    for pid, g, n, eid, key, _t in _subject_rows(cur, rids):
        r = ids.of(pid, g, n, eid)
        if r:
            p_roots[pid].add(r)
        if key:
            p_keys[pid].add(key)
    ents = _ents(cur, {r for s in st.values() for r in s.roots} | {r for rs in p_roots.values() for r in rs})
    by_root: Dict[str, Set[str]] = defaultdict(set)
    by_key: Dict[str, Set[str]] = defaultdict(set)
    by_family: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    by_page: Dict[str, Set[str]] = defaultdict(set)      # story pages (hubs to take out)
    by_addr: Dict[str, Set[str]] = defaultdict(set)      # subject addresses
    for s in st.values():
        for r in s.roots:
            by_root[r].add(s.id)
            e = ents.get(r)
            if e and e.family and e.version:
                by_family[e.family].append((s.id, r))
        for k in s.keys:
            by_key[k].add(s.id)
        for k in s.pages:
            by_page[k].add(s.id)
        for k in s.addresses:
            by_addr[k].add(s.id)
    links = _raw_links(cur, rids)
    hits: Dict[Tuple[str, str], Dict[str, Any]] = {}
    page_hits: Dict[Tuple[str, str], Set[str]] = defaultdict(set)   # (story, post): the story pages it matched

    def hit(sid: str, pid: str, trig: str, entity: Optional[str] = None) -> None:
        h = hits.setdefault((sid, pid), {"trig": set(), "entity": None})
        h["trig"].add(trig)
        if entity and h["entity"] is None:
            h["entity"] = entity

    for p in recent:
        for r in p_roots.get(p.id, ()):
            for sid in by_root.get(r, ()):
                hit(sid, p.id, "E", r)
            e = ents.get(r)
            if e and e.family:
                for sid, sr in by_family.get(e.family, ()):
                    if r != sr and family_follows(e, ents.get(sr)):
                        hit(sid, p.id, "E", sr)
        for k in p_keys.get(p.id, ()):
            for sid in by_key.get(k, ()):
                hit(sid, p.id, "E")
        keys = {k for k in map(page_key, [p.url] + links.get(p.id, [])) if k}
        for k in keys:
            for sid in by_addr.get(k, ()):
                hit(sid, p.id, "L")
            for sid in by_page.get(k, ()):
                page_hits[(sid, p.id)].add(k)
    if page_hits:   # back's hubs: a page linked in HUB_WEEKS+ weeks is no story page (its forms as back reads them)
        plain = {k for ks in page_hits.values() for k in ks if not k.startswith("paper ")}
        hub = back.hubs(cur, plain)
        for (sid, pid), ks in page_hits.items():
            if ks - hub:
                hit(sid, pid, "L")
    at = {p.id: p for p in recent}
    out = []
    for (sid, pid), h in sorted(hits.items(), key=lambda kv: (at[kv[0][1]].at, kv[0])):
        s, p = st[sid], at[pid]
        if p.at <= s.last or pid in s.mids:
            continue
        if p.src in s.sources and (norm(p.url) in s.own or s.own & {norm(u) for u in links.get(pid, ())}):
            continue   # the story's own source again carrying a member's page: a retelling, not a follow-up
        out.append({"story": sid, "post": pid, "members": [m.id for m in s.members], "entity": h["entity"] or s.primary,
                    "trig": [t for t in TRIG_ORDER if t in h["trig"]], "post_at": p.at, "last_at": s.last})
    return out, clock


def write(cur: Any, found: Sequence[Dict[str, Any]], *, run_id: Any = None, now: Optional[datetime] = None) -> int:
    """The new Later rows (one a story and post): how many were new."""
    added = 0
    for c in found:
        cur.execute("""INSERT INTO mx_later (story, post, members, entity, trig, post_at, last_at, run_id, found_at)
                       VALUES (%s, %s, %s::uuid[], %s, %s, %s, %s, %s, COALESCE(%s, now()))
                       ON CONFLICT (story, post) DO NOTHING""",
                    (c["story"], c["post"], c["members"], c["entity"], c["trig"], c["post_at"], c["last_at"], run_id, now))
        added += cur.rowcount
    return added


# ---- the judge -----------------------------------------------------------------------------------------------

def plan(cur: Any, *, open_cap: int = back.OPEN, now: Optional[datetime] = None, **_kw: Any) -> int:
    """A back question for each Later row with none, the newest post first, while fewer than `open_cap` back tasks
    wait (open or leased; back's cap, shared). How many were added."""
    from insight_core.markx import tasks
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = %s AND status IN ('open', 'leased')", (KIND,))
    room = open_cap - cur.fetchone()[0]
    if room <= 0:
        return 0
    cur.execute("""SELECT id::text, story::text, members::text[], post::text, post_at FROM mx_later
                    WHERE task_id IS NULL ORDER BY post_at DESC, id LIMIT %s""", (room,))
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
    """Store the verdict of each asked row whose task has RUNS valid answers (at most `limit`): how many."""
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
    capped run's resume reads on past its last post, no margin), the back questions for them under back's cap, the
    verdicts answered since. Its counts."""
    from insight_core.markx import repo
    t0 = time.monotonic()
    last = repo.get_setting(cur, SINCE_KEY, default=None) or {}
    after = last.get("after")
    if last.get("at"):
        since = datetime.fromisoformat(last["at"]) - (timedelta(0) if after else MARGIN)
    else:
        since = now - timedelta(days=FIRST_SCAN_DAYS)
    found, clock = find(cur, now=now, since=since, limit=limit, after=after)
    out = {"since": since.isoformat(), "clock": clock, "found": len(found),
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


def precision(cur: Any) -> Dict[str, Any]:
    """The owner's labels on Later rows: {labelled, development, precision (None before the first)}."""
    cur.execute("""SELECT DISTINCT ON (a) a::text, answer FROM mx_labels WHERE item_kind = 'later' AND labeller = 'owner'
                    ORDER BY a, created_at DESC, ctid DESC""")
    marks = [ans for _, ans in cur.fetchall() if ans != "undo"]
    dev = sum(a == "development" for a in marks)
    return {"labelled": len(marks), "development": dev, "precision": round(dev / len(marks), 4) if marks else None}


_COLS = "id::text, story::text, post::text, entity::text, trig, post_at, last_at, task_id::text, verdict, runs"


def _items(cur: Any, rows: Sequence[Tuple]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Rows (_COLS) as shown, newest post first, with live verdicts for answered rows not yet settled."""
    late = back._answers(cur, sorted({r[7] for r in rows if r[7] and r[8] is None}))
    shown = back._shown_posts(cur, {r[2] for r in rows} | {r[1] for r in rows})
    names = {e.id: e.name for e in _ents(cur, {r[3] for r in rows if r[3]}).values()}
    marks = _labels(cur, [r[0] for r in rows])
    counts: Counter = Counter(candidates=len(rows))
    items = []
    for lid, story, pid, ent, trig, at, last, tid, verdict, runs in rows:
        if verdict is None and tid:
            v = back.verdict(late.get(tid, []))
            verdict, runs = (v["relation"], v["runs"]) if v else (None, None)
        counts[verdict or "waiting"] += 1
        p = shown.get(pid) or {}
        items.append({"id": lid, "story": story, "headline": (shown.get(story) or {}).get("title"), "post": pid,
                      "title": p.get("title"), "url": p.get("url"), "source": p.get("source"), "at": back._iso(at),
                      "days_after": max(0, (at - last).days), "trig": list(trig), "entity": ent,
                      "entity_name": names.get(ent), "verdict": verdict, "runs": list(runs or []),
                      "label": marks.get(lid)})
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


def of_story(cur: Any, story_id: str) -> Dict[str, Any]:
    """A story page's "Later": {stories [{story, headline, long_lived, following, subjects [{id, name}]}], items
    [every Later row, newest first, with its verdict], counts, precision, news}. `story_id` is a Mark IX story or a
    Mark X story (then the Mark IX stories of its members)."""
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
        cur.execute(f"SELECT {_COLS} FROM mx_later WHERE story = ANY(%s::uuid[]) ORDER BY post_at DESC, id", (six,))
        rows = cur.fetchall()
    items, counts = _items(cur, rows)
    return {"stories": stories, "items": items, "counts": counts, "precision": precision(cur), "news": on_news(cur)}


def of_entity(cur: Any, entity_id: str, *, limit: int = 200) -> Dict[str, Any]:
    """An entity page's "Later developments": the Later rows found for it (or an entity merged into it), newest
    first: {items, counts}."""
    ids = _Ids(cur)
    root = ids.root(entity_id)
    members = sorted(ids.members([root])) if root else []
    rows: List[Tuple] = []
    if members:
        cur.execute(f"SELECT {_COLS} FROM mx_later WHERE entity = ANY(%s::uuid[]) ORDER BY post_at DESC, id LIMIT %s",
                    (members, limit))
        rows = cur.fetchall()
    items, counts = _items(cur, rows)
    return {"entity": root, "items": items, "counts": counts}


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


__all__ = ["AGAIN", "LONG_TYPES", "NEWS_KEY", "family_follows", "find", "follow", "label", "later_or_same", "long_lived",
           "of_entity", "of_story", "on_news", "page_key", "plan", "precision", "settle", "stage", "stopped", "write"]
