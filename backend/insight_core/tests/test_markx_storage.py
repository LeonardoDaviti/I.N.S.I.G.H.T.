"""Mark X Shadow's storage (issue 0086 A, migration 0068): the 14 mx_* tables, their keys and uniques,
closing with valid_to (keep everything), and the migration itself (additive, idempotent, no key to
Mark IX's stories). Every test runs in one transaction rolled back at its end, so it is safe on any
database and leaves nothing behind."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import errors

from insight_core.markx import repo
from insight_core.tests._db import db_url, requires_db

MIGRATION = BACKEND_DIR / "insight_core" / "db" / "migrations" / "0068_markx_shadow.sql"
TABLES = {"mx_guides", "mx_tasks", "mx_calls", "mx_readings", "mx_mentions", "mx_embeddings", "mx_candidates",
          "mx_runs", "mx_stories", "mx_story_posts", "mx_connections", "mx_news", "mx_briefings", "mx_labels"}


def vec(*head: float) -> list:
    """A 1024-dimension vector starting with `head`, the rest zero."""
    return list(head) + [0.0] * (1024 - len(head))


@requires_db
class _Rollback(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)

    def guide(self, guide_id="test-read-v1", kind="read", body="Read the post.") -> str:
        repo.put_guide(self.cur, guide_id, kind, body, {"type": "object"})
        return guide_id

    def task(self, guide_id, text="input text", **kw):
        return repo.add_task(self.cur, kind=kw.pop("kind", "read"), guide=guide_id,
                             subject_kind=kw.pop("subject_kind", "post"), input=text, **kw)

    def call(self, task_id, valid=True, answer=None):
        return repo.add_call(self.cur, task_id=task_id, executor="claude-code", model="haiku", valid=valid,
                             answer=answer if answer is not None else {"ok": True})

    def savepoint_raises(self, exc, sql, params=()):
        """`sql` fails with `exc` without spoiling the test's transaction."""
        with self.assertRaises(exc):
            with self.conn.transaction():
                self.cur.execute(sql, params)


