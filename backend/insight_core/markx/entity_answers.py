"""The owner's answers to Mark X's entity review queue (issue 0119 A1, A3): applied at once, in the request's own
transaction, writing mx_entity* rows and mx_labels only (never mx_mentions: a split is a pin the next run applies, and
every page reads through redirects and pins, so the answer shows at once).

  - an alias pair: `same` merges (a redirect by the owner); `other_version`, `different` and `not_entity` keep the two
    apart, undoing any merge that joined them; they are never merged by a rule or Haiku again;
  - a collision: `different` or `other_version` splits it as proposed (each sense but the largest an entity of its
    own, the mentions the question showed pinned there); `same` keeps one page; `not_entity` marks the entity;
  - an automatic merge from the history: `undo` closes its redirect.
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
    if item["kind"] == "alias":
        if ans == "same":
            applied["redirect"] = I.merge(cur, book, a, b, by="owner", automatic=False, call_id=item["call_id"],
                                          queue_id=item_id, evidence={"queue": item_id})
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
