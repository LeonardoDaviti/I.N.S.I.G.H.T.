"""
Repository for milestone_lanes / milestone_overrides plus the derived-tree queries.

Nothing here writes a milestone. `fetch_release_hits` and `fetch_paper_nodes` are the
whole derivation: one scan each, grouped in Python by MilestonesService.

Every output column is uniquely aliased on purpose - the local psycopg shim
(backend/psycopg/__init__.py) builds result tuples from row_to_json(...).values(),
so two columns named `id` collapse into one. Prod uses real psycopg; local does not.
No list/array parameter is passed anywhere in this file for the same reason
(shim _quote() JSON-encodes lists) - source scoping goes through a comma-joined
string and string_to_array.
"""
import re
from psycopg import Cursor
from typing import List, Dict, Any, Optional
from insight_core.logs.core.logger_config import get_component_logger


# Titles that are entirely "<package-slug> <version>". This is the single most
# important precision filter in the feature and it was tuned against live rows.
#
# Kills (verified, 40+ rows in the live corpus):
#   sqlite-utils 4.2.1 | llm-gemini 0.33 | datasette 1.0a38 | alchemy-utils 0.1a1
#   sdk: v0.117.1 | vertex-sdk: v0.19.3 | bedrock-sdk: v0.32.4 | v2.1.232 | v0.122.0
#   google-cloud-sdk-v0.0.7 | datasette-auth-tokens 0.4a13
# Keeps (verified - these are REAL milestones and a looser version of this regex
# ate them):
#   moonshotai/Kimi-K3            (no space, no leading v, no "-v")
#   deepseek-ai/DeepSeek-V4-Flash-0731  ("-v4" is followed by "-flash", not end-of-string)
#   DeepSeek V4 Pro 0813 (on OpenRouter)  (not anchored at $)
# The $ anchor is what separates the two sets. Do not drop it.
SLUG_RELEASE_BLOCKLIST = (
    r"^(v[0-9][0-9a-z.]*"
    r"|[a-z0-9][a-z0-9._/-]*[ :]+v?[0-9][0-9a-z.]*"
    r"|[a-z0-9][a-z0-9._/-]*-v[0-9][0-9a-z.]*)$"
)

# The text a lane pattern is matched against. title_pivot is lower(title) (NOT a
# translation), so patterns are lowercase and Cyrillic posts still match on the latin
# product name embedded in them.
HAYSTACK_SQL = (
    "coalesce(p.title_pivot, lower(p.title)) || ' ' || coalesce(p.summary_pivot, '')"
)


