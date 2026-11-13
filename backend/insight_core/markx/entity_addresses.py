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


def _names(book: I.Book, roots: Set[Optional[str]]) -> Dict[str, Set[str]]:
    """{root: the name keys that name it: its members' own keys and every alias of them}, of `roots` (v10.17.2, 0204:
    the roots the run's mentions name, not every root of the book at each run)."""
    out: Dict[str, Set[str]] = defaultdict(set)
    for eid, e in book.ents.items():
        r = book.root(eid)
        if r in roots:
            out[r].add(e.key)
    for k, eid in book.alias.items():
        r = book.root(eid)
        if r in roots:
            out[r].add(k)
    return out


def _makers(book: I.Book, root: str) -> Set[str]:
    """The name keys of who makes it: its members' stated maker and their parent (a thing's maker entity). Its
    members are its cluster (v10.17, 0186: not a walk of the book; v10.17.2, 0204: no book.members() of every root)."""
    out: Set[str] = set()
    for eid in book.cluster(root):
        e = book.ents[eid]
        if e.maker:
            out.add(N.key(e.maker))
        if e.parent and e.level == "thing" and e.parent in book.ents:
            out.add(book.ents[book.root(e.parent) or e.parent].key)
    return {m for m in out if m}


def _mentions(cur: Any, post_ids: Optional[List[str]], after: Optional[str] = None) -> List[Tuple]:
    """The linked mentions of the specific types, of `post_ids` (None: every post), or `after` that post as well."""
    from insight_core.markx import schemas
    from insight_core.markx.pairing import SPECIFIC_TYPES
    if after is not None:
        where = "AND (m.post_id > %(after)s::uuid OR m.post_id = ANY(%(ids)s::uuid[]))"
    else:
        where = "AND m.post_id = ANY(%(ids)s::uuid[])" if post_ids is not None else ""
    cur.execute(f"""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.type, m.ref, m.span, m.name
                      FROM mx_mentions_now m
                     WHERE m.guide = ANY(%(g)s) AND m.entity_id IS NOT NULL AND m.type = ANY(%(t)s) {where}""",
                {"g": schemas.mention_guides(), "t": schemas.stored_types(SPECIFIC_TYPES), "ids": list(post_ids or []),
                 "after": after})
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
                  names: Set[str], makers: Set[str]) -> List[Tuple[str, str, str, Optional[str]]]:
    """[(kind, address, rule, owner)] one mention's post gives its entity, by the rules; `owner` is a platform page's
    owner segment when its thing is the entity's name (rule `repo`'s maker candidate), else None."""
    from insight_core.markx import citations, schemas
    t = schemas.entity_type(type_)
    urls = [u for u, _ in links]
    out: List[Tuple[str, str, str, Optional[str]]] = []
    paper = R.by_identifier(ref=ref, span_ids=citations.ids_in(f"{span} {name}"), links=urls, documents=documents,
                            is_document=t == "document")
    if paper:
        out.append((R.PAPER, paper, R.IDENTIFIER, None))
        for kind in (R.CODE, R.DEMO):   # the paper's own links: one of each in the post that gives it
            same = sorted({u for u in urls if R.address_kind(u) == kind})
            if len(same) == 1:
                out.append((kind, same[0], R.IDENTIFIER, None))
    for url, text in links:
        title = titles.get(url) or text
        if R.is_home(url):   # never an address, but a document's work site (E2): its front page is the work
            rule = R.by_site(url, title, names, N.key, N.squash) if t == "document" else None
            if rule:
                out.append((R.WORK, url, rule, None))
            continue
        repo = R.by_repo(url, names, N.key, N.squash)   # v10.13.5: a platform's page of one thing named as it
        kind = repo[0] if repo else R.address_kind(url)
        owner = repo[1] if repo else None
        if not repo and kind == R.RELEASE and R.not_a_release(url):
            continue
        if R.by_title(title, names, N.key):
            out.append((kind, url, R.TITLE, owner))
        elif repo:
            out.append((kind, url, R.REPO, owner))
        elif t in R.MAKER_TYPES and R.by_maker(url, title, makers=makers, names=names, squash=N.squash):
            out.append((kind, url, R.MAKER, None))
    return out


