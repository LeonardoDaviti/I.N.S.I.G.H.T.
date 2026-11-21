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

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.markx import surges as S
from insight_core.markx import pairing
from insight_core.utils import voice

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
    guide). 0232: of `entity_ids`, the mentions linked to them (by the entity index) and, apart, the ones pinned to
    them linked elsewhere: one OR of the two read every mention (a sequential scan of mx_mentions, 1.5M rows on the
    server-shaped clone: 0.65 s for any page, the largest entity's or one of 5 posts)."""
    where, params = ["m.guide = ANY(%s)", "m.entity_id IS NOT NULL"], [guide]
    if since is not None:
        where.append(pairing.post_date_within("p", "%s::timestamptz"))
        params += [since, since]
    sql = f"""SELECT m.post_id::text, m.n, m.role, m.entity_id::text,
                     {pairing.post_date('p')}, p.source_id::text,
                     rs.read_at IS NOT NULL, m.guide
                FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                LEFT JOIN post_reader_state rs ON rs.post_id = m.post_id
               WHERE {' AND '.join(where)}"""
    if entity_ids is None:
        cur.execute(sql, params)
        return cur.fetchall()
    ids = sorted(set(entity_ids))
    cur.execute(f"""{sql} AND m.entity_id = ANY(%s::uuid[])
                    UNION ALL
                    {sql} AND m.entity_id <> ALL(%s::uuid[]) AND (m.post_id, m.guide, m.n) IN
                          (SELECT post_id, guide, n FROM mx_entity_pins WHERE undone_at IS NULL AND entity_id = ANY(%s::uuid[]))""",
                [*params, ids, *params, ids, ids])
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


def _ent_view(book: I.Book, eid: str, facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from insight_core.markx import schemas
    e = book.ents[eid]
    root = book.root(eid) == eid
    # 0164: a cluster is shown under its root's shown name and type (by evidence), its maker as the maker's entity
    # (the stated maker's name read through its alias: "Zentra AI" shows as the org Zentra when they are one)
    # v10.35: a root's maker is the one its names state (I.cluster_maker: a merged name's stated maker kept)
    stated = I.cluster_maker(book, eid) if root else e.maker
    mk = I.maker_root(book, stated) if stated else None
    out = {"id": e.id, "name": book.label(eid) if root else e.name,
           "type": book.shown_type(eid) if root else schemas.entity_type(e.type),
           "maker": book.label(mk) if mk in book.ents else stated, "maker_id": mk if mk in book.ents else None,
           "level": e.level, "version": e.version, "variant": e.variant, "size": e.size, "build": e.build,
           "status": e.status, "family": _family_of(book, eid)}
    f = (facts or {}).get(eid)
    if f is not None:   # 0184: what it is, and its maker when made with none (markx/entity_facts.py)
        out["what"] = f.what
        if not out["maker"] and f.maker:
            out["maker"], out["maker_id"] = f.maker, f.maker_id
    return out


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
    from insight_core.markx import entity_facts
    facts = entity_facts.read(cur, [eid for eid, _ in top])   # 0184: one query by the page's ids (off: none)
    for eid, a in top:
        sids = Counter(s for p in a["posts"] for s in story_of.get(p, ()))
        last = max(at for at, _ in a["posts"].values())
        items.append({**_ent_view(book, eid, facts), "voices": len(a["voices"]), "posts": len(a["posts"]),
                      "reports": len(a["reports"]), "mentions": len(a["posts"]) - len(a["reports"]),
                      "last_at": last, "last_seen": _when(last, now),
                      "stories": [{"id": s, "headline": heads.get(s)} for s, _ in sids.most_common(3)],
                      "newest": [{**{k: (posts.get(p) or {}).get(k) for k in ("id", "title", "source", "kind", "at", "byline")},
                                  "read": read} for p, (_at, read) in newest[eid]],
                      "surges": surge.get(eid, [])[:3]})
    return {"window_days": WINDOW_DAYS, "total": len(agg), "items": items, "accuracy": ACCURACY,
            "queue": open_count(cur), "flagged": flagged_count(cur)}   # 0222: the owner is asked only the flagged


def named_now(cur: Any, book: I.Book) -> Set[str]:
    """0138: the entities (roots) some post's current reading names (mx_mentions_now, through the owner's pins). An
    entity only an earlier guide named has its page (with those posts) but is listed nowhere else. A document's
    publisher named by a current mention's `by` counts as named. Kept on the book (one read a request)."""
    got = getattr(book, "_named_now", None)
    if got is not None:
        return got
    if isinstance(book, I.LazyBook):   # v10.17 (0186): a page asks it of a few roots: answered per root, not a read
        got = I._Has(lambda root: bool(_names_now(cur, book, [root])),   # of every current mention (830k on the
                     lambda roots: _names_now(cur, book, roots))          # server); `want` asks many at once
        book._named_now = got   # type: ignore[attr-defined]
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


def _names_now(cur: Any, book: Any, roots: Sequence[Optional[str]]) -> Set[str]:
    """The `roots` in named_now's set (a page's book): a current mention linked or pinned into the cluster, or a
    current mention's `by` one of its aliases."""
    roots = {r for r in roots if r}
    lead = {i: r for r in roots for i in book._leading_to(r) if I._UUID.match(i)}
    if not lead:
        return set()
    cur.execute("""SELECT post_id::text, guide, n, entity_id::text FROM mx_mentions_now
                    WHERE guide = ANY(%s) AND entity_id = ANY(%s::uuid[])""", (_guide(), sorted(lead)))
    out = {r for p, g, n, e in cur.fetchall() if (r := book.root(book.pins.get((p, g, n), e))) in roots}
    pinned = [k for k, e in book.pins.items() if book.root(e) in roots - out]
    if pinned:
        cur.execute("""SELECT post_id::text, guide, n FROM mx_mentions_now WHERE guide = ANY(%s) AND entity_id IS NOT NULL
                          AND (post_id, guide, n) IN (SELECT * FROM unnest(%s::uuid[], %s::text[], %s::int[]))""",
                    (_guide(), [p for p, _g, _n in pinned], [g for _p, g, _n in pinned], [n for _p, _g, n in pinned]))
        out |= {book.root(book.pins[(p, g, n)]) for p, g, n in cur.fetchall()}
    rest = roots - out
    if rest:
        by = book.__dict__.get("_by_keys")
        if by is None:   # the keys of the current mentions' `by` names (the documents' publishers), read once a request
            cur.execute("SELECT DISTINCT by_name FROM mx_mentions_now WHERE guide = ANY(%s) AND by_name IS NOT NULL",
                        (_guide(),))
            by = book.__dict__["_by_keys"] = {k for k in (N.key(b) for (b,) in cur.fetchall()) if k}
        ids = sorted(i for i, r in lead.items() if r in rest)
        cur.execute("SELECT key, entity_id::text FROM mx_entity_aliases WHERE key = ANY(%s) AND entity_id = ANY(%s::uuid[])",
                    (sorted(by), ids))
        out |= {r for k, e in cur.fetchall() if (r := book.root(e)) in rest}
    return out


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
    out = [{**{k: (posts.get(pid) or {}).get(k) for k in ("id", "title", "source", "kind", "at", "url", "byline")},
            "id": pid, "guide": guide, "span": span, "now": now.get(pid, [])} for pid, guide, span in rows]
    out.sort(key=lambda x: (x["at"] is None, -(x["at"].timestamp() if x["at"] else 0), x["id"]))
    return out


def original(cur: Any, book: I.Book, root: str) -> Dict[str, Any]:
    """0138: the entity's original and its other addresses (markx/entity_addresses.py): {original: {url, kind, rule,
    post: {id, title} when stored, collected: when Collect originals stored it} or None, addresses: [{kind, url,
    rule}], cited: the pages its posts cite (0229: [{url, kind, rule}], never its original)}."""
    from insight_core.markx import entity_addresses as EA
    from insight_core.utils import entity_originals as R
    from insight_core.utils.url_normalization import normalize_url
    picked, cited = EA.page(cur, book, root)
    cited = [{k: c[k] for k in ("url", "kind", "rule")} for c in cited]
    got = R.original_of({k: (v["url"], v["rule"], v["first_at"]) for k, v in picked.items()})
    addresses = [{"kind": k, "url": v["url"], "rule": v["rule"], "owner": v.get("owner")}
                 for k, v in sorted(picked.items(), key=lambda kv: R.KINDS.index(kv[0]))]
    makers = maker_candidates(book, root, [v.get("owner") for v in picked.values()])
    if not got:
        return {"original": None, "addresses": addresses, "maker_candidates": makers, "cited": cited}
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
            "addresses": [a for a in addresses if a["url"] != url], "maker_candidates": makers, "cited": cited}


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
        ids = sorted(x for x in book.by_squashed_key(forms) if book.root(x) == x   # v10.17 (0186): by the index
                     and book.ents[x].type in ("org", "person") and book.ents[x].status != "not_entity")
        out.append({"name": owner, "id": ids[0] if ids else None,
                    "agrees": R.owner_agrees(owner, stated, N.squash)})
    return out


def _members(book: I.Book, root: str) -> Set[str]:
    return set(book.cluster(root))   # v10.17 (0186): the entities whose merges lead to root, not a walk of the book


def family_versions(book: Any, versions: List[Dict[str, Any]],
                    posts: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """v10.30 (0259): a family's versions as a reader counts them: each row's version as a version reads it
    (names.clean: a model id's "5-1" is 5.1 when the family lists 5.1), a row whose version is a ratio ("5:1") left out (no version of the
    family), and a variant that is a setting of its version (names.setting: "Nimbus 5.2 (max)", "Nimbus 5 low") listed
    under that version's row (`settings`), not as a version of its own, when the family lists that version; one it
    does not list stays a row. The order kept."""
    known = {N.vt(v["version"]) for v in versions if v["level"] == "version" and not v["variant"] and v["version"]}
    rows: List[Dict[str, Any]] = []
    for v in versions:
        e = book.ents[v["id"]]
        if N.not_a_version(e.version) and not e.variant:
            continue
        f = N.clean({"version": e.version, "variant": e.variant}, e.name, known)
        rows.append({**v, "version": f["version"], "variant": f["variant"]})
    by_version: Dict[Any, Dict[str, Any]] = {}
    for v in rows:
        if v["level"] == "version" and not v["variant"] and v["version"]:
            by_version.setdefault(N.vt(v["version"]), v)
    out = []
    for v in rows:
        e = book.ents[v["id"]]
        top = by_version.get(N.vt(v["version"])) if v["version"] else None
        typ = book.shown_type(v["id"]) or e.type
        if top is not None and top is not v and any(N.setting(v["variant"], n, typ) for n in {e.name, v["name"]}):
            top.setdefault("settings", []).append({"id": v["id"], "name": v["name"], "variant": v["variant"]})
            continue
        out.append(v)
    # v10.35: a build of a version (GGUF, NVFP4, quantised weights: the name states a build) is listed under the
    # row of the same version and variant that states none (`builds`), as its settings are, not as a version of its own.
    def same(v: Dict[str, Any]) -> Tuple[Any, str]:
        return (N.vt(v["version"]) if v["version"] else None, (v["variant"] or "").strip().lower())
    base = {}
    for v in out:
        if not book.ents[v["id"]].build:
            base.setdefault(same(v), v)
    kept = []
    for v in out:
        top = base.get(same(v)) if book.ents[v["id"]].build and (v["version"] or v["variant"]) else None
        if top is not None:
            top.setdefault("builds", []).append({"id": v["id"], "name": v["name"], "build": book.ents[v["id"]].build})
            continue
        kept.append(v)
    # v10.35: two rows of one version and variant, neither a build, are one version written two ways ("Fable 5.0" and
    # "Fable 5": N.vnorm; "claude-fable-5-1", the model id, and "Fable 5.1" once names.clean reads 5.1): the row of
    # the most posts (`posts`; then the order) lists the others under it (`same`), not as versions of their own.
    def spelled(v: Dict[str, Any]) -> Tuple[Any, str, str]:
        return (N.vnorm(N.vt(v["version"])), (v["variant"] or "").strip().lower(),
                N.squash(N.nk(book.ents[v["id"]].size) or ""))
    def spelled_apart(a: Any, b: Any) -> bool:
        # only a version written two ways ("5.0" / "5", the id's "5-1" / "5.1"), by one maker: two names stating the
        # same version are two things until identity says one (measured: "HP Z6" / "Nikon Z6", "Fourier GR-1" /
        # "ArcFlash Labs GR-1" in one family)
        written = (N.vt(a.version), N.nk(a.variant)) != (N.vt(b.version), N.nk(b.variant))
        return written and (not a.maker or not b.maker or I.same_maker(book, a.maker, b.maker))
    posts = posts or {}
    lead: Dict[Tuple[Any, str, str], Dict[str, Any]] = {}
    for v in kept:
        if v["version"] and not book.ents[v["id"]].build:
            k = spelled(v)
            if k not in lead or posts.get(v["id"], 0) > posts.get(lead[k]["id"], 0):
                lead[k] = v
    one = []
    for v in kept:
        top = lead.get(spelled(v)) if v["version"] and not book.ents[v["id"]].build else None
        if top is not None and top is not v and spelled_apart(book.ents[v["id"]], book.ents[top["id"]]):
            top.setdefault("same", []).append({"id": v["id"], "name": v["name"]})
            continue
        one.append(v)
    return one


def entity_page(cur: Any, entity_id: str, *, now: Optional[datetime] = None,
                by_limit: Optional[int] = None, offer_sample: bool = False,
                replies: bool = False, stories_limit: Optional[int] = None,
                loose_limit: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The entity's page. Issue 0195: `stories_limit` story blocks and `loose_limit` loose posts are listed (None:
    all), `stories_total` and `loose_total` count them all; the timeline and the sample read every story."""
    got = _entity_page(cur, entity_id, now=now, by_limit=by_limit, offer_sample=offer_sample, replies=replies,
                       stories_limit=stories_limit, loose_limit=loose_limit)
    return None if got is None else got[0]


# ---- the kept page (issue 0198) ------------------------------------------------------------------------------

ENTITY_PAGES = 300   # the kept entity pages: the newest built stay (a cache: the rest are built again when opened)
# 0232: a request's limits are capped (out of range: clamped) and one kept page an entity serves them all, built at
# the caps and cut to each request's limits (`_cut`). Before, a page asked with its own limits was built every time
# (Qwen's page with ?stories_limit=5&loose_limit=10: 7.4 s each request), and nothing capped them.
STORIES_CAP = 200     # story blocks a page lists at most (the page asks 50 more at a time)
LOOSE_CAP = 500       # posts in no story listed at most
BY_CAP = 500          # the entity's own (by) posts listed loose at most (the page's "Show all")
DEFAULTS = {"by": 50, "stories": 20, "loose": 30}   # the route's defaults (PP.BY_LIMIT; issue 0195; 0277: were 50, 100)
PAGE_SHAPE = "9"      # v10.35: a story's `about` (stories about it first), the timeline's release rule; a version's `same` (one version written two ways); a version's `builds`; a story's `joined` (its release group). 0272: `brief.numbers`. 0269: a brief line's `note` (0261: `brief`). 0232: the answer's shape, in the kept key (a field the frontend reads added, renamed or gone:
#                       bump it): a page kept by the previous code is sent only while its shape is this one
HOT_PAGES = 20        # 0232: the most opened entity pages the jobs process builds after a run or a deploy
HOT_SECONDS = 120.0   # and at most this long a build (the rest wait for the next one, or are built when opened)


def limits(by_limit: Optional[int] = None, stories_limit: Optional[int] = None,
           loose_limit: Optional[int] = None) -> Tuple[int, int, int]:
    """0232: a request's (by, stories, loose) limits: None the route's default, each clamped into its range (by
    0..BY_CAP, stories 1..STORIES_CAP, loose 1..LOOSE_CAP)."""
    def clamp(v: Optional[int], default: int, low: int, cap: int) -> int:
        return default if v is None else max(low, min(cap, int(v)))
    return (clamp(by_limit, DEFAULTS["by"], 0, BY_CAP), clamp(stories_limit, DEFAULTS["stories"], 1, STORIES_CAP),
            clamp(loose_limit, DEFAULTS["loose"], 1, LOOSE_CAP))


def _page_key(entity_id: str, replies: bool) -> str:
    """The key an entity's page is opened by (mx_page_opens) and, with PAGE_SHAPE, kept by."""
    return f"{entity_id}?replies={int(bool(replies))}"


def _full(cur: Any, entity_id: str, *, now: datetime, replies: bool):
    """(`_entity_page` every request's limits are cut from (`_cut`), its `until`), or None: the story blocks up to
    STORIES_CAP, the by posts up to BY_CAP and the loose posts up to LOOSE_CAP + BY_CAP (what a request listing fewer
    by posts reads further down)."""
    return _entity_page(cur, entity_id, now=now, by_limit=BY_CAP, offer_sample=True, replies=replies,
                        stories_limit=STORIES_CAP, loose_limit=LOOSE_CAP + BY_CAP)


def _cut(full: Dict[str, Any], by: int, stories: int, loose: int, whole: bool = False) -> Dict[str, Any]:
    """`entity_page` at these limits (by <= BY_CAP, stories <= STORIES_CAP, loose <= LOOSE_CAP) from `_full`'s
    answer: its first `stories` blocks; its loose posts without the by posts past `by`, the first `loose` of them;
    loose_total as the build counts it (every loose post but the by posts past `by`).
    0277: unless `whole` (the page's "all" links), the long lists are cut too (`_short`)."""
    from insight_core.markx import person_page as PP
    seen, kept = 0, []
    for ln in full["loose"]:
        if len(kept) >= loose:
            break
        if PP.loose_order(set(ln.get("roles") or ())) == 1:
            seen += 1
            if seen > by:
                continue
        kept.append(ln)
    counts = full["loose_counts"]
    page = {**full, "stories": full["stories"][:stories], "loose": kept,
            "loose_total": sum(counts.values()) - counts["by"] + min(counts["by"], by)}
    return page if whole else _short(page)


# 0277: the default answer's long lists. Anthropic's page on the server was 2.5 MB: 1.1 MB the 1,053 posts citing it,
# 1.06 MB the 50 stories' 1,527 posts, 300 kB a timeline of 920 events of which 8 are shown first, 150 + 104 kB its
# 863 works (twice). Each list is cut to what the page shows first, its total beside it; `whole` (?all=true, the
# page's "all" links) answers every one. Cut from the one kept page: nothing more is built, held or kept.
SHORT = {"story_posts": 6, "citing": 20, "recommending": 20, "works": 30, "relations": 60}


def _short(page: Dict[str, Any]) -> Dict[str, Any]:
    """The page with each story's posts cut to SHORT["story_posts"] (its original first, then the posts about the
    entity, shown in the block's order; `posts_total`), the posts citing or recommending it and its works (published,
    the rabbit hole's) to their first ones (`<list>_total`; the rabbit hole's `missing`: its works not stored, counted),
    and the timeline to its top events (`items_all`: whether every event is listed)."""
    out = dict(page)
    n = SHORT["story_posts"]
    blocks = []
    for b in page.get("stories") or []:
        ps = b.get("posts") or []
        if len(ps) <= n:
            blocks.append({**b, "posts_total": len(ps)})
            continue
        orig = (b.get("original") or {}).get("post")
        first = sorted(range(len(ps)), key=lambda i: (ps[i]["id"] != orig, not ps[i].get("about"), i))[:n]
        blocks.append({**b, "posts": [ps[i] for i in sorted(first)], "posts_total": len(ps)})
    out["stories"] = blocks
    for k in ("citing", "recommending", "published"):
        xs = page.get(k)
        if isinstance(xs, list):
            out[k], out[f"{k}_total"] = xs[:SHORT.get(k, SHORT["works"])], len(xs)
    hole = page.get("rabbit_hole")
    if isinstance(hole, dict) and isinstance(hole.get("works"), list):
        works = hole["works"]
        out["rabbit_hole"] = {**hole, "works": works[:SHORT["works"]], "works_total": len(works),
                              "missing": sum(1 for w in works if w.get("url") and not w.get("stored"))}
    rels = page.get("relations")
    if isinstance(rels, list) and len(rels) > SHORT["relations"]:   # the most stated ones, in their order
        most = set(sorted(range(len(rels)), key=lambda i: (-(rels[i].get("posts") or 0), i))[:SHORT["relations"]])
        out["relations"] = [r for i, r in enumerate(rels) if i in most]
    out["relations_total"] = len(rels) if isinstance(rels, list) else 0
    # a surge's posts (65 kB of ids on Anthropic's page) are read by no view of the page
    out["surges"] = [{k: v for k, v in s.items() if k != "post_ids"} for s in page.get("surges") or []]
    tl = page.get("timeline")
    if isinstance(tl, dict) and isinstance(tl.get("items"), list):
        top = [e for e in tl["items"] if e.get("top")]
        out["timeline"] = {**tl, "items": top, "items_all": len(top) == len(tl["items"])}
    return out


def page_inputs(cur: Any, entity_id: str) -> Tuple[Optional[str], Optional[List[Any]]]:
    """(the newest decision run's id, what an entity's page reads that changes between runs), or None for the second
    when there is no run or no such entity; a few indexed reads. Besides the run (stories, memberships, connections,
    surges, the entity book, the queue, its timeline):
      - the cluster's current mentions (count, newest), read through its merges;
      - the old stories offered to label and their labels (person_page.offer; the page's own offers too);
      - Mark IX's story job's last pass (a post in no Mark X story shows its Mark IX story);
      - what the owner changed (kept_pages.owner_marks: labels, merges, pins, sources, handles, fixes).
    The page's clock (a new day; an old story's edge) is its kept row's `until`. A worker's other answers and new
    posts by its sources or citing its handles are read by the next decision run (each answer asks for one; one runs
    at least hourly): the kept page shows them from that run on."""
    from insight_core.markx import kept_pages, repo
    last = repo.last_run(cur)
    if last is None:
        return None, None
    book = I.lazy_book(cur)
    if entity_id not in book.ents:
        return str(last["id"]), None
    root = book.root(entity_id)
    members = sorted(_members(book, root))
    cur.execute("""SELECT count(*), max(s.at) FROM mx_mentions m      -- mx_mentions_now, with its set's change time
                     JOIN mx_mention_sets s ON s.post_id = m.post_id AND s.guide = m.guide
                    WHERE m.entity_id = ANY(%s::uuid[])""", (members,))
    mentions = list(cur.fetchone())
    cur.execute("""SELECT (SELECT json_build_array(count(*), max(offered_at)) FROM mx_story_samples),
                          (SELECT json_build_array(count(*), max(created_at)) FROM mx_story_sample_labels),
                          (SELECT value->>'computed_at' FROM system_settings WHERE key = 'stories')""")
    samples, sample_labels, story_job = cur.fetchone()
    from insight_core.markx import entity_brief
    return str(last["id"]), [root, members, mentions, sample_labels, story_job, kept_pages.owner_marks(cur),
                             entity_brief.stamp(cur, root), samples]   # 0261: the brief's reports and points


def kept_entity_page(cur: Any, entity_id: str, *, by_limit: Optional[int] = None, replies: bool = False,
                     stories_limit: Optional[int] = None, loose_limit: Optional[int] = None,
                     now: Optional[datetime] = None, whole: bool = False) -> Optional[bytes]:
    """GET /api/markx/entities/{id}: the page's bytes (kept_pages.encode of `entity_page` with its sample offered, at
    the request's `limits`), cut from the entity's one kept page (`kept_full`); the open counted (the jobs process
    builds the most opened pages before anyone asks: `keep_pages`). None: no such entity."""
    from insight_core.markx import kept_pages
    now = now or datetime.now(timezone.utc)
    by, stories, loose = limits(by_limit, stories_limit, loose_limit)
    body = kept_full(cur, entity_id, replies=replies, now=now, any_code=True)
    if body is None:
        return None
    kept_pages.opened(cur, "entity", _page_key(entity_id, replies))
    return kept_pages.recut(body, lambda full: _cut(full, by, stories, loose, whole))


def kept_full(cur: Any, entity_id: str, *, replies: bool = False, now: Optional[datetime] = None,
              any_code: bool = False) -> Optional[bytes]:
    """The bytes of the entity's `_full` page: the kept ones while its inputs (`page_inputs`) and its clock (`until`)
    are the same (0232, `any_code`: kept by the previous code too, in the same shape), else built and kept (the
    newest ENTITY_PAGES pages stay). Kept only when the inputs read after the build are the ones read before (but the
    offers it made itself): a page built while an input changed is answered, not kept. None: no such entity."""
    import logging
    import time
    from insight_core.markx import kept_pages
    now = now or datetime.now(timezone.utc)
    key = kept_pages.shaped(_page_key(entity_id, replies), PAGE_SHAPE)
    run, parts = page_inputs(cur, entity_id)
    if parts is not None:
        got = kept_pages.get(cur, "entity", key, run, kept_pages.stamp("entity", key, parts), now=now,
                             any_code=any_code)
        if got is not None:
            return got
    t0 = time.monotonic()
    built = _full(cur, entity_id, now=now, replies=replies)
    if built is None:
        return None
    page, until = built
    body = kept_pages.encode(page)
    seconds = round(time.monotonic() - t0, 2)
    if parts is not None:
        run_after, after = page_inputs(cur, entity_id)
        if run_after == run and after is not None and after[:-1] == parts[:-1]:
            try:
                with cur.connection.transaction():
                    kept_pages.put(cur, "entity", key, run, kept_pages.stamp("entity", key, after), body,
                                   seconds=seconds, until=until, replace_older=True)
                    kept_pages.prune_rows(cur, "entity", ENTITY_PAGES)
            except Exception:   # noqa: BLE001 - a cache: the page is answered all the same
                logging.getLogger(__name__).exception("Mark X: keeping the entity page %s failed", entity_id)
    return body


# ---- the list, the queue's first page and the most opened pages, kept by the jobs process (0216 item 5, 0232) ------
# The list (3.6-4 s on the server) and the queue's first page (2.7 s) were built on every open; an entity's page at its
# first open after each decision run and after each deploy (4-7.5 s). The jobs process (jobs.KEPT_VIEWS "entities")
# builds them after each decision run and first after a deploy, and the routes send what it kept (kept_or_build: built
# as before when nothing is kept for their inputs).
#   - The list and the queue are stamped by what changes them: the run (everything the entities and surges stages
#     write), the owner's marks (labels, merges, pins, sources, handles, fixes), the mentions' current sets (a worker's
#     entities answer), the queue's rows (answers, flags and their notes, closings); the list may lag behind the
#     posts' titles and read flags (the loose part) within KEPT_LAG, and its clock ("N days ago", the window's edge).
#   - Any other queue page is built live, as before.

LIST_SHAPE = "1"                    # the list's answer's shape, in its key (see PAGE_SHAPE)
QUEUE_SHAPE = "1"                   # the queue's
QUEUE_KEPT = {"limit": 50, "offset": 0, "view": "flagged"}   # the queue's page kept: the page's first, by default
KEPT_LAG = timedelta(minutes=15)    # the list is sent at most this old (its titles, read flags and window's edge)
KEPT_GAP = 60.0                     # the jobs process builds the list and the queue again at most this often


def _list_key() -> str:
    from insight_core.markx import kept_pages
    return kept_pages.shaped("list", LIST_SHAPE)


def _queue_key() -> str:
    from insight_core.markx import kept_pages
    return kept_pages.shaped("limit={limit}&offset={offset}&view={view}".format(**QUEUE_KEPT), QUEUE_SHAPE)


def _queue_marks(cur: Any) -> List[Any]:
    """What the owner's, Claude's and the runs' writes of mx_entity_queue change: the open, answered, closed and
    flagged counts, their newest times, and the open flagged items' notes."""
    cur.execute("""SELECT count(*), count(answer), count(closed_at), max(created_at), max(answered_at), max(closed_at),
                          count(*) FILTER (WHERE flagged_at IS NOT NULL AND answer IS NULL AND closed_at IS NULL),
                          max(flagged_at),
                          md5(string_agg(id::text || ':' || COALESCE(flag_note, '') || ':' || COALESCE(flagged_by, ''),
                                         ',' ORDER BY id) FILTER (WHERE flagged_at IS NOT NULL))
                     FROM mx_entity_queue""")
    return list(cur.fetchone())


def kept_inputs(cur: Any, *, queue_page: bool = False) -> Any:
    """The list's (or the queue's first page's) kept_pages.Inputs: strict, the newest run, the owner's marks, the
    mentions' current sets and the queue's rows; loose (the list only), the posts' and read state's kept inputs."""
    from insight_core.markx import kept_pages, repo
    last = repo.last_run(cur)
    cur.execute("SELECT count(*), max(at) FROM mx_mention_sets")
    sets = list(cur.fetchone())
    strict = [str(last["id"]) if last else None, kept_pages.owner_marks(cur), sets, _queue_marks(cur)]
    if queue_page:
        return kept_pages.Inputs(strict, None)
    return kept_pages.Inputs(strict, json.dumps(kept_pages.changes(cur, ["posts", "reads"]), separators=(",", ":")))


def _list_until(now: datetime) -> datetime:
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return min(day, now + KEPT_LAG)


def kept_list(cur: Any, *, now: Optional[datetime] = None) -> bytes:
    """GET /api/markx/entities: the kept list's bytes (by this code or, its inputs the same, the code before a
    deploy), else `entity_list` built and kept."""
    from insight_core.markx import kept_pages
    now = now or datetime.now(timezone.utc)
    return kept_pages.kept_or_build(cur, "entities", _list_key(), lambda: kept_inputs(cur),
                                    lambda: entity_list(cur, now=now), until=_list_until(now), now=now, any_code=True)


def kept_queue(cur: Any, *, limit: int, offset: int, view: str) -> Any:
    """GET /api/markx/entities/queue: the kept first page's bytes for QUEUE_KEPT's parameters, else `queue` (any other
    page is built live, as before)."""
    from insight_core.markx import kept_pages
    if {"limit": limit, "offset": offset, "view": view} != QUEUE_KEPT:
        return queue(cur, limit=limit, offset=offset, view=view)
    return kept_pages.kept_or_build(cur, "entity_queue", _queue_key(), lambda: kept_inputs(cur, queue_page=True),
                                    lambda: queue(cur, **QUEUE_KEPT), any_code=True)


def _hot(cur: Any) -> List[Tuple[str, bool]]:
    """The most opened entity pages (HOT_PAGES): (entity id, replies)."""
    from insight_core.markx import kept_pages
    out = []
    for key in kept_pages.most_opened(cur, "entity", HOT_PAGES):
        eid, _, rest = key.partition("?replies=")
        if I._UUID.match(eid):
            out.append((eid, rest == "1"))
    return out


def kept_missing(cur: Any, now: Optional[datetime] = None) -> bool:
    """The jobs process's look: whether the list or the queue's first page is not kept for its inputs now by this
    code (or lags past its loose part, or ends its KEPT_LAG before the next looks), or a most opened page has no row
    of the newest run by this code (a run or a deploy since; a page an owner's mark made stale between runs is built
    when opened, as before). Before any decision run, nothing (as News: nothing to keep)."""
    from insight_core.markx import kept_pages, repo
    now = now or datetime.now(timezone.utc)
    last = repo.last_run(cur)
    if last is None:
        return False
    lst = kept_inputs(cur)   # the queue's strict part is the list's
    if not kept_pages.has(cur, "entities", _list_key(), kept_pages.NO_RUN,
                          kept_pages.stamp("entities", _list_key(), lst.strict), loose=lst.loose,
                          until_after=now + timedelta(seconds=2 * KEPT_GAP)):
        return True
    if not kept_pages.has(cur, "entity_queue", _queue_key(), kept_pages.NO_RUN,
                          kept_pages.stamp("entity_queue", _queue_key(), lst.strict)):
        return True
    hot = _hot(cur)
    if not hot:
        return False
    keys = [kept_pages.shaped(_page_key(e, r), PAGE_SHAPE) for e, r in hot]
    cur.execute("""SELECT count(DISTINCT key) FROM mx_kept_pages WHERE page = 'entity' AND key = ANY(%s)
                      AND run_id = %s AND code = %s AND (until IS NULL OR until > %s)""",
                (keys, last["id"], kept_pages.code_stamp(), now + timedelta(seconds=2 * KEPT_GAP)))
    return cur.fetchone()[0] < len(keys)


def keep_pages(cur: Any, *, now: Optional[datetime] = None, budget: float = HOT_SECONDS) -> Dict[str, Any]:
    """In the jobs process (jobs.Jobs.entities), in one snapshot: the list and the queue's first page when not kept
    for their inputs, then the most opened entity pages not kept for theirs (most opened first, within `budget`
    seconds: the rest are built when opened or at the next build). Each by the routes' own path (`entity_list`,
    `queue`, `kept_full`), kept as the routes keep them."""
    import time
    from insight_core.markx import kept_pages
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Any] = {"built": [], "bytes": {}, "build_seconds": {}}
    for page, key, inputs, build, until in (
            ("entities", _list_key(), lambda: kept_inputs(cur), lambda: entity_list(cur, now=now), _list_until(now)),
            ("entity_queue", _queue_key(), lambda: kept_inputs(cur, queue_page=True),
             lambda: queue(cur, **QUEUE_KEPT), None)):
        got = inputs()
        st = kept_pages.stamp(page, key, got.strict)
        if kept_pages.has(cur, page, key, kept_pages.NO_RUN, st, loose=got.loose,
                          until_after=now + timedelta(seconds=2 * KEPT_GAP) if until else None):
            continue
        t0 = time.monotonic()
        body = kept_pages.encode(build())
        seconds = round(time.monotonic() - t0, 2)
        kept_pages.put(cur, page, key, kept_pages.NO_RUN, st, body, seconds=seconds, until=until, loose=got.loose)
        out["built"].append(page)
        out["bytes"][page], out["build_seconds"][page] = len(body), seconds
    t_hot = time.monotonic()
    hot = {"pages": 0, "left": 0, "failed": 0, "slowest": 0.0}
    for eid, replies in _hot(cur):
        if time.monotonic() - t_hot > budget:
            hot["left"] += 1
            continue
        t0 = time.monotonic()
        try:
            with cur.connection.transaction():   # a page that fails is left for its next open; the others go on
                kept_full(cur, eid, replies=replies, now=now)
        except Exception:   # noqa: BLE001 - a cache: the page is built when opened
            import logging
            logging.getLogger(__name__).exception("Mark X: building the opened entity page %s failed", eid)
            hot["failed"] += 1
            continue
        hot["pages"] += 1
        hot["slowest"] = max(hot["slowest"], round(time.monotonic() - t0, 2))
    out["hot"] = {**hot, "seconds": round(time.monotonic() - t_hot, 2)}
    return out


def _until(now: datetime, every: Sequence[Dict[str, Any]], offer_sample: bool) -> datetime:
    """When the page's clock next changes what it shows: the next day (its surges are read by day, its offers counted
    a day), or the moment an old story becomes old enough to be offered (person_page.offer's edge)."""
    from insight_core.markx.story_window import RECENT
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    edge = now - timedelta(days=RECENT)
    crossing = [b["first_at"] + timedelta(days=RECENT) for b in every
                if offer_sample and b["mark"] == "x" and b["first_at"] is not None and b["first_at"] >= edge]
    return min([day, *crossing])


class _Kinded:
    """A post as story_rules.background reads it: its id and its source's kind."""
    __slots__ = ("id", "kind")

    def __init__(self, pid: str, kind: Optional[str]):
        self.id, self.kind = pid, kind


def story_dating(ps: Sequence[str], at: Any, kind: Any) -> Tuple[Set[str], Any]:
    """v10.35: (the background posts of a story's `ps`, its start), by the rule Mark X stores a story's first_at by
    and News leads a row by (story_rules.background, 0263: a Saved page dated more than 72 h before the story's first
    post of a voice neither dates nor leads it). `at`, `kind`: a post's date and its source's kind."""
    from insight_core.utils.story_rules import background
    times = {p: at(p) for p in ps}
    bg = background([_Kinded(p, kind(p)) for p in ps], times)
    return bg, min((t for p, t in times.items() if p not in bg), default=None)


def story_entries(cur: Any, members: Dict[str, List[str]], voices: Dict[str, int]) -> List[List[str]]:
    """v10.35: the entity page's Mark X entries, each [its lead story, *the stories joined into it]: the stories one
    current same_release chain joins (graph.release_groups, 0236) are one entry, as they are one News row, led by
    News's launch order (news.launch_order: the maker's own story, a release first, then most voices), else the one
    of most voices; every other story its own entry."""
    from insight_core.markx import graph
    from insight_core.markx import news as NW
    sids = sorted(s for s, ps in members.items() if ps)
    out, seen = [], set()
    for g in graph.release_groups(cur, sids):
        g = [s for s in g if s in voices]
        if len(g) < 2:
            continue
        order = NW.launch_order(NW._story_facts(cur, g), {s: voices[s] for s in g})
        rest = sorted((s for s in g if s not in order), key=lambda s: (-voices[s], s))
        out.append(list(dict.fromkeys(order + rest)))
        seen |= set(g)
    return out + [[s] for s in sids if s not in seen]


def covered(ix_posts: Sequence[str], entries: Sequence[Set[str]]) -> bool:
    """v10.35: a Mark IX story is the group of a Mark X entry holding most of its posts (more than half): it is listed
    once, as that Mark X story (its posts in no Mark X story are the page's loose posts)."""
    n = len(set(ix_posts))
    return bool(n) and any(2 * len(set(ix_posts) & e) > n for e in entries)


def _entity_page(cur: Any, entity_id: str, *, now: Optional[datetime] = None,
                 by_limit: Optional[int] = None, offer_sample: bool = False,
                 replies: bool = False, stories_limit: Optional[int] = None,
                 loose_limit: Optional[int] = None) -> Optional[Tuple[Dict[str, Any], datetime]]:
    """(`entity_page`, when its clock next changes it: `_until`), or None."""
    from insight_core.markx import person_page as PP
    from insight_core.markx.news import _posts
    now = now or datetime.now(timezone.utc)
    guide = _guide()
    book = I.lazy_book(cur)   # v10.17 (0186): what the page asks of the book, not the whole book
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
    page_original = original(cur, book, root)   # 0138; v10.35: its stored post leads every story holding it
    release = ((page_original.get("original") or {}).get("post") or {}).get("id")

    def at_of(pid: str) -> Any:
        ln = lines.get(pid)
        return ln["at"] if ln else ((posts.get(pid) or {}).get("at") or now)

    def source_of(pid: str) -> Optional[str]:
        ln = lines.get(pid)
        return ln["source_id"] if ln else (posts.get(pid) or {}).get("source_id")

    def line(pid: str) -> Dict[str, Any]:
        p = posts.get(pid) or {"id": pid}
        ln = lines.get(pid) or {"roles": set(), "read": None, "as": set()}
        return {**{k: p.get(k) for k in ("id", "title", "source", "kind", "at", "url", "byline")},
                "roles": sorted(ln["roles"]), "read": ln["read"], "named": sorted(x for x in ln["as"] if x),
                "about": pid in lines}

    def block(sid: str, ps: List[str], mark: str, *, headline: Optional[str], root_post: Optional[str] = None,
              origin_url: Optional[str] = None, origin_title: Optional[str] = None,
              joined: Sequence[str] = ()) -> Dict[str, Any]:
        h = head(sid, ps, mark, headline, root_post=root_post, origin_url=origin_url, joined=joined)
        orig = h["original"]
        ordered = sorted(ps, key=lambda p: (p != orig["post"], at_of(p), p))
        if orig["url"]:
            from insight_core.utils.url_normalization import normalize_url
            cur.execute("SELECT id::text FROM posts WHERE normalized_url = %s LIMIT 1", (normalize_url(orig["url"]) or orig["url"],))
            got = cur.fetchone()
            orig = {**orig, "title": origin_title, "stored": got[0] if got else None}
        return {**h, "original": orig, "posts": [line(p) for p in ordered]}

    def head(sid: str, ps: List[str], mark: str, headline: Optional[str], *, root_post: Optional[str] = None,
             origin_url: Optional[str] = None, joined: Sequence[str] = ()) -> Dict[str, Any]:
        """A block's own fields (what the order, the timeline and the sample read), without its posts' lines.
        v10.35: dated and led as News dates and leads a story (`story_dating`: a background page neither dates nor
        leads it; the entity's release page leads it when held); no headline: its lead's title, as News names it."""
        bg, first_at = story_dating(ps, at_of, lambda p: (posts.get(p) or {}).get("kind"))
        orig = PP.original_of(ps, at_of, set(mine), root_post, origin_url, release, bg)
        title = (posts.get(orig["post"]) or {}).get("title") or (posts.get(root_post) or {}).get("title")
        return {"story": sid, "mark": mark, "headline": headline or title or None, "joined": list(joined),
                "voices": voice.count((voice.Said(source_of(p), (posts.get(p) or {}).get("kind")) for p in ps
                                       if source_of(p)), voice.Policy.MARKX),   # 0189: a saved page is none
                "newest": max(at_of(p) for p in ps), "first_at": first_at, "original": orig}
    # (head, the block's arguments) of every story; the blocks listed are built in full, the rest only headed
    from insight_core.markx import timeline as TL
    x_heads = {sid: head(sid, ps, "x", heads.get(sid)) for sid, ps in x_members.items() if ps}
    specs = []
    for g in story_entries(cur, x_members, {s: h["voices"] for s, h in x_heads.items()}):
        lead, joined = g[0], g[1:]
        ps = list(dict.fromkeys(p for s in g for p in x_members[s]))
        kw = {"headline": heads.get(lead), "joined": joined}
        specs.append((x_heads[lead] if not joined else head(lead, ps, "x", kw["headline"], joined=joined),
                      (lead, ps, "x"), kw))
    entries = [set(a[1]) for _h, a, _k in specs]
    ix_of = {p: s for p, s in ix_of.items() if not covered(ix_stories[s]["posts"], entries)}
    for sid in sorted(set(ix_of.values())):
        st = ix_stories[sid]
        kw = {"headline": st["origin_title"], "root_post": st["root"],
              "origin_url": st["origin_url"], "origin_title": st["origin_title"]}
        specs.append((head(sid, st["posts"], "ix", kw["headline"], root_post=st["root"], origin_url=st["origin_url"]),
                      (sid, st["posts"], "ix"), kw))
    # v10.35: the stories about it first (its timeline's stops: the stored stop answer, else its share of the members
    # whose subject or actor it is, timeline.stops_of), then those that only name it; each by voices, then the newest
    stops = TL.stops_of(cur, book, root, {a[0]: list(a[1]) for _h, a, _k in specs},
                        {p: at_of(p) for _h, a, _k in specs for p in a[1]},
                        {p for p, ln in lines.items() if ln["roles"] & set(ROLE_REPORT)})
    for h, a, _k in specs:
        h["about"] = stops[a[0]][0]
    specs.sort(key=lambda x: (not x[0]["about"], -x[0]["voices"], -x[0]["newest"].timestamp(), x[0]["story"]))
    every = [h for h, _a, _k in specs]
    listed = specs if stories_limit is None else specs[:stories_limit]
    blocks = [block(*args, **kw) for _h, args, kw in listed]
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
        kids = [x for x in book.with_parent_in(fam_root)   # v10.17 (0186): asked of the book, not walked
                if book.root(x) == x and book.ents[x].status != "not_entity"]
        versions = sorted(({"id": x, "name": book.label(x), "version": book.ents[x].version,
                            "variant": book.ents[x].variant, "level": book.ents[x].level} for x in kids),
                          key=lambda v: (tuple((0, x, "") if isinstance(x, int) else (1, 0, str(x))
                                               for x in (book.ents[v["id"]].version_key or ())), v["name"]),
                          reverse=True)
    named = named_now(cur, book)
    versions = [v for v in versions if v["id"] in named]   # 0138: never a version no current reading names
    # 0165 A: a product's components (things under it, not versions) are listed apart, with their posts
    from insight_core.markx import components as C, stops as ST
    comps = [c for c in C.components_of(book, root) if c in named]
    versions = [v for v in versions if v["id"] not in set(comps)]
    versions = family_versions(book, versions, _post_counts(cur, book, [v["id"] for v in versions]))   # v10.30 (0259)
    comp_posts = _post_counts(cur, book, comps)
    maker = book.root(e.parent) if e.parent and e.level in ("family", "thing") else None
    since = (now - timedelta(days=WINDOW_DAYS)).date()
    from insight_core.markx import entity_brief, entity_facts
    facts = entity_facts.read(cur, [root], senses=True)   # 0184: what it is, and the name's other senses
    page_entity = _ent_view(book, root, facts)
    if maker not in book.ents and page_entity.get("maker_id") in book.ents:
        # v10.35: a version's (or a thing's with no maker parent) maker is the one its names state, as its entity
        # shows it (`_ent_view`: I.cluster_maker, else its facts'); the parent is a maker only for a family or thing
        maker = page_entity["maker_id"]
    if root in facts and facts[root].senses:
        page_entity["senses"] = facts[root].senses
    page = {"entity": page_entity, "asked": entity_id, "redirected": root != entity_id,
            "current": current, **({} if current else {"older": older_posts(cur, book, members)}),   # 0138
            **page_original,   # 0138: its original first, and its other addresses
            "aliases": sorted(book.ents[m].name for m in members),
            "maker": {"id": maker, "name": book.label(maker)} if maker in book.ents else None,
            "family": ({"id": fam_root, "name": book.label(fam_root)} if fam_root and fam_root != root else None),
            "versions": versions, "posts": len(lines), "voices": len(sources),
            "components": [{"id": c, "name": book.label(c), "type": book.shown_type(c), "posts": comp_posts.get(c, 0)}
                           for c in sorted(comps, key=lambda c: (-comp_posts.get(c, 0), book.label(c) or ""))],
            "timeline": TL.of_entity(cur, book, root, stories=[{**h, "members": a[1]} for h, a, _k in specs],
                                     original_post=release),   # 0165 C
            "version_line": TL.version_line(cur, book, root) if ST.config().get("version_line") else None,   # 0220
            "relations": _relations(cur, book, root, members),     # 0220: the relations posts state, the measured ones
            "stories": blocks, "loose": [line(p) for p in (loose if loose_limit is None else loose[:loose_limit])],
            "loose_counts": groups_n,   # 0144 B2-B4
            "stories_total": len(every), "loose_total": len(loose),   # issue 0195
            "by": {"sources": selves["by"], "proposed": selves["proposed"], "posts": len(mine)},   # 0144 B1
            "handles": {"known": known,
                        "posts": len([p for p, r in cited.items() if r["role"] != "reply" or replies]),
                        "replies": hidden_replies, "replies_shown": replies},   # 0168
            "sample": PP.offer(cur, root, {s: h["first_at"] for s, h in x_heads.items()}, now)
            if offer_sample else [],                                                                  # 0144 C
            "sources": sorted(sources.values(), key=lambda s: (-s["posts"], s["name"] or "")),
            **_documents(cur, book, members, lines, line),   # 0133: publisher, works, citing and recommending posts
            "rabbit_hole": _rabbit_hole(cur, book, root, members, len(lines)),   # 0138 E3
            "surges": S.surging(cur, book, since=since).get(root, []), "accuracy": ACCURACY,
            "queue": queue_about(cur, book, root),
            "brief": entity_brief.view(cur, root, names=[book.ents[m].name for m in members])}   # 0261, 0269
    if CONTEXT_ON:
        _with_contexts(cur, book, members, page)   # 0222: the sentences around the mention under each post
    return page, _until(now, every, offer_sample)


def _relations(cur: Any, book: I.Book, root: str, members: Set[str]) -> List[Dict[str, Any]]:
    """0220: its current stated relations (markx/graph.py, the ones switched on), one row a relation, direction and
    other thing (two edges to one group are one row, its posts together), oldest first:
    [{relation, direction, other {id, name, type}, since, posts}]."""
    from insight_core.markx import graph
    rows: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for r in graph.entity_relations(cur, members):
        other = book.root(r["other"])
        if other == root or other not in book.ents or book.ents[other].status == "not_entity":
            continue
        x = rows.setdefault((r["relation"], r["direction"], other), {
            "relation": r["relation"], "direction": r["direction"],
            "other": {"id": other, "name": book.label(other), "type": book.shown_type(other)}, "since": r["since"],
            "posts": 0, "_posts": set()})
        x["_posts"] |= set(r["posts"])
        x["since"] = min(filter(None, (x["since"], r["since"])), default=None)
    out = []
    for x in rows.values():
        x["posts"] = len(x.pop("_posts"))
        out.append(x)
    return sorted(out, key=lambda x: (x["relation"], x["direction"], x["since"] or "", x["other"]["name"] or ""))


# ---- the mention's context under each post (issue 0222) ---------------------------------------------------------

CONTEXT_ON = True        # the measurement's switch (the page built with and without it)
CONTEXT_CHARS = 30000    # a post's text read at most (its first characters: a mention further in shows no context)
CONTEXT_WINDOW = 420     # the context's characters at most (2-4 sentences around the mention)
_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])\s+|\n+")


