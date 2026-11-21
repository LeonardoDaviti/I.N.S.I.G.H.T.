"""Mark X entity identity repairs (issue 0164): four classes of wrong identity fixed in the data already made, each
run, idempotent and bounded, within the entities stage's budget. Nothing is deleted: a wrong merge is undone (its
redirect closes, undone_by 'repair', the why in its evidence), a merge is a redirect like any other (undoable), a
changed derived field is logged in mx_entity_fixes with its old value. The owner's answers always win: a merge the
owner made or answered `same` is never undone, a pair the owner kept apart or whose merge the owner undid is never
merged, an owner's rename (shown_by 'owner') is never replaced.

  1. `org_family`: a cluster holding both a product family and an org (or person) (identity.Book.sides: "Vela", the
     family of "Vela 5", merged into the org Zentra, perhaps through "Zentra Vela") is cut in two by undoing the
     fewest automatic redirects that separate the sides. A cluster the owner's merge holds together is left as it is
     (counted: `held`). identity.decide_pair now keeps such merges for the queue (org_family), so they don't return.
  2. `reparent`: a version whose family is an org-like cluster ("Zentra 5" by Zentra, whose family key "zentra" is the
     org's alias) gets a family entity of that name under the org (identity.family_under; new mentions get it as they
     are linked). The old parent is logged (mx_entity_fixes kind 'org_family', field 'parent').
  3. `families`: two families whose names differ only by their maker's name or one of its brands in front ("Zentra
     Vela" / "Vela"; a brand: a word in front of BRAND_MIN or more of the maker's family names; a family is a `family`
     entity or a name a version names as its parent) and share the maker merge (rule 'family_prefix'), with evidence:
     a version both state (two prefixes alone, "Brand App" / "Maker App", are not enough), or for a family that
     states no maker, one of its versions already merged with one of the other's. Their versions stating the same
     version, variant, size and build then merge (rule 'family_version', identity.family_version: the version guard
     and the chain guard as for every rule). Two makers stating one family name are never joined.
  4. (dropped in v10.18, 0203) `suffix`, two orgs one once a corporate suffix goes, merged with posts naming one
     beside the other's things: shipped off, it merged none of 11 candidate pairs on the server copy (none had the
     posts), and the bare pairs were one org 8 of 11. The alias questions alone decide such pairs.
  1b. `product_accounts` (0164 B): a name typed an org that is a product account's ("Zentra Vela": its family Vela's
     maker in front of the family's name; identity.Book.product_of) merges into its family (rule 'product_account'),
     never left an org; its shown type is the family's. Step 1 has cut it out of the maker's cluster first (Book.sides
     counts it on the family side).
  4b. `names` (0250): a bare name whose mentions state several makers splits into one thing a maker
     (identity.split_names, the family maker rule deepened; entity_bands.json `families.split`), the new mentions of
     a name split before placed each run; the last step, a step like the others under the stage's budget.
  4c. `reroot` (v10.35): a cluster rooted on a build (identity.is_build: a checkpoint, or a name stating GGUF, NVFP4...)
     that holds a general name re-roots on it, the keeper identity.merge now chooses: merges made before v10.35 kept
     the larger or older side ("Inkling" redirected into "Thinking Machines Inkling", a 975B GGUF checkpoint, so the
     family page was the GGUF's). The redirects from the general name up to the root are undone (undone_by 'repair',
     why 'reroot') and made again by identity.merge with their own by, queue item and call, so the same names stay
     one thing (the owner's merges too: only the keeper changes). The build root's current facts go with the root
     when the new one has none (entity_facts.write, a new row; the old stays); a brief stays under the id it was
     made for (keep everything) and the brief planner, reading roots, briefs the new root; the shown name follows on
     the touched clusters. Skipped: a rename on the path (an older name into the newer, its own direction), an owner's
     shown name on the build root.
  4d. `levels` (v10.35): a checkpoint of a product, dataset or software (a SKU read as a size: "Core Ultra 9 285K",
     "Radeon 780M") is the variant identity.level_of makes it now; only a model's size or build makes a checkpoint.
  5. `shown`: the name and type each cluster is shown under, by evidence (mx_entities.shown_name, shown_type, on the
     root): the member name the most distinct sources write (then posts), counting no span written as a handle nor
     a post by the account it names (an account's display name: "Zentra Devs"); a person by the full name holding
     its one-word name; the type that most (SHOWN_TYPE_SHARE) of its mentions give, or person over org when a
     person's full name is in it and a third of its mentions say person. The touched clusters each run; every
     cluster over the full passes, resumed (`after`). 0168 D: a cluster shown under one of its confirmed handles
     ("ikestrel") is shown by the display name the handle's "Name (@handle)" pairs gave (markx/handles.learned_names).

Config: entity_bands.json `repairs` (each on or off, and their bars).
"""
from __future__ import annotations

import itertools
import json
import logging
import time
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from insight_core.markx import identity as I
from insight_core.markx import names as N

log = logging.getLogger(__name__)

UNDO_LIMIT = 200          # redirects a run undoes (org_family)
PRODUCT_LIMIT = 500       # product accounts a run merges into their family (product_accounts)
REPARENT_LIMIT = 2000     # versions a run gives a family
FAMILY_LIMIT = 300        # family merges a run (and as many version merges)
RELEVEL_LIMIT = 2000      # v10.35: checkpoints a run makes the variants identity.level_of says (relevel)
REROOT_LIMIT = 200        # clusters a run re-roots on their general name (reroot)
SHOWN_CHUNK = 2000        # clusters whose shown name one query reads
SHOWN_SINGLES = 20000     # v10.23 (0218): a sweep's step: SHOWN_CHUNK clusters of several names, or this many of one
BRAND_MIN = 3
SHOWN_TYPE_SHARE = 0.75
SHOWN_TYPE_MIN = 5


def config() -> Dict[str, Any]:
    got = I.bands().get("repairs") or {}
    return {"org_family": got.get("org_family", True), "product_accounts": got.get("product_accounts", True),
            "reparent": got.get("reparent", True),
            "families": got.get("families", True), "shown": got.get("shown", True),
            "family_home": got.get("family_home", True), "names": got.get("names", True),
            "reroot": got.get("reroot", True), "levels": got.get("levels", True)}


def _owner_same(cur: Any) -> Set[Tuple[str, str]]:
    """The pairs the owner answered `same` (their merge is the owner's even when a rule made it first)."""
    cur.execute("SELECT least(a, b)::text, greatest(a, b)::text FROM mx_entity_queue WHERE kind = 'alias' AND answer = 'same'")
    return {(a, b) for a, b in cur.fetchall()}


