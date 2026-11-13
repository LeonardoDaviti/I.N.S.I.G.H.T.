"""Issue 0183: a background pass that would change nothing is not run again while nothing it reads changed
(markx/unchanged.py), and the check planner reads its stories a chunk at a time.

  - the rule: a pass that wrote nothing it reads, while nothing it reads changed, keeps its inputs' stamp; the next
    pass with that stamp is skipped; any change to a table it names, or to its key, runs it again; a key of None
    always runs;
  - the planners: cite's and check's passes, real, through the declarations the plan job uses: busy, then a no-op
    that keeps its stamp, then skipped; the skipped pass is proved to be what the planner would do (run anyway, it
    adds nothing and writes nothing); an edit, a new story or the window's next day runs it again;
  - the check planner a chunk of stories at a time asks the same questions in the same order as all at once.

Invented names and example hosts only. Every test rolls back (a database whose name ends in _test)."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from insight_core.markx import ent42, repo, schemas, story_window as W, tasks, unchanged
from insight_core.tests._db import requires_test_db
from insight_core.tests.test_markx_scale import CITED
from insight_core.tests.test_markx_story_window import DAYS, H, Window


def digest(cur):
    cur.execute("""SELECT md5(string_agg(x, ',' ORDER BY x)) FROM (
                     SELECT concat_ws('|', kind, guide, a, input_hash, priority, status) x FROM mx_tasks
                     UNION ALL SELECT concat_ws('|', kind, guide, post_id, why, stamp) FROM mx_plan_marks) t""")
    return cur.fetchone()[0]


class _Posts(Window):
    def text(self, pid, content):
        """The post's text replaced (its parts written again, as ingestion does)."""
        from insight_core.db.repo_post_parts import PostPartsRepository
        self.cur.execute("UPDATE posts SET content = %s WHERE id = %s", (content, pid))
        PostPartsRepository.write(self.cur, [pid])
        return pid


@requires_test_db
class TheRule(_Posts):
    TABLES = ("posts", "mx_tasks")

    def pass_(self, key="k", work=None):
        calls = []

        def run():
            calls.append(1)
            return work() if work else 0
        return unchanged.run(self.cur, "test", self.TABLES, key, run), len(calls)

    def test_a_no_op_pass_keeps_its_stamp_and_the_next_is_skipped(self):
        self.post(self.now, "Acme released Widget 4")
        self.assertEqual(self.pass_(), (0, 1))
        self.assertEqual(self.pass_(), (None, 0), "nothing changed: skipped, never run")
        self.assertEqual(self.pass_(), (None, 0))

    def test_a_change_to_a_table_it_reads_runs_it_again(self):
        pid = self.post(self.now, "Acme released Widget 4")
        self.pass_()
        self.cur.execute("UPDATE posts SET title = 'Acme released Widget 5' WHERE id = %s", (pid,))
        self.assertEqual(self.pass_(), (0, 1))
        self.assertEqual(self.pass_(), (None, 0))
        self.cur.execute("DELETE FROM posts WHERE id = %s", (pid,))
        self.assertEqual(self.pass_(), (0, 1), "a delete is a change")

    def test_a_pass_that_writes_what_it_reads_keeps_nothing(self):
        pid = self.post(self.now, "Acme released Widget 4")
        self.assertEqual(self.pass_(work=lambda: tasks.read_task(self.cur, pid)[1]), (True, 1))
        self.assertEqual(self.pass_(work=lambda: tasks.read_task(self.cur, pid)[1]), (False, 1), "it wrote: run again")
        self.assertEqual(self.pass_(work=lambda: tasks.read_task(self.cur, pid)[1]), (None, 0), "then a no-op: kept")

    def test_another_key_runs_it_and_a_key_of_none_always_runs(self):
        self.post(self.now, "Acme released Widget 4")
        self.pass_("a")
        self.assertEqual(self.pass_("b"), (0, 1))
        self.assertEqual(self.pass_(None), (0, 1))
        self.assertEqual(self.pass_(None), (0, 1), "the clock is its input: never skipped")


