"""0245 (built 0249, Stealth v10.27): the general track briefer. One briefer for every track: the tests run the same
code over three invented tracks of different kinds (hardware setups, printable designs, cooking recipes) to show that
nothing in it is about one track; none of these words is in the code.

  - the kinds, guides, planners and the switch (entity_bands.json tracks.briefs, default off: nothing is planned);
  - the checks: a value's quote is in the post; a number's or money's digits (and range, unit, currency) are in its own
    quote, a link inside its own quote, an enum one of its values, text at most 120 characters; a thing whose name did
    not stand is dropped; every drop kept with its reason; the salvage is idempotent;
  - the schema: proposed from the description, the general practice kind added by code, versioned, proposed again on
    a new description, the owner's edit a version of its own (the API);
  - the things: asked only for posts in the track, every window of a long post, the post's own address never offered;
    reports joined by a key value (a link, a name), a practice only within its post; by a shared entity; two practices
    naming one entity asked "same claim?" and joined on `same`;
  - the brief: digest-v2 cites rows (checked: only its rows, its figures in them), the week's issue kept with code's
    counts and the posts with no row, the quick look since the reader's look, the tables with typed filters.
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from insight_core.markx import consumers, identity, repo, schemas, tasks, track_brief as TB, track_things as TT, \
    tracks, validate
from insight_core.tests._db import clear_tables, insert_scratch_source
from insight_core.tests.test_markx_api import call
from insight_core.tests.test_markx_tracks import TRACK_TABLES, _Tracks, verdict

BRIEF_TABLES = TRACK_TABLES + ("mx_track_schemas", "mx_track_things", "mx_track_thing_reports", "mx_track_brief_asks",
                               "mx_track_seen", "mx_track_places", "mx_track_places_state", "mx_track_changes",
                               "mx_kept_pages", "mx_track_subtopic_members", "mx_track_subtopic_asks")

# three invented tracks of three different kinds, each a description and the schema Haiku would propose
TRACKS = {
    "setups": ("Home setups to run language models locally: the hardware, what it cost and how fast it runs", {
        "kinds": [{"kind": "setup", "about": "one machine that runs models", "fields": [
            {"name": "hardware", "type": "text", "key": True, "about": "the machine"},
            {"name": "cost", "type": "money", "about": "what it cost"},
            {"name": "speed", "type": "number", "unit": "tok/s", "about": "tokens a second"},
            {"name": "engine", "type": "enum", "values": ["llama.cpp", "vllm", "other"], "about": "the engine"},
            {"name": "page", "type": "link", "about": "a write-up"}]}]}),
    "prints": ("Useful things to 3D print at home and why they are worth printing", {
        "kinds": [{"kind": "print", "about": "one printable design", "fields": [
            {"name": "what", "type": "text", "key": True, "about": "the design"},
            {"name": "files", "type": "link", "key": True, "about": "the model files"},
            {"name": "material", "type": "enum", "values": ["pla", "petg", "abs", "other"], "about": "filament"},
            {"name": "print_time", "type": "number", "unit": "hours", "about": "time to print"}]}]}),
    "recipes": ("Weeknight cooking recipes with few ingredients and short times", {
        "kinds": [{"kind": "recipe", "about": "one dish", "fields": [
            {"name": "dish", "type": "text", "key": True, "about": "its name"},
            {"name": "minutes", "type": "number", "unit": "minutes", "about": "total time"},
            {"name": "cost", "type": "money", "about": "what it costs"},
            {"name": "source", "type": "link", "about": "the recipe page"}]}]}),
}


def things_input(schema, text, links=(), title="A post"):
    """A things question as plan_things writes it (the checks read it the same way)."""
    lines = ["SCHEMA: t v1", "TRACK: T", "Belongs: b", "Excludes: (none)",
             "KINDS: " + json.dumps(TT.with_practice(schema)), "", "POST", f"Title: {title}", f"Text: {text}"]
    if links:
        lines += ["Links in the post:"] + list(links)
    return "\n".join(lines)


def v(value, quote):
    return {"value": value, "quote": quote}


class Switch:
    """entity_bands.json `tracks.briefs` on for a test (off by default)."""

    def switch(self, on=True):
        bands = identity.bands()
        was = bands.get("tracks")
        bands["tracks"] = dict(was or {}, briefs=on)
        self.addCleanup(lambda: bands.__setitem__("tracks", was) if was is not None else bands.pop("tracks", None))


class Pure(Switch, unittest.TestCase):
    def test_the_kinds_guides_planners_and_the_switch(self):
        for kind, guide in (("track_schema", "track-schema-v1"), ("track_things", "track-things-v2"),
                            ("track_same", "track-same-v1")):
            self.assertEqual(schemas.KINDS[kind].guide, guide)
            self.assertTrue(schemas.guide_body(guide).startswith("#"))
            self.assertIn(kind, tasks.PLANNERS)
            self.assertEqual(consumers.CONSUMER[kind], "tracks")
        self.assertEqual(schemas.GUIDE_VARIANTS["digest-v2"][0], "digest")   # the digest kind deepened, not a second
        self.assertIn("digest-v2", schemas.guide_ids())
        self.assertIs(identity.bands()["tracks"]["briefs"], True, "owner 2026-11-20: ships ON in v10.28, measured live")
        self.assertTrue(TT.on())

    def test_figures_of_a_quote(self):
        self.assertEqual(TT.figures("14-15 tok/s"), {14.0, 15.0})
        self.assertIn(1500.0, TT.figures("$1,500 total"))
        self.assertIn(24.5, TT.figures("24,5 тыс"))
        self.assertIn(24500.0, TT.figures("24,5 тыс"))
        self.assertIn(16000.0, TT.figures("$16K CAD"))
        self.assertIn(43000.0, TT.figures("43 тысячи рублей"))
        self.assertNotIn(5000.0, TT.figures("5km away"))
        self.assertNotIn(4.0, TT.figures("24 GPUs"))

    def test_each_type_is_checked_in_its_own_quote(self):
        shown = ("Built for $1,450 with two 24 GB cards: 14-15 tok/s on llama.cpp. Write-up: "
                 "https://example.org/build-notes\nLinks in the post:\nhttps://example.org/build-notes")
        money, number = {"type": "money"}, {"type": "number"}
        enum, link, text = {"type": "enum", "values": ["llama.cpp", "other"]}, {"type": "link"}, {"type": "text"}
        ok = [(money, v({"number": 1450, "currency": "USD"}, "Built for $1,450"), {"number": 1450.0, "range_to": None,
                                                                                   "currency": "USD"}),
              (number, v({"number": 14, "unit": "tok/s", "range_to": 15}, "14-15 tok/s"),
               {"number": 14.0, "range_to": 15.0, "unit": "tok/s"}),
              (number, v({"number": 24, "unit": "GB"}, "two 24 GB cards"), {"number": 24.0, "range_to": None, "unit": "GB"}),
              (number, v({"number": 14, "unit": "tokens/s"}, "14-15 tok/s"), None),   # a unit by its first letters
              (enum, v("LLAMA.CPP", "on llama.cpp"), "llama.cpp"),
              (link, v("https://example.org/build-notes", "https://example.org/build-notes"),
               "https://example.org/build-notes"),
              (text, v("two 24 GB cards", "two 24 GB cards"), "two 24 GB cards")]
        for f, raw, want in ok:
            with self.subTest(raw=raw):
                got, why = TT.check_value(f, raw, shown)
                self.assertIsNone(why)
                if want is not None:
                    self.assertEqual(got, want)
        bad = [(money, v({"number": 1500, "currency": "USD"}, "Built for $1,450"), "number not in its quote"),
               (money, v({"number": 1450, "currency": "EUR"}, "Built for $1,450"), "currency not in its quote"),
               (money, v("$1,450", "Built for $1,450"), "money not typed"),
               (number, v({"number": 14, "range_to": 16}, "14-15 tok/s"), "range_to not in its quote"),
               (number, v({"number": 4, "unit": "GB"}, "two 24 GB cards"), "number not in its quote"),
               (number, v({"number": 24, "unit": "TB"}, "two 24 GB cards"), "unit not in its quote"),
               (number, v({"number": 14}, "14-15 tok/s, said nobody"), "quote not in the post"),
               (enum, v("vllm", "on llama.cpp"), "enum value not allowed"),
               (link, v("https://example.org/other", "https://example.org/build-notes"), "link not in its quote"),
               (link, v("example.org/build-notes", "https://example.org/build-notes"), "link: not an http(s) URL"),
               (text, v("x" * 121, "two 24 GB cards"), "text over 120 characters"),
               (text, {"value": "two cards"}, "no quote")]
        for f, raw, why in bad:
            with self.subTest(raw=raw):
                self.assertEqual(TT.check_value(f, raw, shown), (None, why))

    def test_one_salvage_for_three_kinds_of_track(self):
        posts = {
            "setups": ("My box: an old workstation with two used 24 GB cards, about $1,450 all in, gets 14-15 tok/s "
                       "with llama.cpp on a 27B model.", ["https://example.org/box"],
                       {"kind": "setup", "fields": {
                           "hardware": v("workstation with two used 24 GB cards", "two used 24 GB cards"),
                           "cost": v({"number": 1450, "currency": "USD"}, "about $1,450 all in"),
                           "speed": v({"number": 14, "unit": "tok/s", "range_to": 15}, "gets 14-15 tok/s"),
                           "engine": v("llama.cpp", "with llama.cpp"),
                           "page": v("https://example.org/box", "https://example.org/box")}}),
            "prints": ("A cable clip that snaps onto a desk edge. Printed in PETG, 2 hours. Files: "
                       "https://files.example.net/clip", ["https://files.example.net/clip"],
                       {"kind": "print", "fields": {
                           "what": v("desk-edge cable clip", "A cable clip that snaps onto a desk edge"),
                           "files": v("https://files.example.net/clip", "https://files.example.net/clip"),
                           "material": v("petg", "Printed in PETG"),
                           "print_time": v({"number": 3, "unit": "hours"}, "PETG, 2 hours")}}),   # 3 is not in it
            "recipes": ("Lemon pasta in 20 minutes for about €4.50 a plate.", [],
                        {"kind": "recipe", "fields": {
                            "dish": v("lemon pasta", "Lemon pasta"),
                            "minutes": v({"number": 20, "unit": "minutes"}, "in 20 minutes"),
                            "cost": v({"number": 4.5, "currency": "EUR"}, "about €4.50 a plate"),
                            "source": v("https://elsewhere.example/pasta", "https://elsewhere.example/pasta")}}),
        }
        for name, (text, links, thing) in posts.items():
            with self.subTest(track=name):
                q = things_input(TRACKS[name][1], text, links)
                practice = {"kind": TT.PRACTICE_KIND, "fields": {"what": v("one claim", "no such words here")}}
                ghost = {"kind": "not_asked", "fields": {"x": v("y", "z")}}
                got, err = validate.check("track_things", {"things": [thing, practice, ghost]}, q)
                self.assertIsNone(err)
                self.assertEqual([t["kind"] for t in got["things"]], [thing["kind"]])
                whys = [d["why"] for d in got["dropped"]]
                self.assertTrue(any("did not stand" in w for w in whys), whys)       # a practice whose `what` failed
                self.assertTrue(any("not asked" in w for w in whys), whys)
                again, err = validate.check("track_things", got, q)                   # idempotent (worker, server)
                self.assertIsNone(err)
                self.assertEqual(again, got)
        got, _ = validate.check("track_things", {"things": [posts["prints"][2]]},
                                things_input(TRACKS["prints"][1], posts["prints"][0], posts["prints"][1]))
        self.assertNotIn("print_time", got["things"][0]["fields"])
        self.assertIn("things[0].print_time: number not in its quote", [d["why"] for d in got["dropped"]])
        self.assertEqual(got["things"][0]["fields"]["material"]["value"], "petg")
        got, _ = validate.check("track_things", {"things": [posts["recipes"][2]]},
                                things_input(TRACKS["recipes"][1], posts["recipes"][0]))
        self.assertNotIn("source", got["things"][0]["fields"], "a link the post does not hold")
        self.assertEqual(got["things"][0]["fields"]["cost"]["value"], {"number": 4.5, "range_to": None, "currency": "EUR"})
        self.assertIsNone(validate.check("track_things", {"things": []}, things_input(TRACKS["recipes"][1], "x"))[1])

    def test_a_schema_answer_is_checked_and_the_practice_kind_added_by_code(self):
        for name, (_d, s) in TRACKS.items():
            self.assertIsNone(validate.check("track_schema", s, "TRACK: x")[1], name)
            stored = TT.with_practice(s)
            self.assertEqual(stored["kinds"][-1]["kind"], TT.PRACTICE_KIND)
            self.assertTrue(stored["kinds"][0]["fields"][0]["key"])
        one = TRACKS["recipes"][1]["kinds"][0]
        cases = {"practice_or_claim is added by code": {"kinds": [dict(one, kind=TT.PRACTICE_KIND)]},
                 "kind recipe twice": {"kinds": [one, one]},
                 "its first field is its name": {"kinds": [dict(one, fields=one["fields"][1:])]},
                 "an enum needs": {"kinds": [dict(one, fields=one["fields"] + [{"name": "diet", "type": "enum",
                                                                                "values": ["any"]}])]},
                 "not one of": {"kinds": [dict(one, fields=[dict(one["fields"][0], type="date")])]}}
        for want, answer in cases.items():
            with self.subTest(want=want):
                self.assertIn(want, validate.check("track_schema", answer, "TRACK: x")[1] or "")

    def test_a_brief_cites_only_its_rows_and_their_figures(self):
        q = ("TRACK: T\nBelongs: b\nPERIOD: p\n\nKINDS:\n- recipe: a dish\n\nROWS:\n"
             "[1] recipe (new): dish: lemon pasta · minutes: 20 minutes\n[2] recipe: dish: bean stew · minutes: 45 minutes")
        ok = {"points": [{"text": "A lemon pasta takes 20 minutes.", "cites": [1]},
                         {"text": "A bean stew takes 45 minutes, the pasta 20.", "cites": [1, 2]}]}
        self.assertIsNone(validate.check("digest", ok, q, guide="digest-v2")[1])
        self.assertIn("row 3", validate.check("digest", {"points": [{"text": "a", "cites": [3]}, ok["points"][0]]}, q,
                                              guide="digest-v2")[1])
        self.assertIn("45", validate.check("digest", {"points": [{"text": "It takes 45 minutes.", "cites": [1]},
                                                                 ok["points"][0]]}, q, guide="digest-v2")[1])
        self.assertIsNone(validate.check("digest", {"points": [{"text": "It takes 45 minutes.", "cites": [1]},
                                                               ok["points"][0]]},
                                         "TRACK: T\nSUB-TOPIC: S\n\nPOSTS:\n[1] a, 2026-11-01: x")[1],
                          "digest-v1 (a sub-topic's) keeps its own checks")

    def test_what_the_reader_is_spared(self):
        """v10.29: the brief's view keeps every value but shows what tells rows apart."""
        self.assertEqual(TT.reader_link("https://raw.githubusercontent.com/zq-o/zq-r/main/docs/A.md"),
                         "https://github.com/zq-o/zq-r/blob/main/docs/A.md")
        self.assertEqual(TT.reader_link("https://raw.githubusercontent.com/zq-o/zq-r/main"), "https://github.com/zq-o/zq-r")
        self.assertEqual(TT.reader_link("https://github.com/zq-o/zq-r.git"), "https://github.com/zq-o/zq-r")
        self.assertEqual(TT.reader_link("https://github.com/zq-o/zq-r/raw/main/x.js"), "https://github.com/zq-o/zq-r/blob/main/x.js")
        self.assertEqual(TT.reader_link("https://github.com/zq-o/zq-r/tree/main/sub"), "https://github.com/zq-o/zq-r/tree/main/sub")
        mem = {"name": "memory", "type": "number", "unit": "GB"}
        self.assertEqual(TT.shown_value(mem, {"number": 22}), "22 GB", "a bare number takes its field's unit")
        self.assertEqual(TT.shown_value(mem, {"number": 600, "unit": "MB"}), "600 MB")
        kind = {"kind": "gadget", "fields": [{"name": "name", "type": "text"}, {"name": "engine", "type": "enum",
                                                                                 "values": ["a", "other"]},
                                             {"name": "price", "type": "money"}, {"name": "site", "type": "link"}]}
        val = lambda x: {"value": x, "quote": str(x), "post": "p"}
        row = lambda i, **f: {"id": i, "kind": "gadget", "fields": {k: val(x) for k, x in f.items()},
                              "first_at": None, "last_at": None, "found_at": None}
        self.assertNotIn("engine", TB.thing_view(kind, row("t", name="X", engine="other"), [], {})["fields"],
                         'a choice of "other" says nothing')
        pr = lambda i, **f: dict(row(i, **f), kind=TT.PRACTICE_KIND)
        got = TB.thing_view(TT.PRACTICE, pr("p", what="Q", result="Runs on about 18 GB", evidence="~18GB"), [], {})
        self.assertNotIn("evidence", got["fields"], "evidence that only repeats its result's figures")
        got = TB.thing_view(TT.PRACTICE, pr("p", what="Q", result="1.8x faster", evidence="2000 tokens/s"), [], {})
        self.assertIn("evidence", got["fields"])
        # quiet columns: 5+ rows, a column filled in under 20% of them, or one choice in over 60%
        rows = [row(f"t{i}", name=f"N{i}", engine="a", site="https://x.example/" + str(i), **({"price": {"number": 9}} if i == 0 else {}))
                for i in range(6)]
        views = [TB.thing_view(kind, r, [], {}) for r in rows]
        self.assertEqual(TB._quiet(kind["fields"], views), {"engine", "price"})
        self.assertEqual(TB._quiet(kind["fields"], views[:4]), set(), "a short section shows every column")
        # practices: inside the thing their post gave, or not shown when they say nothing to try or check
        kinds = {"gadget": kind, TT.PRACTICE_KIND: TT.PRACTICE}
        rows = [row("g1", name="G"), pr("p1", what="Feature", result="works"), pr("p2", what="An opinion"),
                pr("p3", what="Elsewhere", result="2x")]
        rs = {"g1": [{"post": "A"}], "p1": [{"post": "A"}], "p2": [{"post": "B"}], "p3": [{"post": "C"}]}
        secs = TB._sections(kinds, rows, rs, {})
        self.assertEqual([(s["kind"], [t["id"] for t in s["things"]], s["inside"], s["quiet"]) for s in secs],
                         [("gadget", ["g1"], 0, 0), (TT.PRACTICE_KIND, ["p3"], 1, 1)])
        self.assertEqual([p["id"] for p in secs[0]["things"][0]["practices"]], ["p1"])
        pts = TB._point_views({"points": [{"text": "x", "cites": ["p1", "g1", "p3"]}]}, ["g1", "p3"], TB._hosts(secs))
        self.assertEqual(pts[0]["cites"], [{"thing": "g1", "n": 1}, {"thing": "p3", "n": 2}], "a folded practice cites its thing")

    def test_weeks_and_filters(self):
        self.assertEqual(TB.monday(datetime(2026, 11, 22, 23, 0, tzinfo=timezone.utc)), date(2026, 11, 16))
        self.assertEqual(TB.parse_week("2026-11-18"), date(2026, 11, 16))
        start, end = TB.bounds(date(2026, 11, 16))
        self.assertEqual((end - start).days, 7)
        money = {"type": "money"}
        self.assertTrue(TB._match(money, {"number": 1450, "currency": "USD"}, "max", "1500"))
        self.assertFalse(TB._match(money, {"number": 1450, "range_to": 1600, "currency": "USD"}, "max", "1500"))
        self.assertTrue(TB._match(money, {"number": 1450, "currency": "USD"}, "currency", "usd"))
        self.assertTrue(TB._match({"type": "number"}, {"number": 20}, "min", "15"))
        self.assertTrue(TB._match({"type": "enum"}, "petg", "eq", "pla,PETG"))
        self.assertTrue(TB._match({"type": "text"}, "Lemon pasta", "eq", "pasta"))


