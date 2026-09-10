"""
MILESTONES: the landmark releases in a field, as a succession tree.

Computed on read. No derive job, no LLM call, no stored node table. Grouping,
ordering, flagging and cross-lane comparison all happen here in Python over the
hit rows the repo returns.

Scoping reuses folders verbatim via FoldersService.list_source_ids.

DELIBERATE DEVIATION, flagged: this does NOT call
posts_service.get_posts_by_sources_and_range. That method loops one query per
source in Python - 54 round trips for the Smart Glasses track - and cannot push the
lane regex or the slug blocklist into SQL, so it would pull every post into the
process to filter a hundred of them. The scan here is one pushed-down statement.
Scope resolution still goes through FoldersService, which is the part that matters.
"""
import os
import re
import time
import threading
from contextlib import contextmanager
from datetime import date, datetime
from typing import Iterator, List, Dict, Any, Optional, Tuple

import psycopg

from insight_core.db.repo_milestones import MilestonesRepository
from insight_core.services.folders_service import FoldersService
from insight_core.logs.core.logger_config import get_component_logger

# Hard ceiling on hit rows pulled into the process. At the current corpus the real
# number is a few hundred. This exists so that a pathological user pattern like '(.)'
# cannot turn a page load into an OOM. 5000 rows is ~4MB and still renders (badly), so
# we truncate and say so in diagnostics rather than failing.
MAX_HIT_ROWS = int(os.getenv("INSIGHT_MILESTONES_MAX_HITS", "5000"))
MAX_LANES = int(os.getenv("INSIGHT_MILESTONES_MAX_LANES", "200"))
# The tree is a pure function of (posts, lanes, overrides). A 60s memo makes tab
# switching and back-navigation free without ever showing stale data for longer than
# one ingestion is likely to take. Mutations drop the cache entirely.
CACHE_TTL_SECONDS = int(os.getenv("INSIGHT_MILESTONES_CACHE_TTL", "60"))
# The evidence drawer is a SECOND cache tier on purpose, with a much longer TTL.
# get_node used to share the 60s tree memo, so the ordinary reading-rail pattern -
# open a track, read for two minutes, click "Evidence (5)" - fell off the memo and
# paid a full 6.6s corpus derivation to return five rows, rebuilding all 1177 nodes.
# A node's evidence is far more stable than the tree header (it only changes when
# ingestion adds a post to that exact node), so it can be held much longer at no
# real staleness cost, and mutations still drop it via _invalidate.
NODE_CACHE_TTL_SECONDS = int(os.getenv("INSIGHT_MILESTONES_NODE_CACHE_TTL", "900"))
# The node index pins that scope's evidence rows in memory (~1.2MB of the 1.85MB the
# list payload used to ship) for the whole TTL, so bound how many scopes can be pinned
# at once. Realistically one or two tracks are hot; the rest are evicted oldest-first.
MAX_NODE_CACHE_SCOPES = 16
# _CACHE holds the full payload including every evidence row, so it is the fatter tier and
# gets the tighter bound. Two scopes covers the realistic pattern (the main rail plus one
# track); anything beyond that is a folder_id nobody is currently looking at.
MAX_CACHE_SCOPES = 2

