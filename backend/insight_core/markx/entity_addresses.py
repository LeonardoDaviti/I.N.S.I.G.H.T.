"""An entity's addresses: the links its posts carry that are that thing's own page, by utils/entity_originals.py's
rules, with no request. `stage` (the entity stage, after linking) writes mx_entity_addresses, one row an (entity,
address), never deleted; readers (`current`, `of_root`, `page`) read rows through the merges and only while their
post still names the entity in its current set.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.utils import entity_originals as R

MARGIN = timedelta(minutes=2)
CHUNK = 2000


def _names(book: I.Book, roots: Set[Optional[str]]) -> Dict[str, Set[str]]:
    """{root: the name keys that name it: its members' own keys and their aliases}, of `roots` only."""
    return book.names_of(roots)


def _makers(book: I.Book, root: str) -> Set[str]:
    """The name keys of who makes it: its cluster's stated makers and a thing's parent entity."""
    out: Set[str] = set()
    for eid in book.cluster(root):
        e = book.ents[eid]
        if e.maker:
            out.add(N.key(e.maker))
        if e.parent and e.level == "thing" and e.parent in book.ents:
            out.add(book.ents[book.root(e.parent) or e.parent].key)
    return {m for m in out if m}


FROM_START = "00000000-0000-0000-0000-000000000000"   # a sweep waiting to start resumes after it


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
    """A page's read title: Discover's read of it, else a stored post's at that address."""
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
                  names: Set[str], makers: Set[str],
                  known: Optional[Any] = None) -> List[Tuple[str, str, str, Optional[str]]]:
    """[(kind, address, rule, owner)] one mention's post gives its entity, by the rules; `owner` is a platform page's
    owner segment when its thing is the entity's name (rule `repo`'s maker candidate), else None. A page the post
    only cites has kind R.CITED."""
    from insight_core.markx import citations, schemas
    t = schemas.entity_type(type_)
    urls = [u for u, _ in links]
    words = {u: w for u, w in links if w}
    out: List[Tuple[str, str, str, Optional[str]]] = []
    span_ids = citations.ids_in(f"{span} {name}")
    paper = R.by_identifier(ref=ref, span_ids=span_ids, links=urls, documents=documents, is_document=t == "document")
    if paper:
        own = R.paper_is_its_own(carried=R.carries_id(ref, span_ids), title=titles.get(paper), words=words.get(paper),
                                 url=paper, names=names, key=N.key)
        out.append((R.PAPER if own else R.CITED, paper, R.IDENTIFIER, None))
        for kind in (R.CODE, R.DEMO):   # the paper's own links: one of each in the post that gives it
            same = sorted({u for u in urls if R.address_kind(u) == kind})
            if len(same) == 1:
                out.append((kind if own else R.CITED, same[0], R.IDENTIFIER, None))
    for url, text in links:
        title = titles.get(url) or text
        if R.conversation(url):   # a chat with an app is nobody's page, not even one its post cites
            continue
        if R.is_home(url):   # never an address, but a document's work site: its front page is the work
            rule = R.by_site(url, title, names, N.key, N.squash) if t == "document" else None
            if rule:
                out.append((R.WORK, url, rule, None))
            continue
        repo = R.by_repo(url, names, N.key, N.squash)   # a platform's page of one thing named as it
        kind = repo[0] if repo else R.address_kind(url)
        owner = repo[1] if repo else None
        if not repo and kind == R.RELEASE and R.not_a_release(url):
            continue
        if R.by_title(title, names, N.key):
            # a page titled with its name is its own on its own or its maker's site, else a page its post cites; a
            # platform page is whose it is under (R.platform_page_own); a document's titled page is it anywhere
            platform = R.platform_page_own(url, repo=repo, names=names, makers=makers, squash=N.squash) \
                if t in R.MAKER_TYPES else None
            if platform is not None:
                cited = not platform
            else:
                cited = kind == R.RELEASE and t in R.MAKER_TYPES and not R.own_site(url, names | makers, N.squash)
            out.append((R.CITED if cited else kind, url, R.TITLE, owner))
        elif repo:
            out.append((kind, url, R.REPO, owner))
        elif t in R.MAKER_TYPES and R.by_maker(url, title, makers=makers, names=names, squash=N.squash,
                                                           known=known):
            out.append((kind, url, R.MAKER, None))
    return out


