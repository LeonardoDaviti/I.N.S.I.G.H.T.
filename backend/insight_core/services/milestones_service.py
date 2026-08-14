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
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple

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

_CACHE: Dict[Tuple, Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()

_SAFE_NAME = re.compile(r"^[\w .+/&-]{1,60}$")


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
        with _CACHE_LOCK:
            _CACHE.clear()

    def get_tree(self, folder_id: Optional[str] = None,
                 include_hidden: bool = False) -> Dict[str, Any]:
        cache_key = (folder_id or "", bool(include_hidden))
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and now - cached[0] < CACHE_TTL_SECONDS:
                return dict(cached[1], cached=True)

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
        with _CACHE_LOCK:
            _CACHE[cache_key] = (now, payload)
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
