"""v10.14: Mark X's slow spots at the scale of "every post read", each fixed without changing what it answers. Every
fix is checked against the old behaviour on the same rows (an equivalence test), besides what it no longer reads:

  - the planners' marks (plan_marks, migration 0108): a post passed over (its input is another post's task; for cite,
    not a cue) is not read again while its text is unchanged; once it changes, it is read as before;
  - the candidate finder: the embedded posts and the entity subjects read only within the pairs' reach of the new
    posts (the old read every one); the waiting posts a page a run;
  - a lease never plans relate or back while a decision run holds its lock (its uncommitted tasks made the lease's
    insert wait until the run ended);
  - /entities' book without the mention counts it never reads; the per-day call sums from the days they show.

Synthetic data only; the DB tests run on a database whose name ends in _test, in a transaction rolled back."""
from __future__ import annotations

import json
import random
import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.markx import candidates as C
from insight_core.markx import api, decide, ent42, entity_views, identity, jobs, plan_marks, repo, schemas, tasks
from insight_core.tests._db import db_url, requires_test_db
from insight_core.tests.test_markx_api import _Api
from insight_core.tests.test_markx_candidates import _Cands, at_cos, unit
from insight_core.tests.test_markx_entities import T0, H, D, _Db

CITED = "As Varga et al. (2021) showed, Acme grew. " + "More words. " * 10


def _no_marks():
    """The planners as they were before 0108: no mark read, none written."""
    return mock.patch.multiple(plan_marks, unmarked=lambda *a, **k: "TRUE", mark=lambda *a, **k: 0)


def _tasks(cur, kind):
    cur.execute("SELECT a::text, input_hash FROM mx_tasks WHERE kind = %s ORDER BY 1, 2", (kind,))
    return cur.fetchall()


