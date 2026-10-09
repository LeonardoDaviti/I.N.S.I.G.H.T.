"""The safe_ingest CLI shim: argument parsing only (the run itself is test_ingestion_runner)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import FetchRequest, SourceSelector, Trigger
from insight_core.scripts.safe_ingest import parse_args


class SafeIngestCliTests(unittest.TestCase):
    def test_no_arguments_is_a_due_only_cycle_over_all_sources(self):
        self.assertEqual(parse_args([]), FetchRequest(SourceSelector.all(), Trigger.CLI, force=False))

    def test_force_and_folder(self):
        self.assertEqual(parse_args(["--force", "--folder", "f1"]),
                         FetchRequest(SourceSelector.folder("f1"), Trigger.CLI, force=True))

    def test_source(self):
        self.assertEqual(parse_args(["--source", "s1"]).selector, SourceSelector.source("s1"))

    def test_folder_and_source_are_exclusive(self):
        with self.assertRaises(SystemExit):
            parse_args(["--folder", "f1", "--source", "s1"])


if __name__ == "__main__":
    unittest.main()