class MigrationTests(_Rollback):
    def test_the_fourteen_tables_exist_and_0069s_settings(self):
        self.cur.execute("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
                         "AND relkind = 'r' AND relname LIKE 'mx\\_%'")
        self.assertEqual({r[0] for r in self.cur.fetchall()},
                         TABLES | {"mx_settings"} | {"mx_jobs", "mx_candidate_posts", "mx_workers"}   # 0069, 0070
                         | {"mx_entities", "mx_entity_aliases", "mx_entity_redirects", "mx_entity_queue",
                            "mx_entity_pins", "mx_entity_vectors", "mx_entity_surges"}   # 0072 (0119)
                         | {"mx_perspectives", "mx_sheets"}                              # 0074 (0119 B)
                         | {"mx_mention_sets"}                                          # 0082 (0133)
                         | {"mx_back"}                                                  # 0085 (0136)
                         | {"mx_entity_addresses"}                                     # 0089 (0138)
                         | {"mx_post_search"}                                           # 0090 (0139)
                         | {"mx_entity_sources", "mx_story_samples", "mx_story_sample_labels"}   # 0092 (0144)
                         | {"mx_tracks", "mx_track_items", "mx_track_subtopics"}       # 0093 (0145)
                         | {"mx_track_probes", "mx_track_models"}                       # 0094 (0147)
                         | {"mx_later", "mx_later_stops"}                               # 0102 (0163)
                         | {"mx_entity_fixes"}                                          # 0104 (0164)
                         | {"mx_scout_runs", "mx_scout_candidates", "mx_scout_items",
                            "mx_source_provenance"}                                       # 0106 (0148)
                         | {"mx_research_runs", "mx_research_findings", "mx_research_pairs"}   # 0107 (0162)
                         | {"mx_plan_marks"}                                            # 0108 (v10.14)
                         | {"mx_embed_skips"}                                           # 0110 (embed text v2)
                         | {"mx_handle_scans", "mx_handle_refs", "mx_handle_pairs", "mx_entity_handles"}   # 0112 (0168)
                         | {"mx_inc_state", "mx_inc_posts", "mx_inc_inputs", "mx_inc_copies",
                            "mx_inc_tasks"}                                               # 0113 (0169)
                         | {"mx_source_judgements"}                                    # 0116 (0173)
                         | {"mx_news_sections", "mx_news_section_asks"}             # 0117 (0174)
                         | {"mx_happenings"}                                          # 0118 (0175)
                         | {"mx_label_queues", "mx_label_queue_items"}               # 0124 (0182)
                         | {"mx_roundups", "mx_units", "mx_attach", "mx_roundup_issues"}   # 0123 (0181)
                         | {"mx_unit_types", "mx_unit_type_asks"})                          # 0125 (0181)

    def test_a_setting_is_stored_replaced_and_read(self):
        key = f"test_{uuid.uuid4().hex}"
        self.assertEqual(repo.get_setting(self.cur, key, default=30), 30)       # no row: the default
        repo.set_setting(self.cur, key, 120)
        self.assertEqual(repo.get_setting(self.cur, key, default=30), 120)
        repo.set_setting(self.cur, key, None)                                  # null is a value (everything)
        self.assertIsNone(repo.get_setting(self.cur, key, default=30))

    def test_no_mx_table_keys_to_a_mark_ix_table(self):
        """Corrections 2: a Mark IX story's row is deleted and rewritten when it changes shape, so Mark X is keyed
        by posts and content. No foreign key leaves the mx_* tables, so no Mark IX write can cascade into Mark X
        or be blocked by it."""
        self.cur.execute("""SELECT child.relname, parent.relname FROM pg_constraint k
                              JOIN pg_class child ON child.oid = k.conrelid JOIN pg_class parent ON parent.oid = k.confrelid
                             WHERE k.contype = 'f' AND (child.relname LIKE 'mx\\_%' OR parent.relname LIKE 'mx\\_%')""")
        outside = [(c, p) for c, p in self.cur.fetchall() if not (c.startswith("mx_") and p.startswith("mx_"))]
        self.assertEqual(outside, [])

    def test_it_runs_again_and_changes_nothing(self):
        """Idempotent like every migration here: a second run on a migrated database is a no-op."""
        self.cur.execute(MIGRATION.read_text(encoding="utf-8"))
        self.cur.execute("SELECT count(*) FROM pg_class WHERE relname LIKE 'mx\\_%' AND relkind = 'r'")
        self.assertEqual(self.cur.fetchone()[0], 72)       # 0125 two; 0124 two; 0123 four; 0069 adds mx_settings, 0070 mx_jobs, mx_candidate_posts, mx_workers, 0072 seven, 0074 two, 0082 one, 0085 one, 0089 one, 0090 one, 0092 three, 0093 three, 0094 two, 0102 two, 0104 one, 0106 four, 0107 three, 0108 one, 0110 one, 0112 four, 0113 five, 0116 one, 0117 two, 0118 one

    def test_embeddings_have_an_hnsw_cosine_index(self):
        self.cur.execute("SELECT pg_get_indexdef(indexrelid) FROM pg_index WHERE indrelid = 'mx_embeddings'::regclass")
        defs = " ".join(r[0] for r in self.cur.fetchall())
        self.assertIn("USING hnsw (v halfvec_cosine_ops)", defs)

    def test_it_only_adds(self):
        """Additive: the migration's statements create mx_* things only (no ALTER, DROP, UPDATE or DELETE of
        another table)."""
        sql = "\n".join(l for l in MIGRATION.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))
        for word in ("ALTER TABLE", "DROP ", "UPDATE ", "DELETE ", "TRUNCATE"):
            for line in sql.splitlines():
                if word in line.upper():
                    self.assertIn("mx_", line, f"{word.strip()} outside mx_*: {line.strip()}")


