"""Pairing (issue 0166): the move of the candidate sources and decide's re-gates behind markx/pairing.py changed no
pair. Each test runs the code as it was (tests/legacy: verbatim copies of main a395c13) and the code as it is on the same
data and requires the same output:
  - the candidate job (every source, a subset of posts, the entity source alone, the job's `run`) on a seeded
    synthetic world: the same mx_candidates rows (kind, a, b, source, score) and the same counts;
  - decide's planning (plan_pass1, plan_pass2) on seeded random worlds under several configs: the same questions;
  - the decision run on the synthetic world (questions asked as tasks, answered alike, asked again): the same tasks,
    memberships and connections;
and the policy table's rows are the bars the old code wrote down.

Runs the DB parts only on a database whose name ends in _test (it empties the mx_* tables inside its transaction)."""
from __future__ import annotations

import hashlib
import json
import math
import random
import unittest
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.db.repo_post_parts import PostPartsRepository
from insight_core.markx import candidates as C
from insight_core.markx import decide as D
from insight_core.markx import later as later_mod, pairing, repo, schemas, tasks
from insight_core.utils import voice
from insight_core.tests.legacy import incremental_a395c13 as incremental   # the legacy decide's memo (0169 moved it to Postgres)
from insight_core.tests._db import clear_tables, db_url, insert_scratch_source, requires_test_db
from insight_core.tests.legacy import candidates_a395c13 as OLD_C
from insight_core.tests.legacy import decide_a395c13 as OLD_D
from insight_core.tests.test_markx_api import MX_TABLES

T0 = datetime(2100, 6, 1, tzinfo=timezone.utc)   # no other test's post is near
H = timedelta(hours=1)
DIM = 1024


class Table(unittest.TestCase):
    def test_the_rows_hold_the_old_bars(self):
        same, conn = pairing.POLICIES[pairing.SAME_STORY], pairing.POLICIES[pairing.CONNECTED]
        self.assertEqual((same.window, same.cosine, same.nearest, same.late_after), (OLD_C.WINDOW, OLD_C.EMBEDDING_MIN,
                                                                                  OLD_C.NEAREST, OLD_C.BURST_GAP))
        self.assertEqual((same.story_cosine, same.story_window, same.types), (OLD_C.STORY_MIN, OLD_C.STORY_DAYS,
                                                                            OLD_C.SPECIFIC_TYPES))
        old = OLD_D.Config()
        self.assertEqual({k: v for k, v in asdict(D.Config()).items() if k != "roundup_first"}, asdict(old))   # 0205: new
        self.assertEqual((same.min_words, same.document_window), (old.min_words, timedelta(days=old.document_days)))
        self.assertEqual((conn.story_cosine, conn.story_window, conn.min_voices),
                         (old.connect_lo, timedelta(days=old.connect_days), old.connect_voices))

    def test_an_override_changes_only_its_field(self):
        p = pairing.policy(pairing.SAME_STORY, cosine=0.8, min_words=None)
        self.assertEqual(p.cosine, 0.8)
        self.assertEqual(p.min_words, 20)
        self.assertEqual(p.window, pairing.POLICIES[pairing.SAME_STORY].window)

    def test_the_basics(self):
        # the voice basics are Voice's (issue 0189: utils/voice.py, Policy.MARKX)
        said = [voice.Said(s, k) for s, k in (("s1", "telegram"), ("s1", "rss"), ("s2", "saved"), ("s3", "site"))]
        self.assertEqual(voice.count(said, voice.Policy.MARKX), 2)
        self.assertTrue(voice.independent("s1", "telegram", "s2", "site"))
        self.assertFalse(voice.independent("s1", "telegram", "s1", "site"))
        self.assertFalse(voice.independent("s1", "saved", "s2", "site"))
        self.assertEqual(pairing.ordinary_date("x"), "COALESCE(x.surfaced_at, x.published_at, x.fetched_at)")
        # 0181: a round-up's issue time first, else that same expression (tests/test_markx_units.py: identical dates)
        self.assertTrue(pairing.post_date("x").endswith(", COALESCE(x.surfaced_at, x.published_at, x.fetched_at))"))
        self.assertIn("mx_roundups", pairing.post_date("x"))
        self.assertEqual(pairing.page_address("https://www.example.com/a/B/"), "example.com/a/b")
        self.assertEqual(pairing.page_key("https://www.example.com/a/B/"), "example.com/a/b")


# ---- the planning, pure ------------------------------------------------------------------------------------

