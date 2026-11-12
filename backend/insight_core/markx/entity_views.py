"""What the Mark X page reads about entities (issue 0119 A3, 0115 as decided): the list, an entity's page, the review
queue and its history. Read only; everything is read through the merges (redirects) and the owner's splits (pins), so
an answer in the queue shows at once.

  - **The list** (`entity_list`): one list over the News window (30 days), ranked like News: distinct voices, then
    reports (posts where it is the subject or the actor) against mentions, then the newest post. Each row: name,
    type, maker, the exact version, sources and posts, its Mark X stories, its 3 newest posts, when last seen, and its
    surges. Read state never hides anything: a read post is only marked read.
  - **The page** (`entity_page`): every post in every role, the role on each line, grouped by its Mark X stories
    ordered like News (voices, then the newest post), the posts in no story last; every source with its counts; the
    family and its versions as links (a family's page lists every version).
  - **The queue** (`queue`): the open items, each with both names, 2 posts each, the proposal and its evidence; and
    the history: answered items and the merges (automatic ones can be undone). 0164 A: each side carries its group
    (`group`: the cluster's shown name and type, names and sides) and an alias item what `same` would do (`join`).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.markx import surges as S

WINDOW_DAYS = 30
LIST_LIMIT = 200
ROLE_REPORT = ("subject", "actor")
ACCURACY = {
    "merges": "automatic merges 97.6% right on unseen posts (40/41, Wilson 87-100%; lab, 2026-11-06); merges by two "
              "agreeing opinions 71/71 (lab and your answers, 0130)",
    "surges": f"surges {S.PRECISION}",
    "collisions": "collision splits 55% right (6/11, lab): each is a question, never applied by itself",
}


def _guide() -> List[str]:
    """0133: every entities guide; the views read each post's current set (mx_mentions_now) whichever it is."""
    from insight_core.markx import schemas
    return schemas.mention_guides()


def _rows(cur: Any, guide: List[str], since: Optional[datetime], entity_ids: Optional[Iterable[str]] = None):
    """Current mentions with their post's time, source and read state: (post, n, role, entity, at, source id, read,
    guide)."""
    where, params = ["m.guide = ANY(%s)", "m.entity_id IS NOT NULL"], [guide]
    if since is not None:
        where.append("COALESCE(p.surfaced_at, p.published_at, p.fetched_at) >= %s")
        params.append(since)
    if entity_ids is not None:
        where.append("(m.entity_id = ANY(%s::uuid[]) OR (m.post_id, m.guide, m.n) IN "
                     "(SELECT post_id, guide, n FROM mx_entity_pins WHERE undone_at IS NULL AND entity_id = ANY(%s::uuid[])))")
        ids = sorted(set(entity_ids))
        params += [ids, ids]
    cur.execute(f"""SELECT m.post_id::text, m.n, m.role, m.entity_id::text,
                           COALESCE(p.surfaced_at, p.published_at, p.fetched_at), p.source_id::text,
                           rs.read_at IS NOT NULL, m.guide
                      FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                      LEFT JOIN post_reader_state rs ON rs.post_id = m.post_id
                     WHERE {' AND '.join(where)}""", params)
    return cur.fetchall()


def _stories(cur: Any, post_ids: Iterable[str]) -> Dict[str, List[str]]:
    """{post: its current Mark X stories (as a member)}."""
    ids = sorted(set(post_ids))
    if not ids:
        return {}
    cur.execute("""SELECT post_id::text, story_id::text FROM mx_story_posts
                    WHERE valid_to IS NULL AND role = 'member' AND post_id = ANY(%s::uuid[])""", (ids,))
    out: Dict[str, List[str]] = defaultdict(list)
    for pid, sid in cur.fetchall():
        out[pid].append(sid)
    return out


def _story_heads(cur: Any, sids: Iterable[str]) -> Dict[str, Optional[str]]:
    ids = sorted(set(sids))
    if not ids:
        return {}
    cur.execute("SELECT id::text, headline FROM mx_stories WHERE id = ANY(%s::uuid[])", (ids,))
    return dict(cur.fetchall())


def _ent_view(book: I.Book, eid: str) -> Dict[str, Any]:
    from insight_core.markx import schemas
    e = book.ents[eid]
    root = book.root(eid) == eid
    # 0164: a cluster is shown under its root's shown name and type (by evidence), its maker as the maker's entity
    # (the stated maker's name read through its alias: "Zentra AI" shows as the org Zentra when they are one)
    mk = I.maker_root(book, e.maker) if e.maker else None
    return {"id": e.id, "name": book.label(eid) if root else e.name,
            "type": book.shown_type(eid) if root else schemas.entity_type(e.type),
            "maker": book.label(mk) if mk in book.ents else e.maker, "maker_id": mk if mk in book.ents else None,
            "level": e.level, "version": e.version, "variant": e.variant, "size": e.size, "build": e.build,
            "status": e.status, "family": _family_of(book, eid)}


