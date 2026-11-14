"""0208 (Stealth v10.19): News ranked for the reader. The significance question (its input from the existing signals,
which members it shows, the counts in buckets), the answer's checks and score, when a row is asked (once, again only
when its posts changed and the gap passed, never while one waits), the reader's fit, the rank and the Notable lane,
the kept ranks (the jobs process), the Mark X page's and the reader's News order (the switch, `order=coverage`).
Synthetic data only; the DB tests run on a database whose name ends in _test."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from insight_core.markx import news, news_rank as R, repo, schemas, significance as S, validate
from insight_core.tests.test_markx_api import _Api, call

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def member(n, *, source="Source A", kind="telegram", hours=0, title=None, text="", links=()):
    return S.Member(id=f"p{n}", kind=kind, source=source, at=NOW - timedelta(hours=48 - hours),
                    title=title or f"Title {n}", text=text, links=list(links))


ANSWER = {"event": "new_method", "usable": "now", "shipped_in": "in a widely used library",
          "adoption": ["widely_used_library", "paper_with_code"], "coverage": "expert_breakdown", "effect": 4,
          "scope": "field_wide", "why": "Ten times faster than the classic algorithm and shipped in a common library."}


class TheQuestion(unittest.TestCase):
    def test_it_shows_the_existing_signals_first(self):
        ms = [member(1, text="Title 1 short note", links=["https://arxiv.org/abs/2611.01234"]),
              member(2, source="Source B", hours=1, text="x" * 1200, links=["https://github.com/acme/emeans"])]
        text = S.question("A new clustering method", ms, event_type="research_result",
                          subjects=[("e-means", "software"), ("Acme", "org"), ("Lab", "org"), ("Extra", "org")], voices=2)
        lines = text.splitlines()
        self.assertEqual(lines[0], "STORY: A new clustering method")
        self.assertEqual(lines[1], "KIND OF HAPPENING (measured): research result")
        self.assertEqual(lines[2], "MAIN SUBJECTS: e-means (software), Acme (org), Lab (org)")     # at most 3
        self.assertEqual(lines[3], "COVERAGE: 2 posts from 2 sources; 1 long posts (1,000+ characters of their own)")
        self.assertEqual(lines[4], "LINKED PAGES: paper, code")
        self.assertIn("[2] telegram · Source B · 2026-11-11 · 1,200 characters", text)
        self.assertIn("Text: short note", text)                         # the title is not repeated as text

    def test_counts_are_in_buckets_so_one_more_repeat_asks_nothing_new(self):
        many = [member(n, source=f"S{n}") for n in range(12)]
        self.assertEqual(S.question("H", many, voices=12), S.question("H", many + [member(99, source="S99")], voices=13))
        self.assertEqual([S.bucket(n) for n in (5, 6, 9, 10, 19, 20, 400)], ["5", "6-9", "6-9", "10-19", "10-19", "20+", "20+"])

    def test_it_shows_the_first_posts_then_the_longest_one_a_source_first(self):
        ms = [member(0), member(1, hours=1), member(2, hours=2, text="a" * 300),
              member(3, hours=3, text="b" * 3000), member(4, hours=4, source="Source C", text="c" * 2000),
              member(5, hours=5, source="Source D", text="d" * 100)]
        got = [m.id for m in S.chosen(ms)]
        self.assertEqual(got[:2], ["p0", "p1"])                                  # who broke it
        self.assertEqual(set(got), {"p0", "p1", "p2", "p3", "p4", "p5"})
        ms += [member(n, hours=6 + n, text="z" * 5000) for n in range(6, 10)]   # Source A again, long
        got = S.chosen(ms)
        self.assertEqual(len(got), S.MEMBERS)
        self.assertIn("p4", [m.id for m in got])                                 # another source before a 2nd of A

    def test_the_longest_shown_is_read_further(self):
        ms = [member(1, text="q" * 3000), member(2, source="B", text="r" * 3000 + "s")]
        text = S.question("H", ms)
        self.assertIn("r" * (S.LONG_CHARS - 1) + "…", text)
        self.assertIn("q" * (S.TEXT_CHARS - 1) + "…", text)

    def test_the_guide_is_sphere_agnostic_and_names_every_field(self):
        body = schemas.guide_body(S.GUIDE)
        self.assertNotIn(" AI", body)
        for f in schemas.SIGNIFICANCE_SCHEMA["required"]:
            self.assertIn(f"`{f}`", body)


class TheAnswer(unittest.TestCase):
    def test_a_valid_answer_passes_the_checks(self):
        self.assertIsNone(validate.check(S.KIND, ANSWER, "STORY: x", S.GUIDE)[1])

    def test_wrong_answers_are_refused(self):
        for bad in ({**ANSWER, "effect": 6}, {**ANSWER, "event": "launch"}, {**ANSWER, "adoption": ["famous"]},
                    {k: v for k, v in ANSWER.items() if k != "why"}):
            self.assertIsNotNone(validate.check(S.KIND, bad, "STORY: x", S.GUIDE)[1], bad)

    def test_the_score_is_the_effect_first(self):
        self.assertEqual(S.score(ANSWER), 1.0)                                    # .75 + .1 + .1 + .05 + .05 + .05
        small = {**ANSWER, "effect": 2, "usable": "no", "adoption": [], "coverage": "reports", "scope": "niche"}
        self.assertEqual(S.score(small), 0.2)                                     # .25 - .05
        self.assertEqual(S.score({**small, "effect": 1}), 0.0)
        self.assertIsNone(S.score(None))
        self.assertIsNone(S.score({"effect": "big"}))


class WhenARowIsAsked(unittest.TestCase):
    ROW = {"id": "r", "posts": [{"post_id": "a"}, {"post_id": "b"}]}

    def last(self, members, status="answered", hours=7):
        return {"members": set(members), "status": status, "asked_at": NOW - timedelta(hours=hours)}

    def test_once_then_only_when_its_posts_changed_past_the_gap(self):
        self.assertEqual(S.due(self.ROW, None, NOW), (True, "never asked"))
        self.assertFalse(S.due(self.ROW, self.last({"a", "b"}, hours=100), NOW)[0])             # same posts: never
        self.assertEqual(S.due(self.ROW, self.last({"a"}), NOW), (True, "its posts changed"))
        self.assertFalse(S.due(self.ROW, self.last({"a"}, hours=5), NOW)[0])                    # within the gap
        self.assertEqual(S.due(self.ROW, self.last({"a"}, status="leased"), NOW)[1], "one is waiting")


def row(rid, score, hours=10):
    return {"id": rid, "score": score, "first_at": NOW - timedelta(hours=hours), "posts": []}


class TheRank(unittest.TestCase):
    def test_coverage_is_the_score_on_a_log_scale(self):
        self.assertEqual(R.coverage(0), 0.0)
        self.assertEqual(R.coverage(R.COVERAGE_FULL), 1.0)
        self.assertEqual(R.coverage(1000), 1.0)
        self.assertLess(R.coverage(3), R.coverage(10))

    def test_significance_lifts_a_quiet_row_over_a_loud_minor_one(self):
        rows = [row("loud", 25), row("quiet", 3), row("plain", 6)]
        got = R.rank(rows, {"loud": 0.0, "quiet": 1.0, "plain": None}, {}, NOW)
        self.assertEqual([x.row_id for x in got], ["quiet", "plain", "loud"])
        self.assertEqual(got[1].significance, None)                               # not answered: the middle
        self.assertEqual(got[1].score, R.combine(None, R.coverage(6), 0.0))

    def test_the_lane_holds_significant_rows_coverage_would_bury(self):
        rows = [row(f"r{n}", 100 - n) for n in range(30)] + [row("buried", 2), row("old", 2, hours=24 * 8)]
        sig = {r["id"]: 0.3 for r in rows}
        sig.update({"r1": 0.9, "buried": 0.9, "old": 0.95})
        got = {x.row_id: x for x in R.rank(rows, sig, {}, NOW)}
        self.assertTrue(got["buried"].notable)
        self.assertFalse(got["r1"].notable)                                       # already near the top
        self.assertFalse(got["old"].notable)                                      # older than NOTABLE_DAYS
        self.assertEqual(got["buried"].why["coverage_place"], 31)

    def test_the_lane_is_small(self):
        rows = [row(f"r{n}", 100 - n) for n in range(40)]
        sig = {r["id"]: (0.9 if n >= 25 else 0.1) for n, r in enumerate(rows)}
        self.assertEqual(sum(x.notable for x in R.rank(rows, sig, {}, NOW)), R.NOTABLE_MAX)


class TheFit(unittest.TestCase):
    PROFILE = R.Profile(reads=40, posts=4000, sources={"fav": (20, 200), "busy": (2, 2000), "new": (1, 2)},
                        entities={"e-means": 6, "acme": 1}, tracked={"p9"})

    def test_a_source_read_more_than_its_share(self):
        self.assertGreater(R.source_fit(self.PROFILE, "fav"), 0.9)               # read 10x its share
        self.assertEqual(R.source_fit(self.PROFILE, "busy"), 0.0)                # read less than its share
        self.assertLess(R.source_fit(self.PROFILE, "new"), 0.5)                  # 1 of 2: smoothed toward the rate
        self.assertEqual(R.source_fit(R.Profile(), "fav"), 0.0)                  # nothing read: no fit

    def test_the_thing_read_most_and_the_tracks(self):
        value, why = R.fit(self.PROFILE, sources=["busy"], things=["acme", "e-means"], posts=["p9"])
        self.assertEqual(why, {"source": 0.0, "entity": 0.75, "thing": "e-means", "track": True})
        self.assertAlmostEqual(value, R.FIT_PARTS["entity"] * 0.75 + R.FIT_PARTS["track"])

    def test_fit_weighs_nothing_in_the_order_it_is_a_shadow(self):
        self.assertEqual(R.W_FIT, 0.0)
        self.assertEqual(R.combine(0.5, 0.5, 1.0), R.combine(0.5, 0.5, 0.0))


class Ranked(_Api):
    """The DB side: the decision stage's questions, the answers through the API, the jobs process's kept ranks, the pages."""

    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def news_run(self, rows):
        """rows: [(post ids, score)] (a row's id is its first post)."""
        run = repo.start_run(self.cur, code_version="test", config={})
        repo.add_news_rows(self.cur, run, [
            {"id": ps[0], "first_at": self.now - timedelta(hours=1), "voices": 2, "reports": 2, "shares": 0,
             "mentions": 0, "score": score, "tag": "NEW",
             "posts": [{"post_id": p, "role": "report", "position": n} for n, p in enumerate(ps)]}
            for ps, score in rows])
        repo.finish_run(self.cur, run, counts={})
        return str(run)

    def plan(self):
        with self.conn.transaction():
            return S.plan(self.cur)

    def asks(self):
        self.cur.execute("""SELECT a.row_id::text, t.id::text, t.subject_kind, t.a::text, t.input
                              FROM mx_news_significance_asks a JOIN mx_tasks t ON t.id = a.task_id ORDER BY a.asked_at""")
        return self.cur.fetchall()

    def answer_all(self, answers):
        status, work = self.lease(S.KIND, limit=50)
        self.assertEqual(status, 200, work)
        rows = {t["id"]: t for t in work["tasks"]}
        by_row = {a: tid for _r, tid, _s, a, _i in self.asks()}
        got = self.answer(*[(by_row[rid], a) for rid, a in answers.items() if by_row[rid] in rows])
        self.assertEqual(got[0], 200, got)
        return got[1]

    def test_each_row_is_asked_once_and_again_when_its_posts_change(self):
        a, b, c = self.post(title="Loud launch"), self.post(title="Quiet method"), self.post(title="Its breakdown")
        self.news_run([([a], 20), ([b], 3)])
        self.assertEqual(self.plan()["asked"], 2)
        asks = self.asks()
        self.assertEqual({(r, s, x) for r, _t, s, x, _i in asks}, {(a, "story", a), (b, "story", b)})
        self.assertIn("STORY: Quiet method", [i for r, _t, _s, _x, i in asks if r == b][0])
        self.assertEqual(self.plan()["asked"], 0)                                  # the same posts: nothing new
        self.news_run([([a], 20), ([b, c], 4)])
        self.assertEqual(self.plan()["asked"], 0)                                  # waiting (open): not again
        self.answer_all({a: ANSWER, b: ANSWER})
        self.assertEqual(self.plan()["asked"], 0)                                  # changed, within the gap
        self.cur.execute("UPDATE mx_news_significance_asks SET asked_at = asked_at - interval '7 hours'")
        got = self.plan()
        self.assertEqual(got["asked"], 1)                                          # only the row whose posts changed
        self.assertEqual(len([r for r, *_ in self.asks() if r == b]), 2)

    def test_answers_rank_the_rows_and_the_pages_follow_the_switch(self):
        loud, quiet, plain = self.post(title="Loud minor launch"), self.post(title="Quiet method"), self.post(title="Plain")
        run = self.news_run([([loud], 25), ([quiet], 3), ([plain], 6)])
        self.plan()
        minor = {**ANSWER, "event": "product_launch", "effect": 1, "usable": "no", "adoption": [],
                 "coverage": "passing_mentions", "scope": "niche"}
        got = self.answer_all({loud: minor, quiet: ANSWER})
        self.assertEqual(got["valid"], 2, got)
        answers = S.answers(self.cur, [loud, quiet, plain])
        self.assertEqual((answers[quiet]["score"], answers[loud]["score"], plain in answers), (1.0, 0.0, False))
        with self.conn.transaction():
            kept = R.keep(self.cur)
        self.assertEqual((kept["run"], kept["rows"], kept["answered"]), (run, 3, 2))
        ranks = R.read(self.cur, [loud, quiet, plain])
        self.assertEqual(ranks[quiet]["significance"], 1.0)
        self.assertIsNone(ranks[plain]["significance"])
        self.assertEqual(ranks[quiet]["why"]["event"], "new_method")
        # the Mark X page: ranked by default (the measure passed its bar), the rank on each row
        status, page = call("GET", "/api/markx/news", query={"all": 1})
        self.assertEqual(status, 200)
        self.assertEqual(page["order"], "ranked")
        self.assertEqual([i["id"] for i in page["items"]], [quiet, plain, loud])
        self.assertEqual(page["items"][0]["rank"]["significance"], 1.0)
        # the switch: by coverage (a Shadow): the old order, the ranks still shown
        with self.conn.transaction():
            R.set_mode(self.cur, "coverage")
        page = call("GET", "/api/markx/news", query={"all": 1})[1]
        self.assertEqual((page["order"], [i["id"] for i in page["items"]]), ("coverage", [loud, plain, quiet]))
        self.assertIsNotNone(page["items"][-1]["rank"])
        with self.assertRaises(ValueError):
            R.set_mode(self.cur, "loudest")

    def test_a_row_not_ranked_yet_keeps_its_coverage_place(self):
        a, b = self.post(title="One"), self.post(title="Two")
        self.news_run([([a], 3), ([b], 9)])
        page = call("GET", "/api/markx/news", query={"all": 1})[1]
        self.assertEqual([i["id"] for i in page["items"]], [b, a])
        self.assertEqual([i["rank"] for i in page["items"]], [None, None])
        self.assertEqual(page["notable"], [])

    def test_the_kept_page_is_built_again_when_an_answer_lands(self):
        a, b = self.post(title="One"), self.post(title="Two")
        self.news_run([([a], 3), ([b], 9)])
        with self.conn.transaction():
            first = news.keep_pages(self.cur)
        self.assertEqual(sorted(first["built"]), ["all", "differences"])
        self.assertEqual(first["rank"]["rows"], 2)
        with self.conn.transaction():
            self.assertFalse(news.kept_missing(self.cur))
        self.plan()
        self.answer_all({a: ANSWER})
        with self.conn.transaction():
            self.assertTrue(news.kept_missing(self.cur))                           # a significance answer moved it
            again = news.keep_pages(self.cur)
        self.assertEqual(again["rank"]["answered"], 1)
        self.assertEqual(R.read(self.cur, [a])[a]["significance"], 1.0)


class TheReadersNews(_Api):
    """NewsService.ranked: the reader's News over Mark X's rows (the items as news_on built them)."""

    def items(self, *rows):
        return [{"id": f"lead-{rid}", "story": {"id": rid}, "news": {"part": part, "score": score,
                                                                      "first_at": datetime.now(timezone.utc)}}
                for rid, part, score in rows]

    def keep(self, rid, *, sig, score, notable=False):
        run = repo.start_run(self.cur, code_version="test", config={})
        self.cur.execute("""INSERT INTO mx_news_rank (row_id, run_id, significance, fit, coverage, score, notable, why)
                            VALUES (%s, %s, %s, 0, 0, %s, %s, '{"event": "new_method", "effect": 4, "usable": "now"}')""",
                         (rid, run, sig, score, notable))

    def test_the_lane_first_then_each_part_by_its_rank(self):
        from insight_core.services.news_service import NewsService
        ids = [self.post(title=f"Row {n}") for n in range(4)]   # any uuids
        self.keep(ids[0], sig=0.1, score=0.4)
        self.keep(ids[1], sig=0.9, score=0.6)
        self.keep(ids[2], sig=1.0, score=0.7, notable=True)
        items = self.items((ids[0], "recent", 9), (ids[1], "recent", 3), (ids[2], "earlier", 2), (ids[3], "recent", 1))
        got = NewsService.ranked(self.cur, [dict(i, news=dict(i["news"])) for i in items])
        self.assertEqual(got["order"], "ranked")
        self.assertEqual([i["story"]["id"] for i in got["items"]], [ids[2], ids[1], ids[0], ids[3]])
        self.assertEqual([i["news"]["notable"] for i in got["items"]], [True, False, False, False])
        self.assertEqual(got["items"][0]["news"]["rank"]["event"], "new_method")
        self.assertNotIn("rank", got["items"][3]["news"])                           # not ranked yet
        old = NewsService.ranked(self.cur, [dict(i, news=dict(i["news"])) for i in items], "coverage")
        self.assertEqual(([i["story"]["id"] for i in old["items"]], old["order"]), (ids, "coverage"))
        self.assertFalse(any(i["news"]["notable"] for i in old["items"]))


if __name__ == "__main__":
    unittest.main()
