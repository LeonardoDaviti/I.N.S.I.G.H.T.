"""ent-v5, one reading of a post (0212): the guide and schema, the checks (per section; the entities entry by entry),
the planner (new posts only, a window each, only while the switch is shadow or on), the one adapter (a reading row in
read-v3's shape), the reading pickers' one preference list, the switch (on: ent-v5's sets current and the old kinds
not asked; back: the old sets current again) and the /markx comparison. Fixed answers; invented names; DB tests roll
back."""
from __future__ import annotations

import unittest
from datetime import timedelta

from insight_core.markx import event_types, reading5 as R, repo, schemas, tasks, validate
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_entities import T0, H, _Db

POST = "Platform: telegram | Source: Example\nTitle: Acme released Orbit-7\nText: Acme released Orbit-7, a model, today."
WINDOW = ("Platform: site | Source: Example\nTitle: T\nWindow: 2 of 3 of the post's text (characters 5,801-11,800 of "
          "15,000)\nText: […] Later the Kestrel Lab answered.")


def reading(**over):
    r = {"kind": "report", "events": "one", "lang": "en", "type_why": "reports a release", "event_type": "model_release",
         "origin": "other", "items": [], "mentions": []}
    r.update(over)
    return r


def answer(**over):
    a = {"reading": reading(), "event": {"headline_en": "Acme released Orbit-7", "actors": ["Acme"], "object": "Orbit-7",
                                          "action": "released", "date": None, "numbers": []},
         "entities": [{"span": "Orbit-7", "name": "Orbit-7", "type": "model", "role": "subject", "maker": "Acme"},
                      {"span": "Acme", "name": "Acme", "type": "org", "role": "actor"}]}
    a.update(over)
    return a


class TheGuideAndSchema(unittest.TestCase):
    def test_the_kind_its_guide_and_the_guide_is_d7_without_citations_or_relations(self):
        k = schemas.KINDS["reading"]
        self.assertEqual((k.guide, k.subject, k.schema), ("ent-v5", "post", schemas.READING_V5_SCHEMA))
        body = schemas.guide_body("ent-v5")
        self.assertIn("Decide origin in this order", body)
        self.assertIn("type_why", body)
        self.assertNotIn("## 4. citations", body)
        self.assertIn("ent-v5", schemas.mention_guides())
        self.assertNotIn("ent-v5", schemas.ENTITY_ARMS)    # not an arm of the entities switch


class TheChecks(unittest.TestCase):
    def check(self, a, input=POST):
        return validate.check("reading", a, input, "ent-v5")

    def test_a_good_answer_passes_and_entities_may_leave_null_fields_out(self):
        got, err = self.check(answer())
        self.assertIsNone(err)
        self.assertEqual(len(got["entities"]), 2)

    def test_the_reading_is_checked_as_read_v2s(self):
        self.assertIn("main is null", self.check(answer(event=None))[1])
        self.assertIn("main must be null", self.check(answer(reading=reading(events="none")))[1])
        self.assertIn("reading is null", self.check(answer(reading=None))[1])
        self.assertIn("event_type", self.check(answer(reading=reading(event_type="gossip")))[1])

    def test_a_bad_entity_is_dropped_the_rest_stored_and_a_lost_subject_is_asked_again(self):
        bad = {"span": "Nowhere", "name": "Nowhere", "type": "org", "role": "mention"}
        got, err = self.check(answer(entities=answer()["entities"] + [bad]))
        self.assertIsNone(err)
        self.assertEqual([d["item"]["name"] for d in got["dropped"]], ["Nowhere"])
        lost = [{"span": "Orbit-9", "name": "Orbit-9", "type": "model", "role": "subject"},
                {"span": "Acme", "name": "Acme", "type": "org", "role": "actor"}]
        self.assertIn("every subject was dropped", self.check(answer(entities=lost))[1])

    def test_a_later_window_reads_entities_only_and_what_it_wrote_as_a_reading_is_kept_aside(self):
        got, err = self.check({"entities": [{"span": "Kestrel Lab", "name": "Kestrel Lab", "type": "org",
                                             "role": "mention"}]}, WINDOW)
        self.assertIsNone(err)
        self.assertEqual((got["reading"], got["event"]), (None, None))
        got, err = self.check(answer(entities=[{"span": "Kestrel Lab", "name": "Kestrel Lab", "type": "org",
                                                "role": "mention"}]), WINDOW)
        self.assertIsNone(err)
        self.assertIsNone(got["reading"])
        self.assertEqual([d["list"] for d in got["dropped"]], ["reading", "event"])


