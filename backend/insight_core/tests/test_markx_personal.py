"""Stealth v10.42: the reader's interest (markx/personal.py). A row's facts and kind, what reads alone say (decayed,
smoothed against a key's share), a row's interest from taps and learned weights (a named thing beats a kind, the
owner's quant-release cases), the taps kept (newest counts, undo), and the reader's News in the personal order with
global-only one click away. Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from insight_core.markx import news_rank as R, personal as P, repo
from insight_core.tests.test_markx_api import _Api, call

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
QWEN = {"id": "qwen", "name": "Qwen3.8-Flash-Next", "type": "model", "role": "subject"}
INK = {"id": "ink", "name": "Inkling 2 Small", "type": "model", "role": "subject"}
UNSLOTH = {"id": "unsloth", "name": "Unsloth", "type": "org", "role": "actor"}
UD = {"id": "ud", "name": "Unsloth Dynamic v3.1", "type": "software", "role": "mention"}
QUANTS = {"key": "by_other:model", "words": "releases for someone else's model"}


def facts(*things, kind=QUANTS, sources=("s1",)):
    return {"things": [dict(t, posts=1) for t in things], "kind": kind, "sources": list(sources)}


class TheFacts(unittest.TestCase):
    def test_a_release_by_someone_other_than_its_maker(self):
        main = {"name": "Qwen3.8-Flash-Next", "type": "model", "maker": "Alibaba"}
        self.assertEqual(P.kind_of("new_model", main, ["Unsloth"])["key"], "by_other:model")
        self.assertEqual(P.kind_of("release_update", main, ["Unsloth"])["key"], "by_other:model")   # one kind
        self.assertEqual(P.kind_of("new_model", main, ["Alibaba"])["key"], "new_model")             # its maker
        self.assertEqual(P.kind_of("new_model", main, ["Unsloth"], ["Alibaba"])["key"], "new_model")  # ... publishes it
        self.assertEqual(P.kind_of("new_model", main, [])["key"], "new_model")                      # no one ships it
        self.assertEqual(P.kind_of("new_model", {**main, "maker": "Qwen", "name": "Qwen3.8"}, ["Qwen Team"])["key"],
                         "new_model")                                     # the maker's own name inside the thing's
        self.assertEqual(P.kind_of("new_model", {**main, "maker": None}, ["Unsloth"])["key"], "new_model")  # unknown
        self.assertEqual(P.kind_of("policy_legal", main, ["Unsloth"])["key"], "policy_legal")     # not a release
        self.assertIsNone(P.kind_of("other", None, []))
        self.assertIsNone(P.kind_of(None, None, []))

    def test_a_rows_things_subjects_first_its_best_role_each(self):
        ms = [("p1", "mention", "ud", "Unsloth Dynamic v3.1", "software", "Unsloth"),
              ("p1", "subject", "qwen", "Qwen3.8-Flash-Next", "model", "Alibaba"),
              ("p1", "actor", "unsloth", "Unsloth", "org", None),
              ("p2", "subject", "qwen", "Qwen3.8-Flash-Next", "model", "Alibaba"),
              ("p2", "compared", "x", "X", "model", None),            # a comparison is not what a row is about
              ("p2", "mention", "unsloth", "Unsloth", "org", None)]
        got = P.facts_of(ms, "new_model", ["s2", "s1", "s1"])
        self.assertEqual([(t["id"], t["role"], t["posts"]) for t in got["things"]],
                         [("qwen", "subject", 2), ("unsloth", "actor", 2), ("ud", "mention", 1)])
        self.assertEqual(got["kind"]["key"], "by_other:model")
        self.assertEqual(got["sources"], ["s1", "s2"])


class WhatReadsSay(unittest.TestCase):
    def test_acts_decay_and_one_post_is_capped(self):
        got = P.engagement([("a", "opened", NOW), ("a", "kept", NOW), ("a", "kept", NOW),
                            ("b", "opened", NOW - timedelta(days=P.HALF_LIFE_DAYS))], NOW)
        self.assertEqual(got["a"], P.POST_MAX)
        self.assertAlmostEqual(got["b"], 0.5)

    def test_read_more_than_its_share_up_less_down_weakly(self):
        rate = 0.01
        self.assertGreater(P.lift_weight(20, 200, rate), 0.9 * P.IMPLICIT_MAX * 20 / 22)   # read 10x its share, sure
        self.assertLess(P.lift_weight(0, 2000, rate), 0)                 # never opened, often shown: a skip
        self.assertLess(P.lift_weight(1, 2, 0.01), P.lift_weight(4, 8, 0.01))   # as sure as the reads behind it
        self.assertGreaterEqual(P.lift_weight(0, 10 ** 6, rate), P.IMPLICIT_MIN)   # ... weakly
        self.assertLess(P.lift_weight(1, 1, rate), P.lift_weight(20, 200, rate))   # 1 of 1: smoothed toward the rate
        self.assertEqual(P.lift_weight(5, 10, 0.0), 0.0)                 # nothing read: nothing said

    def test_a_track_is_a_mild_prior(self):
        got = P.learned({("thing", "arch"): (0.0, 0)}, 0.01, {"arch": "Local Setups"}, {("thing", "arch"): "Arch"})
        self.assertEqual(got[("thing", "arch")]["weight"], P.TRACK_PRIOR)
        self.assertEqual(got[("thing", "arch")]["why"]["track"], "Local Setups")


def tap(dim, answer, *, seed=False, name=None):
    value = (P.SEED if seed else P.LABEL[dim]) * (1 if answer == "more" else -1)
    return P.Weight(value, "seed" if seed else "reader", answer=answer, name=name)


class ARowsInterest(unittest.TestCase):
    """The owner's cases (2026-11-23): less of "a quant release for a model I do not follow", more of the Unsloth
    Dynamic v3.1 method, quants of a model I follow high."""
    WS = {("kind", QUANTS["key"]): tap("kind", "less"), ("thing", "ud"): tap("thing", "more"),
          ("thing", "ink"): tap("thing", "more")}

    def test_a_quant_release_of_a_model_not_followed_sinks(self):
        got = P.score(self.WS, facts(QWEN, UNSLOTH))
        self.assertLess(got["factor"], 1)
        self.assertEqual(got["why"], "you lowered 'releases for someone else's model'")

    def test_the_method_the_reader_raised_lifts_it_over_the_kind(self):
        got = P.score(self.WS, facts(QWEN, UNSLOTH, UD))
        self.assertGreater(got["factor"], 1.5)
        self.assertEqual(got["why"], "you follow Unsloth Dynamic v3.1")
        self.assertTrue(next(r for r in got["reasons"] if r["dim"] == "kind")["beaten"])

    def test_quants_of_a_followed_model_rise(self):
        got = P.score(self.WS, facts(INK, UNSLOTH))
        self.assertGreater(got["factor"], 1.5)
        self.assertEqual(got["why"], "you follow Inkling 2 Small")

    def test_another_kind_is_untouched_and_nothing_known_is_one(self):
        self.assertEqual(P.score(self.WS, facts(QWEN, kind={"key": "policy_legal", "words": "policy"}))["factor"], 1.0)
        self.assertEqual(P.score({}, None), {"p": 0.0, "factor": 1.0, "why": None, "reasons": []})

    def test_learned_weights_count_by_role_and_a_row_adds_one_liked_thing(self):
        ws = {("thing", "qwen"): P.Weight(0.4, "learned", why={"read": 3}),
              ("thing", "unsloth"): P.Weight(0.4, "learned", why={"read": 3}),
              ("thing", "ud"): P.Weight(0.4, "learned", why={"read": 3})}
        got = P.score(ws, facts(QWEN, UNSLOTH, UD, kind=None))
        self.assertAlmostEqual(got["p"], 0.4)                            # the most liked thing, not three
        self.assertEqual(got["why"], "you often read posts about Qwen3.8-Flash-Next")
        self.assertAlmostEqual(P.score(ws, facts(UD, kind=None))["p"], 0.4 * P.ROLE_FACTOR["mention"])

    def test_none_is_not_a_reason_and_the_factor_is_bounded(self):
        ws = {("thing", "qwen"): P.Weight(0.0, "reader", answer="none")}
        self.assertEqual(P.score(ws, facts(QWEN, kind=None))["factor"], 1.0)
        big = {("thing", "qwen"): tap("thing", "more"), ("source", "s1"): tap("source", "more"),
               ("kind", QUANTS["key"]): tap("kind", "more")}
        self.assertAlmostEqual(P.score(big, facts(QWEN))["p"], P.P_MAX)

    def test_what_a_row_offers_to_teach(self):
        got = P.teachable(facts(QWEN, UNSLOTH), ("s1", "Unsloth AI"), {("thing", "qwen"): tap("thing", "less")})
        self.assertEqual([(t["name"], t["answer"]) for t in got["things"]], [("Qwen3.8-Flash-Next", "less"),
                                                                             ("Unsloth", None)])
        self.assertEqual(got["kind"]["words"], QUANTS["words"])
        self.assertEqual(got["source"], {"id": "s1", "name": "Unsloth AI", "answer": None})


class Taught(_Api):
    def test_the_newest_tap_counts_and_undo_goes_back_to_what_was_learned(self):
        with self.conn.transaction():
            self.cur.execute("INSERT INTO mx_interest_weights (dim, key, weight, name) VALUES ('thing', 'qwen', 0.3, 'Q')")
            P.teach(self.cur, dim="thing", key="qwen", answer="more")
            self.assertEqual(P.weights(self.cur, [("thing", "qwen")])[("thing", "qwen")].value, P.LABEL["thing"])
            P.teach(self.cur, dim="thing", key="qwen", answer="less")
            self.assertEqual(P.weights(self.cur, [("thing", "qwen")])[("thing", "qwen")].value, -P.LABEL["thing"])
            P.teach(self.cur, dim="thing", key="qwen", answer="undo")
            got = P.weights(self.cur, [("thing", "qwen")])[("thing", "qwen")]
            self.assertEqual(got.by, "learned")
            self.assertAlmostEqual(got.value, 0.3, places=5)
            self.cur.execute("SELECT count(*) FROM mx_interests")
            self.assertEqual(self.cur.fetchone()[0], 3)                          # keep everything
            with self.assertRaises(ValueError):
                P.teach(self.cur, dim="row", key="x", answer="more")

    def test_the_route_teaches_and_lists(self):
        status, got = call("POST", "/api/markx/interests", body={"dim": "kind", "key": "by_other:model",
                                                                 "answer": "less", "name": "quants"})
        self.assertEqual((status, got["answer"]), (200, "less"))
        self.assertEqual(call("POST", "/api/markx/interests", body={"dim": "kind", "key": "x", "answer": "meh"})[0], 400)
        status, got = call("GET", "/api/markx/interests")
        self.assertEqual([(t["dim"], t["key"], t["answer"]) for t in got["taught"]], [("kind", "by_other:model", "less")])
        pid = self.post(title="A post")
        status, got = call("GET", f"/api/markx/posts/{pid}/interest")
        self.assertEqual((status, got["kind"], got["things"]), (200, None, []))
        self.assertEqual(got["source"]["id"], str(self.source))


class TheReadersPersonalNews(_Api):
    def keep(self, rid, *, score, why):
        run = repo.start_run(self.cur, code_version="test", config={})
        self.cur.execute("""INSERT INTO mx_news_rank (row_id, run_id, significance, fit, coverage, score, notable, why)
                            VALUES (%s, %s, 0.5, 0, 0, %s, false, %s::jsonb)""", (rid, run, score, json.dumps(why)))

    def test_the_personal_order_and_global_only(self):
        from insight_core.services.news_service import NewsService
        a, b = self.post(title="Quants of a model not followed"), self.post(title="Quants of a followed model")
        self.keep(a, score=0.6, why={"personal": facts(QWEN, UNSLOTH)})
        self.keep(b, score=0.5, why={"personal": facts(INK, UNSLOTH)})
        P.teach(self.cur, dim="kind", key=QUANTS["key"], answer="less")
        P.teach(self.cur, dim="thing", key="ink", answer="more", name="Inkling 2 Small")
        now = datetime.now(timezone.utc)
        items = [{"id": f"lead-{r}", "source_id": self.source, "source_display_name": "Src", "story": {"id": r},
                  "news": {"part": "recent", "score": 1, "first_at": now}} for r in (a, b)]
        got = NewsService.ranked(self.cur, [dict(i, news=dict(i["news"])) for i in items])
        self.assertEqual(got["order"], "personal")
        self.assertEqual([i["story"]["id"] for i in got["items"]], [b, a])
        self.assertEqual(got["items"][0]["news"]["personal"]["why"], "you follow Inkling 2 Small")
        self.assertEqual(got["items"][0]["news"]["personal"]["teach"]["source"]["name"], "Src")
        glob = NewsService.ranked(self.cur, [dict(i, news=dict(i["news"])) for i in items], "ranked")
        self.assertEqual([i["story"]["id"] for i in glob["items"]], [a, b])          # global only
        self.assertIn("personal", glob["items"][0]["news"])                          # still teachable


if __name__ == "__main__":
    unittest.main()