def _never_between(book: I.Book, xs: Iterable[str], ys: Iterable[str]) -> bool:
    ys = list(ys)
    return any(I.pair(x, y) in book.never for x in xs for y in ys)


# ---- 1. a family merged into an org --------------------------------------------------------------------------

def _cuts(members: List[str], edges: List[Tuple[str, str, bool]], fam: Set[str], org: Set[str]) -> Optional[List[int]]:
    """The edges (indexes) to remove so no part holds both a family and an org, the fewest found greedily (each step
    the edge separating the most family-org pairs, a family-org edge first); None when only the owner's edges would
    (edges: (from, to, owner's))."""
    removed: Set[int] = set()

    def parts() -> List[Set[str]]:
        adj: Dict[str, Set[str]] = defaultdict(set)
        for k, (a, b, _) in enumerate(edges):
            if k not in removed:
                adj[a].add(b)
                adj[b].add(a)
        seen: Set[str] = set()
        out = []
        for m in members:
            if m in seen:
                continue
            comp, todo = set(), [m]
            while todo:
                x = todo.pop()
                if x in comp:
                    continue
                comp.add(x)
                todo.extend(adj[x] - comp)
            seen |= comp
            out.append(comp)
        return out

    for _ in range(len(edges)):
        mixed = [c for c in parts() if c & fam and c & org]
        if not mixed:
            return sorted(removed)
        best, best_score = None, (0, 0)
        for k, (a, b, owner) in enumerate(edges):
            if k in removed or owner:
                continue
            comp = next((c for c in mixed if a in c), None)
            if comp is None:
                continue
            removed.add(k)
            side = next(c for c in parts() if a in c)
            removed.discard(k)
            other = comp - side
            score = len(side & fam) * len(other & org) + len(side & org) * len(other & fam)
            cross = int((a in fam and b in org) or (a in org and b in fam))
            if score and (score, cross) > best_score:
                best, best_score = k, (score, cross)
        if best is None:
            return None
        removed.add(best)
    return None


def _components(members: List[str], edges: Iterable[Tuple[str, str]]) -> Dict[str, int]:
    adj: Dict[str, Set[str]] = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    out: Dict[str, int] = {}
    for n, m in enumerate(members):
        if m in out:
            continue
        todo = [m]
        while todo:
            x = todo.pop()
            if x not in out:
                out[x] = n
                todo.extend(adj[x])
    return out


def undo_org_family(cur: Any, book: I.Book, *, run_id: Any, limit: int = UNDO_LIMIT) -> Dict[str, int]:
    """Each merge is an edge between the two names it joined: a rule's or Haiku's between the two roots it redirected,
    the owner's between the two names the owner answered (its queue item; the redirect itself goes root to root). The
    edges cut are undone; an owner's redirect that crossed the cut only because it went root to root is re-pointed:
    undone and made again between the owner's two names (by 'owner', its queue item, `repointed_from`), so the owner's
    answer holds exactly."""
    out = Counter({"clusters": 0, "undone": 0, "repointed": 0, "held": 0})
    rows = redirect_rows(cur)
    owner = _owner_same(cur)
    clusters = book.clusters()
    book.prime_sides(m for ms in clusters.values() for m in ms)   # v10.24 (0221): in one go, not a cluster at a time
    for root, ms in sorted(clusters.items()):   # v10.22 (0216): a cluster of one has no side to cut
        if len(ms) < 2 or out["undone"] >= limit:
            continue
        fam, org = book.sides(ms)
        if not fam or not org:
            continue
        out["clusters"] += 1
        members = sorted(ms)
        edges = cluster_edges(book, members, rows, owner)
        cuts = _cuts(members, [(x, y, o) for x, y, o, _ in edges], fam, org)
        if cuts is None:
            out["held"] += 1
            continue
        why = {"why": "org_family", "run": str(run_id) if run_id else None,
               "family": sorted(book.ents[x].name for x in fam), "org": sorted(book.ents[x].name for x in org)}
        undone, repointed = apply_cuts(cur, book, members, edges, cuts, rows, why=why, undone_by="repair",
                                       run_id=run_id)
        out["undone"] += len(undone)
        out["repointed"] += repointed
    return dict(out)


def redirect_rows(cur: Any) -> Dict[str, Tuple[str, str, str, Optional[str], Optional[str], Optional[str]]]:
    """{from: (redirect id, to, by, its queue item, the item's a, b)} of the current redirects."""
    cur.execute("""SELECT r.from_id::text, r.id::text, r.to_id::text, r.by, q.id::text, q.a::text, q.b::text
                     FROM mx_entity_redirects r LEFT JOIN mx_entity_queue q ON q.id = r.queue_id
                    WHERE r.undone_at IS NULL""")
    return {f: (rid, t, by, qid, qa, qb) for f, rid, t, by, qid, qa, qb in cur.fetchall()}


def cluster_edges(book: I.Book, members: List[str], rows: Dict[str, Tuple], owner: Set[Tuple[str, str]]
                  ) -> List[Tuple[str, str, bool, str]]:
    """A cluster's merges as edges (one name, the other, the owner's, its redirect's from): a rule's or Haiku's
    between the two roots it redirected, the owner's between the two names the owner answered."""
    ms = set(members)
    edges = []
    for f in members:
        if f not in book.redirect or f not in rows:
            continue
        rid, to, by, qid, qa, qb = rows[f]
        mine = by == "owner"
        x, y = (qa, qb) if mine and qa in ms and qb in ms else (f, to)
        edges.append((x, y, mine or I.pair(f, to) in owner, f))
    return edges


def apply_cuts(cur: Any, book: I.Book, members: List[str], edges: List[Tuple[str, str, bool, str]], cuts: List[int],
               rows: Dict[str, Tuple], *, why: Dict[str, Any], undone_by: str, run_id: Any = None
               ) -> Tuple[List[str], int]:
    """The cut edges' redirects undone (`undone_by`, the why in evidence.undone); an owner's redirect crossing the cut
    only because it went root to root is re-pointed (undone, made again between the owner's two names). (The
    redirects undone by the cut, how many re-pointed.)"""
    comp = _components(members, [(x, y) for k, (x, y, _, _) in enumerate(edges) if k not in cuts])
    undone: List[str] = []
    again = []
    for k, (x, y, mine, f) in enumerate(edges):
        rid, to = rows[f][0], rows[f][1]
        if comp.get(f) == comp.get(to):
            continue                     # this redirect stays inside one side
        note = dict(why, repoint=k not in cuts)
        cur.execute("""UPDATE mx_entity_redirects SET undone_at = now(), undone_by = %s,
                              evidence = COALESCE(evidence, '{}'::jsonb) || jsonb_build_object('undone', %s::jsonb)
                        WHERE id = %s AND undone_at IS NULL""", (undone_by, json.dumps(note, default=str), rid))
        if cur.rowcount:
            book.redirect.pop(f, None)
            if k in cuts:
                undone.append(rid)
            else:
                again.append((x, y, rid, rows[f][3]))
    repointed = 0
    for x, y, rid, qid in again:         # the owner's answers, made again between the owner's two names
        if I.merge(cur, book, x, y, by="owner", automatic=False, queue_id=qid, run_id=run_id,
                   evidence={"queue": qid, "repointed_from": rid, "why": why.get("why")}):
            repointed += 1
    return undone, repointed


