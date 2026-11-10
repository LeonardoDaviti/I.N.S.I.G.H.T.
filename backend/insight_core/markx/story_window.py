"""The story window (issue 0144 A, C): how far back Mark X makes its own stories, as the owner sets it on /markx.

  - **The setting** (`story_window_days` in mx_settings, beside the reading window): a number of days, or null for
    every post ("everything"); 30 when never set (corrections 8's window, as before). Read on every run: the decision
    run's window (`decide.Config.days`), the candidate finder's backfill and `tasks.plan_checks` use it. News keeps
    its own window (`NEWS_DAYS`, `news.NEWS_KEEP`): an old story never enters News.
  - **The backfill is newest first and resumable** (`story_backfill` in mx_settings: the oldest day reached). Past
    RECENT days the decision window grows backwards STEP_DAYS at a time, from the newest day: the candidate finder
    first finds the candidates of the next step's posts (CANDIDATE_PAGE a run, newest first, the same four sources and
    rules), and the window steps back only once they are found and the run left no old question waiting. A stopped
    or failed run resumes from the day reached. v10.13.9: a step also needs room (`room`): the run that just finished
    used under ROOM_SHARE of its limit and its entities stage stayed within ENTITY_SLACK times its budget; else the
    window holds and says why (each step makes every later run bigger).
  - **Questions in pages**: while the window reaches past RECENT days, a run adds at most BACKFILL_PAGE new questions
    a kind about posts older than RECENT days (newest first), at priority BACKFILL_PRIORITY, so a worker's lease mixes
    them with today's instead of queueing them behind every new one.
  - **Old Mark IX stories are inputs, not answers**: their pairs are checked as today (`check`), so the stories Mark X
    makes over history are its own.
  - **The fallback** (0144 C): with the window at everything, once MIN_LABELS old stories (first post older than
    RECENT days) are labelled on the entity pages and their precision is under KEEP_PRECISION, the window falls back
    to the last window the owner set before everything (else RECENT), and says why.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from insight_core.markx import repo

KEY = "story_window_days"            # mx_settings: the owner's story window (int days, or null: every post)
PREVIOUS = "story_window_previous"   # mx_settings: the window set before "everything" (the fallback's)
BACKFILL = "story_backfill"          # mx_settings: {"reached": the oldest day the decision window reaches, ISO date}
RECENT = 30                          # the decision window before 0144 (tasks.PLAN_DAYS); never a backfill inside it
STEP_DAYS = 7                        # the backfill reaches this many days further back a step
BACKFILL_PAGE = 200                  # new questions a kind a run may add about posts older than RECENT days
BACKFILL_PRIORITY = 1                # their priority: after today's (0), with yesterday's
CANDIDATE_PAGE = 1000                # posts the candidate finder's backfill reads a run, newest first (about 11 s: 10.7 ms a post measured)
KEEP_PRECISION = 0.97                # old stories' precision to keep the window at everything (0144 C)
MIN_LABELS = 20                      # labelled old stories before the precision counts
ROOM_SHARE = 0.5                     # v10.13.9: a step back only after a run under this share of its limit (`room`)
ENTITY_SLACK = 2.0                   # ... whose entities stage stayed within this many times its budget


def _as_days(value: Any) -> Optional[int]:
    return None if value is None else int(value)


def setting(cur: Any) -> Optional[int]:
    """The owner's story window: days, or None for every post; RECENT when never set."""
    return _as_days(repo.get_setting(cur, KEY, default=RECENT))


def set_window(cur: Any, days: Optional[int]) -> Optional[int]:
    """The page's choice. Choosing everything keeps the window it replaces (the fallback's)."""
    old = setting(cur)
    if days is None and old is not None:
        repo.set_setting(cur, PREVIOUS, old)
    repo.set_setting(cur, KEY, days)
    return days


def precision(cur: Any) -> Dict[str, Any]:
    """The labelled samples' precision, old (first post older than RECENT days when offered) and recent:
    {"old": {"right", "wrong", "missed", "labelled", "precision"}, "recent": {...}}. The newest answer of a story
    counts; "missed" (the story lacks a post) doesn't count against precision."""
    cur.execute("""SELECT DISTINCT ON (l.story_id) l.story_id, l.answer, s.first_at, s.offered_at
                     FROM mx_story_sample_labels l JOIN mx_story_samples s ON s.story_id = l.story_id
                    ORDER BY l.story_id, l.created_at DESC, l.id DESC""")
    out = {k: {"right": 0, "wrong": 0, "missed": 0} for k in ("old", "recent")}
    for _sid, answer, first_at, offered_at in cur.fetchall():
        old = first_at is not None and first_at < offered_at - timedelta(days=RECENT)
        out["old" if old else "recent"][answer] += 1
    for v in out.values():
        judged = v["right"] + v["wrong"] + v["missed"]
        v["labelled"] = judged
        v["precision"] = round(v["right"] / (v["right"] + v["wrong"]), 3) if v["right"] + v["wrong"] else None
    return out