def _world(rng: random.Random, n: int = 40):
    posts = {}
    for k in range(n):
        pid = f"p{k:02d}"
        posts[pid] = D.Post(pid, f"s{rng.randrange(9)}", rng.choice(["telegram"] * 6 + ["site", "saved"]),
                            T0 + rng.uniform(0, 20 * 24) * H, rng.choice([5, 15, 19, 20, 25, 60]))
    ids = sorted(posts)
    rng.shuffle(ids)
    stories, used = {}, 0
    while used < n * 0.6:
        size = rng.choice([2, 2, 3, 4])
        ms = ids[used:used + size]
        used += size
        stories[f"S{len(stories)}"] = [D.Member(m, rng.choice(["report", "report", "share"]),
                                                None if i == 0 else rng.choice(["time", "citation", "thread", "quote"]))
                                       for i, m in enumerate(ms)]
    kinds = {p: rng.choice(["report", "report", "commentary", "roundup", None]) for p in posts}
    cands = [(rng.choice(sorted(posts)), rng.choice(sorted(posts)), rng.choice([None, 0.5, 0.64, 0.65, 0.7, 0.9]))
             for _ in range(80)]
    cands = [(a, b, c) for a, b, c in cands if a != b]
    keys = sorted(stories)
    pairs = [(rng.choice(keys), rng.choice(keys), rng.choice([None, 0.6, 0.69, 0.7, 0.85])) for _ in range(25)]
    return posts, stories, kinds, cands, [(x, y, c) for x, y, c in pairs if x != y]


CONFIGS = (D.Config(), D.Config.prototype(), D.Config(cand_lo=0.7, min_words=15, story_lo=0.8, story_days=3))


def _old(config: D.Config) -> OLD_D.Config:
    return OLD_D.Config(**{k: v for k, v in asdict(config).items() if k != "roundup_first"})   # 0205's rule: new


class Planning(unittest.TestCase):
    def test_pass_one_asks_the_same_questions(self):
        for seed in range(60):
            rng = random.Random(seed)
            posts, stories, kinds, cands, pairs = _world(rng)
            cut = T0 + rng.uniform(0, 10 * 24) * H
            for config in CONFIGS:
                for in_window in (None, lambda a: posts[a].at >= cut):
                    old = OLD_D.plan_pass1(posts, stories, kinds, cands, pairs, _old(config), in_window=in_window)
                    new = D.plan_pass1(posts, stories, kinds, cands, pairs, replace(config, roundup_first=False),
                                       in_window=in_window)
                    self.assertEqual([asdict(q) for q in new], [asdict(q) for q in old], (seed, config))
                    # 0205: a roundup that begins a story is checked too; every other question is the same
                    more = D.plan_pass1(posts, stories, kinds, cands, pairs, replace(config, roundup_first=True),
                                        in_window=in_window)
                    added = [q for q in more if q not in new]
                    self.assertTrue(all(q.type == "check" and kinds.get(q.post) == "roundup" for q in added))
                    self.assertEqual([q for q in more if q not in added], new)

    def test_pass_two_asks_the_same_questions(self):
        for seed in range(60):
            rng = random.Random(seed)
            posts, stories, kinds, _c, _p = _world(rng)
            lone = sorted(set(posts) - {m.post for ms in stories.values() for m in ms})
            answered = []
            for _ in range(12):
                a, b = rng.sample(lone, 2) if len(lone) >= 2 else rng.sample(sorted(posts), 2)
                answered.append((OLD_D.Question(f"pair:{a}:{b}", "pair", post=b, anchor=a),
                                 OLD_D.Verdict(rng.choice(["same_event", "development", "different"]), rng.random())))
            first = OLD_D.decide(posts, stories, answered, _old(D.Config()))

            def cos(pa, pb):
                h = hashlib.sha256(("|".join(pa) + "#" + "|".join(pb)).encode()).digest()
                return None if h[0] < 30 else 0.5 + h[1] / 510

            def docs(pa, pb):
                return hashlib.sha256(("".join(sorted(pa + pb))).encode()).digest()[0] < 40
            for config in CONFIGS:
                for kw in ({}, {"documents": docs}, {"within": lambda a, b: True}):
                    old = OLD_D.plan_pass2(posts, first, cos, _old(config), **kw)
                    new = D.plan_pass2(posts, first, cos, config, **kw)
                    self.assertEqual([asdict(q) for q in new], [asdict(q) for q in old], (seed, config, kw))


# ---- the stored sources and the decision run, on a synthetic world -----------------------------------------------

def _unit(parts):
    v = [0.0] * DIM
    for k, w in parts:
        v[k] += w
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