# ---- 1b. a product account made an org ---------------------------------------------------------------------------

PAGE = 2000   # v10.23 (0218): the entities a walk reads ahead for at once


def _org_names(book: I.Book) -> Iterable[I.Ent]:
    """v10.23 (0218): the names of two words or more typed an org (as their mentions say), not versions, by id: read
    row by row, a page at a time (a book read by need is asked the rest of a page in one go: the mention types, then
    the names their words could be), none held past its page."""
    page: List[I.Ent] = []

    def ready(page: List[I.Ent]) -> List[I.Ent]:
        types = book.etypes(page)
        got = [e for e in page if types.get(e.id) == "org"]
        book.prime_names(e.key for e in got)   # v10.24 (0221): and what product_of asks of them, in one go
        return got
    from insight_core.markx import schemas
    org = schemas.stored_types(["org"])
    # v10.23 (0218): a book read by need narrows its read to the names some mention types an org (or, none counted,
    # typed an org themselves): the walk read every name of two words (~220k rows of the server-sized copy's 330k,
    # 5 s of the stage's budget) for the ~37k its test keeps
    for e in book.walk("""position(' ' in e.key) > 0 AND e.status <> 'not_entity' AND e.level <> ALL(%s)
                          AND e.id IN (SELECT t.id FROM pg_temp.mx_run_types t WHERE t.type = ANY(%s)
                                       UNION ALL SELECT x.id FROM mx_entities x WHERE x.type = ANY(%s) AND NOT EXISTS
                                                 (SELECT 1 FROM pg_temp.mx_run_types t WHERE t.id = x.id))""",
                       (list(I.VERSION_LEVELS), org, org), by_id=True):
        if " " not in e.key or e.status == "not_entity" or e.level in I.VERSION_LEVELS:
            continue
        page.append(e)
        if len(page) >= PAGE:
            yield from ready(page)
            page = []
    yield from ready(page)


def product_accounts(cur: Any, book: I.Book, *, run_id: Any, limit: int = PRODUCT_LIMIT) -> Dict[str, int]:
    """0164 B on the data already made: an entity typed an org whose name is a product account's (Book.product_of:
    "Zentra Vela", the family Vela's maker in front of it) merges into its family (rule 'product_account'), when
    neither cluster holds an org (step 1 cut the automatic links to one; an owner's link is left, `held`) and the
    owner never kept them apart. Its shown type is the family's (`shown`). Idempotent: once one cluster, skipped."""
    out = Counter({"accounts": 0, "merged": 0, "held": 0})
    # v10.23 (0218): the names of two words or more, not versions, read row by row (a book read by need is asked the
    # rest in one go: their mention types, then the names their words could be)
    for e in _org_names(book):
        if out["merged"] >= limit:
            break
        fam = book.product_of(e.key)
        if fam is None:
            continue
        out["accounts"] += 1
        ra, rf = book.root(e.id), book.root(fam)
        if ra == rf:
            continue
        ca, cf = book.cluster(ra), book.cluster(rf)
        if book.sides(ca)[1] or book.sides(cf)[1] or _never_between(book, ca, cf):
            out["held"] += 1
            continue
        if I.merge(cur, book, ra, rf, by="rule:product_account", automatic=True, run_id=run_id,
                   evidence={"rules": ["product_account"], "confidence": I.RULE_CONF, "family": book.ents[fam].name,
                             "repair": True}):
            out["merged"] += 1
    return dict(out)


# ---- the invariant -------------------------------------------------------------------------------------------------

def family_org(book: I.Book, cur: Any = None, show: int = 10) -> Dict[str, Any]:
    """0164 C: the clusters holding both a product family and an org or person (Book.sides): 0 once the repair has
    run, but for the clusters the owner's own merge holds (`held`, when `cur` is given). Up to `show` listed by
    name."""
    mixed = []
    clusters = book.clusters()
    book.prime_sides(m for ms in clusters.values() for m in ms)   # v10.24 (0221): in one go (none if read already)
    for root, ms in clusters.items():   # v10.22 (0216): a cluster of one holds no family and org
        if len(ms) < 2 or root not in book.ents:
            continue
        fam, org = book.sides(ms)
        if fam and org:
            mixed.append((root, fam, org))
    held = 0
    if cur is not None and mixed:
        rows = redirect_rows(cur)
        owner = _owner_same(cur)
        for root, fam, org in mixed:
            members = sorted(book.cluster(root))
            if _cuts(members, [(x, y, o) for x, y, o, _ in cluster_edges(book, members, rows, owner)], fam, org) is None:
                held += 1
    mixed.sort(key=lambda t: (-len(t[1]) - len(t[2]), t[0]))
    return {"count": len(mixed), "held": held,
            "clusters": [{"id": r, "name": book.label(r), "family": sorted(book.ents[x].name for x in fam)[:8],
                          "org": sorted(book.ents[x].name for x in org)[:8]} for r, fam, org in mixed[:show]]}


# ---- 2. a version whose family is an org --------------------------------------------------------------------

