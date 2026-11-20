"""Journeys (issue 0250 #5; owner rule 2026-11-20): scripted walks over a copy's pages, a reader's clicks, each step
checked against the others. Where invariants count one rule over every row, a journey follows one reader from a story
to its things, to a thing's page, its links, its timeline and its family, and asks whether each page agrees with the
one before it:

  - `story_things`: story -> its things: each thing its members' readings make their subject is on the story page
    (one click to its entity page);
  - `story_makers`: story -> each thing: the maker the thing's page gives agrees with the maker the story's mentions of
    it state;
  - `entity_links`: entity -> its links: each post a shown link stands on names this thing (a mention linked here, its
    stated maker this thing's), not a namesake;
  - `entity_timeline`: entity -> timeline: each event's post is about this thing (subject, actor or compared) and of
    its maker;
  - `family_makers`: entity -> family -> versions: one maker across the family, unless the family is a split parent.

Two sets, measured apart: the **hard set** (a file, private: plan/research/lab/journeys.json; each entry a rule, the
names it selects read from the copy, never a name in code: `shared_names` = the bare names whose mentions state
`makers_at_least` distinct makers, each by `mentions_each` mentions, the owner's walks first) and a **random set**
(stories and things in a seeded order of their stable keys). Every step is reported in the breakage format: right /
wrong / missed, each wrong or missed one an exact row (the post, what the page returned, the label), its cause and the
feature that fixes it.

    python -m insight_core.checks.journeys --db <dsn> --json journeys.json [--hard journeys-set.json] [--now ISO]

Read-only. The rules here are the check's own (a maker agrees with another by its key, its words, or the entity its
name aliases), written apart from identity's, so a change to identity can't also change what measures it. The pages
are the app's own services (`perspective_views.story_view`, `entity_views.entity_page`, `graph.entity_relations`),
imported defensively: an older version without a page's field is measured as it is (its step misses).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

EXAMPLES = 5
ROWS_KEPT = 40                 # rows kept a step and set (the report shows fewer)
RANDOM_STORIES = 30
RANDOM_THINGS = 30
STORIES_A_NAME = 3             # the hard set's stories a name walks (the newest it is the subject of)
TOP_NAMES = 50
PRODUCT_TYPES = ("model", "product", "software", "project", "dataset")
ABOUT_ROLES = ("subject", "actor", "compared")
POST_EVENTS = ("birth", "release", "first_outside", "outside")

STEPS = {
    "story_things": "story -> its things: each subject of its members is on the story page, one click from its page",
    "story_makers": "story -> thing: the thing's maker agrees with the maker the story's mentions of it state",
    "entity_links": "entity -> links: each post a shown link stands on names this thing, not a namesake",
    "entity_timeline": "entity -> timeline: each event's post is about this thing (subject, actor, compared), its maker's",
    "family_makers": "entity -> family -> versions: one maker across the family (a split parent apart)",
}
FIX = {
    "story_things": "0250 #4 Things in this story (perspective_views.story_view `things`)",
    "story_makers": "0250 #1 split bare names by maker (identity.split_names, families.split)",
    "entity_links": "0250 #2 links follow the split; a single contradicted `released` held (identity.held_released)",
    "entity_timeline": "0250 #3 outside events need subject/actor/compared (timeline OUTSIDE_ROLES) and the split",
    "family_makers": "0230 family maker rule (identity.other_maker, families.maker) / 0250 #1",
}


def _key(name: Optional[str]) -> str:
    from insight_core.markx import names as N
    return N.key(name or "")


def _words_in(a: str, b: str) -> bool:
    wa, wb = a.split(), b.split()
    return bool(wa) and any(wb[i:i + len(wa)] == wa for i in range(len(wb) - len(wa) + 1))


class Copy:
    """What the walks read besides the pages: the merges (whole: they are few), each post's mentions through the pins,
    and the entities a maker's name aliases."""

    def __init__(self, cur: Any, now: Any) -> None:
        self.cur, self.now = cur, now
        cur.execute("SELECT from_id::text, to_id::text FROM mx_entity_redirects WHERE undone_at IS NULL")
        self.redirect = dict(cur.fetchall())
        self._mentions: Dict[str, List[Dict[str, Any]]] = {}
        self._alias: Dict[str, Optional[str]] = {}
        self._ents: Dict[str, Tuple] = {}
        self.guides = self._guides()

    def _guides(self) -> List[str]:
        try:
            from insight_core.markx import schemas
            return list(schemas.mention_guides())
        except Exception:  # noqa: BLE001 - an older version: every guide
            self.cur.execute("SELECT DISTINCT guide FROM mx_mention_sets")
            return [r[0] for r in self.cur.fetchall()]

    def root(self, eid: Optional[str]) -> Optional[str]:
        seen = set()
        while eid in self.redirect and eid not in seen:
            seen.add(eid)
            eid = self.redirect[eid]
        return eid

    def mentions(self, posts: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
        """{post: its current mentions [{n, root, name, key, type, role, maker}]}, each linked through its pin."""
        want = sorted(set(posts) - set(self._mentions))
        if want:
            self.cur.execute("""SELECT post_id::text, guide, n, entity_id::text, name, name_key, type, role, maker
                                  FROM mx_mentions_now WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[])""",
                             (self.guides, want))
            rows = self.cur.fetchall()
            self.cur.execute("""SELECT DISTINCT ON (post_id, guide, n) post_id::text, guide, n, entity_id::text
                                  FROM mx_entity_pins WHERE undone_at IS NULL AND post_id = ANY(%s::uuid[])
                                 ORDER BY post_id, guide, n, created_at DESC""", (want,))
            pins = {(p, g, n): e for p, g, n, e in self.cur.fetchall()}
            for p in want:
                self._mentions[p] = []
            for p, g, n, e, name, nk, typ, role, maker in rows:
                self._mentions[p].append({"n": n, "root": self.root(pins.get((p, g, n), e)), "name": name, "key": nk,
                                          "type": typ, "role": role, "maker": (maker or "").strip() or None})
        return {p: self._mentions.get(p, []) for p in set(posts)}

    def ents(self, ids: Iterable[str]) -> Dict[str, Tuple]:
        """{id: (name, type, maker, level, parent)}."""
        want = sorted({i for i in ids if i} - set(self._ents))
        if want:
            self.cur.execute("""SELECT id::text, COALESCE(shown_name, name), type, maker, level, parent::text
                                  FROM mx_entities WHERE id = ANY(%s::uuid[])""", (want,))
            for i, *rest in self.cur.fetchall():
                self._ents[i] = tuple(rest)
        return {i: self._ents[i] for i in ids if i in self._ents}

    def maker_of(self, eid: str) -> Optional[str]:
        """An entity's maker as stored: its stated maker, else (a thing under an org) its parent's name."""
        e = self.ents([eid]).get(eid)
        if e is None:
            return None
        if e[2]:
            return e[2]
        if e[4]:
            up = self.root(e[4])
            p = self.ents([up]).get(up)
            if p and (p[1] or "") in ("org", "person"):
                return p[0]
        return None

    def alias_root(self, k: str) -> Optional[str]:
        if k not in self._alias:
            self.cur.execute("SELECT entity_id::text FROM mx_entity_aliases WHERE key = %s", (k,))
            row = self.cur.fetchone()
            self._alias[k] = self.root(row[0]) if row else None
        return self._alias[k]

    def agree(self, a: Optional[str], b: Optional[str]) -> bool:
        """Two maker names are one maker: either unknown, the same key, one's words in the other's, or one entity by
        the names' aliases."""
        ka, kb = _key(a), _key(b)
        if not ka or not kb or ka == kb or _words_in(ka, kb) or _words_in(kb, ka):
            return True
        ra, rb = self.alias_root(ka), self.alias_root(kb)
        return ra is not None and ra == rb

    def split_parents(self) -> Set[str]:
        self.cur.execute("SELECT DISTINCT old->>'entity' FROM mx_entity_fixes WHERE kind = 'maker_split' AND undone_at IS NULL")
        return {self.root(r[0]) for r in self.cur.fetchall() if r[0]}


# ---- what is walked ---------------------------------------------------------------------------------------------

def shared_names(cur: Any, copy: Copy, *, makers_at_least: int = 2, mentions_each: int = 2,
                 top: Optional[int] = TOP_NAMES) -> List[Dict[str, Any]]:
    """The bare names (one word, no digit, a product type) whose current mentions state `makers_at_least` distinct
    makers each by `mentions_each` mentions: a maker's name resolved to the entity its key aliases (one company, many
    spellings), else its key, and two keys one maker when one's words are in the other's. By name key (the reading's),
    never by entity: both versions of a check walk the same names. [{key, name, makers {maker: n}, entities}], the
    most makers first."""
    cur.execute("""SELECT m.name_key, lower(btrim(m.maker)), count(*), min(m.name)
                     FROM mx_mentions_now m
                    WHERE m.guide = ANY(%s) AND m.type = ANY(%s) AND m.name_key !~ '[[:space:][:digit:]]'
                      AND m.name_key <> '' AND NULLIF(btrim(m.maker), '') IS NOT NULL
                    GROUP BY 1, 2""", (copy.guides, list(PRODUCT_TYPES)))
    by: Dict[str, Counter] = defaultdict(Counter)
    shown: Dict[str, str] = {}
    for nk, maker, n, name in cur.fetchall():
        by[nk][maker] += n
        shown.setdefault(nk, name)
    out = []
    for nk, votes in by.items():
        if len(votes) < makers_at_least:
            continue
        groups: List[List[Any]] = []   # [[key, n, alias root, keys]]
        for maker, n in sorted(votes.items(), key=lambda kv: (-kv[1], kv[0])):
            k = _key(maker)
            if not k or k == nk:
                continue
            r = copy.alias_root(k)
            g = next((g for g in groups if (r is not None and r == g[2])
                      or any(_words_in(k, x) or _words_in(x, k) for x in g[3])), None)
            if g is None:
                groups.append([k, n, r, [k]])
            else:
                g[1] += n
                g[3].append(k)
        big = [g for g in groups if g[1] >= mentions_each]
        if len(big) >= makers_at_least:
            out.append({"key": nk, "name": shown[nk], "makers": {g[0]: g[1] for g in big}})
    out.sort(key=lambda x: (-len(x["makers"]), -sum(x["makers"].values()), x["key"]))
    out = out[:top] if top else out
    if out:
        cur.execute("""SELECT DISTINCT name_key, entity_id::text FROM mx_mentions_now
                        WHERE guide = ANY(%s) AND name_key = ANY(%s) AND entity_id IS NOT NULL""",
                    (copy.guides, [x["key"] for x in out]))
        ents: Dict[str, Set[str]] = defaultdict(set)
        for nk, e in cur.fetchall():
            ents[nk].add(copy.root(e))
        cur.execute("""SELECT DISTINCT m.name_key, p.entity_id::text FROM mx_entity_pins p
                         JOIN mx_mentions_now m ON m.post_id = p.post_id AND m.guide = p.guide AND m.n = p.n
                        WHERE p.undone_at IS NULL AND m.name_key = ANY(%s)""", ([x["key"] for x in out],))
        for nk, e in cur.fetchall():
            ents[nk].add(copy.root(e))
        for x in out:
            x["entities"] = sorted(e for e in ents.get(x["key"], ()) if e)
    return out


def stories_naming(cur: Any, copy: Copy, key: str, n: int = STORIES_A_NAME) -> List[str]:
    """The newest current stories a member of which makes the name its subject."""
    cur.execute("""SELECT sp.story_id::text, max(COALESCE(p.published_at, p.created_at))
                     FROM mx_mentions_now m JOIN mx_story_posts sp ON sp.post_id = m.post_id AND sp.valid_to IS NULL
                     JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = ANY(%s) AND m.name_key = %s AND m.role = 'subject'
                    GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1 LIMIT %s""", (copy.guides, key, n))
    return [r[0] for r in cur.fetchall()]


def random_stories(cur: Any, n: int = RANDOM_STORIES) -> List[str]:
    """Stories of 2+ members in a seeded order of their first member's id (stable across the two versions' copies)."""
    cur.execute("""SELECT story_id::text FROM mx_story_posts WHERE valid_to IS NULL GROUP BY story_id
                    HAVING count(*) >= 2 ORDER BY md5(min(post_id::text) || 'journeys') LIMIT %s""", (n,))
    return [r[0] for r in cur.fetchall()]


def random_things(cur: Any, copy: Copy, n: int = RANDOM_THINGS) -> List[str]:
    """Things of a product type named by 3+ posts as their subject, in a seeded order of their name key."""
    cur.execute("""SELECT name_key FROM mx_mentions_now WHERE guide = ANY(%s) AND role = 'subject' AND type = ANY(%s)
                    GROUP BY 1 HAVING count(DISTINCT post_id) >= 3 ORDER BY md5(name_key || 'journeys') LIMIT %s""",
                (copy.guides, list(PRODUCT_TYPES), n))
    keys = [r[0] for r in cur.fetchall()]
    if not keys:
        return []
    cur.execute("""SELECT DISTINCT ON (name_key) name_key, entity_id::text FROM mx_mentions_now
                    WHERE guide = ANY(%s) AND name_key = ANY(%s) AND entity_id IS NOT NULL AND role = 'subject'
                    ORDER BY name_key, post_id""", (copy.guides, keys))
    return sorted({copy.root(e) for _k, e in cur.fetchall() if e})


# ---- the walks ------------------------------------------------------------------------------------------------

class Walks:
    """The steps' results, a set at a time: {(step, set): Counter(right, wrong, missed)} and their rows."""

    def __init__(self, copy: Copy) -> None:
        self.copy = copy
        self.counts: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        self.rows: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        self.errors: List[str] = []
        self._pages: Dict[str, Optional[Dict[str, Any]]] = {}
        self._split: Set[str] = copy.split_parents()   # 0250: a split parent's family holds several makers by design

    def mark(self, step: str, kset: str, label: str, **row: Any) -> None:
        self.counts[(step, kset)][label] += 1
        if label != "right" and len(self.rows[(step, kset)]) < ROWS_KEPT:
            self.rows[(step, kset)].append({"step": step, "set": kset, "label": label, **row, "fix": FIX[step]})

    def page(self, eid: str) -> Optional[Dict[str, Any]]:
        if eid not in self._pages:
            try:
                from insight_core.markx import entity_views
                self._pages[eid] = entity_views.entity_page(self.copy.cur, eid, now=self.copy.now)
            except Exception as e:  # noqa: BLE001 - a page that fails is its own finding
                self.errors.append(f"entity page {eid}: {str(e)[:160]}")
                self._pages[eid] = None
        return self._pages[eid]

    def title(self, post: str) -> str:
        self.copy.cur.execute("SELECT COALESCE(title, left(content, 90)) FROM posts WHERE id = %s", (post,))
        row = self.copy.cur.fetchone()
        return (row[0] or "")[:120] if row else ""

    # story -> its things -> each thing
    def story(self, sid: str, kset: str, start: str) -> None:
        cur, copy = self.copy.cur, self.copy
        try:
            from insight_core.markx import perspective_views
            view = perspective_views.story_view(cur, sid)
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"story page {sid}: {str(e)[:160]}")
            return
        if view is None:
            return
        head = view["story"].get("headline")
        members = [p for p in (view.get("posts") or {})]
        things = {t["id"]: t for t in view.get("things") or []}
        ms = copy.mentions(members)
        subjects: Dict[str, str] = {}
        for p, rows in ms.items():
            for m in rows:
                if m["role"] == "subject" and m["root"]:
                    subjects.setdefault(m["root"], p)
        names = copy.ents(subjects)
        for root, p in sorted(subjects.items()):
            got = root in things
            self.mark("story_things", kset, "right" if got else "missed", start=start, story=sid, headline=head,
                      post=p, title=self.title(p) if not got else None,
                      returned=None if got else f"no link to {names.get(root, ('?',))[0]} on the story page",
                      cause=None if got else "the story page lists no things" if not things else
                      "the story's subject is not among its things")
        for root in sorted(set(things) | set(subjects)):
            e = copy.ents([root]).get(root)
            if e is None or (e[1] or "") not in PRODUCT_TYPES:
                continue
            has = (things.get(root) or {}).get("maker") or copy.maker_of(root)
            for p, rows in ms.items():
                for m in rows:
                    if m["root"] != root or not m["maker"]:
                        continue
                    ok = copy.agree(m["maker"], has)
                    self.mark("story_makers", kset, "right" if ok else "wrong", start=start, story=sid, headline=head,
                              post=p, title=None if ok else self.title(p),
                              returned=None if ok else f"{e[0]} by {has}",
                              said=None if ok else f"the post's {m['name']} is by {m['maker']}",
                              cause=None if ok else "another maker's thing of the name links to this entity")

    # entity -> links, timeline, family
    def entity(self, eid: str, kset: str, start: str) -> None:
        copy = self.copy
        page = self.page(eid)
        if page is None:
            return
        root = page["entity"]["id"]
        name = page["entity"].get("name")
        maker = page["entity"].get("maker") or (page.get("maker") or {}).get("name") or copy.maker_of(root)
        self._links(page, root, name, maker, kset, start)
        self._timeline(page, root, name, maker, kset, start)
        self._family(page, root, name, kset, start)

    def _about(self, post: str, root: str) -> List[Dict[str, Any]]:
        return [m for m in self.copy.mentions([post]).get(post, []) if m["root"] == root]

    def _links(self, page: Dict[str, Any], root: str, name: str, maker: Optional[str], kset: str, start: str) -> None:
        shown = {(r["relation"], r["direction"], r["other"]["id"]): r for r in page.get("relations") or []}
        if not shown:
            return
        try:
            from insight_core.markx import graph
            members = [root] + [x for x, to in self.copy.redirect.items() if self.copy.root(to) == root]
            rels = graph.entity_relations(self.copy.cur, members)
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"relations {root}: {str(e)[:160]}")
            return
        for r in rels:
            k = (r["relation"], r["direction"], self.copy.root(r["other"]))
            if k not in shown:
                continue
            said = f"{r['relation']} {'->' if r['direction'] == 'out' else '<-'} {shown[k]['other']['name']}"
            for p in r.get("posts") or []:
                ms = self._about(p, root)
                bad = [m for m in ms if m["maker"] and not self.copy.agree(m["maker"], maker)]
                ok = bool(ms) and len(bad) < len(ms)
                self.mark("entity_links", kset, "right" if ok else "wrong", start=start, entity=root, name=name,
                          post=p, title=None if ok else self.title(p), returned=None if ok else said,
                          said=None if ok or not bad else f"the post's {bad[0]['name']} is by {bad[0]['maker']}",
                          cause=None if ok else "a namesake's post" if ms else "the post names no mention of it")

    def _timeline(self, page: Dict[str, Any], root: str, name: str, maker: Optional[str], kset: str, start: str) -> None:
        for ev in (page.get("timeline") or {}).get("items") or []:
            post = (ev.get("post") or {}).get("id")
            if ev.get("kind") not in POST_EVENTS or not post or ev.get("linked"):
                continue
            ms = self._about(post, root)
            about = [m for m in ms if m["role"] in ABOUT_ROLES]
            bad = [m for m in about if m["maker"] and not self.copy.agree(m["maker"], maker)]
            ok = bool(about) and len(bad) < len(about)
            cause = None if ok else "a namesake's post" if about else "a post that only names it" if ms else \
                "the post names no mention of it"
            self.mark("entity_timeline", kset, "right" if ok else "wrong", start=start, entity=root, name=name,
                      post=post, title=None if ok else self.title(post),
                      returned=None if ok else f"{ev['kind']} {str(ev.get('at') or '')[:10]}",
                      said=None if ok else (", ".join(sorted({f"{m['role']} {m['maker'] or ''}".strip() for m in ms}))
                                            or "no mention"), cause=cause)

    def _family(self, page: Dict[str, Any], root: str, name: str, kset: str, start: str) -> None:
        fam = (page.get("family") or {}).get("id") or (root if page.get("versions") else None)
        if not fam:
            return
        fpage = page if fam == root else self.page(fam)
        if fpage is None or fam in self._split:
            return
        vs = [v["id"] for v in fpage.get("versions") or []]
        makers = {v: self.copy.maker_of(v) for v in vs}
        votes = Counter(_key(m) for m in makers.values() if m)
        top = votes.most_common(1)[0][0] if votes else _key(self.copy.maker_of(fam))
        for v, m in sorted(makers.items()):
            ok = self.copy.agree(m, top)
            self.mark("family_makers", kset, "right" if ok else "wrong", start=start, entity=fam,
                      name=fpage["entity"].get("name"), version=v,
                      returned=None if ok else f"{self.copy.ents([v]).get(v, ('?',))[0]} by {m} in the family",
                      said=None if ok else f"the family's maker: {top}",
                      cause=None if ok else "another maker's thing in the family")


