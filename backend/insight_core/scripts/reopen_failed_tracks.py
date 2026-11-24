"""Ask again, once, the track questions the track-v3 checks failed before v10.44 (services/data_repairs.py runs it
after a deploy).

    python -m insight_core.scripts.reopen_failed_tracks [--dry-run]

From v10.41 to v10.43 validate refused most track-v3 answers to a post in another script than English ("why: it
names nothing of this post": an English answer shares no word with a Russian post) and quotes of `Belongs:` the judge
reworded a word of ("matches: copy it from the track's header"); a track question fails at its second refusal
(repo.max_attempts), so they stayed failed. Each such task (kind track, a question of GUIDES, failed)
goes back to open with its attempts at 0; its last error stays until its next answer. Its mx_track_items row was
never filled (a failed task has no valid answer), so the next valid answer fills it. Nothing is deleted. Prints the
totals as one JSON line.

v10.47: also the questions of the guides before them (track-v2, track-check-v1, still answered): the same checks
failed them before v10.44 (other scripts), and their out verdicts, whose `why` says why not as those guides ask, were
held to name the post (validate._track); asked again once under the v10.47 checks.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from insight_core.db.migrate import get_conn

GUIDES = ("track-v3", "track-check-v2", "track-v2", "track-check-v1")
# a failed task keeps its input (tasks.spend spends answered ones only), so each one can be asked again
FAILED = """FROM mx_tasks WHERE kind = 'track' AND status = 'failed' AND guide = ANY(%s)"""


def run(conn, *, dry_run: bool) -> Dict[str, Any]:
    """{reopened, by_error: {error: n}, sample: [{task_id, post_id, track_id, error}]}; `dry_run`: rolled back."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT last_error, count(*) {FAILED} GROUP BY last_error ORDER BY count(*) DESC", (list(GUIDES),))
        by_error = {(e or "")[:160]: n for e, n in cur.fetchall()}
        cur.execute(f"SELECT id::text, a::text, b::text, last_error {FAILED} ORDER BY created_at DESC LIMIT 10",
                    (list(GUIDES),))
        sample = [{"task_id": t, "post_id": a, "track_id": b, "error": e} for t, a, b, e in cur.fetchall()]
        cur.execute(f"""UPDATE mx_tasks SET status = 'open', attempts = 0, lease_until = NULL, leased_by = NULL
                         WHERE id IN (SELECT id {FAILED})""", (list(GUIDES),))
        reopened = cur.rowcount
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return {"reopened": reopened, "by_error": by_error, "sample": sample}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with get_conn() as conn:
        out = run(conn, dry_run=args.dry_run)
    print(json.dumps({**out, "dry_run": args.dry_run}, ensure_ascii=False))


if __name__ == "__main__":
    main()
