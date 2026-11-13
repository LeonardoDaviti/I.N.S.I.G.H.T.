"""The shared log files (issue 0188): many processes append to one file, rotated once by size, no line lost.

No database."""
from __future__ import annotations

import glob
import logging
import multiprocessing
import os
import tempfile
import unittest

from insight_core.logs.core.logger_config import SharedRotatingFileHandler


def _write(path: str, tag: str, n: int) -> None:
    handler = SharedRotatingFileHandler(path, maxBytes=2_000, backupCount=50)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger(f"shared-{tag}")
    log.propagate = False
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    for i in range(n):
        log.info("%s %04d %s", tag, i, "x" * 40)
    handler.close()


class SharedRotation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "application.log")

    def lines(self):
        out = []
        for name in glob.glob(self.path + "*"):
            if not name.endswith(".lock"):
                with open(name, encoding="utf-8") as fh:
                    out.extend(fh.read().splitlines())
        return out

    def test_processes_writing_one_file_lose_no_line_and_each_file_stays_near_its_limit(self):
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=_write, args=(self.path, tag, 300)) for tag in ("a", "b", "c")]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertEqual(p.exitcode, 0)
        lines = self.lines()
        self.assertEqual(len(lines), 900)
        self.assertEqual(len(set(lines)), 900)                       # every line once, none torn
        for name in glob.glob(self.path + "*"):
            if not name.endswith(".lock"):
                # one line past the limit per writer at most: each checks before its write
                self.assertLess(os.path.getsize(name), 2_000 + 3 * 60, name)
        self.assertTrue(os.path.exists(self.path + ".1"))

    def test_only_backup_count_files_are_kept(self):
        handler = SharedRotatingFileHandler(self.path, maxBytes=500, backupCount=2)
        handler.setFormatter(logging.Formatter("%(message)s"))
        log = logging.getLogger("shared-keep")
        log.propagate = False
        log.addHandler(handler)
        self.addCleanup(handler.close)
        for i in range(200):
            log.warning("line %04d %s", i, "y" * 40)
        names = sorted(os.path.basename(n) for n in glob.glob(self.path + "*") if not n.endswith(".lock"))
        self.assertEqual(names, ["application.log", "application.log.1", "application.log.2"])


if __name__ == "__main__":
    unittest.main()