def _family_of(book: I.Book, eid: str) -> Optional[Dict[str, str]]:
    e = book.ents[eid]
    if e.level in ("version", "variant", "checkpoint") and e.parent:
        f = book.root(e.parent)
        if f in book.ents:
            return {"id": f, "name": book.label(f)}
    return None


def _when(at: Optional[datetime], now: datetime) -> Optional[str]:
    if at is None:
        return None
    days = (now.date() - at.astimezone(timezone.utc).date()).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def _list_book(cur: Any, rows: Iterable[Tuple]) -> I.Book:
    """v10.16: the book the list reads (it was the whole book: 250k entities at the server's scale, most of /entities'
    5 s): every merge and pin, and the entities of the clusters its rows name. `_list_more` adds what the shown rows
    read besides (their makers' and families' entities)."""
    b = I.Book()
    cur.execute("SELECT from_id::text, to_id::text, automatic FROM mx_entity_redirects WHERE undone_at IS NULL")
    b.redirect = I.Redirects({f: (t, auto) for f, t, auto in cur.fetchall()})
    cur.execute("SELECT post_id::text, guide, n, entity_id::text FROM mx_entity_pins WHERE undone_at IS NULL")
    b.pins = {(p, g, n): e for p, g, n, e in cur.fetchall()}
    I.read_ents(cur, b, {b.root(b.pins.get((pid, g, n), eid)) for pid, n, _r, eid, _a, _s, _rd, g in rows})
    return b


def _list_more(cur: Any, book: I.Book, eids: Iterable[str]) -> None:
    """The entities `_ent_view` reads of these rows' besides their own: each stated maker's (through its alias) and
    each version's family, as their clusters' roots."""
    eids = [e for e in eids if e in book.ents]
    keys = sorted({k for k in (N.key(book.ents[e].maker) for e in eids if book.ents[e].maker) if k} - set(book.alias))
    if keys:
        cur.execute("SELECT key, entity_id::text FROM mx_entity_aliases WHERE key = ANY(%s)", (keys,))
        book.alias.update(dict(cur.fetchall()))
    need = {book.root(book.alias[k]) for k in keys if k in book.alias}
    need |= {book.root(book.ents[e].parent) for e in eids if book.ents[e].parent}
    need -= set(book.ents)
    if need:
        I.read_ents(cur, book, need)


def entity_list(cur: Any, *, now: Optional[datetime] = None, limit: int = LIST_LIMIT) -> Dict[str, Any]:
    from insight_core.markx.news import _posts
    now = now or datetime.now(timezone.utc)
    guide = _guide()
    since = now - timedelta(days=WINDOW_DAYS)
    rows = _rows(cur, guide, since)
    book = _list_book(cur, rows)   # v10.14: no mention count; v10.16: only the entities the rows name
    agg: Dict[str, Dict[str, Any]] = {}
    for pid, n, role, eid, at, src, read, g in rows:
        eid = book.root(book.pins.get((pid, g, n), eid))
        if eid not in book.ents or book.ents[eid].status == "not_entity":
            continue
        a = agg.setdefault(eid, {"voices": set(), "posts": {}, "reports": set()})
        a["voices"].add(src)
        a["posts"][pid] = (at, read)
        if role in ROLE_REPORT:
            a["reports"].add(pid)
    ranked = sorted(agg.items(), key=lambda kv: (-len(kv[1]["voices"]), -len(kv[1]["reports"]),
                                                 -max(at.timestamp() for at, _ in kv[1]["posts"].values()), kv[0]))
    top = ranked[:limit]
    _list_more(cur, book, [eid for eid, _ in top])
    newest = {eid: sorted(a["posts"].items(), key=lambda kv: (-kv[1][0].timestamp(), kv[0]))[:3] for eid, a in top}
    story_of = _stories(cur, {p for _, a in top for p in a["posts"]})
    heads = _story_heads(cur, {s for ss in story_of.values() for s in ss})
    posts = _posts(cur, {p for xs in newest.values() for p, _ in xs})
    surge = S.surging(cur, book, since=since.date())
    items = []
    for eid, a in top:
        sids = Counter(s for p in a["posts"] for s in story_of.get(p, ()))
        last = max(at for at, _ in a["posts"].values())
        items.append({**_ent_view(book, eid), "voices": len(a["voices"]), "posts": len(a["posts"]),
                      "reports": len(a["reports"]), "mentions": len(a["posts"]) - len(a["reports"]),
                      "last_at": last, "last_seen": _when(last, now),
                      "stories": [{"id": s, "headline": heads.get(s)} for s, _ in sids.most_common(3)],
                      "newest": [{**{k: (posts.get(p) or {}).get(k) for k in ("id", "title", "source", "kind", "at")},
                                  "read": read} for p, (_at, read) in newest[eid]],
                      "surges": surge.get(eid, [])[:3]})
    return {"window_days": WINDOW_DAYS, "total": len(agg), "items": items, "accuracy": ACCURACY,
            "queue": open_count(cur)}


