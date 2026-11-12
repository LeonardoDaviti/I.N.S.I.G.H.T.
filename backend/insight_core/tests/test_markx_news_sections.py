"""0174 (Stealth v10.16): Mark X News in Haiku's titled sections, and every row titled by Haiku. The checks on an answer
(every row once, no unknown key, counts, title length, no title twice, "Other" for two rows at most), when the question
is asked (first time, 20% of the rows changed, 30 minutes, one waiting), its input (headline, entities, type, voices,
last time's titles and each row's last section), the answer stored as rows, the page's `sections` (the page's order,
the rows added since as `new`), the lease's planner, and the untitled rows' headline tasks asked first. Synthetic data
only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

from insight_core.markx import news, news_sections as S, repo, schemas, tasks, validate
from insight_core.tests.test_markx_api import _Api, call

PLANNERS = dict(tasks.PLANNERS)        # the real ones (each _Api test empties tasks.PLANNERS)
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def rows_input(n: int) -> str:
    return "NEWS: %d rows, most important first\n\n" % n + "\n".join(f"[r{k}] Headline {k} | 2 voices" for k in range(1, n + 1))


def answer(*groups):
    return {"sections": [{"title": t, "row_ids": list(ks)} for t, ks in groups]}


class TheChecks(unittest.TestCase):
    TEXT = rows_input(7)

    def check(self, a):
        return validate.check("news_sections", a, self.TEXT, "news-sections-v1")[1]

    def test_every_row_in_exactly_one_section(self):
        self.assertIsNone(self.check(answer(("Model releases", ["r1", "r4"]), ("Funding and deals", ["r2", "r3", "r5"]),
                                            ("Research papers", ["r6", "r7"]))))

    def test_a_missing_row_is_refused(self):
        err = self.check(answer(("Model releases", ["r1", "r4"]), ("Funding and deals", ["r2", "r3"]),
                                ("Research papers", ["r6"])))
        self.assertIn("r5, r7 in no section", err)

    def test_a_row_twice_is_refused(self):
        err = self.check(answer(("Model releases", ["r1", "r4", "r2"]), ("Funding and deals", ["r2", "r3", "r5"]),
                                ("Research papers", ["r6", "r7"])))
        self.assertIn("r2 is in two sections", err)

    def test_an_unknown_key_is_refused(self):
        err = self.check(answer(("Model releases", ["r1", "r4", "r9"]), ("Funding and deals", ["r2", "r3", "r5"]),
                                ("Research papers", ["r6", "r7"])))
        self.assertIn("names r9, not a row", err)

    def test_the_counts_and_the_titles(self):
        two = answer(("Model releases", ["r1", "r2", "r3", "r4"]), ("Funding", ["r5", "r6", "r7"]))
        self.assertIn("sections", self.check(two))                                       # fewer than 3
        nine = answer(*[(f"Topic {k}", [f"r{k}"]) for k in range(1, 8)], ("Topic eight", []), ("Topic nine", []))
        self.assertIsNotNone(self.check(nine))                                           # more than 8
        long = answer(("Very long section title here", ["r1", "r4"]), ("Funding and deals", ["r2", "r3", "r5"]),
                      ("Research papers", ["r6", "r7"]))
        self.assertIn("more than 4 words", self.check(long))
        twice = answer(("Funding and deals", ["r1", "r4"]), ("funding and deals", ["r2", "r3", "r5"]),
                       ("Research papers", ["r6", "r7"]))
        self.assertIn("used twice", self.check(twice))
        other = answer(("Model releases", ["r1", "r4"]), ("Funding and deals", ["r2"]), ("Other", ["r3", "r5", "r6", "r7"]))
        self.assertIn("give them a real section", self.check(other))
        small_other = answer(("Model releases", ["r1", "r4", "r3"]), ("Funding and deals", ["r2", "r5"]),
                             ("Other", ["r6", "r7"]))
        self.assertIsNone(self.check(small_other))
        too_long = answer(("x" * (schemas.NEWS_SECTION_TITLE_CHARS + 1), ["r1"]), ("Funding", ["r2", "r3", "r4", "r5"]),
                          ("Research", ["r6", "r7"]))
        self.assertIsNotNone(self.check(too_long))

    def test_sections_are_ordered_by_their_most_important_row(self):
        got = S.sections_of(answer(("Research", ["r7", "r3"]), ("Releases", ["r2", "r1"]), ("Deals", ["r4", "r5", "r6"])),
                            [f"id{k}" for k in range(1, 8)])
        self.assertEqual(got, [("Releases", ["id1", "id2"]), ("Research", ["id3", "id7"]), ("Deals", ["id4", "id5", "id6"])])

    def test_the_guide_is_sphere_agnostic(self):
        body = schemas.guide_body("news-sections-v1")
        self.assertNotIn(" AI", body)
        self.assertIn('"row_ids"', body)


class WhenItIsAsked(unittest.TestCase):
    ROWS = [f"row{k}" for k in range(10)]

    def ask(self, status="answered", minutes=60, rows=None):
        return {"row_ids": rows or self.ROWS, "asked_at": NOW - timedelta(minutes=minutes), "status": status}

    def test_first_time(self):
        self.assertEqual(S.due([], self.ROWS, NOW), (True, "first time"))

    def test_too_few_rows(self):
        self.assertFalse(S.due([], self.ROWS[:S.MIN_ROWS - 1], NOW)[0])

    def test_one_waiting_holds_the_next(self):
        self.assertEqual(S.due([self.ask("open", rows=["x"])], self.ROWS, NOW), (False, "one is waiting"))
        self.assertEqual(S.due([self.ask("leased", rows=["x"])], self.ROWS, NOW)[0], False)

    def test_at_most_once_in_30_minutes(self):
        self.assertFalse(S.due([self.ask(minutes=29, rows=["x"])], self.ROWS, NOW)[0])
        self.assertTrue(S.due([self.ask(minutes=31, rows=["x"])], self.ROWS, NOW)[0])

    def test_twenty_percent_of_the_rows_changed(self):
        one = self.ROWS[:9] + ["new"]                                            # 1 new + 1 removed over 10: 20%
        self.assertTrue(S.due([self.ask()], one, NOW)[0])
        same = self.ROWS[:9] + [self.ROWS[9]]
        self.assertFalse(S.due([self.ask()], same, NOW)[0])
        self.assertFalse(S.due([self.ask()], self.ROWS + ["new"], NOW)[0])       # 1 of 10: 10%
        self.assertAlmostEqual(S.changed_share(self.ROWS, self.ROWS[:8]), 0.2)

    def test_a_failed_question_is_not_the_last_asked(self):
        asks = [self.ask("failed", rows=["x"]), self.ask(rows=self.ROWS, minutes=90)]
        self.assertFalse(S.due(asks, self.ROWS, NOW)[0])                         # the answered one: no change
        self.assertTrue(S.due([self.ask("failed", rows=self.ROWS)], self.ROWS, NOW)[0])   # only a failed one: first time


class Sections(_Api):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def news_run(self, posts, *, scores=None):
        run = repo.start_run(self.cur, code_version="test", config={})
        repo.add_news_rows(self.cur, run, [
            {"id": p, "first_at": self.now - timedelta(hours=1), "voices": 2, "reports": 2, "shares": 0, "mentions": 0,
             "score": (scores or {}).get(p, 100 - n), "tag": "NEW", "posts": [{"post_id": p, "role": "report", "position": 0}]}
            for n, p in enumerate(posts)])
        repo.finish_run(self.cur, run, counts={})
        return str(run)

    def posts(self, n):
        return [self.post(title=f"Item {k} happened") for k in range(n)]

    def entities(self, post, *names):
        with self.conn.transaction():
            tid, _ = tasks.entities_task(self.cur, post)
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True, answer={})
            repo.add_mentions(self.cur, post_id=post, guide="ent-v3", call_id=call_id,
                              mentions=[{"name": nm, "name_key": nm.lower(), "type": typ, "role": "subject", "span": nm}
                                        for nm, typ in names])

    def read3(self, post, event_type):
        from insight_core.markx import folds
        with self.conn.transaction():
            tid, _ = folds.read3_task(self.cur, post)
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="m", valid=True, answer={})
            repo.add_reading(self.cur, post_id=post, guide="read-v3", call_id=call_id, kind="report", events="one",
                             lang="en", headline=None, reading={"event_type": event_type, "origin": "maker"})

    def plan(self):
        with self.conn.transaction():
            return S.plan(self.cur)

    def the_task(self):
        self.cur.execute("SELECT id::text, input, priority, a::text, subject_kind FROM mx_tasks WHERE kind = 'news_sections' "
                         "ORDER BY created_at DESC LIMIT 1")
        return self.cur.fetchone()

    def test_the_question_shows_each_row_in_news_order(self):
        ps = self.posts(8)
        self.entities(ps[0], ("Acme", "org"), ("Widget 4.1", "product"))
        self.read3(ps[0], "product_release")
        run = self.news_run(ps)
        self.assertEqual(self.plan(), 1)
        tid, text, priority, a, subject = self.the_task()
        self.assertEqual((priority, a, subject), (S.PRIORITY, run, "news_run"))
        lines = text.splitlines()
        self.assertEqual(lines[0], "NEWS: 8 rows, most important first")
        self.assertNotIn("LAST TIME'S SECTIONS", text)                             # never sectioned
        self.assertEqual(lines[2], "[r1] Item 0 happened | entities: Acme (org), Widget 4.1 (product) | "
                                   "type: product release | 2 voices")
        self.assertEqual(lines[9], "[r8] Item 7 happened | 2 voices")
        self.cur.execute("SELECT row_ids FROM mx_news_section_asks WHERE task_id = %s", (tid,))
        self.assertEqual(self.cur.fetchone()[0], ps)
        self.assertEqual(self.plan(), 0)                                           # one waiting

    def test_too_few_rows_ask_nothing(self):
        self.news_run(self.posts(S.MIN_ROWS - 1))
        self.assertEqual(self.plan(), 0)

    def sectioned(self, ps):
        """Asked and answered through the API: rows 0-2 releases, 3-5 deals, 6-7 research."""
        self.news_run(ps)
        self.assertEqual(self.plan(), 1)
        tid = self.the_task()[0]
        self.lease("news_sections")
        got = self.answer((tid, answer(("Deals", ["r4", "r5", "r6"]), ("Releases", ["r1", "r2", "r3"]),
                                       ("Research", ["r7", "r8"]))))
        self.assertEqual(got[1]["valid"], 1, got)
        return tid

    def test_an_answer_is_stored_as_rows_and_the_page_groups_by_it(self):
        ps = self.posts(8)
        tid = self.sectioned(ps)
        self.cur.execute("SELECT position, title, row_ids::text[] FROM mx_news_sections WHERE task_id = %s ORDER BY position",
                         (tid,))
        self.assertEqual(self.cur.fetchall(), [(0, "Releases", ps[0:3]), (1, "Deals", ps[3:6]), (2, "Research", ps[6:8])])
        # a new run: one row gone, one new (row ids are first posts): the page keeps the last sectioning, the new row first
        extra = self.post(title="Late item")
        self.news_run(ps[1:] + [extra], scores={extra: 1000})
        status, page = call("GET", "/api/markx/news", query={"all": 1})
        self.assertEqual(status, 200)
        sec = page["sections"]
        self.assertEqual(sec["new"], [extra])
        self.assertEqual([(g["title"], g["rows"]) for g in sec["groups"]],
                         [("Releases", ps[1:3]), ("Deals", ps[3:6]), ("Research", ps[6:8])])
        self.assertFalse(sec["pending"])
        self.assertIsNotNone(sec["at"])
        self.assertEqual(page["counts"]["untitled"], 8)                              # no headline task answered here

    def test_the_next_question_shows_last_times_titles_and_each_rows_section(self):
        ps = self.posts(8)
        self.sectioned(ps)
        self.cur.execute("UPDATE mx_news_section_asks SET asked_at = asked_at - interval '31 minutes'")
        more = self.posts(2)
        self.news_run(ps + more, scores={more[0]: 1000, more[1]: 999})                    # 2 new of 8: 25%
        self.assertEqual(self.plan(), 1)
        text = self.the_task()[1]
        self.assertIn("LAST TIME'S SECTIONS: [s1] Releases | [s2] Deals | [s3] Research", text)
        lines = text.splitlines()
        self.assertTrue(lines[3].startswith("[r1] Item 0 happened") and not lines[3].endswith("last: s1"))   # new: none
        self.assertTrue(lines[5].startswith("[r3] Item 0 happened") and lines[5].endswith("| last: s1"))
        self.assertTrue(lines[12].endswith("| last: s3"))

    def test_little_change_asks_nothing(self):
        ps = self.posts(10)
        self.sectioned(ps[:8])
        self.cur.execute("UPDATE mx_news_section_asks SET asked_at = asked_at - interval '31 minutes'")
        self.news_run(ps[:8] + ps[8:9])                                                   # 1 new of 8: 12.5%
        self.assertEqual(self.plan(), 0)

    def test_a_wrong_answer_is_refused_and_the_page_waits(self):
        ps = self.posts(8)
        self.news_run(ps)
        self.plan()
        tid = self.the_task()[0]
        self.lease("news_sections")
        got = self.answer((tid, answer(("Deals", ["r4", "r5", "r6"]), ("Releases", ["r1", "r2", "r3"]), ("Research", ["r7"]))))
        self.assertEqual(got[1]["valid"], 0)
        self.assertIn("r8 in no section", got[1]["invalid"][0]["error"])
        page = call("GET", "/api/markx/news", query={"all": 1})[1]
        self.assertEqual(page["sections"], {"at": None, "pending": True, "groups": [], "new": []})

    def test_the_planner_runs_when_a_worker_leases_news_sections(self):
        self.news_run(self.posts(8))
        with mock.patch.object(tasks, "PLANNERS", {"news_sections": PLANNERS["news_sections"]}):
            status, work = self.lease("news_sections")
        self.assertEqual((status, [t["kind"] for t in work["tasks"]]), (200, ["news_sections"]))
        self.assertIn("news-sections-v1", work["guides"])

    def test_untitled_rows_get_their_headline_asked_first(self):
        ps = self.posts(3)
        self.news_run(ps)
        with self.conn.transaction():
            open_tid, _ = tasks.headline_task(self.cur, [ps[0]])                     # the row's question, asked at 0
        with self.conn.transaction():
            got = S.title_rows(self.cur)
        self.assertEqual(got, {"untitled": 3, "raised": 1, "added": 2, "waiting": 0, "failed": 0})
        self.cur.execute("SELECT count(*), min(priority), max(priority) FROM mx_tasks WHERE kind = 'headline'")
        self.assertEqual(self.cur.fetchone(), (3, S.PRIORITY, S.PRIORITY))
        with self.conn.transaction():
            self.assertEqual(S.title_rows(self.cur)["added"], 0)                      # once
        # answered: the row is titled by Haiku, and no longer counted
        self.lease("headline")
        self.assertEqual(self.answer((open_tid, {"headline_en": "Item zero happened"}))[1]["valid"], 1)
        page = call("GET", "/api/markx/news", query={"all": 1})[1]
        heads = {i["id"]: i["headline"] for i in page["items"]}
        self.assertEqual(heads[ps[0]], {"text": "Item zero happened", "from": "haiku"})
        self.assertEqual(page["counts"]["untitled"], 2)
        with self.conn.transaction():
            self.assertEqual(S.title_rows(self.cur)["untitled"], 2)


if __name__ == "__main__":
    unittest.main()
