"""0217 Part 2: a News row the reader saw comes back only with a meaningful update (utils/row_updates.py). Pure."""
from __future__ import annotations

import unittest

from insight_core.utils.row_updates import Line, numbers, update


def preview():
    return [Line("p0", "lab", "announced", "model_release", ("1M context",)),
            Line("p1", "forum", None, "opinion_analysis", ()),
            Line("p2", "channel", "announced", "model_release", ("1M context",))]


class Updates(unittest.TestCase):
    def test_the_launch_brings_a_seen_preview_back(self):
        got = update(preview(), [Line("l0", "lab", "released", "model_release", ("2.4T parameters",))])
        self.assertTrue(got.meaningful)
        self.assertEqual(got.what, "launch")
        self.assertIn("new numbers", got.reasons)
        self.assertEqual(got.lines, frozenset({"l0"}))

    def test_twenty_reposts_do_not(self):
        reposts = [Line(f"r{k}", f"voice{k}", "announced", "model_release", ("1M context",), copy_of="p0")
                   for k in range(20)]
        self.assertFalse(update(preview(), reposts).meaningful)

    def test_the_router_and_the_benchmark_are_lines(self):
        seen = preview() + [Line("l0", "lab", "released", "model_release")]
        got = update(seen, [Line("r0", "router", None, "product_release", ("$1.50/M input",))])
        self.assertEqual((got.meaningful, got.what), (True, "availability"))
        got = update(seen, [Line("b0", "evaluator", None, "research_result", ("+9 points",))])
        self.assertEqual(got.what, "benchmarks")

    def test_repetition_is_not_news_and_two_new_voices_are(self):
        seen = preview()
        same = [Line("x0", "blog", "announced", "model_release", ("1M context",))]
        self.assertFalse(update(seen, same).meaningful)          # one new voice, nothing new said
        two = same + [Line("x1", "paper", None, None, ())]
        got = update(seen, two)
        self.assertEqual((got.meaningful, got.what, got.sources), (True, "new sources", 2))
        shares = [Line("s0", "a", None, None, (), report=False), Line("s1", "b", None, None, (), report=False)]
        self.assertFalse(update(seen, shares).meaningful)         # shares and replies are no sources

    def test_a_correction(self):
        got = update(preview(), [Line("c0", "lab", None, None, (), corrects=True)])
        self.assertEqual(got.what, "correction")

    def test_numbers_leave_dates_out(self):
        self.assertEqual(numbers(["November 8", "2026", "$1.50/M input", "+9 points", "1,5x"]), {"1.5", "9"})
        self.assertEqual(numbers([75, None]), {"75"})   # a reading may write a number bare
        self.assertFalse(update(preview(), [Line("d0", "x", None, None, ("November 10", "2027"))]).meaningful)

    def test_nothing_new(self):
        self.assertFalse(update(preview(), []).meaningful)
        self.assertFalse(update(preview(), preview()[:1]).meaningful)


if __name__ == "__main__":
    unittest.main()