def reparent(cur: Any, book: I.Book, w: I.Writer, *, run_id: Any, limit: int = REPARENT_LIMIT) -> Dict[str, int]:
    out = Counter({"versions": 0, "families_made": 0})
    orgish: Dict[str, bool] = {}
    groups: Dict[Tuple[str, str], List[I.Ent]] = defaultdict(list)
    versions = _versions(book)
    book.prime(ids={e.parent for e in versions})
    parents = {book.root(e.parent) for e in versions}
    book.prime_clusters(parents)
    book.prime_sides(m for r in parents if r for m in book.cluster(r))   # v10.24 (0221): org_like's, in one go
    for e in versions:
        r = book.root(e.parent)
        if r not in book.ents:
            continue
        if r not in orgish:
            orgish[r] = book.org_like(r)
        if not orgish[r]:
            continue
        fk = e.family_key or e.pk[0] or book.ents[e.parent].key
        if fk:
            groups[(r, fk)].append(e)
    made_before = len(w.made)
    for (r, fk), vs in sorted(groups.items()):
        if out["versions"] >= limit:
            break
        first = min((v.first_seen for v in vs if v.first_seen), default=None)
        fam = I.family_under(w, r, fk, vs[0].type, vs[0].maker, first, (vs[0].haiku.get("family") or "").strip())
        for v in vs:
            if v.parent == fam:
                continue
            cur.execute("UPDATE mx_entities SET parent = %s WHERE id = %s", (fam, v.id))
            cur.execute("""INSERT INTO mx_entity_fixes (kind, entity_id, field, old, new, evidence, run_id)
                           VALUES ('org_family', %s, 'parent', %s::jsonb, %s::jsonb, %s::jsonb, %s)""",
                        (v.id, json.dumps(v.parent), json.dumps(fam),
                         json.dumps({"org": r, "family_key": fk, "org_name": book.ents[r].name}), run_id))
            v.parent = fam
            book.version_parents().add(fam)
            book.kids()[fam].append(v.id)
            out["versions"] += 1
    out["families_made"] = len(w.made) - made_before
    return dict(out)


# ---- 2b. a version's family: its stem and its maker's (0230: identity's rule, for the versions made before it) -----

def family_home(cur: Any, book: I.Book, w: I.Writer, *, run_id: Any, limit: int = REPARENT_LIMIT) -> Dict[str, int]:
    """0230: the versions linked before identity's family rule (identity.family_stem, other_maker): one whose parent is
    a version of a family (a member's name taken as a family's) gets that family (mx_entity_fixes kind 'family_stem');
    another maker's thing under a family (its stated maker none of the family's) becomes a thing of its own maker,
    `based_on` the family (kind 'family_maker', the old level and parent kept). An org-like parent is reparent's.
    Idempotent; `limit` changes a run."""
    out = Counter({"stem": 0, "other_maker": 0, "edges": 0})
    on = I.families_on()
    if not (on["maker"] or on["stem"]):
        return {**out, "off": True}
    versions = _versions(book)
    book.prime(ids={e.parent for e in versions})
    parents = {book.root(e.parent) for e in versions}
    book.prime_clusters(parents)
    book.prime_sides(m for r in parents if r for m in book.cluster(r))
    orgish: Dict[str, bool] = {}
    for e in versions:
        if out["stem"] + out["other_maker"] >= limit:
            break
        p = book.root(e.parent)
        if p not in book.ents:
            continue
        fam = I.family_stem(book, p)
        if fam not in orgish:
            orgish[fam] = book.org_like(fam)
        if orgish[fam]:
            continue
        old = {"level": e.level, "parent": e.parent}
        if I.other_maker(book, fam, e.maker):
            up = I._maker_entity(w, e.maker, e.first_seen) if N.key(e.maker) != e.key else None
            cur.execute("UPDATE mx_entities SET level = 'thing', parent = %s WHERE id = %s", (up, e.id))
            makers = I.family_makers(book, fam)
            cur.execute("""INSERT INTO mx_entity_fixes (kind, entity_id, field, old, new, evidence, run_id)
                           VALUES ('family_maker', %s, 'parent', %s::jsonb, %s::jsonb, %s::jsonb, %s)""",
                        (e.id, json.dumps(old), json.dumps({"level": "thing", "parent": up}),
                         json.dumps({"family": fam, "family_name": book.label(fam), "maker": e.maker,
                                     "family_makers": makers}), run_id))
            out["edges"] += I.based_on_family(cur, e.id, fam, maker=e.maker, makers=makers, run_id=run_id)
            kids = book.kids().get(e.parent)
            if kids and e.id in kids:
                kids.remove(e.id)
            e.level, e.parent = "thing", up
            out["other_maker"] += 1
        elif fam != p:
            cur.execute("UPDATE mx_entities SET parent = %s WHERE id = %s", (fam, e.id))
            cur.execute("""INSERT INTO mx_entity_fixes (kind, entity_id, field, old, new, evidence, run_id)
                           VALUES ('family_stem', %s, 'parent', %s::jsonb, %s::jsonb, %s::jsonb, %s)""",
                        (e.id, json.dumps(old["parent"]), json.dumps(fam),
                         json.dumps({"was": book.label(p), "family": book.label(fam)}), run_id))
            e.parent = fam
            book.version_parents().add(fam)
            book.kids()[fam].append(e.id)
            out["stem"] += 1
    return dict(out)


# ---- 3. families split by a maker or brand prefix -------------------------------------------------------------

def _versions(book: I.Book) -> List[I.Ent]:
    """v10.23 (0218): the versions, variants and checkpoints naming a parent, not `not_entity`, in id order (read row
    by row from a book read by need)."""
    return [e for e in book.walk("e.level = ANY(%s) AND e.parent IS NOT NULL AND e.status <> 'not_entity'",
                                 (list(I.VERSION_LEVELS),), by_id=True)
            if e.level in I.VERSION_LEVELS and e.parent and e.status != "not_entity"]


def _families(book: I.Book) -> List[I.Ent]:
    """v10.23 (0218): the families (a `family` entity, or a name a version names as its parent, as the book's version
    parents say), not `not_entity`, of no org or person type, in the book's order. A book read by need narrows its
    read to the families and the parents of versions, then and now."""
    lv = list(I.VERSION_LEVELS)
    got = [e for e in book.walk("""e.status <> 'not_entity' AND (e.level = 'family'
                                     OR e.id IN (SELECT v.parent FROM mx_entities v
                                                  WHERE v.level = ANY(%s) AND v.parent IS NOT NULL)
                                     OR e.id IN (SELECT v.parent FROM pg_temp.mx_run_versions v))""", (lv,))
           if e.status != "not_entity"]
    vp = book.version_parents()
    for want in (getattr(vp, "want", None), getattr(book.types, "want", None)):
        if want is not None:
            want([e.id for e in got])
    return [e for e in got if (e.level == "family" or e.id in vp) and book.etype(e.id) not in I.ORGISH]


def _family_roots(book: I.Book) -> Dict[str, List[str]]:
    """{root: its names} of the clusters holding a family (a `family` entity, or a name a version names as its parent:
    a family first written bare is a `thing`) and no org: every member but its versions."""
    roots: Set[str] = set()
    for e in _families(book):
        roots.add(book.root(e.id))
    book.prime_clusters(roots)
    book.prime_sides(m for r in roots if r for m in book.cluster(r))   # v10.24 (0221): sides', in one go
    out: Dict[str, List[str]] = {}
    for r in roots:
        ms = book.cluster(r)
        if r in book.ents and not book.sides(ms)[1]:
            out[r] = sorted(m for m in ms if book.ents[m].level not in I.VERSION_LEVELS
                            and book.ents[m].status != "not_entity")
    return out


