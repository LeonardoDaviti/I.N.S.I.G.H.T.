"""Renames proposed by shared evidence (issue 0165 B): one thing under an earlier name is a question, never a merge.

Two entities (clusters, read through the merges) of one maker, both a thing a maker ships (a model, product, software,
project or dataset; never an org, a person, a version or variant), become a **rename candidate** when one is older
(its last post before the other's first, or after it by less than `rename_overlap_days`, 7) and one of:
  - **address**: they share an own address (0138's mx_entity_addresses: a code repository, a release page, a demo;
    compared by host and path, a code platform's page by its owner and repository), or a post whose subject is one
    links an own address of the other (the birth post linking the repository the launch's entity holds);
  - **named**: the newer one's first posts about it (its subject, up to NAMED_POSTS) name the older one by one of its
    names (2+ words, or 5+ characters run together; never its maker's name alone); `formerly` when that post also
    says so ("formerly", "renamed", "now called", "previously known as", "rebranded", ...).
The guards: never a pair the owner kept apart (an alias or rename answered other than `same`, or a merge the owner
undid), never one cluster already, never one's part or version of the other (one's parent in the other's cluster), never
two names of different versions (identity.vconflict: a version bump is not a rename).

A candidate is asked once (`rename`, rename-v1: both names with their first and last posts, their addresses and why it
is asked). Haiku's `renamed` goes to the review queue (mx_entity_queue kind 'rename', a = the older, b = the newer,
proposal 'same', its confidence); anything else keeps the pair apart (it is never asked again). **Never automatic**
(0165: questions only until measured). The owner's `same` merges the older cluster into the newer as a redirect of kind
'rename' (`merge`; its names shown as "earlier names", undone like any merge); other answers keep them apart for good.
Off with entity_bands.json `timeline.renames`.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N

KIND = "rename"
NAMED_POSTS = 3              # the newer one's first posts about it read for the older one's name
SHOWN_POSTS = 2              # the question shows each side's first and last post
CODE_HOSTS = ("github.com", "gitlab.com", "codeberg.org", "huggingface.co", "bitbucket.org")
ADDRESS_KINDS = ("code", "release", "demo")
CUE = re.compile(r"\b(formerly|renamed|now called|now named|previously (?:known as|called|named)|rebrand(?:ed|ing)?|"
                 r"was called|is now|ранее|переименова\w*|бывш\w*|теперь называ\w*)\b", re.I)
THINGS = ("model", "product", "software", "project", "dataset")


def config() -> Dict[str, Any]:
    from insight_core.markx import components
    return components.config()


def address(u: Optional[str]) -> Optional[str]:
    """An address's compared form: host and path (back.norm), a code platform's page as owner/repository (its
    `.git`, tree and blob paths dropped), a Hugging Face model, dataset or space as its owner/name."""
    from insight_core.markx.back import norm
    n = norm(u)
    if not n:
        return None
    host, _, path = n.partition("/")
    segs = [s for s in path.split("/") if s]
    if host in CODE_HOSTS and segs:
        if host == "huggingface.co" and segs[0] in ("datasets", "spaces") and len(segs) >= 3:
            segs = segs[:3]
        else:
            segs = segs[:2]
        if segs and segs[-1].endswith(".git"):
            segs[-1] = segs[-1][:-4]
        if len(segs) < 2:
            return None
    return host + "/" + "/".join(segs)


# ---- who and when -------------------------------------------------------------------------------------------------

def thing_root(book: I.Book, root: str) -> bool:
    e = book.ents.get(root)
    if e is None or e.status == "not_entity" or e.level in I.VERSION_LEVELS:
        return False
    t = book.shown_type(root) or book.etype(root)
    return t in THINGS and not book.org_like(root)


def maker_index(book: I.Book) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """({root: its maker ids}, {maker id: the roots it makes}), one pass over the entities: a stated maker is its
    cluster (or its key when no entity has it), a thing's org or person parent its cluster. Versions are their family's."""
    makers: Dict[str, Set[str]] = defaultdict(set)
    for eid, e in book.ents.items():
        if e.level in I.VERSION_LEVELS or e.status == "not_entity":
            continue
        r = book.root(eid)
        if e.maker and N.key(e.maker):
            mr = I.maker_root(book, e.maker)
            makers[r].add(mr if mr and mr != r else "key:" + N.key(e.maker))
        if e.parent:
            p = book.root(e.parent)
            if p and p != r and p in book.ents and I.schemas_type(book.ents[p].type) in I.ORGISH:
                makers[r].add(p)
    by_maker: Dict[str, Set[str]] = defaultdict(set)
    for r, ms in makers.items():
        for m in ms:
            by_maker[m].add(r)
    return makers, by_maker


class Span:
    """A cluster's posts: (at, post, role) sorted, the first and last, its subject posts."""

    def __init__(self) -> None:
        self.posts: Dict[str, Tuple[datetime, Set[str], Set[str]]] = {}   # post -> (at, roles, spans)

    def add(self, pid: str, at: datetime, role: Optional[str], span: Optional[str]) -> None:
        got = self.posts.setdefault(pid, (at, set(), set()))
        got[1].add(role or "mention")
        if span:
            got[2].add(span)

    @property
    def ordered(self) -> List[str]:
        return sorted(self.posts, key=lambda p: (self.posts[p][0], p))

    @property
    def first(self) -> datetime:
        return min(v[0] for v in self.posts.values())

    @property
    def last(self) -> datetime:
        return max(v[0] for v in self.posts.values())

    def about(self, n: int) -> List[str]:
        """Its first n posts about it (subject or actor), else its first n posts."""
        subj = [p for p in self.ordered if self.posts[p][1] & {"subject", "actor"}]
        return (subj or self.ordered)[:n]


