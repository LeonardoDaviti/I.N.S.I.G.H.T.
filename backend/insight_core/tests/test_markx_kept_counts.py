"""Mark X's totals, kept (issue 0195, migration 0132, markx/kept_counts.py): the tasks by kind and status and the
calls' totals always equal the GROUP BY and sums over every row they replace, through inserts, leases, answers,
failures, deletes and folds. One transaction per test, rolled back; a _test database; invented rows only."""
from __future__ import annotations

import unittest

import psycopg

from insight_core.markx import kept_counts as K, repo
from insight_core.tests._db import db_url, requires_test_db


@requires_test_db
class KeptCounts(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        repo.put_guide(self.cur, "kept-0195", "read", "A guide for the kept counts test.")

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def task(self, n: int, kind: str = "read"):
        return repo.add_task(self.cur, kind=kind, guide="kept-0195", subject_kind="post", input=f"kept 0195 #{n}")[0]

    def same(self):
        self.assertEqual(K.check(self.cur), {})

    def test_the_kept_totals_follow_every_write_and_fold(self):
        self.same()
        ids = [self.task(n) for n in range(5)] + [self.task(n, kind="entities") for n in range(3)]
        self.same()
        self.cur.execute("UPDATE mx_tasks SET status = 'leased', lease_until = now() + interval '1 hour', leased_by = 'w' "
                         "WHERE id = ANY(%s)", (ids[:3],))
        self.same()
        repo.answer_task(self.cur, ids[0])
        repo.fail_attempt(self.cur, ids[1], "bad", max_attempts=1)
        self.cur.execute("UPDATE mx_tasks SET priority = priority + 1 WHERE id = ANY(%s)", (ids,))   # no count moves
        self.same()
        for n, t in enumerate(ids[:4]):
            repo.add_call(self.cur, task_id=t, executor="api", model="m", valid=n % 2 == 0, answer={},
                          tokens_in=100 + n, tokens_out=10 * n, cost_usd=0.001 * (n + 1))
        self.same()
        K.fold(self.cur)
        self.cur.execute("SELECT count(*) FROM mx_counts_delta")
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.same()
        self.cur.execute("UPDATE mx_calls SET tokens_in = tokens_in + 5 WHERE task_id = %s", (ids[0],))
        self.cur.execute("DELETE FROM mx_calls WHERE task_id = %s", (ids[3],))
        self.cur.execute("DELETE FROM mx_tasks WHERE id = %s", (ids[7],))
        self.same()
        K.fold(self.cur)
        self.same()
        self.assertEqual(repo.queue_counts(self.cur), K.queue_counts(self.cur))

    def test_a_kind_with_no_task_left_is_not_listed(self):
        t = self.task(99, kind="cite")
        self.assertIn("cite", K.queue_counts(self.cur))
        self.cur.execute("DELETE FROM mx_tasks WHERE id = %s", (t,))
        K.fold(self.cur)
        self.same()


if __name__ == "__main__":
    unittest.main()
