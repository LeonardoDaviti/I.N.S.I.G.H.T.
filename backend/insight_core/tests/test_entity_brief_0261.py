"""Issue 0261 (Stealth v10.31): an entity's brief, the general briefer applied to an entity (markx/entity_brief.py).

Invented names only. The entity is briefed as a track whose subject is the entity: the same things questions, checks,
reports, joins and digest as a track's; its schema is the general one, written by code.
"""
from __future__ import annotations

import json
import unittest

from insight_core.markx import entity_brief as EB, identity, track_things as TT
from insight_core.tests._db import insert_scratch_source
from insight_core.tests.test_markx_api import call
from insight_core.tests import test_track_briefer_0245 as B
from insight_core.tests.test_track_briefer_0245 import _Briefer, v


class EntityBrief(_Briefer):
    mention = B.Flow.mention   # a mention of an invented entity, as the 0245 tests write one

    def setUp(self):
        super().setUp()
        bands = identity.bands()
        was = bands.get("entities")
        bands["entities"] = dict(was or {}, brief=True)
        self.addCleanup(lambda: bands.__setitem__("entities", was) if was is not None else bands.pop("entities", None))
        self.src = insert_scratch_source(self.cur, platform="rss", enabled=True,
                                         settings_json=json.dumps({"display_name": "Zq Lab Notes"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.src,))

    def about(self, ent, title, text, *, role="subject"):
        p = self.post(title=title, text=text, source=self.src)
        e = self.mention(p, "Zqedit Mode", entity=ent)
        if role != "subject":
            self.cur.execute("UPDATE mx_mentions SET role = %s WHERE post_id = %s", (role, p))
        return p, e

    def test_the_switch_the_rule_and_the_general_schema(self):
        self.assertFalse((identity.bands().get("entities") or {}).get("brief") is False)
        p1, ent = self.about(None, "Zqedit Mode", "Zqedit Mode is an experimental mode of the Zq editor.")
        p2, _ = self.about(ent, "Turning it on", "Zqedit Mode is turned on with the flag --zq-mode in settings.")
        self.about(ent, "Only named", "A list of editors; Zqedit Mode is one.", role="mention")
        for k in range(2):
            self.about(ent, f"Note {k}", f"Zqedit Mode note {k}.")
        with self.conn.transaction():
            self.assertEqual(EB.plan_things(self.cur, roots=[ent]), 0, "4 report posts: under MIN_POSTS (5)")
        p3, _ = self.about(ent, "Benchmark", "In our test of 40 tasks Zqedit Mode cut steps from 12 to 3.")
        with self.conn.transaction():
            asked = EB.plan_things(self.cur, roots=[ent])
        self.assertEqual(asked, 5, "the five report posts, never the mention")
        s = TT.current_schema(self.cur, ent)
        self.assertEqual((s["by"], [k["kind"] for k in s["schema"]["kinds"]]),
                         ("code", [EB.WHAT, EB.HOW, TT.PRACTICE_KIND]))
        self.cur.execute("SELECT subject FROM mx_track_schemas WHERE track_id = %s", (ent,))
        self.assertEqual(self.cur.fetchone()[0], "entity")
        (_t, _a, _b, text), = [r for r in self.open_tasks("track_things") if r[1] == p1]
        self.assertIn("TRACK: Zqedit Mode", text)
        self.assertIn("what Zqedit Mode itself is", text)
        with self.conn.transaction():
            self.assertEqual(EB.plan_things(self.cur, roots=[ent]), 0, "asked once a schema version")
        # off: nothing is asked, the page has no brief
        identity.bands()["entities"]["brief"] = False
        with self.conn.transaction():
            self.assertEqual(EB.plan_things(self.cur, roots=[ent]), 0)
            self.assertIsNone(EB.view(self.cur, ent))
        identity.bands()["entities"]["brief"] = True

    def test_the_brief_cites_each_line_and_says_who_measured(self):
        p1, ent = self.about(None, "Zqedit Mode", "Zqedit Mode is an experimental mode of the Zq editor.")
        p2, _ = self.about(ent, "Turning it on", "Zqedit Mode is turned on with the flag --zq-mode in settings.")
        p3, _ = self.about(ent, "Benchmark", "In our test of 40 tasks Zqedit Mode cut steps from 12 to 3. "
                                             "Qbench Labs found it 2x faster.")
        more = [self.about(ent, f"Note {k}", f"Zqedit Mode note {k}.")[0] for k in range(2)]
        with self.conn.transaction():
            EB.plan_things(self.cur, roots=[ent])
        for p in more:
            self.things(ent, p)            # read, no row: the brief has read 5 posts (SHOW_POSTS)
        self.things(ent, p1, {"kind": EB.WHAT, "fields": {
            "definition": v("an experimental mode of the Zq editor", "an experimental mode of the Zq editor"),
            "subject": v("Zqedit Mode", "Zqedit Mode is"),
            "stage": v("experimental", "is an experimental mode"),
            "maker": v("Acme", "made by Acme")}})   # not in the post: dropped by the checks, the line stays
        self.things(ent, p2, {"kind": EB.HOW, "fields": {
            "how": v("turned on with a flag in settings", "turned on with the flag --zq-mode in settings"),
            "detail": v("--zq-mode", "the flag --zq-mode")}})
        self.things(ent, p3, {"kind": TT.PRACTICE_KIND, "fields": {
            "what": v("fewer steps per task", "Zqedit Mode cut steps from 12 to 3"),
            "result": v("steps cut from 12 to 3", "cut steps from 12 to 3"),
            "evidence": v("a test of 40 tasks", "In our test of 40 tasks")}},
            {"kind": TT.PRACTICE_KIND, "fields": {
                "what": v("faster", "found it 2x faster"),
                "result": v("2x faster on 9 runs", "found it 2x faster"),   # a figure its quote lacks: dropped
                "by": v("Qbench Labs", "Qbench Labs found it")}})
        with self.conn.transaction():
            b = EB.view(self.cur, ent, names=["Zqedit Mode"])
        (faster,) = [ln for ln in b["results"] if ln["text"].startswith("faster")]
        self.assertEqual(faster["who"], ["Qbench Labs"], "the measurer its quote names, not the poster")
        b["results"] = [ln for ln in b["results"] if ln is not faster]
        self.assertEqual([(ln["text"], ln["note"]) for ln in b["what"]],
                         [("an experimental mode of the Zq editor", "experimental")])
        self.assertEqual([(ln["text"], ln["note"]) for ln in b["how"]], [("turned on with a flag in settings", "--zq-mode")])
        (res,) = b["results"]
        self.assertEqual((res["text"], res["note"]), ("fewer steps per task → steps cut from 12 to 3", "a test of 40 tasks"),
                         "0269: what → result, the evidence apart (it gives a figure the line does not)")
        self.assertEqual(res["who"], ["Zq Lab Notes"])
        self.assertEqual([c["n"] for c in b["what"][0]["cites"] + b["how"][0]["cites"] + res["cites"]], [1, 2, 3])
        self.assertEqual(faster["cites"][0]["n"], 3)
        self.assertEqual(res["cites"][0]["post"], p3)
        self.assertIn("cut steps from 12 to 3", res["cites"][0]["quotes"])
        self.assertEqual([p["n"] for p in b["posts"]], [1, 2, 3])
        # the points: one digest-v3 question over every row, asked again only when the rows change
        with self.conn.transaction():
            self.assertEqual(EB.plan_points(self.cur, roots=[ent]), 1)
            self.assertEqual(EB.plan_points(self.cur, roots=[ent]), 0, "one waits")
        (tid, a, _b, text), = [r for r in self.open_tasks("digest", "digest-v3") if r[1] == ent]
        self.assertIn(f"PERIOD: {EB.PERIOD}", text)
        status, body = self.answer((tid, {"id": "x", "points": [
            {"text": "Zqedit Mode needs fewer steps.", "cites": [3]},
            {"text": "Zqedit Mode is turned on with a flag.", "cites": [2]}]}))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        with self.conn.transaction():
            b = EB.view(self.cur, ent, names=["Zqedit Mode"])
        self.assertEqual(b["points"], [{"text": "Zqedit Mode needs fewer steps.", "cites": [3]},
                                       {"text": "Zqedit Mode is turned on with a flag.", "cites": [2]}])
        # the entity page carries it
        status, page = call("GET", f"/api/markx/entities/{ent}")
        self.assertEqual(status, 200, page)
        self.assertEqual([ln["text"] for ln in page["brief"]["how"]], ["turned on with a flag in settings"])

    def test_a_brief_needs_five_posts_read_and_a_definition_of_the_entity_itself(self):
        """0269 (production: a phone OS's brief, from one post about its camera app, said it 'is a camera app'): a
        brief is shown only when SHOW_POSTS posts were read and a what_it_is line's subject is the entity itself; a
        line about '<entity> Camera' is that product's. Lines of the same figures and key words are one; a result
        whose 'what' is the entity's own name shows its result alone."""
        p1, ent = self.about(None, "Zqedit Mode Camera", "Zqedit Mode Camera is a camera app, version 94.")
        rest = [self.about(ent, f"Post {k}", f"Zqedit Mode post {k}: it cut steps from 12 to 3.")[0] for k in range(4)]
        with self.conn.transaction():
            EB.plan_things(self.cur, roots=[ent])
        self.things(ent, p1, {"kind": EB.WHAT, "fields": {
            "definition": v("a camera app", "is a camera app"),
            "subject": v("Zqedit Mode Camera", "Zqedit Mode Camera is"),
            "stage": v("version 94", "version 94")}})
        with self.conn.transaction():
            self.assertIsNone(EB.view(self.cur, ent, names=["Zqedit Mode"]), "1 post read")
        for k, p in enumerate(rest):
            self.things(ent, p, {"kind": TT.PRACTICE_KIND, "fields": {
                "what": v("Zqedit Mode", f"Zqedit Mode post {k}"),
                "result": v(f"cut steps from 12 to 3{' per task' if k % 2 else ''}", "it cut steps from 12 to 3")}})
        with self.conn.transaction():
            self.assertIsNone(EB.view(self.cur, ent, names=["Zqedit Mode"]),
                              "5 read, but the only definition is of the camera app")
        q = self.post(title="What it is", text="Zqedit Mode is a mode of the Zq editor.", source=self.src)
        self.mention(q, "Zqedit Mode", entity=ent)
        with self.conn.transaction():
            EB.plan_things(self.cur, roots=[ent])
        self.things(ent, q, {"kind": EB.WHAT, "fields": {
            "definition": v("a mode of the Zq editor", "a mode of the Zq editor"),
            "subject": v("Zqedit Mode", "Zqedit Mode is")}})
        with self.conn.transaction():
            b = EB.view(self.cur, ent, names=["Zqedit Mode"])
        self.assertEqual([ln["text"] for ln in b["what"]], ["a mode of the Zq editor"], "the camera app's line is not its")
        texts = sorted(ln["text"] for ln in b["results"])
        self.assertTrue(all("Zqedit Mode" not in t for t in texts), texts)
        self.assertEqual(len(texts), 2, f"the same figures and key words: one line; another word: two ({texts})")
        self.assertEqual(sum(len(ln["cites"]) for ln in b["results"]), 4, "every post the merged lines rest on")


class Checks(unittest.TestCase):
    def test_a_text_values_figures_come_from_its_own_quote(self):
        self.assertTrue(TT.figures_read("32 users at most", "max users 32,"))
        self.assertFalse(TT.figures_read("32 users on a 12 GB phone", "max users 32,"))
        self.assertTrue(TT.figures_read("cut spend by 15%", "cutting model spend by 15%"))
        self.assertTrue(TT.figures_read("1,500 USD box", "a $1 500 box"))
        self.assertTrue(TT.figures_read("16000 tokens", "a 16K window"))
        self.assertTrue(TT.figures_read("no figures here", "none"))
        f = {"name": "what", "type": "text"}
        self.assertEqual(TT.check_value(f, v("Nine users on 12 GB", "max running users nine"), "max running users nine"),
                         (None, "a figure not in its quote"))

    def test_guide_v2_asks_new_posts_only(self):
        from insight_core.markx import schemas
        # v10.41: v3 (a catalog one row) after v2; v3 keeps v2's rules
        self.assertEqual((schemas.KINDS["track_things"].guide, TT.THINGS_GUIDE), ("track-things-v3", "track-things-v3"))
        self.assertEqual(schemas.answer_guides("track_things"), ("track-things-v3", "track-things-v1",
                                                                 "track-things-v2"))
        body = schemas.guide_body("track-things-v3")
        self.assertIn("A value says only what its own quote says", body)
        self.assertIn("a result said of those is not the track's", body)
        self.assertIn("by", [f["name"] for f in TT.PRACTICE["fields"]])