def load_hard(path: Optional[str]) -> List[Dict[str, Any]]:
    """The hard set's entries (a file: {walks: [{id, from: shared_names, makers_at_least, mentions_each, top, why}]});
    none given: the rule's default (the bare names of 2+ makers, the top TOP_NAMES)."""
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return list((json.load(f) or {}).get("walks") or [])
        except FileNotFoundError:
            pass
    return [{"id": "shared-names", "from": "shared_names", "makers_at_least": 2, "mentions_each": 2, "top": TOP_NAMES}]


def run(cur: Any, now: Any, *, hard: Sequence[Dict[str, Any]], random_stories_n: int = RANDOM_STORIES,
        random_things_n: int = RANDOM_THINGS) -> Dict[str, Any]:
    """Every walk of both sets: {found: [{name, area, what, count, of, examples, seconds, note}], rows, sets, errors}."""
    t0 = time.monotonic()
    copy = Copy(cur, now)
    walks = Walks(copy)
    sets: Dict[str, Any] = {"hard": [], "random": {}}
    for entry in hard:
        if entry.get("from") != "shared_names":
            continue
        names = shared_names(cur, copy, makers_at_least=int(entry.get("makers_at_least") or 2),
                             mentions_each=int(entry.get("mentions_each") or 2), top=entry.get("top"))
        sets["hard"].append({"id": entry.get("id"), "names": [{k: x[k] for k in ("key", "name", "makers")} for x in names]})
        for x in names:
            start = f"{entry.get('id')}: {x['name']}"
            for sid in stories_naming(cur, copy, x["key"]):
                walks.story(sid, "hard", start)
            for eid in x.get("entities") or []:
                walks.entity(eid, "hard", start)
    stories, things = random_stories(cur, random_stories_n), random_things(cur, copy, random_things_n)
    sets["random"] = {"stories": len(stories), "things": len(things)}
    for sid in stories:
        walks.story(sid, "random", f"random story {sid}")
    for eid in things:
        walks.entity(eid, "random", f"random thing {eid}")
    found = []
    for step, what in STEPS.items():
        for kset in ("hard", "random"):
            c = walks.counts.get((step, kset), Counter())
            rows = walks.rows.get((step, kset), [])
            found.append({"name": f"journeys.{step}.{kset}", "area": "journeys", "what": what,
                          "count": c["wrong"] + c["missed"], "of": c["right"] + c["wrong"] + c["missed"],
                          "examples": [r.get("post") or r.get("version") for r in rows[:EXAMPLES]],
                          "seconds": 0.0, "note": f"right {c['right']}, wrong {c['wrong']}, missed {c['missed']}"})
    return {"found": found, "rows": [r for k in sorted(walks.rows) for r in walks.rows[k]], "sets": sets,
            "errors": walks.errors[:50], "seconds": round(time.monotonic() - t0, 1)}