@requires_test_db
class _World(unittest.TestCase):
    """A seeded world: 9 sources (one saved), 70 posts over 12 days in 5 topics (vectors at cosines 0.5-0.95 within
    a topic), Mark IX stories, ent-v3 subjects of every type and role, shared pages with late linkers, readings."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, MX_TABLES)
        schemas.load_guides(self.cur)
        incremental.forget()
        self.addCleanup(incremental.forget)
        rng = random.Random(166)
        self.sources = [insert_scratch_source(self.cur, platform=pl, settings_json=json.dumps({"display_name": "Example"}))
                        for pl in ["telegram"] * 6 + ["rss", "rss", "saved"]]
        pages = [f"https://example.com/research/page-{k}" for k in range(4)]
        names = [("Widget 4.1", "model", "4.1"), ("Widget 4.2", "model", "4.2"), ("Acme", "org", None),
                 ("Gizmo", "product", None), ("FlashProve", "software", None), ("A Study", "paper", None),
                 ("Jane Example", "person", None)]
        self.posts = []
        for k in range(70):
            topic = rng.randrange(5)
            at = T0 + rng.uniform(0, 12 * 24) * H
            src = rng.choice(self.sources)
            links = rng.sample(pages, rng.choice([0, 0, 1, 1, 3]))
            if rng.random() < 0.15:
                links = ["https://example.com/a", "https://example.com/b"] + links + ["https://example.com/c"]
            title = f"Acme topic {topic} item {k}"
            url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
            body = title + ". " + " ".join(f"word{j}{url[-6:]}" for j in range(rng.choice([8, 30, 40])))
            self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                             "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (src, url, url, title, body, at))
            pid = str(self.cur.fetchone()[0])
            for n, target in enumerate(links):
                self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position) VALUES (%s, %s, %s, %s)",
                                 (pid, target, "example.com", n))
            repo.put_embedding(self.cur, post_id=pid, model="bge-m3", text_hash="h-" + pid, model_sha256="a" * 64,
                               vector=_unit([(topic, 1.0), (10 + k, rng.uniform(0.3, 1.6)), (5 + topic, rng.uniform(0, 0.5))]))
            if rng.random() < 0.6:
                ents = rng.sample(names, rng.choice([1, 2]))
                task_id, _ = tasks.entities_task(self.cur, pid)
                call = repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="claude-haiku-5-5",
                                     valid=True, answer={"entities": []})
                repo.add_mentions(self.cur, post_id=pid, guide="ent-v3", call_id=call, mentions=[
                    {"span": nm, "name": nm, "name_key": tasks.name_key(nm), "type": t,
                     "role": rng.choice(["subject", "subject", "actor"]), "version": v} for nm, t, v in ents])
            self.posts.append(pid)
        PostPartsRepository.write(self.cur, self.posts)
        order = sorted(self.posts, key=lambda p: self._at(p))
        used = 0
        while used < 30:
            size = rng.choice([2, 3])
            ms = order[used:used + size]
            used += size + rng.choice([0, 1, 2])
            self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, %s)", (ms[0], self._at(ms[0]), len(ms)))
            for n, m in enumerate(ms):
                self.cur.execute("INSERT INTO story_posts (post_id, story_id, role, voice, parent_id, parent_reason) "
                                 "VALUES (%s, %s, 'report', %s, %s, %s)",
                                 (m, ms[0], f"v{n}", ms[n - 1] if n else None, rng.choice(["citation", "time"]) if n else None))
        self.now = T0 + 12 * 24 * H

    def _at(self, pid):
        self.cur.execute("SELECT published_at FROM posts WHERE id = %s", (pid,))
        return self.cur.fetchone()[0]

    def rows(self):
        self.cur.execute("SELECT kind, a::text, b::text, source, score FROM mx_candidates ORDER BY 1, 2, 3, 4")
        return self.cur.fetchall()

    def both(self, fn_old, fn_new):
        """(old's result, its rows; new's result, its rows), each from the same state (a savepoint between)."""
        self.cur.execute("SAVEPOINT pairing_equiv")
        got_old = fn_old()
        old = self.rows()
        self.cur.execute("ROLLBACK TO SAVEPOINT pairing_equiv")
        got_new = fn_new()
        return got_old, old, got_new, self.rows()


class Candidates(_World):
    def test_every_source_finds_the_same_pairs(self):
        got_old, old, got_new, new = self.both(lambda: OLD_C.find(self.cur, self.posts), lambda: C.find(self.cur, self.posts))
        self.assertEqual(new, old)
        self.assertEqual(dict(got_new), dict(got_old))
        self.assertEqual(list(got_new), list(got_old))
        sources = {r[3] for r in old}
        self.assertTrue({"embedding", "link", "entity", "burst"} <= sources, sources)   # the world exercises each
        self.assertIn(pairing.STORY_STORY, {r[0] for r in old})

    def test_a_subset_and_one_source_alone(self):
        some = self.posts[::3]
        for sources in (("embedding", "link", "entity", "burst"), ("entity",), ("embedding",), ("burst", "link")):
            got_old, old, got_new, new = self.both(lambda: OLD_C.find(self.cur, some, sources=sources),
                                                   lambda: C.find(self.cur, some, sources=sources))
            self.assertEqual(new, old, sources)
            self.assertEqual(dict(got_new), dict(got_old), sources)

    def test_the_job_run_in_steps(self):
        since = datetime.now(timezone.utc) - H

        def steps(mod):
            out = [dict(mod.run(self.cur, self.posts[:20], since=since))]
            out.append(dict(mod.run(self.cur, self.posts[20:45])))
            out.append(dict(mod.find(self.cur, self.posts)))
            return out
        got_old, old, got_new, new = self.both(lambda: steps(OLD_C), lambda: steps(C))
        self.assertEqual(new, old)
        self.assertEqual(got_new, got_old)


class DecisionRun(_World):
    """Two rounds of the decision run: the questions asked as tasks; every task answered the same way by its input
    (a hash: some about, some not, some confident); then the run again (joins, pairs, merges, the second pass, the
    connect questions, asked again). The same tasks, memberships and connections."""

    def answer_all(self):
        self.cur.execute("SELECT id, kind, guide, input, a FROM mx_tasks WHERE status = 'open' ORDER BY kind, input")
        for tid, kind, guide, text, a in self.cur.fetchall():
            h = hashlib.sha256(text.encode()).digest()
            if kind == "read":
                ans = {"kind": ["report", "commentary", "roundup"][h[0] % 3], "events": "one", "lang": "en", "items": [],
                       "mentions": [], "main": {"headline_en": "Acme released Widget", "actors": ["Acme"],
                                                "object": "Widget", "action": "released"}}
            elif kind == "card":
                ans = {"headline": "Acme released Widget", "actors": ["Acme"], "object": "Widget", "action": "released"}
            elif kind in ("join", "pair", "merge", "check", "connect"):
                rel = (["same_event", "development", "reaction", "different", "mention"] if kind != "connect"
                       else ["development", "same_event", "different", "background"])[h[1] % (5 if kind != "connect" else 4)]
                ans = {"relation": rel, "confidence": 50 + h[2] % 50, "reason": "Both are about it."}
            else:
                continue
            call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": kind, "guide": guide, "a": a}, call, ans)

    def state(self):
        self.cur.execute("SELECT kind, input, a::text, b::text, status FROM mx_tasks ORDER BY 1, 2, 3, 4")
        t = self.cur.fetchall()
        self.cur.execute("""SELECT sp.post_id::text, sp.role, s.first_at FROM mx_story_posts sp JOIN mx_stories s ON s.id = sp.story_id
                             WHERE sp.valid_to IS NULL ORDER BY 3, 1""")
        m = self.cur.fetchall()
        self.cur.execute("SELECT a_kind, b_kind, relation, rule FROM mx_connections WHERE valid_to IS NULL ORDER BY 1, 2, 3, 4")
        return t, m, self.cur.fetchall()

    def test_the_same_tasks_memberships_and_connections(self):
        C.find(self.cur, self.posts)
        for pid in self.posts:
            tasks.read_task(self.cur, pid)
        self.answer_all()

        def rounds(mod, config):
            out = []
            for _ in range(3):
                incremental.forget()
                mod.run(self.cur, now=self.now, config=config, full=True)
                out.append(self.state())
                self.answer_all()
            return out
        for config in (D.Config(), D.Config(document_merges=True, connect_lo=0.5, story_days=5)):
            old_cfg = _old(config)
            config = replace(config, roundup_first=False)   # 0205's rule is new: the rest is the same
            self.cur.execute("SAVEPOINT pairing_run")
            # 0203 dropped Later developments: the legacy copy's later stage is a no-op here
            with mock.patch.object(later_mod, "stage", lambda *a, **k: {}, create=True):
                old = rounds(OLD_D, old_cfg)
            self.cur.execute("ROLLBACK TO SAVEPOINT pairing_run")
            new = rounds(D, config)
            self.cur.execute("ROLLBACK TO SAVEPOINT pairing_run")
            for n, (o, w) in enumerate(zip(old, new)):
                self.assertEqual(w[0], o[0], f"tasks, round {n}")
                self.assertEqual(w[1], o[1], f"memberships, round {n}")
                self.assertEqual(w[2], o[2], f"connections, round {n}")
            kinds = {k for k, *_ in old[-1][0]}
            self.assertTrue({"join", "pair", "merge"} & kinds, kinds)


if __name__ == "__main__":
    unittest.main()
