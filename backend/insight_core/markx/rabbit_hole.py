"""The rabbit hole (issue 0138 E3-E4): an entity's world on its page, and Discover's row for one with something left.

For an org, a person or a document with 2+ works (its `published` documents, 0133's edges) or 10+ posts:
  - **its sites:** the sites of its addresses and of its works' (markx/entity_addresses.py: release pages and work sites'
    front pages; never a paper host or a code host, which are no one's site), each with what you have of it: followed,
    stored (its front page is a post), or what Discover's follow test said (a feed: Follow; a page: Watch page; untested:
    Follow, the feed finder decides). Every add goes through Add source (the feed finder, then page watching);
  - **its works:** its published documents with their original (a paper, a release page, a work site), stored or not;
  - **its people:** who it is published by and whom it publishes (people only), and who talks about it (its voices, on
    the page already).
Read only; nothing is fetched or followed here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from insight_core.markx import entity_addresses as EA
from insight_core.markx import identity as I
from insight_core.utils import entity_originals as R
from insight_core.utils.addresses import host_of, site_of
from insight_core.utils.discover_rules import paper_address
from insight_core.utils.url_normalization import normalize_url

TYPES = ("org", "person", "document")
MIN_WORKS, MIN_POSTS = 2, 10
SITE_KINDS = (R.RELEASE, R.WORK)


def eligible(type_: Optional[str], works: int, posts: int) -> bool:
    return type_ in TYPES and (works >= MIN_WORKS or posts >= MIN_POSTS)


def _sites(urls: List[str]) -> List[str]:
    out: List[str] = []
    for url in urls:
        host = host_of(url)
        if not host or paper_address(url) or site_of(host) in R.CODE_SITES or site_of(host) == "huggingface.co":
            continue
        front = normalize_url(f"https://{host}/") or f"https://{host}/"
        if front not in out:
            out.append(front)
    return out


def of(cur: Any, book: I.Book, root: str, *, works: List[str], people: List[str], posts: int,
       followed: Optional[Set[str]] = None, follow_tests: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """{sites: [{url, host, state: followed | stored | feed | page | untested}], works: [{id, name, url, kind, stored,
    post_id}], people: [{id, name}], left: {sites, works}} for an eligible entity, else None. `works`: its published
    documents' roots; `people`: its published edges' other ends."""
    from insight_core.db.repo_discover import light_facts
    from insight_core.markx import schemas
    e = book.ents[root]
    if not eligible(schemas.entity_type(e.type), len(works), posts):
        return None
    found = EA.current(cur, book, [root, *works])
    work_rows = []
    urls = [u for k, u, _r, _a, _p in found.get(root, ()) if k in SITE_KINDS]
    for w in works:
        picked = R.pick((k, u, r, at) for k, u, r, at, _ in found.get(w, ()))
        orig = R.original_of(picked)
        urls += [v[0] for k, v in picked.items() if k in SITE_KINDS]
        work_rows.append({"id": w, "name": book.label(w), "url": orig[1] if orig else None,
                          "kind": orig[0] if orig else None})
    sites = _sites(urls)
    stored_urls = [w["url"] for w in work_rows if w["url"]] + sites
    stored: Dict[str, str] = {}
    if stored_urls:
        cur.execute("SELECT normalized_url, id::text FROM posts WHERE normalized_url = ANY(%s)", (stored_urls,))
        stored = dict(cur.fetchall())
    for w in work_rows:
        w["post_id"] = stored.get(w["url"]) if w["url"] else None
        w["stored"] = w["post_id"] is not None
    if followed is None:
        followed = light_facts(cur).followed()
    tests = follow_tests if follow_tests is not None else _follow_tests(cur)
    site_rows = []
    for front in sites:
        host = host_of(front)
        h = host[4:] if host.startswith("www.") else host
        if h in followed or site_of(h) in followed:
            state = "followed"
        elif front in stored:
            state = "stored"
        else:
            label = (tests.get(h) or tests.get(site_of(h)) or {}).get("label")
            state = "feed" if label == "feed" else "page" if label == "page" else "untested"
        site_rows.append({"url": front, "host": h, "state": state})
    people_rows = [{"id": p, "name": book.label(p)} for p in people
                   if p in book.ents and schemas.entity_type(book.ents[p].type) == "person"]
    left = {"sites": sum(1 for s in site_rows if s["state"] not in ("followed", "stored")),
            "works": sum(1 for w in work_rows if w["url"] and not w["stored"])}
    return {"sites": site_rows, "works": work_rows, "people": people_rows, "left": left}


def _follow_tests(cur: Any) -> Dict[str, Any]:
    from insight_core.db.repo_discover import DiscoverRepository
    return (DiscoverRepository.reads(cur) or {}).get("follow") or {}


def discover_rows(cur: Any, *, limit: int = 12) -> List[Dict[str, Any]]:
    """E4: "<entity>: N sites, M not followed, K works not stored" for the entities with 2+ works whose rabbit hole has
    something left, the most left first. Only entities some current reading names (`named`, roots)."""
    from insight_core.db.repo_discover import light_facts
    cur.execute("""SELECT a::text, b::text FROM mx_connections WHERE valid_to IS NULL AND relation = 'published'
                     AND a_kind = 'entity' AND b_kind = 'entity'""")
    edges = cur.fetchall()
    if not edges:
        return []
    from insight_core.markx.entity_views import named_now
    book = I.load_book(cur)
    named = named_now(cur, book)
    works: Dict[str, Set[str]] = {}
    for a, b in edges:
        ra, rb = book.root(a), book.root(b)
        if ra in book.ents and rb in book.ents and ra != rb and rb in named:
            works.setdefault(ra, set()).add(rb)
    candidates = [r for r, ws in works.items() if len(ws) >= MIN_WORKS and r in named]
    if not candidates:
        return []
    followed, tests = light_facts(cur).followed(), _follow_tests(cur)
    out = []
    for r in candidates:
        hole = of(cur, book, r, works=sorted(works[r]), people=[], posts=0, followed=followed, follow_tests=tests)
        if not hole or not (hole["left"]["sites"] or hole["left"]["works"]):
            continue
        out.append({"entity": {"id": r, "name": book.label(r)}, "sites": len(hole["sites"]),
                    "not_followed": hole["left"]["sites"], "works_not_stored": hole["left"]["works"]})
    out.sort(key=lambda x: (-(x["not_followed"] + x["works_not_stored"]), x["entity"]["name"]))
    return out[:limit]


__all__ = ["discover_rows", "eligible", "of"]
