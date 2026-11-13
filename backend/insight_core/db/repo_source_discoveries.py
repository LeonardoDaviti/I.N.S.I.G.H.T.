"""What one source discovered (issue 0143, section 5): read from what Discover and Mark X already store, no write.

- **Sites and accounts it linked that Discover lists** (followed or not): Discover's kept counts (system_settings
  `discover_counts`, issue 0067) name the sources linking each key; this source's links to it (post_links ->
  discover_addresses) give how many addresses and since when. Each is open, followed or hidden as Discover says
  (discover_open).
- **Sources you followed after it linked them** (inferred: nothing records where a follow came from): a key whose
  link INSIGHT stored from it (the post's fetch) before the source that follows that site or account was added.
- **Pages and originals collected because of it** (0123's collect, 0114's linked fetch, 0138's originals:
  story_originals): an original whose address one of its posts links, or whose story holds one of its posts.
- **Entities it named first** (Mark X, `mx_mentions_now`): the entities its posts mention whose earliest mention in
  any post is one of its own (merges and the owner's splits not resolved: the identity a mention was linked to).

Sorted as the source page shows them: what you followed first, then the most voices.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from psycopg import Cursor
from insight_core.markx import pairing

LIMIT = 50

_LINKED = f"""
SELECT d.key, min(d.site), bool_or(d.platform), count(DISTINCT d.url),
       count(DISTINCT d.url) FILTER (WHERE d.article), min({pairing.ix_date('p')}), min(p.fetched_at)
FROM posts p
JOIN post_links pl ON pl.post_id = p.id AND NOT pl.boilerplate
JOIN discover_addresses d ON d.url = pl.target_url   -- one row an address (whichever rules wrote it)
WHERE p.source_id = %(source)s AND d.key IS NOT NULL
GROUP BY d.key
"""

_ORIGINALS = """
SELECT o.kind, o.url, o.outcome, o.post_id::text, o.story_id::text, o.asked_at, t.title
FROM story_originals o
LEFT JOIN posts t ON t.id = o.post_id
WHERE EXISTS (SELECT 1 FROM post_links pl JOIN posts p ON p.id = pl.post_id
              WHERE pl.target_url = o.url AND p.source_id = %(source)s)
   OR (o.story_id IS NOT NULL AND EXISTS (SELECT 1 FROM story_posts sp JOIN posts p ON p.id = sp.post_id
                                          WHERE sp.story_id = o.story_id AND p.source_id = %(source)s))
ORDER BY o.asked_at DESC
LIMIT %(limit)s
"""

_FIRST_NAMED = f"""
WITH mine AS (
  SELECT DISTINCT m.entity_id FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
  WHERE p.source_id = %(source)s AND m.entity_id IS NOT NULL),
firsts AS (
  SELECT DISTINCT ON (m.entity_id) m.entity_id, m.post_id, p.source_id, {pairing.ix_date('p')} AS at
  FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
  WHERE m.entity_id IN (SELECT entity_id FROM mine)
  ORDER BY m.entity_id, {pairing.ix_date('p')}, p.id)
