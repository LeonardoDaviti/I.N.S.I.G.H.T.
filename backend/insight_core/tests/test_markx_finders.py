"""0147 (Stealth v10.13): track recall, several finders. Example posts (probes) planned once per track version,
embedded, scored by max cosine with near-misses subtracted; domain and word sets learned from ✓ items with their
thresholds; numbers with the ✓ items' units as words; the union's order and budget; "found by" on items (0203 dropped
the never-adopted entity finder, source and story priors and classifier). Synthetic data only; the DB tests run on a
database whose name ends in _test."""
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.tests._db import clear_tables
from insight_core.markx import finders, repo, schemas, tasks, tracks, validate
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_tracks import NOW, _Tracks, b64, BUILD, unit, verdict

PROBES = {"probes": [f"Example post {k}: a printed drawer organiser with the STL" for k in range(12)],
          "near_misses": ["A printer review", "A filament deal"]}


class Pure(unittest.TestCase):
    def test_the_kind_its_guide_and_its_answer(self):
        k = schemas.KINDS["probes"]
        self.assertEqual((k.guide, k.subject), ("probes-v1", "track"))
        self.assertIn("near_misses", schemas.guide_body("probes-v1"))
        self.assertIn("probes", tasks.PLANNERS)
        self.assertIsNone(validate.check("probes", PROBES, "q")[1])
        self.assertIsNotNone(validate.check("probes", {"probes": ["one"] * 3}, "q")[1])          # fewer than 12
        self.assertIn("twice", validate.check("probes", {"probes": ["same"] * 12}, "q")[1])
        self.assertIsNotNone(validate.check("probes", dict(PROBES, near_misses=["x"] * 5), "q")[1])

    def test_max_sim_with_near_miss_subtraction(self):
        self.assertEqual(finders.probe_score(0.6, None), 0.6)
        self.assertEqual(finders.probe_score(0.6, 0.5), 0.6)                  # the near-miss is further: nothing
        self.assertAlmostEqual(finders.probe_score(0.6, 0.7), 0.5)            # closer to a near-miss by 0.1: -0.1
        self.assertIsNone(finders.probe_score(None, 0.7))

    def test_domains_of_two_items_not_platforms_and_the_classes_the_description_names(self):
        pos = [["example.org", "reddit.com", "busy.com"], ["example.org", "reddit.com", "busy.com"]]
        got = finders.domain_set(pos, {"example.org": 4, "busy.com": 900}, 1000, "a reading list")
        self.assertEqual(got, ["example.org"])                                # reddit a platform, busy.com too common
        printed = finders.domain_set([], {}, 1000, "Things worth 3D printing")
        self.assertIn("printables.com", printed)
        self.assertNotIn("github.com", printed)
        self.assertIn("github.com", finders.domain_set([], {}, 1000, "open-source side projects"))
        self.assertNotIn("huggingface.co", finders.domain_set([], {}, 1000, "local AI: quantised models"))   # measured out

    def test_the_lexicon_over_represented_in_items(self):
        pos = [["tok", "vram", "the", "quant"], ["tok", "vram", "the"], ["tok", "the", "rare"]]
        df = {"tok": 4, "vram": 3, "the": 900, "quant": 2, "rare": 1}
        got = finders.lexicon(pos, df, 20000)
        self.assertEqual(got[:2], ["tok", "vram"])
        self.assertNotIn("the", got)                                          # everywhere: not over-represented
        self.assertNotIn("quant", got)                                        # in one ✓ only
        many = [f"w{k}" for k in range(50)]
        self.assertEqual(len(finders.lexicon([many] * 3, {w: 6 for w in many}, 20000)), finders.WORDS)   # the top 30

    def test_numbers_with_the_items_units_count_as_a_word(self):
        self.assertEqual(finders.units_of(["22 tok/s on an RTX 3060", "16 GB VRAM", "$300"]), {"tok/s", "gb", "$"})
        units = finders.unit_set([["22 tok/s", "12 GB"], ["48 tok/s"], ["8 GB", "$1,200"]])
        self.assertEqual(units, ["gb", "tok/s"])                              # $ in one item only
        import re
        rx = finders.units_regex(units)
        self.assertTrue(re.search(rx, "about 30 tok/s", re.I))
        self.assertTrue(re.search(rx, "a 24 GB card", re.I))
        self.assertFalse(re.search(rx, "Gbps networking", re.I))
        self.assertIsNone(finders.units_regex([]))

    def test_what_fires(self):
        prep = {"bar": 0.5}
        self.assertEqual(finders.fire({"probe": 0.47, "words": 2}, prep), ["word"])
        self.assertEqual(finders.fire({"probe": 0.44, "words": 1}, prep), [])
        self.assertEqual(finders.fire({"probe": 0.5, "domain": True, "words": 3}, prep), ["probe", "domain", "word"])

    def test_the_adopted_finders_and_the_env(self):
        self.assertEqual(finders.active(), finders.ADOPTED)
        self.assertEqual(finders.ADOPTED, ("probe", "domain", "word"))
        with mock.patch.dict(os.environ, {finders.FINDERS_ENV: "domain, entity,bogus"}):
            self.assertEqual(finders.active(), ("probe", "domain"))    # the example posts always; dropped names ignored
        off = {"bar": 0.5, "on": ("probe",)}
        self.assertEqual(finders.fire({"probe": 0.6, "domain": True, "words": 3}, off), ["probe"])

    def test_the_union_order(self):
        a = {"fired": ["probe", "domain"], "probe": 0.4}
        b = {"fired": ["probe"], "probe": 0.6}
        c = {"fired": ["word"], "probe": 0.3}
        self.assertEqual(sorted([c, b, a], key=finders.order_key, reverse=True), [a, b, c])   # count, then probe

    def test_the_budget_bar(self):
        rows = [{"probe": 1 - k / 100} for k in range(100)]
        self.assertEqual(finders.budget_bar(rows, 0.3, 0.99), 0.71)           # 30 by probe alone
        for d in rows[50:60]:
            d["fired"] = ["domain"]                                            # 10 other hits first
        self.assertEqual(finders.budget_bar(rows, 0.3, 0.99), 0.81)           # the probes fill 20
        for d in rows[60:100]:
            d["fired"] = ["domain"]                                            # 50 others: probes keep half
        self.assertEqual(finders.budget_bar(rows, 0.3, 0.99), 0.86)
        self.assertEqual(finders.budget_bar(rows, 0.3, 0.5), 0.5)             # at most the cap

