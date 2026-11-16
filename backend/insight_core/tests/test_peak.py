"""0215: a job's own peak memory (utils/peak), not the scheduler's carried into it across the spawn.

On the server every job (the kept views, the rebuild's slices, official) recorded ~1,366-1,395 MB: getrusage's
ru_maxrss of a spawned child starts at its parent's resident size (exec folds the fork's high-water into it)."""
from __future__ import annotations

import multiprocessing
import os
import resource
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.utils import peak

HELD_MB = 300


def _child(out) -> None:
    out.put((peak.mb(), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0))


def _touch(mb: int) -> bytearray:
    block = bytearray(mb * 2**20)
    for i in range(0, len(block), 4096):
        block[i] = 1
    return block


@unittest.skipUnless(os.path.exists("/proc/self/status"), "Linux's /proc")
class APeak(unittest.TestCase):
    def test_a_spawned_job_counts_its_own_not_its_parents(self):
        held = _touch(HELD_MB)
        ctx = multiprocessing.get_context("spawn")
        out = ctx.Queue()
        child = ctx.Process(target=_child, args=(out,))
        child.start()
        own, carried = out.get(timeout=60)
        child.join(60)
        del held
        self.assertGreaterEqual(carried, HELD_MB, "ru_maxrss: the parent's, carried across the spawn")
        self.assertLess(own, HELD_MB / 2, "its own peak")

    def test_reset_starts_from_what_it_holds_now(self):
        block = _touch(HELD_MB)
        self.assertGreaterEqual(peak.mb(), HELD_MB)
        del block                       # a large block is unmapped when freed
        if not peak.reset():
            self.skipTest("clear_refs not writable here")
        self.assertLess(peak.mb(), HELD_MB)

    def test_without_proc_it_is_ru_maxrss(self):
        self.assertEqual(peak.mb("/nonexistent/status"),
                         round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1))
        self.assertFalse(peak.reset("/nonexistent/clear_refs"))


if __name__ == "__main__":
    unittest.main()
