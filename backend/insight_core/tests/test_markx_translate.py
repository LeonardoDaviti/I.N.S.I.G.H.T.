"""0130 D (Stealth v10.5): translation. A post's language (its reading's lang before the feed's code), the request
route (idempotent, first in the lease, a failed task opened again), the view the post page shows, the owner's ✓ / ✗ as
Mark X labels (migration 0078), the Mark X News leads planner (non-English leads of the newest written run, once a
post), the guide translate-v2. Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from insight_core.markx import repo, schemas, tasks, translate as T, validate
from insight_core.tests.test_markx_api import _Api, call, reading

PLANNERS = dict(tasks.PLANNERS)        # the real ones (each _Api test empties tasks.PLANNERS)

RU = ("Компания Acme выпустила Widget 4.1: 27B параметров, цена $20 в месяц. Фронт стал быстрее, а ручки API "
      "отвечают за 40 мс.")
EN = {"title_en": "Acme released Widget 4.1",
      "text_en": "Acme released Widget 4.1: 27B parameters, $20 a month. The frontend got faster, and the API "
                 "endpoints answer in 40 ms."}


class TheGuide(unittest.TestCase):
    def test_v2_is_v1_with_the_glossary_and_keeps_the_answer_shape(self):
        v1, v2 = schemas.guide_body("translate-v1"), schemas.guide_body("translate-v2")
        self.assertIn("Answer with JSON: {\"title_en\": \"...\", \"text_en\": \"...\"}", v2)
        for line in v1.splitlines()[2:5]:
            self.assertIn(line, v2)                             # v1's rules, unchanged
        self.assertIn("| фронт, фронтенд | frontend | front, frontier |", v2)
        self.assertIn("endpoint", v2)
        self.assertIn(schemas.KINDS["translate"].guide, ("translate-v1", "translate-v2"))

    def test_the_checks_hold_numbers_and_length(self):
        text = f"Title: Acme\nText: {RU}"
        self.assertIsNone(validate.check("translate", EN, text)[1])
        self.assertIn("number 40", validate.check("translate", {**EN, "text_en": EN["text_en"].replace("40", "forty")}, text)[1])


class Translation(_Api):
    def setUp(self):
        super().setUp()
        self.run = repo.start_run(self.cur, code_version="test", config={})

    def ru(self, *, lang="ru", at=None):
        p = self.post(title="Acme", text=RU + " (" + "".join(random.choice("абвгдежзикл") for _ in range(12)) + ")", at=at)
        self.cur.execute("UPDATE posts SET language_code = %s WHERE id = %s", (lang, p))
        return p

    def read_as(self, post, lang):
        with self.conn.transaction():
            tid, _ = tasks.read_task(self.cur, post)
        self.assertEqual(self.answer((tid, reading(lang=lang)))[1]["valid"], 1)

    def test_the_language_is_the_readings_first_then_the_feeds(self):
        ru, en, und, gb = self.ru(), self.ru(lang="en"), self.ru(lang="und"), self.ru(lang="en-GB")
        self.assertEqual([T.language(self.cur, p) for p in (ru, en, und, gb)], ["ru", "en", None, "en"])
        self.read_as(und, "ru")                               # the reading names it
        self.read_as(ru, "en")                                # the feed's ru was wrong: the reading wins
        self.assertEqual(T.language(self.cur, und), "ru")
        self.assertEqual(T.language(self.cur, ru), "en")
        self.assertEqual([T.foreign(x) for x in ("ru", "en", None, "")], [True, False, False, False])

    def test_ask_answer_view_and_label(self):
        p = self.ru()
        status, got = call("GET", f"/api/markx/posts/{p}/translation")
        self.assertEqual((status, got["foreign"], got["task"], got["translation"]), (200, True, None, None))
        status, asked = call("POST", f"/api/markx/posts/{p}/translate")
        self.assertEqual((status, asked["new"], asked["view"]["task"]["status"]), (200, True, "open"))
        again = call("POST", f"/api/markx/posts/{p}/translate")[1]
        self.assertEqual((again["new"], again["task_id"]), (False, asked["task_id"]))   # idempotent
        # a request is leased before the planned ones
        with self.conn.transaction():
            planned, _ = tasks.translate_task(self.cur, self.ru())
        status, work = self.lease("translate", limit=1)
        self.assertEqual([t["id"] for t in work["tasks"]], [asked["task_id"]])
        self.assertEqual(work["tasks"][0]["guide"], schemas.KINDS["translate"].guide)
        self.assertIn(work["tasks"][0]["guide"], work["guides"])
        self.assertEqual(call("GET", f"/api/markx/posts/{p}/translation")[1]["task"]["status"], "leased")
        self.assertEqual(self.answer((asked["task_id"], EN))[1]["valid"], 1)
        got = call("GET", f"/api/markx/posts/{p}/translation")[1]
        self.assertEqual(got["translation"]["text_en"], EN["text_en"])
        self.assertEqual((got["translation"]["model"], got["label"]), ("claude-haiku-5-5", None))
        # ✓, then ✗, then undo: three label rows (keep everything), the newest counts
        self.assertEqual(call("POST", f"/api/markx/posts/{p}/translation/label", body={"answer": "right"})[1]["label"], "right")
        self.assertEqual(call("POST", f"/api/markx/posts/{p}/translation/label", body={"answer": "wrong"})[1]["label"], "wrong")
        score = call("GET", "/api/markx/translations/score")[1]
        self.assertEqual(score["guides"][got["translation"]["guide"]]["wrong"], 1)
        self.assertIsNone(call("POST", f"/api/markx/posts/{p}/translation/label", body={"answer": "undo"})[1]["label"])
        self.cur.execute("SELECT answer, a::text, b::text FROM mx_labels WHERE item_kind = 'translation' ORDER BY created_at, ctid")
        self.assertEqual(self.cur.fetchall(), [(a, asked["task_id"], p) for a in ("right", "wrong", "undo")])
        self.assertEqual(call("GET", "/api/markx/translations/score")[1]["guides"], {})
        # refusals
        self.assertEqual(call("POST", f"/api/markx/posts/{p}/translation/label", body={"answer": "maybe"})[0], 400)
        self.assertEqual(call("POST", f"/api/markx/posts/{self.ru()}/translation/label", body={"answer": "right"})[0], 404)
        self.assertEqual(call("POST", f"/api/markx/posts/{self.ru(lang='en')}/translate")[0], 400)
        self.assertEqual(call("GET", "/api/markx/posts/not-a-uuid/translation")[0], 404)
        self.assertEqual(call("GET", "/api/markx/posts/00000000-0000-0000-0000-000000000000/translation")[0], 404)

    def test_a_failed_task_is_opened_again_when_the_owner_asks(self):
        p = self.ru()
        tid = call("POST", f"/api/markx/posts/{p}/translate")[1]["task_id"]
        bad = {**EN, "text_en": "Acme released a widget."}
        for _ in range(3):
            self.lease("translate")
            self.answer((tid, bad))
        got = call("GET", f"/api/markx/posts/{p}/translation")[1]
        self.assertEqual(got["task"]["status"], "failed")
        self.assertIn("not in the translation", got["task"]["error"])
        again = call("POST", f"/api/markx/posts/{p}/translate")[1]
        self.assertEqual((again["task_id"], again["view"]["task"]["status"]), (tid, "open"))
        self.assertEqual(repo.get_task(self.cur, tid)["attempts"], 0)

    def news(self, *rows, at=None):
        """A written Mark X News run whose rows are led by these posts."""
        run = repo.start_run(self.cur, code_version="test", config={})
        repo.add_news_rows(self.cur, run, [
            {"id": p, "first_at": at or datetime.now(timezone.utc), "voices": 2, "reports": 2, "shares": 0, "mentions": 0,
             "score": 10 - n, "tag": "NEW", "posts": [{"post_id": p, "role": "report", "position": 0}]}
            for n, p in enumerate(rows)])
        repo.finish_run(self.cur, run, counts={})
        return run

    def test_the_planner_asks_the_non_english_leads_of_the_newest_run_once(self):
        old = self.ru()
        self.news(old)
        ru, en, und, loose = self.ru(), self.ru(lang="en"), self.ru(lang="und"), self.ru()   # loose: in no row
        stale = self.ru()
        self.news(stale, at=datetime.now(timezone.utc) - timedelta(days=40))   # outside News' window: no row of it
        self.news(ru, en, und)
        self.assertIn("translate", PLANNERS)
        with self.conn.transaction():
            self.assertEqual(T.plan(self.cur), 1)
            self.assertEqual(T.plan(self.cur), 0)                              # once a post
        self.cur.execute("SELECT a::text, priority FROM mx_tasks WHERE kind = 'translate'")
        self.assertEqual(self.cur.fetchall(), [(ru, 0)])

    def test_the_planner_runs_when_a_worker_leases_translate(self):
        tasks.PLANNERS = {"translate": PLANNERS["translate"]}
        ru = self.ru()
        self.news(ru)
        status, work = self.lease("translate")
        self.assertEqual((status, [t["kind"] for t in work["tasks"]]), (200, ["translate"]))
        self.assertTrue(work["tasks"][0]["input"].startswith("Title: Acme\nText: Компания Acme"))

    def test_mark_ix_tables_are_untouched(self):
        from insight_core.tests.test_markx_decide import checksums
        p = self.ru()
        self.news(p)
        before = checksums(self.cur)
        with self.conn.transaction():
            T.plan(self.cur)
        tid = call("POST", f"/api/markx/posts/{p}/translate")[1]["task_id"]
        self.answer((tid, EN))
        call("POST", f"/api/markx/posts/{p}/translation/label", body={"answer": "right"})
        self.assertEqual(checksums(self.cur), before)

    def test_mx_labels_takes_translation_and_still_its_other_kinds(self):
        for kind in ("translation", "fold", "join", "news_row", "entity"):
            repo.add_label(self.cur, item_kind=kind, a=None, b=None, answer="x")
        q = "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'mx_labels_item_kind_check'"
        self.cur.execute(q)
        before = self.cur.fetchone()[0]
        sql = (Path(__file__).resolve().parents[1] / "db" / "migrations" / "0078_markx_translation_labels.sql").read_text()
        self.cur.execute(sql)                                                   # idempotent
        self.cur.execute(q)
        self.assertEqual(self.cur.fetchone()[0], before)
        self.assertEqual(before.count("'translation'"), 1)


if __name__ == "__main__":
    unittest.main()
