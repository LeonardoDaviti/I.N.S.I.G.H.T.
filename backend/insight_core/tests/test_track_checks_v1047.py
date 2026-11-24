"""Stealth v10.47 (0280 E3): "why: it names nothing of this post" on track answers, measured on real answers.

Haiku answered 1,641 real track questions (four guides, four topic tracks, the newest 1,100 posts of the server,
2026-11-24). Under the v10.44 checks track-v3 and track-check-v2 refused 3 of 860 for naming nothing (their
`subject` names the post: validate._track_v3 reads it), track-v2 and track-check-v1 14 of 781 (no `subject`; their
`why` alone). Of those 14, 12 were right out verdicts whose why said why not, as those guides ask ("When `in` is
false, say briefly why not"), and 2 answered another post (both out verdicts anyway). So an answer with no `subject`
names its post only when `in` is true (validate._track); track-v3 still checks its subject, which catches a verdict
of another post. The cases are shaped on those rows, with invented tracks and posts. The failed questions of the
older guides are asked again once (data repair reopen_failed_track_v3, v10.47: test_track_v3_checks_v1044.Reopen).
"""
from __future__ import annotations

import unittest

from insight_core.markx import validate

HEAD = ("TRACK: Local Setups\nBelongs: Running AI models on your own hardware: GPUs and machines, quantised models, "
        "inference engines and their settings, real speeds and memory on particular GPUs")


def question(title, text):
    return HEAD + validate.POST_MARK + f"Platform: rss | Source: Example Wire\nTitle: {title}\nText: {text}"


ROLLOUT = question("Orbit 4 is now rolled out to Example Workspace customers through the Orbit app",
                   "Enjoy, and thanks to the whole team for pushing to make it happen this quarter.")
LAWSUIT = question("Two states sue Example Rockets over generated images",
                   "The states accused the company of violating consumer protection laws with its image generator.")
GADGET = question("What you can do with your old, discontinued Mac Pro",
                  "Apple stopped selling it last year; owners still have options, from resale to parts and repairs.")


def check(a, q, guide):
    return validate.check("track", a, q, guide)[1]


def v2(**kw):
    return {"id": "x", "in": False, "confidence": 0.93, "subtopic": None, **kw}


class OlderGuides(unittest.TestCase):
    """track-v2 / track-check-v1: no `subject`; an out why says why not."""

    def test_an_out_verdict_that_says_why_not_is_a_verdict(self):
        for guide in ("track-v2", "track-check-v1"):
            for q, why in ((ROLLOUT, "Cloud product rollout announcement; not run on local hardware."),
                           (LAWSUIT, "Legal news about a company's AI tool; nothing about running models locally."),
                           (GADGET, "Buying and reuse advice with no local model run or setup detail.")):
                self.assertIsNone(check(v2(why=why), q, guide), (guide, why))

    def test_an_in_verdict_still_names_its_post(self):
        for guide in ("track-v2", "track-check-v1"):
            vague = v2(**{"in": True, "confidence": 0.8, "why": "A useful setup with real numbers for the track."})
            self.assertIn("names nothing", check(vague, ROLLOUT, guide), guide)
            named = v2(**{"in": True, "confidence": 0.8, "why": "Orbit 4 rolled out to Workspace customers."})
            self.assertIsNone(check(named, ROLLOUT, guide), guide)

    def test_confidence_zero_is_still_no_verdict(self):
        self.assertIn("confidence", check(v2(confidence=0, why="Not a local setup."), ROLLOUT, "track-v2"))


class TrackV3(unittest.TestCase):
    """track-v3 / track-check-v2: the post is named by `subject` (or `why`), in or out."""

    def v3(self, subject, why):
        return {"id": "x", "subject": subject, "fits": False, "matches": None, "excluded": None, "in": False,
                "confidence": 0.95, "subtopic": None, "why": why}

    def test_an_out_verdict_named_in_its_subject_is_one(self):
        a = self.v3("Orbit 4 rollout to Example Workspace customers", "Cloud product rollout; not run on local hardware.")
        for guide in ("track-v3", "track-check-v2"):
            self.assertIsNone(check(a, ROLLOUT, guide), guide)

    def test_a_verdict_of_another_post_is_refused(self):
        """The real right refusals: an answer whose subject is the batch's other post."""
        a = self.v3("Coding-agent harness comparison benchmarks", "Benchmark news; no workflow or setup detail.")
        for guide in ("track-v3", "track-check-v2"):
            self.assertIn("names nothing", check(a, LAWSUIT, guide), guide)


if __name__ == "__main__":
    unittest.main()
