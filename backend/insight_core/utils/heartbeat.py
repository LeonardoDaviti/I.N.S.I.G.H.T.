"""Heartbeats (issue 0188): insight-ingestion's loops say they are alive in a file each, in the logs volume both
containers mount, so its Docker healthcheck and the API's /api/status read the truth instead of grepping /proc for
a process name (which a hung loop keeps).

  - "scheduler": run_scheduler.py's event loop, every BEAT_SECONDS from a task of its own (an ingestion tick may run
    long; the loop answering is what this says, the ingestion's freshness is /api/status's own check).
  - "markx": Mark X's job loop (markx/jobs.py Runner), after each look; a look can wait for a job's process up to
    a decision run and the Labels build after it (HARD_LIMIT each), so its limit is longer. Cleared at the scheduler's start, written only while the loop runs.

    python -I insight_core/utils/heartbeat.py   # the healthcheck: exit 1 when a heartbeat is stale

0216: a beat may carry its process's own numbers (`stats`: utils/peak.own, {rss_mb, hwm_mb, cpu_s}) on a second line,
so the scheduler parent's memory and CPU are read by a GET (/api/status, GET /metrics) without touching the process.
Each API process has a beat too, "api-<pid>", written by the API's supervisor (scripts/api_supervisor.py) for its
numbers only: no healthcheck reads those.
`processes()` reads every beat with its numbers. 0233 (0225 #18, ghost processes): the writer of a set of beats owns
their end: the supervisor writes the beats of uvicorn's processes alive now and removes every other "api-" beat in the
same step (`only`), so a process that ended (killed by the open-files guard, a restarted worker, the previous
container's after a restart, uvicorn's own pid beaten before its workers were up) is never listed. Before, the reader
removed an API beat only an hour (API_GONE) after its last write, and /api/status listed the dead processes till then.

Standard library only, and no import of insight_core: the healthcheck starts a Python each minute.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

BEAT_SECONDS = 30.0
# a heartbeat older than this is a loop that stopped: the scheduler's beats every 30 s; Mark X's after each look,
# which waits at most for a decision run and the Labels build after it, each up to HARD_LIMIT (900 s) and its kill
LIMITS = {"scheduler": 180.0, "markx": 2000.0}


def folder() -> str:
    """The logs volume's runtime folder (INSIGHT_LOG_DIR, as services/api_watchdog.shared_dir)."""
    return os.path.join(os.getenv("INSIGHT_LOG_DIR") or "logs", "runtime")


def _path(name: str) -> str:
    return os.path.join(folder(), f"heartbeat-{name}")


def beat(name: str, now: Optional[float] = None, stats: Optional[Dict[str, Any]] = None) -> None:
    """`name` is alive now; 0216: with its process's own numbers (`stats`, one JSON line). Never raises (a full disk
    never stops a loop)."""
    try:
        os.makedirs(folder(), exist_ok=True)
        path = _path(name)
        body = f"{time.time() if now is None else now:.0f}\n"
        if stats:
            body += json.dumps(stats, separators=(",", ":")) + "\n"
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(path + ".tmp", path)
    except (OSError, TypeError, ValueError):
        pass


def _read(path: str) -> Optional[Dict[str, Any]]:
    """{at, and the numbers the beat carries}, or None (no file, or not a beat)."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        out: Dict[str, Any] = {"at": float(lines[0].strip())}
    except (OSError, ValueError, IndexError):
        return None
    if len(lines) > 1:
        try:
            extra = json.loads(lines[1])
        except ValueError:
            extra = None
        if isinstance(extra, dict):
            out.update({k: v for k, v in extra.items() if k != "at"})
    return out


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
        got = _read(_path(name))
        out[name] = None if got is None else max(0.0, now - got["at"])
    return out


def only(prefix: str, names: Any) -> int:
    """0233: the beats named `prefix`... other than `names` removed (their processes ended): how many. The writer of
    those beats calls it with the names it just wrote. Never raises."""
    keep = set(names)
    gone = 0
    try:
        files = os.listdir(folder())
    except OSError:
        return 0
    for file in files:
        name = file[len("heartbeat-"):]
        if file.startswith("heartbeat-" + prefix) and not file.endswith(".tmp") and name not in keep:
            try:
                os.remove(os.path.join(folder(), file))
                gone += 1
            except OSError:
                pass
    return gone


def processes(now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """0216: every beat in the folder, {name: {age, rss_mb, hwm_mb, cpu_s}} (the numbers its process wrote; only `age`
    for a beat without): the loops' and each API process's ("api-<pid>"; 0233: only the live ones, `only`)."""
    now = time.time() if now is None else now
    out: Dict[str, Dict[str, Any]] = {}
    try:
        files = sorted(os.listdir(folder()))
    except OSError:
        return out
    for file in files:
        if not file.startswith("heartbeat-") or file.endswith(".tmp"):
            continue
        name = file[len("heartbeat-"):]
        path = os.path.join(folder(), file)
        got = _read(path)
        if got is None:
            continue
        out[name] = {"age": max(0.0, now - got.pop("at")), **got}
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
