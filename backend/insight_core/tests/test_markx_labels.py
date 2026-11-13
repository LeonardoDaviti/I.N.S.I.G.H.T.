"""Mark X Shadow's labels (issue 0086 F): the queue (near a bar, every merge, a weighted sample of the rest), the dev and
test split by date, each feature's precision with its bar and interval, one answer a new row, the one tap on Mark X News
members, and the routes. 0182: the queue is built by the jobs process and kept; the routes read only the kept queue
(never `population`), and answer "being built" until it is kept. Synthetic data only; the DB tests run on a database
whose name ends in _test."""
from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.markx import api, decide as D, labels as L, repo, schemas, tasks
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES, call

T = datetime(2100, 3, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
DAY = timedelta(days=1)
LONG = 30


def item(n, feature="join", p=0.9, accepted=True, relation="same_event", bar=0.6, day=0):
    return L.Item(id=f"00000000-0000-0000-0000-{n:012d}", feature=feature, post=None, day=T + day * DAY, p=p, bar=bar,
                  relation=relation, accepted=accepted)



def _wanted(cur) -> bool:
    """0199, 0198: the Labels queue is wanted (labels.ask's mark, which the jobs process's policy reads)."""
    from insight_core.markx import jobs
    return jobs.state(cur)["labels"]["wanted_at"] is not None

class Queue(unittest.TestCase):
    """The pure parts: the pools, the sample and its order, the cut, the precision arithmetic."""

    def test_near_a_bar_and_every_merge_are_asked_and_the_rest_sampled(self):
        items = [item(n, p=0.65) for n in range(5)]                                  # near the 0.6 bar
        items += [item(100 + n, p=0.95) for n in range(30)]                          # accepted, far from the bar
        items += [item(200 + n, p=0.1, accepted=False, relation="different") for n in range(30)]
        items += [item(300 + n, feature="merge", p=0.3, bar=0.85, accepted=False, relation="different") for n in range(4)]
        q = L.build(items, L.Settings(sample=6))
        pools = {}
        for i in q.order:
            pools.setdefault(q.items[i].pool, []).append(i)
        self.assertEqual({k: len(v) for k, v in pools.items()},
                         {"join:near": 5, "join:accepted": 6, "join:rejected": 6, "merge:all": 4})
        self.assertEqual(q.pools["join:accepted"], 30)
        self.assertEqual(q.items[pools["join:accepted"][0]].weight_hint, 5.0)
        # stable: the same population gives the same queue
        self.assertEqual(L.build(items, L.Settings(sample=6)).order, q.order)
        # interleaved: the first two items are one join and one merge
        self.assertEqual({q.items[i].feature for i in q.order[:2]}, {"join", "merge"})

    def test_the_newest_quarter_of_days_is_test(self):
        q = L.build([item(n, day=n) for n in range(8)], L.Settings(sample=99))
        self.assertEqual(q.cut, (T + 6 * DAY).date().isoformat())
        self.assertEqual([q.split_of(q.items[i]) for i in sorted(q.items)], ["dev"] * 6 + ["test"] * 2)

    def test_what_is_right_per_feature(self):
        self.assertTrue(L.right(item(1), "follow_up"))                               # a follow-up joins (F2)
        self.assertFalse(L.right(item(1), "related"))
        self.assertTrue(L.right(item(1, accepted=False), "different"))
        check = item(2, feature="check", p=0.1, bar=0.3)
        self.assertTrue(L.right(check, "related"))                                    # taken out, rightly
        self.assertFalse(L.right(check, "same_event"))
        merge = item(3, feature="merge", bar=0.85)
        self.assertFalse(L.right(merge, "follow_up"))                                 # a follow-up is not a merge
        self.assertTrue(L.right(item(4, feature="connect"), "related"))
        self.assertTrue(L.right(item(5, feature="entities", p=None, bar=None), "right"))

    def test_wilson(self):
        lo, hi = L.wilson(9, 10)
        self.assertAlmostEqual(lo, 0.5958, places=3)
        self.assertAlmostEqual(hi, 0.9821, places=3)

    def test_precision_weighs_each_pool_back_to_its_size(self):
        near = [item(n, p=0.62) for n in range(10)]                                   # 10 of 10 labelled
        far = [item(100 + n, p=0.95) for n in range(90)]                              # 10 of 90 labelled
        q = L.build(near + far, L.Settings(sample=10))
        answers = {i.id: ("same_event" if n < 5 else "different", "dev") for n, i in enumerate(near)}
        sampled = [i for i in q.order if q.items[i].pool == "join:accepted"]
        answers.update({i: ("same_event" if n < 9 else "related", "dev") for n, i in enumerate(sampled)})
        unsampled = next(i.id for i in far if i.id not in answers)
        answers[unsampled] = ("unsure", "dev")                                       # left out of every count
        f, = L.score(q, answers, L.Settings(sample=10))
        dev = f["splits"]["dev"]["acted"]
        self.assertEqual(f["population"], 100)
        self.assertEqual(dev["precision"], round((5 + 9 * 9) / (10 + 90), 4))          # 0.86, not the 14/20 unweighted
        self.assertAlmostEqual(dev["n_eff"], 100 * 100 / (10 + 10 * 81), places=1)
        self.assertLess(dev["lo"], dev["precision"])
        self.assertGreater(dev["hi"], dev["precision"])
        self.assertIsNone(f["splits"]["test"]["acted"]["precision"])
        at = {s["bar"]: s["dev"] for s in f["sweep"]}
        self.assertEqual(at[0.7]["labelled"], 10)                                     # above 0.7: the far pool only
        self.assertEqual(at[0.7]["precision"], 0.9)

    def test_the_bar_is_re_picked_on_dev_and_reported_on_test(self):
        items = [item(n, p=0.6 + n * 0.035, day=n % 4) for n in range(10)]           # p 0.60 .. 0.915
        q = L.build(items, L.Settings(sample=99, near=0.0))
        answers = {i.id: ("same_event" if i.p >= 0.7 else "different", q.split_of(i)) for i in items}
        f, = L.score(q, answers, L.Settings(sample=99, near=0.0, target=0.95, min_dev=5))
        self.assertEqual(f["repick"]["bar"], 0.7)
        self.assertEqual(f["repick"]["dev"]["precision"], 1.0)
        self.assertEqual(f["splits"]["all"]["acted"]["precision"], 0.7)               # at today's 0.6 bar
        f, = L.score(q, answers, L.Settings(sample=99, near=0.0, target=0.95))
        self.assertIsNone(f["repick"])                                                # 5 dev labels: too few to re-pick


@requires_test_db
class Labels(unittest.TestCase):
    """On a test database, in one transaction rolled back after each test: the queue from a real decision run."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        schemas.load_guides(self.cur)
        self.now = T + 30 * H

    def post(self, hours, title):
        source = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "Example"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        # each post a text of its own: posts of one text are near-copies, never checked (0112 bug 3)
        body = title + ". " + " ".join(f"word{k}{url[-6:]}" for k in range(LONG))
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source, url, url, title, body, T + hours * H))
        pid = str(self.cur.fetchone()[0])
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [pid])
        return pid

    def ix_story(self, *members):
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)", (members[0], T, len(members)))
        for n, m in enumerate(members):
            self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                             "VALUES (%s, %s, 'report', %s, %s, %s)",
                             (m, members[0], f"v{n}", members[n - 1] if n else None, "citation" if n else None))

    def answer(self, kind, answer_of):
        self.cur.execute("SELECT id, kind, guide, a FROM mx_tasks WHERE kind = %s AND status = 'open'", (kind,))
        for tid, k, guide, a in self.cur.fetchall():
            ans = answer_of(str(a))
            call_id = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": k, "guide": guide, "a": a}, call_id, ans)

    def scene(self):
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 is out"), self.post(2, "Widget 4 hands-on")
        self.ix_story(a, b, c)
        d, e = self.post(3, "Beta launches Gizmo"), self.post(4, "Gizmo by Beta is here")
        repo.add_candidate(self.cur, kind="post_post", a=d, b=e, source="embedding", score=0.8)
        for pid in (d, e):
            tasks.read_task(self.cur, pid)
        self.answer("read", lambda a: {"kind": "report", "events": "one", "lang": "en", "items": [], "mentions": [],
                                       "main": {"headline_en": "Beta launched Gizmo", "actors": ["Beta"],
                                                "object": "Gizmo", "action": "launched"}})
        D.run(self.cur, now=self.now)
        self.answer("check", lambda p: {"relation": "same_event" if p == b else "different",
                                        "confidence": 90 if p == b else 75, "reason": "why " + p[:4]})
        self.answer("pair", lambda p: {"relation": "same_event", "confidence": 65, "reason": "same launch"})
        D.run(self.cur, now=self.now)
        # a story-changing answer counts once asked again (0112 Decided 8): the run reopened the pair
        self.answer("pair", lambda p: {"relation": "same_event", "confidence": 65, "reason": "same launch"})
        D.run(self.cur, now=self.now)
        return a, b, c, d, e

    def test_the_reading_reads_only_the_window_s_candidate_pairs_and_the_queue_is_the_same(self):
        """0199: labels' reading (decide.load with no incremental state) reads only the candidate pairs its window
        keeps; a pair whose first post is older than the window changes neither the reading's posts nor the queue."""
        import dataclasses
        self.scene()
        before = [dataclasses.asdict(i) for i in L.population(self.cur, now=self.now)]
        old_a, old_b = self.post(-40 * 24, "An old post"), self.post(-40 * 24 + 1, "Another old post")
        repo.add_candidate(self.cur, kind="post_post", a=old_a, b=old_b, source="embedding", score=0.9)
        world = D.load(self.cur, self.now, D.Config())
        self.assertNotIn(old_a, world.posts)
        self.assertEqual([dataclasses.asdict(i) for i in L.population(self.cur, now=self.now)], before)

    def test_the_queue_offers_the_run_s_decisions_blind_and_keeps_every_answer(self):
        a, b, c, d, e = self.scene()
        q = L.queue(self.cur, now=self.now)
        by = {(it.feature, it.post): it for it in q.items.values()}
        self.assertEqual(set(by), {("check", b), ("check", c), ("pair", e)})
        self.assertEqual(by[("check", c)].pool, "check:near")         # p 0.25 by the 0.30 bar: taken out
        self.assertTrue(by[("check", c)].accepted)
        self.assertEqual(by[("check", b)].pool, "check:rejected")     # kept at 0.90
        self.assertEqual(by[("pair", e)].pool, "pair:near")           # 0.65 by the 0.6 bar
        self.assertEqual(len(q.order), 3)
        it = by[("check", c)]
        view = L.item_view(self.cur, q, it.id)
        self.cur.execute("SELECT input FROM mx_tasks WHERE id = %s", (it.id,))
        self.assertEqual(view["evidence"], self.cur.fetchone()[0])     # the judge's input, as it saw it
        self.assertIsNone(view["verdict"])                             # never before an answer
        self.assertIsNone(view["pool"])                                # nor the pool, which names the decision
        self.assertNotIn("why", json.dumps(view, default=str))
        got = L.label(self.cur, q, it.id, "different", note="  ")
        self.assertEqual(got["verdict"]["decision"], "taken out")
        self.assertEqual(got["verdict"]["p"], 0.25)
        self.assertIsNone(got["label"]["note"])
        L.label(self.cur, q, it.id, "related", note="a side remark")
        self.cur.execute("SELECT answer, item_kind, a::text, b::text FROM mx_labels ORDER BY created_at, ctid")
        self.assertEqual(self.cur.fetchall(), [("different", "check", it.id, c), ("related", "check", it.id, c)])
        view = L.item_view(self.cur, q, it.id)
        self.assertEqual((view["label"]["answer"], view["verdict"]["decision"]), ("related", "taken out"))
        with self.assertRaises(ValueError):
            L.label(self.cur, q, it.id, "right")                       # not an answer to a relation question
        state = L.queue_view(self.cur, q)
        self.assertEqual((state["done"], state["total"]), (1, 3))
        self.assertNotIn(it.id, state["next"])
        prec = L.precision(self.cur, q)
        check = next(f for f in prec["features"] if f["feature"] == "check")
        self.assertEqual(check["bar"], 0.3)
        self.assertEqual(check["splits"]["all"]["acted"]["precision"], 1.0)
        self.assertEqual(check["labelled"], 1)
        self.assertEqual(L.precision(self.cur, q, labeller="claude")["features"][0]["labelled"], 0)
        # Mark IX drops c from its story: the question is no longer asked, and its label still counts ("earlier")
        self.cur.execute("DELETE FROM story_posts WHERE post_id = %s", (c,))
        q2 = L.queue(self.cur, now=self.now)
        self.assertEqual(q2.items[it.id].pool, "check:earlier")
        self.assertNotIn(it.id, q2.order)
        check = next(f for f in L.precision(self.cur, q2)["features"] if f["feature"] == "check")
        self.assertEqual((check["labelled"], check["splits"]["all"]["acted"]["precision"]), (1, 1.0))

    def test_the_kept_queue_reads_as_the_built_one(self):
        """0182: the queue kept by the jobs process (labels.keep, then labels.kept) is the queue built in place: the same
        items with the same fields, the same order, pools, cut, views and precision numbers, before and after labels."""
        self.scene()
        built = L.queue(self.cur, now=self.now)
        out = L.keep(self.cur, now=self.now, peak=lambda: 12.5)
        self.assertEqual((out["items"], out["queued"]), (len(built.items), len(built.order)))
        self.assertEqual(L.keep(self.cur, now=self.now)["already"], True)          # once a run and code stamp
        self.assertFalse(L.missing(self.cur))

        def same(kept):
            self.assertFalse(kept.building)
            self.assertEqual((kept.run, kept.order, kept.cut, dict(kept.pools)),
                             (built.run, built.order, built.cut, dict(built.pools)))
            self.assertEqual(list(kept.pools), list(built.pools))                   # and in the same order
            self.assertEqual(L.queue_view(self.cur, kept), L.queue_view(self.cur, built))
            for i in built.items:
                self.assertEqual(L.item_view(self.cur, kept, i), L.item_view(self.cur, built, i))
            fields = lambda it: {k: v for k, v in vars(it).items() if k != "rank"}
            kept.ensure(self.cur, built.items)
            self.assertEqual({i: fields(it) for i, it in kept.items.items()},
                             {i: fields(it) for i, it in built.items.items()})
            for labeller in ("owner", "claude"):
                self.assertEqual(L.precision(self.cur, kept, labeller=labeller),
                                 L.precision(self.cur, built, labeller=labeller))
        same(L.kept(self.cur))
        for n, i in enumerate(built.order):
            L.label(self.cur, L.kept(self.cur), i, ("same_event", "different", "related")[n % 3])
        L.label(self.cur, built, built.order[0], "unsure", labeller="claude")
        same(L.kept(self.cur))
        self.cur.execute("SELECT seconds, peak_mb, items, items_kept FROM mx_label_queues")
        seconds, peak_mb, n, items_kept = self.cur.fetchone()
        self.assertEqual((peak_mb, n, items_kept), (12.5, len(built.items), True))
        self.assertIsNotNone(seconds)

    def test_the_answers_are_read_in_sql_as_python_read_them(self):
        """0182: the population reads of an answer only the verdict's fields and whether `entities` names anything,
        in SQL: the same truth as Python's `(answer or {}).get("entities")`, the same Verdict.of."""
        answers = {"list": {"entities": [{"name": "Acme"}]}, "empty list": {"entities": []}, "none": {},
                   "null": {"entities": None}, "object": {"entities": {"a": 1}}, "empty object": {"entities": {}},
                   "string": {"entities": "Acme"}, "empty string": {"entities": ""}, "zero": {"entities": 0},
                   "number": {"entities": 2}, "true": {"entities": True}, "false": {"entities": False}}
        ids = {}
        for name, answer in answers.items():
            tid, _ = repo.add_task(self.cur, kind="entities", guide=schemas.KINDS["entities"].guide,
                                   subject_kind="post", input=f"POST {name}", a=str(uuid.uuid4()))
            repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=answer)
            repo.answer_task(self.cur, tid)
            ids[str(tid)] = name
        verdicts = {"full": {"relation": "development", "confidence": 80, "reason": "later"},
                    "no confidence": {"relation": "related", "reason": "r"}, "nothing": {},
                    "string confidence": {"relation": "development", "confidence": "70"}}
        for name, answer in verdicts.items():
            tid, _ = repo.add_task(self.cur, kind="connect", guide=schemas.KINDS["connect"].guide,
                                   subject_kind="story_story", input=f"STORIES {name}", a=str(uuid.uuid4()),
                                   b=str(uuid.uuid4()))
            repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=answer)
            repo.answer_task(self.cur, tid)
            ids[str(tid)] = name
        got = {it.id: it for it in L.population(self.cur, now=self.now)}
        named = {ids[i] for i, it in got.items() if it.feature == "entities"}
        self.assertEqual(named, {n for n, a in answers.items() if (a or {}).get("entities")})
        for i, it in got.items():
            if it.feature == "connect":
                v = D.Verdict.of(verdicts[ids[i]])
                self.assertEqual((it.p, it.relation, it.reason), (round(v.p, 4), v.relation, v.reason), ids[i])
        self.assertEqual(sum(it.feature == "connect" for it in got.values()), len(verdicts))

    def test_being_built_until_the_newest_run_s_queue_is_kept(self):
        self.assertIsNone(L.kept(self.cur).run)                                      # no run: nothing to label
        self.assertFalse(L.missing(self.cur))
        self.scene()
        q = L.kept(self.cur)
        self.assertTrue(q.building)
        self.assertIsNone(q.key)
        self.assertTrue(L.missing(self.cur))                                         # not kept,
        self.assertFalse(_wanted(self.cur))                                          # 0199: nobody asked
        L.ask(self.cur, q)                                                           # a Labels page opened
        self.assertTrue(_wanted(self.cur))
        view = L.queue_view(self.cur, q)
        self.assertEqual((view["total"], view["next"], view["run"]), (0, [], q.run))
        L.keep(self.cur, now=self.now)
        first = L.kept(self.cur)
        self.assertFalse(first.building)
        D.run(self.cur, now=self.now + H)                                            # a newer run: its queue not kept yet
        q = L.kept(self.cur)
        self.assertTrue(q.building)
        self.assertEqual((q.key, q.order), (first.key, first.order))                  # the last kept one meanwhile
        with mock.patch.object(L, "stamp", lambda settings=L.Settings(): "another code"):
            self.assertIsNone(L.kept(self.cur).key)                                  # another code's is never read
            self.assertTrue(L.missing(self.cur))                                     # asked above, not built since

    def test_the_items_of_older_queues_are_pruned_and_their_headers_kept(self):
        self.scene()
        built = L.queue(self.cur, now=self.now)
        keys = []
        for n in range(L.KEEP_ITEMS + 2):
            run = repo.start_run(self.cur, code_version="test", config={})
            built.run = str(run)
            keys.append(L._store(self.cur, built, stamp=L.stamp(), settings=L.Settings(), read_at=self.now,
                                 seconds=1.0, peak_mb=None))
            L.prune(self.cur)
        self.cur.execute("SELECT id::text, items_kept, items FROM mx_label_queues ORDER BY built_at")
        rows = self.cur.fetchall()
        self.assertEqual([r[0] for r in rows], keys)
        self.assertEqual([r[1] for r in rows], [False, False] + [True] * L.KEEP_ITEMS)
        self.assertEqual({r[2] for r in rows}, {len(built.items)})                    # each header keeps its size
        self.cur.execute("SELECT DISTINCT queue_id::text FROM mx_label_queue_items")
        self.assertEqual({r[0] for r in self.cur.fetchall()}, set(keys[2:]))
        self.assertEqual(L.kept(self.cur).key, keys[-1])

    def test_one_tap_on_a_news_member_is_a_label_and_ok_takes_it_back(self):
        a, b, c, d, e = self.scene()
        self.cur.execute("SELECT story_id::text, reason FROM mx_story_posts WHERE post_id = %s AND valid_to IS NULL", (e,))
        story, reason = self.cur.fetchone()
        self.assertEqual(reason, "judge:pair")
        L.flag(self.cur, post=e, story=story, answer="wrong_story")
        self.assertEqual(L.flags(self.cur, [(e, story)]), {(e, story): "wrong_story"})
        self.assertEqual(L.news_flags(self.cur), {"pair": {"wrong_story": 1}})
        L.flag(self.cur, post=e, story=story, answer="ok")
        self.assertEqual(L.flags(self.cur, [(e, story)]), {})
        self.cur.execute("SELECT count(*) FROM mx_labels WHERE item_kind = 'news_row'")
        self.assertEqual(self.cur.fetchone()[0], 2)                    # both rows kept
        with self.assertRaises(KeyError):
            L.flag(self.cur, post=a, story=str(uuid.uuid4()), answer="not_about")
        with self.assertRaises(ValueError):
            L.flag(self.cur, post=e, story=story, answer="maybe")
        page = __import__("insight_core.markx.news", fromlist=["page"]).page(self.cur, now=self.now)
        lines = [p for r in page["items"] for p in r["posts"] if p["id"] == e]
        self.assertTrue(lines and lines[0]["story"] == story and lines[0]["flag"] is None, json.dumps(page, default=str)[:3000])

    def test_mark_ix_tables_are_untouched_by_the_queue_and_labels(self):
        from insight_core.tests.test_markx_decide import checksums
        a, b, c, d, e = self.scene()
        before = checksums(self.cur)
        self.cur.execute("SELECT count(*) FROM mx_tasks")
        tasks_before = self.cur.fetchone()[0]
        q = L.queue(self.cur, now=self.now)
        for i in q.order:
            L.label(self.cur, q, i, "same_event")
        L.precision(self.cur, q)
        self.assertEqual(checksums(self.cur), before)
        self.cur.execute("SELECT count(*) FROM mx_tasks")
        self.assertEqual(self.cur.fetchone()[0], tasks_before)         # reading the queue asks nothing new