def named_now(cur: Any, book: I.Book) -> Set[str]:
    """0138: the entities (roots) some post's current reading names (mx_mentions_now, through the owner's pins). An
    entity only an earlier guide named has its page (with those posts) but is listed nowhere else. A document's
    publisher named by a current mention's `by` counts as named. Kept on the book (one read a request)."""
    got = getattr(book, "_named_now", None)
    if got is not None:
        return got
    cur.execute("SELECT post_id::text, guide, n, entity_id::text, by_name FROM mx_mentions_now WHERE guide = ANY(%s) "
                "AND (entity_id IS NOT NULL OR by_name IS NOT NULL)", (_guide(),))
    got = set()
    for p, g, n, e, by in cur.fetchall():
        if e:
            got.add(book.root(book.pins.get((p, g, n), e)))
        if by and book.by_key(N.key(by)):
            got.add(book.root(book.by_key(N.key(by))))
    book._named_now = got   # type: ignore[attr-defined]
    return got


def older_posts(cur: Any, book: I.Book, members: Set[str]) -> List[Dict[str, Any]]:
    """0138: the posts that named one of `members` under an earlier guide (mx_mentions, every guide), each with the
    guide, the words, and what its current reading names as its subjects instead: [{id, title, source, at, url,
    guide, span, now: [{id, name, type}]}], newest first."""
    from insight_core.markx.news import _posts
    ids = sorted(members)
    if not ids:
        return []
    cur.execute("""SELECT DISTINCT ON (m.post_id) m.post_id::text, m.guide, m.span
                     FROM mx_mentions m
                    WHERE m.entity_id = ANY(%s::uuid[])
                       OR (m.post_id, m.guide, m.n) IN (SELECT post_id, guide, n FROM mx_entity_pins
                                                        WHERE entity_id = ANY(%s::uuid[]))
                    ORDER BY m.post_id, m.guide DESC""", (ids, ids))
    rows = cur.fetchall()
    if not rows:
        return []
    pids = [r[0] for r in rows]
    cur.execute("""SELECT post_id::text, guide, n, entity_id::text, name, type FROM mx_mentions_now
                    WHERE post_id = ANY(%s::uuid[]) AND role = 'subject' ORDER BY post_id, n""", (pids,))
    now: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for pid, g, n, eid, name, type_ in cur.fetchall():
        root = book.root(book.pins.get((pid, g, n), eid)) if eid else None
        if all(x.get("id") != root or root is None for x in now[pid]):
            now[pid].append({"id": root if root in book.ents else None,
                             "name": book.label(root) if root in book.ents else name, "type": schemas_type(type_)})
    posts = _posts(cur, pids)
    out = [{**{k: (posts.get(pid) or {}).get(k) for k in ("id", "title", "source", "kind", "at", "url")},
            "id": pid, "guide": guide, "span": span, "now": now.get(pid, [])} for pid, guide, span in rows]
    out.sort(key=lambda x: (x["at"] is None, -(x["at"].timestamp() if x["at"] else 0), x["id"]))
    return out


def original(cur: Any, book: I.Book, root: str) -> Dict[str, Any]:
    """0138: the entity's original and its other addresses (markx/entity_addresses.py): {original: {url, kind, rule,
    post: {id, title} when stored, collected: when Collect originals stored it} or None, addresses: [{kind, url,
    rule}]}."""
    from insight_core.markx import entity_addresses as EA
    from insight_core.utils import entity_originals as R
    from insight_core.utils.url_normalization import normalize_url
    picked = EA.of_root(cur, book, root)
    got = R.original_of({k: (v["url"], v["rule"], v["first_at"]) for k, v in picked.items()})
    addresses = [{"kind": k, "url": v["url"], "rule": v["rule"], "owner": v.get("owner")}
                 for k, v in sorted(picked.items(), key=lambda kv: R.KINDS.index(kv[0]))]
    makers = maker_candidates(book, root, [v.get("owner") for v in picked.values()])
    if not got:
        return {"original": None, "addresses": addresses, "maker_candidates": makers}
    kind, url = got
    cur.execute("SELECT id::text, title, metadata ? 'collected_original' FROM posts WHERE normalized_url = %s LIMIT 1",
                (normalize_url(url) or url,))
    row = cur.fetchone()
    cur.execute("SELECT outcome, asked_at FROM story_originals WHERE kind IN ('entity', 'collect') AND url = %s "
                "ORDER BY asked_at LIMIT 1", (url,))
    asked = cur.fetchone()
    return {"original": {"url": url, "kind": kind, "rule": picked[kind]["rule"], "owner": picked[kind].get("owner"),
                         "post": {"id": row[0], "title": row[1], "collected": bool(row[2])} if row else None,
                         "asked": {"outcome": asked[0], "at": asked[1]} if asked else None},
            "addresses": [a for a in addresses if a["url"] != url], "maker_candidates": makers}