def spans_of(cur: Any, book: I.Book, roots: Iterable[str]) -> Dict[str, Span]:
    from insight_core.markx import schemas
    roots = set(roots)
    members = sorted(m for r in roots for m in book.cluster(r))
    if not members:
        return {}
    cur.execute("""SELECT m.entity_id::text, m.post_id::text, m.guide, m.n, m.role, m.span,
                          COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = ANY(%s) AND m.entity_id = ANY(%s::uuid[])""", (schemas.mention_guides(), members))
    out: Dict[str, Span] = {}
    for eid, pid, g, n, role, span, at in cur.fetchall():
        r = book.root(book.pins.get((pid, g, n), eid))
        if r in roots and at is not None:
            out.setdefault(r, Span()).add(pid, at, role, span)
    return out


def names_of(book: I.Book, root: str, maker_keys: Set[str]) -> Set[str]:
    """A cluster's names worth finding in a text: 2+ words, or 5+ characters run together, never a maker's name; and
    each without its maker's name in front when 2+ words stay ("Acme Forge Snap" is also written "Forge Snap")."""
    out = set()
    for m in book.cluster(root):
        k = book.ents[m].key
        if k and k not in maker_keys and (len(k.split()) >= 2 or len(N.squash(k)) >= 5):
            out.add(k)
        for mk in maker_keys:
            if mk and k.startswith(mk + " ") and len(k[len(mk) + 1:].split()) >= 2:
                out.add(k[len(mk) + 1:])
    return out


def without(text_key: str, keys: Iterable[str]) -> str:
    """A text key with these names taken out (each occurrence a break)."""
    t = f" {text_key} "
    for k in sorted(keys, key=len, reverse=True):
        if k:
            t = t.replace(f" {k} ", " | ")
    return t.strip()


def _maker_keys(book: I.Book, makers: Set[str]) -> Set[str]:
    out = set()
    for mk in makers:
        if mk.startswith("key:"):
            out.add(mk[4:])
        elif mk in book.ents:
            out |= {book.ents[x].key for x in book.cluster(mk)}
    return out


_PUNCT = re.compile(r"(?<!\d)[.](?!\d)|[!?…*|<>\[\]{}“”‘’\"]")


def text_key_of(text: str) -> str:
    """A text as name keys are written (names.base_key), its sentence marks gone ("Snap." is "snap"; "4.1" stays)."""
    return N.base_key(_PUNCT.sub(" ", text or ""))


def words_in(text_key: str, k: str) -> bool:
    return f" {k} " in f" {text_key} "


# ---- the candidates -----------------------------------------------------------------------------------------------

def guard(book: I.Book, old: str, new: str) -> Optional[str]:
    """Why a pair is never a rename candidate, or None."""
    if book.root(old) == book.root(new):
        return "one"
    co, cn = book.cluster(old), book.cluster(new)
    if any(I.pair(x, y) in book.never for x in co for y in cn):
        return "owner_apart"
    for a, b in ((co, new), (cn, old)):
        if any(book.ents[x].parent and book.root(book.ents[x].parent) == book.root(b) for x in a):
            return "part"
    eo, en = book.ents[book.root(old)], book.ents[book.root(new)]
    if I.vconflict(eo, en) == "strong":
        return "version"
    if N.has_version(eo.pk) and N.has_version(en.pk) and eo.pk[0] and eo.pk[0] == en.pk[0]:
        return "version"            # one family, two versions: a version bump, never a rename
    return None