def stage(cur: Any, *, now: datetime, since: Optional[datetime], full: bool, after: Optional[str] = None,
          deadline: Optional[float] = None, also: Iterable[str] = (), book: Optional[I.Book] = None) -> Dict[str, Any]:
    """Find and store the addresses of the posts whose current set came since `since` and the posts in `also` (the
    posts whose mentions the run linked: v10.13.9, a run that stops at its budget links the rest later, after their
    set came). `full` or no `since`: a sweep of every post, in post id order; `after` resumes a sweep past that post.
    A sweep stops after the chunk of CHUNK posts that passes `deadline` (a time.monotonic() value) and says where
    ({done: false, after}); the run's own posts are done first, always. Returns {posts, found, added, by_rule, done,
    after}."""
    import time
    sweep = full or since is None or after is not None
    first: Set[str] = set(also)
    if since is not None and not full:
        cur.execute("SELECT post_id::text FROM mx_mention_sets WHERE at >= %s", (since - MARGIN,))
        first |= {r[0] for r in cur.fetchall()}
    empty = {"posts": 0, "found": 0, "added": 0, "by_rule": {}, "done": True, "after": None}
    if not sweep and not first:
        return empty
    # a resumed sweep reads the posts past where it stopped (and the run's own), not every post again
    rows = _mentions(cur, sorted(first), after) if after is not None else \
        _mentions(cur, None if sweep else sorted(first))
    if not rows:
        return empty
    book = book if book is not None else I.load_book(cur)
    names = _names(book, {book.root(book.pins.get((r[0], r[1], r[2]), r[3])) for r in rows})
    makers: Dict[str, Set[str]] = {}
    have = {r[0] for r in rows}
    head = sorted(have & first)
    rest = sorted(p for p in have - first if after is None or p > after) if sweep else []
    found: Dict[Tuple[str, str], Tuple[str, str, str, Optional[str]]] = {}
    by_rule: Dict[str, int] = defaultdict(int)
    by_post: Dict[str, List[Tuple]] = defaultdict(list)   # v10.13.4: each chunk reads its own posts' rows, not all
    for r in rows:
        by_post[r[0]].append(r)
    chunks = [head[k:k + CHUNK] for k in range(0, len(head), CHUNK)]
    n_head = len(chunks)
    chunks += [rest[k:k + CHUNK] for k in range(0, len(rest), CHUNK)]
    done_posts, last, done = 0, after, True
    for k, chunk in enumerate(chunks):
        links = _links(cur, chunk)
        docs = _documents(cur, chunk)
        titles = _titles(cur, {u for pid in chunk for u, _ in links.get(pid, ())})
        for pid, guide, n, eid, type_, ref, span, name in (r for p in chunk if links.get(p) for r in by_post[p]):
            root = book.root(book.pins.get((pid, guide, n), eid))
            if root not in book.ents or book.ents[root].status == "not_entity":
                continue
            if root not in makers:
                makers[root] = _makers(book, root)   # its cluster (0186: not a walk), not book.members()
            for kind, url, rule, owner in found_in_post(root=root, type_=type_, ref=ref, span=span or "", name=name or "",
                                                 links=links[pid], titles=titles, documents=docs.get(pid, 0),
                                                 names=names.get(root, set()), makers=makers[root]):
                found.setdefault((root, url), (kind, rule, pid, owner))
        done_posts += len(chunk)
        if k >= n_head:
            last = chunk[-1]
        if n_head <= k < len(chunks) - 1 and deadline is not None and time.monotonic() > deadline:
            done = False   # the sweep's posts left are the next run's (it stops only after one of its own chunks)
            break
    added = 0
    for (root, url), (kind, rule, pid, owner) in sorted(found.items()):
        cur.execute("""INSERT INTO mx_entity_addresses (entity_id, url, kind, rule, post_id, first_at, owner)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (entity_id, url) DO NOTHING""",
                    (root, url, kind, rule, pid, now, owner))
        added += cur.rowcount
        by_rule[rule] += 1
    return {"posts": done_posts, "found": len(found), "added": added, "by_rule": dict(by_rule), "done": done,
            "after": None if done else last}