def maker_candidates(book: I.Book, root: str, owners: Iterable[Optional[str]]) -> List[Dict[str, Any]]:
    """v10.13.5: who may make it, proposed by its platform pages' owners (rule `repo`), never asserted: [{name, id: the
    org or person entity of that name run together (handle suffixes aside) or None, agrees: it is the stated maker}]."""
    from insight_core.utils import entity_originals as R
    stated = set()
    e = book.ents.get(root)
    if e is not None:
        stated = {N.key(e.maker)} if e.maker else set()
        if e.parent and e.level in ("family", "thing") and book.root(e.parent) in book.ents:
            stated.add(book.ents[book.root(e.parent)].key)
    out: List[Dict[str, Any]] = []
    for owner in sorted({o for o in owners if o}, key=str.casefold):
        forms = set(N.handle_forms(owner)) | {N.squash(owner.casefold())}
        ids = sorted(x for x, ent in book.ents.items() if book.root(x) == x and ent.type in ("org", "person")
                     and ent.status != "not_entity" and ent.sq in forms)
        out.append({"name": owner, "id": ids[0] if ids else None,
                    "agrees": R.owner_agrees(owner, stated, N.squash)})
    return out


def _members(book: I.Book, root: str) -> Set[str]:
    return {e for e in book.ents if book.root(e) == root}


