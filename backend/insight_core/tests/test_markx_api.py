"""Mark X Shadow's worker API (issue 0086 C) over ASGI, against the run's own _test database: the switch
(off answers 404), the bearer token, leases, answers checked and stored (valid, invalid, the third try, a
second answer), releases, the status, the guides loaded by sha256, the tasks built from content only, and
every kind round-tripped with synthetic answers.

These suites commit (the API opens its own transactions), so they run only on a database whose name ends
in _test; each test starts from empty mx_* tables there. Every post and source is synthetic."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from urllib.parse import urlencode

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.ingestion.credentials import SecretBox
from insight_core.markx import api, repo, schemas, tasks
from insight_core.services import registry
from insight_core.tests._db import db_url, insert_scratch_source, requires_test_db

MX_TABLES = ("mx_labels", "mx_briefings", "mx_news", "mx_connections", "mx_story_posts", "mx_stories", "mx_runs",
             "mx_candidates", "mx_embeddings", "mx_mentions", "mx_readings", "mx_calls", "mx_tasks", "mx_guides",
             "mx_settings", "mx_jobs", "mx_candidate_posts", "mx_workers")


def call(method: str, path: str, *, query: Optional[Dict[str, Any]] = None, body: Any = None,
         token: Optional[str] = None):
    """(status, parsed body) of one request through the app, with a bearer token when given."""
    import main
    return asyncio.run(_call(main.app, method, path, query, body, token))


async def _call(app, method, path, query, body, token):
    raw = b"" if body is None else json.dumps(body).encode()
    headers = [(b"host", b"test"), (b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "root_path": "", "query_string": urlencode(query or {}).encode(),
             "headers": headers, "client": ("127.0.0.1", 1), "server": ("test", 80)}
    sent, status, chunks = False, 0, []
    done = asyncio.Event()

    async def receive():
        nonlocal sent
        if sent:
            await done.wait()
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                done.set()

    await app(scope, receive, send)
    data = b"".join(chunks)
    return status, (json.loads(data) if data else None)


# Three texts of their own, for the check planner's stories: posts of one text are near-copies, never checked (0112).
OWN = ("Acme released Widget 4.1 today, with 27B parameters and a price of $20 a month for every user who signs up.",
       "I tried the new version on my old laptop for a day and the battery lasted longer than with any build before.",
       "The benchmark table puts it ahead on three of the five tests, behind on long documents and on code repair.")


def reading(**over):
    r = {"kind": "report", "events": "one", "main": {"headline_en": "Acme released Widget 4.1", "actors": ["Acme"],
         "object": "Widget 4.1", "action": "released"}, "items": [], "mentions": [], "lang": "en"}
    r.update(over)
    return r


@requires_test_db
class _Api(unittest.TestCase):
    plan = False

    def setUp(self):
        self.env = os.environ.get("INSIGHT_MARKX")
        os.environ["INSIGHT_MARKX"] = "on"
        self.addCleanup(self._restore_env)
        self.addCleanup(registry.use, registry.use(SimpleNamespace(db_url=db_url())))
        self.addCleanup(setattr, api, "token_store", api.token_store)
        api.token_store = api.TokenStore(box=SecretBox(SecretBox.generate_key()))
        schemas._ready.clear()
        api._contacts.clear()
        if not self.plan:
            self.addCleanup(setattr, tasks, "PLANNERS", tasks.PLANNERS)
            tasks.PLANNERS = {}
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        # a scratch _test database: each test starts from empty mx_* tables and no worker token
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        self.cur.execute("DELETE FROM credentials WHERE provider = 'markx'")
        self.source = insert_scratch_source(self.cur, platform="telegram",
                                            settings_json=json.dumps({"display_name": "Example Channel"}))
        self.other = insert_scratch_source(self.cur, platform="rss", settings_json=json.dumps({"display_name": "Example Site"}))
        self.addCleanup(self.cur.execute, "DELETE FROM sources WHERE id = ANY(%s::uuid[])", ([self.source, self.other],))
        status, body = call("POST", "/api/markx/token")
        self.assertEqual(status, 200, body)
        self.token = body["token"]
        with self.conn.transaction():
            schemas.load_guides(self.cur)

    def _restore_env(self):
        if self.env is None:
            os.environ.pop("INSIGHT_MARKX", None)
        else:
            os.environ["INSIGHT_MARKX"] = self.env

    def post(self, title="Acme released Widget 4.1", text=None, *, source=None, at=None, links=()) -> str:
        """A synthetic post; by default each with a text of its own (the same content is the same question)."""
        url = f"https://test.invalid/mark-x/{uuid.uuid4().hex}"
        if text is None:
            text = ("Acme released Widget 4.1 today, with 27B parameters and a price of $20 a month for every user "
                    f"who signs up this week and next (note {url[-8:]}).")
        self.cur.execute("INSERT INTO posts (source_id, url, normalized_url, title, content, published_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                         (source or self.source, url, url, title, text, at or datetime.now(timezone.utc)))
        pid = str(self.cur.fetchone()[0])
        for n, (target, anchor) in enumerate(links):
            self.cur.execute("INSERT INTO post_links (post_id, target_url, target_site, position, link_text) "
                             "VALUES (%s, %s, 'example.com', %s, %s)", (pid, target, n, anchor))
        return pid

    def task(self, kind="read", post=None):
        with self.conn.transaction():
            return getattr(tasks, f"{kind}_task")(self.cur, post or self.post())[0]

    def lease(self, kind="read", limit=20, worker="device-1", token=None):
        return call("GET", "/api/markx/work", query={"kinds": kind, "limit": limit, "worker": worker},
                    token=self.token if token is None else token)

    def answer(self, *rows, worker="device-1", executor="claude-code", model="claude-haiku-5-5"):
        return call("POST", "/api/markx/answers", token=self.token,
                    body={"worker": worker, "executor": executor, "model": model,
                          "answers": [{"task_id": str(t), "answer": a, "tokens_in": 100, "tokens_out": 20, "ms": 900,
                                       "cost_usd": 0.0001} for t, a in rows]})

    def row(self, task_id):
        return repo.get_task(self.cur, task_id)


class TheSwitchAndTheToken(_Api):
    def test_off_every_path_answers_404(self):
        os.environ["INSIGHT_MARKX"] = "off"
        for method, path in (("GET", "/api/markx/work"), ("POST", "/api/markx/answers"), ("POST", "/api/markx/release"),
                             ("GET", "/api/markx/status"), ("GET", "/api/markx/token"), ("POST", "/api/markx/token")):
            with self.subTest(path=path):
                self.assertEqual(call(method, path, token=self.token, body={} if method == "POST" else None)[0], 404)
        os.environ.pop("INSIGHT_MARKX")
        self.assertEqual(call("GET", "/api/markx/status", token=self.token)[0], 404)   # the default is off

    def test_the_worker_routes_need_the_token(self):
        self.assertEqual(call("GET", "/api/markx/status")[0], 401)
        self.assertEqual(call("GET", "/api/markx/status", token="not-the-token")[0], 401)
        self.assertEqual(call("GET", "/api/markx/status", token=self.token)[0], 200)

    def test_the_token_is_stored_encrypted_and_shown_once(self):
        status, view = call("GET", "/api/markx/token")
        self.assertEqual((status, view["set"], view["last4"]), (200, True, self.token[-4:]))
        self.assertNotIn("token", view)
        self.cur.execute("SELECT ciphertext FROM credentials WHERE provider = 'markx' AND key = 'worker_token'")
        self.assertNotIn(self.token.encode(), bytes(self.cur.fetchone()[0]))

    def test_a_new_token_replaces_the_old_one(self):
        status, body = call("POST", "/api/markx/token")
        self.assertEqual(status, 200)
        self.assertNotEqual(body["token"], self.token)
        self.assertEqual(call("GET", "/api/markx/status", token=self.token)[0], 401)
        self.assertEqual(call("GET", "/api/markx/status", token=body["token"])[0], 200)


class Leases(_Api):
    def test_work_leases_by_priority_then_age_with_the_guides(self):
        old, new = self.task(), self.task()
        with self.conn.transaction():
            urgent = tasks.read_task(self.cur, self.post(title="Globex raised $300m"), priority=-1)[0]
        status, body = self.lease(limit=2)
        self.assertEqual(status, 200, body)
        self.assertEqual([t["id"] for t in body["tasks"]][0], str(urgent))
        self.assertEqual(len(body["tasks"]), 2)
        guide = body["guides"]["read-v2"]
        self.assertEqual(guide["sha256"], hashlib.sha256(guide["body"].encode()).hexdigest())
        self.assertEqual(guide["schema"], schemas.READ_SCHEMA)
        until = datetime.fromisoformat(body["lease_until"])
        self.assertIsNotNone(until.tzinfo)
        self.assertAlmostEqual((until - datetime.now(timezone.utc)).total_seconds(), 1800, delta=60)
        self.assertEqual(self.row(urgent)["status"], "leased")
        self.assertEqual(self.row(urgent)["leased_by"], "device-1")
        _, rest = self.lease(limit=20, worker="device-2")
        self.assertEqual(len(rest["tasks"]), 1)     # the third; the two leased are not leased again
        _, none = self.lease(limit=20, worker="device-2")
        self.assertEqual((none["tasks"], none["guides"]), ([], {}))

    def test_two_first_leases_at_once_on_a_fresh_database_both_succeed(self):
        """0112 bug 4: the first lease marked the guides loaded before its transaction committed, so a second lease
        planned tasks naming a guide not committed yet (a foreign-key failure, HTTP 500, worker exit 3)."""
        import threading
        import time
        from unittest import mock
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")       # a fresh database: no guide yet
        schemas._ready.clear()
        tasks.PLANNERS = {"read": lambda cur, **kw: tasks.plan_posts(cur, "read", **kw)}
        self.post(title="Globex raised $300m")
        counts, first = repo.queue_counts, threading.Event()

        def slow_first(cur):                    # the first lease holds its transaction open after loading the guides
            if not first.is_set():
                first.set()
                time.sleep(1.0)
            return counts(cur)
        got = {}

        def lease(name):
            got[name] = self.lease(worker=name)
        with mock.patch.object(repo, "queue_counts", slow_first):
            one = threading.Thread(target=lease, args=("device-1",))
            one.start()
            self.assertTrue(first.wait(5))
            two = threading.Thread(target=lease, args=("device-2",))
            two.start()
            one.join(10)
            two.join(10)
        self.assertEqual([got[n][0] for n in ("device-1", "device-2")], [200, 200], got)
        leased = [t["id"] for n in got for t in got[n][1]["tasks"]]
        self.assertTrue(leased)
        self.assertEqual(len(leased), len(set(leased)))                # none leased twice

    def test_the_guides_are_ready_only_once_their_load_commits(self):
        from unittest import mock
        from insight_core.db import database
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas._ready.clear()
        with mock.patch.object(schemas, "load_guides", side_effect=RuntimeError("the load failed")):
            with self.assertRaises(RuntimeError):
                with database.transaction(db_url()) as cur:
                    schemas.ensure_guides(cur)
        self.assertEqual(schemas._ready, set())                       # a failed load: not ready, the next one retries
        with database.transaction(db_url()) as cur:
            schemas.ensure_guides(cur)
            self.assertEqual(schemas._ready, set())                   # loaded, not committed yet: not ready
        self.assertEqual(len(schemas._ready), 1)
        self.cur.execute("SELECT count(*) FROM mx_guides")
        self.assertEqual(self.cur.fetchone()[0], len(schemas.guide_ids()))
        with mock.patch.object(schemas, "load_guides") as load:
            with database.transaction(db_url()) as cur:
                schemas.ensure_guides(cur)
        load.assert_not_called()

    def test_a_task_input_is_sent_as_built(self):
        pid = self.post(links=[("https://example.com/a", "Widget notes"), ("https://example.com/b", None)])
        self.task(post=pid)
        _, body = self.lease()
        text = body["tasks"][0]["input"]
        self.assertTrue(text.startswith("Platform: telegram | Source: Example Channel\nTitle: Acme released Widget 4.1"))
        self.assertIn('Links, in order:\n1. https://example.com/a "Widget notes"\n2. https://example.com/b', text)

    def test_an_unknown_kind_or_a_bad_limit_is_refused(self):
        self.assertEqual(self.lease(kind="summarise")[0], 400)
        self.assertEqual(self.lease(limit=0)[0], 422)
        self.assertEqual(self.lease(limit=101)[0], 422)

    def test_an_expired_lease_is_leased_again(self):
        t = self.task()
        self.lease(worker="device-1")
        self.cur.execute("UPDATE mx_tasks SET lease_until = now() - interval '1 minute' WHERE id = %s", (t,))
        _, body = self.lease(worker="device-2")
        self.assertEqual([x["id"] for x in body["tasks"]], [str(t)])
        self.assertEqual(self.row(t)["leased_by"], "device-2")

    def test_release_hands_back_some_or_all_without_a_try(self):
        a, b, c = self.task(), self.task(), self.task()
        self.lease()
        status, body = call("POST", "/api/markx/release", token=self.token, body={"worker": "device-1", "task_ids": [str(a)]})
        self.assertEqual((status, body), (200, {"released": 1}))
        self.assertEqual(self.row(a)["status"], "open")
        self.assertEqual(self.row(b)["status"], "leased")
        self.assertEqual(call("POST", "/api/markx/release", token=self.token, body={"worker": "device-2"})[1], {"released": 0})
        self.assertEqual(call("POST", "/api/markx/release", token=self.token, body={"worker": "device-1"})[1], {"released": 2})
        self.assertEqual([self.row(x)["attempts"] for x in (a, b, c)], [0, 0, 0])


class Answers(_Api):
    def test_a_valid_answer_closes_its_task_and_writes_the_reading(self):
        pid = self.post()
        t = self.task(post=pid)
        self.lease()
        status, body = self.answer((t, reading()))
        self.assertEqual((status, body), (200, {"stored": 1, "valid": 1, "invalid": [], "repeated": 0}))
        self.assertEqual(self.row(t)["status"], "answered")
        call_row, = repo.calls(self.cur, t)
        self.assertEqual((call_row["valid"], call_row["executor"], call_row["model"], call_row["tokens_in"]),
                         (True, "claude-code", "claude-haiku-5-5", 100))
        got = repo.readings(self.cur, [pid], "read-v2")[uuid.UUID(pid)]
        self.assertEqual((got["kind"], got["headline"], got["call_id"]), ("report", "Acme released Widget 4.1", call_row["id"]))

    def test_an_answer_wrapped_in_its_name_is_unwrapped(self):
        t = self.task()
        self.assertEqual(self.answer((t, {"reading": reading()}))[1]["valid"], 1)
        self.assertEqual(repo.calls(self.cur, t)[0]["answer"]["kind"], "report")

    def test_an_invalid_answer_goes_back_to_open_with_its_error_and_fails_at_the_third(self):
        t = self.task()
        for attempt in (1, 2, 3):
            self.lease()
            status, body = self.answer((t, reading(kind="news")))
            self.assertEqual(status, 200)
            self.assertEqual(body["invalid"], [{"task_id": str(t), "error": body["invalid"][0]["error"]}])
            self.assertIn("'news' is not one of", body["invalid"][0]["error"])
            row = self.row(t)
            self.assertEqual((row["attempts"], row["status"]), (attempt, "open" if attempt < 3 else "failed"))
            self.assertIn("kind", row["last_error"])
        self.assertEqual([c["valid"] for c in repo.calls(self.cur, t)], [False, False, False])
        self.assertEqual(self.lease()[1]["tasks"], [])

    def test_a_second_answer_is_kept_as_a_call_and_changes_nothing(self):
        pid = self.post()
        t = self.task(post=pid)
        self.answer((t, reading()))
        answered_at = self.row(t)["answered_at"]
        _, body = self.answer((t, reading(kind="commentary")), worker="device-2")
        self.assertEqual((body["valid"], body["repeated"]), (1, 1))
        _, body = self.answer((t, reading(kind="news")))
        self.assertEqual((body["stored"], body["repeated"], len(body["invalid"])), (1, 1, 1))
        row = self.row(t)
        self.assertEqual((row["status"], row["answered_at"], row["attempts"]), ("answered", answered_at, 0))
        self.assertEqual(len(repo.calls(self.cur, t)), 3)
        self.assertEqual(repo.readings(self.cur, [pid], "read-v2")[uuid.UUID(pid)]["kind"], "report")

    def test_an_answer_after_the_lease_ended_is_taken(self):
        t = self.task()
        self.lease(worker="device-1")
        self.cur.execute("UPDATE mx_tasks SET lease_until = now() - interval '1 minute' WHERE id = %s", (t,))
        self.lease(worker="device-2")
        self.assertEqual(self.answer((t, reading()), worker="device-1")[1]["valid"], 1)
        self.assertEqual(self.row(t)["status"], "answered")

    def test_a_task_id_that_names_no_task_is_listed_and_not_stored(self):
        t = self.task()
        _, body = self.answer((uuid.uuid4(), reading()), ("not-a-uuid", reading()), (t, reading()))
        self.assertEqual((body["stored"], body["valid"]), (1, 1))
        self.assertEqual([x["error"] for x in body["invalid"]], ["no such task", "no such task"])

    def test_the_executor_and_model_are_checked(self):
        t = self.task()
        self.assertEqual(self.answer((t, reading()), executor="laptop")[0], 400)
        self.assertEqual(self.answer((t, reading()), model="")[0], 400)
        self.assertEqual(repo.calls(self.cur, t), [])

    def test_entities_are_written_with_their_name_key(self):
        pid = self.post(title="Acme released Widget‑4.1 Pro")
        t = self.task("entities", post=pid)
        ents = [{"span": "Widget‑4.1 Pro", "name": "Widget 4.1 Pro", "type": "product", "role": "subject", "maker": "Acme",
                 "family": "Widget", "version": "4.1", "variant": "Pro", "size": None, "build": None},
                {"span": "Acme", "name": "Acme", "type": "org", "role": "actor"}]
        self.assertEqual(self.answer((t, {"entities": ents, "relations": []}))[1]["valid"], 1)
        got = repo.mentions(self.cur, pid, "ent-v3")
        self.assertEqual([(m["n"], m["name"], m["name_key"], m["version"]) for m in got],
                         [(0, "Widget 4.1 Pro", "widget 4.1 pro", "4.1"), (1, "Acme", "acme", None)])

    def test_the_status_counts_the_queue_the_answers_and_the_workers(self):
        a, b = self.task(), self.task()
        self.lease()
        self.answer((a, reading()), (b, reading(events="none")))
        status, body = call("GET", "/api/markx/status", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body["queue"], {"read": {"answered": 1, "open": 1}})
        self.assertEqual(body["tokens"], {"calls": 2, "tokens_in": 200, "tokens_out": 40, "cost_usd": 0.0002})
        self.assertEqual(body["answers_per_day"][0]["valid"], 1)
        self.assertEqual([w["worker"] for w in body["workers"]], ["device-1"])
        self.assertIsNone(body["last_run"])
        self.assertEqual(set(body["guides"]), set(schemas.guide_ids()))


class GuidesAndInputs(_Api):
    def test_the_guides_are_loaded_by_sha256_and_never_edited(self):
        got = repo.guides(self.cur)
        self.assertEqual(set(got), set(schemas.guide_ids()))
        for gid, g in got.items():
            body = (schemas.GUIDES_DIR / f"{gid}.md").read_text(encoding="utf-8")
            self.assertEqual((g["body"], g["sha256"]), (body, hashlib.sha256(body.encode()).hexdigest()))
        with self.conn.transaction():
            schemas.load_guides(self.cur)            # at every start: the same bodies, no change
        with self.assertRaises(ValueError):
            with self.conn.transaction():
                repo.put_guide(self.cur, "read-v2", "read", "another body")

    def test_a_builder_called_before_any_request_loads_the_guides_itself(self):
        """S2's and S5's jobs build tasks without the API having run: the first task loads the guides."""
        self.cur.execute(f"TRUNCATE {', '.join(MX_TABLES)}")
        schemas._ready.clear()
        task_id = self.task()
        self.assertEqual(self.row(task_id)["guide"], "read-v2")
        self.assertEqual(set(repo.guides(self.cur)), set(schemas.guide_ids()))

    def test_the_text_is_markx_text_v1_the_first_1500_characters(self):
        long = "word " * 400
        with self.conn.transaction():
            p = tasks.load_posts(self.cur, [self.post(text=long)])
        text = tasks.read_input(next(iter(p.values())))
        self.assertIn("Text: " + long.strip()[:1500] + " […]", text)
        self.assertEqual(tasks.TEXT_VERSION, "markx-text-v1")

    def test_a_story_question_is_keyed_by_its_members_content_not_by_order_or_story(self):
        post = self.post(title="Widget 4.1 is out", source=self.other)
        a = self.post(title="Acme ships Widget 4.1")
        b = self.post(title="Widget 4.1 benchmarks", at=datetime.now(timezone.utc) - timedelta(hours=1))
        with self.conn.transaction():
            first, new = tasks.check_task(self.cur, post, [a, b])
            again, new_again = tasks.check_task(self.cur, post, [b, a])
        self.assertEqual((first, new, new_again), (again, True, False))
        text = self.row(first)["input"]
        self.assertTrue(text.startswith("STORY\nHeadline: Widget 4.1 benchmarks\n"))   # the earliest other member
        self.assertNotIn("Reading of the post", text)                                    # the raw form
        self.assertIsNone(self.row(first)["b"])                                         # no Mark IX story id

    def test_checks_are_planned_from_mark_ix_stories_and_a_changed_story_is_counted_as_re_asked(self):
        """F1's checks read Mark IX's stories (never writing them, never keying by their id); when a story changes
        shape its check's input changes, and `reasked` counts it (build plan, corrections 4)."""
        t0 = datetime.now(timezone.utc) - timedelta(hours=3)
        origin = self.post(title="Acme ships Widget 4.1", text=OWN[0], source=self.other, at=t0)
        member = self.post(title="Widget 4.1 thoughts", text=OWN[1], at=t0 + timedelta(hours=1))
        late = self.post(title="Widget 4.1 benchmarks", text=OWN[2], source=self.other, at=t0 + timedelta(hours=2))
        story = origin                     # a Mark IX story is keyed by its first post
        self.addCleanup(self.cur.execute, "DELETE FROM stories WHERE id = %s", (story,))
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (story, t0))
        self.cur.execute("INSERT INTO story_posts (story_id, post_id, role, voice, parent_reason) VALUES "
                         "(%s, %s, 'report', 'v', NULL), (%s, %s, 'report', 'v', 'citation')", (story, origin, story, member))
        with self.conn.transaction():
            tasks.plan_checks(self.cur, days=1)
        self.cur.execute("SELECT input, b FROM mx_tasks WHERE kind = 'check' AND a = %s", (member,))
        (text, b), = self.cur.fetchall()
        self.assertIsNone(b)
        self.assertNotIn(story, text)
        self.assertIn("Headline: Acme ships Widget 4.1", text)
        with self.conn.transaction():
            self.assertEqual(tasks.reasked(self.cur)["check"]["would_change"], 0)
        self.cur.execute("INSERT INTO story_posts (story_id, post_id, role, voice, parent_reason) VALUES "
                         "(%s, %s, 'report', 'v', 'citation')", (story, late))
        with self.conn.transaction():
            got = tasks.reasked(self.cur)["check"]
        self.assertGreaterEqual(got["tasks"], 1)
        self.assertEqual(got["would_change"], 1)     # the member's question now shows the late post too

    def test_a_one_report_storys_check_shows_its_other_members(self):
        """0112 bug 2: a member that is its story's only report was checked against an empty story ("Headline: " and
        no member); it is shown the story's other members (any role) and its card, and a story's only post is never
        checked."""
        t0 = datetime.now(timezone.utc) - timedelta(hours=3)
        origin = self.post(title="Acme ships Widget 4.1", text="The release notes list every change in the new "
                           "version, from the faster start to the smaller memory footprint and the fixed crash.",
                           source=self.other, at=t0)
        member = self.post(title="Widget 4.1 thoughts", text="I tried it for a day on my old laptop and the battery "
                           "lasted longer than with any build before, though the settings page still confuses me.",
                           at=t0 + timedelta(hours=1))
        story = origin
        self.addCleanup(self.cur.execute, "DELETE FROM stories WHERE id = %s", (story,))
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (story, t0))
        self.cur.execute("INSERT INTO story_posts (story_id, post_id, role, voice, parent_reason) VALUES "
                         "(%s, %s, 'share', 'v', NULL), (%s, %s, 'report', 'v', 'citation')", (story, origin, story, member))
        with self.conn.transaction():
            got = {p.id: text for p, text in tasks.check_questions(self.cur, days=1)}
        text = got[member]
        self.assertTrue(text.startswith("STORY\nHeadline: Acme ships Widget 4.1\nMembers (earliest first):\n"), text)
        self.assertNotIn("Headline: \n", text)

    def test_the_real_data_check_counts_a_waiting_check_that_shows_an_empty_story(self):
        """0112 C: markx.check_empty_story, a check task still to be asked whose input shows a story with no member."""
        from insight_core.checks import invariants
        a, b = self.post(title="Acme ships Widget 4.1", text=OWN[0]), self.post(title="Widget 4.1 thoughts", text=OWN[1])
        posts = tasks.load_posts(self.cur, [a, b])
        with self.conn.transaction():
            empty, _ = tasks.add(self.cur, "check", tasks.check_input(posts[b], []), a=b)
            shown, _ = tasks.add(self.cur, "check", tasks.check_input(posts[b], [posts[a]]), a=b)
            asked, _ = tasks.add(self.cur, "check", tasks.check_input(posts[a], []), a=a)
            self.cur.execute("UPDATE mx_tasks SET status = 'answered' WHERE id = %s", (asked,))
        for text, empty_story in ((tasks.check_input(posts[b], []), True), (tasks.check_input(posts[b], [posts[a]]), False)):
            self.assertEqual(tasks.shows_empty_story(text), empty_story)
            self.assertEqual(invariants._shows_empty_story(text), empty_story)   # the checks package's own copy
        check, = [i for i in invariants.INVARIANTS if i.name == "markx.check_empty_story"]
        with self.conn.transaction():
            ids, of = check.count(invariants.Run(db_url(), self.cur, datetime.now(timezone.utc)))
        self.assertEqual((ids, of), ([str(empty)], 2))      # waiting: the empty one and the shown one; answered: v10.0's

    def test_the_story_a_check_shows(self):
        a, b, c = (tasks.Post(id=x, kind="telegram", source=x, source_id=x, at=datetime(2100, 1, 1, n, tzinfo=timezone.utc),
                              title=x, text="t") for n, x in enumerate("abc"))
        self.assertEqual([m.id for m in tasks.check_side(b, [a, b, c], {"a", "b"})], ["a"])     # the reports but the post
        self.assertEqual([m.id for m in tasks.check_side(b, [a, b, c], {"b"})], ["a", "c"])     # its only report: any role
        self.assertEqual(tasks.check_side(b, [b], {"b"}), [])                                   # alone: nothing to ask

    def test_a_near_copy_is_never_a_check_question(self):
        """0112 bug 3: identical reposts were checked and removed (9 of 44 removals). A member whose folded text is
        another member's, or whose 5-word shingles overlap one's by 0.6 or more, from any source, is never checked."""
        t0 = datetime.now(timezone.utc) - timedelta(hours=3)
        teaser = ("Open meeting on Friday: a project with agents from the first idea to working code, "
                  "with a live demo and questions at the end, everyone is welcome to join us.")
        origin = self.post(title="Open meeting on Friday", text=teaser, source=self.other, at=t0)
        copy = self.post(title="Open meeting on Friday", text="🔥 " + teaser.upper(), at=t0 + timedelta(hours=1))
        own = self.post(title="My notes from the agents meeting", text="The speaker showed how they split a large task "
                        "into small steps, and the part about tests before code was the most useful for my team.",
                        at=t0 + timedelta(hours=2))
        story = origin
        self.addCleanup(self.cur.execute, "DELETE FROM stories WHERE id = %s", (story,))
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (story, t0))
        self.cur.execute("INSERT INTO story_posts (story_id, post_id, role, voice, parent_reason) VALUES "
                         "(%s, %s, 'report', 'v', NULL), (%s, %s, 'report', 'v', 'copy'), (%s, %s, 'report', 'v', 'citation')",
                         (story, origin, story, copy, story, own))
        with self.conn.transaction():
            asked = {p.id for p, _ in tasks.check_questions(self.cur, days=1)}
        self.assertNotIn(copy, asked)
        self.assertIn(own, asked)

    def test_near_copies(self):
        def p(pid, text, title="T", source="s"):
            return tasks.Post(id=pid, kind="telegram", source=source, source_id=source,
                              at=datetime(2100, 1, 1, tzinfo=timezone.utc), title=title, text=text)
        base = " ".join(f"w{k}" for k in range(40))
        edited = " ".join(f"w{k}" for k in range(36)) + " x1 x2 x3 x4"           # 32 shingles shared of 40: 0.8
        other = " ".join(f"w{k}" for k in range(0, 40, 2)) + " " + " ".join(f"v{k}" for k in range(20))
        ms = [p("a", base), p("b", "«" + base.upper() + "»!", source="t"), p("c", edited, source="u"), p("d", other)]
        self.assertTrue(tasks.near_copy(ms[0], ms[1]))                           # the same folded text, another source
        self.assertTrue(tasks.near_copy(ms[0], ms[2]))                           # shingles at 0.6 or more
        self.assertFalse(tasks.near_copy(ms[0], ms[3]))
        self.assertEqual(tasks.near_copies(ms), {"a", "b", "c"})
        self.assertEqual(tasks.near_copies([ms[0], ms[3]]), set())

    def test_a_member_joined_by_thread_is_checked_unless_switched_off(self):
        """The S5 review's W1: a thread Mark IX hung on a story by its root's citation is checked reply by reply."""
        t0 = datetime.now(timezone.utc) - timedelta(hours=3)
        origin = self.post(title="Acme ships Widget 4.1", text=OWN[0], source=self.other, at=t0)
        root = self.post(title="Benchmarks of many models", text=OWN[1], at=t0 + timedelta(hours=1))
        reply = self.post(title="More benchmark numbers", text=OWN[2], at=t0 + timedelta(hours=2))
        story = origin
        self.addCleanup(self.cur.execute, "DELETE FROM stories WHERE id = %s", (story,))
        self.cur.execute("INSERT INTO stories (id, first_at, voices) VALUES (%s, %s, 2)", (story, t0))
        self.cur.execute("INSERT INTO story_posts (story_id, post_id, role, voice, parent_reason) VALUES "
                         "(%s, %s, 'report', 'v', NULL), (%s, %s, 'report', 'v', 'citation'), "
                         "(%s, %s, 'report', 'v', 'thread')", (story, origin, story, root, story, reply))
        with self.conn.transaction():
            asked = {p.id for p, _ in tasks.check_questions(self.cur, days=1)}
            without = {p.id for p, _ in tasks.check_questions(self.cur, days=1, threads=False)}
        self.assertTrue({root, reply} <= asked)
        self.assertIn(root, without)
        self.assertNotIn(reply, without)

    def test_plan_posts_takes_the_newest_of_the_last_30_days_once(self):
        now = datetime.now(timezone.utc) + timedelta(days=3650)    # a window no other suite's posts reach
        fresh = self.post(at=now - timedelta(hours=2))
        older = self.post(at=now - timedelta(days=3, hours=1))
        self.post(at=now - timedelta(days=40))
        with self.conn.transaction():
            self.assertEqual(tasks.plan_posts(self.cur, "read", now=now), 2)
            self.assertEqual(tasks.plan_posts(self.cur, "read", now=now), 0)
        self.cur.execute("SELECT a, priority FROM mx_tasks WHERE kind = 'read' ORDER BY priority")
        self.assertEqual([(str(a), p) for a, p in self.cur.fetchall()], [(fresh, 0), (older, 3)])


