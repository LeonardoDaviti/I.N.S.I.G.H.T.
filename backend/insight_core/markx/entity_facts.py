"""Identity facts (issue 0184, Stealth v10.18): what an entity is, owned by one module.

An entity's **facts** are its kind, its maker (an entity, and the maker as the posts state it), a one-line `what`, up
to four words that tell it from another thing of the same name (`context`), and whether the name is a common word
(`generic`). A name key may hold several **senses** (one entity each: the key's own entity and the ones a split made,
"Vexa (terminal app)"); each sense's facts row carries the bare key it is a sense of (`sense_key`).

Two entry points, everything else inside:

  - `place(cur, book, mentions, run_id)`: the entities stage, for the mentions it just linked: a bare name's mention
    is placed in one of its senses by rule (1. its stated maker names one sense's maker; 2. its post shares a source
    or a co-named entity with posts already in exactly one sense), a pin by `facts` that the next linking honours;
    otherwise it is marked `wait` and its entity is asked (identity.collisions widens its trigger with `to_ask`).
    The answers are applied by `apply` (called by identity.collisions on a settled answer): facts rows, and when the
    split bar is met, new sense entities with their mentions pinned (entity_answers.split, by `facts`).
  - `read(cur, roots, senses=False)`: every reader: {root: Facts} in one query by id (never the book); `senses`: the
    other senses of the root's name key with their `what` and post counts (search's grouping).

Behind a switch (entity_bands.json `facts`): off, `read` returns nothing, `place` places nothing and the answers are
queued as before (identity's collision items), so a deploy changes no page. Keep everything: a new fact supersedes
the current row, never updates it; an owner's fact is never superseded by a rule or Haiku; a facts pin is undone by
`undone_at`, and an owner's undo of one is final.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N

KINDS = ("person", "org", "model", "product", "software", "dataset", "paper", "event", "place", "project", "law", "other")
PRODUCTS = ("model", "product", "software", "dataset", "project")
WHAT_MAX = 80
_DIGIT = re.compile(r"\d")


def config() -> Dict[str, Any]:
    return I.bands().get("facts") or {}


def on() -> bool:
    return bool(config().get("on"))


@dataclass
class Facts:
    entity_id: str
    kind: Optional[str] = None
    maker_id: Optional[str] = None
    maker: Optional[str] = None          # the maker's shown name (its entity's), else as the posts state it
    what: Optional[str] = None
    context: List[str] = field(default_factory=list)
    generic: bool = False
    by: Optional[str] = None
    sense_key: Optional[str] = None
    senses: List[Dict[str, Any]] = field(default_factory=list)   # the other senses of the name (read(senses=True))

    def view(self) -> Dict[str, Any]:
        return {"kind": self.kind, "maker": {"id": self.maker_id, "name": self.maker} if self.maker else None,
                "what": self.what, "context": self.context, "generic": self.generic, "by": self.by,
                **({"senses": self.senses} if self.senses else {})}


# ---- read: every reader -------------------------------------------------------------------------------

def read(cur: Any, roots: Iterable[Optional[str]], *, senses: bool = False, force: bool = False) -> Dict[str, Facts]:
    """{root: Facts} for the current facts of these entities, one query (an index on entity_id); `senses`: one more
    query for the other senses of their name keys. Off (the switch): nothing, unless `force` (the stage's own use)."""
    ids = sorted({r for r in roots if r})
    if not ids or not (on() or force):
        return {}
    cur.execute("""SELECT f.entity_id::text, f.kind, f.maker_id::text, COALESCE(me.shown_name, me.name, f.maker_name),
                          f.what, f.context, f.generic, f.by, f.sense_key
                     FROM mx_entity_facts f LEFT JOIN mx_entities me ON me.id = f.maker_id
                    WHERE f.superseded_at IS NULL AND f.entity_id = ANY(%s::uuid[])""", (ids,))
    out = {eid: Facts(eid, kind, mid, maker, what, list(ctx or []), bool(gen), by, sk)
           for eid, kind, mid, maker, what, ctx, gen, by, sk in cur.fetchall()}
    if senses and out:
        keys = sorted({f.sense_key for f in out.values() if f.sense_key})
        if keys:
            cur.execute("""SELECT f.sense_key, f.entity_id::text, f.what, f.generic,
                                  (SELECT count(DISTINCT m.post_id) FROM mx_mentions_now m WHERE m.entity_id = f.entity_id)
                             FROM mx_entity_facts f JOIN mx_entities e ON e.id = f.entity_id
                            WHERE f.superseded_at IS NULL AND f.sense_key = ANY(%s) AND e.status <> 'not_entity'""",
                        (keys,))
            by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for key, eid, what, gen, posts in cur.fetchall():
                if not gen:
                    by_key[key].append({"id": eid, "what": what, "posts": int(posts or 0)})
            for f in out.values():
                f.senses = sorted((s for s in by_key.get(f.sense_key or "", []) if s["id"] != f.entity_id),
                                  key=lambda s: (-s["posts"], s["id"]))
    return out


# ---- write: one current row an entity, superseded never updated -----------------------------------------

def write(cur: Any, eid: str, *, by: str, kind: Optional[str] = None, maker_id: Optional[str] = None,
          maker_name: Optional[str] = None, what: Optional[str] = None, context: Sequence[str] = (),
          generic: bool = False, sense_key: Optional[str] = None, guide: Optional[str] = None,
          call_id: Optional[str] = None, confidence: Optional[float] = None, evidence: Optional[Dict[str, Any]] = None,
          run_id: Any = None) -> Optional[str]:
    """The entity's new current facts (the old row superseded), unless they say what the current row says, or the
    current row is the owner's and this one isn't. Fields not given keep the current row's. Returns the new row's id."""
    cur.execute("""SELECT id::text, kind, maker_id::text, maker_name, what, context, generic, by, sense_key
                     FROM mx_entity_facts WHERE entity_id = %s AND superseded_at IS NULL""", (eid,))
    row = cur.fetchone()
    if row and row[7] == "owner" and by != "owner":
        return None
    old = dict(zip(("id", "kind", "maker_id", "maker_name", "what", "context", "generic", "by", "sense_key"), row)) if row else {}
    new = {"kind": kind if kind in KINDS else old.get("kind"),
           "maker_id": maker_id or old.get("maker_id"), "maker_name": maker_name or old.get("maker_name"),
           "what": ((what or "").strip()[:WHAT_MAX] or None) if what is not None else old.get("what"),
           "context": [c for c in (list(context) or list(old.get("context") or [])) if isinstance(c, str)][:4],
           "generic": bool(generic) if what is not None or generic else bool(old.get("generic")),
           "sense_key": sense_key or old.get("sense_key")}
    if old and all(new[k] == old.get(k) for k in new):
        return None
    if old:
        cur.execute("UPDATE mx_entity_facts SET superseded_at = now() WHERE id = %s", (old["id"],))
    cur.execute("""INSERT INTO mx_entity_facts (entity_id, kind, maker_id, maker_name, what, context, generic, by,
                                                guide, call_id, confidence, evidence, run_id, sense_key)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) RETURNING id::text""",
                (eid, new["kind"], new["maker_id"], new["maker_name"], new["what"], new["context"], new["generic"], by,
                 guide, call_id, confidence, json.dumps(evidence or {}, default=str), run_id, new["sense_key"]))
    nid = cur.fetchone()[0]
    if old:
        cur.execute("UPDATE mx_entity_facts SET superseded_by = %s WHERE id = %s", (nid, old["id"]))
    return nid


# ---- bare names and their senses ------------------------------------------------------------------------

def bare(name: Optional[str], maker: Optional[str] = None) -> bool:
    """One word (or one after "the"), no digit, no maker: a name only its posts can tell apart."""
    words = N.key(name or "").split()
    if words[:1] == ["the"]:
        words = words[1:]
    return len(words) == 1 and not _DIGIT.search(words[0]) and not maker


def senses_of(cur: Any, keys: Iterable[str]) -> Dict[str, List[Facts]]:
    """{bare key: its senses' facts} (every current facts row naming the key, the key's own entity included)."""
    ks = sorted(set(keys))
    if not ks:
        return {}
    cur.execute("""SELECT sense_key, entity_id::text, kind, maker_id::text, maker_name, what, context, generic, by
                     FROM mx_entity_facts WHERE superseded_at IS NULL AND sense_key = ANY(%s)""", (ks,))
    out: Dict[str, List[Facts]] = defaultdict(list)
    for key, eid, kind, mid, mname, what, ctx, gen, by in cur.fetchall():
        out[key].append(Facts(eid, kind, mid, mname, what, list(ctx or []), bool(gen), by, key))
    return out


# ---- place: the entities stage's mentions ----------------------------------------------------------------

def place(cur: Any, book: I.Book, mentions: Sequence[Any], *, run_id: Any = None) -> Dict[str, int]:
    """The run's just-linked mentions of bare names with 2+ senses: rule 1 (the stated maker), rule 2 (a shared source
    or co-named entity with exactly one sense's posts), else `wait`. Off: nothing."""
    out: Counter = Counter()
    if not on() or not config().get("place"):
        return {}
    ms = [m for m in mentions if m.entity_id and bare(m.name)]
    keys = {m.key for m in ms}
    sens = {k: v for k, v in senses_of(cur, keys).items() if len([s for s in v if not s.generic]) >= 2}
    ms = [m for m in ms if m.key in sens and not book.pins.get((m.post_id, m.guide, m.n))]
    if not ms:
        return dict(out)
    ctx = _contexts(cur, {s.entity_id for v in sens.values() for s in v}, {m.post_id for m in ms})
    for m in ms:
        options = [s for s in sens[m.key] if not s.generic]
        to, how = None, None
        stated = I.maker_root(book, m.maker) if m.maker else None
        if stated:
            hit = [s for s in options if s.maker_id and book.root(s.maker_id) == stated]
            if len(hit) == 1:
                to, how = hit[0].entity_id, "rule:maker"
        if to is None and config().get("rule_context"):
            # off: a shared source meant the same sense 140/171 (81.9%) on the server's collision names (v10.18)
            src, named = ctx["post"].get(m.post_id, (None, set()))
            hit = [s for s in options if src in ctx["sources"].get(s.entity_id, set())
                   or (named & ctx["named"].get(s.entity_id, set()))]
            if len(hit) == 1:
                to, how = hit[0].entity_id, "rule:context"
        if to is None:
            _mark(cur, m, "wait")
            out["wait"] += 1
            continue
        if book.root(to) != book.root(m.entity_id):
            pin(cur, book, m, to, call_id=None)
        _mark(cur, m, how)
        out[how] += 1
    return dict(out)


def place_by_handle(cur: Any, book: I.Book, mentions: Sequence[Any]) -> Dict[str, int]:
    """0168's learned handles: a bare first name ("Kip") in a post by an account whose handle the owner confirmed as a
    person's ("Kip Marlow" = @kipm) is that person (a facts pin, placed `rule:handle`). Off until measured
    (`rule_handle`)."""
    if not on() or not config().get("rule_handle"):
        return {}
    ms = [m for m in mentions if m.entity_id and bare(m.name) and (m.type or "") in ("person", "other", None)]
    if not ms:
        return {}
    cur.execute("""SELECT DISTINCT ON (r.post_id, r.platform, r.handle) r.post_id::text, h.entity_id::text
                     FROM mx_handle_refs r
                     JOIN LATERAL (SELECT entity_id, answer FROM mx_entity_handles x
                                    WHERE x.platform = r.platform AND x.handle = r.handle
                                    ORDER BY created_at DESC LIMIT 1) h ON h.answer = 'yes'
                    WHERE r.role = 'by' AND r.post_id = ANY(%s::uuid[])""", (sorted({m.post_id for m in ms}),))
    authors: Dict[str, Set[str]] = defaultdict(set)
    for pid, eid in cur.fetchall():
        r = book.root(eid)
        if r in book.ents and I.schemas_type(book.shown_type(r)) == "person":
            authors[pid].add(r)
    out: Counter = Counter()
    for m in ms:
        hit = [r for r in authors.get(m.post_id, ()) if (N.key(book.label(r) or "").split() or [""])[0] == m.key]
        if len(hit) == 1 and book.root(m.entity_id) != hit[0] and not book.pins.get((m.post_id, m.guide, m.n)):
            if pin(cur, book, m, hit[0], call_id=None):
                _mark(cur, m, "rule:handle")
                out["rule:handle"] += 1
    return dict(out)


def _contexts(cur: Any, sense_ids: Set[str], post_ids: Set[str]) -> Dict[str, Any]:
    """The senses' sources and co-named entities (from their posts), and each new post's source and named entities."""
    cur.execute("""SELECT m.entity_id::text, p.source_id::text, o.entity_id::text
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                     LEFT JOIN mx_mentions_now o ON o.post_id = m.post_id AND o.entity_id IS DISTINCT FROM m.entity_id
                    WHERE m.entity_id = ANY(%s::uuid[]) AND m.post_id <> ALL(%s::uuid[])""",
                (sorted(sense_ids), sorted(post_ids)))
    sources: Dict[str, Set[str]] = defaultdict(set)
    named: Dict[str, Set[str]] = defaultdict(set)
    for eid, src, other in cur.fetchall():
        sources[eid].add(src)
        if other:
            named[eid].add(other)
    cur.execute("""SELECT p.id::text, p.source_id::text, array_remove(array_agg(DISTINCT m.entity_id::text), NULL)
                     FROM posts p LEFT JOIN mx_mentions_now m ON m.post_id = p.id
                    WHERE p.id = ANY(%s::uuid[]) GROUP BY 1, 2""", (sorted(post_ids),))
    post = {pid: (src, set(ents or [])) for pid, src, ents in cur.fetchall()}
    return {"sources": sources, "named": named, "post": post}


def _mark(cur: Any, m: Any, how: str) -> None:
    cur.execute("UPDATE mx_mentions SET placed = %s WHERE post_id = %s AND guide = %s AND n = %s",
                (how, m.post_id, m.guide, m.n))


def pin(cur: Any, book: I.Book, m: Any, to: str, *, call_id: Optional[str]) -> bool:
    """A facts pin: the mention goes to `to` (the link it replaced kept in from_entity). Never over an owner's pin,
    and never again where the owner undid a facts pin of this mention (final)."""
    cur.execute("""INSERT INTO mx_entity_pins (post_id, guide, n, entity_id, by, call_id, from_entity)
                   SELECT %s, %s, %s, %s, 'facts', %s, %s WHERE NOT EXISTS (
                     SELECT 1 FROM mx_entity_pins WHERE post_id = %s AND guide = %s AND n = %s
                        AND (undone_at IS NULL OR by = 'facts'))""",
                (m.post_id, m.guide, m.n, to, call_id, m.entity_id, m.post_id, m.guide, m.n))
    if cur.rowcount:
        book.pins[(m.post_id, m.guide, m.n)] = to
        return True
    return False


# ---- the question's side: who is asked, with what, and what an answer does ------------------------------

def to_ask(cur: Any, book: I.Book, seeds: Optional[Set[str]], guide: Sequence[str], limit: int) -> Set[str]:
    """The entities identity.collisions also asks when the switch is on: those holding `wait` mentions, and (the
    backfill) bare names with 2+ posts and no facts yet, oldest first, up to `limit`."""
    if not on() or limit <= 0:
        return set()
    cur.execute("""SELECT DISTINCT entity_id::text FROM mx_mentions
                    WHERE guide = ANY(%s) AND placed = 'wait' AND entity_id IS NOT NULL LIMIT %s""", (list(guide), limit))
    out = {r[0] for r in cur.fetchall()}
    if config().get("backfill") and len(out) < limit:
        cur.execute("""SELECT e.id::text, e.name, e.maker FROM mx_entities e
                        WHERE e.status <> 'not_entity' AND e.level = 'thing' AND e.maker IS NULL
                          AND NOT EXISTS (SELECT 1 FROM mx_entity_facts f WHERE f.entity_id = e.id)
                          AND (SELECT count(DISTINCT m.post_id) FROM mx_mentions_now m WHERE m.entity_id = e.id) >= 2
                        ORDER BY e.first_seen NULLS LAST, e.id LIMIT %s""", (4 * limit,))
        for eid, name, maker in cur.fetchall():
            if len(out) >= limit:
                break
            if bare(name, maker) and book.root(eid) == eid:
                out.add(eid)
    if seeds is not None:
        out = {e for e in out if e in seeds} | (out if config().get("backfill") else set())
    return out


def known_block(cur: Any, eid: str) -> str:
    """The question's known senses ("S1: what | kind | maker"), the entity's name key's senses with facts."""
    cur.execute("SELECT key FROM mx_entities WHERE id = %s", (eid,))
    row = cur.fetchone()
    if not row:
        return ""
    ss = [s for s in senses_of(cur, [row[0]]).get(row[0], []) if s.what and not s.generic]
    if len(ss) < 1:
        return ""
    lines = ["KNOWN SENSES"] + [f"S{k}: {s.what} | kind {s.kind or 'other'} | maker {s.maker or 'none'}"
                                for k, s in enumerate(sorted(ss, key=lambda s: s.entity_id), 1)]
    return "\n".join(lines) + "\n"


def apply(cur: Any, book: I.Book, eid: str, answers: Sequence[Tuple[str, Dict[str, Any]]], text: str, *,
          prop: Optional[Dict[str, Any]], run_id: Any, guide: str) -> Dict[str, int]:
    """A settled answer to an entity's question (identity.collisions): the facts of each sense; a split (two runs
    agreeing, `prop`) made into sense entities when the bar is met (`split`), else returned for the queue."""
    out: Counter = Counter()
    if not answers:
        return dict(out)
    call_id, first = answers[0]
    e = book.ents.get(eid)
    if e is None:
        return dict(out)
    key = e.key
    senses = [s for s in first.get("senses") or [] if s.get("m")]
    if not senses:
        return dict(out)
    groups = sorted(senses, key=lambda s: -len(s.get("m") or []))
    home = groups[0]
    # the entity's own sense: the largest group's facts (generic: the name is a common word there)
    write(cur, eid, by="haiku", kind=home.get("kind"), maker_name=home.get("maker") or None,
          maker_id=I.maker_root(book, home.get("maker")) if home.get("maker") else None,
          what=home.get("what") or "", context=home.get("context") or [], generic=bool(home.get("generic")),
          sense_key=key, guide=guide, call_id=call_id, confidence=first.get("confidence"), run_id=run_id)
    out["facts"] += 1
    # the entity's unplaced mentions were asked: answered (linked by the name as before; a split below pins its own)
    cur.execute("UPDATE mx_mentions SET placed = 'facts' WHERE entity_id = %s AND placed = 'wait'", (eid,))
    if prop is not None and config().get("split"):
        from insight_core.markx import entity_answers
        got = entity_answers.split(cur, book, {"id": None, "a": eid, "evidence": prop}, by="facts", call_id=call_id)
        for new, sense in zip(got["entities"], got.get("senses") or []):
            write(cur, new, by="haiku", kind=sense.get("kind"), maker_name=sense.get("maker") or None,
                  maker_id=I.maker_root(book, sense.get("maker")) if sense.get("maker") else None,
                  what=sense.get("what") or "", context=sense.get("context") or [],
                  generic=bool(sense.get("generic")), sense_key=key, guide=guide, call_id=call_id, run_id=run_id)
            out["senses"] += 1
        out["pinned"] += got["pinned"]
        out["split"] += 1
    elif prop is not None:
        out["queue"] += 1
    return dict(out)


# ---- makers for products (no call) ----------------------------------------------------------------------

def makers(cur: Any, book: I.Book, roots: Iterable[str], guide: Sequence[str], *, run_id: Any = None) -> int:
    """A product's maker from the majority of its mentions' stated makers over all its posts (a maker the post's own
    words name), when the entity was made with none: a facts row `rule:mentions`. mx_entities.maker stays."""
    if not on():
        return 0
    rs = sorted({r for r in roots if r in book.ents and not book.ents[r].maker
                 and I.schemas_type(book.ents[r].type) in PRODUCTS})
    if not rs:
        return 0
    from insight_core.markx import tasks, validate
    cur.execute("""SELECT entity_id::text, post_id::text, maker FROM mx_mentions_now
                    WHERE guide = ANY(%s) AND entity_id = ANY(%s::uuid[]) AND maker IS NOT NULL""", (list(guide), rs))
    rows = cur.fetchall()
    posts = tasks.load_posts(cur, {p for _, p, _ in rows})
    votes: Dict[str, Counter] = defaultdict(Counter)
    for eid, pid, maker in rows:
        p = posts.get(pid)
        if p and validate.occurs(maker, p.title + "\n" + p.text):
            r = I.maker_root(book, maker)
            if r and r != book.root(eid):
                votes[eid][r] += 1
    n = 0
    for eid, c in votes.items():
        (top, k), = c.most_common(1)
        if k >= 1 and (len(c) == 1 or c.most_common(2)[1][1] < k):
            if write(cur, eid, by="rule:mentions", maker_id=top, maker_name=book.label(top),
                     sense_key=book.ents[eid].key if bare(book.ents[eid].name) else None,
                     evidence={"votes": dict(c)}, run_id=run_id):
                n += 1
    return n