def entity_page(cur: Any, entity_id: str, *, now: Optional[datetime] = None,
                by_limit: Optional[int] = None, offer_sample: bool = False,
                replies: bool = False) -> Optional[Dict[str, Any]]:
    from insight_core.markx import person_page as PP
    from insight_core.markx.news import _posts
    now = now or datetime.now(timezone.utc)
    guide = _guide()
    book = I.load_book(cur)
    if entity_id not in book.ents:
        return None
    root = book.root(entity_id)
    members = _members(book, root)
    lines: Dict[str, Dict[str, Any]] = {}
    for pid, n, role, eid, at, src, read, g in _rows(cur, guide, None, members):
        if book.root(book.pins.get((pid, g, n), eid)) != root:
            continue
        ln = lines.setdefault(pid, {"roles": set(), "at": at, "source_id": src, "read": read, "as": set()})
        ln["roles"].add(role or "mention")
        ln["as"].add(book.ents[eid].name if eid in book.ents else "")
    current = bool(lines)
    # 0144 B1: the sources that are this person or org; their posts are on the page with role `by`
    selves = PP.by_sources(cur, book, root, members)
    mine = PP.by_posts(cur, [s["id"] for s in selves["by"]])
    for pid, (at, src, read) in mine.items():
        ln = lines.setdefault(pid, {"roles": set(), "at": at, "source_id": src, "read": read, "as": set()})
        ln["roles"].add("by")
    # 0168 A-B: the posts citing the entity's known handles (the owner's yes, its own sources' accounts) by the
    # handle rule: a repost or quote of theirs is `by` (their own post, the original of its story), a status link or
    # "@h said" `source`, an @mention `mention`; a reply to them is hidden unless asked (`replies`)
    from insight_core.markx import handles as HD
    known = HD.entity_handles(cur, book, root, members, selves["by"])
    cited = HD.posts_citing(cur, known, exclude_sources=[s["id"] for s in selves["by"]])
    hidden_replies = 0
    for pid, ref in cited.items():
        if ref["role"] == "reply" and not replies:
            hidden_replies += 1
            continue
        if ref["at"] is None:
            continue
        ln = lines.setdefault(pid, {"roles": set(), "at": ref["at"], "source_id": ref["source_id"], "read": ref["read"],
                                    "as": set()})
        ln["roles"].add(ref["role"])
        ln["as"] |= {"@" + h.split(":", 1)[1] for h in ref["handles"]}
        if ref["role"] == "by":
            mine.setdefault(pid, (ref["at"], ref["source_id"], ref["read"]))
    # 0144 B2: every Mark X story of these posts and, for a post in none, its Mark IX story, each with all its posts
    x_of, x_members = PP.mark_x_stories(cur, lines)
    ix_of, ix_stories = PP.mark_ix_stories(cur, [p for p in lines if not x_of.get(p)])
    shown = {p for ps in x_members.values() for p in ps} | {p for st in ix_stories.values() for p in st["posts"]}
    posts = _posts(cur, set(lines) | shown)
    heads = _story_heads(cur, x_members)

    def at_of(pid: str) -> Any:
        ln = lines.get(pid)
        return ln["at"] if ln else ((posts.get(pid) or {}).get("at") or now)

    def source_of(pid: str) -> Optional[str]:
        ln = lines.get(pid)
        return ln["source_id"] if ln else (posts.get(pid) or {}).get("source_id")

    def line(pid: str) -> Dict[str, Any]:
        p = posts.get(pid) or {"id": pid}
        ln = lines.get(pid) or {"roles": set(), "read": None, "as": set()}
        return {**{k: p.get(k) for k in ("id", "title", "source", "kind", "at", "url")},
                "roles": sorted(ln["roles"]), "read": ln["read"], "named": sorted(x for x in ln["as"] if x),
                "about": pid in lines}

    def block(sid: str, ps: List[str], mark: str, *, headline: Optional[str], root_post: Optional[str] = None,
              origin_url: Optional[str] = None, origin_title: Optional[str] = None) -> Dict[str, Any]:
        orig = PP.original_of(ps, at_of, set(mine), root_post, origin_url)
        ordered = sorted(ps, key=lambda p: (p != orig["post"], at_of(p), p))
        if orig["url"]:
            from insight_core.utils.url_normalization import normalize_url
            cur.execute("SELECT id::text FROM posts WHERE normalized_url = %s LIMIT 1", (normalize_url(orig["url"]) or orig["url"],))
            got = cur.fetchone()
            orig = {**orig, "title": origin_title, "stored": got[0] if got else None}
        return {"story": sid, "mark": mark, "headline": headline,
                "voices": len({source_of(p) for p in ps if source_of(p)}),
                "newest": max(at_of(p) for p in ps), "first_at": min(at_of(p) for p in ps),
                "original": orig, "posts": [line(p) for p in ordered]}
    blocks = [block(sid, ps, "x", headline=heads.get(sid)) for sid, ps in x_members.items() if ps]
    for sid, st in ix_stories.items():
        rp = posts.get(st["root"]) or {}
        blocks.append(block(sid, st["posts"], "ix", headline=st["origin_title"] or rp.get("title"),
                            root_post=st["root"], origin_url=st["origin_url"], origin_title=st["origin_title"]))
    blocks.sort(key=lambda b: (-b["voices"], -b["newest"].timestamp(), b["story"]))
    in_story = set(x_of) | set(ix_of)
    # 0144 B4: the loose posts by role: subject and actor, then by, then the other roles, then mentions
    loose_all = sorted((p for p in lines if p not in in_story),
                       key=lambda p: (PP.loose_order(lines[p]["roles"]), -lines[p]["at"].timestamp(), p))
    groups_n = {"report": 0, "by": 0, "other": 0, "mention": 0}
    names = ("report", "by", "other", "mention")
    for p in loose_all:
        groups_n[names[PP.loose_order(lines[p]["roles"])]] += 1
    cap = PP.BY_LIMIT if by_limit is None else by_limit
    by_seen = 0
    loose = []
    for p in loose_all:
        if PP.loose_order(lines[p]["roles"]) == 1:
            by_seen += 1
            if by_seen > cap:
                continue
        loose.append(p)
    sources: Dict[str, Dict[str, Any]] = {}
    for pid, ln in lines.items():
        p = posts.get(pid) or {}
        s = sources.setdefault(ln["source_id"], {"id": ln["source_id"], "name": p.get("source"), "kind": p.get("kind"),
                                                 "posts": 0, "reports": 0, "by": False})
        s["posts"] += 1
        s["reports"] += 1 if ln["roles"] & set(ROLE_REPORT) else 0
        s["by"] = s["by"] or "by" in ln["roles"]
    e = book.ents[root]
    fam_root = root if e.level in ("family", "thing") else (_family_of(book, root) or {}).get("id")
    versions = []
    if fam_root:
        kids = [x for x, ent in book.ents.items() if ent.parent and book.root(ent.parent) == fam_root
                and book.root(x) == x and ent.status != "not_entity"]
        versions = sorted(({"id": x, "name": book.label(x), "version": book.ents[x].version,
                            "variant": book.ents[x].variant, "level": book.ents[x].level} for x in kids),
                          key=lambda v: (tuple((0, x, "") if isinstance(x, int) else (1, 0, str(x))
                                               for x in (book.ents[v["id"]].version_key or ())), v["name"]),
                          reverse=True)
    named = named_now(cur, book)
    versions = [v for v in versions if v["id"] in named]   # 0138: never a version no current reading names
    # 0165 A: a product's components (things under it, not versions) are listed apart, with their posts
    from insight_core.markx import components as C, timeline as TL
    comps = [c for c in C.components_of(book, root) if c in named]
    versions = [v for v in versions if v["id"] not in set(comps)]
    comp_posts = _post_counts(cur, book, comps)
    maker = book.root(e.parent) if e.parent and e.level in ("family", "thing") else None
    since = (now - timedelta(days=WINDOW_DAYS)).date()
    return {"entity": _ent_view(book, root), "asked": entity_id, "redirected": root != entity_id,
            "current": current, **({} if current else {"older": older_posts(cur, book, members)}),   # 0138
            **original(cur, book, root),   # 0138: its original first, and its other addresses
            "aliases": sorted(book.ents[m].name for m in members),
            "maker": {"id": maker, "name": book.label(maker)} if maker in book.ents else None,
            "family": ({"id": fam_root, "name": book.label(fam_root)} if fam_root and fam_root != root else None),
            "versions": versions, "posts": len(lines), "voices": len(sources),
            "components": [{"id": c, "name": book.label(c), "type": book.shown_type(c), "posts": comp_posts.get(c, 0)}
                           for c in sorted(comps, key=lambda c: (-comp_posts.get(c, 0), book.label(c) or ""))],
            "timeline": TL.of_entity(cur, book, root, stories=blocks),   # 0165 C
            "stories": blocks, "loose": [line(p) for p in loose], "loose_counts": groups_n,   # 0144 B2-B4
            "by": {"sources": selves["by"], "proposed": selves["proposed"], "posts": len(mine)},   # 0144 B1
            "handles": {"known": known,
                        "posts": len([p for p, r in cited.items() if r["role"] != "reply" or replies]),
                        "replies": hidden_replies, "replies_shown": replies},   # 0168
            "sample": PP.offer(cur, root, {b["story"]: b["first_at"] for b in blocks if b["mark"] == "x"}, now)
            if offer_sample else [],                                                                  # 0144 C
            "sources": sorted(sources.values(), key=lambda s: (-s["posts"], s["name"] or "")),
            **_documents(cur, book, members, lines, line),   # 0133: publisher, works, citing and recommending posts
            "rabbit_hole": _rabbit_hole(cur, book, root, members, len(lines)),   # 0138 E3
            "surges": S.surging(cur, book, since=since).get(root, []), "accuracy": ACCURACY,
            "queue": [q for q in queue(cur, book=book)["open"] if root in (q["a"]["id"], (q.get("b") or {}).get("id"))]}


