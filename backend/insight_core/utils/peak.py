"""A job's own peak memory (issue 0215).

The jobs (markx/jobs.py: the kept views, the rebuild's slices, the decision run; the source stats, the official
channels) each run in a process of their own, started with multiprocessing's "spawn" from insight-ingestion's scheduler.
They recorded `getrusage(RUSAGE_SELF).ru_maxrss` as their peak, but Linux carries a process's high-water across exec:
the child is forked from the scheduler first, and exec folds the fork's resident size (the scheduler's, every page
mapped) into the child's ru_maxrss. So every job on the server reported the scheduler's ~1,366-1,395 MB, whatever it
held itself (measured: a parent holding 1,213 MB, its spawned child's ru_maxrss 1,215 MB, its own VmHWM 16.8 MB).

`mb()` reads the process's own high-water (VmHWM: this address space's, reset by exec), and `reset()` starts it again
from what the process holds now, so jobs built one after the other in one process (the kept views due together) each
record their own. Off Linux (no /proc), ru_maxrss as before.

0216: a process's own numbers, read the same way, for the heartbeats and GET /metrics: `rss_mb()` (VmRSS now),
`cpu_s()` (its CPU seconds, user and system, since its start or the last `reset()`: a spawned job counts its own
from its start) and `own()` (all three: what a process writes in its heartbeat); `of(pid)` the same three of another
process (/proc/<pid>/status and /stat: the API's supervisor reads its API processes'). A few /proc reads, no state
but the CPU baseline.
"""
from __future__ import annotations

import os
import resource
from typing import Dict, Optional

STATUS = "/proc/self/status"
CLEAR_REFS = "/proc/self/clear_refs"


def mb(path: str = STATUS) -> float:
    """This process's peak resident memory in MB since its start or the last `reset()`."""
    hwm = _vm_hwm_kb(path)
    if hwm is None:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)   # KiB on Linux
    return round(hwm / 1024.0, 1)


_cpu_at_reset = 0.0


def _cpu_total() -> float:
    t = os.times()
    return t.user + t.system


def cpu_s() -> float:
    """0216: this process's CPU seconds (user + system, its own: not its children's) since its start or the last
    `reset()`."""
    return round(max(0.0, _cpu_total() - _cpu_at_reset), 2)


def rss_mb(path: str = STATUS) -> Optional[float]:
    """0216: this process's resident memory now (VmRSS) in MB, or None where /proc is not there."""
    kb = _status_kb(path, "VmRSS:")
    return None if kb is None else round(kb / 1024.0, 1)


def own(path: str = STATUS) -> Dict[str, Optional[float]]:
    """0216: {rss_mb, hwm_mb, cpu_s}: what this process holds now, its high-water and its CPU (`mb`, `cpu_s`)."""
    return {"rss_mb": rss_mb(path), "hwm_mb": mb(path), "cpu_s": cpu_s()}


def of(pid: int, proc: str = "/proc") -> Dict[str, Optional[float]]:
    """0216: another process's {rss_mb, hwm_mb, cpu_s} (its whole life's CPU: /proc/<pid>/stat's utime + stime), read
    by its parent (the API's supervisor for each API process); None for what can't be read (the process is gone)."""
    status = f"{proc}/{pid}/status"
    rss, hwm = _status_kb(status, "VmRSS:"), _status_kb(status, "VmHWM:")
    cpu: Optional[float] = None
    try:
        with open(f"{proc}/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()   # after "(comm)": state is fields[0], utime fields[11]
        cpu = round((int(fields[11]) + int(fields[12])) / _TICKS, 2)
    except (OSError, ValueError, IndexError):
        pass
    return {"rss_mb": None if rss is None else round(rss / 1024.0, 1),
            "hwm_mb": None if hwm is None else round(hwm / 1024.0, 1), "cpu_s": cpu}


_TICKS = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0


def reset(path: str = CLEAR_REFS) -> bool:
    """Start the peak again from the current resident size (Linux: "5" to clear_refs), and the CPU count from now
    (0216); False where the peak can't be."""
    global _cpu_at_reset
    _cpu_at_reset = _cpu_total()
    try:
        with open(path, "w") as f:
            f.write("5")
        return True
    except OSError:
        return False


def _vm_hwm_kb(path: str) -> Optional[int]:
    return _status_kb(path, "VmHWM:")


def _status_kb(path: str, field: str) -> Optional[int]:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(field):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None
