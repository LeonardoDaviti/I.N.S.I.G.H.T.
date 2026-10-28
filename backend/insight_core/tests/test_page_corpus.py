"""The shared reader on a corpus of real article pages (issue 0032; see _page_corpus).

Every reader change runs against every page, so a fix for one site cannot silently break
another. A failure names the page, the expectation and what the reader kept. A known gap
(expectations.json "known_gaps") is expected to fail; one that passes fails the test too,
so the gap is removed and the expectation guards from then on.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.tests import _page_corpus as corpus


class PageCorpusTests(unittest.TestCase):
    def test_every_page_has_its_file_and_a_reason_for_each_gap(self):
        expectations = corpus.load_expectations()
        self.assertGreaterEqual(len(expectations), 20)
        for name, expected in expectations.items():
            self.assertTrue((corpus.PAGES_DIR / f"{name}.html").exists(), name)
            self.assertTrue(expected.get("url", "").startswith("https://"), name)
            for check, reason in (expected.get("known_gaps") or {}).items():
                self.assertIn(check, corpus.CHECKS, f"{name}: unknown check {check!r}")
                self.assertIn(check, expected, f"{name}: a gap for {check!r}, which the page does not check")
                self.assertTrue(str(reason).strip(), f"{name}: the gap for {check!r} needs a reason")

    def test_the_reader_meets_every_expectation_but_the_known_gaps(self):
        failures = []
        for name, expected in corpus.load_expectations().items():
            kept = corpus.read(corpus.page_html(name), expected["url"])
            gaps = expected.get("known_gaps") or {}
            for check, problem in corpus.problems(expected, kept).items():
                if problem and check not in gaps:
                    failures.append(f"{name}: {check}: {problem}")
                elif not problem and check in gaps:
                    failures.append(f"{name}: {check} now passes; remove its known gap ({gaps[check]})")
        self.assertEqual([], failures, "\n" + "\n".join(failures))

    def test_the_corpus_stays_small(self):
        size = sum(path.stat().st_size for path in corpus.PAGES_DIR.iterdir())
        self.assertLess(size, 4_000_000)


if __name__ == "__main__":
    unittest.main()