def _post_counts(cur: Any, book: I.Book, roots: Iterable[str]) -> Dict[str, int]:
    """{root: the posts naming its cluster now} (0165 A: a product's components block)."""
    roots = set(roots)
    members = sorted(m for r in roots for m in book.cluster(r))
    if not members:
        return {}
    cur.execute("""SELECT post_id::text, guide, n, entity_id::text FROM mx_mentions_now
                    WHERE guide = ANY(%s) AND entity_id = ANY(%s::uuid[])""", (_guide(), members))
    got: Dict[str, Set[str]] = defaultdict(set)
    for pid, g, n, eid in cur.fetchall():
        r = book.root(book.pins.get((pid, g, n), eid))
        if r in roots:
            got[r].add(pid)
    return {r: len(ps) for r, ps in got.items()}


def _rabbit_hole(cur: Any, book: I.Book, root: str, members: Set[str], posts: int) -> Optional[Dict[str, Any]]:
    """0138 E3: the entity's world (markx/rabbit_hole.py) when it is an org, person or document with 2+ works or 10+
    posts, else None."""
    from insight_core.markx import rabbit_hole
    by, works = published_edges(cur, book, members)
    return rabbit_hole.of(cur, book, root, works=works, people=by + works, posts=posts)


def published_edges(cur: Any, book: I.Book, members: Set[str]) -> Tuple[List[str], List[str]]:
    """0133: (who published these entities, what they published): the current `published` edges' other ends, as
    roots, most posts first."""
    ids = sorted(members)
    if not ids:
        return [], []
    cur.execute("""SELECT a::text, b::text FROM mx_connections WHERE valid_to IS NULL AND relation = 'published'
                      AND a_kind = 'entity' AND b_kind = 'entity' AND (a = ANY(%s::uuid[]) OR b = ANY(%s::uuid[]))""",
                (ids, ids))
    by, works = Counter(), Counter()
    for a, b in cur.fetchall():
        ra, rb = book.root(a), book.root(b)
        if b in members and ra not in members:
            by[ra] += 1
        if a in members and rb not in members:
            works[rb] += 1
    named = named_now(cur, book)   # 0138: an edge's other end no current reading names is not shown
    order = lambda c: [e for e, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])) if e in book.ents and e in named]
    return order(by), order(works)


def _documents(cur: Any, book: I.Book, members: Set[str], lines: Dict[str, Dict[str, Any]], line: Any) -> Dict[str, Any]:
    by, works = published_edges(cur, book, members)
    ref = lambda e: {"id": e, "name": book.label(e), "type": book.shown_type(e)}
    newest = lambda role: [line(p) for p in sorted((p for p, ln in lines.items() if role in ln["roles"]),
                                                   key=lambda p: (-lines[p]["at"].timestamp(), p))]
    return {"published_by": [ref(e) for e in by], "published": [ref(e) for e in works],
            "citing": newest("source"), "recommending": newest("recommended")}