def candidates(cur: Any, book: I.Book, *, seeds: Optional[Iterable[str]], overlap_days: int = 7,
               spans: Optional[Dict[str, Span]] = None) -> List[Dict[str, Any]]:
    """[{old, new, rules, evidence}]: the rename candidates touching `seeds` (roots; None: every thing)."""
    from insight_core.markx import entity_addresses as EA, tasks
    makers, by_maker = maker_index(book)
    is_thing: Dict[str, bool] = {}

    def thing(r: str) -> bool:
        if r not in is_thing:
            is_thing[r] = thing_root(book, r)
        return is_thing[r]
    seeds = set(makers) if seeds is None else {book.root(s) for s in seeds if book.root(s) in makers}
    seeds = {s for s in seeds if thing(s)}
    partners = {s: {p for m in makers[s] for p in by_maker[m] if p != s and thing(p)} for s in seeds}
    roots = {s for s, ps in partners.items() if ps} | {p for ps in partners.values() for p in ps}
    if not roots:
        return []
    spans = spans if spans is not None else spans_of(cur, book, roots)
    gap = timedelta(days=overlap_days)
    pairs: Dict[Tuple[str, str], None] = {}
    for s in sorted(seeds):
        if s not in spans:
            continue
        for p in sorted(partners.get(s, ())):
            if p not in spans:
                continue
            a, b = spans[s], spans[p]
            old, new = (s, p) if (a.first, s) < (b.first, p) else (p, s)
            so, sn = spans[old], spans[new]
            if so.first >= sn.first or so.last > sn.first + gap:
                continue
            if guard(book, old, new) is None:
                pairs[(old, new)] = None
    if not pairs:
        return []
    ends = sorted({x for p in pairs for x in p})
    # address: shared own addresses, or a subject post of one linking an own address of the other
    own: Dict[str, Set[str]] = defaultdict(set)
    for r, rows in EA.current(cur, book, ends).items():
        for kind, url, _rule, _at, _pid in rows:
            a = address(url) if kind in ADDRESS_KINDS else None
            if a:
                own[r].add(a)
    about = {r: set(spans[r].about(50)) for r in ends}
    links: Dict[str, Set[str]] = defaultdict(set)
    ids = sorted({p for r in ends for p in about[r]})
    if ids and own:
        cur.execute("SELECT post_id::text, target_url FROM post_links WHERE post_id = ANY(%s::uuid[]) AND NOT boilerplate",
                    (ids,))
        for pid, url in cur.fetchall():
            a = address(url)
            if a:
                links[pid].add(a)
    # named: the newer one's first posts about it, read
    first = {new: spans[new].about(NAMED_POSTS) for _, new in pairs}
    posts = tasks.load_posts(cur, {p for ps in first.values() for p in ps})
    text_key = {pid: text_key_of(p.title + " \n " + p.text) for pid, p in posts.items()}
    cued = {pid for pid, p in posts.items() if CUE.search(p.title + "\n" + p.text)}
    out: List[Dict[str, Any]] = []
    for old, new in pairs:
        rules: List[str] = []
        ev: Dict[str, Any] = {}
        shared = own[old] & own[new]
        if shared:
            rules.append("address")
            ev["address"] = sorted(shared)[:3]
        else:
            linked = sorted({a for x, y in ((old, new), (new, old)) for p in about[x] for a in links.get(p, set()) & own[y]})
            if linked:
                rules.append("address")
                ev["address"] = linked[:3]
                ev["linked"] = True
        mk = _maker_keys(book, makers.get(old, set()) | makers.get(new, set()))
        news = {book.ents[x].key for x in book.cluster(new)}
        olds = names_of(book, old, mk) - news
        # the newer one's own names are taken out first: "Snap" inside "Acme Snap" is not the older "Snap"
        texts = {pid: without(text_key[pid], news) for pid in first.get(new, ()) if pid in text_key}
        hits = [(pid, k) for pid, t in texts.items() for k in sorted(olds) if words_in(t, k)]
        if hits:
            rules.append("named")
            ev["named"] = {"post": hits[0][0], "name": hits[0][1]}
            if any(pid in cued for pid, _ in hits):
                rules.append("formerly")
        if rules:
            out.append({"old": old, "new": new, "rules": rules, "evidence": ev})
    return out


