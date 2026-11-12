"""Mark X's incremental decision runs (issue 0116), their state kept in Postgres (issue 0169): a run reads again only
what changed since the last one, in a process of its own, and its result is a full run's: after each incremental run,
a full run of the same snapshot writes nothing (no membership, connection or News row changes) and its check (the
incremental reading of that snapshot against the full one) finds no difference. A state gone wrong is caught by that
check, with its stories. The DB tests run only on a database whose name ends in _test."""
from __future__ import annotations

import json
import random
import unittest
import unittest.mock
import uuid
from datetime import datetime, timedelta, timezone

import psycopg

from insight_core.markx import decide as D
from insight_core.markx import incremental as I
from insight_core.markx import repo, schemas, tasks
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db
from insight_core.tests.test_markx_api import MX_TABLES

T = datetime(2100, 3, 1, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)
LONG = 30
STATE = ("mx_inc_state", "mx_inc_posts", "mx_inc_inputs", "mx_inc_copies", "mx_inc_tasks")


class Codec(unittest.TestCase):
    def test_what_a_run_keeps_comes_back_as_it_was(self):
        at = datetime(2100, 3, 1, 12, 30, 15, 123456, tzinfo=timezone.utc)
        news = {"since": at, "window": {"a", "b"}, "first": {"s1": at, "s2": None},
                "rows": [{"id": "p1", "first_at": at, "voices": 2, "reports": 1, "shares": 0, "mentions": 0,
                          "score": 3.25, "tag": "SAME", "posts": [{"post_id": "p1", "role": "report", "voice": "v",
                                                                   "name": None, "position": 0, "story": "s1"}]}],
                "stories": {"s1": (frozenset({"p1", "p2"}), frozenset())}}
        want = {"k": {"p1": ("member", "rule:none", None, None), "p2": ("member", "judge:join", 0.9, "c1")}}
        for value in (news, want, None, {"x": [1, 2.5, "y", (1, "z")]}):
            back = I.decode(json.loads(I.encode(value)))
            self.assertEqual(back, value)
            self.assertEqual(type(back), type(value))
        self.assertEqual(str(I.decode(json.loads(I.encode(at)))), str(at))


