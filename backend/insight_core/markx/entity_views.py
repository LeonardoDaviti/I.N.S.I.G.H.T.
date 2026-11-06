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
    the history: answered items and the merges (automatic ones can be undone).
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
    "merges": "automatic merges 97.6% right on unseen posts (40/41, Wilson 87-100%; lab, 2026-11-06)",
    "surges": f"surges {S.PRECISION}",
    "collisions": "collision splits 55% right (6/11, lab): each is a question, never applied by itself",
}


def _guide() -> str:
    from insight_core.markx import schemas
    return schemas.KINDS["entities"].guide


def _rows(cur: Any, guide: str, since: Optional[datetime], entity_ids: Optional[Iterable[str]] = None):
    """Mentions with their post's time, source and read state: (post, n, role, entity, at, source id, read)."""
    where, params = ["m.guide = %s", "m.entity_id IS NOT NULL"], [guide]
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
                           rs.read_at IS NOT NULL
                      FROM mx_mentions m JOIN posts p ON p.id = m.post_id
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
    e = book.ents[eid]
    return {"id": e.id, "name": e.name, "type": e.type, "maker": e.maker, "level": e.level,
            "version": e.version, "variant": e.variant, "size": e.size, "build": e.build, "status": e.status,
            "family": _family_of(book, eid)}


def _family_of(book: I.Book, eid: str) -> Optional[Dict[str, str]]:
    e = book.ents[eid]
    if e.level in ("version", "variant", "checkpoint") and e.parent:
        f = book.root(e.parent)
        if f in book.ents:
            return {"id": f, "name": book.ents[f].name}
    return None


def _when(at: Optional[datetime], now: datetime) -> Optional[str]:
    if at is None:
        return None
    days = (now.date() - at.astimezone(timezone.utc).date()).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def entity_list(cur: Any, *, now: Optional[datetime] = None, limit: int = LIST_LIMIT) -> Dict[str, Any]:
    from insight_core.markx.news import _posts
    now = now or datetime.now(timezone.utc)
    guide = _guide()
    book = I.load_book(cur)
    since = now - timedelta(days=WINDOW_DAYS)
    agg: Dict[str, Dict[str, Any]] = {}
    for pid, n, role, eid, at, src, read in _rows(cur, guide, since):
        eid = book.root(book.pins.get((pid, guide, n), eid))
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


def _members(book: I.Book, root: str) -> Set[str]:
    return {e for e in book.ents if book.root(e) == root}