# ---- the question ---------------------------------------------------------------------------------------------------

def _side(book: I.Book, root: str, span: Span, own: Sequence[str], posts: Dict[str, Any]) -> str:
    e = book.ents[root]
    names = sorted({book.ents[m].name for m in book.cluster(root)})
    head = (f'name "{book.label(root)}" (also written: {", ".join(repr(n) for n in names[:4])}) | type '
            f"{book.shown_type(root)} | maker {e.maker} | {len(span.posts)} posts | first {span.first.date()} | "
            f"last {span.last.date()}")
    lines = [head]
    if own:
        lines.append("  its own addresses: " + ", ".join(own[:3]))
    order = span.ordered
    picks = [("first post", order[0])] + ([("last post", order[-1])] if len(order) > 1 else [])
    for what, pid in picks:
        p = posts.get(pid)
        if p is not None:
            sp = sorted(span.posts[pid][2], key=len, reverse=True)
            lines.append(f"  {what}: " + I._ctx(p, sp[0] if sp else e.name))
    return "\n".join(lines)


WHY = {"address": "they share an own address", "named": "NEW's first post names OLD",
       "formerly": "NEW's first post says it was renamed or formerly called so"}


def rename_input(book: I.Book, c: Dict[str, Any], spans: Dict[str, Span], own: Dict[str, List[str]],
                 posts: Dict[str, Any]) -> str:
    why = "; ".join(WHY[r] for r in c["rules"])
    if c["evidence"].get("address"):
        why += f" ({', '.join(c['evidence']['address'])})"
    return (f"OLD: {_side(book, c['old'], spans[c['old']], own.get(c['old'], []), posts)}\n"
            f"NEW: {_side(book, c['new'], spans[c['new']], own.get(c['new'], []), posts)}\n"
            f"Asked because: {why}")


def asked(cur: Any) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """{(old, new): (task id, status)} of the rename questions asked (either way round)."""
    cur.execute("SELECT id::text, a::text, b::text, status FROM mx_tasks WHERE kind = %s AND b IS NOT NULL ORDER BY created_at",
                (KIND,))
    out = {}
    for tid, a, b, status in cur.fetchall():
        out[(a, b)] = (tid, status)
    return out


def stage(cur: Any, book: I.Book, *, ask: Any, run_id: Any, full: bool, since: Optional[datetime],
          seeds: Iterable[str] = ()) -> Dict[str, Any]:
    """The decision run's rename step (after the addresses): the candidates touching the run's linked entities
    (every thing on the full pass) asked, and the answers come since (every answer on the full pass) queued."""
    from insight_core.markx import entity_addresses as EA, tasks
    cfg = config()
    if not cfg["renames"]:
        return {"off": True}
    if hasattr(ask, "caps"):
        ask.caps.setdefault(KIND, cfg["rename_cap"])
    got = asked(cur)
    out = {"candidates": 0, "asked": 0, "waiting": 0, "queued": 0, "answered": 0, "apart": 0}
    seeds = None if full else {book.root(s) for s in seeds if book.root(s)}
    found = candidates(cur, book, seeds=seeds, overlap_days=cfg["rename_overlap_days"]) if seeds is None or seeds else []
    out["candidates"] = len(found)
    by_rule: Dict[str, int] = defaultdict(int)
    for c in found:
        for r in c["rules"]:
            by_rule[r] += 1
    out["by_rule"] = dict(by_rule)
    new = [c for c in found if (c["old"], c["new"]) not in got and (c["new"], c["old"]) not in got]
    if new:
        new = new[:max(0, cfg["rename_cap"] - ask.added[KIND])]
        roots = {x for c in new for x in (c["old"], c["new"])}
        spans = spans_of(cur, book, roots)
        own = {r: sorted({u for kind, u, *_ in rows if kind in ADDRESS_KINDS})
               for r, rows in EA.current(cur, book, roots).items()}
        posts = tasks.load_posts(cur, {p for r in roots if r in spans for p in (spans[r].ordered[:1] + spans[r].ordered[-1:])})
        for c in new:
            if c["old"] not in spans or c["new"] not in spans:
                continue
            text = rename_input(book, c, spans, own, posts)
            if ask.added[KIND] >= cfg["rename_cap"]:
                ask.waiting[KIND] += 1
                out["waiting"] += 1
                continue
            ask.answer(KIND, text, a=c["old"], b=c["new"])
            got[(c["old"], c["new"])] = ("new", "open")
            out["asked"] += 1
    # the answers: Haiku's `renamed` queued for the owner (never merged by itself)
    rules_of = {(c["old"], c["new"]): c for c in found}
    tids = {tid: pr for pr, (tid, status) in got.items() if status == "answered"}
    if tids:
        params: List[Any] = [list(tids)]
        when = ""
        if since is not None and not full:
            when, params = "AND created_at >= %s", params + [since]
        cur.execute(f"""SELECT DISTINCT ON (c.task_id) c.task_id::text, c.id::text, c.answer, t.input FROM mx_calls c
                         JOIN mx_tasks t ON t.id = c.task_id
                         WHERE c.valid AND c.task_id = ANY(%s::uuid[]) {when.replace('created_at', 'c.created_at')}
                         ORDER BY c.task_id, c.created_at, c.ctid""", params)
        for tid, call, ans, text in cur.fetchall():
            old, new_ = tids[tid]
            ans = ans or {}
            out["answered"] += 1
            if ans.get("relation") != "renamed":
                out["apart"] += 1
                continue
            if old not in book.ents or new_ not in book.ents or guard(book, old, new_) in ("one", "owner_apart"):
                continue
            c = rules_of.get((old, new_)) or {}
            if I.queue_item(cur, kind="rename", a=old, b=new_, proposal="same", reason="rename",
                            conf=float(ans.get("confidence") or 0),
                            evidence={"judge": ans, "rules": c.get("rules"), "found": c.get("evidence"),
                                      "asked_because": (text or "").rsplit("Asked because: ", 1)[-1][:300]},
                            call_id=call, run_id=run_id):
                out["queued"] += 1
    return out