@requires_test_db
class ThePlanners(_Posts):
    def plan(self, kind, now=None):
        """One pass as the plan job runs it (jobs.Jobs.plan_background)."""
        now = now or self.now
        return unchanged.run(self.cur, "plan:" + kind, *tasks.background_inputs(self.cur, kind, now),
                             lambda: tasks.PLANNERS[kind](self.cur, now=now))

    def proved(self, kind, now=None):
        """The planner itself, run where the plan job skipped it: it adds nothing and writes nothing."""
        before = digest(self.cur)
        self.assertEqual(tasks.PLANNERS[kind](self.cur, now=now or self.now), 0)
        self.assertEqual(digest(self.cur), before)

    def test_cite_busy_then_a_no_op_then_skipped_and_an_edit_plans_again(self):
        schemas.set_entities_arm(self.cur, "ent-v4.2", allow_placeholder=True)
        tasks.set_reading_window(self.cur, None)
        cited = self.text(self.post(self.now - H, "A study"), CITED)
        plain = self.text(self.post(self.now - 2 * H, "Acme shipped a thing"), "Acme shipped a thing. More words here.")
        tasks.plan_posts(self.cur, "entities", days=None, now=self.now)
        ent42._not_cue.clear()
        self.assertEqual(self.plan("cite"), 1)                      # busy: a task added, the others marked
        ent42._not_cue.clear()
        self.assertEqual(self.plan("cite"), 0)                      # a no-op: its stamp kept
        ent42._not_cue.clear()
        self.assertIsNone(self.plan("cite", self.now + 3 * H))      # nothing changed: skipped (later the same day)
        ent42._not_cue.clear()
        self.proved("cite", self.now + 3 * H)
        self.text(plain, CITED.replace("Varga", "Nagy"))
        ent42._not_cue.clear()
        self.assertEqual(self.plan("cite"), 1, "an edit made it a cue: planned as before")

    def test_check_busy_then_a_no_op_then_skipped_and_a_new_day_or_story_plans_again(self):
        W.set_window(self.cur, None)
        repo.set_setting(self.cur, W.BACKFILL, {"reached": (self.now - 70 * DAYS).date().isoformat()})
        old = self.now - 60 * DAYS
        self.ix_story(*[self.post(old + n * H, f"Widget 4 news {n}") for n in range(3)])
        self.assertTrue(tasks.planned_in_background(self.cur, "check", self.now))
        self.assertEqual(self.plan("check"), 2)
        self.assertEqual(self.plan("check"), 0)
        self.assertIsNone(self.plan("check"))
        self.proved("check")
        tomorrow = self.now + DAYS
        self.assertEqual(self.plan("check", tomorrow), 0, "the window's next day is another key: run")
        self.ix_story(*[self.post(old + n * H, f"Gadget 2 news {n}") for n in range(2)])
        self.assertEqual(self.plan("check", tomorrow), 1, "a new story: run, and its check asked")

    def test_the_check_planner_a_chunk_of_stories_at_a_time_asks_the_same_in_the_same_order(self):
        W.set_window(self.cur, None)
        repo.set_setting(self.cur, W.BACKFILL, {"reached": (self.now - 70 * DAYS).date().isoformat()})
        for s in range(5):
            ids = [self.post(self.now - (s + 2) * DAYS + n * H, f"Story {s} news {n}") for n in range(2 + s % 3)]
            self.ix_story(*ids)
        roundup = self.post(self.now - 10 * DAYS, "Weekly roundup")
        self.text(roundup, "Short.")
        self.ix_story(self.post(self.now - 10 * DAYS - H, "Acme released Widget 9"), roundup)
        tasks.read_task(self.cur, roundup)
        self.answer("read", {"kind": "roundup", "events": "several", "lang": "en", "items": [], "mentions": [],
                             "main": None})

        def asked(chunk):
            with mock.patch.object(tasks, "CHECK_CHUNK", chunk):
                return [(p.id, text) for p, text in tasks.check_questions(self.cur, days=None, now=self.now)]
        whole = asked(10 ** 6)
        self.assertIn(roundup, [p for p, _ in whole], "a short roundup is checked by its reading's kind")
        self.assertEqual(asked(1), whole)
        self.assertEqual(asked(2), whole)