class _Briefer(Switch, _Tracks):
    def setUp(self):
        super().setUp()
        clear_tables(self.cur, BRIEF_TABLES)
        self.addCleanup(clear_tables, self.cur, BRIEF_TABLES)
        self.switch()
        self.addCleanup(self.cur.execute, "DELETE FROM mx_entities WHERE name LIKE 'Zq%%'")

    def track(self, name):
        """A new topic track (its own folder and active source) described as TRACKS[name]: its folder id."""
        self.cur.execute("INSERT INTO folders (name, kind) VALUES (%s, 'track') RETURNING id::text",
                         (f"{name} {uuid.uuid4().hex[:6]}",))
        f = self.cur.fetchone()[0]
        self.addCleanup(self.cur.execute, "DELETE FROM folders WHERE id = %s", (f,))
        src = insert_scratch_source(self.cur, platform="rss", enabled=True,
                                    settings_json=json.dumps({"display_name": f"{name} blog"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (src,))
        self.cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (f, src))
        with self.conn.transaction():
            tracks.set_topic(self.cur, f, description=TRACKS[name][0])
        self.sources = getattr(self, "sources", {})
        self.sources[f] = src
        return f

    def in_track(self, f, title, text, *, at=None, links=()):
        """A post of the track's source, judged in."""
        p = self.post(title=title, text=text, source=self.sources[f], at=at, links=links)
        self.plan(days=None)
        self.cur.execute("SELECT task_id FROM mx_track_items WHERE track_id = %s AND post_id = %s", (f, p))
        status, body = self.answer((self.cur.fetchone()[0], verdict(why=f"{title}: {text}"[:200])))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        return p

    def run_planner(self, kind):
        with self.conn.transaction():
            return tasks.PLANNERS[kind](self.cur)

    def open_tasks(self, kind, guide=None):
        self.cur.execute("""SELECT id::text, a::text, b::text, input FROM mx_tasks WHERE kind = %s AND status = 'open'
                              AND (%s::text IS NULL OR guide = %s) ORDER BY created_at, id""", (kind, guide, guide))
        return self.cur.fetchall()

    def schema(self, f, name):
        self.run_planner("track_schema")
        (tid, a, _b, text), = [r for r in self.open_tasks("track_schema") if r[1] == f]
        self.assertIn(f"Belongs: {TRACKS[name][0]}", text)
        status, body = self.answer((tid, dict(TRACKS[name][1], id="x")))
        self.assertEqual((status, body["valid"]), (200, 1), body)

    def things(self, f, post, *things):
        """The post's (first window's) things question answered: its task id."""
        rows = [r for r in self.open_tasks("track_things") if r[1] == post and r[2] == f]
        status, body = self.answer((rows[0][0], {"id": "x", "things": list(things)}))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        return rows[0][0]


class Flow(_Briefer):
    def test_off_nothing_is_planned_or_built(self):
        self.switch(False)
        f = self.track("recipes")
        self.assertEqual(self.run_planner("track_schema"), 0)
        self.assertEqual(self.run_planner("track_things"), 0)
        status, body = call("GET", f"/api/markx/tracks/{f}/schema")
        self.assertEqual((status, body["on"], body["schema"]), (200, False, None))
        status, body = call("GET", f"/api/markx/tracks/{f}/brief", query={"since": "seen"})
        self.assertEqual((status, body["on"], body["nothing_new"]), (200, False, True))
        self.assertEqual(TB.keep_issues(self.cur)["built"], [])

    def test_three_tracks_one_briefer(self):
        """Every kind of track goes through the same code: schema, things, checks, rows."""
        made = {}
        for name in TRACKS:
            f = self.track(name)
            self.schema(f, name)
            made[name] = f
        for name, f in made.items():
            got = TT.current_schema(self.cur, f)
            self.assertEqual((got["version"], got["by"], got["track_version"]), (1, "haiku", 1))
            self.assertEqual([k["kind"] for k in got["schema"]["kinds"]],
                             [TRACKS[name][1]["kinds"][0]["kind"], TT.PRACTICE_KIND])
        self.assertEqual(self.run_planner("track_schema"), 0, "one schema a description")
        posts = {
            "setups": ("Workstation build", "Two used 24 GB cards, about $1,450 all in, 14-15 tok/s with llama.cpp.",
                       {"kind": "setup", "fields": {"hardware": v("two used 24 GB cards", "Two used 24 GB cards"),
                                                    "cost": v({"number": 1450, "currency": "USD"}, "about $1,450 all in"),
                                                    "speed": v({"number": 14, "unit": "tok/s", "range_to": 15},
                                                               "14-15 tok/s")}}),
            "prints": ("Desk clip", "A cable clip that snaps onto a desk edge, printed in PETG in 2 hours.",
                       {"kind": "print", "fields": {"what": v("desk cable clip", "A cable clip that snaps onto a desk edge"),
                                                    "material": v("petg", "printed in PETG"),
                                                    "print_time": v({"number": 2, "unit": "hours"}, "in 2 hours")}}),
            "recipes": ("Lemon pasta", "Lemon pasta in 20 minutes for about €4.50 a plate.",
                        {"kind": "recipe", "fields": {"dish": v("lemon pasta", "Lemon pasta"),
                                                      "minutes": v({"number": 20, "unit": "minutes"}, "in 20 minutes"),
                                                      "cost": v({"number": 4.5, "currency": "EUR"}, "about €4.50")}}),
        }
        ids = {name: self.in_track(made[name], title, text) for name, (title, text, _t) in posts.items()}
        self.assertGreaterEqual(self.run_planner("track_things"), 3)
        for name, (_ti, _te, thing) in posts.items():
            self.things(made[name], ids[name], thing)
            (row,) = TT.current(self.cur, made[name])
            self.assertEqual(row["kind"], thing["kind"])
            self.assertEqual(set(row["fields"]), set(thing["fields"]))
            self.assertEqual({x["post"] for x in row["fields"].values()}, {ids[name]})
        status, body = call("GET", f"/api/markx/tracks/{made['setups']}/things",
                            query={"kind": "setup", "cost.max": "1500", "cost.currency": "USD", "speed.min": "10"})
        self.assertEqual((status, body["count"]), (200, 1), body)
        self.assertEqual(body["things"][0]["fields"]["speed"]["shown"], "14-15 tok/s")
        self.assertEqual(body["things"][0]["posts"][0]["id"], ids["setups"])
        self.assertEqual(call("GET", f"/api/markx/tracks/{made['setups']}/things",
                              query={"kind": "setup", "cost.max": "1000"})[1]["count"], 0)
        self.assertEqual(call("GET", f"/api/markx/tracks/{made['prints']}/things",
                              query={"kind": "print", "material": "pla,petg"})[1]["count"], 1)
        self.assertEqual(call("GET", f"/api/markx/tracks/{made['recipes']}/things",
                              query={"kind": "recipe", "minutes.min": "x"})[0], 400)
        self.assertEqual(call("GET", f"/api/markx/tracks/{made['recipes']}/things",
                              query={"kind": "recipe", "spice.min": "1"})[0], 400)
        self.assertEqual(call("GET", f"/api/markx/tracks/{made['recipes']}/things", query={"kind": "setup"})[0], 400)

    def test_questions_windows_and_the_posts_own_address(self):
        f = self.track("prints")
        self.schema(f, "prints")
        self.post(title="Not judged", source=self.sources[f])   # not in the track until judged in
        long_text = ("A wall hook for headphones. " * 300) + "Files: https://files.example.net/hook"
        p = self.in_track(f, "Headphone hook", long_text, links=[("https://files.example.net/hook", "files")])
        self.cur.execute("SELECT url FROM posts WHERE id = %s", (p,))
        own = self.cur.fetchone()[0]
        self.cur.execute("UPDATE posts SET content = content || ' Seen at ' || url WHERE id = %s", (p,))
        added = self.run_planner("track_things")
        rows = [r for r in self.open_tasks("track_things") if r[2] == f]
        self.assertEqual({r[1] for r in rows}, {p}, "only posts in the track")
        self.assertEqual(added, len(rows))
        self.assertGreater(len(rows), 1, "a long post: one question a window")
        self.assertTrue(all(r[3].startswith(f"SCHEMA: {f} v1\n") for r in rows))
        self.assertEqual(sorted(r[3].split("\nWindow: ")[1][:6] for r in rows), ["1 of 3", "2 of 3", "3 of 3"])
        for r in rows:
            self.assertNotIn(own, r[3], "the post's own address is never offered")
            self.assertIn("Links in the post:\nhttps://files.example.net/hook", r[3])
        self.assertEqual(self.run_planner("track_things"), 0, "asked once a schema version")
        # the owner's schema: a version of its own, every post asked again
        kinds = [dict(TRACKS["prints"][1]["kinds"][0], about="one design to print")]
        status, body = call("PUT", f"/api/markx/tracks/{f}/schema", body={"kinds": kinds})
        self.assertEqual((status, body["version"], body["by"]), (200, 2, "owner"), body)
        self.assertEqual(body["schema"]["kinds"][-1]["kind"], TT.PRACTICE_KIND)
        self.assertEqual(call("PUT", f"/api/markx/tracks/{f}/schema", body={"kinds": []})[0], 400)
        self.assertGreater(self.run_planner("track_things"), 0)
        self.assertTrue(any(r[3].startswith(f"SCHEMA: {f} v2\n") for r in self.open_tasks("track_things")))
        # a new description proposes again
        with self.conn.transaction():
            tracks.set_topic(self.cur, f, description="Practical prints for the kitchen and the desk")
        self.assertEqual(call("GET", f"/api/markx/tracks/{f}/schema")[1]["stale"], True)
        self.assertEqual(self.run_planner("track_schema"), 1)

    def test_reports_join_by_key_and_a_practice_only_in_its_post(self):
        f = self.track("prints")
        self.schema(f, "prints")
        link = "https://files.example.net/clip"
        a = self.in_track(f, "Clip", f"A desk clip for cables. Printed in PLA. {link}", links=[(link, "files")])
        b = self.in_track(f, "Remix", f"My remix of the clip at {link}: printed in PETG this time.",
                          links=[(link, "files")])
        self.run_planner("track_things")
        claim = {"kind": TT.PRACTICE_KIND, "fields": {"what": v("print cable clips in PETG", "printed in PETG")}}
        self.things(f, a, {"kind": "print", "fields": {"what": v("desk clip for cables", "A desk clip for cables"),
                                                      "files": v(link, link), "material": v("pla", "Printed in PLA")}})
        self.things(f, b, {"kind": "print", "fields": {"what": v("clip remix", "My remix of the clip"),
                                                      "files": v(link, link), "material": v("petg", "printed in PETG")}},
                    claim)
        prints = TT.current(self.cur, f, "print")
        self.assertEqual(len(prints), 1, "one link, one thing")
        rs = TT.reports(self.cur, f, [prints[0]["id"]])[prints[0]["id"]]
        self.assertEqual({r["post"] for r in rs}, {a, b})
        self.assertEqual(prints[0]["fields"]["material"]["value"], "petg", "the newest post's value")
        self.assertEqual(len(TT.current(self.cur, f, TT.PRACTICE_KIND)), 1)

    def test_an_explainer_that_links_a_release_joins_its_row(self):
        """v10.29: a page listing many items keeps each item's anchor (two releases on one page stay two rows); a post
        that gives one thing is that thing's page, so a later post linking that address joins its row."""
        self.assertEqual(TT.norm_url("https://Zq.example/releases#2026111800"), "zq.example/releases#2026111800")
        self.assertEqual(TT.norm_url("https://nitter.local/zq/status/1#m"), "nitter.local/zq/status/1")
        self.assertEqual(TT.norm_url("https://zq.example/a/#comments"), "zq.example/a")
        f = self.track("recipes")
        self.schema(f, "recipes")
        rel = {}
        for name, dish in (("stew", "bean stew"), ("soup", "tomato soup")):
            p = self.in_track(f, f"{dish} notes", f"Release notes: {dish} in 30 minutes.")
            self.cur.execute("UPDATE posts SET url = %s, normalized_url = %s WHERE id = %s",
                             (f"https://cook.example/menu#{name}", f"https://cook.example/menu#{name}", p))
            rel[name] = p
        self.run_planner("track_things")
        for name, dish in (("stew", "bean stew"), ("soup", "tomato soup")):
            self.things(f, rel[name], {"kind": "recipe", "fields": {"dish": v(dish, dish.capitalize())}})
        why = self.in_track(f, "Why this stew works", "The slow simmer is what makes it: https://cook.example/menu#stew")
        self.run_planner("track_things")
        self.things(f, why, {"kind": "recipe", "fields": {
            "dish": v("slow simmer stew", "The slow simmer"),
            "source": v("https://cook.example/menu#stew", "https://cook.example/menu#stew")}})
        things = TT.current(self.cur, f, "recipe")
        self.assertEqual(len(things), 2, "two items of one page stay two rows; the explainer joins the stew's")
        rs = TT.reports(self.cur, f)
        stew = next(t for t in things if any(r["post"] == rel["stew"] for r in rs[t["id"]]))
        self.assertEqual({r["post"] for r in rs[stew["id"]]}, {rel["stew"], why})

    def test_entity_joins_and_same_claim_questions(self):
        f = self.track("setups")
        self.schema(f, "setups")
        a = self.in_track(f, "Box one", "Zqbox 9 runs a 27B model at 30 tok/s. Undervolting halves the power draw.")
        b = self.in_track(f, "Box two", "The ZQBOX-9 does 28 tok/s. Undervolting halves the power draw of the Zqbox 9.")
        ent = self.mention(a, "Zqbox 9")
        self.mention(b, "ZQBOX-9", entity=ent)
        self.run_planner("track_things")
        self.things(f, a, {"kind": "setup", "fields": {"hardware": v("Zqbox 9", "Zqbox 9 runs a 27B model")}},
                    {"kind": TT.PRACTICE_KIND, "fields": {"what": v("undervolt to halve power",
                                                                    "Undervolting halves the power draw")}})
        self.things(f, b, {"kind": "setup", "fields": {"hardware": v("ZQBOX 9 box", "The ZQBOX-9 does 28 tok/s")}},
                    {"kind": TT.PRACTICE_KIND, "fields": {"what": v("undervolting saves power",
                                                                    "Undervolting halves the power draw of the Zqbox 9")}})
        self.assertEqual(len(TT.current(self.cur, f, "setup")), 2, "the key texts differ")
        with self.conn.transaction():
            self.assertEqual(TT.refresh(self.cur), {})   # neither key text is the entity's name: no entity join
        self.cur.execute("""UPDATE mx_track_thing_reports SET field_values = jsonb_set(field_values, '{hardware,value}',
                            '"ZQBOX-9"') WHERE post_id = %s AND field_values ? 'hardware'""", (b,))
        with self.conn.transaction():
            self.assertEqual(TT.refresh(self.cur), {f: 1})
        setups = TT.current(self.cur, f, "setup")
        self.assertEqual(len(setups), 1)
        self.cur.execute("SELECT merged_by FROM mx_track_things WHERE status = 'merged'")
        self.assertEqual(self.cur.fetchone()[0], "entity")
        # the two practices name the same entity in their quotes: one "same claim?" question, joined on `same`
        self.assertEqual(self.run_planner("track_same"), 0, "only b's practice quote names the entity")
        self.cur.execute("""UPDATE mx_track_thing_reports SET field_values = jsonb_set(field_values, '{what,quote}',
                            '"Zqbox 9 runs a 27B model at 30 tok/s. Undervolting halves the power draw"')
                             WHERE post_id = %s AND field_values ? 'what'""", (a,))
        self.assertEqual(self.run_planner("track_same"), 1)
        self.assertEqual(self.run_planner("track_same"), 0, "asked once a pair")
        (tid, x, y, text), = self.open_tasks("track_same")
        self.assertIn("A: what:", text)
        status, body = self.answer((tid, {"id": "x", "same": True, "why": "One undervolting claim."}))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        self.assertEqual(len(TT.current(self.cur, f, TT.PRACTICE_KIND)), 1)

    def mention(self, post, name, *, entity=None):
        with self.conn.transaction():
            task_id, _ = tasks.entities_task(self.cur, post)
            cid = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                answer={"entities": []})
            repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=cid, mentions=[
                {"span": name, "name": name, "name_key": tasks.name_key(name), "type": "product", "role": "subject",
                 "maker": None, "family": None, "version": None, "variant": None, "size": None, "build": None}])
            if entity is None:
                self.cur.execute("""INSERT INTO mx_entities (type, name, key, level, status)
                                    VALUES ('product', %s, %s, 'thing', 'provisional') RETURNING id::text""",
                                 (name, tasks.name_key(name) + uuid.uuid4().hex[:4]))
                entity = self.cur.fetchone()[0]
            self.cur.execute("UPDATE mx_mentions SET entity_id = %s WHERE post_id = %s", (entity, post))
        return entity

    def test_the_weekly_issue_and_the_quick_look(self):
        f = self.track("recipes")
        self.schema(f, "recipes")
        now = datetime.now(timezone.utc)
        last = TB.monday(now) - timedelta(weeks=1)
        mid = datetime.combine(last, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=2)
        a = self.in_track(f, "Pasta", "Lemon pasta in 20 minutes.", at=mid)
        b = self.in_track(f, "Stew", "Bean stew in 45 minutes for about €3 a plate.", at=mid + timedelta(hours=3))
        c = self.in_track(f, "Chat", "What do you all cook on Tuesdays?", at=mid + timedelta(hours=5))
        self.run_planner("track_things")
        self.things(f, a, {"kind": "recipe", "fields": {"dish": v("lemon pasta", "Lemon pasta"),
                                                       "minutes": v({"number": 20, "unit": "minutes"}, "in 20 minutes")}})
        self.things(f, b, {"kind": "recipe", "fields": {"dish": v("bean stew", "Bean stew"),
                                                       "minutes": v({"number": 45, "unit": "minutes"}, "in 45 minutes"),
                                                       "cost": v({"number": 3, "currency": "EUR"}, "about €3 a plate")}})
        self.things(f, c)
        # the brief: the digest planner asks digest-v2 over the week's rows
        self.run_planner("digest")
        briefs = [r for r in self.open_tasks("digest", "digest-v3") if r[1] == f]
        self.assertEqual(len(briefs), 1)
        q = briefs[0][3]
        self.assertIn(f"PERIOD: the week of {last.isoformat()}", q)
        self.assertIn("[1] recipe (new): dish: bean stew · minutes: 45 minutes · cost: 3 EUR", q)
        self.assertEqual(self.run_planner("digest"), 0, "the same rows: asked once")
        bad = {"id": "x", "points": [{"text": "A stew takes 50 minutes.", "cites": [1]},
                                     {"text": "Pasta is quick.", "cites": [2]}]}
        status, body = self.answer((briefs[0][0], bad))
        self.assertEqual(body["valid"], 0, "a figure in none of its rows")
        good = {"id": "x", "points": [{"text": "A bean stew takes 45 minutes at 3 EUR a plate.", "cites": [1]},
                                      {"text": "Lemon pasta is ready in 20 minutes.", "cites": [2]}]}
        status, body = self.answer((briefs[0][0], good))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        # the week's issue, kept by the jobs process
        self.assertTrue(TB.missing(self.cur))
        with self.conn.transaction():
            built = TB.keep_issues(self.cur)["built"]
        self.assertIn(f"{f}:{last.isoformat()}", built)
        self.assertFalse(TB.missing(self.cur))
        status, issue = call("GET", f"/api/markx/tracks/{f}/brief", query={"week": (last + timedelta(days=3)).isoformat()})
        self.assertEqual(status, 200, issue)
        self.assertTrue(issue["week"]["closed"])
        (sec,) = issue["sections"]
        self.assertEqual((sec["kind"], sec["header"], sec["count"], sec["new"]), ("recipe", "Recipe (2)", 2, 2))
        self.assertEqual([p["text"] for p in issue["points"]], [p["text"] for p in good["points"]])
        cited = {c["thing"] for p in issue["points"] for c in p["cites"]}
        self.assertEqual(cited, {t["id"] for t in sec["things"]})
        self.assertEqual([p["id"] for p in issue["also"]], [c], "the post that gave no row")
        self.assertEqual(issue["counts"], {"things": 2, "new": 2, "posts": 2, "also": 1})
        self.assertFalse(issue["updated"])
        # a correction after the week closed: built again, marked updated (keep everything)
        d = self.in_track(f, "Stew again", "Bean stew in 45 minutes, now with lentils.", at=mid + timedelta(hours=8))
        self.run_planner("track_things")
        self.things(f, d, {"kind": "recipe", "fields": {"dish": v("bean stew", "Bean stew"),
                                                       "minutes": v({"number": 45, "unit": "minutes"}, "in 45 minutes")}})
        self.assertTrue(TB.missing(self.cur))
        from insight_core.markx import jobs
        from insight_core.tests._db import db_url
        got = jobs.Jobs(db_url())._keep_track_briefs()                       # the jobs process's own path
        self.assertEqual(got["built"], [f"{f}:{last.isoformat()}"], got)
        issue = call("GET", f"/api/markx/tracks/{f}/brief", query={"week": last.isoformat()})[1]
        self.assertTrue(issue["updated"])
        self.assertEqual(issue["counts"]["things"], 2, "the same stew, one more post")
        # the quick look: since the reader's look, only what was found after it
        call("POST", f"/api/markx/tracks/{f}/seen", body={})
        status, look = call("GET", f"/api/markx/tracks/{f}/brief", query={"since": "seen"})
        self.assertEqual((status, look["nothing_new"], look["last_issue"]), (200, True, last.isoformat()), look)
        e = self.in_track(f, "Soup", "Tomato soup in 25 minutes.")
        self.run_planner("track_things")
        self.things(f, e, {"kind": "recipe", "fields": {"dish": v("tomato soup", "Tomato soup"),
                                                       "minutes": v({"number": 25, "unit": "minutes"}, "in 25 minutes")}})
        old = self.in_track(f, "Old curry", "Red curry in 35 minutes.", at=mid)   # read after the look, posted last week
        self.run_planner("track_things")
        self.things(f, old, {"kind": "recipe", "fields": {"dish": v("red curry", "Red curry"),
                                                         "minutes": v({"number": 35, "unit": "minutes"}, "in 35 minutes")}})
        look = call("GET", f"/api/markx/tracks/{f}/brief", query={"since": "seen"})[1]
        self.assertFalse(look["nothing_new"])
        self.assertEqual([t["fields"]["dish"]["value"] for s in look["sections"] for t in s["things"]], ["tomato soup"],
                         "v10.29: a thing from an older post, found since the look, is in the tables, not new")
        self.assertEqual(look["points"], [], "last week's points cite none of the new things")
        self.assertEqual(look["weeks"], [TB.monday(now).isoformat(), last.isoformat()], "the issue strip, newest first")
        # the rail's count (v10.28): things since the look; none for a track not opened in 30 days
        counts = call("GET", "/api/markx/tracks/counts")[1]["by_track"]
        self.assertEqual(counts[f]["things"], 1)
        self.assertEqual(TB.new_count(self.cur, f, now=now + timedelta(days=31)), 0)
        # 0271: "Since you looked" reads the track's lines from the quick look; the reader's one look moves the track's
        from insight_core.markx import track_subtopics as TS
        seen = datetime.fromisoformat(TS.seen(self.cur, f)["track"])
        got = TB.since_lines(self.cur, f, seen)
        self.assertEqual((got["new"], got["lines"][0]["text"].lower()), (1, "tomato soup"), got)
        self.assertTrue(got["name"].startswith("recipes"))
        later = datetime.now(timezone.utc) + timedelta(minutes=1)
        with self.conn.transaction():
            TS.look_all(self.cur, now=later)
        self.assertEqual(TS.seen(self.cur, f)["track"], later.isoformat(), "the later of its own look and the reader's")
        self.assertEqual(call("GET", "/api/markx/tracks/counts")[1]["by_track"][f]["things"], 0)
        self.switch(False)
        self.assertNotIn("things", call("GET", "/api/markx/tracks/counts")[1]["by_track"][f], "off: the shape as before")
        self.switch(True)
        self.assertEqual(call("GET", f"/api/markx/tracks/{f}/brief", query={"since": "yesterday"})[0], 400)
        self.assertEqual(call("GET", f"/api/markx/tracks/{f}/brief", query={"week": "soon"})[0], 400)
        self.assertEqual(call("GET", f"/api/markx/tracks/{uuid.uuid4()}/brief", query={"week": last.isoformat()})[0], 404)

    def test_points_about_rows_that_left_the_week_are_not_shown_and_the_week_is_asked_again(self):
        """0269 (production: a week's points asked in the morning cited old rows that re-dating their posts moved out
        of the week): a point is shown only when every row it cites is in the issue's sections; the week in progress
        whose brief's cited rows mostly left is asked again within BRIEF_EVERY."""
        f = self.track("recipes")
        self.schema(f, "recipes")
        now = datetime.now(timezone.utc)
        week = TB.monday(now)
        start = datetime.combine(week, datetime.min.time(), tzinfo=timezone.utc)
        dishes = [("Pasta", "lemon pasta", 20), ("Stew", "bean stew", 45), ("Soup", "tomato soup", 25),
                  ("Curry", "red curry", 35)]
        posts = [self.in_track(f, title, f"{dish.capitalize()} in {mins} minutes.", at=start + (now - start) * (k + 1) / 10)
                 for k, (title, dish, mins) in enumerate(dishes)]
        self.run_planner("track_things")
        for p, (_title, dish, mins) in zip(posts, dishes):
            self.things(f, p, {"kind": "recipe", "fields": {"dish": v(dish, dish.capitalize()),
                                                           "minutes": v({"number": mins, "unit": "minutes"},
                                                                        f"in {mins} minutes")}})
        self.run_planner("digest")
        (brief,) = [r for r in self.open_tasks("digest", "digest-v3") if r[1] == f]
        n = {d: next(int(ln[1:ln.index("]")]) for ln in brief[3].splitlines() if ln.startswith("[") and d in ln)
             for _t, d, _m in dishes}
        answer = {"id": "x", "points": [
            {"text": "A bean stew takes 45 minutes and a soup 25.", "cites": [n["bean stew"], n["tomato soup"]]},
            {"text": "Lemon pasta is ready in 20 minutes.", "cites": [n["lemon pasta"]]}]}
        status, body = self.answer((brief[0], answer))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        self.assertEqual(len(TB.issue(self.cur, f, week, now=now)["points"]), 2)
        with self.conn.transaction():
            self.assertEqual(TB.plan(self.cur, now=now), 0, "answered, the same rows: not asked again")
        # the stew's and the soup's posts dated again, three weeks back: their rows leave this week
        self.cur.execute("UPDATE posts SET surfaced_at = %s, published_at = %s WHERE id = ANY(%s::uuid[])",
                         (start - timedelta(days=20), start - timedelta(days=20), posts[1:3]))
        issue = TB.issue(self.cur, f, week, now=now)
        self.assertEqual(sorted(t["fields"]["dish"]["value"] for s in issue["sections"] for t in s["things"]),
                         ["lemon pasta", "red curry"])
        self.assertEqual([p["text"] for p in issue["points"]], ["Lemon pasta is ready in 20 minutes."],
                         "the point citing rows that left the week is not shown")
        def asks():
            self.cur.execute("SELECT count(*) FROM mx_track_brief_asks WHERE track_id = %s AND week = %s", (f, week))
            return self.cur.fetchone()[0]
        with self.conn.transaction():
            TB.plan(self.cur, now=now + timedelta(minutes=5))
        self.assertEqual(asks(), 2, "2 of the 3 rows its brief cites left the week in progress: asked again within "
                                    "BRIEF_EVERY")
        with self.conn.transaction():
            TB.plan(self.cur, now=now + timedelta(minutes=6))
        self.assertEqual(asks(), 2, "one waits: not asked twice")


if __name__ == "__main__":
    unittest.main()