def _maker_of(book: I.Book, fams: Iterable[str]) -> Tuple[Optional[str], bool]:
    """(the maker cluster a family's members state, conflicting): its parent's cluster or its stated maker's."""
    got = set()
    for f in fams:
        e = book.ents[f]
        r = book.root(e.parent) if e.parent else None
        if r is None and e.maker:
            r = I.maker_root(book, e.maker)
        if r is not None:
            got.add(r)
    return (next(iter(got)) if len(got) == 1 else None), len(got) > 1


def _children(book: I.Book) -> Tuple[Dict[str, Set[str]], Dict[str, Set[Tuple]]]:
    """({family root: the clusters of its versions}, {family root: the versions they state})."""
    kids: Dict[str, Set[str]] = defaultdict(set)
    sigs: Dict[str, Set[Tuple]] = defaultdict(set)
    for e in _versions(book):
        if e.level in I.VERSION_LEVELS and e.parent and e.status != "not_entity":
            r = book.root(e.parent)
            kids[r].add(book.root(e.id))
            sig = I._vsig(e)
            if any(x is not None for x in sig):
                sigs[r].add(sig)
    return kids, sigs


def merge_families(cur: Any, book: I.Book, *, run_id: Any, limit: int = FAMILY_LIMIT) -> Dict[str, int]:
    out = Counter({"families": 0, "versions": 0, "unproven": 0, "two_makers": 0})
    roots = _family_roots(book)
    makers: Dict[str, Optional[str]] = {}
    for r, fs in roots.items():
        m, conflict = _maker_of(book, fs)
        makers[r] = None if conflict else m
    # the makers' names, and their brands: a word in front of BRAND_MIN or more of a maker's family names
    owner_of: Dict[str, Set[str]] = defaultdict(set)
    for m in {m for m in makers.values() if m}:
        for x in book.cluster(m):
            owner_of[book.ents[x].key].add(m)
    firsts: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    for r, fs in roots.items():
        if makers[r]:
            for f in fs:
                words = book.ents[f].key.split()
                if len(words) >= 2:
                    firsts[makers[r]][words[0]].add(book.ents[f].key)
    for m, ws in firsts.items():
        for wd, keys in ws.items():
            if len(keys) >= BRAND_MIN and wd not in owner_of:
                owner_of[wd].add(m)
    prefix_owner = {k: next(iter(ms)) for k, ms in owner_of.items() if len(ms) == 1}
    groups: Dict[str, List[Tuple[str, Optional[str], bool]]] = defaultdict(list)
    for r, fs in roots.items():
        for f in fs:
            words = book.ents[f].key.split()
            groups[N.squash(" ".join(words))].append((r, makers[r], False))
            for i in range(1, len(words)):
                m = prefix_owner.get(" ".join(words[:i]))
                if m and makers[r] in (None, m):
                    groups[N.squash(" ".join(words[i:]))].append((r, m, True))
    kids, sigs = _children(book)
    for sq, entries in sorted(groups.items()):
        if out["families"] >= limit:
            break
        if not any(pref for _, _, pref in entries):
            continue
        ms = {m for _, m, _ in entries if m}
        if len(ms) != 1:
            out["two_makers"] += int(len(ms) > 1)
            continue
        m = next(iter(ms))
        known = {book.root(r) for r, mk, _ in entries if mk == m}
        bare = {book.root(r) for r, mk, _ in entries if mk is None} - known
        # the evidence they are one family: a version of each already one (a merge), or, the maker the same, a
        # version both state; a family stating no maker joins only by the first
        order = sorted(known | bare, key=lambda r: (r in bare, -book.cluster_size(r), r))
        head = order[0]
        group_kids, group_sigs = set(kids.get(head, ())), set(sigs.get(head, ()))
        for r in order[1:]:
            ha, hb = book.root(head), book.root(r)
            if ha == hb:
                continue
            if not (kids.get(r, set()) & group_kids or (r in known and sigs.get(r, set()) & group_sigs)):
                out["unproven"] += 1
                continue
            if _never_between(book, book.cluster(ha), book.cluster(hb)):
                continue
            if not I.types_ok(book.etype(ha), book.etype(hb)) or I.org_family(book, ha, hb):
                continue
            if book.cluster_size(ha) + book.cluster_size(hb) > I.MAX_CLUSTER:
                continue
            if I.merge(cur, book, ha, hb, by="rule:family_prefix", automatic=True, run_id=run_id,
                       evidence={"rules": ["family_prefix"], "confidence": I.RULE_CONF, "family": sq,
                                 "maker": book.ents[m].name}):
                out["families"] += 1
                group_kids |= kids.get(r, set())
                group_sigs |= sigs.get(r, set())
    out["versions"] = merge_versions(cur, book, run_id=run_id, limit=limit)
    return dict(out)


def merge_versions(cur: Any, book: I.Book, *, run_id: Any, limit: int = FAMILY_LIMIT) -> int:
    """The versions of one family cluster that holds two or more families (merged by name or by this repair) stating
    one version, variant, size and build: merged by the rule 'family_version' through decide_pair and the chain
    guard (every guard of a rule's merge)."""
    fam_keys: Dict[str, Set[str]] = defaultdict(set)
    for e in _families(book):
        fam_keys[book.root(e.id)].add(e.key)
    multi = {r for r, ks in fam_keys.items() if len(ks) >= 2}
    by: Dict[Tuple[str, Tuple], Dict[str, str]] = defaultdict(dict)
    for e in _versions(book):
        r = book.root(e.parent)
        sig = I._vsig(e)
        if r in multi and any(x is not None for x in sig):
            by[(r, sig)].setdefault(book.root(e.id), e.id)
    decisions: List[I.Decision] = []
    for _, reps in sorted(by.items(), key=lambda kv: str(kv[0])):
        for (ra, a), (rb, b) in itertools.combinations(sorted(reps.items()), 2):
            if _never_between(book, book.cluster(ra), book.cluster(rb)):
                continue
            if not I.family_version(book, book.ents[a], book.ents[b]):
                continue
            p = I.Pooled(*I.pair(a, b))
            decisions.append(I.decide_pair(book, p, {"family_version"}, set(), None, None))
    I.chain_guard(book, decisions)
    n = 0
    for d in decisions:
        if d.tier != "auto" or n >= limit:
            continue
        if I.merge(cur, book, d.pair[0], d.pair[1], by="rule:family_version", automatic=True, run_id=run_id,
                   evidence={"rules": ["family_version"], "confidence": d.conf}):
            n += 1
    return n


