"""Issue 0272 (Stealth v10.32): an entity's numbers over time (0095), read from its brief's measure rows
(markx/entity_brief.py `series`): one series per measure name and unit, each value with its date, post and quote; a
series only with 2+ values from 2+ posts; two posts' different values of one date and setting are a dispute (0097).

Invented names only.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from insight_core.markx import entity_brief as EB, identity, track_things as TT
from insight_core.tests._db import insert_scratch_source
from insight_core.tests.test_markx_api import call
from insight_core.tests import test_track_briefer_0245 as B
from insight_core.tests.test_track_briefer_0245 import _Briefer, v

D = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def num(n, unit, quote, **kw):
    return {"value": {"number": n, "unit": unit, "range_to": None}, "quote": quote, **kw}


def rep(post, day, measure, fig, money=False, setting=None, as_of=None):
    vals = {"measure": v(measure, measure), ("amount" if money else "value"): fig}
    if setting:
        vals["setting"] = v(setting, setting)
    if as_of:
        vals["as_of"] = v(as_of, as_of)
    return {"post": post, "at": D + timedelta(days=day), "values": vals}


class Series(unittest.TestCase):
    def test_one_series_a_name_and_unit_two_posts_at_least(self):
        got = EB.series([
            rep("p1", 0, "Zqbench score", num(71, "%", "71% on Zqbench")),
            rep("p2", 5, "ZQBENCH score", num(74.5, "percent", "74.5 percent")),
            rep("p2", 5, "Zqbench score", num(74.5, "%", "74.5%")),            # the same post's same figure: once
            rep("p3", 6, "Zqbench score", num(9, "points", "9 points")),       # another unit: another series
            rep("p4", 7, "price per million input tokens",
                {"value": {"number": 3, "currency": "USD", "range_to": None}, "quote": "$3 per million"}, money=True),
        ])
        self.assertEqual(len(got), 1, "a series needs 2+ posts: the points and the price have one each")
        (s,) = got
        self.assertEqual((s["measure"], s["unit"], s["money"], s["posts"], s["disputes"]),
                         ("Zqbench score", "%", False, 2, 0))
        self.assertEqual([(p["at"], p["value"], p["post"], p["quote"]) for p in s["points"]],
                         [("2026-11-01", 71, "p1", "71% on Zqbench"),
                          ("2026-11-06", 74.5, "p2", "74.5 percent")])

    def test_a_dispute_is_two_posts_values_of_one_date_and_setting(self):
        got = EB.series([
            rep("p1", 0, "Zqbench score", num(71, "%", "71%")),
            rep("p2", 0, "Zqbench score", num(74, "%", "74%")),
            rep("p3", 0, "Zqbench score", num(80, "%", "80%"), setting="high effort"),   # another setting: another
            rep("p4", 3, "Zqbench score", num(71, "%", "71%")),                          # measure, its own series
            rep("p5", 4, "Zqbench score", num(82, "%", "82%"), setting="High effort"),
        ])
        self.assertEqual([(s["setting"], s["disputes"]) for s in got], [(None, 1), ("high effort", 0)])
        self.assertEqual(sorted((p["post"], p["dispute"]) for p in got[0]["points"]),
                         [("p1", True), ("p2", True), ("p4", False)])
        self.assertEqual([p["post"] for p in got[1]["points"]], ["p3", "p5"])

    def test_money_by_currency_and_a_stated_period(self):
        usd = lambda n, q: {"value": {"number": n, "currency": "USD", "range_to": None}, "quote": q}   # noqa: E731
        (s,) = EB.series([rep("p1", 0, "revenue", usd(30e9, "$30 billion"), money=True, as_of="Q2"),
                          rep("p2", 90, "revenue", usd(35e9, "$35 billion"), money=True, as_of="Q3"),
                          rep("p3", 90, "revenue", {"value": {"number": 4, "currency": "EUR", "range_to": None},
                                                    "quote": "€4"}, money=True)])
        self.assertEqual((s["unit"], s["money"], [p["shown"] for p in s["points"]], [p["as_of"] for p in s["points"]]),
                         ("USD", True, ["30,000,000,000 USD", "35,000,000,000 USD"], ["Q2", "Q3"]))

    def test_money_per_unit_is_its_own_series(self):
        usd = lambda n, q, per: {"value": {"number": n, "currency": "USD", "unit": per}, "quote": q}   # noqa: E731
        got = EB.series([rep("p1", 0, "hashprice", usd(33, "$33 per PH/s", "per PH/s"), money=True),
                         rep("p2", 0, "hashprice", usd(33095, "$33,095 per EH/s", "per EH/s"), money=True),
                         rep("p3", 1, "hashprice", usd(32, "$32 per PH/s", "per PH/s"), money=True)])
        self.assertEqual([(s["unit"], s["disputes"], [p["shown"] for p in s["points"]]) for s in got],
                         [("USD per PH/s", 0, ["33 USD per PH/s", "32 USD per PH/s"])])

    def test_a_typed_figure_is_read_with_its_multiplier_and_its_sign(self):
        f = {"name": "value", "type": "number"}
        m = {"name": "amount", "type": "money"}
        q = "115,8 млрд долларов выручки"
        self.assertEqual(TT.check_value(m, {"value": {"number": 115.8, "currency": "USD"}, "quote": q}, q),
                         (None, "number not in its quote"), "115.8 is not 115,8 billion")
        self.assertEqual(TT.check_value(m, {"value": {"number": 115.8e9, "currency": "USD"}, "quote": q}, q)[1], None)
        self.assertEqual(TT.check_value(f, num(16, "K", "a 16K window"), "a 16K window"), (None, "number not in its quote"))
        self.assertEqual(TT.check_value(f, num(5, "m", "a 5 m cable"), "a 5 m cable")[1], None, "a unit after a space")
        self.assertEqual(TT.check_value(f, num(-7, "%", "dropped about 7%"), "dropped about 7%")[0]["number"], -7)
        self.assertTrue(TT.figures_read("115.8 billion in revenue", q), "a text value still reads the bare figure")
        q2 = "costs $3 per million input tokens"
        got, why = TT.check_value(m, {"value": {"number": 3, "currency": "USD", "unit": "per million input tokens"},
                                      "quote": q2}, q2)
        self.assertEqual((why, TT.shown_value(m, got)), (None, "3 USD per million input tokens"))
        self.assertEqual(TT.check_value(m, {"value": {"number": 3, "currency": "USD", "unit": "per month"},
                                            "quote": q2}, q2), (None, "unit not in its quote"))

    def test_units_as_written(self):
        self.assertEqual([EB.unit_key(u) for u in ("%", "Percent", "per cent", "tok/s", "tok /s", None, "GB.")],
                         ["%", "%", "%", "tok/s", "tok/s", "", "gb"])

    def test_the_measure_kind_is_typed_and_checked_like_every_value(self):
        f = {x["name"]: x for x in EB.MEASURE_KIND["fields"]}
        self.assertEqual((f["measure"]["type"], f["measure"]["key"], f["value"]["type"], f["amount"]["type"]),
                         ("text", True, "number", "money"))
        self.assertEqual(TT.check_value(f["value"], num(74, "%", "scored 71% on it"), "scored 71% on it"),
                         (None, "number not in its quote"))


class Page(_Briefer):
    mention = B.Flow.mention

    def setUp(self):
        super().setUp()
        bands = identity.bands()
        was = bands.get("entities")
        bands["entities"] = dict(was or {}, brief=True, numbers=True)
        self.addCleanup(lambda: bands.__setitem__("entities", was) if was is not None else bands.pop("entities", None))
        self.src = insert_scratch_source(self.cur, platform="rss", enabled=True,
                                         settings_json=json.dumps({"display_name": "Zq Lab Notes"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = %s", (self.src,))

    def about(self, ent, title, text, at):
        p = self.post(title=title, text=text, source=self.src, at=at)
        return p, self.mention(p, "Zqmodel 3", entity=ent)

    def test_the_page_shows_each_measure_over_time_cited(self):
        p1, ent = self.about(None, "Zqmodel 3", "Zqmodel 3 scores 71% on Zqbench.", D)
        p2, _ = self.about(ent, "Update", "Zqmodel 3 now scores 74.5% on Zqbench.", D + timedelta(days=9))
        p3, _ = self.about(ent, "Price", "Zqmodel 3 costs $3 per million input tokens.", D + timedelta(days=10))
        p4, _ = self.about(ent, "What", "Zqmodel 3 is a language model.", D + timedelta(days=1))
        p5, _ = self.about(ent, "Note", "Zqmodel 3 note.", D + timedelta(days=2))
        with self.conn.transaction():
            EB.plan_things(self.cur, roots=[ent])
        self.things(ent, p4, {"kind": EB.WHAT, "fields": {"definition": v("a language model", "a language model"),
                                                          "subject": v("Zqmodel 3", "Zqmodel 3 is")}})
        self.things(ent, p5)   # read, no row: 0269's SHOW_POSTS read
        s = TT.current_schema(self.cur, ent)
        self.assertEqual((s["track_version"], [k["kind"] for k in s["schema"]["kinds"]]),
                         (EB.NUMBERS_VERSION, [EB.WHAT, EB.HOW, EB.MEASURE, TT.PRACTICE_KIND]),
                         "on: the schema gains the measure kind, a version of its own")
        self.things(ent, p1, {"kind": EB.MEASURE, "fields": {"measure": v("Zqbench score", "on Zqbench"),
                                                             "value": num(71, "%", "scores 71% on Zqbench")}})
        self.things(ent, p2, {"kind": EB.MEASURE, "fields": {"measure": v("Zqbench score", "on Zqbench"),
                                                             "value": num(74.5, "%", "scores 74.5% on Zqbench")}},
                    {"kind": TT.PRACTICE_KIND, "fields": {"what": v("a higher Zqbench score", "now scores 74.5%")}})
        self.things(ent, p3, {"kind": EB.MEASURE, "fields": {
            "measure": v("price per million input tokens", "per million input tokens"),
            "amount": {"value": {"number": 3, "currency": "USD"}, "quote": "costs $3 per million"}}})
        with self.conn.transaction():
            b = EB.view(self.cur, ent, names=["Zqmodel 3"])
        self.assertEqual([ln["text"] for ln in b["results"]], ["a higher Zqbench score"], "a measure is never a line")
        (s,) = b["numbers"]
        self.assertEqual((s["measure"], s["unit"]), ("Zqbench score", "%"))
        self.assertEqual([(p["value"], p["post"], p["n"]) for p in s["points"]], [(71, p1, 3), (74.5, p2, 2)],
                         "numbered after the lines' cites")
        self.assertEqual({p["id"] for p in b["posts"]}, {p1, p2, p4})
        status, page = call("GET", f"/api/markx/entities/{ent}")
        self.assertEqual((status, page["brief"]["numbers"][0]["measure"]), (200, "Zqbench score"), page)
        identity.bands()["entities"]["numbers"] = False
        with self.conn.transaction():
            self.assertEqual(EB.view(self.cur, ent, names=["Zqmodel 3"])["numbers"], [], "off: no numbers")