def stage(cur: Any, *, now: datetime, since: Optional[datetime], full: bool, after: Optional[str] = None,
          deadline: Optional[float] = None, also: Iterable[str] = (), book: Optional[I.Book] = None) -> Dict[str, Any]:
    """Find and store the addresses of the posts whose current set came since `since` and the posts in `also` (those
    the run linked). `full` or no `since`: a sweep of every post in id order; `after` resumes a sweep past that post.
    A sweep starts no chunk past `deadline` (time.monotonic()) and says where it stopped ({done: false, after}); the
    run's own posts always go first. Returns {posts, found, added, changed, demoted, by_rule, done, after}."""
    sweep = full or since is None or after is not None
    # no time left: the run's own posts only; the sweep waits where it is for a run with time left (0221)
    waits = after or FROM_START if sweep and deadline is not None and time.monotonic() > deadline else None
    if waits is not None:
        sweep, after = False, None
    first: Set[str] = set(also)
    if since is not None and not full:
        cur.execute("SELECT post_id::text FROM mx_mention_sets WHERE at >= %s", (since - MARGIN,))
        first |= {r[0] for r in cur.fetchall()}
    empty = {"posts": 0, "found": 0, "added": 0, "changed": 0, "by_rule": {}, "done": waits is None, "after": waits}
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
    seen: Dict[Tuple[str, str], Set[str]] = defaultdict(set)   # the posts that gave each (entity, address)
    by_rule: Dict[str, int] = defaultdict(int)
    by_post: Dict[str, List[Tuple]] = defaultdict(list)   # each chunk reads its own posts' rows
    for r in rows:
        by_post[r[0]].append(r)
    chunks = [head[k:k + CHUNK] for k in range(0, len(head), CHUNK)]
    n_head = len(chunks)
    chunks += [rest[k:k + CHUNK] for k in range(0, len(rest), CHUNK)]
    done_posts, last, done, demoted = 0, after, True, 0
    for k, chunk in enumerate(chunks):
        links = _links(cur, chunk)
        docs = _documents(cur, chunk)
        titles = _titles(cur, {u for pid in chunk for u, _ in links.get(pid, ())})
        gave_none: Set[Tuple[str, str, str]] = set()   # (entity, address, post) the post gives nothing of
        for pid, guide, n, eid, type_, ref, span, name in (r for p in chunk if links.get(p) for r in by_post[p]):
            root = book.root(book.pins.get((pid, guide, n), eid))
            if root not in book.ents or book.ents[root].status == "not_entity":
                continue
            if root not in makers:
                makers[root] = _makers(book, root)
            gave = found_in_post(root=root, type_=type_, ref=ref, span=span or "", name=name or "",
                                 links=links[pid], titles=titles, documents=docs.get(pid, 0),
                                 names=names.get(root, set()), makers=makers[root],
                                 known=lambda k: book.by_key(k) is not None)
            given = {u for _, u, _, _ in gave}
            gave_none.update((root, u, pid) for u, _ in links[pid] if u not in given)
            for kind, url, rule, owner in gave:
                had = found.get((root, url))
                if had is None or (had[0] == R.CITED and kind != R.CITED):   # a post naming it as its own wins
                    found[(root, url)] = (kind, rule, pid, owner)
                seen[(root, url)].add(pid)
        demoted += _demote(cur, gave_none)
        done_posts += len(chunk)
        if k >= n_head:
            last = chunk[-1]
        if n_head <= k + 1 < len(chunks) and deadline is not None and time.monotonic() > deadline:
            done = False   # the sweep's posts left are the next run's
            break
    added = changed = 0
    for (root, url), (kind, rule, pid, owner) in sorted(found.items()):
        # one row an (entity, address), first_at kept; its kind follows the posts that gave it: own beats cited, and
        # an own row becomes cited only when its own post now gives it as cited
        cur.execute("""INSERT INTO mx_entity_addresses AS a (entity_id, url, kind, rule, post_id, first_at, owner)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (entity_id, url) DO UPDATE
                          SET kind = EXCLUDED.kind, rule = EXCLUDED.rule, post_id = EXCLUDED.post_id, owner = EXCLUDED.owner
                        WHERE a.kind IS DISTINCT FROM EXCLUDED.kind
                          AND ((a.kind = 'cited') OR (EXCLUDED.kind = 'cited' AND a.post_id = ANY(%s::uuid[])))
                    RETURNING (xmax = 0)""",
                    (root, url, kind, rule, pid, now, owner, sorted(seen[(root, url)])))
        got = cur.fetchone()
        if got is not None:
            added += 1 if got[0] else 0
            changed += 0 if got[0] else 1
        by_rule[rule] += 1
    if waits is not None:
        done, last = False, waits
    return {"posts": done_posts, "found": len(found), "added": added, "changed": changed, "demoted": demoted,
            "by_rule": dict(by_rule), "done": done, "after": None if done else last}


