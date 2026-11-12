"""The owner's answers to Mark X's entity review queue (issue 0119 A1, A3): applied at once, in the request's own
transaction, writing mx_entity* rows and mx_labels only (never mx_mentions: a split is a pin the next run applies, and
every page reads through redirects and pins, so the answer shows at once).

  - an alias pair: `same` merges (a redirect by the owner; 0164 A: when the two clusters would put a product family
    and an org together, only the two names join, `owner_same`); `other_version`, `different` and `not_entity` keep the two
    apart, undoing any merge that joined them; they are never merged by a rule or Haiku again;
  - a collision: `different` or `other_version` splits it as proposed (each sense but the largest an entity of its
    own, the mentions the question showed pinned there); `same` keeps one page; `not_entity` marks the entity;
  - an automatic merge from the history: `undo` closes its redirect;
  - a rename (0165 B): `same` redirects the older name's cluster into the newer's (kind 'rename': the older names are
    shown as earlier names); the other answers keep them apart, undoing any merge that joined them.
Each answer is also a label: mx_labels item kind `entity`, a and b the two entities, split `test`, the queue item in
its note.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from insight_core.markx import identity as I
from insight_core.markx import names as N

ANSWERS = I.ANSWERS


class NotFound(LookupError):
    pass


def _confirm(cur: Any, *eids: Optional[str]) -> None:
    cur.execute("UPDATE mx_entities SET status = 'confirmed' WHERE id = ANY(%s::uuid[]) AND status = 'provisional'",
                ([e for e in eids if e],))


def _label(cur: Any, *, a: str, b: Optional[str], answer: str, note: Dict[str, Any]) -> str:
    from insight_core.markx import repo
    return str(repo.add_label(cur, item_kind="entity", a=a, b=b, answer=answer, split="test",
                              note=json.dumps(note, default=str)))


def _path(book: I.Book, eid: str) -> List[str]:
    out, seen = [eid], {eid}
    while out[-1] in book.redirect and book.redirect[out[-1]][0] not in seen:
        out.append(book.redirect[out[-1]][0])
        seen.add(out[-1])
    return out


def separate(cur: Any, book: I.Book, a: str, b: str) -> List[str]:
    """Undo the redirects that put a and b in one cluster (b's side first): the redirects undone."""
    undone: List[str] = []
    while book.root(a) == book.root(b) and a != b:
        pa, pb = _path(book, a), _path(book, b)
        common = next(x for x in pb if x in set(pa))
        side = pb if pb.index(common) > 0 else pa
        frm = side[side.index(common) - 1]
        cur.execute("""UPDATE mx_entity_redirects SET undone_at = now(), undone_by = 'owner'
                        WHERE from_id = %s AND undone_at IS NULL RETURNING id::text""", (frm,))
        row = cur.fetchone()
        if row:
            undone.append(row[0])
        book.redirect.pop(frm, None)
    return undone


def split(cur: Any, book: I.Book, item: Dict[str, Any]) -> Dict[str, Any]:
    """Each sense but the largest becomes an entity of its own (senses related as `part` stay together), and the
    mentions the question showed in it are pinned there."""
    from insight_core.markx import schemas
    guide = schemas.KINDS["entities"].guide
    ev = item["evidence"] or {}
    e = book.ents[str(item["a"])]
    senses = ev.get("senses") or []
    n = max([int(x) for s in senses for x in s.get("m") or []] + [0])
    rel = I.pairrel({"senses": senses, "related": ev.get("related") or []}, n)
    groups: List[List[int]] = []
    for s in senses:
        ms = [int(x) for x in s.get("m") or []]
        if not ms:
            continue
        home = next((g for g in groups if rel.get((min(g[0], ms[0]), max(g[0], ms[0]))) == "part"), None)
        if home is not None:
            home.extend(ms)
        else:
            groups.append(list(ms))
    groups.sort(key=lambda g: -len(g))
    posts_of = {int(r["n"]): [tuple(x) for x in r.get("posts") or []] for r in ev.get("mentions") or []}
    what = {int(x): (s.get("what") or "").strip() for s in senses for x in s.get("m") or []}
    made, pinned = [], 0
    for g in groups[1:]:
        label = next((what[x] for x in g if what.get(x)), "")[:60]
        name = f"{e.name} ({label})" if label else f"{e.name} ({len(made) + 2})"
        cur.execute("""INSERT INTO mx_entities (type, name, key, level, parent, maker, status, first_seen)
                       VALUES (%s, %s, %s, 'thing', %s, NULL, 'confirmed', %s) RETURNING id::text""",
                    (e.type, name, N.key(name), e.parent, e.first_seen))
        new = cur.fetchone()[0]
        made.append(new)
        for x in g:
            for pid, mn in posts_of.get(x, []):
                from insight_core.markx import repo   # 0133: the pin names the post's current set's guide
                guide = repo.current_guide(cur, pid) or schemas.KINDS["entities"].guide
                cur.execute("""INSERT INTO mx_entity_pins (post_id, guide, n, entity_id, queue_id)
                               SELECT %s, %s, %s, %s, %s WHERE NOT EXISTS (
                                 SELECT 1 FROM mx_entity_pins WHERE post_id = %s AND guide = %s AND n = %s
                                    AND undone_at IS NULL)""",
                            (pid, guide, mn, new, item["id"], pid, guide, mn))
                pinned += cur.rowcount
    _confirm(cur, e.id)
    return {"entities": made, "pinned": pinned}


def queue_get(cur: Any, item_id: str) -> Optional[Dict[str, Any]]:
    keys = ("id", "kind", "a", "b", "proposal", "reason", "confidence", "evidence", "call_id", "answer", "answered_at",
            "applied", "closed_at", "created_at")
    cur.execute(f"""SELECT id::text, kind, a::text, b::text, proposal, reason, confidence, evidence, call_id::text, answer,
                           answered_at, applied, closed_at, created_at FROM mx_entity_queue WHERE id = %s""", (item_id,))
    row = cur.fetchone()
    return None if row is None else dict(zip(keys, row))


# ---- 0164 A: the owner's `same` never joins a family to an org blindly ------------------------------------------

def join_plan(book: I.Book, a: str, b: str) -> Dict[str, Any]:
    """What `same` on a and b does to their clusters. {mixes: False}: merging the two roots puts no product family
    and org (or person) in one cluster (Book.sides): the roots merge as ever. Else {mixes: True, kind: the side the
    two names are on ('family' / 'org'), detach: [(an answered name, its cluster, the members of the other kind it
    must leave)]}; kind None when the names are of two kinds or neither (the owner chooses: `needs_choice`)."""
    ra, rb = book.root(a), book.root(b)
    if ra is None or rb is None or ra == rb or ra not in book.ents or rb not in book.ents:
        return {"mixes": False}
    ca, cb = book.cluster(ra), book.cluster(rb)
    fam, org = book.sides(ca + cb)
    if not (fam and org):
        return {"mixes": False}
    kinds = {x: "family" if x in fam else "org" if x in org else None for x in (a, b)}
    got = {k for k in kinds.values() if k}
    if len(got) != 1:
        return {"mixes": True, "kind": None, "detach": []}
    kind = got.pop()
    other = org if kind == "family" else fam
    detach = [(x, sorted(c), sorted(set(c) & other)) for x, c in ((a, ca), (b, cb)) if set(c) & other]
    return {"mixes": True, "kind": kind, "detach": detach}


def _group_name(book: I.Book, members: List[str]) -> str:
    """The name a set of a cluster's members goes by: its root's shown name when the root is in it, else its names."""
    roots = {book.root(m) for m in members}
    r = next(iter(roots)) if len(roots) == 1 else None
    if r in members:
        return book.label(r) or book.ents[r].name
    names = sorted({book.ents[m].name for m in members})
    return ", ".join(names[:3]) + (" …" if len(names) > 3 else "")


def _held_message(book: I.Book, x: str, others: List[str]) -> str:
    return (f"“{book.ents[x].name}” is held with {_group_name(book, others)} by your own earlier merge, so “same” "
            f"would join a product family and an org. Undo that merge in the history first, or answer another way.")


def owner_same(cur: Any, book: I.Book, item: Dict[str, Any]) -> Dict[str, Any]:
    """The owner's `same` on an alias item (0164 A). When merging the two roots would put a product family and an org
    in one cluster, only the two names join: each answered name first leaves the members of the other kind its
    cluster holds (the automatic merges that hold it there undone, undone_by 'owner_answer', the why in their
    evidence, as the repair's cut), then the two names merge (the owner's redirect). When only the owner's own earlier
    merge holds it there, or the names are of two kinds, nothing is written: {result: 'needs_choice', message}."""
    from insight_core.markx import entity_repair as R
    a, b, qid = item["a"], item["b"], item["id"]
    plan = join_plan(book, a, b)
    ev: Dict[str, Any] = {"queue": qid}
    out: Dict[str, Any] = {}
    if plan["mixes"]:
        if plan["kind"] is None:
            return {"result": "needs_choice", "message": (
                f"“{book.ents[a].name}” and “{book.ents[b].name}” are a product family’s name and an org’s: “same” "
                "would join a family and an org. Answer another way, or undo the merge that put one of them there.")}
        rows, owner = R.redirect_rows(cur), R._owner_same(cur)
        detached: List[str] = []
        kept_apart: List[str] = []
        cur.execute("SAVEPOINT owner_same")
        for x, members, others in plan["detach"]:
            edges = R.cluster_edges(book, members, rows, owner)
            cuts = R._cuts(members, [(p, q, o) for p, q, o, _ in edges], {x}, set(others))
            if cuts is None:
                cur.execute("ROLLBACK TO SAVEPOINT owner_same")
                return {"result": "needs_choice", "message": _held_message(book, x, others)}
            kept_apart.append(_group_name(book, others))
            why = {"why": "owner_answer", "queue": qid, "name": book.ents[x].name,
                   "kept_apart": sorted(book.ents[o].name for o in others)[:8],
                   "joined": [book.ents[a].name, book.ents[b].name]}
            undone, _ = R.apply_cuts(cur, book, members, edges, cuts, rows, why=why, undone_by="owner_answer")
            detached += undone
            rows = R.redirect_rows(cur)
        fam, org = book.sides(book.cluster(book.root(a)) + book.cluster(book.root(b)))
        if fam and org:
            cur.execute("ROLLBACK TO SAVEPOINT owner_same")
            return {"result": "needs_choice", "message": (
                f"“same” would still join a product family ({_group_name(book, sorted(fam))}) and an org "
                f"({_group_name(book, sorted(org))}). Undo the merge that holds them in the history, or answer another way.")}
        cur.execute("RELEASE SAVEPOINT owner_same")
        ev.update(joined_only=True, detached=detached)
        out.update(result="joined_names", detached=detached, kept_apart=kept_apart)
    out["redirect"] = I.merge(cur, book, a, b, by="owner", automatic=False, call_id=item["call_id"], queue_id=qid,
                              evidence=ev)
    return out


def owner_rename(cur: Any, book: I.Book, item: Dict[str, Any]) -> Dict[str, Any]:
    """0165 B: the owner's `same` on a rename item (a = the older name, b = the newer): the older cluster redirects into
    the newer one (kind 'rename', markx/rename.merge). Like 0164 A's `same`, never a product family joined to an org
    blindly: when the two clusters would mix them, nothing is written ({result: 'needs_choice', message})."""
    from insight_core.markx import rename
    a, b = item["a"], item["b"]
    if join_plan(book, a, b)["mixes"]:
        return {"result": "needs_choice", "message": (
            f"“{book.ents[a].name}” and “{book.ents[b].name}” are in groups holding a product family and an org: "
            "a rename would join them. Undo the merge that put one of them there first, or answer another way.")}
    return {"redirect": rename.merge(cur, book, a, b, queue_id=item["id"], call_id=item["call_id"],
                                     evidence={"queue": item["id"]}), "renamed": True}


def answer(cur: Any, item_id: str, ans: str, note: Optional[str] = None) -> Dict[str, Any]:
    """The owner's answer to one review item, applied at once and labelled."""
    if ans not in ANSWERS:
        raise ValueError(f"answer: one of {', '.join(ANSWERS)}")
    item = queue_get(cur, item_id)
    if item is None:
        raise NotFound(item_id)
    book = I.load_book(cur)
    a, b = item["a"], item["b"]
    applied: Dict[str, Any] = {"answer": ans}
    if item["kind"] == "rename":    # 0165 B: `same` = one thing, renamed: the older name becomes the newer's earlier name
        if ans == "same":
            got = owner_rename(cur, book, item)
            if got.get("result") == "needs_choice":
                return {**applied, **got}
            applied.update(got)
            _confirm(cur, a, b)
        else:
            applied["undone"] = separate(cur, book, a, b)
            if ans != "not_entity":
                _confirm(cur, a, b)
    elif item["kind"] == "alias":
        if ans == "same":
            got = owner_same(cur, book, item)
            if got.get("result") == "needs_choice":
                return {**applied, **got}       # nothing written: the item stays open, the message says why
            applied.update(got)
            _confirm(cur, a, b)
        else:
            applied["undone"] = separate(cur, book, a, b)
            if ans != "not_entity":
                _confirm(cur, a, b)
    elif ans in ("different", "other_version"):
        applied.update(split(cur, book, item))
    elif ans == "not_entity":
        cur.execute("UPDATE mx_entities SET status = 'not_entity' WHERE id = %s", (a,))
    else:
        _confirm(cur, a)
    cur.execute("UPDATE mx_entity_queue SET answer = %s, answered_at = now(), applied = %s::jsonb WHERE id = %s",
                (ans, json.dumps(applied, default=str), item_id))
    applied["label"] = _label(cur, a=a, b=b, answer=ans, note={
        "queue": item_id, "kind": item["kind"], "proposal": item["proposal"], "reason": item["reason"],
        "note": (note or "").strip() or None})
    return applied


def undo(cur: Any, redirect_id: str, note: Optional[str] = None) -> Dict[str, Any]:
    """Undo one merge from the history: its redirect closes, the pair is never merged automatically again, and the
    answer is a label ('different')."""
    cur.execute("""UPDATE mx_entity_redirects SET undone_at = now(), undone_by = 'owner'
                    WHERE id = %s AND undone_at IS NULL RETURNING from_id::text, to_id::text, by, automatic""",
                (redirect_id,))
    row = cur.fetchone()
    if row is None:
        raise NotFound(redirect_id)
    frm, to, by, automatic = row
    label = _label(cur, a=frm, b=to, answer="different",
                   note={"undo": redirect_id, "by": by, "automatic": automatic, "note": (note or "").strip() or None})
    return {"undone": redirect_id, "label": label}