def entity_page(cur: Any, entity_id: str, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    from insight_core.markx.news import _posts
    now = now or datetime.now(timezone.utc)
    guide = _guide()
    book = I.load_book(cur)
    if entity_id not in book.ents:
        return None
    root = book.root(entity_id)
    members = _members(book, root)
    lines: Dict[str, Dict[str, Any]] = {}
    for pid, n, role, eid, at, src, read in _rows(cur, guide, None, members):
        if book.root(book.pins.get((pid, guide, n), eid)) != root:
            continue
        ln = lines.setdefault(pid, {"roles": set(), "at": at, "source_id": src, "read": read, "as": set()})
        ln["roles"].add(role or "mention")
        ln["as"].add(book.ents[eid].name if eid in book.ents else "")
    posts = _posts(cur, lines)
    story_of = _stories(cur, lines)
    heads = _story_heads(cur, {s for ss in story_of.values() for s in ss})
    groups: Dict[str, List[str]] = defaultdict(list)
    for pid in lines:
        for s in story_of.get(pid) or ["-"]:
            groups[s].append(pid)

    def line(pid: str) -> Dict[str, Any]:
        p = posts.get(pid) or {"id": pid}
        ln = lines[pid]
        return {**{k: p.get(k) for k in ("id", "title", "source", "kind", "at", "url")},
                "roles": sorted(ln["roles"]), "read": ln["read"], "named": sorted(x for x in ln["as"] if x)}
    blocks = []
    for sid, ps in groups.items():
        if sid == "-":
            continue
        ps.sort(key=lambda p: (lines[p]["at"], p))
        blocks.append({"story": sid, "headline": heads.get(sid),
                       "voices": len({lines[p]["source_id"] for p in ps}),
                       "newest": max(lines[p]["at"] for p in ps), "posts": [line(p) for p in ps]})
    blocks.sort(key=lambda b: (-b["voices"], -b["newest"].timestamp(), b["story"]))
    loose = sorted(groups.get("-", []), key=lambda p: (-lines[p]["at"].timestamp(), p))
    sources: Dict[str, Dict[str, Any]] = {}
    for pid, ln in lines.items():
        p = posts.get(pid) or {}
        s = sources.setdefault(ln["source_id"], {"id": ln["source_id"], "name": p.get("source"), "kind": p.get("kind"),
                                                 "posts": 0, "reports": 0})
        s["posts"] += 1
        s["reports"] += 1 if ln["roles"] & set(ROLE_REPORT) else 0
    e = book.ents[root]
    fam_root = root if e.level in ("family", "thing") else (_family_of(book, root) or {}).get("id")
    versions = []
    if fam_root:
        kids = [x for x, ent in book.ents.items() if ent.parent and book.root(ent.parent) == fam_root
                and book.root(x) == x and ent.status != "not_entity"]
        versions = sorted(({"id": x, "name": book.ents[x].name, "version": book.ents[x].version,
                            "variant": book.ents[x].variant, "level": book.ents[x].level} for x in kids),
                          key=lambda v: (tuple((0, x, "") if isinstance(x, int) else (1, 0, str(x))
                                               for x in (book.ents[v["id"]].version_key or ())), v["name"]),
                          reverse=True)
    maker = book.root(e.parent) if e.parent and e.level in ("family", "thing") else None
    since = (now - timedelta(days=WINDOW_DAYS)).date()
    return {"entity": _ent_view(book, root), "asked": entity_id, "redirected": root != entity_id,
            "aliases": sorted(book.ents[m].name for m in members),
            "maker": {"id": maker, "name": book.ents[maker].name} if maker in book.ents else None,
            "family": ({"id": fam_root, "name": book.ents[fam_root].name} if fam_root and fam_root != root else None),
            "versions": versions, "posts": len(lines), "voices": len(sources),
            "stories": blocks, "loose": [line(p) for p in loose],
            "sources": sorted(sources.values(), key=lambda s: (-s["posts"], s["name"] or "")),
            "surges": S.surging(cur, book, since=since).get(root, []), "accuracy": ACCURACY,
            "queue": [q for q in queue(cur, book=book)["open"] if root in (q["a"]["id"], (q.get("b") or {}).get("id"))]}


def open_count(cur: Any) -> int:
    cur.execute("SELECT count(*) FROM mx_entity_queue WHERE answer IS NULL AND closed_at IS NULL")
    return cur.fetchone()[0]


def _side(book: I.Book, eid: Optional[str], examples: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if not eid or eid not in book.ents:
        return None
    return {**_ent_view(book, eid), "root": book.root(eid), "posts": examples.get(eid, [])}


def _examples(cur: Any, eids: Iterable[str], guide: str, n: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    from insight_core.markx.news import _posts
    ids = sorted(set(eids))
    if not ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (m.entity_id, m.post_id) m.entity_id::text, m.post_id::text, m.span, m.role,
                          COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                     FROM mx_mentions m JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = %s AND m.entity_id = ANY(%s::uuid[])""", (guide, ids))
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
    open_rows = [r for r in rows if r[8] is None]
    done_rows = [r for r in rows if r[8] is not None][:history]
    ex = _examples(cur, {x for r in open_rows + done_rows for x in (r[2], r[3]) if x}, guide)

    def item(r) -> Dict[str, Any]:
        qid, kind, a, b, proposal, reason, conf, ev, ans, at, created = r
        ev = ev or {}
        return {"id": qid, "kind": kind, "a": _side(book, a, ex), "b": _side(book, b, ex), "proposal": proposal,
                "reason": reason, "confidence": conf, "answer": ans, "answered_at": at, "created_at": created,
                "evidence": {"judge": ev.get("judge"), "rules": ev.get("rules"), "senses": ev.get("senses"),
                             "mentions": [{k: m.get(k) for k in ("n", "span", "type", "maker")}
                                          for m in ev.get("mentions") or []],
                             "split_runs": ev.get("split_runs"), "runs": ev.get("runs")}}
    cur.execute("""SELECT r.id::text, r.from_id::text, r.to_id::text, r.by, r.automatic, r.at, r.undone_at, r.evidence
                     FROM mx_entity_redirects r ORDER BY r.at DESC LIMIT %s""", (history,))
    merges = [{"id": rid, "from": {"id": f, "name": book.ents[f].name if f in book.ents else None},
               "to": {"id": t, "name": book.ents[t].name if t in book.ents else None}, "by": by, "automatic": auto,
               "at": at, "undone_at": undone, "confidence": (ev or {}).get("confidence")}
              for rid, f, t, by, auto, at, undone, ev in cur.fetchall()]
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
    guide = _guide()
    book = I.load_book(cur)
    cur.execute("SELECT n, entity_id::text FROM mx_mentions WHERE post_id = %s AND guide = %s", (post_id, guide))
    return {n: book.root(book.pins.get((post_id, guide, n), eid)) if eid else None for n, eid in cur.fetchall()}


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
            out[pid].append({"id": root, "name": book.ents[root].name, "day": day.isoformat(), "voices": voices})
    return dict(out)