@requires_test_db
class InShadow(_Db):
    def post(self, src=0, at=T0, fetched=None, **kw):
        pid = super().post(src, at, **kw)
        self.cur.execute("UPDATE posts SET fetched_at = %s WHERE id = %s", (fetched or at, pid))
        return pid

    def mode(self, m):
        return R.set_mode(self.cur, m)

    def plan(self):
        return tasks.PLANNERS["reading"](self.cur, now=T0 + H)

    def read(self, pid, a=None):
        """Plan and answer the post's ent-v5 tasks (window 1 with `a`, later windows with no entity)."""
        self.cur.execute("SELECT id FROM mx_tasks WHERE kind = 'reading' AND a = %s ORDER BY input ~ '\\nWindow: '", (pid,))
        ids = [r[0] for r in self.cur.fetchall()]
        self.assertTrue(ids, "the post has ent-v5 tasks")
        for n, task_id in enumerate(ids):
            task = repo.get_task(self.cur, task_id)
            got, err = validate.check("reading", a if n == 0 else {"entities": []}, task["input"], task["guide"])
            self.assertIsNone(err)
            call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                                 answer=got)
            repo.answer_task(self.cur, task_id)
            tasks.record(self.cur, task, call, got)

    def old_read(self, pid, kind="report", event_type=None):
        """The post's read-v2 (and read-v3) reading, as the old kinds write them."""
        task_id, _ = tasks.read_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True, answer={})
        repo.add_reading(self.cur, post_id=pid, guide="read-v2", call_id=call, kind=kind, events="one", lang="en",
                         headline="Acme ships", reading={"kind": kind, "events": "one", "main": {"action": "released"}})
        if event_type:
            repo.add_reading(self.cur, post_id=pid, guide="read-v3", call_id=call, kind=kind, events="one", lang="en",
                             headline="Acme ships", reading={"kind": kind, "events": "one", "event_type": event_type,
                                                             "origin": "maker"})

    def test_off_plans_nothing_and_shadow_plans_new_posts_only_a_window_each(self):
        new = self.post(0, T0, title="Acme released Orbit-7", text="Acme released Orbit-7. " + "Words. " * 1500)
        old = self.post(1, T0 - timedelta(days=20), fetched=T0 - timedelta(days=20))
        self.assertEqual(self.plan(), 0)                                     # off: the default
        self.assertEqual(R.mode(self.cur), "off")
        self.mode("shadow")
        n = self.plan()
        self.cur.execute("SELECT a::text, count(*) FROM mx_tasks WHERE kind = 'reading' AND guide = 'ent-v5' GROUP BY a")
        got = dict(self.cur.fetchall())
        self.assertEqual(set(got), {new})                                    # no archive re-read
        self.assertEqual(got[new], n)
        self.assertGreater(n, 1)                                             # 9,000 characters: two windows
        self.assertNotIn(old, got)
        self.assertEqual(self.plan(), 0)                                     # asked once
        self.cur.execute("SELECT input FROM mx_tasks WHERE kind = 'reading' AND a = %s ORDER BY input ~ '\\nWindow: '", (new,))
        first = self.cur.fetchone()[0]
        self.assertIn("\nAddress: ", first)
        self.assertIn("\nPublished: ", first)

    def test_in_shadow_its_rows_are_stored_and_nothing_reads_them(self):
        p = self.post(0, T0, title="Acme released Orbit-7", text="Acme released Orbit-7, a model, today. More words.")
        self.old_read(p, event_type="product_release")
        before = repo.current_guide(self.cur, p)
        self.mode("shadow")
        self.plan()
        self.read(p, answer())
        row = repo.readings(self.cur, [p], "ent-v5")
        r = next(iter(row.values()))["reading"]
        self.assertEqual((r["kind"], r["main"]["action"], r["event_type"], r["origin"]),
                         ("report", "released", "model_release", "other"))       # read-v3's shape
        self.cur.execute("SELECT name FROM mx_mentions WHERE post_id = %s AND guide = 'ent-v5' ORDER BY n", (p,))
        self.assertEqual([x[0] for x in self.cur.fetchall()], ["Orbit-7", "Acme"])
        self.assertEqual(repo.current_guide(self.cur, p), before)                 # Shadow: the set did not move
        self.assertEqual(tasks.readings(self.cur, [p])[p]["main"], {"action": "released"})   # read-v2's still
        self.assertEqual(event_types.of_posts(self.cur, [p])[p].type, "product_release")      # read-v3's still
        from insight_core.markx import news
        self.assertEqual(news.post_panel(self.cur, p)["reading"]["guide"], "read-v3")

    def test_on_puts_it_first_moves_its_sets_and_stops_the_old_kinds_for_what_it_reads_and_off_moves_them_back(self):
        p = self.post(0, T0, title="Acme released Orbit-7", text="Acme released Orbit-7, a model, today. More words.")
        self.old_read(p, event_type="product_release")
        self.mode("shadow")
        self.plan()
        self.read(p, answer())
        got = self.mode("on")
        self.assertEqual(got["sets_moved"], 1)
        self.assertEqual(repo.current_guide(self.cur, p), "ent-v5")
        self.assertEqual(tasks.readings(self.cur, [p])[p]["event_type"], "model_release")
        self.assertEqual(event_types.of_posts(self.cur, [p])[p].type, "model_release")
        self.assertEqual(R.guides(self.cur, "read-v2"), ["ent-v5", "read-v2"])
        from insight_core.markx import news
        self.assertEqual(news.post_panel(self.cur, p)["reading"]["guide"], "ent-v5")
        # a new post ent-v5 reads gets no read or entities task from the old planners
        q = self.post(1, T0, title="Globex bought Initech", text="Globex bought Initech today. More words here.")
        self.plan()
        self.assertEqual(tasks.plan_posts(self.cur, "read", now=T0 + H, fetched_since=T0 - H), 0)
        self.cur.execute("SELECT kind FROM mx_tasks WHERE a = %s", (q,))
        self.assertEqual({k for (k,) in self.cur.fetchall()}, {"reading"})
        back = self.mode("shadow")
        self.assertEqual(back["sets_moved"], 1)
        self.assertNotEqual(repo.current_guide(self.cur, p), "ent-v5")
        self.assertEqual(R.guides(self.cur, "read-v2"), ["read-v2"])

    def test_the_comparison_shows_both_sides_and_the_agreement(self):
        p = self.post(0, T0, title="Acme released Orbit-7", text="Acme released Orbit-7, a model, today. More words.")
        self.old_read(p, kind="commentary", event_type="model_release")
        self.mode("shadow")
        self.plan()
        self.read(p, answer())
        got = R.compare(self.cur)
        self.assertEqual(got["mode"], "shadow")
        row = got["posts"][0]
        self.assertEqual((row["v5"]["kind"], row["current"]["kind"]), ("report", "commentary"))
        self.assertEqual(got["agree"]["kind"], {"same": 0, "of": 1})
        self.assertEqual(got["agree"]["event_type"], {"same": 1, "of": 1})
        self.assertEqual(row["v5"]["entities"], ["Acme", "Orbit-7"])

    def test_the_switch_refuses_an_unknown_mode(self):
        with self.assertRaises(ValueError):
            R.set_mode(self.cur, "sometimes")


if __name__ == "__main__":
    unittest.main()