class GuideTests(_Rollback):
    def test_a_guide_id_is_one_body(self):
        sha = repo.put_guide(self.cur, "test-g-v1", "read", "Body one.", None)
        self.assertEqual(repo.put_guide(self.cur, "test-g-v1", "read", "Body one.", None), sha)   # loaded again at start
        with self.assertRaises(ValueError):                                                       # a changed guide is a new id
            repo.put_guide(self.cur, "test-g-v1", "read", "Body two.", None)
        self.assertNotEqual(repo.put_guide(self.cur, "test-g-v2", "read", "Body two.", None), sha)
        self.assertEqual(repo.guides(self.cur, ["test-g-v1"])["test-g-v1"]["body"], "Body one.")

    def test_the_database_refuses_an_edited_guide_or_a_wrong_hash(self):
        self.guide("test-g-v1")
        self.savepoint_raises(errors.RaiseException, "UPDATE mx_guides SET body = 'x', sha256 = encode(sha256('x'), 'hex') "
                                                     "WHERE id = 'test-g-v1'")
        self.savepoint_raises(errors.CheckViolation, "INSERT INTO mx_guides (id, kind, sha256, body) VALUES ('test-bad', 'read', 'abc', 'b')")
        self.savepoint_raises(errors.UniqueViolation, "INSERT INTO mx_guides (id, kind, sha256, body) "
                                                      "VALUES ('test-g-v1', 'read', encode(sha256('y'), 'hex'), 'y')")


class TaskTests(_Rollback):
    def test_one_task_per_kind_guide_and_input(self):
        g = self.guide()
        first, created = self.task(g, "same input")
        self.assertTrue(created)
        again, created = self.task(g, "same input")
        self.assertEqual((again, created), (first, False))
        other, created = self.task(self.guide("test-read-v2", body="Another."), "same input")
        self.assertTrue(created)
        self.assertNotEqual(other, first)
        self.assertTrue(self.task(g, "same input", kind="entities")[1])
        self.savepoint_raises(errors.UniqueViolation,
                              "INSERT INTO mx_tasks (kind, guide, subject_kind, input, input_hash) "
                              "SELECT kind, guide, subject_kind, input, input_hash FROM mx_tasks WHERE id = %s", (first,))

    def test_the_input_hash_is_the_inputs_alone(self):
        """Corrections 2: a re-rooted Mark IX story with the same members has the same input, so it is never asked
        twice, whatever its subject ids say."""
        g = self.guide(kind="check")
        first, _ = self.task(g, "post + members", kind="check", subject_kind="post_story", a=uuid.uuid4(), b=uuid.uuid4())
        again, created = self.task(g, "post + members", kind="check", subject_kind="post_story", a=uuid.uuid4(), b=uuid.uuid4())
        self.assertEqual((again, created), (first, False))
        self.assertEqual(repo.get_task(self.cur, first)["input_hash"], repo.sha256_hex("post + members"))
        self.savepoint_raises(errors.CheckViolation,
                              "INSERT INTO mx_tasks (kind, guide, subject_kind, input, input_hash) VALUES ('read', %s, 'post', 'x', 'nope')", (g,))

    def test_lease_answer_retry_and_fail(self):
        g = self.guide()
        low, _ = self.task(g, "later", priority=5)
        high, _ = self.task(g, "first", priority=0)
        leased = repo.lease_tasks(self.cur, kinds=["read"], limit=10, worker="w1")
        ours = [t["id"] for t in leased if t["id"] in (low, high)]
        self.assertEqual(ours, [high, low])
        self.assertEqual(repo.get_task(self.cur, high)["status"], "leased")
        self.assertEqual(repo.lease_tasks(self.cur, kinds=["read"], limit=10, worker="w2"), [])   # leased: not again
        self.assertTrue(repo.answer_task(self.cur, high))
        self.assertFalse(repo.answer_task(self.cur, high))          # a second answer changes nothing
        self.assertEqual(repo.fail_attempt(self.cur, low, "span not in input"), "open")
        self.assertEqual(repo.fail_attempt(self.cur, low, "again"), "open")
        self.assertEqual(repo.fail_attempt(self.cur, low, "third"), "failed")
        row = repo.get_task(self.cur, low)
        self.assertEqual((row["attempts"], row["last_error"], row["leased_by"]), (3, "third", None))

    def test_release_and_expired_leases(self):
        g = self.guide()
        t1, _ = self.task(g, "one")
        t2, _ = self.task(g, "two")
        repo.lease_tasks(self.cur, kinds=["read"], limit=100, worker="w1")
        self.assertGreaterEqual(repo.release_tasks(self.cur, "w1"), 2)
        self.assertEqual(repo.get_task(self.cur, t1)["status"], "open")
        repo.lease_tasks(self.cur, kinds=["read"], limit=100, worker="w1")
        self.cur.execute("UPDATE mx_tasks SET lease_until = now() - interval '1 minute' WHERE id = %s", (t2,))
        self.assertGreaterEqual(repo.expire_leases(self.cur), 1)
        self.assertEqual(repo.get_task(self.cur, t2)["status"], "open")
        self.assertEqual(repo.get_task(self.cur, t1)["status"], "leased")


