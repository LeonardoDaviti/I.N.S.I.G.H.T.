"""v10.14: the planners' marks (migration 0108, mx_plan_marks): a post a planner read and passed over is not read again
until its text changes.

The post planners (tasks.plan_posts for read and entities, ent42.plan for cite) page through
every post of the window that has no task of their kind. Some never get one: a post whose input repeats an asked one
(a media-only post, a repost: the same input is one task) and, for cite, a post the cue rule passes over (most posts).
Before, those were loaded, rendered and tried again on every call: with the windows at "everything" the cite planner
read ~110k posts a run (84 s on the server for nothing added), the read and entities leases ~2 s each.

A mark is (kind, guide, post) with why it was passed over (`same_input`, `not_cue`) and the post's text **stamp**: the
version of what tasks.load_posts reads (the post's row, its parts, its kept links, the source's shown name and kind and
its linked page: mx_post_stamps since v10.22), as the planner's query saw them. The planners skip a post whose mark's
stamp is its stamp now; when any of those rows changes the stamp differs and the post is read again exactly as before
(and marked again if passed over again).
So a planner adds the same tasks as before, only without re-reading what cannot have changed. Marks are derived rows:
kept (keep everything), overwritten when a post is passed over again.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

SAME_INPUT, NOT_CUE, ONE_WINDOW = "same_input", "not_cue", "one_window"   # 0176: one_window (the windows planner)

# 0208: the stored page a link post shares (the originals step's story_originals kind `linked`), over a post id
# expression: tasks.load_posts reads a link post with no words of its own with that page's text.
LINKED_PAGE = """SELECT o.post_id FROM post_parts lp JOIN story_originals o
                   ON o.kind = 'linked' AND o.url = lp.link_target AND o.post_id IS NOT NULL
                WHERE lp.post_id = {post} AND lp.link_kind = 'page' LIMIT 1"""

# The post's text stamp, over alias `p` (posts): what load_posts reads, as one version (v10.22, migration 0147:
# mx_post_stamps.n, moved by triggers on every write of the post's row, its parts, its kept links, its source's shown
# name and kind, and the `linked` original its page is (0208)). Was: the post's row version and those four read again
# as subqueries for every post of the window on every planner run (on the server 12% of the database's time); now one
# primary-key probe of a narrow table. NULL for a post with no row (never marked, always read).
STAMP = "(SELECT ps.n::text FROM mx_post_stamps ps WHERE ps.post_id = p.id)"


def unmarked(kind_param: str = "%(kind)s", guide_param: str = "%(guide)s") -> str:
    """A WHERE condition over alias `p`: no mark of this kind and guide holds for the post (none, or its stamp is old).
    A scalar subquery, so it is one primary-key probe a post and the stamp is computed only for a marked one (as an
    anti-join, a planner that thought the table empty compared every mark with every post: 56 s on the scale copy)."""
    return f"""NOT COALESCE((SELECT mk.stamp = {STAMP} FROM mx_plan_marks mk
                              WHERE mk.kind = {kind_param} AND mk.guide = {guide_param} AND mk.post_id = p.id), false)"""


def unread(asks: str, kind_param: str = "%(kind)s", guide_param: str = "%(guide)s") -> str:
    """A WHERE condition over alias `p` that narrows a planner's posts before any is read: the post is one `asks` holds
    for (a condition over `q.id`: the planner's own "no task of mine yet", from the tasks' (a, kind, guide) index) and
    no mark of this kind and guide holds for it (`unmarked`'s, by a join of mx_plan_marks and mx_post_stamps). Both are
    the planner's own conditions over narrow tables and indexes, so a window whose posts all have their task, or are
    passed over for their current text, is found without reading a post row (v10.22: every planner run read every
    post of the window, ~3 page reads a post for the post, ~3 for its mark, ~3 for its task).
    v10.33 (0277): an array of ids (`p.id = ANY(ARRAY(...))`), not `p.id IN (...)`: the planner estimated the posts
    left at ~80% of all (the tasks' (kind, guide) estimate is a fifth of the real one), so it walked the date index
    over every post of the window, reading each post's row to test it against the hashed set (production: ~3 s and
    ~1.4M blocks a call, 1,361 calls, with the all-time window); the array is the posts' primary-key probes, so only
    the posts left are read (synthetic 200k posts, 1k left: 407 -> 207 ms, 137k -> 97k blocks). The price: a guide
    with no task yet (every post left) reads every post and sorts them (synthetic: 0.31 -> 1.25 s) for its first
    pages, while it has PLAN_LIMIT tasks a call to add."""
    return f"""p.id = ANY(ARRAY(SELECT q.id FROM posts q
                                WHERE {asks}
                                  AND NOT EXISTS (SELECT 1 FROM mx_plan_marks mk
                                                    JOIN mx_post_stamps ps ON ps.post_id = mk.post_id
                                                   WHERE mk.kind = {kind_param} AND mk.guide = {guide_param}
                                                     AND mk.post_id = q.id AND mk.stamp = ps.n::text)))"""


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
