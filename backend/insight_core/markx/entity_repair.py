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
  4. `suffix`: two orgs whose names are one once a corporate suffix goes ("Zentra" / "Zentra AI": AI, Inc.,
     Corporation, Labs, Technologies, Holdings), with posts naming the bare org beside things the suffixed one makes
     (or the other way round) in at least `min_posts` posts, merge (rule 'corp_suffix'); squashed-equal orgs (a maker
     made for the hierarchy alone is never pooled) merge as the squash rule does. Without the posts, nothing: the
     existing alias questions decide (a suffix alone is ambiguous: "Moon" / "Moon AI"). The full pass only.
  1b. `product_accounts` (0164 B): a name typed an org that is a product account's ("Zentra Vela": its family Vela's
     maker in front of the family's name; identity.Book.product_of) merges into its family (rule 'product_account'),
     never left an org; its shown type is the family's. Step 1 has cut it out of the maker's cluster first (Book.sides
     counts it on the family side).
  5. `shown`: the name and type each cluster is shown under, by evidence (mx_entities.shown_name, shown_type, on the
     root): the member name the most distinct sources write (then posts), counting no span written as a handle nor
     a post by the account it names (an account's display name: "Zentra Devs"); a person by the full name holding
     its one-word name; the type that most (SHOWN_TYPE_SHARE) of its mentions give, or person over org when a
     person's full name is in it and a third of its mentions say person. The touched clusters each run; every
     cluster over the full passes, resumed (`after`).

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
SUFFIX_LIMIT = 200        # suffix pairs a run checks against the posts
SHOWN_CHUNK = 2000        # clusters whose shown name one query reads
BRAND_MIN = 3
SUFFIXES = ("ai", "inc", "corporation", "corp", "labs", "lab", "technologies", "holdings")
SHOWN_TYPE_SHARE = 0.75
SHOWN_TYPE_MIN = 5


def config() -> Dict[str, Any]:
    got = I.bands().get("repairs") or {}
    return {"org_family": got.get("org_family", True), "product_accounts": got.get("product_accounts", True),
            "reparent": got.get("reparent", True),
            "families": got.get("families", True), "suffix": got.get("suffix", True),
            "suffix_min_posts": int(got.get("suffix_min_posts", 2)), "shown": got.get("shown", True)}


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
    for root, ms in sorted(book.members().items()):
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

def product_accounts(cur: Any, book: I.Book, *, run_id: Any, limit: int = PRODUCT_LIMIT) -> Dict[str, int]:
    """0164 B on the data already made: an entity typed an org whose name is a product account's (Book.product_of:
    "Zentra Vela", the family Vela's maker in front of it) merges into its family (rule 'product_account'), when
    neither cluster holds an org (step 1 cut the automatic links to one; an owner's link is left, `held`) and the
    owner never kept them apart. Its shown type is the family's (`shown`). Idempotent: once one cluster, skipped."""
    out = Counter({"accounts": 0, "merged": 0, "held": 0})
    for e in sorted(book.ents.values(), key=lambda e: e.id):
        if out["merged"] >= limit:
            break
        if " " not in e.key or e.status == "not_entity" or e.level in I.VERSION_LEVELS or book.etype(e.id) != "org":
            continue
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
    for root, ms in book.members().items():
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
    for e in sorted(book.ents.values(), key=lambda e: e.id):
        if e.level not in I.VERSION_LEVELS or not e.parent or e.status == "not_entity":
            continue
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


# ---- 3. families split by a maker or brand prefix -------------------------------------------------------------

def _family_roots(book: I.Book) -> Dict[str, List[str]]:
    """{root: its names} of the clusters holding a family (a `family` entity, or a name a version names as its parent:
    a family first written bare is a `thing`) and no org: every member but its versions."""
    roots: Set[str] = set()
    vp = book.version_parents()
    for e in book.ents.values():
        if (e.level == "family" or e.id in vp) and e.status != "not_entity" and book.etype(e.id) not in I.ORGISH:
            roots.add(book.root(e.id))
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
    for e in book.ents.values():
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
    vp = book.version_parents()
    for e in book.ents.values():
        if (e.level == "family" or e.id in vp) and e.status != "not_entity" and book.etype(e.id) not in I.ORGISH:
            fam_keys[book.root(e.id)].add(e.key)
    multi = {r for r, ks in fam_keys.items() if len(ks) >= 2}
    by: Dict[Tuple[str, Tuple], Dict[str, str]] = defaultdict(dict)
    for e in sorted(book.ents.values(), key=lambda e: e.id):
        if e.level not in I.VERSION_LEVELS or not e.parent or e.status == "not_entity":
            continue
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


# ---- 4. an org and its name with a corporate suffix --------------------------------------------------------------

def _bare(key: str) -> Optional[str]:
    words = key.split()
    if len(words) >= 2 and words[-1] in SUFFIXES:
        b = N.squash(" ".join(words[:-1]))
        return b if len(b) >= 3 else None
    return None


def link_suffix(cur: Any, book: I.Book, guide: Any, *, run_id: Any, min_posts: int = 2,
                limit: int = SUFFIX_LIMIT) -> Dict[str, int]:
    out = Counter({"pairs": 0, "merged_squash": 0, "merged_suffix": 0, "no_posts": 0, "judged_apart": 0})
    orgs = [r for r, ms in book.members().items() if r in book.ents and book.ents[r].status != "not_entity"
            and book.org_like(r)]
    by_sq: Dict[str, Set[str]] = defaultdict(set)
    for r in orgs:
        for x in book.cluster(r):
            if book.ents[x].sq:
                by_sq[book.ents[x].sq].add(r)
    cands: Set[Tuple[str, str, str]] = set()
    for r in orgs:
        for x in book.cluster(r):
            k = book.ents[x].key
            for o in by_sq.get(book.ents[x].sq, ()):
                if o != r:
                    cands.add((min(r, o), max(r, o), "squash"))
            b = _bare(k)
            for o in by_sq.get(b or "", ()):
                if o != r:
                    cands.add((r, o, "suffix"))      # r: the suffixed side
    made_by_key: Dict[str, List[str]] = defaultdict(list)    # a stated maker's key -> the things it makes
    made_under: Dict[str, List[str]] = defaultdict(list)     # a parent cluster -> the things under it
    for e in book.ents.values():
        if e.id in book.mentioned:
            if e.maker:
                made_by_key[N.key(e.maker)].append(e.id)
            if e.parent:
                made_under[book.root(e.parent)].append(e.id)

    def made(r: str) -> List[str]:
        got = set(made_under.get(r, ()))
        for x in book.cluster(r):
            got.update(made_by_key.get(book.ents[x].key, ()))
        return sorted(got)
    for a, b, how in sorted(cands):
        if out["pairs"] >= limit:
            break
        ra, rb = book.root(a), book.root(b)
        if ra == rb or ra not in book.ents or rb not in book.ents:
            continue
        ca, cb = book.cluster(ra), book.cluster(rb)
        # the chain guard's: never two clusters of 2 or more names, never more than MAX_CLUSTER
        if _never_between(book, ca, cb) or (len(ca) >= 2 and len(cb) >= 2) or len(ca) + len(cb) > I.MAX_CLUSTER:
            continue
        out["pairs"] += 1
        if _judged_apart(cur, ca, cb):
            out["judged_apart"] += 1
            continue
        ev: Dict[str, Any] = {"rules": [f"corp_{how}"], "confidence": I.RULE_CONF}
        if how == "suffix":
            n = _beside(cur, guide, made(ra), cb) + _beside(cur, guide, made(rb), ca)
            if n < min_posts:
                out["no_posts"] += 1
                continue
            ev["posts"] = n
        if I.merge(cur, book, ra, rb, by="rule:corp_" + how, automatic=True, run_id=run_id, evidence=ev):
            out["merged_" + how] += 1
    return dict(out)


def _beside(cur: Any, guide: Any, made: List[str], others: List[str]) -> int:
    """The posts naming one of `others` beside one of `made` (the things a maker makes: their stated maker one of its
    cluster's names, or their parent the cluster)."""
    if not made or not others:
        return 0
    cur.execute("""SELECT count(DISTINCT x.post_id) FROM mx_mentions_now x JOIN mx_mentions_now y
                     ON y.post_id = x.post_id AND y.guide = x.guide
                    WHERE x.guide = ANY(%s) AND x.entity_id = ANY(%s::uuid[]) AND y.entity_id = ANY(%s::uuid[])""",
                (guide, list(others), made))
    return int(cur.fetchone()[0] or 0)


def _judged_apart(cur: Any, xs: List[str], ys: List[str]) -> bool:
    """Haiku called a pair of their names different (or another thing's version)."""
    cur.execute("""SELECT 1 FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                    WHERE t.kind IN ('alias', 'alias2') AND ((t.a = ANY(%s::uuid[]) AND t.b = ANY(%s::uuid[]))
                          OR (t.a = ANY(%s::uuid[]) AND t.b = ANY(%s::uuid[])))
                      AND c.answer->>'relation' IS DISTINCT FROM 'same' LIMIT 1""", (xs, ys, ys, xs))
    return cur.fetchone() is not None


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


def shown(cur: Any, book: I.Book, guide: Any, *, roots: Optional[Iterable[str]], after: Optional[str] = None,
          deadline: Optional[float] = None) -> Dict[str, Any]:
    """The shown name and type of `roots` (None: every cluster, from `after` in id order, in chunks, stopping past
    `deadline` after a chunk; {done, after} says where). Writes only what changed; never an owner's rename."""
    cur.execute("SELECT id::text FROM mx_entities WHERE shown_by = 'owner'")
    owners = {r[0] for r in cur.fetchall()}
    members = book.members()
    if roots is None:
        todo = sorted(r for r in members if r in book.ents and (after is None or r > after))
    else:
        todo = sorted({book.root(r) for r in roots if r in book.ents} & set(members))
    out = Counter({"clusters": 0, "names": 0, "types": 0})
    from insight_core.markx import rename
    early = rename.earlier_members(cur)   # 0165 B: an earlier name (a rename's old side) is never the name shown

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
        if (name, typ) != (e.shown_name, e.shown_type):
            cur.execute("""UPDATE mx_entities SET shown_name = %s, shown_type = %s, shown_by = 'evidence'
                            WHERE id = %s AND shown_by IS DISTINCT FROM 'owner'""", (name, typ, r))
            out["names"] += int(name != e.shown_name)
            out["types"] += int(typ != e.shown_type)
            e.shown_name, e.shown_type = name, typ
    # one name: only its type can change, read from the book (no query); the clusters of several names in chunks
    for r in todo:
        if len(members[r]) == 1 and (roots is not None or after is None):
            write(r, {})
    many = [r for r in todo if len(members[r]) > 1]
    last, done = after, True
    for k in range(0, len(many), SHOWN_CHUNK):
        chunk = many[k:k + SHOWN_CHUNK]
        spans = _span_counts(cur, guide, sorted({m for r in chunk for m in members[r]}))
        for r in chunk:
            write(r, spans)
        last = chunk[-1]
        if roots is None and k + SHOWN_CHUNK < len(many) and deadline is not None and time.monotonic() > deadline:
            done = False
            break
    got: Dict[str, Any] = dict(out)
    if roots is None:
        got.update(done=done, after=None if done else last)
    return got


# ---- the step ---------------------------------------------------------------------------------------------------

def repair(cur: Any, book: I.Book, *, run_id: Any, full: bool, deadline: Optional[float] = None) -> Dict[str, Any]:
    """Steps 1-4 (4 on the full pass), in order, each skipped past `deadline` (the next run does it)."""
    from insight_core.markx import schemas
    cfg = config()
    guide = schemas.mention_guides()
    w = I.Writer(cur, book, run_id)
    out: Dict[str, Any] = {}
    t0 = time.monotonic()
    steps = [("org_family", lambda: undo_org_family(cur, book, run_id=run_id)),
             ("product_accounts", lambda: product_accounts(cur, book, run_id=run_id)),
             ("reparent", lambda: reparent(cur, book, w, run_id=run_id)),
             ("families", lambda: merge_families(cur, book, run_id=run_id))]
    if full:
        steps.append(("suffix", lambda: link_suffix(cur, book, guide, run_id=run_id,
                                                     min_posts=cfg["suffix_min_posts"])))
    for name, step in steps:
        if not cfg.get(name, True):
            continue
        if deadline is not None and time.monotonic() > deadline:
            out[name] = {"skipped": "budget"}
            continue
        out[name] = step()
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out