class AnswerTablesTests(_Rollback):
    def test_calls_readings_and_mentions(self):
        g = self.guide()
        task, _ = self.task(g)
        bad = self.call(task, valid=False, answer={"kind": "nonsense"})
        good = self.call(task)
        self.assertEqual([c["id"] for c in repo.calls(self.cur, task)], [bad, good])
        post = uuid.uuid4()
        self.assertTrue(repo.add_reading(self.cur, post_id=post, guide=g, call_id=good, kind="release", events="one",
                                         lang="en", headline="A thing shipped", reading={"main": "A thing"}))
        self.assertFalse(repo.add_reading(self.cur, post_id=post, guide=g, call_id=good, kind="other", events="one",
                                          lang="en", headline="x", reading={}))     # PK (post, guide): the first stays
        self.assertEqual(repo.readings(self.cur, [post], g)[post]["kind"], "release")

        eg = self.guide("test-ent-v1", kind="entities", body="Name the things.")
        n = repo.add_mentions(self.cur, post_id=post, guide=eg, call_id=good, mentions=[
            {"span": "Model 4.1", "name": "Maker Model 4.1", "name_key": "maker model 4.1", "type": "model",
             "role": "subject", "maker": "Maker", "family": "Model", "version": "4.1"},
            {"span": "Maker", "name": "Maker", "name_key": "maker", "type": "org", "role": "actor"}])
        self.assertEqual(n, 2)
        self.assertEqual([m["n"] for m in repo.mentions(self.cur, post, eg)], [0, 1])
        self.assertEqual(repo.posts_naming(self.cur, "maker model 4.1", version="4.1"), [post])
        self.assertEqual(repo.add_mentions(self.cur, post_id=post, guide=eg, call_id=good, mentions=[
            {"span": "x", "name": "x", "name_key": "x"}]), 0)    # a post's mentions under a guide are written once

    def test_embeddings_halfvec_and_nearest(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        self.assertTrue(repo.put_embedding(self.cur, post_id=a, model="test-m", text_hash="h1", vector=vec(1.0, 0.0)))
        repo.put_embedding(self.cur, post_id=b, model="test-m", text_hash="h1", vector=vec(0.9, 0.1))
        repo.put_embedding(self.cur, post_id=c, model="test-m", text_hash="h1", vector=vec(0.0, 1.0))
        self.assertFalse(repo.put_embedding(self.cur, post_id=a, model="test-m", text_hash="h1", vector=vec(1.0)))   # same text
        self.assertTrue(repo.put_embedding(self.cur, post_id=a, model="test-m", text_hash="h2", vector=vec(1.0)))    # text changed
        self.assertEqual(repo.embedding_hashes(self.cur, [a, b], "test-m"), {a: "h2", b: "h1"})
        self.assertTrue(repo.put_embedding(self.cur, post_id=b, model="test-m", text_hash="h1", vector=vec(0.9, 0.1),
                                           model_sha256="build-1"))   # the build recorded
        self.assertEqual(repo.embedding_builds(self.cur, "test-m"), {None: 2, "build-1": 1})
        near = repo.nearest(self.cur, vec(1.0, 0.0), model="test-m", limit=3, exclude=[a])
        self.assertEqual([p for p, _ in near if p in (b, c)], [b, c])
        self.assertAlmostEqual(dict(near)[c], 1.0, places=3)
        self.savepoint_raises(errors.DataException,
                              "INSERT INTO mx_embeddings (post_id, model, text_hash, v) VALUES (%s, 'test-m', 'h', '[1,2]')",
                              (uuid.uuid4(),))

    def test_candidates_once_per_source(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        self.assertTrue(repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.71))
        self.assertFalse(repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="embedding", score=0.9))
        self.assertTrue(repo.add_candidate(self.cur, kind="post_post", a=a, b=b, source="entity", score=1))
        self.assertEqual({c["source"] for c in repo.candidates(self.cur, "post_post", post=a)}, {"embedding", "entity"})


