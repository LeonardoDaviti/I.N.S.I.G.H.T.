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
"""
from __future__ import annotations

import resource
from typing import Optional

STATUS = "/proc/self/status"
CLEAR_REFS = "/proc/self/clear_refs"


def mb(path: str = STATUS) -> float:
    """This process's peak resident memory in MB since its start or the last `reset()`."""
    hwm = _vm_hwm_kb(path)
    if hwm is None:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)   # KiB on Linux
    return round(hwm / 1024.0, 1)


def reset(path: str = CLEAR_REFS) -> bool:
    """Start the peak again from the current resident size (Linux: "5" to clear_refs); False where it can't."""
    try:
        with open(path, "w") as f:
            f.write("5")
        return True
    except OSError:
        return False


def _vm_hwm_kb(path: str) -> Optional[int]:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None
