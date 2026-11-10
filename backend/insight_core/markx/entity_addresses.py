"""An entity's addresses (issue 0138 A): the links its posts carry that are that thing's own page, by the rules of
utils/entity_originals.py, with no request. Written to mx_entity_addresses by the decision run's entity stage
(entity_stage.entities, after identity's linking): incrementally, the posts whose current mention set came since the
last run; on the full pass, every post. One row an (entity, address), never deleted; a row is written under the
entity's root then, and every reader reads it through the merges (`of_root`) and only while its post still names the
entity in its current set (a later guide's reading may not).

    counts = stage(cur, now=now, since=since, full=False)
    found = of_root(cur, book, root)        # {kind: {url, rule, post_id, first_at}}, original first
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.utils import entity_originals as R

MARGIN = timedelta(minutes=2)
CHUNK = 2000


def _names(book: I.Book) -> Dict[str, Set[str]]:
    """{root: the name keys that name it: its members' own keys and every alias of them}."""
    out: Dict[str, Set[str]] = defaultdict(set)
    for eid, e in book.ents.items():
        out[book.root(eid)].add(e.key)
    for k, eid in book.alias.items():
        out[book.root(eid)].add(k)
    return out


def _makers(book: I.Book, root: str) -> Set[str]:
    """The name keys of who makes it: its members' stated maker and their parent (a thing's maker entity)."""
    out: Set[str] = set()
    for eid, e in book.ents.items():
        if book.root(eid) != root:
            continue
        if e.maker:
            out.add(N.key(e.maker))
        if e.parent and e.level == "thing" and e.parent in book.ents:
            out.add(book.ents[book.root(e.parent) or e.parent].key)
    return {m for m in out if m}


def _mentions(cur: Any, post_ids: Optional[List[str]]) -> List[Tuple]:
    from insight_core.markx import schemas
    from insight_core.markx.candidates import SPECIFIC_TYPES
    where = "AND m.post_id = ANY(%(ids)s::uuid[])" if post_ids is not None else ""
    cur.execute(f"""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.type, m.ref, m.span, m.name
                      FROM mx_mentions_now m
                     WHERE m.guide = ANY(%(g)s) AND m.entity_id IS NOT NULL AND m.type = ANY(%(t)s) {where}""",
                {"g": schemas.mention_guides(), "t": schemas.stored_types(SPECIFIC_TYPES), "ids": post_ids})
    return cur.fetchall()


def _documents(cur: Any, post_ids: List[str]) -> Dict[str, int]:
    from insight_core.markx import schemas
    cur.execute("""SELECT post_id::text, count(*) FROM mx_mentions_now WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[])
                      AND type = ANY(%s) AND name_key <> '' GROUP BY 1""",
                (schemas.mention_guides(), post_ids, schemas.stored_types(["document"])))
    return dict(cur.fetchall())


def _links(cur: Any, post_ids: List[str]) -> Dict[str, List[Tuple[str, Optional[str]]]]:
    """{post: [(address, the link's own words)]}: its kept links, not boilerplate, not a reference list's."""
    cur.execute("""SELECT post_id::text, target_url, link_text FROM post_links
                    WHERE post_id = ANY(%s::uuid[]) AND NOT boilerplate AND kind = 'link' ORDER BY post_id, position""",
                (post_ids,))
    out: Dict[str, List[Tuple[str, Optional[str]]]] = defaultdict(list)
    for pid, url, text in cur.fetchall():
        out[pid].append((url, text))
    return out


def _titles(cur: Any, urls: Iterable[str]) -> Dict[str, str]:
    """A page's read title (0113's rule 8): Discover's read of it, else a stored post's at that address."""
    from insight_core.db.repo_discover import DiscoverRepository
    urls = sorted(set(urls))
    if not urls:
        return {}
    out = dict(DiscoverRepository.read_titles(cur, urls))
    cur.execute("SELECT normalized_url, title FROM posts WHERE normalized_url = ANY(%s) AND title IS NOT NULL", (urls,))
    for url, title in cur.fetchall():
        out.setdefault(url, title)
    return out


def found_in_post(*, root: str, type_: Optional[str], ref: Optional[str], span: str, name: str,
                  links: List[Tuple[str, Optional[str]]], titles: Dict[str, str], documents: int,
                  names: Set[str], makers: Set[str]) -> List[Tuple[str, str, str]]:
    """[(kind, address, rule)] one mention's post gives its entity, by the three rules."""
    from insight_core.markx import citations, schemas
    t = schemas.entity_type(type_)
    urls = [u for u, _ in links]
    out: List[Tuple[str, str, str]] = []
    paper = R.by_identifier(ref=ref, span_ids=citations.ids_in(f"{span} {name}"), links=urls, documents=documents,
                            is_document=t == "document")
    if paper:
        out.append((R.PAPER, paper, R.IDENTIFIER))
        for kind in (R.CODE, R.DEMO):   # the paper's own links: one of each in the post that gives it
            same = sorted({u for u in urls if R.address_kind(u) == kind})
            if len(same) == 1:
                out.append((kind, same[0], R.IDENTIFIER))
    for url, text in links:
        title = titles.get(url) or text
        if R.is_home(url):   # never an address, but a document's work site (E2): its front page is the work
            rule = R.by_site(url, title, names, N.key, N.squash) if t == "document" else None
            if rule:
                out.append((R.WORK, url, rule))
            continue
        kind = R.address_kind(url)
        if kind == R.RELEASE and R.not_a_release(url):
            continue
        if R.by_title(title, names, N.key):
            out.append((kind, url, R.TITLE))
        elif t in R.MAKER_TYPES and R.by_maker(url, title, makers=makers, names=names, squash=N.squash):
            out.append((kind, url, R.MAKER))
    return out


def stage(cur: Any, *, now: datetime, since: Optional[datetime], full: bool) -> Dict[str, Any]:
    """Find and store the addresses of the posts whose current set came since `since` (every post when `full` or
    there is no `since`). Returns {posts, found, added, by_rule}."""
    if full or since is None:
        post_ids = None
    else:
        cur.execute("SELECT post_id::text FROM mx_mention_sets WHERE at >= %s", (since - MARGIN,))
        post_ids = [r[0] for r in cur.fetchall()]
        if not post_ids:
            return {"posts": 0, "found": 0, "added": 0, "by_rule": {}}
    rows = _mentions(cur, post_ids)
    if not rows:
        return {"posts": 0, "found": 0, "added": 0, "by_rule": {}}
    book = I.load_book(cur)
    names = _names(book)
    makers: Dict[str, Set[str]] = {}
    ids = sorted({r[0] for r in rows})
    found: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    by_rule: Dict[str, int] = defaultdict(int)
    by_post: Dict[str, List[Tuple]] = defaultdict(list)   # v10.13.4: each chunk reads its own posts' rows, not all
    for r in rows:
        by_post[r[0]].append(r)
    for k in range(0, len(ids), CHUNK):
        chunk = ids[k:k + CHUNK]
        links = _links(cur, chunk)
        docs = _documents(cur, chunk)
        titles = _titles(cur, {u for pid in chunk for u, _ in links.get(pid, ())})
        for pid, guide, n, eid, type_, ref, span, name in (r for p in chunk if links.get(p) for r in by_post[p]):
            root = book.root(book.pins.get((pid, guide, n), eid))
            if root not in book.ents or book.ents[root].status == "not_entity":
                continue
            if root not in makers:
                makers[root] = _makers(book, root)
            for kind, url, rule in found_in_post(root=root, type_=type_, ref=ref, span=span or "", name=name or "",
                                                 links=links[pid], titles=titles, documents=docs.get(pid, 0),
                                                 names=names.get(root, set()), makers=makers[root]):
                found.setdefault((root, url), (kind, rule, pid))
    added = 0
    for (root, url), (kind, rule, pid) in sorted(found.items()):
        cur.execute("""INSERT INTO mx_entity_addresses (entity_id, url, kind, rule, post_id, first_at)
                       VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (entity_id, url) DO NOTHING""",
                    (root, url, kind, rule, pid, now))
        added += cur.rowcount
        by_rule[rule] += 1
    return {"posts": len(ids), "found": len(found), "added": added, "by_rule": dict(by_rule)}


def add(cur: Any, *, root: str, url: str, kind: str, rule: str, post_id: Optional[str], now: datetime) -> bool:
    """One address found otherwise (C's lookup)."""
    cur.execute("""INSERT INTO mx_entity_addresses (entity_id, url, kind, rule, post_id, first_at)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (entity_id, url) DO NOTHING""",
                (root, url, kind, rule, post_id, now))
    return cur.rowcount > 0


def current(cur: Any, book: I.Book, roots: Optional[Iterable[str]] = None) -> Dict[str, List[Tuple[str, str, str, Any, Optional[str]]]]:
    """{root: [(kind, url, rule, first_at, post_id)]}: the stored addresses read through the merges, each kept only
    while its post still names that root in its current set (a lookup's, with no post, always)."""
    roots = None if roots is None else set(roots)
    if roots is not None:
        members = sorted(e for e in book.ents if book.root(e) in roots)
        cur.execute("""SELECT entity_id::text, url, kind, rule, first_at, post_id::text FROM mx_entity_addresses
                        WHERE entity_id = ANY(%s::uuid[])""", (members,))
    else:
        cur.execute("SELECT entity_id::text, url, kind, rule, first_at, post_id::text FROM mx_entity_addresses")
    rows = cur.fetchall()
    posts = sorted({r[5] for r in rows if r[5]})
    named: Set[Tuple[str, str]] = set()
    if posts:
        from insight_core.markx import schemas
        cur.execute("""SELECT post_id::text, guide, n, entity_id::text FROM mx_mentions_now
                        WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""",
                    (schemas.mention_guides(), posts))
        named = {(pid, book.root(book.pins.get((pid, g, n), eid))) for pid, g, n, eid in cur.fetchall()}
    out: Dict[str, List[Tuple[str, str, str, Any, Optional[str]]]] = defaultdict(list)
    for eid, url, kind, rule, at, pid in rows:
        root = book.root(eid)
        if roots is not None and root not in roots:
            continue
        if pid and (pid, root) not in named:
            continue
        out[root].append((kind, url, rule, at, pid))
    return out


def of_root(cur: Any, book: I.Book, root: str) -> Dict[str, Dict[str, Any]]:
    """{kind: {url, rule, first_at, post_id}} of one entity: one address a kind (the rules' order)."""
    rows = current(cur, book, [root]).get(root, [])
    picked = R.pick((k, u, r, at) for k, u, r, at, _ in rows)
    posts = {(k, u): pid for k, u, _, _, pid in rows}
    return {k: {"url": u, "rule": r, "first_at": at, "post_id": posts.get((k, u))} for k, (u, r, at) in picked.items()}


__all__ = ["add", "current", "found_in_post", "of_root", "stage"]
