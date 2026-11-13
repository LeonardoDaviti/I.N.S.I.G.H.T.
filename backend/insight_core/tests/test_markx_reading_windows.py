"""Issue 0176 (Stealth v10.16): the fresh lane (posts fetched in the last 24 hours planned and leased first, with a
cap both ways) and long posts' entities read in windows (0150 C). The DB tests run only on a database whose name ends
in _test, each in a transaction rolled back after it."""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import api, plan_marks, repo, schemas, tasks
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests import test_markx_incremental as TI
from insight_core.tests.test_markx_api import MX_TABLES, _Api

H, D = timedelta(hours=1), timedelta(days=1)
T0 = datetime(2100, 1, 5, 12, tzinfo=timezone.utc)   # the planners' tests: a clock of their own (the test database
                                                      # keeps other tests' posts, dated now)


def _post(text: str, title: str = "A long round-up") -> tasks.Post:
    return tasks.Post(id=str(uuid.uuid4()), kind="site", source="Example Site", source_id="s", at=datetime.now(timezone.utc),
                      title=title, text=text, links=[("https://example.com/a", "a link")])


def _tokens(n: int) -> str:
    """A text of n distinct tokens (t00000 t00001 ...): no token is a part of another."""
    return " ".join(f"t{k:05d}" for k in range(n))