def lines(base: Optional[Dict[str, Any]], head: Optional[Dict[str, Any]], labels: Sequence[str],
          rows_shown: int = 8) -> List[str]:
    """The report's journeys section: right / wrong / missed of each step and set on both versions, then the head's
    wrong and missed rows (post -> what the page returned -> label, cause, the fixing feature)."""
    if not head:
        return ["Not walked (no journeys.json: a version before 0250's check, or its step failed)."]
    note = lambda d, n: next((f["note"] for f in (d or {}).get("found") or [] if f["name"] == n), "-")   # noqa: E731
    out = [f"| step | set | {labels[0]} | {labels[1]} |", "|---|---|---|---|"]
    for f in head["found"]:
        step, kset = f["name"].split(".")[1:]
        out.append(f"| `{step}` | {kset} | {note(base, f['name'])} | {f['note']} |")
    for s in head.get("sets", {}).get("hard", []):
        out.append(f"- hard set `{s['id']}`: {len(s['names'])} names")
    by: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in head.get("rows") or []:
        by[(r["step"], r["set"])].append(r)
    for (step, kset), rows in sorted(by.items()):
        out += ["", f"**{step}, {kset}** ({FIX[step]}):"]
        for r in rows[:rows_shown]:
            where = r.get("headline") or r.get("name") or ""
            out.append(f"- {r['start']} · {where} · post `{r.get('post') or r.get('version')}` "
                       f"\"{r.get('title') or ''}\" → {r.get('returned')}{' (' + r['said'] + ')' if r.get('said') else ''}"
                       f" → **{r['label']}**; cause: {r.get('cause')}")
    if head.get("errors"):
        out += ["", "Errors: " + "; ".join(head["errors"][:5])]
    return out


def main(argv=None) -> int:
    from insight_core.checks.session import copy_now, open_copy
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--hard")
    ap.add_argument("--now")
    args = ap.parse_args(argv)
    with open_copy(args.db) as conn, conn.cursor() as cur:
        now = copy_now(cur, args.now)
        got = run(cur, now, hard=load_hard(args.hard))
    got["now"] = now.isoformat()
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(got, f, ensure_ascii=False, indent=1, default=str)
    for f in got["found"]:
        print(f"{f['name']:<36} {f['count']:>5} of {f['of']:<6} {f['note']}")
    print(f"{got['seconds']} s; {len(got['errors'])} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
