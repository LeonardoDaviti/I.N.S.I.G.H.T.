"""The planners' marks (mx_plan_marks): a post a planner read and passed over is not read again until its text
changes.

A mark is (kind, guide, post) with why it was passed over (`same_input`, `not_cue`, `one_window`) and the post's text
**stamp** (STAMP: the version of what tasks.load_posts reads) as the planner's query saw it. The planners skip a post
whose mark's stamp is its stamp now; when any of those rows changes, the post is read again exactly as before. So a
planner adds the same tasks, without re-reading what cannot have changed. Marks are derived rows, overwritten when a
post is passed over again.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

SAME_INPUT, NOT_CUE, ONE_WINDOW = "same_input", "not_cue", "one_window"   # one_window: the windows planner

# the stored page a link post shares (story_originals kind `linked`), over a post id expression: tasks.load_posts reads
# a link post with no words of its own with that page's text.
LINKED_PAGE = """SELECT o.post_id FROM post_parts lp JOIN story_originals o
                   ON o.kind = 'linked' AND o.url = lp.link_target AND o.post_id IS NOT NULL
                WHERE lp.post_id = {post} AND lp.link_kind = 'page' LIMIT 1"""

# The post's text stamp, over alias `p` (posts): what load_posts reads, as one version (mx_post_stamps.n, moved by
# triggers on every write of the post's row, its parts, its kept links, its source's shown name and kind, and the
# `linked` original its page is): one primary-key probe of a narrow table. NULL for a post with no row (never marked).
STAMP = "(SELECT ps.n::text FROM mx_post_stamps ps WHERE ps.post_id = p.id)"


def unmarked(kind_param: str = "%(kind)s", guide_param: str = "%(guide)s") -> str:
    """A WHERE condition over alias `p`: no mark of this kind and guide holds for the post (none, or its stamp is old).
    A scalar subquery, so one primary-key probe a post, the stamp computed only for a marked one (an anti-join could
    compare every mark with every post)."""
    return f"""NOT COALESCE((SELECT mk.stamp = {STAMP} FROM mx_plan_marks mk
                              WHERE mk.kind = {kind_param} AND mk.guide = {guide_param} AND mk.post_id = p.id), false)"""


def unread(asks: str, kind_param: str = "%(kind)s", guide_param: str = "%(guide)s") -> str:
    """A WHERE condition over alias `p` that narrows a planner's posts before any is read: the post is one `asks` holds
    for (a condition over `q.id`: the planner's own "no task of mine yet") and no mark of this kind and guide holds for
    it. Both over narrow tables and indexes, so a window whose posts all have their task, or are passed over, is found
    without reading a post row. An array of ids (`p.id = ANY(ARRAY(...))`), not `IN (...)`: the planner's estimate would
    walk the date index over every post of the window; the array is primary-key probes, so only the posts left are read
    (measured: plan/issues/0277). A guide with no task yet reads every post for its first pages."""
    return f"""p.id = ANY(ARRAY(SELECT q.id FROM posts q
                                WHERE {asks}
                                  AND NOT EXISTS (SELECT 1 FROM mx_plan_marks mk
                                                    JOIN mx_post_stamps ps ON ps.post_id = mk.post_id
                                                   WHERE mk.kind = {kind_param} AND mk.guide = {guide_param}
                                                     AND mk.post_id = q.id AND mk.stamp = ps.n::text)))"""


def left(asks: str, kind_param: str = "%(kind)s", guide_param: str = "%(guide)s") -> str:
    """`unread`'s narrowing for a planner whose own question is a set of post ids (`asks`: a query of one uuid column,
    e.g. its tasks' ids EXCEPT its kind's), over alias `p`: the ids asked, EXCEPT the posts marked at their current
    stamp, as an array of primary-key probes. Set operations, so no plan rests on the estimate of the marks' stamp
    join."""
    return f"""p.id = ANY(ARRAY(({asks})
                                EXCEPT SELECT mk.post_id FROM mx_plan_marks mk
                                         JOIN mx_post_stamps ps ON ps.post_id = mk.post_id AND mk.stamp = ps.n::text
                                        WHERE mk.kind = {kind_param} AND mk.guide = {guide_param}))"""


def execute(cur: Any, sql: str, params: Any) -> List[Tuple]:
    """The planner's query's rows, read with JIT off, then JIT as it was: the stamp's subqueries push the cost estimate
    past jit_above_cost, and compiling costs more than the query. A query that fails aborts the transaction, which ends
    the SET LOCAL with it."""
    cur.execute("SELECT current_setting('jit')")
    was = cur.fetchone()[0]
    cur.execute("SET LOCAL jit = off")
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.execute("SELECT set_config('jit', %s, true)", (was,))
    return rows


def mark(cur: Any, kind: str, guide: str, rows: Iterable[Tuple[str, str, Optional[str]]]) -> int:
    """Mark these posts passed over: rows of (post id, why, stamp as the planner's query read it). How many."""
    rows = [(str(p), why, stamp) for p, why, stamp in rows if stamp is not None]
    if not rows:
        return 0
    cur.execute("""INSERT INTO mx_plan_marks (kind, guide, post_id, why, stamp)
                   SELECT %s, %s, x.p, x.why, x.stamp
                     FROM unnest(%s::uuid[], %s::text[], %s::text[]) AS x(p, why, stamp)
                   ON CONFLICT (kind, guide, post_id) DO UPDATE
                      SET why = EXCLUDED.why, stamp = EXCLUDED.stamp, marked_at = now()""",
                (kind, guide, [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]))
    return len(rows)