def _long(n_chars: int, every: int = 700) -> str:
    """A text of about n_chars with a distinct person named every `every` characters (Person0, Person1, ...)."""
    out, k = [], 0
    while sum(len(x) for x in out) < n_chars:
        out.append(f"Then Person{k} Example said a thing about the topic. " + "Filler words go on here. " * ((every - 60) // 25))
        k += 1
    return "".join(out)[:n_chars]


class Windows(unittest.TestCase):
    """The split itself: pure."""

    def test_a_short_post_is_one_window_and_its_input_is_todays(self):
        for chars in (1500, 6000):
            p = _post("Acme released Widget 4. " * 40)              # 960 characters
            self.assertEqual(tasks.text_windows(p.text, chars), [(0, len(p.text))])
            self.assertEqual(tasks.entity_inputs(p, chars), [tasks.entities_input(p, chars)])
            exact = _post("x" * chars)                              # exactly one window long
            self.assertEqual(tasks.entity_inputs(exact, chars), [tasks.entities_input(exact, chars)])
            self.assertEqual(tasks.window_of(tasks.entities_input(p, chars)), 0)

    def test_a_long_post_is_windows_of_the_guides_size_that_overlap_and_cover_it(self):
        text = _long(20_000)
        for chars in (1500, 6000):
            ws = tasks.text_windows(text, chars, cap=100)
            self.assertEqual(ws[0], (0, chars))
            self.assertEqual(ws[-1][1], len(text))                                     # the whole text
            for (a0, a1), (b0, b1) in zip(ws, ws[1:]):
                self.assertEqual(a1 - b0, tasks.WINDOW_OVERLAP)                       # each shares the overlap
                self.assertLessEqual(b1 - b0, chars)
            self.assertEqual(len(ws), 1 + -(-(len(text) - chars) // (chars - tasks.WINDOW_OVERLAP)))

    def test_windows_are_capped_and_the_rest_stays_unread(self):
        text = _long(60_000)
        ws = tasks.text_windows(text, 1500, cap=12)
        self.assertEqual(len(ws), 12)
        self.assertLess(ws[-1][1], len(text))
        self.assertEqual(len(tasks.text_windows(text, 1500, cap=1)), 1)              # cap 1: as before 0176

    def test_each_later_window_says_which_it_is_and_shows_its_text_without_links(self):
        p = _post(_long(9_000))
        inputs = tasks.entity_inputs(p, 1500)
        self.assertEqual(inputs[0], tasks.entities_input(p, 1500))
        self.assertIn("Links, in order:", inputs[0])
        ws = tasks.text_windows(p.text, 1500)
        for w, x in enumerate(inputs[1:], 1):
            self.assertEqual(tasks.window_of(x), w)
            self.assertIn(f"Window: {w + 1} of {len(inputs)} of the post's text", x)
            self.assertIn("Title: A long round-up", x)
            self.assertNotIn("Links, in order:", x)
            self.assertIn(p.text[ws[w][0]:ws[w][1]], x)
            shared, rest = tasks.window_overlap(x)
            self.assertEqual(shared, p.text[ws[w][0]:ws[w][0] + tasks.WINDOW_OVERLAP])
        self.assertEqual(len(set(inputs)), len(inputs))                               # a task each

    def test_a_text_that_writes_a_window_line_is_still_its_first_window(self):
        p = _post("Window: 3 of 4 is how the slides were numbered.\n" + "Words here. " * 50)
        self.assertEqual(tasks.window_of(tasks.entities_input(p, 1500)), 0)


@requires_test_db
class _Db(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        schemas.load_guides(self.cur)
        self.source = insert_scratch_source(self.cur, platform="rss",
                                            settings_json=json.dumps({"display_name": "Example Site"}))
        self.now = T0

    def post(self, text=None, *, title="Acme released Widget 4", published=None, fetched=None):
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        text = text or f"{title}. More words about it here, note {url[-8:]}."
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at, fetched_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                         (self.source, url, url, title, text, published or self.now - H, fetched or self.now - H))
        return str(self.cur.fetchone()[0])

    def entity_tasks(self, pid):
        self.cur.execute("SELECT id, input FROM mx_tasks WHERE kind = 'entities' AND a = %s ORDER BY created_at, id", (pid,))
        return self.cur.fetchall()

    def answer(self, tid, entities):
        task = repo.get_task(self.cur, tid)
        ans = {"entities": entities}
        call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
        repo.answer_task(self.cur, tid)
        tasks.record(self.cur, task, call, ans)


class WindowTasks(_Db):
    def test_a_short_post_is_planned_exactly_as_before(self):
        pid = self.post()
        self.assertEqual(tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H), 1)
        (_tid, x), = self.entity_tasks(pid)
        p = tasks.load_posts(self.cur, [pid])[pid]
        self.assertEqual(x, tasks.entities_input(p, schemas.entities_arm(self.cur).chars))
        self.assertEqual(tasks.plan_windows(self.cur, days=5, now=self.now + H), 0)

    def test_a_long_post_is_a_task_a_window_up_to_the_cap(self):
        pid = self.post(_long(9_000))
        n = len(tasks.text_windows(_long(9_000), 1500))
        self.assertEqual(tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H), n)
        got = self.entity_tasks(pid)
        self.assertEqual(sorted(tasks.window_of(x) for _t, x in got), list(range(n)))
        big = self.post(_long(60_000), title="A bigger round-up")
        self.assertEqual(tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H), tasks.MAX_WINDOWS)
        self.assertEqual(len(self.entity_tasks(big)), tasks.MAX_WINDOWS)

    def test_the_owners_cap_of_one_is_the_first_window_only(self):
        tasks.set_max_windows(self.cur, 1)
        pid = self.post(_long(9_000))
        self.assertEqual(tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H), 1)
        self.assertEqual(tasks.plan_windows(self.cur, days=5, now=self.now + H), 0)
        tasks.set_max_windows(self.cur, 12)                       # raised: the earlier post's later windows follow
        self.assertEqual(tasks.plan_windows(self.cur, days=5, now=self.now + H), len(tasks.text_windows(_long(9_000), 1500)) - 1)
        self.assertEqual(tasks.plan_windows(self.cur, days=5, now=self.now + H), 0)
        self.assertEqual(len(self.entity_tasks(pid)), len(tasks.text_windows(_long(9_000), 1500)))

    def test_a_post_long_only_in_bytes_is_marked_and_not_read_again(self):
        tasks.set_max_windows(self.cur, 1)
        pid = self.post("Новости дня. " * 100)                     # 1,300 characters, 2,300 bytes
        tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H)
        tasks.set_max_windows(self.cur, 12)
        self.assertEqual(tasks.plan_windows(self.cur, days=5, now=self.now + H), 0)
        self.cur.execute("SELECT post_id::text, why FROM mx_plan_marks WHERE kind = %s", (tasks.WINDOWS_MARK,))
        self.assertEqual(self.cur.fetchall(), [(pid, plan_marks.ONE_WINDOW)])

    def test_the_entities_planner_adds_the_windows_of_posts_asked_before(self):
        tasks.set_max_windows(self.cur, 1)
        pid = self.post(_long(4_000))
        tasks.PLANNERS["entities"](self.cur, days=5, now=self.now + H)
        tasks.set_max_windows(self.cur, 12)
        self.assertEqual(tasks.PLANNERS["entities"](self.cur, days=5, now=self.now + H), len(tasks.text_windows(_long(4_000), 1500)) - 1)
        self.assertEqual(len(self.entity_tasks(pid)), len(tasks.text_windows(_long(4_000), 1500)))