class ReadingWindow(_Api):
    """0112 Decided 9: the read, entities and embed planners' window is the owner's (the page's mx_settings row,
    default 30 days, null for every post), and a lease may carry its own (`days`); the decision window stays 30."""
    plan = True

    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        self.fresh = self.post(title="Fresh", at=self.now - timedelta(days=2))
        self.old = self.post(title="Old", at=self.now - timedelta(days=100))
        self.ancient = self.post(title="Ancient", at=self.now - timedelta(days=2000))

    def planned(self, kind="read"):
        self.cur.execute("SELECT a::text FROM mx_tasks WHERE kind = %s", (kind,))
        return {r[0] for r in self.cur.fetchall()} & {self.fresh, self.old, self.ancient}

    def test_the_page_setting_changes_the_next_planner_runs_window(self):
        self.assertEqual(call("GET", "/api/markx/settings")[1]["reading_window_days"], 30)     # no row: 30
        with self.conn.transaction():
            tasks.plan_posts(self.cur, "read")
        self.assertEqual(self.planned(), {self.fresh})
        status, body = call("POST", "/api/markx/settings/reading-window", body={"days": 120})
        self.assertEqual((status, body["reading_window_days"]), (200, 120))
        with self.conn.transaction():
            tasks.plan_posts(self.cur, "read")
            tasks.plan_posts(self.cur, "entities")
        self.assertEqual(self.planned(), {self.fresh, self.old})
        self.assertEqual(self.planned("entities"), {self.fresh, self.old})
        self.assertEqual(call("POST", "/api/markx/settings/reading-window", body={"days": None})[1]["reading_window_days"], None)
        with self.conn.transaction():
            tasks.PLANNERS["read"](self.cur)
        self.assertEqual(self.planned(), {self.fresh, self.old, self.ancient})
        self.assertEqual(call("GET", "/api/markx/overview")[1]["reading_window"]["days"], None)

    def test_the_embed_planner_reads_the_setting(self):
        with self.conn.transaction():
            tasks.PLANNERS["embed"](self.cur)
        self.assertEqual(self.planned("embed"), {self.fresh})
        call("POST", "/api/markx/settings/reading-window", body={"days": 120})
        with self.conn.transaction():
            tasks.PLANNERS["embed"](self.cur)
        self.assertEqual(self.planned("embed"), {self.fresh, self.old})

    def test_a_bad_window_is_refused(self):
        for bad in (0, -3, "120", 1.5, 100000):
            self.assertEqual(call("POST", "/api/markx/settings/reading-window", body={"days": bad})[0], 422, bad)
        self.assertEqual(self.lease(days="soon")[0], 400)
        self.assertEqual(self.lease(days="0")[0], 400)

    def lease(self, days, kind="read", limit=100):
        return call("GET", "/api/markx/work", query={"kinds": kind, "limit": limit, "worker": "device-1", "days": days},
                    token=self.token)

    def test_a_lease_with_days_120_plans_older_posts_first(self):
        status, body = self.lease("120")
        self.assertEqual(status, 200, body)
        self.assertEqual(self.planned(), {self.fresh, self.old})
        leased = {t["input"].split("Title: ")[1].split("\n")[0] for t in body["tasks"]}
        self.assertTrue({"Fresh", "Old"} <= leased)
        self.assertNotIn("Ancient", leased)
        self.assertEqual(call("GET", "/api/markx/settings")[1]["reading_window_days"], 30)   # the page's is unchanged

    def test_a_lease_with_days_all_covers_every_post(self):
        status, body = self.lease("all")
        self.assertEqual(status, 200, body)
        self.assertEqual(self.planned(), {self.fresh, self.old, self.ancient})

    def test_neither_touches_the_decision_window(self):
        from insight_core.markx import decide as D
        call("POST", "/api/markx/settings/reading-window", body={"days": None})
        self.lease("all")
        self.assertEqual(D.Config().days, 30)
        with self.conn.transaction():
            world = D.load(self.cur, self.now, D.Config())
        self.assertEqual(world.since, self.now - timedelta(days=30))
        import inspect
        self.assertEqual(inspect.signature(tasks.plan_checks).parameters["days"].default, 30)


