"""0274: an entity brief's senses settled from the sense question's runs (invented answers, no database)."""
import unittest

from insight_core.markx import entity_brief as EB, schemas


def run(*groups, unclear=()):
    return ("c", {"senses": [{"m": list(g), "what": f"thing {g[0]}", "kind": "other", "maker": None} for g in groups],
                  "unclear": list(unclear)})


class Settled(unittest.TestCase):
    def test_one_run_is_not_settled(self):
        self.assertIsNone(EB.settled([run([1, 2], [3])]))

    def test_two_runs_alike(self):
        got = EB.settled([run([1, 2], [3]), run([3], [1, 2])])
        self.assertEqual([s["m"] for s in got["senses"]], [[1, 2], [3]])
        self.assertEqual(got["unclear"], [])
        self.assertEqual(got["senses"][0]["what"], "thing 1")

    def test_a_stray_mention_is_left_out_and_the_rest_settle(self):
        # three runs that never group alike: mention 7 moves between two groups
        got = EB.settled([run([6, 8, 9], [4, 5, 7], [1], [2, 3]), run([1], [2, 3, 7], [4, 5], [6, 8, 9]),
                          run([2, 3, 4, 5, 7], [6, 8, 9], [1])])
        self.assertEqual([s["m"] for s in got["senses"]], [[1], [2, 3], [4, 5], [6, 8, 9]])
        self.assertEqual(got["unclear"], [7])

    def test_an_unclear_mention_in_one_run_settles_by_the_others(self):
        got = EB.settled([run([1, 3, 5], [2]), run([1, 3], [2], unclear=[5]), run([1, 3, 5], [2])])
        self.assertEqual([s["m"] for s in got["senses"]], [[1, 3, 5], [2]])

    def test_runs_past_the_asks_are_not_read(self):
        got = EB.settled([run([1], [2]), run([1, 2]), run([1, 2]), run([1], [2])])
        self.assertEqual([s["m"] for s in got["senses"]], [[1, 2]])


class Registered(unittest.TestCase):
    def test_the_sense_guide_is_a_collide_variant(self):
        self.assertEqual(schemas.GUIDE_VARIANTS[EB.SENSE_GUIDE][0], "collide")
        self.assertIs(schemas.schema_for("collide", EB.SENSE_GUIDE), schemas.COLLIDE2_SCHEMA)
        self.assertIn(EB.SENSE_GUIDE, schemas.guide_ids())

    def test_off_by_default(self):
        self.assertFalse(EB.senses_on())


if __name__ == "__main__":
    unittest.main()