class WindowMentions(_Db):
    def ent(self, name, span=None):
        return {"span": span or name, "name": name, "type": "person", "role": "subject"}

    def test_each_window_records_its_mentions_with_its_index_and_numbers(self):
        text = _long(5_000)
        pid = self.post(text)
        tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H)
        by_window = {tasks.window_of(x): tid for tid, x in self.entity_tasks(pid)}
        self.assertEqual(len(by_window), 4)
        # answered out of order: window 2 first
        self.answer(by_window[2], [self.ent("Person9 Example")])
        self.answer(by_window[0], [self.ent("Person0 Example"), self.ent("Person1 Example")])
        self.answer(by_window[1], [])
        self.cur.execute("SELECT name, win, n FROM mx_mentions_now WHERE post_id = %s ORDER BY n", (pid,))
        self.assertEqual(self.cur.fetchall(), [("Person0 Example", 0, 0), ("Person1 Example", 0, 1),
                                               ("Person9 Example", 2, 2 * tasks.WINDOW_N)])
        self.answer(by_window[0], [self.ent("Someone Else")])            # a later answer of a window adds nothing
        self.cur.execute("SELECT count(*) FROM mx_mentions WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone()[0], 3)

    def test_a_name_wholly_in_the_overlap_is_the_window_befores(self):
        pid = self.post(_tokens(800))
        tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H)
        x1 = next(x for _t, x in self.entity_tasks(pid) if tasks.window_of(x) == 1)
        t1 = next(t for t, x in self.entity_tasks(pid) if tasks.window_of(x) == 1)
        shared, rest = tasks.window_overlap(x1)
        in_overlap = shared.split()[3]
        self.assertNotIn(in_overlap, rest)
        self.answer(t1, [self.ent("Overlap Name", span=in_overlap), self.ent("Later Name", span=rest.split()[5])])
        self.cur.execute("SELECT name FROM mx_mentions WHERE post_id = %s", (pid,))
        self.assertEqual([r[0] for r in self.cur.fetchall()], ["Later Name"])

    def test_a_short_posts_mentions_are_as_before(self):
        pid = self.post()
        tid, _new = tasks.entities_task(self.cur, pid)
        self.answer(tid, [self.ent("Acme", span="Acme")])
        self.cur.execute("SELECT name, win, n FROM mx_mentions WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchall(), [("Acme", 0, 0)])

    def test_a_later_window_marks_the_set_changed(self):
        pid = self.post(_long(3_000))
        tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H)
        by_window = {tasks.window_of(x): tid for tid, x in self.entity_tasks(pid)}
        self.answer(by_window[0], [self.ent("Person0 Example")])
        self.cur.execute("UPDATE mx_mention_sets SET at = now() - interval '1 day' WHERE post_id = %s RETURNING call_id", (pid,))
        first_call = self.cur.fetchone()[0]
        self.answer(by_window[1], [self.ent("Person3 Example")])
        self.cur.execute("SELECT at > now() - interval '1 hour', call_id FROM mx_mention_sets WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone(), (True, first_call))


class WindowsUnderEnt42(_Db):
    """ent-v4.2 (the server's arm, 6,000 characters): a later window drops the post's own title, takes no cite merge,
    and a cite answer waits for the first window, as it waited for the post's one answer before."""

    def test_a_later_window_and_the_cite_answer(self):
        from insight_core.markx import ent42
        schemas.set_entities_arm(self.cur, "ent-v4.2")
        title = "Weekly roundup of model releases"
        pid = self.post(_long(9_000), title=title)
        self.assertEqual(tasks.plan_posts(self.cur, "entities", days=5, now=self.now + H), 2)
        by_window = {tasks.window_of(x): tid for tid, x in self.entity_tasks(pid)}
        doc = {"span": title, "name": title, "type": "document", "role": "subject"}
        body = tasks.window_overlap(repo.get_task(self.cur, by_window[1])["input"])[1]
        name = "Person" + body.split("Person", 1)[1].split(" said", 1)[0]
        self.answer(by_window[1], [doc, {"span": name, "name": name, "type": "person", "role": "subject"}])
        self.cur.execute("SELECT name, win FROM mx_mentions WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchall(), [(name, 1)])
        cite, _ = tasks.add(self.cur, "cite", "the cite question of the post", a=pid)
        task = repo.get_task(self.cur, cite)
        call = repo.add_call(self.cur, task_id=cite, executor="claude-code", model="haiku", valid=True,
                             answer={"entities": []})
        self.assertEqual(ent42.after_cite(self.cur, task, call, {"entities": [
            {"span": "Example Lab", "name": "Example Lab", "type": "org", "role": "source"}]}), 0)   # waits for window 1


class FreshPlanning(_Db):
    def test_a_post_fetched_today_is_planned_whatever_its_date_and_the_window(self):
        tasks.set_reading_window(self.cur, 2)
        late = self.post(title="A deal closed", published=self.now - 5 * D, fetched=self.now - 2 * H)
        old = self.post(title="Old news", published=self.now - 5 * D, fetched=self.now - 3 * D)
        self.post(title="From an archive", published=self.now - 300 * D, fetched=self.now - H)   # imported: not new
        self.assertEqual(tasks.plan_posts(self.cur, "read", now=self.now), 0)                   # outside the window: never, before
        self.assertEqual(tasks.plan_fresh(self.cur, "read", now=self.now), 1)
        self.assertEqual(tasks.plan_fresh(self.cur, "entities", now=self.now), 1)
        self.cur.execute("SELECT DISTINCT a::text FROM mx_tasks")
        self.assertEqual({r[0] for r in self.cur.fetchall()}, {late})
        self.assertNotEqual(late, old)

    def test_a_surfaced_post_is_fresh(self):
        pid = self.post(title="A page that changed", published=self.now - 30 * D, fetched=self.now - 30 * D)
        self.assertEqual(tasks.plan_fresh(self.cur, "read", now=self.now), 0)
        self.cur.execute("UPDATE posts SET surfaced_at = %s WHERE id = %s", (self.now - H, pid))
        self.assertEqual(tasks.plan_fresh(self.cur, "read", now=self.now), 1)


class FreshLease(_Db):
    """The lease reads the database's clock: these posts are dated by it (only this test's tasks are queued)."""

    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def queue(self, n, *, fresh, kind="read"):
        ids = []
        for k in range(n):
            at = self.now - (2 * H if fresh else 5 * D) - k * timedelta(minutes=1)
            pid = self.post(title=f"{'Fresh' if fresh else 'Backfill'} post {k}", published=at, fetched=at)
            ids.append(str(getattr(tasks, f"{kind}_task")(self.cur, pid)[0]))
        return ids

    def lease(self, limit, **kw):
        kw.setdefault("fresh", tasks.FRESH_KINDS)
        kw.setdefault("fresh_hours", tasks.FRESH_HOURS)
        return [str(t["id"]) for t in repo.lease_tasks(self.cur, kinds=["read", "entities", "headline"], limit=limit,
                                                         worker="w", windowed=tasks.WINDOWED, **kw)]

    def test_a_big_backfill_never_starves_the_fresh_lane(self):
        old = self.queue(60, fresh=False)
        self.cur.execute("UPDATE mx_tasks SET priority = -1 WHERE id = ANY(%s::uuid[])", (old,))   # even urgent ones
        new = self.queue(5, fresh=True)
        got = self.lease(8)
        self.assertEqual(len(got), 8)
        self.assertTrue(set(new) <= set(got), "every fresh task in the first lease")

    def test_the_fresh_lane_never_starves_the_backfill(self):
        old = self.queue(10, fresh=False)
        new = self.queue(40, fresh=True)
        for limit, cap in ((8, 6), (20, 15), (2, 1)):
            got = self.lease(limit)
            self.assertEqual(len(got), limit)
            self.assertEqual(sum(1 for t in got if t in new), cap, limit)
            self.assertEqual(sum(1 for t in got if t in old), limit - cap, limit)

    def test_a_lane_with_nothing_else_waiting_fills_the_lease(self):
        new = self.queue(10, fresh=True)
        first = self.lease(8)
        self.assertEqual(len(first), 8)
        self.assertEqual(sorted(first + self.lease(8)), sorted(new))

    def test_without_the_lane_the_order_is_as_before(self):
        old = self.queue(30, fresh=False)
        new = self.queue(3, fresh=True)
        got = self.lease(5, fresh=(), fresh_hours=None)
        self.assertEqual((len(set(got) & set(new)), len(set(got) & set(old))), (3, 2))   # today's first by rank, as before

    def test_a_fresh_posts_headline_rides_in_the_lane(self):
        old = self.queue(20, fresh=False)
        self.cur.execute("UPDATE mx_tasks SET priority = -1 WHERE id = ANY(%s::uuid[])", (old,))
        pid = self.post(title="A deal closed", published=self.now - 3 * D, fetched=self.now - H)
        hid, _ = tasks.headline_task(self.cur, [pid])
        self.assertIn(str(hid), self.lease(4))

    def test_the_lag_of_a_fresh_post_behind_a_backfill(self):
        """The fixture behind the issue's numbers: 400 backfill tasks waiting, 10 posts fetched now, leases of 20.
        Before 0176 the new posts wait behind the whole queue only when their dates rank them behind it (a post dated
        days before it was fetched, the real case); with the lane they are all in the first lease."""
        old = self.queue(400, fresh=False)
        self.cur.execute("UPDATE posts SET published_at = now() - interval '1 day' WHERE id IN "
                         "(SELECT a FROM mx_tasks WHERE id = ANY(%s::uuid[]))", (old,))       # the backfill: yesterday's
        new = []
        for k in range(10):     # fetched now, dated days back (the deal-close posts: written, then fetched late)
            pid = self.post(title=f"Deal post {k}", published=self.now - 5 * D, fetched=self.now - timedelta(minutes=k))
            new.append(str(tasks.read_task(self.cur, pid)[0]))

        def leases_until_read(**kw):
            self.cur.execute("SAVEPOINT lag")
            n, left = 0, set(new)
            while left and n < 100:
                n += 1
                left -= set(self.lease(20, **kw))
            self.cur.execute("ROLLBACK TO SAVEPOINT lag")
            return n
        self.assertEqual((leases_until_read(fresh=(), fresh_hours=None), leases_until_read()), (21, 1))


class FreshLaneApi(_Api):
    plan = True

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, api, "FRESH_REST_SECONDS", api.FRESH_REST_SECONDS)
        api.FRESH_REST_SECONDS = 0.0

    def test_a_lease_plans_new_posts_even_when_the_queue_is_full(self):
        for k in range(25):                                         # a full queue: the general planner rests
            pid = self.post(title=f"Backfill {k}", at=datetime.now(timezone.utc) - 5 * D)
            self.cur.execute("UPDATE posts SET fetched_at = now() - interval '5 days' WHERE id = %s", (pid,))
            self.task("read", pid)
        new = self.post(title="A deal closed", at=datetime.now(timezone.utc) - 5 * D)
        with self.conn.transaction():
            tasks.set_reading_window(self.cur, 2)                       # its date is outside the reading window
            tasks.note_planned(self.cur, "read", 2)
        status, body = self.lease("read", limit=4)
        self.assertEqual(status, 200, body)
        self.cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'read' AND a = %s", (new,))
        self.assertEqual(self.cur.fetchone()[0], 1)          # planned (the lease's order: FreshLease)

    def test_an_entities_task_carries_its_post(self):
        pid = self.post(text=_long(4_000))
        status, body = self.lease("entities", limit=20)
        self.assertEqual(status, 200, body)
        self.assertTrue(all(t.get("post") for t in body["tasks"]))
        self.assertEqual(sum(1 for t in body["tasks"] if t["post"] == pid), len(tasks.text_windows(_long(4_000), 1500)))


@requires_test_db
class WindowsIncremental(unittest.TestCase):
    """0169's invariant with windows: an incremental run after a long post's later windows are answered is a full
    run's result (the entities stage reads mx_mentions_now, every window's rows). The scene is 0169's tests'."""
    setUp = TI.Incremental.setUp
    post, ix_story, answer, read_all, scene = (TI.Incremental.post, TI.Incremental.ix_story, TI.Incremental.answer,
                                               TI.Incremental.read_all, TI.Incremental.scene)
    go, full_writes_nothing = TI.Incremental.go, TI.Incremental.full_writes_nothing

    def test_an_incremental_run_after_later_windows_is_a_full_runs_result(self):
        self.scene()
        self.go()
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        src = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example"}))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                         (src, url, url, "A round-up of the week", _long(5_000), self.now - 2 * H))
        pid = str(self.cur.fetchone()[0])
        tasks.entities_task(self.cur, pid)
        self.cur.execute("SELECT id, input FROM mx_tasks WHERE kind = 'entities' AND a = %s", (pid,))
        rows = self.cur.fetchall()
        self.assertGreater(len(rows), 1)
        self.go()                                   # the new post and source read (a new source may make it full)
        for tid, x in sorted(rows, key=lambda r: tasks.window_of(r[1])):
            body = tasks.window_overlap(x)[1] or x.split("\nText: ", 1)[1]     # a name past the overlap
            name = "Person" + body.split("Person", 1)[1].split(" said", 1)[0]
            ans = {"entities": [{"span": name, "name": name, "type": "person", "role": "subject"}]}
            call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, repo.get_task(self.cur, tid), call, ans)
            out = self.go()
            self.assertEqual(out["run"]["kind"], "incremental")
            self.full_writes_nothing()
        self.cur.execute("SELECT count(DISTINCT win) FROM mx_mentions_now WHERE post_id = %s", (pid,))
        self.assertEqual(self.cur.fetchone()[0], len(rows))


if __name__ == "__main__":
    unittest.main()
