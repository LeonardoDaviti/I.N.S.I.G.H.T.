"""The decision run's two entity stages (issue 0119 A1-A2): `entities` (markx/identity.py) and `surges`
(markx/surges.py), each logged with its duration under the run's limit (0112 Decided 12).

Incremental by the database, not by a process's memory (each job runs in a process of its own): a run links the
mentions not linked yet (entity_id null) and decides the pairs whose answers came since the last run; the surges
recount only the days those mentions fall on, or every day of the window when a merge, an undo or a split changed
since the last run. The first run after NIGHTLY_HOUR (server time), or a forced full run, is the full pass: every
mention relinked and checked against what was stored (`entities.check`), every entity pooled, every day recounted.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

from insight_core.markx import identity, surges as S

NIGHTLY_HOUR = 4
MARGIN = timedelta(minutes=2)


def full_due(cur: Any, now: datetime) -> bool:
    local = now.astimezone()
    mark = local.replace(hour=NIGHTLY_HOUR, minute=0, second=0, microsecond=0)
    if mark > local:
        mark -= timedelta(days=1)
    cur.execute("""SELECT max((counts->'run'->>'now')::timestamptz) FROM mx_runs
                    WHERE finished_at IS NOT NULL AND counts->'entities'->>'kind' = 'full'""")
    last = cur.fetchone()[0]
    return last is None or last < mark


def entities(cur: Any, *, ask: Any, now: datetime, run_id: Any, since: Optional[datetime],
             full: Optional[bool] = None) -> Tuple[Dict[str, Any], Optional[Set[date]]]:
    """(the stage's counts, the days the surges recount: None for every day)."""
    whole = bool(full) or full_due(cur, now)
    # an answer committed by a transaction that began before the last run's start is read again (jobs.MENTIONS_MARGIN)
    since = since - MARGIN if since is not None else None
    out = identity.stage(cur, ask=ask, now=now, run_id=run_id, full=whole, since=since)
    days = {date.fromisoformat(d) for d in out.pop("days", [])}
    out["days_linked"] = len(days)
    if whole or since is None:
        return out, None
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_entity_redirects WHERE at >= %(s)s OR undone_at >= %(s)s)
                       OR EXISTS (SELECT 1 FROM mx_entity_pins WHERE created_at >= %(s)s OR undone_at >= %(s)s)""",
                {"s": since})
    return out, (None if cur.fetchone()[0] else days)


def surges(cur: Any, *, now: datetime, run_id: Any, days: Optional[Set[date]], since: Optional[datetime],
           window_days: int = 30) -> Dict[str, Any]:
    return S.stage(cur, now=now, run_id=run_id, days=days, window_days=window_days)