class EveryKindRoundTrips(_Api):
    """Each kind built by its builder, leased, answered with a valid answer, then the invalid cases 0086 C names."""

    def setUp(self):
        super().setUp()
        t0 = datetime.now(timezone.utc) - timedelta(hours=5)
        self.a1 = self.post(title="Acme ships Widget 4.1 Pro", text="Acme released Widget 4.1 Pro with 27B parameters, "
                            "priced at $20 a month for teams.", source=self.other, at=t0)
        self.a2 = self.post(title="Widget 4.1 Pro is out", text="Acme's Widget 4.1 Pro arrived today for everyone "
                            "who builds agents.", at=t0 + timedelta(hours=1))
        self.b1 = self.post(title="Globex raised $987m", text="Globex raised $987m in a round led by Initech to build "
                            "chips.", source=self.other, at=t0 + timedelta(hours=2))
        self.b2 = self.post(title="Globex funding round", text="The round values Globex at $2bn, its founders said "
                            "on Tuesday.", at=t0 + timedelta(hours=3))

    def build(self):
        with self.conn.transaction():
            c = self.cur
            return {
                "read": tasks.read_task(c, self.a1)[0],
                "entities": tasks.entities_task(c, self.a1)[0],
                "check": tasks.check_task(c, self.a2, [self.a1])[0],
                "join": tasks.join_task(c, self.a2, [self.a1])[0],
                "pair": tasks.pair_task(c, self.a1, self.a2)[0],
                "merge": tasks.merge_task(c, [self.a1, self.a2], [self.b1, self.b2])[0],
                "connect": tasks.connect_task(c, [self.a1, self.a2], [self.b1, self.b2])[0],
                "card": tasks.card_task(c, [self.a1, self.a2])[0],
                "headline": tasks.headline_task(c, [self.a1, self.a2])[0],
                "briefing": tasks.briefing_task(c, date(2026, 11, 2), [("Acme ships Widget 4.1 Pro", [self.a1, self.a2]),
                                                                      ("Globex raised $987m", [self.b1, self.b2])])[0],
                "translate": tasks.translate_task(c, self.b2)[0],
            }

    VALID = {
        "read": reading(),
        "entities": {"entities": [{"span": "Widget 4.1 Pro", "name": "Widget 4.1 Pro", "type": "product", "role": "subject",
                                   "version": "4.1"}], "relations": []},
        "check": {"relation": "same_event", "confidence": 90, "reason": "Same launch."},
        "join": {"relation": "reaction", "confidence": 70, "reason": "Reacts to it."},
        "pair": {"relation": "same_event", "confidence": 85, "reason": "Same launch."},
        "merge": {"relation": "different", "confidence": 95, "reason": "Another event."},
        "connect": {"relation": "different", "confidence": 90, "reason": "Unrelated."},
        "card": {"headline_en": "Acme released Widget 4.1 Pro", "actors": ["Acme"], "object": "Widget 4.1 Pro",
                 "action": "released", "date": None, "summary_en": "Acme released it.", "odd": []},
        "headline": {"headline_en": "Acme ships Widget 4.1 Pro at $20 a month", "summary_en": "Acme released it."},
        "briefing": {"lines": [{"text": "Acme shipped Widget 4.1 Pro at $20 a month.", "stories": ["s1"]},
                               {"text": "Globex raised $987m.", "stories": ["s2"]}]},
        "translate": {"title_en": "Globex funding round", "text_en": "The round values Globex at $2bn, its founders said on Tuesday."},
    }
    INVALID = {
        "read": ({**reading(), "events": "none"}, "main must be null when events is none"),
        "entities": ({"entities": [{"span": "Widget 5", "name": "Widget 5", "type": "product", "role": "subject"}]},
                     "entities[0].span 'Widget 5' does not occur in the post"),
        "check": ({"relation": "related", "confidence": 50}, "answer.relation: 'related' is not one of"),
        "join": ({"relation": "same_event", "confidence": 150}, "answer.confidence: above 100"),
        "pair": ({"relation": "same_event"}, "answer: confidence missing"),
        "merge": ({"relation": "merged", "confidence": 90}, "answer.relation: 'merged' is not one of"),
        "connect": ({"relation": "builds_on", "confidence": 90}, "answer.relation: 'builds_on' is not one of"),
        "card": ({"headline_en": "Acme released Widget 4.1 Pro", "actors": [], "object": "", "action": "released",
                  "odd": ["ffffffff"]}, "odd names 'ffffffff', not a member"),
        "headline": ({"headline_en": "Acme ships Widget 4.1 Pro at $99"}, "headline_en: the figure 99 occurs in no member"),
        "briefing": ({"lines": [{"text": "Globex raised $987m.", "stories": ["s1"]},
                                {"text": "Acme shipped.", "stories": ["s2"]}]},
                     "lines[0]: the figure 987 occurs in none of its stories (s1)"),
        "translate": ({"title_en": "Globex funding round", "text_en": "The round values Globex highly, its founders said."},
                      "the number 2 of the post is not in the translation"),
    }

    def test_every_kind_is_leased_and_answered(self):
        ids = self.build()
        for kind, task_id in ids.items():
            with self.subTest(kind=kind):
                _, body = self.lease(kind)
                self.assertEqual([t["id"] for t in body["tasks"]], [str(task_id)])
                self.assertEqual(set(body["guides"]), {schemas.KINDS[kind].guide})
                _, got = self.answer((task_id, self.VALID[kind]))
                self.assertEqual(got, {"stored": 1, "valid": 1, "invalid": [], "repeated": 0}, got)
                self.assertEqual(self.row(task_id)["status"], "answered")

    def test_every_kind_returns_its_invalid_case_with_its_error(self):
        ids = self.build()
        for kind, task_id in ids.items():
            with self.subTest(kind=kind):
                answer, error = self.INVALID[kind]
                _, got = self.answer((task_id, answer))
                self.assertEqual(got["valid"], 0)
                self.assertTrue(got["invalid"][0]["error"].startswith(error), got["invalid"][0]["error"])
                self.assertEqual(self.row(task_id)["status"], "open")
                self.assertTrue(self.row(task_id)["last_error"].startswith(error))

    def test_too_many_entities_and_a_version_not_in_the_post(self):
        t = self.build()["entities"]
        one = {"span": "Acme", "name": "Acme", "type": "org", "role": "actor"}
        _, got = self.answer((t, {"entities": [one] * 21}))
        self.assertEqual(got["invalid"][0]["error"], "answer.entities: 21 items, more than 20")
        _, got = self.answer((t, {"entities": [dict(one, span="Widget 4.1 Pro", version="4.2")]}))
        self.assertEqual(got["invalid"][0]["error"], "entities[0].version '4.2' does not occur in the post")


if __name__ == "__main__":
    unittest.main()