class MilestonesRepository:
    """Database access for milestone lanes, overrides, and the derived tree."""

    LANE_UPDATABLE_FIELDS = {"name", "vendor", "match_pattern", "lane_order", "enabled"}

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("repo_milestones")

    # ---------- lanes ----------

    def _lane_from_row(self, row: tuple) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "folder_id": str(row[1]) if row[1] else None,
            "name": row[2],
            "vendor": row[3],
            "match_pattern": row[4],
            "lane_order": int(row[5]) if row[5] is not None else 999,
            "enabled": bool(row[6]),
        }

    def list_lanes(self, cur: Cursor, folder_id: Optional[str],
                   enabled_only: bool = False) -> List[Dict[str, Any]]:
        """This folder's lanes, plus the global vocabulary unless the folder opts out.

        A curated track usually wants only its own lanes: the global AI-model lanes match
        real posts in any tech corpus, which fills a smart-glasses rail with GPT and Claude
        releases. folders.use_global_milestone_lanes (0018) controls that per folder and
        defaults TRUE, so unscoped and existing folders behave exactly as before.
        """
        query = """
            SELECT l.id            AS lane_id,
                   l.folder_id     AS lane_folder_id,
                   l.name          AS lane_name,
                   l.vendor        AS lane_vendor,
                   l.match_pattern AS lane_match_pattern,
                   l.lane_order    AS lane_lane_order,
                   l.enabled       AS lane_enabled
            FROM milestone_lanes l
            WHERE (
                    l.folder_id::text = %s
                    OR (
                      l.folder_id IS NULL
                      AND COALESCE(
                            (SELECT f.use_global_milestone_lanes FROM folders f
                              WHERE f.id::text = %s),
                            TRUE)
                    )
                  )
              AND (%s = false OR l.enabled)
            ORDER BY l.lane_order, l.name
        """
        scope = folder_id or ""
        cur.execute(query, (scope, scope, bool(enabled_only)))
        return [self._lane_from_row(r) for r in cur.fetchall()]

    def get_lane(self, cur: Cursor, lane_id: str) -> Optional[Dict[str, Any]]:
        cur.execute(
            """
            SELECT l.id AS lane_id, l.folder_id AS lane_folder_id, l.name AS lane_name,
                   l.vendor AS lane_vendor, l.match_pattern AS lane_match_pattern,
                   l.lane_order AS lane_lane_order, l.enabled AS lane_enabled
            FROM milestone_lanes l WHERE l.id = %s
            """,
            (lane_id,),
        )
        row = cur.fetchone()
        return self._lane_from_row(row) if row else None

    def insert_lane(self, cur: Cursor, folder_id: Optional[str], name: str,
                    vendor: Optional[str], match_pattern: str,
                    lane_order: int) -> Dict[str, Any]:
        cur.execute(
            """
            INSERT INTO milestone_lanes (folder_id, name, vendor, match_pattern, lane_order)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id AS lane_id, folder_id AS lane_folder_id, name AS lane_name,
                      vendor AS lane_vendor, match_pattern AS lane_match_pattern,
                      lane_order AS lane_lane_order, enabled AS lane_enabled
            """,
            (folder_id, name, vendor, match_pattern, lane_order),
        )
        lane = self._lane_from_row(cur.fetchone())
        self.logger.info("Created milestone lane %s -> %s", name, lane["id"])
        return lane

    def update_lane(self, cur: Cursor, lane_id: str,
                    fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates = {k: v for k, v in fields.items() if k in self.LANE_UPDATABLE_FIELDS}
        if not updates:
            return self.get_lane(cur, lane_id)
        set_clause = ", ".join(f"{key} = %s" for key in updates)
        values = list(updates.values()) + [lane_id]
        cur.execute(
            f"""
            UPDATE milestone_lanes SET {set_clause}, updated_at = now()
            WHERE id = %s
            RETURNING id AS lane_id, folder_id AS lane_folder_id, name AS lane_name,
                      vendor AS lane_vendor, match_pattern AS lane_match_pattern,
                      lane_order AS lane_lane_order, enabled AS lane_enabled
            """,
            values,
        )
        row = cur.fetchone()
        return self._lane_from_row(row) if row else None

    def delete_lane(self, cur: Cursor, lane_id: str) -> bool:
        cur.execute("DELETE FROM milestone_lanes WHERE id = %s RETURNING id AS lane_id",
                    (lane_id,))
        return cur.fetchone() is not None

    def validate_pattern(self, cur: Cursor, pattern: str) -> Optional[str]:
        """Compile the pattern with the REAL engine. Returns an error string or None.

        Python's `re` is not Postgres ARE - \\m and \\M are valid here and a syntax
        error in `re`. Asking Postgres is the only honest check.
        """
        if not pattern or len(pattern) > 400:
            return "Pattern must be 1-400 characters"
        try:
            cur.execute("SELECT ('claude opus 5' ~ %s) AS pattern_ok", (pattern,))
            cur.fetchone()
        except Exception as exc:  # noqa: BLE001 - the message is the product here
            return f"Invalid regex: {exc}"
        # substring(text FROM pattern) does NOT raise on 0 or 2+ groups - it returns the
        # whole match or group 1 - so the DB probe below can never enforce the rule the
        # schema states. Count the groups ourselves. Without this, '\\mgemini[ -]?[0-9]+'
        # (0 groups) yields version_label 'gemini 3', producing node titles like
        # "Gemini gemini 3" and a version_sort that orders the chain arbitrarily.
        if len(re.findall(r"(?<!\\)\((?!\?)", pattern)) != 1:
            return "Pattern must contain exactly one capturing group, e.g. ([0-9]+(?:\\.[0-9]+)?)"
        try:
            cur.execute(
                "SELECT substring('claude opus 5' from %s) AS pattern_capture", (pattern,)
            )
            cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            return f"Invalid capture group: {exc}"
        return None

    # ---------- overrides ----------

    def list_overrides(self, cur: Cursor) -> Dict[str, Dict[str, Any]]:
        cur.execute(
            """
            SELECT o.node_key     AS override_node_key,
                   o.state        AS override_state,
                   o.custom_title AS override_custom_title,
                   o.note         AS override_note
            FROM milestone_overrides o
            """
        )
        return {
            r[0]: {"state": r[1], "custom_title": r[2], "note": r[3]}
            for r in cur.fetchall()
        }

    def upsert_override(self, cur: Cursor, node_key: str, state: Optional[str],
                        custom_title: Optional[str], note: Optional[str]) -> Dict[str, Any]:
        cur.execute(
            """
            INSERT INTO milestone_overrides (node_key, state, custom_title, note)
            VALUES (%s, coalesce(%s, 'active'), %s, %s)
            ON CONFLICT (node_key) DO UPDATE SET
              state        = coalesce(%s, milestone_overrides.state),
              custom_title = CASE WHEN %s THEN EXCLUDED.custom_title
                                  ELSE milestone_overrides.custom_title END,
              note         = CASE WHEN %s THEN EXCLUDED.note
                                  ELSE milestone_overrides.note END,
              updated_at   = now()
            RETURNING node_key AS override_node_key, state AS override_state,
                      custom_title AS override_custom_title, note AS override_note
            """,
            (node_key, state, custom_title, note,
             state, custom_title is not None, note is not None),
        )
        row = cur.fetchone()
        return {"node_key": row[0], "state": row[1], "custom_title": row[2], "note": row[3]}

    # ---------- the derivation ----------

    def _scope_predicate(self, source_ids: Optional[List[str]]) -> str:
        """SQL fragment + one %s param. Empty list is NOT the same as None."""
        if source_ids is None:
            return "TRUE"
        return "p.source_id::text = ANY (string_to_array(%s, ','))"

    def fetch_release_hits(self, cur: Cursor, lanes: List[Dict[str, Any]],
                           source_ids: Optional[List[str]],
                           max_rows: int) -> List[Dict[str, Any]]:
        """One row per (lane, post) hit. Grouping happens in Python.

        source_ids is None  -> every non-arXiv source (the default landing scope).
        source_ids is []    -> nothing. Returns [] without touching the DB.
        """
        if not lanes:
            return []
        if source_ids is not None and not source_ids:
            return []

        # Lanes go in as a parameterised VALUES list: 5 placeholders per lane, no arrays.
        # The columns are explicitly cast because an all-unknown VALUES list resolves to
        # text, which would return lane_order as a string and sort '100' before '20'.
        lane_values = ", ".join(["(%s, %s, %s, %s, %s)"] * len(lanes))
        params: List[Any] = []
        for lane in lanes:
            params.extend([
                lane["id"], lane["name"], lane["vendor"] or "",
                lane["match_pattern"], int(lane["lane_order"]),
            ])
        params.append(SLUG_RELEASE_BLOCKLIST)
        scope_sql = self._scope_predicate(source_ids)
        if source_ids is not None:
            params.append(",".join(source_ids))
        params.append(int(max_rows))

        query = f"""
            WITH lane AS (
              SELECT v.c1::text AS lane_id,
                     v.c2::text AS lane_name,
                     v.c3::text AS lane_vendor,
                     v.c4::text AS lane_pattern,
                     v.c5::int  AS lane_order
              FROM (VALUES {lane_values}) AS v (c1, c2, c3, c4, c5)
            ),
            scoped AS (
              SELECT p.id           AS post_id,
                     p.source_id    AS post_source_id,
                     p.title        AS post_title,
                     p.url          AS post_url,
                     p.published_at AS post_published_at,
                     coalesce(s.settings->>'display_name', s.handle_or_url) AS source_name,
                     {HAYSTACK_SQL} AS post_haystack
              FROM posts p
              JOIN sources s ON s.id = p.source_id
              WHERE p.published_at IS NOT NULL
                AND s.handle_or_url NOT ILIKE '%%arxiv%%'
                AND coalesce(p.title_pivot, lower(p.title)) !~ %s
                AND {scope_sql}
            )
            SELECT lane.lane_id      AS hit_lane_id,
                   lane.lane_name    AS hit_lane_name,
                   lane.lane_vendor  AS hit_lane_vendor,
                   lane.lane_order   AS hit_lane_order,
                   substring(scoped.post_haystack from lane.lane_pattern) AS hit_version,
                   scoped.post_id           AS hit_post_id,
                   scoped.post_title        AS hit_post_title,
                   scoped.post_url          AS hit_post_url,
                   scoped.post_published_at AS hit_post_published_at,
                   scoped.post_source_id    AS hit_post_source_id,
                   scoped.source_name       AS hit_source_name
            FROM scoped
            JOIN lane ON scoped.post_haystack ~ lane.lane_pattern
            WHERE substring(scoped.post_haystack from lane.lane_pattern) !~ '^0'
            ORDER BY lane.lane_order, scoped.post_published_at
            LIMIT %s
        """
        cur.execute(query, params)
        return [
            {
                "lane_id": str(r[0]), "lane_name": r[1], "vendor": r[2] or None,
                "lane_order": int(r[3]) if r[3] is not None else 999,
                "version_label": r[4],
                "post_id": str(r[5]), "post_title": r[6], "post_url": r[7],
                "published_at": r[8], "source_id": str(r[9]), "source_name": r[10],
            }
            for r in cur.fetchall()
        ]

    def fetch_paper_nodes(self, cur: Cursor,
                          source_ids: Optional[List[str]]) -> List[Dict[str, Any]]:
        """arXiv papers the daily briefing chose to name in bold.

        Zero marginal LLM cost: briefing_service already generated and paid for
        briefings.content. This is regexp_matches over the stored rows.

        The `LIKE name || ':%%'` prefix guard is what takes this from 16 rows with 3
        false positives ('Modal' from "The Modal Ceiling") to 13 rows with 0. The bold
        capture class excludes % and _, so LIKE needs no escaping - which is why this
        is LIKE and not the regexp_replace escaping dance.

        subject_type is 'daily_briefing'. 'daily' returns 0 rows.
        """
        if source_ids is not None and not source_ids:
            return []
        scope_sql = self._scope_predicate(source_ids)
        params: List[Any] = []
        if source_ids is not None:
            params.append(",".join(source_ids))

        query = f"""
            WITH bold AS (
              SELECT DISTINCT trim(
                (regexp_matches(b.content, '\\*\\*([A-Za-z][A-Za-z0-9 .+/-]{{2,40}})\\*\\*', 'g'))[1]
              ) AS bold_name
              FROM briefings b
              WHERE b.subject_type = 'daily_briefing'
            )
            SELECT bold.bold_name        AS paper_bold_name,
                   p.id                  AS paper_post_id,
                   p.title               AS paper_post_title,
                   p.url                 AS paper_post_url,
                   p.published_at        AS paper_published_at,
                   coalesce(s.settings->>'display_name', s.handle_or_url) AS paper_source_name
            FROM bold
            JOIN posts p ON (p.title LIKE bold.bold_name || ':%%'
                          OR p.title LIKE bold.bold_name || ',%%')
            JOIN sources s ON s.id = p.source_id
            WHERE s.handle_or_url ILIKE '%%arxiv%%'
              AND p.published_at IS NOT NULL
              AND {scope_sql}
            ORDER BY p.published_at DESC, bold.bold_name
        """
        cur.execute(query, params)
        return [
            {
                "bold_name": r[0], "post_id": str(r[1]), "post_title": r[2],
                "post_url": r[3], "published_at": r[4], "source_name": r[5],
            }
            for r in cur.fetchall()
        ]

    def scope_coverage(self, cur: Cursor,
                       source_ids: Optional[List[str]]) -> Dict[str, Any]:
        """Post count / date span of the scope. Drives the empty state and the
        'N weeks of history' header line, which is the honest answer to the
        'this should go back years' expectation."""
        if source_ids is not None and not source_ids:
            return {"posts_in_scope": 0, "sources_in_scope": 0,
                    "first_post_at": None, "last_post_at": None}
        scope_sql = self._scope_predicate(source_ids)
        params: List[Any] = []
        if source_ids is not None:
            params.append(",".join(source_ids))
        cur.execute(
            f"""
            SELECT count(*)                     AS coverage_posts,
                   count(DISTINCT p.source_id)  AS coverage_sources,
                   min(p.published_at)          AS coverage_first,
                   max(p.published_at)          AS coverage_last
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE p.published_at IS NOT NULL
              AND s.handle_or_url NOT ILIKE '%%arxiv%%'
              AND {scope_sql}
            """,
            params,
        )
        row = cur.fetchone()
        return {
            "posts_in_scope": int(row[0] or 0),
            "sources_in_scope": int(row[1] or 0),
            "first_post_at": row[2],
            "last_post_at": row[3],
        }

    def count_daily_briefings(self, cur: Cursor) -> int:
        cur.execute(
            "SELECT count(*) AS briefing_count FROM briefings WHERE subject_type = 'daily_briefing'"
        )
        row = cur.fetchone()
        return int(row[0] or 0)

    def preview_pattern(self, cur: Cursor, pattern: str,
                        source_ids: Optional[List[str]], limit: int = 25) -> Dict[str, Any]:
        """FREE dry-run of a lane pattern. No writes, no LLM, no tokens.

        This is the curation loop: edit a regex, see 'GPT: 24 posts / 4 sources ->
        5 versions' before committing it. Without this the lanes table is a config
        file; with it, it is a tuning surface.

        Parameter order: blocklist, pattern (match), [source csv], pattern (capture), limit.
        """
        if source_ids is not None and not source_ids:
            return {"total_hits": 0, "versions": [], "samples": []}
        scope_sql = self._scope_predicate(source_ids)
        params: List[Any] = [SLUG_RELEASE_BLOCKLIST, pattern]
        if source_ids is not None:
            params.append(",".join(source_ids))
        params.extend([pattern, pattern, int(limit)])  # capture, partition-capture, limit
        cur.execute(
            f"""
            WITH scoped AS (
              SELECT p.id AS post_id, p.title AS post_title,
                     p.published_at AS post_published_at,
                     coalesce(s.settings->>'display_name', s.handle_or_url) AS source_name,
                     {HAYSTACK_SQL} AS post_haystack
              FROM posts p JOIN sources s ON s.id = p.source_id
              WHERE p.published_at IS NOT NULL
                AND s.handle_or_url NOT ILIKE '%%arxiv%%'
                AND coalesce(p.title_pivot, lower(p.title)) !~ %s
                AND {HAYSTACK_SQL} ~ %s
                AND {scope_sql}
            )
            SELECT scoped.post_id AS preview_post_id,
                   scoped.post_title AS preview_post_title,
                   scoped.post_published_at AS preview_published_at,
                   scoped.source_name AS preview_source_name,
                   substring(scoped.post_haystack from %s) AS preview_version,
                   -- Window functions are evaluated BEFORE LIMIT, so this is the true
                   -- match count. len(rows) would report the page size (25) instead,
                   -- which defeats the whole point of a preview: the user is judging a
                   -- regex by how many posts it matches.
                   count(*) OVER () AS preview_total,
                   -- Same reason: the version histogram must describe the whole match
                   -- set, not the 25 most recent rows.
                   count(*) OVER (PARTITION BY substring(scoped.post_haystack from %s))
                       AS preview_version_total
            FROM scoped ORDER BY scoped.post_published_at DESC LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
        total_hits = int(rows[0][5]) if rows else 0
        versions: Dict[str, int] = {}
        samples = []
        for r in rows:
            ver = r[4]
            versions[ver] = int(r[6])
            samples.append({
                "post_id": str(r[0]), "title": r[1],
                "published_at": r[2].isoformat() if hasattr(r[2], "isoformat") else r[2],
                "source_name": r[3], "version_label": ver,
            })
        return {
            "total_hits": total_hits,
            "returned": len(rows),
            "versions": [{"version_label": k, "post_count": v}
                         for k, v in sorted(versions.items())],
            "samples": samples,
        }