# ---- 4d. a product's SKU is no checkpoint -----------------------------------------------------------------------

def relevel(cur: Any, book: I.Book, *, limit: int = RELEVEL_LIMIT) -> int:
    """v10.35: a checkpoint of a type no size or build makes one of (identity.level_of: a product's, a dataset's,
    software's "285K", "780M", "10k"), made before v10.35, is the variant identity.level_of makes it now (in id
    order; idempotent: none is left once done). Its fields stay as stated. Before `reroot`, which reads a checkpoint
    as a build."""
    n = 0
    for e in book.walk("e.level = %s", ("checkpoint",), by_id=True):
        if n >= limit:
            break
        to = I.level_of(e.type, e.hk, e.pk) if e.level == "checkpoint" else "checkpoint"
        if to == "checkpoint":
            continue
        cur.execute("UPDATE mx_entities SET level = %s WHERE id = %s AND level = 'checkpoint'", (to, e.id))
        e.level = to
        n += 1
    return n


# ---- 4c. a cluster rooted on a build ---------------------------------------------------------------------------

def reroot_plan(cur: Any, book: I.Book) -> List[Dict[str, Any]]:
    """v10.35: the clusters rooted on a build that hold a general name, each {root, keeper, path (the redirects from
    the keeper up to the root, keeper first), skip (None, or why not)}. Reads only. The keeper is identity.merge's:
    of the general names, the one heading the most names (the cluster it brought), then the older; the names on
    its path up are all builds."""
    out: List[Dict[str, Any]] = []
    plans = []
    for root, ms in sorted(book.clusters().items()):
        e = book.ents.get(root)
        if e is None or not I.is_build(e):
            continue
        general = [m for m in ms if m in book.ents and not I.is_build(book.ents[m])]
        if not general:
            continue
        into: Dict[str, List[str]] = defaultdict(list)
        for m in ms:
            if m != root and m in book.redirect:
                into[book.redirect[m][0]].append(m)

        def under(x: str) -> int:
            n, todo, seen = 0, [x], set()
            while todo:
                y = todo.pop()
                if y not in seen:
                    seen.add(y)
                    n += 1
                    todo.extend(into.get(y, ()))
            return n

        def weight(m: str):
            f = book.ents[m].first_seen
            return (under(m), -(f.timestamp() if f else 0), m)
        keeper = max(general, key=weight)
        path, x = [], keeper
        while x != root and x in book.redirect:
            path.append(x)
            x = book.redirect[x][0]
        plans.append({"root": root, "keeper": keeper, "path": path, "skip": None})
    if not plans:
        return out
    cur.execute("""SELECT from_id::text, id::text, kind FROM mx_entity_redirects
                    WHERE undone_at IS NULL AND from_id = ANY(%s::uuid[])""",
                ([f for p in plans for f in p["path"]],))
    kinds = {f: (rid, kind) for f, rid, kind in cur.fetchall()}
    cur.execute("SELECT id::text FROM mx_entities WHERE id = ANY(%s::uuid[]) AND shown_by = 'owner'",
                ([p["root"] for p in plans],))
    renamed = {r for (r,) in cur.fetchall()}
    for p in plans:
        if any(f not in kinds for f in p["path"]):
            p["skip"] = "stale"            # the book's redirects are not the table's (another writer)
        elif any(kinds[f][1] == "rename" for f in p["path"]):
            p["skip"] = "rename"
        elif p["root"] in renamed:
            p["skip"] = "owner_shown"
        p["redirects"] = [kinds[f][0] for f in p["path"] if f in kinds]
        out.append(p)
    return out


def reroot_builds(cur: Any, book: I.Book, *, run_id: Any, limit: int = REROOT_LIMIT) -> Dict[str, int]:
    """v10.35: each cluster of reroot_plan not skipped re-roots on its keeper: the redirects of its path undone and
    made again by identity.merge (its keeper rule puts the general name on top) with their own by, automatic, call
    and queue item (evidence: theirs, and `rerooted_from`). The old root's current facts are written to the new
    root when it has none."""
    from insight_core.markx import entity_facts
    out = Counter({"clusters": 0, "rerooted": 0, "redirects": 0, "facts": 0, "skipped": 0})
    for p in reroot_plan(cur, book):
        out["clusters"] += 1
        if p["skip"] or out["rerooted"] >= limit:
            out["skipped"] += 1
            if p["skip"]:
                out["skip_" + p["skip"]] += 1
            continue
        cur.execute("""SELECT id::text, from_id::text, to_id::text, by, automatic, call_id::text, queue_id::text, evidence
                         FROM mx_entity_redirects WHERE id = ANY(%s::uuid[]) AND undone_at IS NULL""", (p["redirects"],))
        rows = {r[1]: r for r in cur.fetchall()}
        if set(rows) != set(p["path"]):
            out["skipped"] += 1
            out["skip_stale"] += 1
            continue
        why = {"why": "reroot", "run": str(run_id) if run_id else None, "root": p["root"], "keeper": p["keeper"]}
        before = {f: book.redirect[f] for f in p["path"]}
        cur.execute("SAVEPOINT entity_reroot")
        made = 0
        for f in p["path"]:
            cur.execute("""UPDATE mx_entity_redirects SET undone_at = now(), undone_by = 'repair',
                                  evidence = COALESCE(evidence, '{}'::jsonb) || jsonb_build_object('undone', %s::jsonb)
                            WHERE id = %s AND undone_at IS NULL""", (json.dumps(why, default=str), rows[f][0]))
            book.redirect.pop(f, None)
        for f in p["path"]:
            rid, _f, to, by, auto, call, queue, ev = rows[f]
            made += int(bool(I.merge(cur, book, f, to, by=by, automatic=auto, call_id=call, queue_id=queue,
                                     run_id=run_id, evidence={**(ev or {}), "rerooted_from": rid, "why": "reroot"})))
        new = book.root(p["root"])
        if made != len(p["path"]) or new != book.root(p["keeper"]) or I.is_build(book.ents[new]):
            cur.execute("ROLLBACK TO SAVEPOINT entity_reroot")   # one thing still, on its old root (a raced write)
            for f in set(p["path"]) | {p["root"]}:
                book.redirect.pop(f, None)
            for f, got in before.items():
                book.redirect[f] = got
            out["skipped"] += 1
            out["skip_failed"] += 1
            continue
        cur.execute("RELEASE SAVEPOINT entity_reroot")
        out["redirects"] += made
        out["rerooted"] += 1
        cur.execute("""SELECT entity_id::text, kind, maker_id::text, maker_name, what, context, generic, by, sense_key
                         FROM mx_entity_facts WHERE entity_id = ANY(%s::uuid[]) AND superseded_at IS NULL""",
                    ([p["root"], new],))
        facts = {r[0]: r for r in cur.fetchall()}
        if p["root"] in facts and new not in facts:
            _e, kind, maker_id, maker_name, what, context, generic, by, sense_key = facts[p["root"]]
            if entity_facts.write(cur, new, by=by, kind=kind, maker_id=maker_id, maker_name=maker_name, what=what,
                                  context=context or (), generic=bool(generic), sense_key=sense_key, run_id=run_id,
                                  evidence={"rerooted_from": p["root"]}):
                out["facts"] += 1
    return dict(out)