@requires_test_db
class Incremental(unittest.TestCase):
    """On a test database, in one transaction rolled back after each test."""

    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES + STATE)}")
        schemas.load_guides(self.cur)
        self.now = T + 30 * H

    # -- the scene ----------------------------------------------------------------------------------------
    def post(self, hours, title, source=None):
        source = source or insert_scratch_source(self.cur, platform="telegram",
                                                 settings_json=json.dumps({"display_name": "Example"}))
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
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
                             (m, members[0], f"v{n}", members[n - 1] if n else None, "time" if n else None))
        return members[0]

    def answer(self, kind, answer_of, limit=None):
        self.cur.execute("SELECT id, kind, guide, a, b FROM mx_tasks WHERE kind = %s AND status = 'open' ORDER BY id",
                         (kind,))
        n = 0
        for tid, k, guide, a, b in self.cur.fetchall()[:limit]:
            ans = answer_of(str(a), str(b) if b else None)
            call = repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=True, answer=ans)
            repo.answer_task(self.cur, tid)
            tasks.record(self.cur, {"kind": k, "guide": guide, "a": a}, call, ans)
            n += 1
        return n

    def read_all(self, ids):
        for pid in ids:
            tasks.read_task(self.cur, pid)
        self.answer("read", lambda a, b: {"kind": "report", "events": "one", "lang": "en", "items": [], "mentions": [],
                                          "main": {"headline_en": "Acme released Widget", "actors": ["Acme"],
                                                   "object": "Widget", "action": "released"}})

    def scene(self):
        """Two Mark IX stories (one checked), lone posts paired with each other and joined to the stories."""
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 is out"), self.post(2, "Widget 4 hands-on")
        self.ix_story(a, b, c)
        d, e = self.post(3, "Beta launches Gizmo"), self.post(4, "Gizmo by Beta is here")
        self.ix_story(d, e)
        f, g, h = self.post(5, "Widget 4 review"), self.post(6, "Gizmo price"), self.post(7, "Gamma ships Doohickey")
        k = self.post(8, "Doohickey by Gamma")
        for x, y in ((a, f), (d, g), (h, k), (f, h)):
            repo.add_candidate(self.cur, kind="post_post", a=x, b=y, source="embedding", score=0.8)
        self.read_all([a, b, c, d, e, f, g, h, k])
        return a, b, c, d, e, f, g, h, k

    # -- the runs -----------------------------------------------------------------------------------------
    def go(self, **kw):
        return D.run(self.cur, now=self.now, **kw)

    def full_writes_nothing(self):
        """A full run of this snapshot, in a savepoint undone after (the state with it): it must change nothing the
        incremental run left, and its check must find no difference."""
        self.cur.execute("SAVEPOINT full_check")
        try:
            out = self.go(full=True)
        finally:
            self.cur.execute("ROLLBACK TO SAVEPOINT full_check")
        self.assertEqual(out["run"]["kind"], "full")
        self.assertEqual(out["check"], {"same": True})
        self.assertEqual(out["memberships"], {}, out["memberships"])
        self.assertEqual(out["connections"], {})
        self.assertFalse(out["news"]["written"])
        return out

    def test_every_incremental_run_is_a_full_runs_result(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        first = self.go()
        self.assertEqual(first["run"]["kind"], "full")                 # no state yet
        self.full_writes_nothing()
        answers = [("check", lambda x, y: {"relation": "different" if x == c else "same_event", "confidence": 90}),
                   ("join", lambda x, y: {"relation": "same_event", "confidence": 90, "reason": "same release"}),
                   ("pair", lambda x, y: {"relation": "same_event", "confidence": 90, "reason": "same launch"}),
                   ("join", lambda x, y: {"relation": "same_event", "confidence": 85, "reason": "same release"}),
                   ("pair", lambda x, y: {"relation": "same_event", "confidence": 80, "reason": "same launch"})]
        kinds = []
        for kind, answer_of in answers:
            self.answer(kind, answer_of, limit=1)
            out = self.go()
            kinds.append(out["run"]["kind"])
            self.full_writes_nothing()
        self.assertEqual(set(kinds), {"incremental"})
        self.cur.execute("SELECT count(*) FROM mx_story_posts WHERE valid_to IS NULL AND reason LIKE 'judge:%%'")
        self.assertGreater(self.cur.fetchone()[0], 0)                   # the answers changed stories

    def test_the_dirty_set_is_the_tasks_answered_since_and_the_closure_their_stories(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        self.go()
        quiet = self.go()
        self.assertEqual((quiet["run"]["kind"], quiet["run"]["dirty_tasks"], quiet["run"]["closure"]),
                         ("incremental", 0, 0))
        self.assertEqual(quiet["run"]["texts_read"], 0)                 # nothing changed: no text read again ...
        self.assertEqual(quiet["run"]["texts_loaded"], 0)               # ... nor for a render: every input was kept
        self.assertEqual(quiet["run"]["inputs_rendered"], 0)
        self.assertGreater(quiet["run"]["inputs_kept"], 0)
        n = self.answer("check", lambda x, y: {"relation": "different", "confidence": 95})
        self.assertEqual(n, 3)                                          # b and c in one story, e in the other
        out = self.go()
        self.assertEqual(out["run"]["dirty_tasks"], 3)
        self.assertEqual(out["run"]["dirty_posts"], 3)
        self.assertEqual(out["changes"], {"remove": 2})                 # e, the second voice of d and e: asked again
        self.assertEqual(out["tasks_reasked"], {"check": 1})
        self.assertGreaterEqual(out["run"]["closure"], 1)
        self.assertEqual(out["news"]["made"], "incremental")
        self.full_writes_nothing()

    def test_a_new_post_or_a_changed_text_is_read_again(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        self.go()
        self.cur.execute("UPDATE posts SET title = 'Acme released Widget 4 today' WHERE id = %s", (a,))
        from insight_core.db.repo_post_parts import PostPartsRepository
        PostPartsRepository.write(self.cur, [a])
        out = self.go()
        self.assertEqual(out["run"]["kind"], "incremental")
        self.assertEqual(out["run"]["texts_read"], 1)                   # its rules' post read again
        self.assertIn("posts", out["run"]["ix_changed"])
        self.assertGreater(out["run"]["inputs_rendered"], 0)            # the questions showing it, rendered again
        self.assertEqual(out["news"]["made"], "incremental")            # 0177: the changed post seeds News' rows
        self.assertGreater(out["news"]["group"], 0)
        self.full_writes_nothing()
        x = self.post(9, "Widget 4 teardown")                           # a new post, paired with the story's
        repo.add_candidate(self.cur, kind="post_post", a=a, b=x, source="embedding", score=0.9)
        self.read_all([x])
        out = self.go()
        self.assertEqual((out["run"]["kind"], out["run"]["texts_read"]), ("incremental", 1))
        self.full_writes_nothing()

    def test_news_is_made_again_for_the_posts_whose_story_post_changed(self):
        """0177: a link's resolution moving (a page stored at an address a post links), or a post's text, seeds the
        rows made again; the source facts a StoryPost reads changing makes News in full. Each time a full run of the
        snapshot writes nothing more."""
        a, b, c, d, e, f, g, h, k = self.scene()
        self.go()
        self.cur.execute("""INSERT INTO post_links (post_id, target_url, target_site, position, link_text, boilerplate, kind)
                            VALUES (%s, 'https://test.invalid/page/one', 'test.invalid', 9, 'a page', false, 'link')""", (b,))
        out = self.go()
        self.assertEqual(out["news"]["made"], "incremental")
        self.full_writes_nothing()
        self.cur.execute("SELECT source_id FROM posts WHERE id = %s", (d,))
        source = self.cur.fetchone()[0]
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, published_at)
                            VALUES (%s, 'https://test.invalid/page/one', 'https://test.invalid/page/one', 'The page',
                                    'Its words.', %s)""", (source, T + 9 * H))
        out = self.go()                                                  # b's link now resolves to a stored post
        self.assertEqual(out["news"]["made"], "incremental")
        self.assertGreater(out["news"]["group"], 0)
        self.full_writes_nothing()
        self.cur.execute("UPDATE sources SET platform = 'rss' WHERE id = %s", (source,))
        out = self.go()                                                  # a source's kind: the facts changed
        self.assertEqual(out["news"]["made"], "full")
        self.full_writes_nothing()

    def test_the_check_finds_a_state_gone_wrong_with_its_stories(self):
        a, b, c, d, e, f, g, h, k = self.scene()
        self.go()
        self.answer("check", lambda x, y: {"relation": "different", "confidence": 95})
        self.go()
        # a bug: the kept inputs of every check point at no task, so the incremental reading forgets every check answer
        self.cur.execute("UPDATE mx_inc_inputs SET input_hash = md5(input_hash) WHERE kind = 'check'")
        out = self.go(full=True)
        self.assertFalse(out["check"]["same"])
        self.assertIn("stories", out["check"]["differences"])
        self.assertIn(c, json.dumps(out["check"]["differences"]))      # the stories are named by their posts
        self.assertEqual(self.go()["run"]["kind"], "incremental")       # the full run wrote the state whole again
        self.full_writes_nothing()

    def test_a_run_in_a_new_process_is_incremental_and_full_without_the_state_and_nightly(self):
        self.scene()
        self.assertEqual(self.go()["run"]["kind"], "full")
        self.assertEqual(self.go()["run"]["kind"], "incremental")      # nothing of it lives in this process
        self.cur.execute("DELETE FROM mx_inc_state")                   # no state
        self.assertEqual(self.go()["run"]["kind"], "full")
        self.assertEqual(self.go()["run"]["kind"], "incremental")
        self.assertEqual(D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))["run"]["kind"], "full")  # a rule
        with unittest.mock.patch.object(I, "code_stamp", return_value="other code"):                         # the code
            self.assertEqual(D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))["run"]["kind"], "full")
        self.assertEqual(D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))["run"]["kind"], "full")  # back
        self.assertEqual(D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))["run"]["kind"], "incremental")
        self.now += timedelta(days=1)                                 # past the night's NIGHTLY_HOUR
        out = D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))
        self.assertEqual((out["run"]["kind"], out["run"].get("nightly")), ("full", True))
        self.assertEqual(out["check"], {"same": True})
        self.assertEqual(D.run(self.cur, now=self.now, config=D.Config(tau_join=0.7))["run"]["kind"], "incremental")

    def test_a_failed_run_leaves_the_last_finished_runs_state(self):
        self.scene()
        self.go()
        self.answer("check", lambda x, y: {"relation": "different", "confidence": 95})
        self.cur.execute("SAVEPOINT boom")
        with unittest.mock.patch.object(D, "persist", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.go()
        self.cur.execute("ROLLBACK TO SAVEPOINT boom")
        out = self.go()
        self.assertEqual((out["run"]["kind"], out["run"]["dirty_tasks"]), ("incremental", 3))   # the answers, still new
        self.full_writes_nothing()

    def test_a_repost_counts_as_its_author_only_when_a_source_follows_the_author(self):
        """Mark IX's rule in Mark X's decisions (pairing.counted_voice): two feeds forwarding one followed channel are
        that channel's one voice (their story is never checked); forwards of a stranger stay their feeds' two voices;
        a feed quoting a stranger is one voice. In a full run and in the state an incremental run keeps; a source that
        starts following an author makes the next run full."""
        def forward(pid, name, username):
            self.cur.execute("UPDATE posts SET metadata = jsonb_build_object('forwarded_from', jsonb_build_object("
                             "'name', %s::text, 'username', %s::text)) WHERE id = %s", (name, username, pid))
        wire, stranger = f"examplewire{uuid.uuid4().hex[:8]}", f"strangerwire{uuid.uuid4().hex[:8]}"
        followed = insert_scratch_source(self.cur, platform="telegram",
                                         settings_json=json.dumps({"display_name": "Wire"}))
        self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s", (wire, followed))
        a, b, c = self.post(0, "Acme released Widget 4"), self.post(1, "Widget 4 is out"), self.post(2, "Widget 4 hands-on")
        self.ix_story(a, b, c)                                         # three feeds, three voices: checked
        d, e = self.post(3, "Beta launches Gizmo"), self.post(4, "Gizmo by Beta is here")
        forward(d, "Example Wire", wire)
        forward(e, "Example Wire", "@" + wire.upper())
        self.ix_story(d, e)                                            # two feeds, one followed voice: never checked
        f, g = self.post(5, "Gamma ships Doohickey"), self.post(6, "Doohickey by Gamma is out")
        forward(f, "Stranger Wire", stranger)
        forward(g, "Stranger Wire", stranger)
        self.ix_story(f, g)                                            # a stranger's forwards: the two feeds' voices
        x = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Ivo"}))
        self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s",
                         (f"https://nitter.example.net/ivo{uuid.uuid4().hex[:6]}/rss", x))
        self.cur.execute("SELECT handle_or_url FROM sources WHERE id = %s", (x,))
        own = self.cur.fetchone()[0].split("/")[3]
        q1, q2 = self.post(7, "Delta Gadget notes", source=x), self.post(8, "Delta Gadget, quoted", source=x)
        self.cur.execute("UPDATE posts SET author = %s WHERE id = ANY(%s::uuid[])", (own, [q1, q2]))
        self.cur.execute("UPDATE post_parts SET quoted = 'a stranger: Delta Gadget is out' WHERE post_id = %s", (q2,))
        self.read_all([a, b, c, d, e, f, g, q1, q2])
        world = D.load(self.cur, self.now, D.Config())
        self.assertEqual(world.posts[d].source, followed)              # the followed channel's voice
        self.assertEqual((D.voices(world.posts, [d, e]), D.voices(world.posts, [f, g])), (1, 2))
        quote = tasks.load_posts(self.cur, [q1, q2])
        self.assertEqual(tasks.voices(quote.values()), 1)              # a quote of a stranger adds no voice
        self.assertEqual(D.voices(world.posts, [a, b, c]), 3)
        self.go()
        self.cur.execute("SELECT a::text FROM mx_tasks WHERE kind = 'check'")
        checked = {r[0] for r in self.cur.fetchall()}
        self.assertTrue(checked & {b, c})
        self.assertIn(g, checked)
        self.assertFalse(checked & {d, e})
        self.cur.execute("SELECT voice FROM mx_inc_posts WHERE post_id = %s", (d,))
        self.assertEqual(self.cur.fetchone()[0], followed)            # the state keeps the voice
        self.assertEqual(self.go()["run"]["kind"], "incremental")
        self.full_writes_nothing()
        forward(c, "Example Wire", wire)                               # a member becomes a forward: read again
        out = self.go()
        self.assertEqual((out["run"]["kind"], out["run"]["texts_read"]), ("incremental", 1))
        self.full_writes_nothing()
        also = insert_scratch_source(self.cur, platform="telegram", settings_json=json.dumps({"display_name": "S"}))
        self.cur.execute("UPDATE sources SET handle_or_url = %s WHERE id = %s", (stranger, also))
        out = self.go()                                                # the stranger is followed now: a full run
        self.assertEqual(out["run"]["kind"], "full")
        world = D.load(self.cur, self.now, D.Config())
        self.assertEqual(D.voices(world.posts, [f, g]), 1)
        self.assertEqual(self.go()["run"]["kind"], "incremental")
        self.full_writes_nothing()

    def test_a_seeded_world_over_rounds_of_answers_and_changes(self):
        """A random world (seeded): 8 sources, 36 posts in 6 topics, Mark IX stories, candidates within and across
        topics. Each round answers some open questions at random (every kind and relation, confidences across the
        bars), and some rounds change a text, add a post with its candidates, or add a reading; after each round an
        incremental run, then a full run of the snapshot that must write nothing and find no difference."""
        rng = random.Random(169)
        sources = [insert_scratch_source(self.cur, platform=rng.choice(["telegram", "rss"]),
                                         settings_json=json.dumps({"display_name": f"Example {n}"})) for n in range(8)]
        topics = ["Acme Widget", "Beta Gizmo", "Gamma Doohickey", "Delta Gadget", "Epsilon Thing", "Zeta Device"]
        posts, by_topic = [], {}
        for n in range(36):
            t = rng.randrange(len(topics))
            pid = self.post(rng.uniform(0, 48), f"{topics[t]} news {n}", source=rng.choice(sources))
            posts.append(pid)
            by_topic.setdefault(t, []).append(pid)
        for t, ps in by_topic.items():
            if len(ps) >= 3:
                self.ix_story(*ps[:3])

        def pairs(new=None):
            pool = posts if new is None else [new]
            for x in pool:
                for y in rng.sample(posts, 3):
                    if x != y:
                        a, b = sorted([x, y])
                        repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding",
                                           score=round(rng.uniform(0.6, 0.95), 3))
        pairs()
        unread = rng.sample(posts, 6)
        self.read_all([p for p in posts if p not in unread])
        rels = ["same_event", "development", "reaction", "mention", "digest_item", "different"]

        def answer_of(x, y):
            return {"relation": rng.choice(rels), "confidence": rng.choice([20, 55, 70, 88, 95]),
                    "reason": rng.choice(["same release", "a different event", "the same launch"]),
                    "headline_en": "A headline", "actors": ["Acme"], "object": "Widget", "action": "released",
                    "summary_en": "A summary."}
        first = self.go()
        self.assertEqual(first["run"]["kind"], "full")
        self.full_writes_nothing()
        kinds = []
        for round_ in range(8):
            for kind in ("check", "join", "pair", "merge", "card", "headline", "connect"):
                self.answer(kind, answer_of, limit=rng.randint(0, 3))
            if round_ >= 6:   # the last two rounds agree on every open join and pair (asked, then asked again): joins
                for kind in ("join", "pair"):
                    self.answer(kind, lambda x, y: {"relation": "same_event", "confidence": 95,
                                                    "reason": "the same launch"})
            if round_ == 2:                                            # a text changes
                pid = rng.choice(posts)
                self.cur.execute("UPDATE posts SET content = content || ' Updated.' WHERE id = %s", (pid,))
                from insight_core.db.repo_post_parts import PostPartsRepository
                PostPartsRepository.write(self.cur, [pid])
            if round_ == 4:                                            # a new post with candidates
                pid = self.post(rng.uniform(0, 48), f"{topics[0]} late news", source=rng.choice(sources))
                posts.append(pid)
                pairs(pid)
                self.read_all([pid])
            if round_ == 5:                                            # readings arrive
                self.read_all(unread[:3])
            out = self.go()
            kinds.append(out["run"]["kind"])
            self.full_writes_nothing()
        self.assertEqual(set(kinds), {"incremental"})
        self.cur.execute("SELECT count(*) FROM mx_story_posts WHERE valid_to IS NULL AND reason LIKE 'judge:%%'")
        self.assertGreater(self.cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