class ValidToTests(_Rollback):
    """Keep everything: a membership or connection that changes is closed with valid_to, never deleted."""

    def setUp(self):
        super().setUp()
        self.run = repo.start_run(self.cur, code_version="test", config={"join_p": 0.6})
        self.story = repo.add_story(self.cur, first_at=datetime.now(timezone.utc), run_id=self.run)

    def test_one_current_membership_per_story_and_post(self):
        post = uuid.uuid4()
        self.assertTrue(repo.open_membership(self.cur, story_id=self.story, post_id=post, role="member",
                                             reason="rule:link", run_id=self.run))
        self.assertFalse(repo.open_membership(self.cur, story_id=self.story, post_id=post, role="mention",
                                              reason="judge:join", run_id=self.run, p=0.7))
        self.savepoint_raises(errors.UniqueViolation,
                              "INSERT INTO mx_story_posts (story_id, post_id, role, reason) VALUES (%s, %s, 'member', 'x')",
                              (self.story, post))
        self.assertEqual([(m["post_id"], m["role"]) for m in repo.current_members(self.cur, self.story)], [(post, "member")])

    def test_closing_keeps_the_row_and_frees_the_slot(self):
        post = uuid.uuid4()
        repo.open_membership(self.cur, story_id=self.story, post_id=post, role="member", reason="rule:link", run_id=self.run)
        closed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        self.assertTrue(repo.close_membership(self.cur, story_id=self.story, post_id=post, at=closed_at))
        self.assertFalse(repo.close_membership(self.cur, story_id=self.story, post_id=post))   # nothing current to close
        self.assertEqual(repo.current_members(self.cur, self.story), [])
        self.assertEqual(repo.stories_of_post(self.cur, post), [])
        self.assertTrue(repo.open_membership(self.cur, story_id=self.story, post_id=post, role="mention",
                                             reason="judge:join", run_id=self.run, p=0.65, at=closed_at))
        history = repo.membership_history(self.cur, self.story, post)
        self.assertEqual([(h["role"], h["valid_to"] is None) for h in history], [("member", False), ("mention", True)])
        self.assertEqual(history[0]["valid_to"], closed_at)
        self.assertEqual(repo.stories_of_post(self.cur, post), [self.story])
        self.savepoint_raises(errors.CheckViolation,
                              "UPDATE mx_story_posts SET valid_to = valid_from - interval '1 day' WHERE post_id = %s AND valid_to IS NULL",
                              (post,))

    def test_a_post_in_several_stories(self):
        """0074's edge model: one post may be current in two Mark X stories."""
        other = repo.add_story(self.cur, first_at=datetime.now(timezone.utc), run_id=self.run)
        post = uuid.uuid4()
        repo.open_membership(self.cur, story_id=self.story, post_id=post, role="member", reason="rule:link", run_id=self.run)
        repo.open_membership(self.cur, story_id=other, post_id=post, role="mention", reason="judge:join", run_id=self.run)
        self.assertEqual(set(repo.stories_of_post(self.cur, post)), {self.story, other})

    def test_connections_close_and_reopen(self):
        other = repo.add_story(self.cur, first_at=datetime.now(timezone.utc), run_id=self.run)
        key = dict(a_kind="story", a=self.story, b_kind="story", b=other, relation="development")
        self.assertTrue(repo.open_connection(self.cur, **key, p=0.8, rule="test:rule", run_id=self.run, evidence={"why": "x"}))
        self.assertFalse(repo.open_connection(self.cur, **key, p=0.9, rule="test:rule", run_id=self.run))
        self.assertEqual(len(repo.current_connections(self.cur, "story", other)), 1)
        self.assertTrue(repo.close_connection(self.cur, **key))
        self.assertEqual(repo.current_connections(self.cur, "story", self.story), [])
        self.assertTrue(repo.open_connection(self.cur, **key, p=0.9, rule="test:rule", run_id=self.run))
        self.cur.execute("SELECT count(*) FROM mx_connections WHERE a = %s", (self.story,))
        self.assertEqual(self.cur.fetchone()[0], 2)
        self.savepoint_raises(errors.CheckViolation,   # every connection names a rule or a call (0086 Safety 3)
                              "INSERT INTO mx_connections (a_kind, a, b_kind, b, relation) VALUES ('post', %s, 'post', %s, 'same_topic')",
                              (uuid.uuid4(), uuid.uuid4()))

    def test_stories_runs_news_briefings_labels(self):
        other = repo.add_story(self.cur, first_at=datetime.now(timezone.utc), run_id=self.run)
        repo.merge_story(self.cur, other, into=self.story)
        self.assertEqual(repo.get_story(self.cur, other)["merged_into"], self.story)
        repo.finish_run(self.cur, self.run, counts={"joins": 1})
        self.assertEqual(repo.last_run(self.cur)["counts"], {"joins": 1})
        lead = uuid.uuid4()
        repo.add_news_rows(self.cur, self.run, [{
            "id": lead, "first_at": datetime.now(timezone.utc), "voices": 3, "reports": 2, "shares": 1, "mentions": 0,
            "score": 2.5, "tag": "NEW", "posts": [{"post_id": str(lead), "role": "report", "voice": "v", "name": None, "position": 0}]}])
        rows = repo.news_rows(self.cur, self.run)
        self.assertEqual((rows[0]["id"], rows[0]["tag"], rows[0]["posts"][0]["role"]), (lead, "NEW", "report"))
        g = self.guide("test-brief-v1", kind="briefing", body="Brief.")
        task, _ = self.task(g, kind="briefing", subject_kind="day", day=date(2026, 11, 5))
        call = self.call(task)
        repo.add_briefing(self.cur, day=date(2026, 11, 5), call_id=call, lines=[{"text": "A line", "keys": [str(lead)]}])
        self.assertEqual(repo.briefings(self.cur, date(2026, 11, 5))[0]["lines"][0]["text"], "A line")
        label = repo.add_label(self.cur, item_kind="join", a=lead, b=self.story, answer="same_event", split="dev")
        self.assertEqual([l["id"] for l in repo.labels(self.cur, "join") if l["id"] == label], [label])
        self.savepoint_raises(errors.CheckViolation,
                              "INSERT INTO mx_labels (item_kind, answer) VALUES ('nonsense', 'x')")