# ---- 5. the name and type shown ----------------------------------------------------------------------------------

_SPAN_SQUASH = "lower(regexp_replace(m.span, '[^[:alnum:]]+', '', 'g'))"


def _span_counts(cur: Any, guide: Any, eids: List[str]) -> Dict[str, List[Tuple[str, int, int]]]:
    """{entity: [(span, sources, posts)]}: the spans not written as a handle nor in a post by the account they name."""
    cur.execute(f"""SELECT m.entity_id::text, m.span, count(DISTINCT p.source_id), count(DISTINCT m.post_id)
                      FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id LEFT JOIN sources s ON s.id = p.source_id
                     WHERE m.guide = ANY(%s) AND m.entity_id = ANY(%s::uuid[]) AND m.span <> ''
                       AND m.span !~ '^@' AND m.span !~ '^[A-Za-z0-9]+_[A-Za-z0-9_]*$'
                       AND {_SPAN_SQUASH} IS DISTINCT FROM lower(p.author)
                       AND {_SPAN_SQUASH} IS DISTINCT FROM
                           lower(regexp_replace(COALESCE(s.settings->>'display_name', ''), '[^[:alnum:]]+', '', 'g'))
                     GROUP BY 1, 2""", (guide, eids))
    out: Dict[str, List[Tuple[str, int, int]]] = defaultdict(list)
    for eid, span, srcs, posts in cur.fetchall():
        out[eid].append((span, int(srcs), int(posts)))
    return out


def _type(book: I.Book, root: str, members: List[str], ents: Iterable[I.Ent]) -> Optional[str]:
    """The type: the one most (SHOWN_TYPE_SHARE) of its mentions give, or person over org when a person's full name
    is in it and a third of its mentions say person; else its own."""
    types: Counter = Counter()
    for m in members:
        for t, n in book.types.get(m, {}).items():
            types[I.schemas_type(t)] += n
    base = I.schemas_type(book.ents[root].type)
    fam, org = book.sides(members)
    if base in I.ORGISH and root in fam:
        # 0164 B: a product account at the root ("Zentra Vela" typed an org) is shown as its family's type
        fams = [f for f in sorted(fam) if book.family_like(f)] or \
            [f for f in [book.product_of(book.ents[root].key)] if f]
        base = I.product_type(book, fams[0]) if fams else "model"
    total = sum(types.values())
    if not total:
        return base
    top, n = max(types.items(), key=lambda kv: (kv[1], str(kv[0])))
    if top in I.ORGISH and fam and not org:
        return base                      # 0164 B: a family whose org-typed names are its product accounts
    if top != base and n >= SHOWN_TYPE_SHARE * total and total >= SHOWN_TYPE_MIN:
        return top
    if base == "org" and types.get("person", 0) * 3 >= total and \
            any(book.etype(e.id) == "person" and len(e.key.split()) >= 2 for e in ents):
        return "person"
    return base


def choose(book: I.Book, root: str, members: List[str], spans: Dict[str, List[Tuple[str, int, int]]]
           ) -> Tuple[Optional[str], Optional[str]]:
    """(the name, the type) a cluster is shown under (None: its own)."""
    ents = [book.ents[m] for m in sorted(members) if book.ents[m].status != "not_entity"] or [book.ents[root]]
    by_key = {e.key: e.name for e in ents}
    by_sq: Dict[str, str] = {}
    for e in ents:
        by_sq.setdefault(e.sq, e.name)
    score: Counter = Counter()
    posts: Counter = Counter()
    for m in members:
        for span, srcs, n in spans.get(m, ()):
            k = N.key(span)
            name = by_key.get(k) or by_sq.get(N.squash(k))
            if name:
                score[name] += srcs
                posts[name] += n
    typ = _type(book, root, members, ents)
    base = I.schemas_type(book.ents[root].type)
    name = None
    if score:
        root_name = book.ents[root].name
        name = max(score, key=lambda x: (score[x], posts[x], x == root_name, x))
        if typ == "person" and len(N.key(name).split()) == 1:
            k = N.key(name)
            longer = [x for x in score if len(N.key(x).split()) >= 2 and k in N.key(x).split()]
            if longer:
                name = max(longer, key=lambda x: (score[x], posts[x], x))
    return (name if name and name != book.ents[root].name else None,
            typ if typ and typ != base else None)


class _Clusters(dict):
    """{root: its members} for the clusters of two or more names; any other root's members are itself."""

    def __missing__(self, r: str) -> Set[str]:
        return {r}