def add(cur: Any, *, root: str, url: str, kind: str, rule: str, post_id: Optional[str], now: datetime) -> bool:
    """One address found otherwise (C's lookup)."""
    cur.execute("""INSERT INTO mx_entity_addresses (entity_id, url, kind, rule, post_id, first_at)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (entity_id, url) DO NOTHING""",
                (root, url, kind, rule, post_id, now))
    return cur.rowcount > 0


def current(cur: Any, book: I.Book, roots: Optional[Iterable[str]] = None) -> Dict[str, List[Tuple[str, str, str, Any, Optional[str]]]]:
    """{root: [(kind, url, rule, first_at, post_id)]}: the stored addresses read through the merges, each kept only
    while its post still names that root in its current set (a lookup's, with no post, always); rule `repo`'s rows
    of one kind under 2+ owners only the stated maker's (R.one_owner)."""
    return {root: [r[:5] for r in rows] for root, rows in _current(cur, book, roots).items()}


def _current(cur: Any, book: I.Book, roots: Optional[Iterable[str]]) -> Dict[str, List[Tuple]]:
    """current's rows with the owner last: (kind, url, rule, first_at, post_id, owner)."""
    roots = None if roots is None else set(roots)
    cols = "entity_id::text, url, kind, rule, first_at, post_id::text, owner"
    if roots is not None:
        members = sorted({e for r in roots for e in book.cluster(r)})   # v10.17 (0186): not a walk of the book
        cur.execute(f"SELECT {cols} FROM mx_entity_addresses WHERE entity_id = ANY(%s::uuid[])", (members,))
    else:
        cur.execute(f"SELECT {cols} FROM mx_entity_addresses")
    rows = cur.fetchall()
    book.prime(ids=[r[0] for r in rows])   # v10.17 (0186): a page's book reads them in one go
    posts = sorted({r[5] for r in rows if r[5]})
    named: Set[Tuple[str, str]] = set()
    if posts:
        from insight_core.markx import schemas
        cur.execute("""SELECT post_id::text, guide, n, entity_id::text FROM mx_mentions_now
                        WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""",
                    (schemas.mention_guides(), posts))
        named = {(pid, book.root(book.pins.get((pid, g, n), eid))) for pid, g, n, eid in cur.fetchall()}
    out: Dict[str, List[Tuple]] = defaultdict(list)
    for eid, url, kind, rule, at, pid, owner in rows:
        root = book.root(eid)
        if roots is not None and root not in roots:
            continue
        if pid and (pid, root) not in named:
            continue
        out[root].append((kind, url, rule, at, pid, owner))
    for root, got in out.items():   # a fork or a namesake: 2+ owners of one kind keep the stated maker's only
        repo = [(k, u, o) for k, u, r, _, _, o in got if r == R.REPO]
        if len({(k, N.squash((o or "").casefold())) for k, _, o in repo}) > len({k for k, _, _ in repo}):
            keep = R.one_owner(repo, _makers(book, root), N.squash)   # v10.17 (0186): its cluster, not book.members()
            out[root] = [g for g in got if g[2] != R.REPO or g[1] in keep]
    return out


def of_root(cur: Any, book: I.Book, root: str) -> Dict[str, Dict[str, Any]]:
    """{kind: {url, rule, first_at, post_id, owner}} of one entity: one address a kind (the rules' order); `owner` is
    a platform page's owner segment (rule `repo`'s maker candidate), else None."""
    rows = _current(cur, book, [root]).get(root, [])
    picked = R.pick((k, u, r, at) for k, u, r, at, _, _ in rows)
    posts = {(k, u): (pid, owner) for k, u, _, _, pid, owner in rows}
    return {k: {"url": u, "rule": r, "first_at": at, "post_id": posts.get((k, u), (None, None))[0],
                "owner": posts.get((k, u), (None, None))[1]} for k, (u, r, at) in picked.items()}


__all__ = ["add", "current", "found_in_post", "of_root", "stage"]