def schemas_type(t: Optional[str]) -> Optional[str]:
    from insight_core.markx import schemas
    return schemas.entity_type(t)


def open_count(cur: Any) -> int:
    cur.execute("SELECT count(*) FROM mx_entity_queue WHERE answer IS NULL AND closed_at IS NULL")
    return cur.fetchone()[0]


def _side(book: I.Book, eid: Optional[str], examples: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if not eid or eid not in book.ents:
        return None
    return {**_ent_view(book, eid), "root": book.root(eid), "posts": examples.get(eid, []), "group": group(book, eid)}


GROUP_NAMES = 8


def group(book: I.Book, eid: str) -> Dict[str, Any]:
    """0164 A: the cluster an item's name is in, as the card shows it ("Zentra Vela is part of Zentra AI (Zentra,
    Zentra AI, ...)"): its root's shown name and type, its names (up to GROUP_NAMES, versions last) and its sides
    (Book.sides: the product family names, the org or person names)."""
    r = book.root(eid)
    cache = book.__dict__.setdefault("_groups", {})
    key = (r, getattr(book.redirect, "rev", None))
    if key in cache and key[1] is not None:
        return cache[key]
    ms = book.cluster(r)
    fam, org = book.sides(ms)
    order = sorted(ms, key=lambda m: (m != r, book.ents[m].level in I.VERSION_LEVELS, book.ents[m].name.lower()))
    names = list(dict.fromkeys(book.ents[m].name for m in order))
    cache[key] = {"root": r, "name": book.label(r), "type": book.shown_type(r), "size": len(ms),
                  "names": names[:GROUP_NAMES], "more": max(0, len(names) - GROUP_NAMES),
                  "sides": {"family": sorted({book.ents[m].name for m in fam})[:GROUP_NAMES],
                            "org": sorted({book.ents[m].name for m in org})[:GROUP_NAMES]}}
    return cache[key]


def join(cur: Any, book: I.Book, a: Optional[str], b: Optional[str], cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """0164 A: what `same` would do to an alias item's two groups (entity_answers.join_plan): None when the roots
    merge as ever; else {mixes, only_names (only the two names join), apart: [{name, from}] (who stays apart from
    whom), needs_choice (the owner's own merge holds a name there, or the two names are of two kinds)}."""
    from insight_core.markx import entity_answers as A, entity_repair as R
    if not a or not b or a not in book.ents or b not in book.ents:
        return None
    plan = A.join_plan(book, a, b)
    if not plan["mixes"]:
        return None
    if plan["kind"] is None:
        return {"mixes": True, "only_names": False, "apart": [], "needs_choice": True}
    if "rows" not in cache:
        cache["rows"], cache["owner"] = R.redirect_rows(cur), R._owner_same(cur)
    apart, held = [], False
    for x, members, others in plan["detach"]:
        edges = R.cluster_edges(book, members, cache["rows"], cache["owner"])
        if R._cuts(members, [(p, q, o) for p, q, o, _ in edges], {x}, set(others)) is None:
            held = True
        other = b if x == a else a
        apart.append({"name": A._group_name(book, others), "from": book.label(other) or book.ents[other].name})
    return {"mixes": True, "only_names": not held, "apart": apart, "needs_choice": held}


def _examples(cur: Any, eids: Iterable[str], guide: str, n: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    from insight_core.markx.news import _posts
    ids = sorted(set(eids))
    if not ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (m.entity_id, m.post_id) m.entity_id::text, m.post_id::text, m.span, m.role,
                          COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = ANY(%s) AND m.entity_id = ANY(%s::uuid[])""", (guide, ids))
    by: Dict[str, List[Tuple]] = defaultdict(list)
    for eid, pid, span, role, at in cur.fetchall():
        by[eid].append((role != "subject", -at.timestamp(), pid, span, role))
    pick = {eid: sorted(xs)[:n] for eid, xs in by.items()}
    posts = _posts(cur, {x[2] for xs in pick.values() for x in xs})
    return {eid: [{**{k: (posts.get(x[2]) or {}).get(k) for k in ("id", "title", "source", "at")},
                   "span": x[3], "role": x[4]} for x in xs] for eid, xs in pick.items()}


def queue(cur: Any, *, book: Optional[I.Book] = None, history: int = 50) -> Dict[str, Any]:
    guide = _guide()
    book = book or I.load_book(cur)
    cur.execute("""SELECT id::text, kind, a::text, b::text, proposal, reason, confidence, evidence, answer, answered_at,
                          created_at FROM mx_entity_queue WHERE closed_at IS NULL
                    ORDER BY answer IS NOT NULL, answered_at DESC NULLS LAST, confidence DESC NULLS LAST, created_at""")
    rows = cur.fetchall()
    named = named_now(cur, book)   # 0138: an item about an entity no current reading names waits, unshown
    open_rows = [r for r in rows if r[8] is None and all(book.root(x) in named for x in (r[2], r[3]) if x)]
    done_rows = [r for r in rows if r[8] is not None][:history]
    ex = _examples(cur, {x for r in open_rows + done_rows for x in (r[2], r[3]) if x}, guide)
    joins: Dict[str, Any] = {}

    def item(r) -> Dict[str, Any]:
        qid, kind, a, b, proposal, reason, conf, ev, ans, at, created = r
        ev = ev or {}
        return {"id": qid, "kind": kind, "a": _side(book, a, ex), "b": _side(book, b, ex), "proposal": proposal,
                "join": join(cur, book, a, b, joins) if kind == "alias" and ans is None else None,   # 0164 A
                "reason": reason, "confidence": conf, "answer": ans, "answered_at": at, "created_at": created,
                "band": I.band_of(conf) if kind == "alias" else None,   # 0130 A1: the measured band it falls in
                "evidence": {"judge": ev.get("judge"), "rules": ev.get("rules"), "senses": ev.get("senses"),
                             "reasons": ev.get("reasons"), "second": ev.get("second"),      # 0130 A2
                             "disagree": ev.get("disagree"), "second_asked": ev.get("second_asked"),
                             "mentions": [{k: m.get(k) for k in ("n", "span", "type", "maker")}
                                          for m in ev.get("mentions") or []],
                             "split_runs": ev.get("split_runs"), "runs": ev.get("runs"),
                             "asked_because": ev.get("asked_because"),   # 0165 B: why a rename was asked
                             # 0168 C: a handle question's (or a handle-named alias's) pairs
                             **({k: ev.get(k) for k in ("platform", "handle", "display", "pairs", "total", "first",
                                                        "last", "alias_of", "named_by_handle")}
                                if ev.get("handle") else {})}}
    cur.execute("""SELECT r.id::text, r.from_id::text, r.to_id::text, r.by, r.automatic, r.at, r.undone_at, r.evidence,
                          r.kind FROM mx_entity_redirects r ORDER BY r.at DESC LIMIT %s""", (history,))
    merges = [{"id": rid, "from": {"id": f, "name": book.ents[f].name if f in book.ents else None},
               "to": {"id": t, "name": book.ents[t].name if t in book.ents else None}, "by": by, "automatic": auto,
               "at": at, "undone_at": undone, "confidence": (ev or {}).get("confidence"), "kind": kind}   # 0165 B
              for rid, f, t, by, auto, at, undone, ev, kind in cur.fetchall()]
    cur.execute("""SELECT count(*) FILTER (WHERE automatic AND undone_at IS NULL),
                          count(*) FILTER (WHERE automatic AND undone_by = 'owner') FROM mx_entity_redirects""")
    auto_live, auto_undone = cur.fetchone()
    cur.execute("""SELECT answer, count(*) FROM mx_entity_queue WHERE answer IS NOT NULL GROUP BY 1""")
    answered = dict(cur.fetchall())
    return {"open": [item(r) for r in open_rows], "answered": [item(r) for r in done_rows], "merges": merges,
            "counts": {"open": len(open_rows), "answered": answered, "automatic_merges": auto_live,
                       "automatic_undone": auto_undone}, "accuracy": ACCURACY}


def post_entities(cur: Any, post_id: str) -> Dict[int, Optional[str]]:
    """{mention n: the entity it shows under (root, through pins)} for the post page's panel."""
    book = I.load_book(cur)
    cur.execute("SELECT n, entity_id::text, guide FROM mx_mentions_now WHERE post_id = %s", (post_id,))   # 0133
    return {n: book.root(book.pins.get((post_id, g, n), eid)) if eid else None for n, eid, g in cur.fetchall()}


def surging_posts(cur: Any, post_ids: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    """{post: the surges it is evidence of, [{id, name, day, voices}]}: the News rows' "surging" mark (0119 A2)."""
    ids = sorted(set(post_ids))
    if not ids:
        return {}
    cur.execute("""SELECT s.entity_id::text, s.day, s.voices, p.pid FROM mx_entity_surges s
                     CROSS JOIN LATERAL jsonb_array_elements_text(s.evidence->'posts') AS p(pid)
                    WHERE s.valid_to IS NULL AND p.pid = ANY(%s)""", (ids,))
    rows = cur.fetchall()
    if not rows:
        return {}
    book = I.load_book(cur)
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for eid, day, voices, pid in rows:
        root = book.root(eid) or eid
        if root in book.ents and not any(x["id"] == root for x in out[pid]):
            out[pid].append({"id": root, "name": book.label(root), "day": day.isoformat(), "voices": voices})
    return dict(out)
