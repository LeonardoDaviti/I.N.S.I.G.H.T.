"""Each source's post statistics, kept (issue 0195, migration 0131).

Source health, the Ingestion tab's overview and /api/status read per source: how many posts, its newest post, the
newest page reads, whether its newest paid post was a teaser, where its newest posts moved, and the corpus' freshness.
They were six correlated subqueries per source over posts on every request. Here they are kept in source_post_stats
and read; a source whose posts changed since its last refresh (a row in source_post_stats_changes, written by the
posts triggers, whoever wrote the posts) or that was never kept is read live by the very same expressions, so a read
is never stale. `refresh` (after each ingestion run) keeps the changed sources again.

`stats_sql()` is the one place the statistics are defined: the refresh and the live read both use it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from psycopg import Cursor

from insight_core.db.repo_posts import PAGE_READ_KEY
from insight_core.markx import pairing
from insight_core.utils.post_fields import MOVED_KEY

PAGE_READS_IN_HEALTH = 8    # the newest page-read posts source health sums (issue 0032)
MOVED_NEWEST = 10           # the newest posts whose pages' moves say a source moved (issue 0108)

# Session-scoped advisory key: one refresh at a time (a second skips; the rows stay read live until the next).
REFRESH_LOCK = 0x5050_0195

# Each kept column, as the expression over the source `s` that defines it (read live while a source is changed).
COLUMNS: Dict[str, str] = {
    "post_count": "(SELECT count(*) FROM posts p WHERE p.source_id = s.id)",
    "last_post_at": f"""(SELECT max({pairing.ordinary_date('p')}) FROM posts p
                         WHERE p.source_id = s.id)""",
    "page_reads": f"""(SELECT COALESCE(jsonb_agg(r.page_read ORDER BY r.fetched_at DESC), '[]'::jsonb)
                         FROM (SELECT p.metadata -> '{PAGE_READ_KEY}' AS page_read, p.fetched_at
                                 FROM posts p
                                WHERE p.source_id = s.id AND p.metadata ? '{PAGE_READ_KEY}'
                                ORDER BY p.fetched_at DESC LIMIT {PAGE_READS_IN_HEALTH}) r)""",
    "paid_preview": """(SELECT (p.metadata ->> 'paywalled')::boolean FROM posts p
                         WHERE p.source_id = s.id AND p.metadata ->> 'audience' = 'only_paid'
                         ORDER BY p.fetched_at DESC LIMIT 1)""",
    "moved": f"""(SELECT array_agg(r.moved) FROM (SELECT p.metadata ->> '{MOVED_KEY}' AS moved FROM posts p
                   WHERE p.source_id = s.id
                   ORDER BY {pairing.ordinary_date('p')} DESC, p.id DESC
                   LIMIT {MOVED_NEWEST}) r)""",
    "latest_at": f"(SELECT max({pairing.ix_date('p')}) FROM posts p WHERE p.source_id = s.id)",
    "oldest_at": f"(SELECT min({pairing.ix_date('p')}) FROM posts p WHERE p.source_id = s.id)",
    "latest_fetch_at": "(SELECT max(p.fetched_at) FROM posts p WHERE p.source_id = s.id)",
}

# A source read live: never kept, or its posts changed since (st is its source_post_stats row, or NULL).
_LIVE = "(st.source_id IS NULL OR EXISTS (SELECT 1 FROM source_post_stats_changes c WHERE c.source_id = s.id))"


def stats_sql(where: str = "") -> str:
    """SELECT source_id, <every kept column> for each source (`s`), each column kept or, for a changed or never kept
    source, read live (a CASE: the live subquery runs only for those). `where` filters the sources (`s`)."""
    picked = ",\n       ".join(f"CASE WHEN {_LIVE} THEN {expr} ELSE st.{name} END AS {name}"
                               for name, expr in COLUMNS.items())
    return f"""SELECT s.id AS source_id,
       {picked}
  FROM sources s
  LEFT JOIN source_post_stats st ON st.source_id = s.id
  {where}"""


def refresh(cur: Cursor) -> Optional[int]:
    """Keep the changed and the never kept sources again; the number kept, or None when another refresh runs.

    One statement, so one snapshot: the change rows it takes are exactly those whose posts it reads, and a change
    committed after it stays logged (read live until the next refresh). The caller commits."""
    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (REFRESH_LOCK,))
    if not cur.fetchone()[0]:
        return None
    names = ", ".join(COLUMNS)
    cur.execute(f"""
        WITH taken AS (DELETE FROM source_post_stats_changes RETURNING source_id),
             due AS (SELECT source_id FROM taken
                     UNION SELECT s.id FROM sources s
                      WHERE NOT EXISTS (SELECT 1 FROM source_post_stats st WHERE st.source_id = s.id))
        INSERT INTO source_post_stats (source_id, {names}, refreshed_at)
        SELECT s.id, {", ".join(COLUMNS.values())}, now()
          FROM sources s WHERE s.id IN (SELECT source_id FROM due)
        ON CONFLICT (source_id) DO UPDATE SET {", ".join(f"{n} = EXCLUDED.{n}" for n in COLUMNS)},
                                              refreshed_at = EXCLUDED.refreshed_at""")
    return cur.rowcount or 0


def corpus(cur: Cursor) -> Dict[str, Any]:
    """The corpus over every source's statistics: {total_posts, latest_at, oldest_at, latest_fetch_at}."""
    cur.execute(f"""SELECT COALESCE(sum(x.post_count), 0), max(x.latest_at), min(x.oldest_at), max(x.latest_fetch_at)
                      FROM ({stats_sql()}) x""")
    total, latest, oldest, latest_fetch = cur.fetchone()
    return {"total_posts": int(total or 0), "latest_at": latest, "oldest_at": oldest, "latest_fetch_at": latest_fetch}


def opened_counts(cur: Cursor, source_ids: Optional[Sequence[str]] = None) -> Dict[str, int]:
    """{source_id: its posts the owner opened} (repo_fetch_state.OPENED_POST_SQL's rule, counted from the few opened
    posts up rather than per source over every post; not kept: reading changes it)."""
    where, params = "", {}
    if source_ids is not None:
        where, params = "AND p.source_id = ANY(%(ids)s::uuid[])", {"ids": [str(s) for s in source_ids]}
    cur.execute(f"""
        SELECT p.source_id::text, count(*) FROM posts p
         WHERE p.id IN (SELECT i.post_id FROM post_interactions i
                         WHERE i.interaction_type IN ('opened', 'reading_session')
                        UNION
                        SELECT r.post_id FROM post_reader_state r
                         WHERE r.later_at IS NOT NULL OR r.starred_at IS NOT NULL OR r.resume_block IS NOT NULL)
           {where}
         GROUP BY 1""", params)
    return {sid: int(n) for sid, n in cur.fetchall()}
