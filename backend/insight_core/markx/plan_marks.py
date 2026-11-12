"""v10.14: the planners' marks (migration 0108, mx_plan_marks): a post a planner read and passed over is not read again
until its text changes.

The post planners (tasks.plan_posts for read and entities, ent42.plan for cite) page through
every post of the window that has no task of their kind. Some never get one: a post whose input repeats an asked one
(a media-only post, a repost: the same input is one task) and, for cite, a post the cue rule passes over (most posts).
Before, those were loaded, rendered and tried again on every call: with the windows at "everything" the cite planner
read ~110k posts a run (84 s on the server for nothing added), the read and entities leases ~2 s each.

A mark is (kind, guide, post) with why it was passed over (`same_input`, `not_cue`) and the post's text **stamp**: the
row versions of what tasks.load_posts reads (the post's row, its parts, its kept links) and the source's shown name and
kind, as the planner's query saw them. The planners skip a post whose mark's stamp is its stamp now; when any of those
rows changes the stamp differs and the post is read again exactly as before (and marked again if passed over again).
So a planner adds the same tasks as before, only without re-reading what cannot have changed. Marks are derived rows:
kept (keep everything), overwritten when a post is passed over again.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

SAME_INPUT, NOT_CUE, ONE_WINDOW = "same_input", "not_cue", "one_window"   # 0176: one_window (the windows planner)

# The post's text stamp, over alias `p` (posts): what load_posts reads. Row versions (xmin || ctid, as
# incremental.post_stamps) for the post, its parts and its links; the source's values themselves (its row is
# rewritten by the cadence job, which changes nothing a render shows).
STAMP = """(p.xmin::text || p.ctid::text
            || '|' || COALESCE((SELECT pp.xmin::text || pp.ctid::text FROM post_parts pp WHERE pp.post_id = p.id), '')
            || '|' || COALESCE((SELECT md5(concat_ws(chr(31), s.platform, s.handle_or_url, s.settings->>'display_name',
                                                     s.settings->>'name'))
                                  FROM sources s WHERE s.id = p.source_id), '')
            || '|' || COALESCE((SELECT string_agg(l.xmin::text || l.ctid::text, ',' ORDER BY l.position, l.target_url)
                                  FROM post_links l WHERE l.post_id = p.id), ''))"""


def unmarked(kind_param: str = "%(kind)s", guide_param: str = "%(guide)s") -> str:
    """A WHERE condition over alias `p`: no mark of this kind and guide holds for the post (none, or its stamp is old).
    A scalar subquery, so it is one primary-key probe a post and the stamp is computed only for a marked one (as an
    anti-join, a planner that thought the table empty compared every mark with every post: 56 s on the scale copy)."""
    return f"""NOT COALESCE((SELECT mk.stamp = {STAMP} FROM mx_plan_marks mk
                              WHERE mk.kind = {kind_param} AND mk.guide = {guide_param} AND mk.post_id = p.id), false)"""


def execute(cur: Any, sql: str, params: Any) -> List[Tuple]:
    """The planner's query's rows, read with JIT off, then JIT as it was: the stamp's subqueries make the planner's cost estimate
    pass jit_above_cost, and compiling took ~0.5 s of a 0.1 s query (folds.plan on the scale copy). A query that fails
    aborts the transaction, which ends the SET LOCAL with it."""
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
