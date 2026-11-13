"""Heartbeats (issue 0188): insight-ingestion's loops say they are alive in a file each, in the logs volume both
containers mount, so its Docker healthcheck and the API's /api/status read the truth instead of grepping /proc for
a process name (which a hung loop keeps).

  - "scheduler": run_scheduler.py's event loop, every BEAT_SECONDS from a task of its own (an ingestion tick may run
    long; the loop answering is what this says, the ingestion's freshness is /api/status's own check).
  - "markx": Mark X's job loop (markx/jobs.py Runner), after each look; a look can wait for a job's process up to
    a decision run and the Labels build after it (HARD_LIMIT each), so its limit is longer. Cleared at the scheduler's start, written only while the loop runs.

    python -I insight_core/utils/heartbeat.py   # the healthcheck: exit 1 when a heartbeat is stale

Standard library only, and no import of insight_core: the healthcheck starts a Python each minute.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, Optional

BEAT_SECONDS = 30.0
# a heartbeat older than this is a loop that stopped: the scheduler's beats every 30 s; Mark X's after each look,
# which waits at most for a decision run and the Labels build after it, each up to HARD_LIMIT (900 s) and its kill
LIMITS = {"scheduler": 180.0, "markx": 2000.0}


def folder() -> str:
    """The logs volume's runtime folder (INSIGHT_LOG_DIR, as services/api_watchdog.shared_dir)."""
    return os.path.join(os.getenv("INSIGHT_LOG_DIR") or "logs", "runtime")


def _path(name: str) -> str:
    return os.path.join(folder(), f"heartbeat-{name}")


def beat(name: str, now: Optional[float] = None) -> None:
    """`name` is alive now. Never raises (a full disk never stops a loop)."""
    try:
        os.makedirs(folder(), exist_ok=True)
        path = _path(name)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(f"{time.time() if now is None else now:.0f}\n")
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def clear(name: str) -> None:
    """A loop that will not run (Mark X off): no heartbeat left from an earlier start reads as a stopped loop."""
    try:
        os.remove(_path(name))
    except OSError:
        pass


def ages(now: Optional[float] = None) -> Dict[str, Optional[float]]:
    """Seconds since each known loop's last beat; None when it has none (never ran, or cleared)."""
    now = time.time() if now is None else now
    out: Dict[str, Optional[float]] = {}
    for name in LIMITS:
        try:
            with open(_path(name), encoding="utf-8") as fh:
                out[name] = max(0.0, now - float(fh.read().strip()))
        except (OSError, ValueError):
            out[name] = None
    return out


def stale(now: Optional[float] = None, *, required: tuple = ("scheduler",)) -> List[str]:
    """Why the loops are not healthy: a required loop with no heartbeat, or any loop's beat older than its limit."""
    reasons = []
    for name, age in ages(now).items():
        if age is None:
            if name in required:
                reasons.append(f"no {name} heartbeat")
        elif age > LIMITS[name]:
            reasons.append(f"the {name} loop's last heartbeat was {age:.0f} s ago (limit {LIMITS[name]:.0f} s)")
    return reasons


if __name__ == "__main__":
    problems = stale()
    for line in problems:
        print(line)
    sys.exit(1 if problems else 0)