def _demote(cur: Any, gave_none: Set[Tuple[str, str, str]]) -> int:
    """A row taken as its own whose own post, read again, no longer gives that address becomes `cited`; never
    removed. A post giving it as its own later in the run makes it its own again (the upsert after)."""
    rows = sorted(gave_none)
    n = 0
    for k in range(0, len(rows), 20000):
        part = rows[k:k + 20000]
        cur.execute("""UPDATE mx_entity_addresses a SET kind = 'cited'
                         FROM unnest(%s::uuid[], %s::text[], %s::uuid[]) AS x(e, u, p)
                        WHERE a.entity_id = x.e AND a.url = x.u AND a.post_id = x.p AND a.kind <> 'cited'""",
                    ([r[0] for r in part], [r[1] for r in part], [r[2] for r in part]))
        n += max(cur.rowcount or 0, 0)
    return n


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
        members = sorted({e for r in roots for e in book.cluster(r)})
        cur.execute(f"SELECT {cols} FROM mx_entity_addresses WHERE entity_id = ANY(%s::uuid[])", (members,))
    else:
        cur.execute(f"SELECT {cols} FROM mx_entity_addresses")
    rows = cur.fetchall()
    book.prime(ids=[r[0] for r in rows])   # a page's book reads them in one go
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
        if R.conversation(url):   # a row an older rule took from a chat with an app
            continue
        out[root].append((kind, url, rule, at, pid, owner))
    for root, got in out.items():   # a fork or a namesake: 2+ owners of one kind keep the stated maker's only
        repo = [(k, u, o) for k, u, r, _, _, o in got if r == R.REPO]
        if len({(k, N.squash((o or "").casefold())) for k, _, o in repo}) > len({k for k, _, _ in repo}):
            keep = R.one_owner(repo, _makers(book, root), N.squash)
            out[root] = [g for g in got if g[2] != R.REPO or g[1] in keep]
        # a platform page under the stated maker wins over another owner's page of that kind (a namesake's)
        plat = [(g[0], R.repository(g[1])) for g in out[root] if g[0] != R.CITED and R.platform_owned(g[1])]
        if len({o for _, (o, _) in plat}) > 1:
            makers = list(_makers(book, root))
            theirs = {k for k, (o, _) in plat if R.owner_agrees(o, makers, N.squash)}
            out[root] = [g for g in out[root] if g[0] not in theirs or not R.platform_owned(g[1])
                         or R.owner_agrees(R.repository(g[1])[0], makers, N.squash)]
    return out


def of_root(cur: Any, book: I.Book, root: str) -> Dict[str, Dict[str, Any]]:
    """{kind: {url, rule, first_at, post_id, owner}} of one entity: one address a kind (the rules' order); `owner` is
    a platform page's owner segment (rule `repo`'s maker candidate), else None."""
    return page(cur, book, root)[0]


def page(cur: Any, book: I.Book, root: str) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """(of_root's {kind: ...}, the pages its posts cite: [{url, kind, rule, post_id}] oldest first), from one read."""
    rows = _current(cur, book, [root]).get(root, [])
    picked = R.pick((k, u, r, at) for k, u, r, at, _, _ in rows)
    posts = {(k, u): (pid, owner) for k, u, _, _, pid, owner in rows}
    own = {k: {"url": u, "rule": r, "first_at": at, "post_id": posts.get((k, u), (None, None))[0],
               "owner": posts.get((k, u), (None, None))[1]} for k, (u, r, at) in picked.items()}
    cited = [{"url": u, "kind": R.address_kind(u), "rule": r, "post_id": pid}
             for k, u, r, at, pid, _ in sorted(rows, key=lambda x: (x[3] is None, x[3].timestamp() if x[3] else 0, x[1]))
             if k == R.CITED]
    return own, cited


__all__ = ["add", "current", "found_in_post", "of_root", "page", "stage"]