def fallback(cur: Any, measured: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """{"days", "why"} when the window set at everything falls back (old stories' precision under KEEP_PRECISION on
    MIN_LABELS or more labels), else None."""
    if setting(cur) is not None:
        return None
    old = (measured or precision(cur))["old"]
    judged = old["right"] + old["wrong"]
    if judged < MIN_LABELS or old["precision"] is None or old["precision"] >= KEEP_PRECISION:
        return None
    back = _as_days(repo.get_setting(cur, PREVIOUS, default=RECENT))
    back = RECENT if back is None else back
    return {"days": back, "why": f"stories older than {RECENT} days were right {old['right']} of {judged} "
                                 f"({old['precision']:.0%}), under {KEEP_PRECISION:.0%}: back to {back} days"}


def window(cur: Any) -> Optional[int]:
    """The window in force: the setting, or the fallback's days."""
    fb = fallback(cur)
    return fb["days"] if fb else setting(cur)


def _day(value: Any) -> Optional[date]:
    return date.fromisoformat(value) if isinstance(value, str) else None


def reached(cur: Any) -> Optional[date]:
    """The oldest day the backfill reached, or None (never stepped past RECENT)."""
    return _day((repo.get_setting(cur, BACKFILL, default=None) or {}).get("reached"))


def backfilling(cur: Any) -> bool:
    w = window(cur)
    return w is None or w > RECENT


def _start(now: datetime, days: int) -> date:
    return (now - timedelta(days=days)).astimezone(timezone.utc).date()


def days_for_run(cur: Any, now: datetime) -> int:
    """The decision window of a run at `now`, in days: the window in force when it is RECENT or under, else the part
    the backfill reached (RECENT days at first), at most the window."""
    w = window(cur)
    if w is not None and w <= RECENT:
        return w
    got = reached(cur)
    days = RECENT if got is None else max(RECENT, (now.astimezone(timezone.utc).date() - got).days + 1)
    return days if w is None else min(days, w)


def next_since(cur: Any, now: datetime) -> Optional[datetime]:
    """Where the candidate finder's backfill reads from: one step past the decision window (None: no backfill)."""
    if not backfilling(cur):
        return None
    days = days_for_run(cur, now) + STEP_DAYS
    w = window(cur)
    return now - timedelta(days=days if w is None else min(days, w))


def oldest_post(cur: Any) -> Optional[datetime]:
    cur.execute("SELECT min(COALESCE(surfaced_at, published_at, fetched_at)) FROM posts")
    return cur.fetchone()[0]


def room(seconds: float, limit: float, *, entities: Optional[float] = None,
         entity_budget: Optional[float] = None) -> Optional[str]:
    """v10.13.9: why the window must hold, or None when the run that just finished left room for a bigger one: it used
    under ROOM_SHARE of the limit (`seconds`: what the limit counts, the entities stage apart) and its entities stage
    stayed within ENTITY_SLACK times its budget. Every step makes the next run bigger (on the server the backfill
    reached February and the runs were killed or stopped for hours), so a step needs room, not only a success."""
    if seconds >= ROOM_SHARE * limit:
        return f"held: run took {seconds:.0f} s (steps back under {ROOM_SHARE * limit:.0f} s, {ROOM_SHARE:.0%} of {limit:.0f} s)"
    if entities is not None and entity_budget is not None and entities > ENTITY_SLACK * entity_budget:
        return (f"held: the entities stage took {entities:.0f} s (steps back within {ENTITY_SLACK * entity_budget:.0f} s, "
                f"{ENTITY_SLACK:g}x its {entity_budget:.0f} s budget)")
    return None


def advance(cur: Any, now: datetime, *, waiting_old: int, candidates_left: int,
            held: Optional[str] = None) -> Dict[str, Any]:
    """After a decision run: the backfill steps STEP_DAYS further back when the run left no old question waiting and
    the candidate finder found every post of the next step, never past the window or the oldest post; a step with no
    post goes on to the week of the next older post (a misdated post years back costs one step, not hundreds). The state as
    the page shows it: {"reached", "done", "stepped"}. v10.13.9: `held` (room's why) keeps it where it is, and says so
    ({"held": why})."""
    state = dict(repo.get_setting(cur, BACKFILL, default=None) or {})
    if not backfilling(cur):
        return {"reached": state.get("reached"), "done": False, "stepped": False}
    w = window(cur)
    days = days_for_run(cur, now)
    oldest = oldest_post(cur)
    floor = _start(now, w - 1) if w is not None else (oldest.astimezone(timezone.utc).date() if oldest else None)
    current = _start(now, days - 1)
    done = floor is not None and current <= floor
    stepped = False
    if not done and held:
        return {"reached": state.get("reached"), "done": False, "stepped": False, "held": held}
    if not done and waiting_old == 0 and candidates_left == 0:
        target = current - timedelta(days=STEP_DAYS)
        cur.execute("SELECT max(COALESCE(surfaced_at, published_at, fetched_at)) FROM posts "
                    "WHERE COALESCE(surfaced_at, published_at, fetched_at) < %s", (current,))
        newest_before = cur.fetchone()[0]           # a step with no post: on to the next post's week (no empty runs)
        if newest_before is not None and newest_before.astimezone(timezone.utc).date() < target:
            target = newest_before.astimezone(timezone.utc).date() - timedelta(days=STEP_DAYS - 1)
        if floor is not None and target < floor:
            target = floor
        state["reached"] = target.isoformat()
        repo.set_setting(cur, BACKFILL, state)
        stepped, done = True, floor is not None and target <= floor
    return {"reached": state.get("reached"), "done": done, "stepped": stepped}


def view(cur: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """What /markx shows beside the reading window."""
    now = now or datetime.now(timezone.utc)
    measured = precision(cur)
    fb = fallback(cur, measured)
    got = reached(cur)
    return {"days": setting(cur), "default": RECENT, "in_force": fb["days"] if fb else setting(cur),
            "fallback": fb, "run_days": days_for_run(cur, now), "reached": got.isoformat() if got else None,
            "precision": measured, "keep": KEEP_PRECISION, "min_labels": MIN_LABELS}
