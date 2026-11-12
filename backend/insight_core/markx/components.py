"""A product's components get their own entity (issue 0165 A).

A mention written "<product> <name>" ("Acme Forge Snap": the product Forge, the name Snap) whose post is about the
name, not the product, is linked to the component's own entity, with the product as its parent (`parent` = the
product's root; level `thing`, as a maker's thing is). The parent's page lists its components; a component's posts are
its own. Called by the linking (identity.stage) for the mentions it links, before their keys' entities are made.

The rule, from the reading, never a word list:
  - **the shape**: the mention's name, or its span when the span says more than the name (the name the product's,
    "NVIDIA Forge" for the span "NVIDIA Forge Snap"), is a known product's name followed by more words: the longest
    leading words that are a name key of a product cluster (not an org or person, not `not_entity`: a family, a
    version's parent, or a thing whose mentions type it a model, product or software), at least one word after it,
    the rest of 3+ characters, not a version, variant, size or build (a version is a version: the version guard), not
    an org's word ("Forge Labs"); the product's stated maker and the mention's the same maker, or one none;
  - **the evidence** (one of): the mention is its post's subject (role `subject`); the post's entities answer marks
    it `part_of` the product (its `relations`); the post's reading names it as its object (read-v2's main.object).
  A mention whose name the parser reads as versioned keeps its version entity (entity_for's), whatever its words.

What it writes (only when entity_bands.json `timeline.components` is on; `plan` alone writes nothing, for measuring):
  - a component key with no entity yet: its entity, made under the product (`make`);
  - a component entity already made under its maker (or nothing): its parent becomes the product, logged in
    mx_entity_fixes (kind 'component', field 'parent', old and new; undoable), never one the owner made;
  - a mention whose span is the component's but whose name is the product's: `Book.components` sends it to the
    component's entity (identity.resolve_mention reads it, after the owner's pins).
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N

MIN_REST = 3          # characters the component's own words keep once squashed


def config() -> Dict[str, Any]:
    got = I.bands().get("timeline") or {}
    return {"components": bool(got.get("components", False)), "renames": bool(got.get("renames", True)),
            "rename_cap": int(got.get("rename_cap", 200)), "rename_overlap_days": int(got.get("rename_overlap_days", 7))}


def product_like(book: I.Book, root: Optional[str]) -> bool:
    """A cluster a component can belong to: a product family or a product-typed thing, not an org or person."""
    if root is None or root not in book.ents:
        return False
    e = book.ents[root]
    if e.status == "not_entity" or e.level in I.VERSION_LEVELS:
        return False
    if book.org_like(root):
        return False
    fam, org = book.sides(book.cluster(root))
    if org:
        return False
    return bool(fam) or book.etype(root) in I.PRODUCT_TYPES


def split(book: I.Book, key: str, maker: Optional[str]) -> Optional[Tuple[str, str, str]]:
    """(the product's root, the product's words, the component's own words) of a name key "<product> <rest>", the
    longest product prefix first; None when the key is no product's name followed by more."""
    words = (key or "").split()
    for i in range(len(words) - 1, 0, -1):
        head, rest = " ".join(words[:i]), " ".join(words[i:])
        if len(N.squash(rest)) < MIN_REST or words[-1] in I.CORP_WORDS:
            continue
        got = book.by_key(head)
        root = book.root(got) if got else None
        if not product_like(book, root):
            continue
        if N.has_version(N.fields_key(N.parse(rest, "software", None), None)):
            continue                                       # "Forge 2": a version, never a component
        pm = book.ents[root].maker
        if maker and pm and not I.same_maker(book, maker, pm):
            continue
        return root, head, rest
    return None


def _versioned(m: I.Mention) -> bool:
    if m.type not in I.TYPES_VERSIONED:
        return False
    hk = N.fields_key(m.fields, m.maker)
    pk = N.fields_key(N.parse(m.name, m.type, m.maker), m.maker)
    return N.has_version(hk) or N.has_version(pk)


def _evidence(cur: Any, ms: Sequence[Tuple[I.Mention, str, str]]) -> Dict[Tuple[str, str, int], str]:
    """{mention: why it is about the component}: its role, its answer's `part_of`, or its post's reading's object."""
    out: Dict[Tuple[str, str, int], str] = {}
    rest: List[Tuple[I.Mention, str, str]] = []
    for m, comp, head in ms:
        if (m.role or "") == "subject":
            out[(m.post_id, m.guide, m.n)] = "subject"
        else:
            rest.append((m, comp, head))
    if not rest:
        return out
    calls = sorted({m.call_id for m, _, _ in rest if m.call_id})
    rels: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    if calls:
        cur.execute("SELECT id::text, answer->'relations' FROM mx_calls WHERE id = ANY(%s::uuid[])", (calls,))
        for cid, got in cur.fetchall():
            for r in got or []:
                if isinstance(r, dict):
                    rels[cid].append((N.key(r.get("a")), str(r.get("rel") or ""), N.key(r.get("b"))))
    posts = sorted({m.post_id for m, _, _ in rest})
    cur.execute("""SELECT post_id::text, reading->'main'->>'object' FROM mx_readings
                    WHERE post_id = ANY(%s::uuid[]) AND guide = 'read-v2'""", (posts,))
    obj = {pid: N.key(o) for pid, o in cur.fetchall() if o}
    for m, comp, head in rest:
        k = (m.post_id, m.guide, m.n)
        if any(rel == "part_of" and a in (comp, N.key(m.span)) and (b == head or b.endswith(" " + head) or head.endswith(" " + b))
               for a, rel, b in rels.get(m.call_id or "", ())):
            out[k] = "part_of"
        elif obj.get(m.post_id) and set(comp.split()) <= set(obj[m.post_id].split()):
            out[k] = "reading"
    return out


def plan(cur: Any, book: I.Book, ms: Iterable[I.Mention]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    """{mention: {key, name, product, why, by_span}}: the mentions the rule gives a component (writes nothing)."""
    cands: List[Tuple[I.Mention, str, str, str, str, bool]] = []   # (m, comp key, comp name, product root, head, by span)
    for m in ms:
        if not m.key or _versioned(m) or I.schemas_type(m.type) in I.ORGISH or I.schemas_type(m.type) == "document":
            continue
        pin = book.pins.get((m.post_id, m.guide, m.n))
        if pin:
            continue                                       # the owner's split wins
        got = split(book, m.key, m.maker)
        if got is not None:
            cands.append((m, m.key, m.name, got[0], got[1], False))
            continue
        sk = N.key(m.span)
        if sk and sk != m.key and sk.startswith(m.key + " "):   # the span says more than the name
            got = split(book, sk, m.maker)
            if got is not None and book.root(book.by_key(m.key)) == got[0]:
                cands.append((m, sk, m.span.strip(), got[0], got[1], True))
    if not cands:
        return {}
    why = _evidence(cur, [(c[0], c[1], c[4]) for c in cands])
    out: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for m, comp, name, prod, head, by_span in cands:
        k = (m.post_id, m.guide, m.n)
        if k in why:
            out[k] = {"key": comp, "name": name, "product": prod, "why": why[k], "by_span": by_span,
                      "type": m.type, "maker": (m.maker or "").strip() or None, "at": m.at}
    return out


def make(cur: Any, book: I.Book, w: I.Writer, got: Dict[Tuple[str, str, int], Dict[str, Any]],
         *, run_id: Any = None) -> Dict[str, int]:
    """Write what `plan` found: each component's entity (made under its product, or re-parented to it), and the
    span-only mentions sent to it (Book.components)."""
    counts = {"made": 0, "reparented": 0, "mentions": len(got), "by_span": 0}
    comps = book.__dict__.setdefault("components", {})
    by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for k, c in got.items():
        by_key[c["key"]].append(dict(c, mention=k))
    for key in sorted(by_key):
        cs = by_key[key]
        c = cs[0]
        prod = book.root(c["product"])
        eid = book.by_key(key)
        if eid is None:
            first = min((x["at"] for x in cs if x["at"]), default=None)
            eid = w.entity(type_=c["type"], name=c["name"], key=key, level="thing", parent=prod, maker=c["maker"],
                           fields=dict(N.NONE), first_seen=first)
            counts["made"] += 1
        else:
            r = book.root(eid)
            e = book.ents[eid]
            if r == prod:
                continue                                   # merged into the product already: the owner's to undo
            if e.level == "thing" and e.parent != prod and (e.parent is None or not product_like(book, book.root(e.parent))):
                cur.execute("""INSERT INTO mx_entity_fixes (kind, entity_id, field, old, new, evidence, run_id)
                               VALUES ('component', %s, 'parent', %s::jsonb, %s::jsonb, %s::jsonb, %s)""",
                            (eid, json.dumps(e.parent), json.dumps(prod),
                             json.dumps({"product": book.ents[prod].name, "why": sorted({x["why"] for x in cs})}),
                             run_id))
                cur.execute("UPDATE mx_entities SET parent = %s WHERE id = %s", (prod, eid))
                e.parent = prod
                counts["reparented"] += 1
        for x in cs:
            if x["by_span"]:
                comps[x["mention"]] = eid
                counts["by_span"] += 1
    return counts


def components_of(book: I.Book, root: str) -> List[str]:
    """The component roots under a product's cluster: things (not versions) whose parent is in it, the product not
    an org (an org's things are its products, not its components)."""
    if not product_like(book, root):
        return []
    members = set(book.cluster(root))
    out = {book.root(x) for x, e in book.ents.items()
           if e.level == "thing" and e.parent in members and e.status != "not_entity" and book.root(x) != root}
    return sorted(r for r in out if r in book.ents)


def preview(cur: Any, *, limit: Optional[int] = None) -> Dict[str, Any]:
    """The measurement before the switch (0165 Measure): every current mention the rule would give a component, read
    only: {mentions, moved (linked elsewhere now), by_why, by_product: [{product, mentions, components}], sample}."""
    from insight_core.markx import schemas
    book = I.load_book(cur)
    ms = I._mentions(cur, schemas.mention_guides(), unlinked=False, limit=limit)
    got = plan(cur, book, ms)
    by_m = {(m.post_id, m.guide, m.n): m for m in ms}
    by_why: Dict[str, int] = defaultdict(int)
    by_product: Dict[str, Dict[str, Any]] = {}
    moved = 0
    sample = []
    for k, c in sorted(got.items()):
        m = by_m[k]
        now = book.root(m.entity_id) if m.entity_id else None
        target = book.root(book.by_key(c["key"])) if book.by_key(c["key"]) else None
        if now is None or now != target:
            moved += 1
        by_why[c["why"]] += 1
        p = by_product.setdefault(c["product"], {"product": book.label(c["product"]), "mentions": 0, "components": set()})
        p["mentions"] += 1
        p["components"].add(c["name"])
        sample.append({"post": m.post_id, "n": m.n, "span": m.span, "name": m.name, "component": c["name"],
                       "product": book.label(c["product"]), "why": c["why"], "now": book.label(now) if now else None})
    rows = sorted(({**v, "components": sorted(v["components"])} for v in by_product.values()),
                  key=lambda r: -r["mentions"])
    return {"mentions": len(got), "moved": moved, "by_why": dict(by_why), "by_product": rows, "sample": sample}


__all__ = ["components_of", "config", "make", "plan", "preview", "product_like", "split"]