REOPEN = BACKEND_DIR / "insight_core" / "db" / "migrations" / "0069_markx_v10_0_1.sql"
BUG1 = "answer.mentions[{}]: name missing"


class ReopenTests(_Rollback):
    """0112 Decided 5 (migration 0069): the read tasks that failed only from bug 1 (read-v2 never names the mention
    field) are opened again once, with their tries back; their failed answers stay recorded."""

    def failed(self, kind, errors, status="failed", text=None):
        g = self.guide(f"test-{kind}-v1", kind)
        tid, _ = self.task(g, text or uuid.uuid4().hex, kind=kind)
        for e in errors:
            repo.add_call(self.cur, task_id=tid, executor="claude-code", model="haiku", valid=False, answer={}, error=e)
        self.cur.execute("UPDATE mx_tasks SET status = %s, attempts = %s, last_error = %s WHERE id = %s",
                         (status, len(errors), errors[-1] if errors else None, tid))
        return tid

    def row(self, tid):
        self.cur.execute("SELECT status, attempts, lease_until, leased_by FROM mx_tasks WHERE id = %s", (tid,))
        return self.cur.fetchone()

    def calls(self, tid):
        self.cur.execute("SELECT count(*) FROM mx_calls WHERE task_id = %s", (tid,))
        return self.cur.fetchone()[0]

    def test_only_reads_that_failed_from_bug_1_alone_are_reopened(self):
        bug1 = self.failed("read", [BUG1.format(0), BUG1.format(2), BUG1.format(0)])
        mixed = self.failed("read", [BUG1.format(0), "answer.kind: not one of report, commentary", BUG1.format(1)])
        other = self.failed("read", ["answer.main: missing"] * 3)
        entities = self.failed("entities", [BUG1.format(0)] * 3)
        waiting = self.failed("read", [BUG1.format(0)], status="open")
        self.cur.execute(REOPEN.read_text(encoding="utf-8"))
        self.assertEqual(self.row(bug1), ("open", 0, None, None))
        self.assertEqual(self.calls(bug1), 3)                      # the failed answers stay recorded
        self.assertEqual(self.row(mixed)[:2], ("failed", 3))
        self.assertEqual(self.row(other)[:2], ("failed", 3))
        self.assertEqual(self.row(entities)[:2], ("failed", 3))
        self.assertEqual(self.row(waiting)[:2], ("open", 1))
        self.cur.execute(REOPEN.read_text(encoding="utf-8"))       # idempotent: nothing more changes
        self.assertEqual(self.row(bug1), ("open", 0, None, None))
        self.assertEqual(self.row(mixed)[:2], ("failed", 3))

    def test_a_waiting_check_that_shows_an_empty_story_is_never_asked(self):
        """0112 C: v10.0 queued checks against an empty story; v10.0.1 never reads their answers, so the waiting ones
        are closed as failed, with the reason, not asked. An answered one stays as it was."""
        from insight_core.markx import tasks
        empty = "STORY\nHeadline: \n\nPOST\nPlatform: telegram | Source: S\nTitle: T\nText: words"
        shown = ("STORY\nHeadline: H\nMembers (earliest first):\n- [S, telegram] H — t\n\n"
                 "POST\nPlatform: telegram | Source: S\nTitle: T\nText: words")
        self.assertTrue(tasks.shows_empty_story(empty))
        self.assertFalse(tasks.shows_empty_story(shown))
        g = self.guide("test-check-v1", "check")
        waiting, _ = self.task(g, empty, kind="check", subject_kind="post_story")
        leased, _ = self.task(g, empty + " (leased)", kind="check", subject_kind="post_story")
        self.cur.execute("UPDATE mx_tasks SET status = 'leased', lease_until = now(), leased_by = 'w' WHERE id = %s", (leased,))
        answered, _ = self.task(g, empty + " (answered)", kind="check", subject_kind="post_story")
        self.cur.execute("UPDATE mx_tasks SET status = 'answered' WHERE id = %s", (answered,))
        fine, _ = self.task(g, shown, kind="check", subject_kind="post_story")
        self.cur.execute(REOPEN.read_text(encoding="utf-8"))
        for tid in (waiting, leased):
            self.cur.execute("SELECT status, last_error, lease_until FROM mx_tasks WHERE id = %s", (tid,))
            status, error, until = self.cur.fetchone()
            self.assertEqual((status, until), ("failed", None))
            self.assertIn("empty story", error)
        self.assertEqual(self.row(answered)[0], "answered")
        self.assertEqual(self.row(fine)[0], "open")


if __name__ == "__main__":
    unittest.main()