# ---- the owner's answer -----------------------------------------------------------------------------------------------

def merge(cur: Any, book: I.Book, old: str, new: str, *, queue_id: Any = None, call_id: Any = None,
          evidence: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The owner's `same` on a rename item: the older cluster's root redirects into the newer one's (kind 'rename',
    by the owner), whatever their sizes, so the newer name is the one shown and the older is its earlier name."""
    ro, rn = book.root(old), book.root(new)
    if ro == rn or ro is None or rn is None:
        return None
    got = I._savepoint(cur, """INSERT INTO mx_entity_redirects (from_id, to_id, by, automatic, call_id, queue_id, evidence, kind)
                               VALUES (%s, %s, 'owner', false, %s, %s, %s::jsonb, 'rename') RETURNING id::text""",
                       (ro, rn, call_id, queue_id, json.dumps(evidence or {}, default=str)))
    if got is None:
        return None
    book.redirect[ro] = (rn, False)
    return got[0]


def earlier(cur: Any, book: I.Book, root: str) -> List[Dict[str, Any]]:
    """The earlier names of a cluster (its current rename redirects): [{id, name, names, members}], oldest first by
    when the rename was answered. `members`: the entities under the earlier name (the redirect's from side)."""
    members = set(book.cluster(root))
    if len(members) < 2:
        return []
    cur.execute("""SELECT id::text, from_id::text, to_id::text, at FROM mx_entity_redirects
                    WHERE kind = 'rename' AND undone_at IS NULL AND from_id = ANY(%s::uuid[]) ORDER BY at, id""",
                (sorted(members),))
    rows = cur.fetchall()
    if not rows:
        return []
    into: Dict[str, List[str]] = defaultdict(list)
    for frm, (to, _) in book.redirect.items():
        into[to].append(frm)
    out = []
    for rid, frm, _to, at in rows:
        sub, todo = {frm}, [frm]
        while todo:
            x = todo.pop()
            for y in into.get(x, ()):
                if y not in sub:
                    sub.add(y)
                    todo.append(y)
        sub = {x for x in sub if x in book.ents}
        e = book.ents.get(frm)
        out.append({"redirect": rid, "id": frm, "name": (e.shown_name or e.name) if e else None,
                    "names": sorted({book.ents[x].name for x in sub}), "members": sorted(sub), "at": at})
    return out


def earlier_members(cur: Any) -> Set[str]:
    """Every entity under an earlier name (the from side of a current rename redirect, and what redirects into it)."""
    cur.execute("SELECT from_id::text FROM mx_entity_redirects WHERE kind = 'rename' AND undone_at IS NULL")
    return {r[0] for r in cur.fetchall()}


__all__ = ["address", "candidates", "earlier", "guard", "merge", "rename_input", "stage"]