@requires_test_db
class PlannerMarks(_Db):
    def same(self, src, at, title="Media only"):
        return self.post(src, at, title=title, text="The same words every time, a repost of one thing.")

    def loaded(self):
        """The posts each load_posts call reads, as the planner asks."""
        seen = []
        real = tasks.load_posts

        def spy(cur, ids):
            ids = [str(i) for i in ids]
            seen.extend(ids)
            return real(cur, ids)
        return seen, mock.patch.object(tasks, "load_posts", spy)

    def test_a_repeated_input_is_marked_and_not_read_again_until_its_text_changes(self):
        a = self.same(0, T0)
        b = self.same(0, T0 - H)                 # the same source and words: the same input as a
        c = self.post(1, T0 - 2 * H, title="Another thing entirely")
        self.assertEqual(tasks.plan_posts(self.cur, "read", days=5, now=T0 + H), 2)
        self.cur.execute("SELECT post_id::text, why FROM mx_plan_marks WHERE kind = 'read'")
        self.assertEqual(self.cur.fetchall(), [(b, "same_input")])
        seen, spy = self.loaded()
        with spy:
            self.assertEqual(tasks.plan_posts(self.cur, "read", days=5, now=T0 + H), 0)
        self.assertNotIn(b, seen)                                            # passed over: not read again
        self.cur.execute("UPDATE posts SET title = 'Media only, now with a caption' WHERE id = %s", (b,))
        with spy:
            self.assertEqual(tasks.plan_posts(self.cur, "read", days=5, now=T0 + H), 1)  # its text changed: read, now asked
        self.assertIn(b, seen)
        self.assertIn(b, [x for x, _h in _tasks(self.cur, "read")])
        self.assertNotIn(c, seen)

    def test_a_new_version_of_its_rows_reads_it_again_its_sources_cadence_does_not(self):
        link = ("https://example.com/a",)
        self.post(0, T0, title="Media only", text="The same words every time.", links=link)
        b = self.post(0, T0 - H, title="Media only", text="The same words every time.", links=link)
        tasks.plan_posts(self.cur, "read", days=5, now=T0 + H)
        for change, read in (("UPDATE post_links SET boilerplate = boilerplate WHERE post_id = %s", True),
                             ("UPDATE posts SET updated_at = now() WHERE id = %s", True),
                             ("UPDATE sources SET cadence_tier = 'fast', cadence_computed_at = now() "
                              "WHERE id = (SELECT source_id FROM posts WHERE id = %s)", False)):
            self.cur.execute(change, (b,))
            for again in (read, False):                    # read once (and marked again), then passed over
                seen, spy = self.loaded()
                with spy:
                    self.assertEqual(tasks.plan_posts(self.cur, "read", days=5, now=T0 + H), 0)
                self.assertEqual(b in seen, again, change)

    def test_the_tasks_planned_are_the_same_as_without_marks(self):
        """Equivalence: on the same posts (repeats, reposts across sources, a page smaller than the repeats), the
        tasks added call by call are the ones the planner added before 0108."""
        rnd = random.Random(14)
        for n in range(60):
            if rnd.random() < 0.4:
                self.same(rnd.randrange(2), T0 - n * H, title=f"Repeat {rnd.randrange(3)}")
            else:
                self.post(rnd.randrange(5), T0 - n * H, title=f"Post {n}")

        def run(marks):
            got = []
            with self.conn.transaction() as tx:
                for _ in range(8):
                    if marks:
                        got.append(tasks.plan_posts(self.cur, "read", days=5, now=T0 + H, limit=5))
                    else:
                        with _no_marks():
                            got.append(tasks.plan_posts(self.cur, "read", days=5, now=T0 + H, limit=5))
                got.append(_tasks(self.cur, "read"))
                raise psycopg.Rollback(tx)
            return got
        old, new = run(False), run(True)
        self.assertEqual(new, old)
        self.assertGreater(len(old[-1]), 20)

    def test_cite_marks_the_posts_that_are_no_cue_and_a_fresh_process_skips_them(self):
        schemas.set_entities_arm(self.cur, "ent-v4.2", allow_placeholder=True)
        cited = self.post(0, T0, text=CITED)
        plain = self.post(1, T0, text="Acme shipped a thing. More words about it here.")
        tasks.plan_posts(self.cur, "entities", days=5, now=T0 + H)
        self.assertEqual(ent42.plan(self.cur, days=5, now=T0 + H), 1)
        self.cur.execute("SELECT post_id::text, why FROM mx_plan_marks WHERE kind = 'cite'")
        self.assertEqual(self.cur.fetchall(), [(plain, "not_cue")])
        ent42._not_cue.clear()                                               # the plan job: a new process
        seen, spy = self.loaded()
        with spy:
            self.assertEqual(ent42.plan(self.cur, days=5, now=T0 + H), 0)
        self.assertNotIn(plain, seen)
        self.cur.execute("UPDATE posts SET content = %s WHERE id = %s", (CITED.replace("Varga", "Nagy"), plain))
        ent42._not_cue.clear()
        with spy:
            self.assertEqual(ent42.plan(self.cur, days=5, now=T0 + H), 1)            # now a cue: asked as before
        self.assertIn(plain, [x for x, _h in _tasks(self.cur, "cite")])
        self.assertIn(cited, [x for x, _h in _tasks(self.cur, "cite")])

    def test_cite_adds_the_same_tasks_as_without_marks(self):
        schemas.set_entities_arm(self.cur, "ent-v4.2", allow_placeholder=True)
        rnd = random.Random(42)
        for n in range(40):
            text = CITED.replace("Varga", "Varga" + "abcdefghijklmnopqrstuvwxyz"[n % 26] + "abcdefghijklmnopqrstuvwxyz"[n // 26]) if rnd.random() < 0.3 else f"Plain words about thing {n}. " * 3
            self.post(rnd.randrange(5), T0 - n * H, text=text)
        tasks.plan_posts(self.cur, "entities", days=5, now=T0 + H)

        def run(marks):
            got = []
            with self.conn.transaction() as tx:
                for _ in range(6):
                    ent42._not_cue.clear()
                    if marks:
                        got.append(ent42.plan(self.cur, days=5, now=T0 + H, limit=3))
                    else:
                        with _no_marks():
                            got.append(ent42.plan(self.cur, days=5, now=T0 + H, limit=3))
                got.append(_tasks(self.cur, "cite"))
                raise psycopg.Rollback(tx)
            return got
        new, old = run(True), run(False)
        self.assertEqual(new, old)                     # each call's count, then the tasks, ordered by (post, input)
        self.assertGreaterEqual(len(old[-1]), 8)       # not vacuous: the cue posts were asked
        self.assertGreater(sum(old[:-1]), 0)


@requires_test_db
class CandidateReads(_Cands):
    """The candidate finder reads the embedded posts within 2 x 72 hours of the new posts and the entity subjects
    within 72 hours of theirs; the old read every one. On the same rows they find the same pairs."""

    def subjects(self, pid, *names):
        task_id, _ = tasks.entities_task(self.cur, pid)
        call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=True,
                             answer={"entities": []})
        repo.add_mentions(self.cur, post_id=pid, guide="ent-v3", call_id=call, mentions=[
            {"span": n, "name": n, "name_key": tasks.name_key(n), "type": "model", "role": "subject", "version": None}
            for n in names])

    def scene(self, seed):
        """Posts every few hours over three weeks, vectors near one of three topics, a few stories, shared subjects."""
        rnd = random.Random(seed)
        srcs = [self.source() for _ in range(4)]
        start = T0 + timedelta(days=60 * seed)
        posts = []
        for n in range(70):
            at = start + timedelta(hours=rnd.uniform(0, 21 * 24))
            pid = self.post(srcs[rnd.randrange(4)], at, title=f"Post {n}",
                            vector=at_cos(rnd.uniform(0.55, 0.99), axis=1 + rnd.randrange(3)))
            posts.append(pid)
            if rnd.random() < 0.5:
                self.subjects(pid, f"Widget {rnd.randrange(3)}")
        members = rnd.sample(posts, 12)
        for k in range(4):
            self.story(*members[3 * k:3 * k + 3])
        return posts, rnd

    def everything(self):
        """The old reads: one span over all time."""
        lo, hi = datetime(1900, 1, 1, tzinfo=timezone.utc), datetime(2300, 1, 1, tzinfo=timezone.utc)
        return mock.patch.object(C, "spans", lambda times, reach: ([lo], [hi]))

    def found(self, new, **kw):
        with self.conn.transaction() as tx:
            counts = C.find(self.cur, new, **kw)
            self.cur.execute("SELECT kind, a::text, b::text, source, score FROM mx_candidates ORDER BY 1, 2, 3, 4")
            rows = self.cur.fetchall()
            raise psycopg.Rollback(tx)
        return dict(counts), rows

    def test_the_same_pairs_as_reading_every_post(self):
        for seed in (1, 2, 3):
            posts, rnd = self.scene(seed)
            for new in (rnd.sample(posts, 5), rnd.sample(posts, 20)):
                with self.everything():
                    old = self.found(new)
                new_ = self.found(new)
                self.assertEqual(new_, old, seed)
                with self.everything():
                    old_e = self.found(new, sources=("entity",))
                self.assertEqual(self.found(new, sources=("entity",)), old_e, seed)
            self.assertTrue(any(old[0].values()))

    def test_only_the_posts_a_new_post_can_reach_are_read(self):
        s1, s2 = self.source(), self.source()
        new = self.post(s1, T0, vector=unit((0, 1)))
        near = self.post(s2, T0 + 100 * H, vector=at_cos(0.9))      # within 2 x 72 h: a neighbour's neighbour
        far = self.post(s2, T0 + 200 * H, vector=at_cos(0.99))
        got = C.Posts(self.cur, extra=[new])
        self.assertEqual(got.embedded, {new, near})
        self.assertNotIn(far, got.at)

    def test_spans_merge_what_overlaps(self):
        lo, hi = C.spans([T0 + 10 * H, T0, T0 + 100 * H], 6 * H)
        self.assertEqual(lo, [T0 - 6 * H, T0 + 94 * H])
        self.assertEqual(hi, [T0 + 16 * H, T0 + 106 * H])
        self.assertEqual(C.spans([], H), ([], []))


@requires_test_db
class WaitingPage(_Cands):
    def test_waiting_posts_a_page_oldest_noted_first(self):
        ids = [str(uuid.uuid4()) for _ in range(5)]
        for n, pid in enumerate(ids):
            self.cur.execute("INSERT INTO mx_candidate_posts (post_id, noted_at) VALUES (%s, now() - %s * interval '1 minute')",
                             (pid, 10 - n))
        self.assertEqual(jobs.waiting_posts(self.cur, 3), ids[:3])
        self.assertEqual(jobs.waiting_posts(self.cur), ids)


class APageARun(_Api):
    def test_a_run_takes_a_page_and_stays_wanted_while_posts_wait(self):
        with self.conn.transaction():
            for _ in range(5):
                jobs.note_posts(self.cur, [str(uuid.uuid4())])
        seen = []
        with mock.patch.object(jobs, "WAIT_PAGE", 2), \
                mock.patch("insight_core.markx.candidates.run", lambda cur, ids, since=None: seen.append(len(ids)) or {}), \
                mock.patch("insight_core.markx.candidates.backfill", lambda cur, now: {}):
            j = jobs.Jobs(db_url())
            for _ in range(3):
                j.candidates()
                last = j.last("candidates")
                self.assertEqual(last["wanted_at"] is not None, last["last"].get("more", False))
        self.assertEqual(seen, [2, 2, 1])
        self.assertIsNone(j.last("candidates")["wanted_at"])


class LeaseDuringARun(_Api):
    """The relate and back planners of a lease rest while a decision run holds its lock: the run plans them in its
    own long transaction, and a lease inserting one of the same questions waited until the run ended (6 to 57 s on
    the server, every 5 minutes)."""

    def test_relate_and_back_are_not_planned_while_a_run_holds_the_lock(self):
        relate, back, read = mock.Mock(return_value=0), mock.Mock(return_value=0), mock.Mock(return_value=0)
        with mock.patch.dict(tasks.PLANNERS, {"relate": relate, "back": back, "read": read}):
            with psycopg.connect(db_url()) as run:
                run.execute("SELECT pg_try_advisory_xact_lock(%s)", (decide.LOCK_KEY,))
                with self.conn.transaction():
                    self.assertTrue(jobs.decision_running(self.cur))
                self.assertEqual(self.lease("relate,back,read")[0], 200)
                self.assertEqual((relate.call_count, back.call_count, read.call_count), (0, 0, 1))
                run.rollback()
            with self.conn.transaction():
                self.assertFalse(jobs.decision_running(self.cur))
            self.lease("relate,back,read")
        self.assertEqual((relate.call_count, back.call_count), (1, 1))

    def test_the_lease_no_longer_waits_on_the_runs_uncommitted_task(self):
        """The shape of the wait: the run inserted a relate question and holds it uncommitted; a lease planning
        the same question would wait for it. Under the lock the lease plans nothing and answers at once."""
        text = "relate question " + uuid.uuid4().hex
        planner = lambda cur, **kw: int(tasks.add(cur, "relate", text, a=None)[1])   # noqa: E731
        with mock.patch.dict(tasks.PLANNERS, {"relate": planner}):
            with psycopg.connect(db_url()) as run:
                run.execute("SELECT pg_try_advisory_xact_lock(%s)", (decide.LOCK_KEY,))
                schemas.load_guides(run.cursor())
                tasks.add(run.cursor(), "relate", text, a=None)
                got = {}
                t = threading.Thread(target=lambda: got.update(r=self.lease("relate")))
                t.start()
                t.join(10)
                self.assertFalse(t.is_alive(), "the lease waited on the run")
                self.assertEqual(got["r"][0], 200)
                run.rollback()


@requires_test_db
class Readers(_Db):
    def test_the_entity_list_reads_the_book_without_counts_and_answers_the_same(self):
        a = self.post(0, T0, title="Widget 4 is out")
        b = self.post(1, T0 + H, title="Widget 4 reviewed")
        self.mentions(a, ("Widget 4", "model", "subject", "Acme"), ("Acme", "org", "actor"))
        self.mentions(b, ("Widget 4", "model", "subject", "Acme"))
        from insight_core.markx import entity_stage
        entity_stage.entities(self.cur, ask=decide.Ask(self.cur, T0), now=T0 + 2 * D,
                              run_id=repo.start_run(self.cur, code_version="test", config={}), since=None, full=True)
        full = identity.load_book(self.cur)
        light = identity.load_book(self.cur, counts=False)
        self.assertEqual(sorted(light.ents), sorted(full.ents))
        self.assertEqual((light.pins, dict(light.redirect), light.alias), (full.pins, dict(full.redirect), full.alias))
        self.assertTrue(full.types and not light.types)
        now = T0 + 2 * D
        got = entity_views.entity_list(self.cur, now=now)
        with mock.patch.object(identity, "load_book", lambda cur, counts=True: full):
            self.assertEqual(json.dumps(got, default=str, sort_keys=True),
                             json.dumps(entity_views.entity_list(self.cur, now=now), default=str, sort_keys=True))
        self.assertTrue(got["items"])

    def test_the_book_counts_as_before(self):
        a = self.post(0, T0)
        self.mentions(a, ("Widget 4", "model", "subject"), ("Widget 4", "product", "actor"), ("Acme", "org", "subject"))
        from insight_core.markx import entity_stage
        entity_stage.entities(self.cur, ask=decide.Ask(self.cur, T0), now=T0 + 2 * D,
                              run_id=repo.start_run(self.cur, code_version="test", config={}), since=None, full=True)
        b = identity.load_book(self.cur)
        self.cur.execute("""SELECT entity_id::text, type, count(*), count(*) FILTER (WHERE role = 'subject')
                              FROM mx_mentions_now WHERE entity_id IS NOT NULL GROUP BY 1, 2""")
        types, subject = {}, {}
        for eid, t, n, s in self.cur.fetchall():
            types.setdefault(eid, {})[t] = types.get(eid, {}).get(t, 0) + n
            if s and identity.schemas_type(t) in identity.PRODUCT_TYPES:
                subject[eid] = subject.get(eid, 0) + s
        self.assertEqual({k: dict(v) for k, v in b.types.items()}, types)
        self.assertEqual(b.subject, subject)
        self.assertTrue(subject)


@requires_test_db
class CallsByDay(_Db):
    def calls(self, *days_ago):
        task, _ = tasks.add(self.cur, "read", "calls by day " + uuid.uuid4().hex, a=None)
        for d in days_ago:
            self.cur.execute("""INSERT INTO mx_calls (task_id, executor, model, valid, tokens_in, tokens_out, cost_usd,
                                                      created_at)
                                VALUES (%s, 'claude-code', 'haiku', %s, 10, 2, 0.001, now() - %s * interval '1 day')""",
                             (task, d % 3 != 0, d))

    def by_day(self, floor):
        where = "" if floor is False else "WHERE created_at >= COALESCE(%s, '-infinity'::timestamptz)"
        self.cur.execute(f"""SELECT created_at::date, count(*), count(*) FILTER (WHERE valid), COALESCE(sum(tokens_in), 0)
                               FROM mx_calls {where} GROUP BY 1 ORDER BY 1 DESC LIMIT 4""",
                         () if floor is False else (floor,))
        return self.cur.fetchall()

    def test_the_newest_days_with_calls_as_reading_every_call(self):
        self.assertIsNone(repo.calls_days_floor(self.cur, 4))
        self.assertEqual(self.by_day(repo.calls_days_floor(self.cur, 4)), [])
        self.calls(0, 0, 1, 3, 3, 3, 9, 10, 40, 41, 41)          # gaps between the days with calls
        self.assertEqual(self.by_day(repo.calls_days_floor(self.cur, 4)), self.by_day(False))
        self.assertEqual(len(self.by_day(False)), 4)
        self.cur.execute("DELETE FROM mx_calls")
        self.calls(2, 2)                                          # fewer days than asked
        self.assertEqual(self.by_day(repo.calls_days_floor(self.cur, 4)), self.by_day(False))