_CACHE: Dict[Tuple, Tuple[float, Dict[str, Any]]] = {}
# scope key -> (stored_at, {node_key: node}). Values are the SAME node dicts the tree
# payload holds, so warming this costs a pointer store per node, not a copy.
_NODE_CACHE: Dict[Tuple, Tuple[float, Dict[str, Dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()

# Bumped by every _invalidate(). A build reads it before touching the DB and refuses to
# store its result if it changed in the meantime. main.py runs get_milestone_node through
# asyncio.to_thread, so a build genuinely runs in parallel with the event loop now - before
# that, API_WORKERS=1 plus fully synchronous route bodies made _build_full and _invalidate
# mutually atomic and this could not happen. Without the guard, a 6.6s build that started
# before a 'hide' click repopulates both tiers with pre-hide data on the way out, and the
# one user-facing write in this feature appears to do nothing for up to
# NODE_CACHE_TTL_SECONDS - a page refresh included.
_CACHE_GENERATION = 0
# cache_key -> (lock, waiter_count). Single-flight: N concurrent misses on one scope share
# one derivation instead of each opening its own psycopg connection and materialising its
# own MAX_HIT_ROWS hit set. The single event loop used to enforce this for free.
_BUILD_LOCKS: Dict[Tuple, list] = {}

_SAFE_NAME = re.compile(r"^[\w .+/&-]{1,60}$")


def _evict_oldest(cache: Dict[Tuple, Tuple[float, Any]], max_entries: int) -> None:
    """Drop oldest-first until the cache is within bounds. Call under _CACHE_LOCK."""
    while len(cache) > max_entries:
        del cache[min(cache, key=lambda key: cache[key][0])]


def _version_sort(label: str) -> str:
    """Zero-pad each dot-separated numeric run to 5 chars.

    '5'   -> '00005'
    '5.6' -> '00005.00006'
    Lexicographic order over these strings is semver-ish order, and it degrades
    safely on junk (a non-numeric part sorts as itself). '.' (0x2E) sorts before
    '0' (0x30), so '00005' < '00005.00006' - a bare major precedes its own minors,
    which is what you want.

    THIS, NOT THE DATE, IS THE ORDER OF A CHAIN. Claude Opus 4.5 is first observed
    2025-11-24 while 4.6 is first observed 2026-05-28; a date-ordered lane renders
    Anthropic's lineage out of order.
    """
    parts = str(label or "").split(".")
    return ".".join(p.zfill(5) if p.isdigit() else p for p in parts)


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _day(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


class MilestonesService:
    """Derives the milestone tree on read; owns lane and override CRUD."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = MilestonesRepository(db_url)
        self.folders_service = FoldersService(db_url)
        self.logger = get_component_logger("milestones_service")

    # ---------- scope ----------

    def _resolve_source_ids(self, folder_id: Optional[str]) -> Optional[List[str]]:
        """None  = every non-arXiv source (the default landing scope).
        []      = a real, empty folder. NOT the same thing.

        folder_id NULL has to be a first-class scope: a large slice of the corpus -
        both Telegram channels and every GitHub feed - belongs to no folder, and that
        is where the release chain actually lives.
        """
        if not folder_id:
            return None
        return self.folders_service.list_source_ids(folder_id)

    # ---------- lanes ----------

    def list_lanes(self, folder_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_lanes(cur, folder_id)

    def create_lane(self, name: str, vendor: Optional[str] = None,
                    match_pattern: Optional[str] = None,
                    folder_id: Optional[str] = None,
                    lane_order: int = 500) -> Dict[str, Any]:
        """A lane with no explicit pattern gets one generated from its name.

        This is what makes the empty state actionable for a non-AI track: the user
        types 'Ray-Ban Display' / 'Meta' and gets a working lane with no regex.
        """
        clean = (name or "").strip()
        if not clean:
            raise ValueError("Lane name is required")
        if not _SAFE_NAME.match(clean):
            raise ValueError("Lane name may only contain letters, digits, space . + / & -")
        pattern = (match_pattern or "").strip() or self._pattern_from_name(clean)
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                if len(self.repo.list_lanes(cur, folder_id)) >= MAX_LANES:
                    raise ValueError(f"Lane limit reached ({MAX_LANES})")
                err = self.repo.validate_pattern(cur, pattern)
                if err:
                    raise ValueError(err)
                lane = self.repo.insert_lane(
                    cur, folder_id, clean, (vendor or "").strip() or None,
                    pattern, int(lane_order),
                )
                conn.commit()
        self._invalidate()
        return lane

    @staticmethod
    def _pattern_from_name(name: str) -> str:
        """'Ray-Ban Display' -> '\\m(?:ray\\-ban display)[ -]?v?([0-9]+(?:\\.[0-9]+)?)\\M'"""
        escaped = re.sub(r"([.+*?()\[\]{}|^$\\-])", r"\\\1", name.lower())
        return r"\m(?:" + escaped + r")[ -]?v?([0-9]+(?:\.[0-9]+)?)\M"

    def update_lane(self, lane_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                if fields.get("match_pattern"):
                    err = self.repo.validate_pattern(cur, str(fields["match_pattern"]))
                    if err:
                        raise ValueError(err)
                lane = self.repo.update_lane(cur, lane_id, fields)
                conn.commit()
        if lane is None:
            raise ValueError(f"Lane {lane_id} not found")
        self._invalidate()
        return lane

    def delete_lane(self, lane_id: str) -> bool:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                deleted = self.repo.delete_lane(cur, lane_id)
                conn.commit()
        self._invalidate()
        return deleted

    def preview_pattern(self, pattern: str,
                        folder_id: Optional[str] = None) -> Dict[str, Any]:
        source_ids = self._resolve_source_ids(folder_id)
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                err = self.repo.validate_pattern(cur, pattern)
                if err:
                    return {"success": False, "error": err,
                            "total_hits": 0, "versions": [], "samples": []}
                result = self.repo.preview_pattern(cur, pattern, source_ids)
        return {"success": True, **result}

    # ---------- overrides ----------

    def set_node_state(self, node_key: str, state: Optional[str] = None,
                       custom_title: Optional[str] = None,
                       note: Optional[str] = None) -> Dict[str, Any]:
        key = (node_key or "").strip()
        if not key or len(key) > 200:
            raise ValueError("node_key is required")
        if state is not None and state not in ("active", "hidden", "pinned"):
            raise ValueError("state must be active, hidden or pinned")
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                row = self.repo.upsert_override(cur, key, state, custom_title, note)
                conn.commit()
        self._invalidate()
        return row

    # ---------- the tree ----------

    def _invalidate(self) -> None:
        # Both tiers, always. A lane edit changes which posts land on which node, so a
        # surviving node index would hand back evidence for a node that no longer exists.
        # The generation bump also disowns every build already in flight, which clearing
        # alone cannot do - see _CACHE_GENERATION.
        global _CACHE_GENERATION
        with _CACHE_LOCK:
            _CACHE_GENERATION += 1
            _CACHE.clear()
            _NODE_CACHE.clear()

    def get_tree(self, folder_id: Optional[str] = None,
                 include_hidden: bool = False) -> Dict[str, Any]:
        """The list payload: the full tree with the per-node detail projected away.

        Measured at 1.85MB on the live corpus, of which ~two thirds was evidence rows
        and uncapped comparison edges that the rail only renders behind a click (or,
        for comparisons, never past the third). Detail now comes from get_node.
        """
        return self._project_list(self._build_full(folder_id, include_hidden))

    # Everything the rail reads off a node on first paint. Anything not in here is
    # either backend-internal (version_sort orders the chain, state drives hiding) or
    # fetched on demand by get_node.
    _LIST_NODE_FIELDS = ("node_key", "title", "custom_title", "occurred_on",
                         "post_count", "source_count", "flags")
    # The rail renders .slice(0, 3). Shipping the other 40 edges of a busy node is
    # pure waste; comparison_count keeps a "+N more" affordance possible.
    LIST_COMPARISON_CAP = 3

    def _project_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Rebuild payload with slimmed nodes.

        MUST construct new dicts, never mutate in place: _build_full hands back a
        shallow copy of the memoized payload, so `del node["evidence"]` here would
        gut the cached full tree and break get_node for the rest of the TTL.
        """
        def node(src: Dict[str, Any]) -> Dict[str, Any]:
            out = {key: src.get(key) for key in self._LIST_NODE_FIELDS}
            comparisons = src.get("comparisons") or []
            out["comparisons"] = [
                {"node_key": c.get("node_key"), "title": c.get("title"),
                 "post_id": c.get("post_id"), "post_title": c.get("post_title")}
                for c in comparisons[:self.LIST_COMPARISON_CAP]
            ]
            out["comparison_count"] = len(comparisons)
            return out

        slim = dict(payload)
        slim["vendors"] = [
            {
                "vendor": v.get("vendor"),
                "node_count": v.get("node_count"),
                "lanes": [
                    {
                        "lane_id": l.get("lane_id"),
                        "lane_name": l.get("lane_name"),
                        "node_count": l.get("node_count"),
                        "nodes": [node(n) for n in (l.get("nodes") or [])],
                    }
                    for l in (v.get("lanes") or [])
                ],
            }
            for v in (payload.get("vendors") or [])
        ]
        slim["papers"] = [node(p) for p in (payload.get("papers") or [])]
        return slim

    def get_node(self, node_key: str, folder_id: Optional[str] = None,
                 include_hidden: bool = False) -> Dict[str, Any]:
        """Evidence and comparisons for one node, uncapped.

        No SQL of its own in the common case: every full-tree build indexes its nodes
        into _NODE_CACHE, which outlives the tree memo by NODE_CACHE_TTL_SECONDS, so a
        drawer click minutes after the page load is a dict lookup and no DB round trip.

        A miss still costs one whole-tree derivation, because a node's comparison edges
        are cross-lane by construction - they exist only where one post matches two
        different lanes - and repo_milestones exposes no way to ask for one node's or
        one post's hits. That rebuild is now bounded to once per scope per node-cache
        TTL rather than once per click, it warms every other node on the page with it,
        and main.py runs this whole call off the event loop.

        Pass the SAME include_hidden the list call used or this hits a second cache key
        and rebuilds the whole tree.
        """
        key = (node_key or "").strip()
        if not key:
            return {"success": False, "error": "node_key is required",
                    "evidence": [], "comparisons": []}
        index = self._cached_index(folder_id, include_hidden)
        if index is not None:
            node = index.get(key)
            if node is not None:
                return self._node_detail(node)
            return {"success": False, "error": "Node not found",
                    "evidence": [], "comparisons": []}
        payload = self._build_full(folder_id, include_hidden)
        for vendor in payload.get("vendors") or []:
            for lane in vendor.get("lanes") or []:
                for node in lane.get("nodes") or []:
                    if node.get("node_key") == key:
                        return self._node_detail(node)
        for paper in payload.get("papers") or []:
            if paper.get("node_key") == key:
                return self._node_detail(paper)
        return {"success": False, "error": "Node not found",
                "evidence": [], "comparisons": []}

    @staticmethod
    def _node_detail(node: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "node_key": node.get("node_key"),
            "evidence": list(node.get("evidence") or []),
            "comparisons": list(node.get("comparisons") or []),
        }

    @staticmethod
    def _cached_index(folder_id: Optional[str],
                      include_hidden: bool) -> Optional[Dict[str, Dict[str, Any]]]:
        """The whole scope's node index, or None if cold. Not one node.

        Returning the index rather than a node is what lets get_node answer 'Node not
        found' from memory: within a scope the index is exactly the set of nodes the
        tree walk would find, so an unknown key needs no derivation either. Otherwise a
        stale or bogus node_key rebuilds the corpus on every request.
        """
        cache_key = (folder_id or "", bool(include_hidden))
        with _CACHE_LOCK:
            entry = _NODE_CACHE.get(cache_key)
            if not entry or time.monotonic() - entry[0] >= NODE_CACHE_TTL_SECONDS:
                return None
            return entry[1]

    @staticmethod
    def _store(cache_key: Tuple, generation: int, payload: Dict[str, Any],
               nodes: List[Dict[str, Any]]) -> None:
        """Publish one build to both cache tiers, or to neither.

        Only the nodes that survived the include_hidden filter are indexed, so a hidden node
        stays 'Node not found' in the drawer exactly as it is in the tree walk.

        Both tiers are written under one lock acquisition: they are two views of the same
        derivation, and an _invalidate() landing between them would leave the drawer holding
        evidence for a tree nobody can see. A build whose generation is stale drops its
        result entirely rather than resurrecting pre-mutation data.

        Timestamps are taken HERE, not at build start. Stamping a 30s build with its start
        time makes it the oldest entry the instant it lands, so the slowest-building scope -
        the one the node cache exists for - evicts itself on insert.
        """
        stored_at = time.monotonic()
        index = {n["node_key"]: n for n in nodes}
        with _CACHE_LOCK:
            if generation != _CACHE_GENERATION:
                return
            _CACHE[cache_key] = (stored_at, payload)
            _NODE_CACHE[cache_key] = (stored_at, index)
            # Both tiers are bounded, and _CACHE more tightly than _NODE_CACHE: it holds the
            # FULL payload (evidence rows included, ~4MB per scope at MAX_HIT_ROWS) while the
            # index holds ~1.2MB. _read_cache only *ignores* stale entries, it never dropped
            # them, so every distinct folder_id ever passed to /api/milestones - a query
            # param, so caller-controlled - pinned a payload until the next _invalidate().
            # That is the same shape as the /api/operations/overview growth that cost ~1GB.
            _evict_oldest(_CACHE, MAX_CACHE_SCOPES)
            _evict_oldest(_NODE_CACHE, MAX_NODE_CACHE_SCOPES)

    @staticmethod
    def _read_cache(cache_key: Tuple) -> Optional[Dict[str, Any]]:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
                return dict(cached[1], cached=True)
            return None

    @staticmethod
    @contextmanager
    def _build_slot(cache_key: Tuple) -> Iterator[None]:
        """Hold the single-flight lock for one scope, refcounted so the dict stays bounded.

        folder_id reaches here straight off a query param, so leaving one lock per key
        behind forever is an unbounded dict keyed by user input.
        """
        with _CACHE_LOCK:
            entry = _BUILD_LOCKS.get(cache_key)
            if entry is None:
                entry = _BUILD_LOCKS[cache_key] = [threading.Lock(), 0]
            entry[1] += 1
        try:
            # Acquired outside _CACHE_LOCK: it is held for the whole multi-second derivation.
            with entry[0]:
                yield
        finally:
            with _CACHE_LOCK:
                entry[1] -= 1
                if entry[1] <= 0:
                    _BUILD_LOCKS.pop(cache_key, None)

    def _build_full(self, folder_id: Optional[str] = None,
                    include_hidden: bool = False) -> Dict[str, Any]:
        cache_key = (folder_id or "", bool(include_hidden))
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached
        with self._build_slot(cache_key):
            # Re-check: whoever held the slot has just published, and paying for a second
            # full derivation of the same scope is exactly what the slot exists to prevent.
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached
            return self._derive_full(cache_key, folder_id, include_hidden)

    def _derive_full(self, cache_key: Tuple, folder_id: Optional[str],
                     include_hidden: bool) -> Dict[str, Any]:
        # Read BEFORE the DB work: anything invalidated from here on invalidates this build.
        with _CACHE_LOCK:
            generation = _CACHE_GENERATION

        started = time.monotonic()
        source_ids = self._resolve_source_ids(folder_id)
        scope = self._describe_scope(folder_id, source_ids)

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                lanes = self.repo.list_lanes(cur, folder_id, enabled_only=True)
                overrides = self.repo.list_overrides(cur)
                coverage = self.repo.scope_coverage(cur, source_ids)
                briefing_count = self.repo.count_daily_briefings(cur)
                # Lane patterns are user-editable regexes evaluated over the whole corpus.
                # Postgres' DFA engine shrugs off classic catastrophic patterns, but a
                # pathological one is still slow, and validate_pattern only compiles against
                # a 13-char probe string - cheap to validate, expensive to run. Bound it.
                cur.execute("SET LOCAL statement_timeout = '10s'")
                hits = self.repo.fetch_release_hits(cur, lanes, source_ids, MAX_HIT_ROWS)
                paper_rows = self.repo.fetch_paper_nodes(cur, source_ids)

        nodes, comparisons = self._group_release_nodes(hits, coverage, overrides)
        papers = self._build_paper_nodes(paper_rows, overrides)

        hidden_count = sum(1 for n in nodes + papers if n["state"] == "hidden")
        if not include_hidden:
            nodes = [n for n in nodes if n["state"] != "hidden"]
            papers = [p for p in papers if p["state"] != "hidden"]
            # Comparison edges are built in _group_release_nodes, BEFORE this filter, and
            # carry the peer's title for rendering. Without pruning, hiding a node removes
            # it from the tree but leaves "compared with <that node's title>" on its peers -
            # so the one user-facing write in this feature visibly fails to hide anything.
            surviving = {n["node_key"] for n in nodes} | {p["node_key"] for p in papers}
            for node in nodes:
                node["comparisons"] = [
                    c for c in (node.get("comparisons") or [])
                    if c.get("node_key") in surviving
                ]
            comparisons = [
                c for c in comparisons
                if c.get("from") in surviving and c.get("to") in surviving
            ]

        vendors = self._group_by_vendor(nodes)
        first = coverage.get("first_post_at")
        last = coverage.get("last_post_at")
        weeks = 0
        if first and last:
            weeks = max(1, int((last - first).days // 7) + 1)

        payload = {
            "success": True,
            "scope": scope,
            "coverage": {
                "posts_in_scope": coverage["posts_in_scope"],
                "sources_in_scope": coverage["sources_in_scope"],
                "first_post_at": _iso(first),
                "last_post_at": _iso(last),
                "weeks_covered": weeks,
            },
            "vendors": vendors,
            "papers": papers,
            "stats": {
                "nodes": len(nodes),
                "lanes": len({n["lane_id"] for n in nodes}),
                "vendors": len(vendors),
                "comparisons": len(comparisons),
                "papers": len(papers),
            },
            "diagnostics": {
                "lanes_configured": len(lanes),
                "lanes_matched": len({n["lane_id"] for n in nodes}),
                "hidden_nodes": hidden_count,
                "briefings_available": briefing_count,
                "hit_rows": len(hits),
                "truncated": len(hits) >= MAX_HIT_ROWS,
            },
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "cached": False,
        }
        # Warms the drawer tier from the same build. nodes/papers here are post-filter and
        # post-comparison-prune, i.e. the exact dicts the tree walk in get_node would find.
        self._store(cache_key, generation, payload, nodes + papers)
        return payload

    def _describe_scope(self, folder_id: Optional[str],
                        source_ids: Optional[List[str]]) -> Dict[str, Any]:
        if not folder_id:
            return {"folder_id": None, "name": "All sources", "kind": None,
                    "source_count": None}
        folder = self.folders_service.get_folder(folder_id)
        if not folder:
            return {"folder_id": folder_id, "name": "Unknown folder", "kind": None,
                    "source_count": 0}
        return {"folder_id": folder_id, "name": folder.get("name"),
                "kind": folder.get("kind"),
                "source_count": len(source_ids or [])}

    def _group_release_nodes(self, hits: List[Dict[str, Any]],
                             coverage: Dict[str, Any],
                             overrides: Dict[str, Dict[str, Any]]):
        """hits -> nodes keyed by (lane_id, version_label), plus comparison edges."""
        buckets: Dict[Tuple[str, str], Dict[str, Any]] = {}
        by_post: Dict[str, set] = {}

        for hit in hits:
            version = (hit.get("version_label") or "").strip()
            if not version:
                continue
            key = (hit["lane_id"], version)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "lane_id": hit["lane_id"], "lane_name": hit["lane_name"],
                    "vendor": hit["vendor"] or hit["lane_name"],
                    "lane_order": hit["lane_order"], "version_label": version,
                    "evidence": [],
                }
                buckets[key] = bucket
            bucket["evidence"].append(hit)
            by_post.setdefault(hit["post_id"], set()).add(key)

        first_post = coverage.get("first_post_at")
        nodes: List[Dict[str, Any]] = []
        for key, bucket in buckets.items():
            evidence = sorted(bucket["evidence"], key=lambda h: h["published_at"])
            seen_sources = set()
            rows = []
            for index, hit in enumerate(evidence):
                if index == 0:
                    role = "announce"
                elif hit["source_id"] not in seen_sources:
                    role = "corroborate"
                else:
                    role = "mention"
                seen_sources.add(hit["source_id"])
                rows.append({
                    "post_id": hit["post_id"], "title": hit["post_title"],
                    "url": hit["post_url"], "published_at": _iso(hit["published_at"]),
                    "source_name": hit["source_name"], "role": role,
                })
            node_key = f"release:{bucket['lane_id']}:{bucket['version_label']}"
            override = overrides.get(node_key) or {}
            occurred = evidence[0]["published_at"]
            flags = []
            if len(seen_sources) == 1:
                flags.append("single_source")
            if first_post and (occurred - first_post).days <= 14:
                flags.append("chain_start_at_corpus_edge")
            nodes.append({
                "node_key": node_key,
                "kind": "release",
                "lane_id": bucket["lane_id"],
                "lane_name": bucket["lane_name"],
                "lane_order": bucket["lane_order"],
                "vendor": bucket["vendor"],
                "title": f"{bucket['lane_name']} {bucket['version_label']}",
                "custom_title": override.get("custom_title"),
                "version_label": bucket["version_label"],
                "version_sort": _version_sort(bucket["version_label"]),
                "occurred_on": _day(occurred),
                "last_seen_on": _day(evidence[-1]["published_at"]),
                "post_count": len(rows),
                "source_count": len(seen_sources),
                "state": override.get("state") or "active",
                "note": override.get("note"),
                "flags": flags,
                "evidence": rows,
                "comparisons": [],
            })

        index_by_key = {(n["lane_id"], n["version_label"]): n for n in nodes}

        # Retrospective flag: a node whose FIRST observation is later than that of a
        # HIGHER version in the same lane is a look-back mention, not a launch.
        # The chain still renders in version order; the flag is what stops the date
        # reading as a lie.
        by_lane: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            by_lane.setdefault(node["lane_id"], []).append(node)
        for lane_nodes in by_lane.values():
            lane_nodes.sort(key=lambda n: n["version_sort"])
            for i, node in enumerate(lane_nodes):
                if any(node["occurred_on"] > later["occurred_on"]
                       for later in lane_nodes[i + 1:]):
                    node["flags"].append("retrospective")

        # Cross-lane comparison edges: one post whose text names two different lanes.
        # This is "branching where a field forks", and it is free because we already
        # have every hit row in memory.
        comparisons: List[Dict[str, Any]] = []
        for post_id, keys in by_post.items():
            lanes_touched = {k[0] for k in keys}
            if len(lanes_touched) < 2:
                continue
            ordered = sorted(keys)
            for i, left in enumerate(ordered):
                for right in ordered[i + 1:]:
                    if left[0] == right[0]:
                        continue
                    a, b = index_by_key.get(left), index_by_key.get(right)
                    if not a or not b:
                        continue
                    evidence = next((e for e in a["evidence"] if e["post_id"] == post_id), None)
                    if not evidence:
                        continue
                    comparisons.append({"from": a["node_key"], "to": b["node_key"]})
                    for src, dst in ((a, b), (b, a)):
                        src["comparisons"].append({
                            "node_key": dst["node_key"],
                            "title": dst["custom_title"] or dst["title"],
                            "post_id": post_id,
                            "post_title": evidence["title"],
                            "published_at": evidence["published_at"],
                        })
        return nodes, comparisons

    def _build_paper_nodes(self, rows: List[Dict[str, Any]],
                           overrides: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        papers = []
        for row in rows:
            node_key = f"paper:{row['post_id']}"
            override = overrides.get(node_key) or {}
            papers.append({
                "node_key": node_key,
                "kind": "paper",
                "lane_id": None,
                "lane_name": row["bold_name"],
                "lane_order": 0,
                "vendor": None,
                "title": row["post_title"],
                "custom_title": override.get("custom_title"),
                "version_label": None,
                "version_sort": _day(row["published_at"]) or "",
                "occurred_on": _day(row["published_at"]),
                "last_seen_on": _day(row["published_at"]),
                "post_count": 1,
                "source_count": 1,
                "state": override.get("state") or "active",
                "note": override.get("note"),
                "flags": ["named_by_briefing"],
                "evidence": [{
                    "post_id": row["post_id"], "title": row["post_title"],
                    "url": row["post_url"], "published_at": _iso(row["published_at"]),
                    "source_name": row["source_name"], "role": "announce",
                }],
                "comparisons": [],
            })
        papers.sort(key=lambda p: (p["occurred_on"] or "", p["lane_name"]), reverse=True)
        return papers

    def _group_by_vendor(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Vendors are columns; lanes inside a vendor are the parallel chains.

        Anthropic forking into Opus / Sonnet / Haiku / Fable / Mythos is exactly the
        branch the user described, and it needs no inference at all - `vendor` is a
        column on milestone_lanes.
        """
        vendors: Dict[str, Dict[str, Any]] = {}
        for node in nodes:
            vendor = node["vendor"] or "Other"
            group = vendors.setdefault(vendor, {"vendor": vendor, "lanes": {},
                                                "latest": ""})
            lane = group["lanes"].setdefault(node["lane_id"], {
                "lane_id": node["lane_id"], "lane_name": node["lane_name"],
                "lane_order": node["lane_order"], "nodes": [],
            })
            lane["nodes"].append(node)
            if (node["occurred_on"] or "") > group["latest"]:
                group["latest"] = node["occurred_on"] or ""

        out = []
        for group in vendors.values():
            lanes = sorted(group["lanes"].values(),
                           key=lambda l: (l["lane_order"], l["lane_name"]))
            for lane in lanes:
                # NEWEST FIRST, ordered by version_sort - never by date. The tree
                # "goes up" as new releases land.
                lane["nodes"].sort(key=lambda n: n["version_sort"], reverse=True)
                lane["node_count"] = len(lane["nodes"])
            out.append({"vendor": group["vendor"], "latest_on": group["latest"],
                        "lanes": lanes,
                        "node_count": sum(l["node_count"] for l in lanes)})
        out.sort(key=lambda v: (v["latest_on"], v["node_count"]), reverse=True)
        return out