class _Finders(_Tracks):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, "mx_track_probes")
        self.addCleanup(clear_tables, self.cur, "mx_track_probes")

    def probes(self, answer=PROBES):
        with self.conn.transaction():
            self.assertEqual(finders.plan_probes(self.cur), 1)
        status, body = self.lease("probes")
        self.assertEqual(status, 200, body)
        mine = [t for t in body["tasks"] if t["kind"] == "probes"]
        status, got = self.answer((mine[0]["id"], dict(answer, id="x")))
        self.assertEqual((status, got["valid"]), (200, 1), got)
        return mine[0]

    def probe_vector(self, text, v, near=False):
        self.cur.execute("UPDATE mx_track_probes SET v = %s::halfvec WHERE track_id = %s AND text = %s",
                         (repo.vector_text(v), self.folder, text))

    def label_many(self, ids, answer):
        for p in ids:
            repo.add_label(self.cur, item_kind="track", a=p, b=self.folder, answer=answer)


class Probes(_Finders):
    def test_planned_once_per_version_embedded_and_stored(self):
        self.describe()
        task = self.probes()
        self.assertTrue(task["input"].startswith("TRACK: Prints"))
        self.assertNotIn("Marked in", task["input"])                         # once a version, not once a label
        rows = finders.probe_rows(self.cur, self.folder, 1)
        self.assertEqual((sum(not r["near"] for r in rows), sum(r["near"] for r in rows)), (12, 2))
        with self.conn.transaction():
            self.assertEqual(finders.plan_probes(self.cur), 0)                # this version has its example posts
        status, body = self.lease("embed", limit=100)
        probe_tasks = [t for t in body["tasks"] if t["input"] in PROBES["probes"] + PROBES["near_misses"]]
        self.assertEqual(len(probe_tasks), 14)
        self.cur.execute("SELECT DISTINCT subject_kind, priority FROM mx_tasks WHERE id = ANY(%s::uuid[])",
                         ([t["id"] for t in probe_tasks],))
        self.assertEqual(self.cur.fetchall(), [("track_probe", -1)])
        status, got = call("POST", "/api/markx/embeddings", token=self.token,
                           body={"worker": "device-1", "model": "bge-m3", "model_sha256": BUILD,
                                 "vectors": [{"task_id": t["id"], "vector": b64(unit((k + 1, 1)))}
                                             for k, t in enumerate(probe_tasks)]})
        self.assertEqual((status, got["stored"]), (200, 14), got)
        self.assertTrue(all(r["embedded"] for r in finders.probe_rows(self.cur, self.folder, 1)))
        self.describe("Things worth 3D printing for the workshop")
        with self.conn.transaction():
            self.assertEqual(finders.plan_probes(self.cur), 1)                # a new version: asked again

    def test_max_sim_and_the_near_miss(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        self.probes()
        self.probe_vector(PROBES["probes"][0], unit((1, 1)))
        self.probe_vector(PROBES["near_misses"][0], unit((2, 1)))
        a = self.post(title="like the probe", source=self.other)
        b = self.post(title="like the near-miss", source=self.other)
        self.vector(a, unit((1, 1), (0, 0.1)))
        self.vector(b, unit((2, 1), (1, 0.5)))
        t = tracks.get(self.cur, self.folder)
        prep = finders.prepare(self.cur, t, {"in": [], "out": []}, now=NOW)
        got = {d["post_id"]: d for d in finders.score(self.cur, t, prep, ids=[a, b])}
        self.assertGreater(got[a]["probe"], 0.95)                              # the max over the probes, not the mean
        self.assertLess(got[a]["desc"], 0.2)                                   # the description alone misses it
        self.assertLess(got[b]["probe"], got[b]["probe_pos"])                  # nearer a near-miss: pulled down

    def test_before_probes_the_description_alone(self):
        self.describe()
        self.desc_vector(unit((0, 1)))
        p = self.post(title="near", source=self.other)
        self.vector(p, unit((0, 1), (1, 0.3)))
        self.plan()
        self.cur.execute("SELECT found_by, score FROM mx_track_items WHERE post_id = %s", (p,))
        found, score = self.cur.fetchone()
        self.assertEqual(found, ["probe"])
        self.assertGreater(score, 0.9)


class Learned(_Finders):
    def setUp(self):
        super().setUp()
        self.describe("Cheap local AI setups")
        self.desc_vector(unit((0, 1)))
        self.dim = 100

    def far(self):
        """A vector of its own: far from the description and from every other post."""
        self.dim += 1
        return unit((self.dim, 1))

    def passive(self, title, text=None, links=(), at=None):
        p = self.post(title=title, text=text, source=self.other, links=links, at=at)
        self.vector(p, self.far())
        return p

    def a_call(self, post, kind, guide):
        schemas.ensure_guides(self.cur)
        tid, _ = repo.add_task(self.cur, kind=kind, guide=guide, subject_kind="post", input=f"{kind} {post}", a=post)
        return repo.add_call(self.cur, task_id=tid, executor="claude-code", model="test", valid=True, answer={})

    def numbers(self, post, numbers):
        repo.add_reading(self.cur, post_id=post, guide="read-v2", call_id=self.a_call(post, "read", "read-v2"),
                         kind="report", events="one", lang="en", headline="h", reading={"main": {"numbers": numbers}})

    def prepare(self):
        t = tracks.get(self.cur, self.folder)
        return t, finders.prepare(self.cur, t, tracks.examples(self.cur, self.folder))

    # v10.16 (0177): a plan pass reads the window's counts once for every track (`prefetch` into one cache), and what
    # each track learns from them is what it learns alone.
    def scene(self):
        texts = [f"Running a quantised model on a used card {k}: 22 tok/s with llamafile and kobold" for k in range(3)]
        items = [self.passive(f"item {k}", text=x, links=[(f"https://example.com/build/{k}", "build")])
                 for k, x in enumerate(texts)]
        for k in range(10):
            self.passive(f"background {k}", text=" ".join(f"garden{k}x{j}" for j in range(40)) + " llamafile",
                         links=[(f"https://example.com/other/{k}", "x")])
        self.label_many(items, "in")
        return items

    def test_one_read_of_the_window_learns_what_each_read_learned(self):
        items = self.scene()
        now = datetime.now(timezone.utc) + timedelta(minutes=1)   # the posts are stored now
        t = tracks.get(self.cur, self.folder)
        alone = finders.learn(self.cur, t, items, now=now)
        cache = {}
        finders.prefetch(self.cur, items, now=now, cache=cache)
        seen = []
        real = type(self.cur).execute

        def counting(this, query, *a, **kw):
            seen.append(str(query))
            return real(this, query, *a, **kw)
        with mock.patch.object(type(self.cur), "execute", counting):
            shared = finders.learn(self.cur, t, items, now=now, cache=cache)
        self.assertEqual(shared, alone)
        self.assertTrue(alone["domains"], alone)
        window = [q for q in seen if "ts_stat" in q or "MATERIALIZED" in q or "count(*), COALESCE(sum(length" in q]
        self.assertEqual(window, [])                                       # every window count came from the cache

    def test_the_cache_keys_the_window(self):
        items = self.scene()
        now = datetime.now(timezone.utc) + timedelta(minutes=1)   # the posts are stored now
        t = tracks.get(self.cur, self.folder)
        cache = {}
        finders.learn(self.cur, t, items, now=now, cache=cache)
        later = finders.learn(self.cur, t, items, now=now + timedelta(days=400), cache=cache)   # a window of no post
        self.assertEqual(later, finders.learn(self.cur, t, items, now=now + timedelta(days=400)))
        self.assertEqual(later["n_posts"], 1)

    def test_a_domain_of_two_items_finds_a_post_not_its_home_page(self):
        items = [self.passive(f"item {k}", links=[(f"https://example.com/build/{k}", "build")]) for k in range(2)]
        self.label_many(items, "in")
        deep = self.passive("deep link", links=[("https://example.com/build/9", "x")])
        home = self.passive("home page", links=[("https://example.com/", "x")])
        t, prep = self.prepare()
        self.assertIn("example.com", prep["learned"]["domains"])
        got = {d["post_id"]: d["fired"] for d in finders.score(self.cur, t, prep, ids=[deep, home])}
        self.assertEqual((got[deep], got[home]), (["domain"], []))

    def test_words_of_the_items_and_numbers_with_their_units(self):
        texts = [f"Running a quantised model on a used card {k}: 22 tok/s with llamafile and kobold" for k in range(3)]
        items = [self.passive(f"item {k}", text=x) for k, x in enumerate(texts)]
        for k in range(30):
            self.passive(f"background {k}", text=" ".join(f"garden{k}x{j}" for j in range(120)))   # a month of other words
        self.label_many(items, "in")
        two = self.passive("two words", text="A post about llamafile and kobold together")
        one = self.passive("one word", text="A post about llamafile alone")
        for p in items + [one]:
            self.numbers(p, ["30 tok/s"])
        t, prep = self.prepare()
        self.assertTrue({"llamafil", "kobold"} <= set(prep["learned"]["words"]) or
                        {"llamafile", "kobold"} <= set(prep["learned"]["words"]), prep["learned"]["words"])
        self.assertEqual(prep["learned"]["units"], ["tok/s"])
        got = {d["post_id"]: d for d in finders.score(self.cur, t, prep, ids=[two, one])}
        self.assertIn("word", got[two]["fired"])
        self.assertIn("word", got[one]["fired"])                              # one word + a number in tok/s

    def test_found_by_on_items_and_the_page(self):
        items = [self.passive(f"item {k}", links=[(f"https://example.com/build/{k}", "build")]) for k in range(2)]
        self.label_many(items, "in")
        p = self.passive("links it", links=[("https://example.com/build/9", "x")])
        self.plan()
        self.cur.execute("SELECT found_by FROM mx_track_items WHERE post_id = %s", (p,))
        self.assertEqual(self.cur.fetchone()[0], ["domain"])
        self.judge(p, verdict())
        body = self.page()
        shown = next(it for it in body["discover"] if it["post_id"] == p)
        self.assertEqual(shown["found_by"], ["domain"])
        self.assertEqual(body["prefilter"]["found_by"]["domain"], 1)

    def test_the_capped_union_goes_by_finders_fired_then_probe(self):
        two = self.post(title="two finders", source=self.other, links=[("https://example.com/b/7", "b")])
        self.vector(two, unit((0, 1), (500, 0.1)))                            # near the description: the probe too
        one = self.passive("one finder", links=[("https://example.com/b/8", "b")])
        items = [self.passive(f"item {k}", links=[(f"https://example.com/b/{k}", "b")]) for k in range(2)]
        self.label_many(items, "in")
        self.plan(cap=1)
        self.assertEqual(list(self.items()), [two])
        self.assertNotEqual(two, one)


if __name__ == "__main__":
    unittest.main()