def shown(cur: Any, book: I.Book, guide: Any, *, roots: Optional[Iterable[str]], after: Optional[str] = None,
          deadline: Optional[float] = None) -> Dict[str, Any]:
    """The shown name and type of `roots` (None: every cluster, from `after` in id order, in chunks, stopping past
    `deadline` after a chunk; {done, after} says where). Writes only what changed; never an owner's rename."""
    # an owner's rename, and (0250) a split name's "<name> (<maker>)" (identity.split_names), are never replaced here
    cur.execute("SELECT id::text FROM mx_entities WHERE shown_by IN ('owner', 'split')")
    owners = {r[0] for r in cur.fetchall()}
    # v10.22 (0216): the clusters of two or more names; any other root is a cluster of one, itself (book.members() of
    # every root made a set for each of the server's 330k entities, ~90 MB, every run)
    members = _Clusters(book.clusters())
    if roots is None:   # every root (an entity that is its own root), from `after`
        todo = [r for r in book.ids(after) if book.root(r) == r]   # v10.23: read in id order, not walked
    else:
        todo = sorted({book.root(r) for r in roots if r in book.ents})
    out = Counter({"clusters": 0, "names": 0, "types": 0})
    from insight_core.markx import rename
    early = rename.earlier_members(cur)   # 0165 B: an earlier name (a rename's old side) is never the name shown
    from insight_core.markx import handles
    learned = handles.learned_names(cur, book)   # 0168 D: {root: (display name, its confirmed handles squashed)}

    def now_named(ms: List[str]) -> List[str]:
        if not early:
            return ms
        keep = []
        for m in ms:
            x, seen = m, set()
            while x is not None and x not in early and x in book.redirect and x not in seen:
                seen.add(x)
                x = book.redirect[x][0]
            if x not in early:
                keep.append(m)
        return keep or ms

    def write(r: str, spans: Dict[str, List[Tuple[str, int, int]]]) -> None:
        out["clusters"] += 1
        if r in owners:
            return
        e = book.ents[r]
        if len(members[r]) == 1:   # one name: its own; only the type can differ
            typ = _type(book, r, [r], [e])
            name, typ = None, (typ if typ != I.schemas_type(e.type) else None)
        else:
            name, typ = choose(book, r, now_named(sorted(members[r])), spans)
        lr = learned.get(r)   # 0168 D: a name that is one of its confirmed handles shows the name its pairs gave
        if lr and N.squash(N.key(name or e.name)) in lr[1]:
            name = lr[0] if lr[0] != e.name else None
        if (name, typ) != (e.shown_name, e.shown_type):
            cur.execute("""UPDATE mx_entities SET shown_name = %s, shown_type = %s, shown_by = 'evidence'
                            WHERE id = %s AND shown_by IS DISTINCT FROM 'owner'""", (name, typ, r))
            out["names"] += int(name != e.shown_name)
            out["types"] += int(typ != e.shown_type)
            e.shown_name, e.shown_type = name, typ

    def singles(page: List[str]) -> None:
        """One name each: only its type can change, read from the book (no spans)."""
        book.prime(ids=page)
        for want in (getattr(book.types, "want", None), getattr(book.version_parents(), "want", None)):
            if want is not None:
                want(page)
        book.prime_products(page)
        for r in page:
            write(r, {})
        if roots is None:
            book.forget(page)   # v10.23 (0218): a book read by need lets each page go

    def several(chunk: List[str]) -> None:
        """Clusters of several names: their names' spans read in one go."""
        book.prime_clusters(chunk)   # v10.23 (0218): a book read by need reads the chunk's clusters in one go
        book.prime_products(m for r in chunk for m in members[r])
        spans = _span_counts(cur, guide, sorted({m for r in chunk for m in members[r]}))
        for r in chunk:
            write(r, spans)

    # v10.23 (0218): one sweep in id order, a step at a time (SHOWN_CHUNK clusters of several names or SHOWN_SINGLES
    # of one, whichever comes first), stopping past `deadline` after a step; `after` (the step's last root) says where
    # the next run resumes. The single names were all done at a sweep's start, past the deadline: every run with a
    # full pass half done starts a sweep once the last is done (330k names read and let go, 18 s past the budget).
    # v10.24 (0221): a step starts only when the seconds the last one took are left (the first: any time left), so
    # the sweep never runs past the stage's budget; `steps` says how many it did
    done, last, steps, took = True, after, 0, 0.0
    lone: List[str] = []
    many: List[str] = []
    for n, r in enumerate(todo):
        (many if len(members[r]) > 1 else lone).append(r)
        if n + 1 < len(todo) and len(many) < SHOWN_CHUNK and len(lone) < SHOWN_SINGLES:
            continue
        if roots is None and deadline is not None and time.monotonic() + took > deadline:
            done = False   # this step and the rest are the next run's (it resumes after the last step done)
            break
        at = time.monotonic()
        for p in range(0, len(lone), SHOWN_CHUNK):
            singles(lone[p:p + SHOWN_CHUNK])
        if many:
            several(many)
        lone, many = [], []
        steps, last, took = steps + 1, r, time.monotonic() - at
    got: Dict[str, Any] = dict(out)
    if roots is None:
        got.update(done=done, after=None if done else last, steps=steps)
    return got


# ---- the step ---------------------------------------------------------------------------------------------------

STEPS = ("org_family", "product_accounts", "reparent", "families", "family_home", "names", "levels", "reroot")
GUESS = 1.0   # v10.24 (0221): the seconds a step never measured is expected to take


def repair(cur: Any, book: I.Book, *, run_id: Any, full: bool, deadline: Optional[float] = None,
           last: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Steps 1, 1b, 2 and 3, in order. v10.24 (0221): with what the stage's budget has left after the linking and the
    full pass. A step starts only when the seconds it took the last time (`last`: the last run's counts, `took`) are
    left; the steps it can't start are the next run's, which begins at the first of them (`next`) and goes on to the
    last (`done` once the last ran). Each step is idempotent: run again, it finds what is left to fix."""
    cfg = config()
    w = I.Writer(cur, book, run_id)
    out: Dict[str, Any] = {}
    t0 = time.monotonic()
    steps = {"org_family": lambda: undo_org_family(cur, book, run_id=run_id),
             "product_accounts": lambda: product_accounts(cur, book, run_id=run_id),
             "reparent": lambda: reparent(cur, book, w, run_id=run_id),
             "families": lambda: merge_families(cur, book, run_id=run_id),
             "family_home": lambda: family_home(cur, book, w, run_id=run_id),
             # 0250: a bare name several makers state, one thing a maker (identity.split_names; families.split)
             "names": lambda: I.split_names(cur, book, w, run_id=run_id, full=full),
             # v10.35: a cluster rooted on a build re-roots on its general name (identity.merge's keeper)
             "reroot": lambda: reroot_builds(cur, book, run_id=run_id),
             # v10.35: a product's SKU ("285K") is no checkpoint (identity.level_of)
             "levels": lambda: relevel(cur, book)}
    last = last or {}
    took_before = last.get("took") if isinstance(last.get("took"), dict) else {}
    start = STEPS.index(last["next"]) if last.get("next") in STEPS and last.get("done") is False else 0
    took: Dict[str, float] = {}
    nxt = None
    for name in STEPS[start:]:
        if not cfg.get(name, True):
            continue
        expect = float(took_before.get(name) or GUESS)
        if deadline is not None and time.monotonic() + expect > deadline:
            nxt = name   # this step and those after it are the next run's
            break
        at = time.monotonic()
        out[name] = steps[name]()
        took[name] = round(time.monotonic() - at, 3)
    out["took"] = {**{k: v for k, v in took_before.items() if k in STEPS}, **took}
    out["done"], out["next"] = nxt is None, nxt
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out
