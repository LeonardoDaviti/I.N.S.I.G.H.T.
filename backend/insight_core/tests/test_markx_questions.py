"""0275: questions with citations - the code check of an answer (markx/questions.kept), its schema, its kind."""
from __future__ import annotations

import unittest

from insight_core.markx import consumers, questions, schemas, validate

INPUT = """QUESTION: What runs a 27B model under $1,500?
TODAY: 2026-11-19

POSTS:
[1] @azisk, 2026-11-18: Kadas Mind Pro review — 64GB of memory runs a 27B model at 21 tok/s for $1,399.
[2] @other, 2026-11-17: A GPU dock — a discrete GPU inside the dock."""


class Kept(unittest.TestCase):
    def test_cited_and_supported_sentences_are_kept(self):
        got, dropped = questions.kept({"answerable": True, "sentences": [
            {"text": "@azisk ran a 27B model on the Kadas Mind Pro with 64GB at 21 tok/s.", "cites": [1]},
            {"text": "The dock has a discrete GPU.", "cites": [2, 2]}]}, INPUT)
        self.assertEqual([s["cites"] for s in got], [[1], [2]])
        self.assertEqual(dropped, 0)

    def test_uncited_out_of_set_and_unsupported_figures_are_dropped(self):
        got, dropped = questions.kept({"answerable": True, "sentences": [
            {"text": "It costs $1,399.", "cites": []},                       # no cite
            {"text": "It costs $1,399.", "cites": [7]},                      # not one of the posts
            {"text": "The dock costs $499.", "cites": [2]},                  # a figure no cited post holds
            {"text": "The Kadas Mind Pro costs $1,399.", "cites": [1, 9]}]}, INPUT)
        self.assertEqual(got, [{"text": "The Kadas Mind Pro costs $1,399.", "cites": [1]}])
        self.assertEqual(dropped, 3)

    def test_not_answerable_is_not_in_your_sources(self):
        self.assertEqual(questions.kept({"answerable": False, "sentences": []}, INPUT), ([], 0))
        self.assertEqual(questions.kept(None, INPUT), ([], 0))

    def test_numbered_reads_the_posts_back(self):
        self.assertEqual(sorted(questions.numbered(INPUT)), [1, 2])


class Kind(unittest.TestCase):
    def test_kind_guide_and_consumer(self):
        self.assertEqual(schemas.KINDS["question"].guide, "question-v1")
        self.assertIn("outside", schemas.guide_body("question-v1"))
        self.assertEqual(consumers.CONSUMER["question"], "questions")

    def test_schema(self):
        ok, err = validate.check("question", {"answerable": True, "sentences": [{"text": "x", "cites": [1]}]}, INPUT)
        self.assertIsNone(err)
        _a, err = validate.check("question", {"answerable": True}, INPUT)
        self.assertIsNotNone(err)

    def test_off_by_default_until_measured(self):
        self.assertFalse(questions.on())


if __name__ == "__main__":
    unittest.main()