def _sentences(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each sentence (or line) of `text`, blanks left out."""
    out, at = [], 0
    for m in _SENTENCE_END.finditer(text):
        if text[at:m.start()].strip():
            out.append((at, m.start()))
        at = m.end()
    if text[at:].strip():
        out.append((at, len(text)))
    return out


def _in_address(low: str, at: int) -> bool:
    """Whether position `at` is inside a web address ("github.com/acme/x": a name there is not the post naming it)."""
    a = max(low.rfind(" ", 0, at), low.rfind("\n", 0, at)) + 1
    token = low[a:at]
    return "://" in token or token.startswith("www.") or ("/" in token and "." in token)


def _find(low: str, terms: Sequence[str]) -> Optional[Tuple[int, int]]:
    """The first occurrence (start, end) in `low` of the first term found, in the terms' order (the post's own
    spans first), whole words where the term starts or ends with a word character; one in the text before one inside
    a web address (that only when the text names it nowhere else)."""
    in_address = None
    for t in terms:
        tl = t.lower().strip()
        if len(tl) < 2:
            continue
        pat = (r"(?<!\w)" if tl[0].isalnum() else "") + re.escape(tl) + (r"(?!\w)" if tl[-1].isalnum() else "")
        for m in re.finditer(pat, low):
            if not _in_address(low, m.start()):
                return m.start(), m.end()
            in_address = in_address or (m.start(), m.end())
    return in_address


def mention_context(text: Optional[str], terms: Sequence[str], window: int = CONTEXT_WINDOW
                    ) -> Optional[List[Dict[str, Any]]]:
    """The 2-4 sentences of `text` closest to the first mention of `terms`, as parts [{t, m?}] (m: a mention of a
    term, highlighted), at most `window` characters (cut with an ellipsis); None when no term occurs in the text (the
    post's title stands alone)."""
    if not text or not terms:
        return None
    low = text.lower()
    hit = _find(low, terms)
    if hit is None:
        return None
    sents = _sentences(text)
    k = next((i for i, (a, b) in enumerate(sents) if a <= hit[0] < b), None)
    if k is None:
        lo, hi = max(0, hit[0] - window // 2), min(len(text), hit[1] + window // 2)
    else:
        lo, hi = sents[k]
        # the sentences around it, the next first, while the window has room (up to 4)
        i, j = k, k
        while j - i < 3:
            grown = False
            for nxt in (j + 1, i - 1):
                if 0 <= nxt < len(sents) and nxt not in range(i, j + 1):
                    a, b = min(lo, sents[nxt][0]), max(hi, sents[nxt][1])
                    if b - a <= window:
                        lo, hi = a, b
                        i, j = min(i, nxt), max(j, nxt)
                        grown = True
                        break
            if not grown:
                break
        if hi - lo > window:   # one long sentence: the window around the mention
            lo = max(lo, min(hit[0] - window // 3, hi - window))
            hi = min(hi, lo + window)
    # an ellipsis where the window cuts into a sentence
    lead = "" if lo == 0 or any(a == lo for a, _b in sents) else "… "
    tail = "" if hi == len(text) or any(b == hi for _a, b in sents) else " …"
    piece = text[lo:hi]
    # every mention of a term inside the window, highlighted (the longest first where two overlap)
    marks: List[Tuple[int, int]] = []
    plow = piece.lower()
    for t in sorted({t.lower().strip() for t in terms if len(t.strip()) >= 2}, key=len, reverse=True):
        pat = (r"(?<!\w)" if t[0].isalnum() else "") + re.escape(t) + (r"(?!\w)" if t[-1].isalnum() else "")
        for m in re.finditer(pat, plow):
            if not any(m.start() < e and s < m.end() for s, e in marks):
                marks.append((m.start(), m.end()))
    parts: List[Dict[str, Any]] = []
    at = 0
    for s, e in sorted(marks):
        if s > at:
            parts.append({"t": piece[at:s]})
        parts.append({"t": piece[s:e], "m": True})
        at = e
    if at < len(piece):
        parts.append({"t": piece[at:]})
    for p in parts:   # one line: the breaks and runs of spaces squashed
        p["t"] = re.sub(r"\s+", " ", p["t"])
    if parts:
        parts[0]["t"] = lead + parts[0]["t"].lstrip()
        parts[-1]["t"] = parts[-1]["t"].rstrip() + tail
    return parts


def _contexts(cur: Any, members: Set[str], book: I.Book, want: Dict[str, Set[str]]) -> Dict[str, Any]:
    """{post: mention_context} of the posts shown (`want`: {post: the names its line says it is about}): each post's
    own spans of the cluster's names first, then those names, then the cluster's names; its text's first
    CONTEXT_CHARS read (one query for the shown posts, never the full text sent)."""
    from insight_core.utils.post_parts import Body, shown
    ids = sorted(want)
    if not ids:
        return {}
    cur.execute("""SELECT m.post_id::text, m.span, m.entity_id::text, m.guide, m.n FROM mx_mentions_now m
                    WHERE m.post_id = ANY(%s::uuid[]) AND m.guide = ANY(%s) AND m.span IS NOT NULL""", (ids, _guide()))
    own: Dict[str, List[str]] = defaultdict(list)
    roots = {book.root(m) for m in members}
    for pid, span, eid, g, n in cur.fetchall():
        if eid and span and book.root(book.pins.get((pid, g, n), eid)) in roots:
            own[pid].append(span)
    cur.execute("""SELECT p.id::text, left(p.content, %s), pp.text_cut, pp.text_decode_entities, pp.text_cut_leaves_break,
                          left(pp.text_copy, %s)
                     FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id WHERE p.id = ANY(%s::uuid[])""",
                (CONTEXT_CHARS, CONTEXT_CHARS, ids))
    names = sorted({book.ents[m].name for m in members if m in book.ents}, key=len, reverse=True)
    out: Dict[str, Any] = {}
    for pid, content, cut, decode, brk, copy in cur.fetchall():
        text = shown(content, Body(cut=cut, decode_entities=bool(decode), cut_leaves_break=bool(brk), copy=copy))
        terms = list(dict.fromkeys(sorted(own.get(pid, []), key=len, reverse=True) +
                                   [x.lstrip("@") if x.startswith("@") else x for x in sorted(want[pid])] + names))
        got = mention_context(text, terms)
        if got:
            out[pid] = got
    return out


def _with_contexts(cur: Any, book: I.Book, members: Set[str], page: Dict[str, Any]) -> None:
    """Each shown line about the entity gets `context` (its mention's sentences, `_contexts`); the stories' posts,
    the loose posts, the citing and recommending ones."""
    lines = [ln for b in page["stories"] for ln in b["posts"]] + page["loose"] + page.get("citing", []) + \
        page.get("recommending", [])
    want: Dict[str, Set[str]] = {}
    for ln in lines:
        if ln.get("about"):
            want.setdefault(ln["id"], set()).update(ln.get("named") or ())
    got = _contexts(cur, members, book, want)
    for ln in lines:
        if ln.get("about"):
            ln["context"] = got.get(ln["id"])


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


def flagged_count(cur: Any) -> int:
    """0222: the open items Claude's review flagged for the owner (all the owner is asked by default)."""
    cur.execute("SELECT count(*) FROM mx_entity_queue WHERE flagged_at IS NOT NULL AND answer IS NULL AND closed_at IS NULL")
    return cur.fetchone()[0]


QUEUE_COLS = ("id::text, kind, a::text, b::text, proposal, reason, confidence, evidence, answer, answered_at, created_at, "
              "call_id::text, flagged_at, flagged_by, flag_note")
VIEWS = ("flagged", "all")


def _voids(cur: Any, book: I.Book, rows: Sequence[Tuple]) -> Dict[str, str]:
    """0222: {item id: why} of the open alias items whose Haiku answer (or second opinion) no longer holds: the posts
    its question showed of a side are no longer that side's (identity.void_opinions; read, nothing written). Such an
    item's answer is never shown nor banded; the next run closes it and asks the pair again."""
    calls: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        ev = r[7] or {}
        if r[1] == "alias" and r[8] is None:
            for c in (r[11], ev.get("second_call")):
                if c:
                    calls[str(c)].append(r[0])
    if not calls:
        return {}
    cur.execute("""SELECT c.id::text, t.id::text, t.kind, t.input_hash FROM mx_calls c JOIN mx_tasks t ON t.id = c.task_id
                    WHERE c.id = ANY(%s::uuid[]) AND t.kind IN ('alias', 'alias2', 'alias3', 'alias4')""", (sorted(calls),))
    task_of = {cid: (tid, (kind, h)) for cid, tid, kind, h in cur.fetchall()}
    void = I.void_opinions(cur, book, _guide(), {tid: kh for tid, kh in task_of.values()}, store=False)
    out: Dict[str, str] = {}
    for cid, items in calls.items():
        why = void.get(task_of.get(cid, (None,))[0])
        if why:
            for q in items:
                out.setdefault(q, why)
    return out


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
    cur.execute(f"""SELECT DISTINCT ON (m.entity_id, m.post_id) m.entity_id::text, m.post_id::text, m.span, m.role,
                          {pairing.post_date('p')}
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = ANY(%s) AND m.entity_id = ANY(%s::uuid[])""", (guide, ids))
    by: Dict[str, List[Tuple]] = defaultdict(list)
    for eid, pid, span, role, at in cur.fetchall():
        by[eid].append((role != "subject", -at.timestamp(), pid, span, role))
    pick = {eid: sorted(xs)[:n] for eid, xs in by.items()}
    posts = _posts(cur, {x[2] for xs in pick.values() for x in xs})
    return {eid: [{**{k: (posts.get(x[2]) or {}).get(k) for k in ("id", "title", "source", "at", "byline")},
                   "span": x[3], "role": x[4]} for x in xs] for eid, xs in pick.items()}


def _item(cur: Any, book: I.Book, r: Tuple, ex: Dict[str, List[Dict[str, Any]]],
          joins: Dict[str, Any], void: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One queue row (QUEUE_COLS) as the queue shows it (`ex`: its entities' examples; `joins`: join()'s cache;
    `void`: `_voids`, the items whose answer is about other posts: shown with no answer, no confidence, no band)."""
    qid, kind, a, b, proposal, reason, conf, ev, ans, at, created, _call, flagged_at, flagged_by, flag_note = r
    ev = dict(ev or {})
    why_void = (void or {}).get(qid)
    if why_void:   # 0222: never shown on a stale verdict
        ev.update(judge=None, second=None, disagree=None)
        conf = None
    judge = ev.get("judge") if isinstance(ev.get("judge"), dict) else None
    opinion = None
    if kind == "alias":
        # v10.18: who says what, truthfully: Haiku's answer with its own confidence, or a name rule's proposal (a rule
        # has no confidence; the 0.97 stored on rule-proposed items was a constant for the chain guard's order)
        conf = float(judge["confidence"]) if judge and judge.get("confidence") is not None else None
        opinion = ({"by": "haiku", "relation": judge.get("relation"), "confidence": conf, "rules": ev.get("rules") or []}
                   if judge else {"by": "rule", "rules": ev.get("rules") or []} if ev.get("rules") else None)
    return {"id": qid, "kind": kind, "a": _side(book, a, ex), "b": _side(book, b, ex), "proposal": proposal,
            "join": join(cur, book, a, b, joins) if kind == "alias" and ans is None else None,   # 0164 A
            "reason": reason, "confidence": conf, "answer": ans, "answered_at": at, "created_at": created,
            "opinion": opinion, "void": why_void,   # 0222
            "flag": {"at": flagged_at, "by": flagged_by, "note": flag_note} if flagged_at else None,   # 0222
            # 0130 A1: the measured band Haiku's `same` falls in (none for a rule's proposal or another answer)
            "band": I.band_of(conf) if opinion and opinion["by"] == "haiku" and opinion["relation"] == "same" else None,
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


def queue(cur: Any, *, book: Optional[I.Book] = None, history: int = 50, limit: Optional[int] = None,
          offset: int = 0, view: str = "all") -> Dict[str, Any]:
    """The review queue: {open, answered, merges, counts, accuracy}. Issue 0195: with `limit`, `open` is the page of
    `limit` open items from `offset` (counts.open still counts every open item) and `next_offset` the next page's
    (None at the end); only the shown items are built.

    0222: `view` 'flagged' lists only the open items Claude's review flagged for the owner (the owner's default: every
    other item is decided by its measured band, or stays apart or held and is asked again); 'all' every open item
    (the operator's view). counts.flagged counts the flagged ones; in the flagged view counts.open is every open row.
    An item whose Haiku answer is about posts its sides no longer hold shows no answer (`void`, `_voids`)."""
    if view not in VIEWS:
        raise ValueError(f"view: one of {', '.join(VIEWS)}")
    guide = _guide()
    book = book or I.lazy_book(cur)   # v10.17 (0186): what the queue's items ask of the book
    # Issue 0206: paged in SQL. The open items are read as their ids and sides only (the narrow rows the named test
    # needs: every open item is counted), the answered ones `history` at most; only the rows shown are read whole
    # (their reasons and evidence: 28.9 MB for 12,572 open items on the server before 0195, all read on every page).
    order = "answered_at DESC NULLS LAST, confidence DESC NULLS LAST, created_at, id"   # ties by id (were unordered)
    flagged = view == "flagged"
    cur.execute(f"""SELECT id::text, a::text, b::text FROM mx_entity_queue WHERE closed_at IS NULL AND answer IS NULL
                       {"AND flagged_at IS NOT NULL" if flagged else ""}
                     ORDER BY {"flagged_at DESC, " if flagged else ""}{order}""")
    sides = cur.fetchall()
    named = named_now(cur, book)   # 0138: an item about an entity no current reading names waits, unshown
    if isinstance(named, I._Has):
        named.want({book.root(x) for _q, a, b in sides for x in (a, b) if x})
    open_ids = [q for q, a, b in sides if all(book.root(x) in named for x in (a, b) if x)]
    shown_total = len(open_ids)
    open_total = open_count(cur) if flagged else shown_total
    if limit is not None:
        open_ids = open_ids[offset:offset + limit]
    cur.execute(f"SELECT {QUEUE_COLS} FROM mx_entity_queue WHERE id = ANY(%s::uuid[])", (open_ids,))
    whole = {r[0]: r for r in cur.fetchall()}
    open_rows = [whole[q] for q in open_ids if q in whole]
    cur.execute(f"""SELECT {QUEUE_COLS} FROM mx_entity_queue WHERE closed_at IS NULL AND answer IS NOT NULL
                     ORDER BY {order} LIMIT %s""", (history,))
    done_rows = cur.fetchall()
    book.prime(ids=[x for r in open_rows + done_rows for x in (r[2], r[3]) if x])
    ex = _examples(cur, {x for r in open_rows + done_rows for x in (r[2], r[3]) if x}, guide)
    void = _voids(cur, book, open_rows)
    joins: Dict[str, Any] = {}

    def item(r) -> Dict[str, Any]:
        return _item(cur, book, r, ex, joins, void)

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
            "counts": {"open": open_total, "answered": answered, "automatic_merges": auto_live,
                       "automatic_undone": auto_undone, "flagged": shown_total if flagged else flagged_count(cur)},
            "accuracy": ACCURACY, "view": view,
            **({} if limit is None else {"next_offset": offset + limit if offset + limit < shown_total else None})}


def queue_about(cur: Any, book: I.Book, root: str) -> List[Dict[str, Any]]:
    """The open items whose side `a` or `b` is `root` itself, as queue()'s `open` shows them: the entity page's
    questions (issue 0195: only these are built, not every open item of the queue). 0222: flagged ones first."""
    guide = _guide()
    cur.execute(f"""SELECT {QUEUE_COLS} FROM mx_entity_queue WHERE closed_at IS NULL AND answer IS NULL
                      AND (a = %s::uuid OR b = %s::uuid)
                    ORDER BY flagged_at DESC NULLS LAST, confidence DESC NULLS LAST, created_at""", (root, root))
    rows = cur.fetchall()
    book.prime(ids=[x for r in rows for x in (r[2], r[3]) if x])
    named = named_now(cur, book)
    if isinstance(named, I._Has):
        named.want({book.root(x) for r in rows for x in (r[2], r[3]) if x})
    mine = [r for r in rows if all(book.root(x) in named for x in (r[2], r[3]) if x)]
    ex = _examples(cur, {x for r in mine for x in (r[2], r[3]) if x}, guide)
    void = _voids(cur, book, mine)
    joins: Dict[str, Any] = {}
    return [_item(cur, book, r, ex, joins, void) for r in mine]


THINGS_SHOWN = 12   # 0250: a story page's things at most
THING_ROLES = ("subject", "actor", "compared", "predecessor", "venue", "source", "recommended", "mention")


def story_things(cur: Any, post_ids: Iterable[str], *, shown: int = THINGS_SHOWN) -> List[Dict[str, Any]]:
    """0250: "Things in this story": the entities its members' current readings name (through the merges and pins),
    each with the best role a member gives it (subject first: THING_ROLES' order) and how many members name it, ranked
    by that role, then that count, then name: [{id, name, type, maker, maker_id, role, posts}], `shown` at most. An
    entity marked not one is left out."""
    ids = sorted(set(post_ids))
    if not ids:
        return []
    cur.execute("""SELECT post_id::text, guide, n, entity_id::text, role FROM mx_mentions_now
                    WHERE guide = ANY(%s) AND post_id = ANY(%s::uuid[]) AND entity_id IS NOT NULL""", (_guide(), ids))
    rows = cur.fetchall()
    if not rows:
        return []
    book = I.lazy_book(cur)   # the merges and pins (few), each entity read by need
    book.prime(ids=[x for p, g, n, e, _r in rows for x in (e, book.pins.get((p, g, n))) if x])
    rank = {r: k for k, r in enumerate(THING_ROLES)}
    best: Dict[str, int] = {}
    posts: Dict[str, Set[str]] = defaultdict(set)
    for p, g, n, e, role in rows:
        r = book.root(book.pins.get((p, g, n), e))
        if r is None or r not in book.ents or book.ents[r].status == "not_entity":
            continue
        best[r] = min(best.get(r, len(THING_ROLES)), rank.get(role or "mention", len(THING_ROLES)))
        posts[r].add(p)
    order = sorted(best, key=lambda r: (best[r], -len(posts[r]), (book.label(r) or "").lower(), r))[:shown]
    out = []
    for r in order:
        v = _ent_view(book, r)
        out.append({"id": r, "name": v["name"], "type": v["type"], "maker": v["maker"], "maker_id": v["maker_id"],
                    "role": THING_ROLES[best[r]] if best[r] < len(THING_ROLES) else "mention", "posts": len(posts[r])})
    return out


def post_entities(cur: Any, post_id: str) -> Dict[int, Optional[str]]:
    """{mention n: the entity it shows under (root, through pins)} for the post page's panel."""
    book = I.lazy_book(cur)   # v10.17 (0186): the merges and pins, not the whole book
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
    book = I.lazy_book(cur)   # v10.17 (0186): the surging entities' clusters, not the whole book
    book.prime(ids=[eid for eid, _d, _v, _p in rows])
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for eid, day, voices, pid in rows:
        root = book.root(eid) or eid
        if root in book.ents and not any(x["id"] == root for x in out[pid]):
            out[pid].append({"id": root, "name": book.label(root), "day": day.isoformat(), "voices": voices})
    return dict(out)