SELECT e.id::text, e.name, e.type, f.post_id::text, f.at, t.title
FROM firsts f JOIN mx_entities e ON e.id = f.entity_id LEFT JOIN posts t ON t.id = f.post_id
WHERE f.source_id = %(source)s AND e.status <> 'not_entity'
ORDER BY f.at DESC
LIMIT %(limit)s
"""


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


def _exists(cur: Cursor, relation: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (relation,))
    return bool(cur.fetchone()[0])


def source_discoveries(cur: Cursor, source_id: str, *, limit: int = LIMIT) -> Dict[str, Any]:
    """{sites, followed_from_here, originals, entities, counts} for one source (see the module docstring).
    LookupError when the source does not exist."""
    from insight_core.db.repo_discover import DiscoverRepository
    from insight_core.db.repo_stories import SourceFacts, StoriesRepository
    from insight_core.utils.discover_rules import discover_open

    cur.execute("SELECT id FROM sources WHERE id = %s", (source_id,))
    if cur.fetchone() is None:
        raise LookupError(f"Source {source_id} not found")
    kept = DiscoverRepository.kept(cur) or {}
    listed = {found["key"]: found for found in kept.get("found") or []
              if isinstance(found, dict) and any(str(pair[0]) == source_id for pair in found.get("sources") or [])}
    cur.execute(_LINKED, {"source": source_id})
    linked = {row[0]: row for row in cur.fetchall()}

    facts = SourceFacts(cur)
    followed, accounts = facts.followed(), facts.followed_accounts()
    hidden = StoriesRepository.hidden(cur)
    cur.execute("SELECT id::text, created_at, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) "
                "FROM sources")
    added = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    def follower(key: str, site: str, platform: bool) -> Optional[str]:
        """The source that follows this key (its account, or its site), other than this one."""
        for other in added:
            if other == source_id:
                continue
            if platform and facts.account.get(other) == key:
                return other
            if not platform and site and site in (facts.site.get(other), facts.handle_site.get(other)):
                return other
        return None

    sites: List[Dict[str, Any]] = []
    followed_here: List[Dict[str, Any]] = []
    for key, found in listed.items():
        row = linked.get(key)
        site = row[1] if row else key.split("/", 1)[0]
        platform = bool(row[2]) if row else "/" in key
        state = ("hidden" if key in hidden or site in hidden
                 else "open" if discover_open(key, site, platform, followed=followed, hidden=hidden,
                                              followed_accounts=accounts) else "followed")
        first_linked = row[5] if row else None
        entry = {"key": key, "site": site, "platform": platform, "state": state,
                 "voices": len(found.get("voices") or []), "articles": int(row[4]) if row else None,
                 "addresses": int(row[3]) if row else None, "first_linked": _iso(first_linked),
                 "followed_source": None}
        if state == "followed" and (other := follower(key, site, platform)) is not None:
            created, name = added[other]
            entry["followed_source"] = {"id": other, "name": name, "added_at": _iso(created)}
            # Followed after INSIGHT first stored this source's link to it (its fetch, not the post's date: an
            # archive stores old posts late).
            first_seen = row[6] if row else None
            if first_seen is not None and created is not None and created > first_seen:
                followed_here.append({**entry["followed_source"], "key": key})
        sites.append(entry)
    rank = {"followed": 0, "open": 1, "hidden": 2}
    sites.sort(key=lambda s: (rank[s["state"]], -s["voices"], -(s["articles"] or 0), s["key"]))

    originals: List[Dict[str, Any]] = []
    if _exists(cur, "story_originals"):
        cur.execute(_ORIGINALS, {"source": source_id, "limit": limit})
        originals = [{"kind": r[0], "url": r[1], "outcome": r[2], "post_id": r[3], "story_id": r[4],
                      "asked_at": _iso(r[5]), "title": r[6]} for r in cur.fetchall()]

    entities: List[Dict[str, Any]] = []
    if _exists(cur, "mx_mentions_now") and _exists(cur, "mx_entities"):
        cur.execute(_FIRST_NAMED, {"source": source_id, "limit": limit})
        entities = [{"id": r[0], "name": r[1], "type": r[2], "post_id": r[3], "at": _iso(r[4]), "post_title": r[5]}
                    for r in cur.fetchall()]

    return {
        "source_id": source_id,
        "sites": sites[:limit],
        "followed_from_here": followed_here,
        "originals": originals,
        "entities": entities,
        "counts": {"sites": len(sites), "followed": sum(1 for s in sites if s["state"] == "followed"),
                   "open": sum(1 for s in sites if s["state"] == "open"), "originals": len(originals),
                   "entities": len(entities), "followed_from_here": len(followed_here)},
        # Discover has counted (its story job keeps the counts): before that, no site can be listed.
        "discover_counted": bool(kept),
    }
