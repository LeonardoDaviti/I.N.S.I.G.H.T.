"""A process's own peak memory and CPU (0215, 0216).

The jobs run in processes started with multiprocessing's "spawn", and Linux carries the forked parent's resident size
across exec into the child's ru_maxrss, so that reports the scheduler's size, not the job's. `mb()` reads the process's
own high-water (VmHWM, reset by exec) and `reset()` starts it again, so jobs run one after the other in one process
each record their own; off Linux, ru_maxrss. `rss_mb()`, `cpu_s()` and `own()` give this process's numbers for the
heartbeats and GET /metrics; `of(pid)` the same of another process. A few /proc reads, no state but the CPU baseline.
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
    """This process's CPU seconds (user + system, its own: not its children's) since its start or the last
    `reset()`."""
    return round(max(0.0, _cpu_total() - _cpu_at_reset), 2)


def rss_mb(path: str = STATUS) -> Optional[float]:
    """This process's resident memory now (VmRSS) in MB, or None where /proc is not there."""
    kb = _status_kb(path, "VmRSS:")
    return None if kb is None else round(kb / 1024.0, 1)


def own(path: str = STATUS) -> Dict[str, Optional[float]]:
    """{rss_mb, hwm_mb, cpu_s}: what this process holds now, its high-water and its CPU (`mb`, `cpu_s`)."""
    return {"rss_mb": rss_mb(path), "hwm_mb": mb(path), "cpu_s": cpu_s()}


def of(pid: int, proc: str = "/proc") -> Dict[str, Optional[float]]:
    """Another process's {rss_mb, hwm_mb, cpu_s} (its whole life's CPU: /proc/<pid>/stat's utime + stime), read
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
    """Start the peak again from the current resident size (Linux: "5" to clear_refs), and the CPU count from now;
    False where the peak can't be."""
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
