"""Stealth v10.41: search inside a track's table (FIX 5) and suggested fields (FIX 6), the same code for any track.

  - search: words ANDed across a row's fields and its posts' titles, numbers as whole words ("24" is not "i5-2400"),
    a text field's filter by the same rule; the entities a row's posts name (a name's words in order, a type);
  - suggested fields: the schema planner's second guide (track-fields-v1), one question a schema version once it has
    rows; its answer checked (a kind shown, a field it lacks) and never applied; shown less the fields the schema has
    and those dismissed; Add is the owner's schema edit (a kind may then hold up to OWNER_FIELDS fields).
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import unittest

from insight_core.markx import schemas, track_brief as TB, track_fields as TF, track_things as TT, validate
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_track_briefer_0245 import TRACKS, _Briefer, v


class Pure(unittest.TestCase):
    def test_words_and_numbers_whole(self):
        w = TB.words
        self.assertEqual(w("Qwen3.8-27B on i5-2400, 24GB, $1,500"), ["qwen", "3.8", "27", "b", "on", "i", "5", "2400",
                                                                     "24", "gb", "1500"])
        self.assertEqual(w("Qwen3 235B"), ["qwen", "3", "235", "b"], "a space is no thousands separator")
        self.assertFalse(TB.has_words(w("24"), w("Core i5-2400")))
        self.assertTrue(TB.has_words(w("24 GB 27B"), w("RTX 3090 24GB with Qwen 3.8 27B")))
        self.assertTrue(TB.has_words(w("raspberry pi llm"), w("runs LLMs on a Raspberry Pi 5")), "a longer word: its start")
        self.assertFalse(TB.has_words(w("pi"), w("a pipeline")), "a short word: whole")
        self.assertFalse(TB.has_words(w("duress pin"), w("a duress password")), "every word")

    def test_a_text_field_filter_reads_words(self):
        f = {"name": "hardware", "type": "text"}
        self.assertFalse(TB._match(f, "Core i5-2400, no GPU", "eq", "24"))
        self.assertTrue(TB._match(f, "RTX 4090, 24 GB VRAM", "eq", "24"))
        self.assertTrue(TB._match(f, "RTX 4090, 24 GB VRAM", "eq", "vram 4090"))

    def test_entities_by_name_and_their_chips(self):
        pi5 = {"name": "Raspberry Pi 5", "type": "product", "words": {tuple(TB.words("Raspberry Pi 5"))}}
        qwen = {"name": "Qwen 3.8", "type": "model", "words": {tuple(TB.words("Qwen 3.8"))}}
        self.assertTrue(TB.names_entity(TB.words("Raspberry Pi"), pi5))
        self.assertFalse(TB.names_entity(TB.words("Pi Raspberry"), pi5), "in order")
        self.assertFalse(TB.names_entity(TB.words("Raspberry Pi 4"), pi5))
        ents = {"a": {"e1": pi5, "e2": qwen}, "b": {"e1": pi5}, "c": {"e2": qwen}}
        got = TB.entity_chips(ents, ["a", "b", "c"])
        self.assertEqual([(e["name"], e["rows"]) for e in got["entities"]], [("Qwen 3.8", 2), ("Raspberry Pi 5", 2)])
        self.assertEqual(got["types"], [{"type": "model", "rows": 2}, {"type": "product", "rows": 2}])
        self.assertEqual(TB.entity_chips(ents, ["c"])["entities"], [], "one row's entity is no chip")

    def test_the_fields_question_and_its_check(self):
        track = {"folder_id": "t1", "name": "T", "description": "d", "excludes": None}
        schema = TT.with_practice(TRACKS["setups"][1])
        rows = [{"kind": "setup", "fields": {"hardware": {"shown": "RTX 3090, 24 GB VRAM"}, "speed": {"shown": "40 tok/s"}}}]
        q = TF.fields_input(track, schema, 3, rows, [{"title": "A build", "text": "decode 40 tok/s, prefill 900 tok/s"}])
        self.assertTrue(q.startswith("FIELDS: t1 v3\nTRACK: T\n"))
        self.assertEqual(TF.kinds_of(q)["setup"], {"hardware", "cost", "speed", "engine", "page"})
        self.assertIn(TT.PRACTICE_KIND, TF.kinds_of(q))
        ok = {"fields": [{"kind": "setup", "name": "prefill_speed", "type": "number", "unit": "tok/s", "why": "post [1]"}]}
        self.assertEqual(validate.check("track_schema", ok, q, TF.FIELDS_GUIDE), (ok, None))
        for bad, why in ((dict(ok["fields"][0], name="speed"), "setup.speed: the kind has it"),
                         (dict(ok["fields"][0], kind="print"), "print: not a kind shown"),
                         (dict(ok["fields"][0], kind=TT.PRACTICE_KIND), f"{TT.PRACTICE_KIND} is fixed"),
                         ({**ok["fields"][0], "type": "enum", "values": ["x"]}, "setup.prefill_speed: an enum needs 2+ values")):
            with self.subTest(bad=bad):
                self.assertEqual(validate.check("track_schema", {"fields": [bad]}, q, TF.FIELDS_GUIDE)[1], why)
        self.assertEqual(schemas.schema_for("track_schema", TF.FIELDS_GUIDE), schemas.TRACK_FIELDS_SCHEMA)
        self.assertTrue(schemas.guide_body(TF.FIELDS_GUIDE).startswith("#"))

    def test_rows_shown_are_the_owners_kinds_first(self):
        rows = [{"kind": TT.PRACTICE_KIND}] * 30 + [{"kind": "setup"}] * 30
        got = TF.pick_rows(rows)
        self.assertEqual(len(got), TF.ROWS_SAMPLE + TF.PRACTICE_SAMPLE)
        self.assertEqual(got[0]["kind"], "setup")


class Flow(_Briefer):
    def setUp(self):
        super().setUp()
        clear = ("DELETE FROM mx_track_field_dismissals",)
        for q in clear:
            self.cur.execute(q)
            self.addCleanup(self.cur.execute, q)

    def two_setups(self):
        f = self.track("setups")
        self.schema(f, "setups")
        a = self.in_track(f, "Workstation build", "Two used 24 GB cards, about $1,450 all in, 14-15 tok/s.")
        b = self.in_track(f, "Old office PC", "A Core i5-2400 box with no GPU runs a tiny model at 3 tok/s.")
        self.run_planner("track_things")
        self.things(f, a, {"kind": "setup", "fields": {"hardware": v("two used 24 GB cards", "Two used 24 GB cards"),
                                                       "speed": v({"number": 14, "unit": "tok/s", "range_to": 15},
                                                                  "14-15 tok/s")}})
        self.things(f, b, {"kind": "setup", "fields": {"hardware": v("Core i5-2400 box, no GPU",
                                                                     "A Core i5-2400 box with no GPU"),
                                                       "speed": v({"number": 3, "unit": "tok/s"}, "at 3 tok/s")}})
        return f

    def table(self, f, **query):
        status, body = call("GET", f"/api/markx/tracks/{f}/things", query={"kind": "setup", **query})
        self.assertEqual(status, 200, body)
        return [x["fields"]["hardware"]["shown"] for x in body["things"]], body

    def test_search_across_a_row_and_its_titles(self):
        f = self.two_setups()
        self.assertEqual(self.table(f, q="24 GB")[0], ["two used 24 GB cards"])
        self.assertEqual(self.table(f, hardware="24")[0], ["two used 24 GB cards"], "24 is not i5-2400")
        self.assertEqual(self.table(f, q="workstation 15")[0], ["two used 24 GB cards"], "a title's words, a range's")
        self.assertEqual(self.table(f, q="office gpu")[0], ["Core i5-2400 box, no GPU"])
        self.assertEqual(self.table(f, q="office cards")[0], [], "every word")
        got, body = self.table(f, q="gpu", entity_type="model")
        self.assertEqual((got, body["search"]["entity_type"], body["chips"]["entities"]), ([], "model", []))

    def test_fields_suggested_never_applied_added_or_dismissed(self):
        self.patch_rows(1)
        f = self.two_setups()
        self.assertEqual(self.run_planner("track_schema"), 1)
        (tid, a, _b, q), = self.open_tasks("track_schema", TF.FIELDS_GUIDE)
        self.assertEqual(a, f)
        self.assertTrue(q.startswith(f"FIELDS: {f} v1\n"))
        self.assertIn("Old office PC", q)
        self.assertEqual(self.run_planner("track_schema"), 0, "one question a schema version")
        answer = {"id": "x", "fields": [
            {"kind": "setup", "name": "vram", "type": "number", "unit": "GB", "about": "GPU memory", "why": "both rows"},
            {"kind": "setup", "name": "model", "type": "text", "why": "the tiny model"}]}
        status, body = self.answer((tid, answer))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        self.assertEqual(TT.current_schema(self.cur, f)["version"], 1, "never applied")
        status, got = call("GET", f"/api/markx/tracks/{f}/schema/suggestions")
        self.assertEqual((status, [s["name"] for s in got["fields"]], got["asked_for"]), (200, ["vram", "model"], 1))
        self.assertEqual(got["fields"][0]["why"], "both rows")
        status, got = call("POST", f"/api/markx/tracks/{f}/schema/suggestions/dismiss", body={"kind": "setup", "name": "model"})
        self.assertEqual((status, [s["name"] for s in got["fields"]]), (200, ["vram"]))
        kinds = TRACKS["setups"][1]["kinds"]
        many = [dict(kinds[0], fields=kinds[0]["fields"] + [{"name": f"extra_{i}", "type": "text"} for i in range(5)]
                     + [{"name": "vram", "type": "number", "unit": "GB"}])]
        self.assertEqual(len(many[0]["fields"]), 11)
        status, view = call("PUT", f"/api/markx/tracks/{f}/schema", body={"kinds": many})
        self.assertEqual((status, view["version"], view["by"]), (200, 2, "owner"), view)
        status, got = call("GET", f"/api/markx/tracks/{f}/schema/suggestions")
        self.assertEqual((status, got["fields"]), (200, []), "added: the schema has it")
        self.assertEqual(self.run_planner("track_schema"), 0, "no row read under v2 yet")

    def patch_rows(self, n):
        was = TF.FIELDS_MIN_ROWS
        TF.FIELDS_MIN_ROWS = n
        self.addCleanup(setattr, TF, "FIELDS_MIN_ROWS", was)


if __name__ == "__main__":
    unittest.main()