@requires_test_db
class Routes(unittest.TestCase):
    """The labels routes through the app, on committed rows (removed after), with a queue built for the test."""

    def setUp(self):
        from types import SimpleNamespace

        from insight_core.services import registry
        self.env = os.environ.get("INSIGHT_MARKX")
        os.environ["INSIGHT_MARKX"] = "on"
        self.addCleanup(lambda: os.environ.__setitem__("INSIGHT_MARKX", self.env) if self.env is not None
                        else os.environ.pop("INSIGHT_MARKX", None))
        self.addCleanup(registry.use, registry.use(SimpleNamespace(db_url=db_url())))
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        self.addCleanup(clear_tables, self.cur, MX_TABLES)
        schemas._ready.clear()
        with self.conn.transaction():
            schemas.load_guides(self.cur)
            self.task, _ = repo.add_task(self.cur, kind="join", guide="judge-read-v1", subject_kind="post_story",
                                         input="STORY\nHeadline: Acme released Widget 4\n\nPOST\nTitle: Widget 4 is out")
            repo.add_call(self.cur, task_id=self.task, executor="claude-code", model="haiku", valid=True,
                          answer={"relation": "same_event", "confidence": 62, "reason": "the same release"})
            repo.answer_task(self.cur, self.task)
            self.run = repo.start_run(self.cur, code_version="test", config={})
            repo.finish_run(self.cur, self.run, counts={})
        self.post = str(uuid.uuid4())
        self.q = L.build([L.Item(id=str(self.task), feature="join", post=self.post, day=T, p=0.62, bar=0.6,
                                 relation="same_event", reason="the same release", accepted=True)], run=str(self.run))
        # 0182: the API never builds the queue: every builder fails the test if a route calls it
        for name in ("population", "build", "queue", "keep"):
            patcher = mock.patch.object(L, name, side_effect=AssertionError(f"the API called labels.{name}"))
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("load", "think"):
            patcher = mock.patch.object(D, name, side_effect=AssertionError(f"the API called decide.{name}"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def keep(self):
        with self.conn.transaction():
            L._store(self.cur, self.q, stamp=L.stamp(), settings=L.Settings(), read_at=T, seconds=0.1, peak_mb=None)

    def test_being_built_until_the_jobs_process_keeps_it(self):
        status, body = call("GET", "/api/markx/labels")
        self.assertEqual((status, body["building"], body["run"], body["total"], body["next"]),
                         (200, True, str(self.run), 0, []))
        status, body = call("GET", "/api/markx/labels/precision")
        self.assertEqual((status, body["building"], body["features"]), (200, True, []))
        status, body = call("GET", f"/api/markx/labels/items/{self.task}")
        self.assertEqual(status, 503)
        self.assertIn("being built", body["detail"])
        status, body = call("POST", "/api/markx/labels", body={"item": str(self.task), "answer": "same_event"})
        self.assertEqual(status, 503)
        self.cur.execute("SELECT count(*) FROM mx_label_queues")
        self.assertEqual(self.cur.fetchone()[0], 0)                                  # nothing built in the API
        self.assertTrue(L.missing(self.cur))
        self.assertTrue(_wanted(self.cur), "0199: opening it asked the jobs process for it")
        self.keep()
        status, body = call("GET", "/api/markx/labels")
        self.assertEqual((status, body["building"], body["next"]), (200, False, [str(self.task)]))

    def test_the_tab_s_routes(self):
        self.keep()
        status, body = call("GET", "/api/markx/labels")
        self.assertEqual((status, body["total"], body["done"], body["next"], body["building"]),
                         (200, 1, 0, [str(self.task)], False))
        status, body = call("GET", f"/api/markx/labels/items/{self.task}")
        self.assertEqual(status, 200)
        self.assertIsNone(body["verdict"])
        self.assertIn("Widget 4 is out", body["evidence"])
        self.assertEqual(body["answers"], list(L.RELATION_ANSWERS))
        status, body = call("POST", "/api/markx/labels", body={"item": str(self.task), "answer": "nonsense"})
        self.assertEqual(status, 400)
        status, body = call("POST", "/api/markx/labels", body={"item": str(uuid.uuid4()), "answer": "same_event"})
        self.assertEqual(status, 404)
        status, body = call("POST", "/api/markx/labels", body={"item": str(self.task), "answer": "same_event", "note": "ok"})
        self.assertEqual((status, body["verdict"]["relation"], body["next"], body["done"]), (200, "same_event", None, 1))
        status, body = call("GET", "/api/markx/labels/precision")
        self.assertEqual(status, 200)
        self.assertEqual(body["features"][0]["splits"]["all"]["acted"]["precision"], 1.0)
        status, body = call("POST", "/api/markx/labels/news",
                            body={"post": str(uuid.uuid4()), "story": str(uuid.uuid4()), "answer": "wrong_story"})
        self.assertEqual(status, 404)

    def test_404_when_off(self):
        with mock.patch.dict(os.environ, {"INSIGHT_MARKX": "off"}):
            for method, path in (("GET", "/api/markx/labels"), ("GET", "/api/markx/labels/precision"),
                                 ("GET", f"/api/markx/labels/items/{self.task}"), ("POST", "/api/markx/labels"),
                                 ("POST", "/api/markx/labels/news")):
                self.assertEqual(call(method, path, body={})[0], 404, path)


if __name__ == "__main__":
    unittest.main()
