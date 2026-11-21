"""Tests for scripts/markx-worker (0086 part D) against a stub of 0086 C's API and a fake `claude`.

    python3 -m unittest discover -s scripts/tests -p 'test_markx_worker.py'

Standard library only, no network beyond 127.0.0.1, never the real `claude`: every run passes --claude
scripts/tests/fake-claude, and PATH starts with a directory whose `claude` is the fake too.
"""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
WORKER = HERE.parent / "markx-worker"
FAKE = HERE / "fake-claude"
TOKEN = "test-token-not-a-secret"

_loader = importlib.machinery.SourceFileLoader("markx_worker", str(WORKER))
_spec = importlib.util.spec_from_loader("markx_worker", _loader)
W = importlib.util.module_from_spec(_spec)
_loader.exec_module(W)

SCHEMA = {"type": "object", "required": ["kind", "headline"], "additionalProperties": False,
          "properties": {"kind": {"enum": ["news", "other"]}, "headline": {"type": "string", "maxLength": 200}}}


def guide(gid, body):
    return {"sha256": hashlib.sha256(body.encode()).hexdigest(), "body": body, "schema": SCHEMA}


GUIDES = {"read-v2": guide("read-v2", "GUIDE read-v2: read the post."),
          "ent-v3": guide("ent-v3", "GUIDE ent-v3: list the entities."),
          "judge-story-v1": guide("judge-story-v1", "GUIDE judge-story-v1: are the two stories one?")}
KIND_GUIDE = {"read": "read-v2", "entities": "ent-v3", "merge": "judge-story-v1"}


# ---------------------------------------------------------------------------------------------- the stub

class Stub:
    """0086 C's worker API, in memory: leases, checks, calls, releases."""

    def __init__(self, lease_seconds=1800, token=TOKEN):
        self.lease_seconds = lease_seconds
        self.token = token
        self.tasks = {}             # str(id) -> task
        self.calls = []             # every stored answer
        self.posts = []             # every answers payload
        self.releases = []          # every release body
        self.works = []             # every /work query
        self.picked = []            # tasks each /work leased
        self.fail_posts = 0         # answer this many posts with 503 first
        self.slow_kinds = set()     # /work for these kinds answers after 2 s (v10.13.2)
        self.unknown_kinds = set()  # /work for these kinds answers 400 unknown kind (a server older than the worker)
        self.guides = dict(GUIDES)
        self.lock = threading.Lock()
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth(self):
                if self.headers.get("Authorization") != f"Bearer {stub.token}":
                    self._send(401, {"detail": "bad token"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                u = urlparse(self.path)
                if u.path == "/api/markx/work":
                    q = {k: v[0] for k, v in parse_qs(u.query).items()}
                    if q.get("kinds") in stub.slow_kinds:
                        time.sleep(2)
                    if q.get("kinds") in stub.unknown_kinds:
                        return self._send(400, {"detail": f"unknown kind: {q.get('kinds')}"})
                    self._send(200, stub.work(q))
                elif u.path == "/api/markx/status":
                    self._send(200, stub.status())
                else:
                    self._send(404, {})

            def do_POST(self):
                if not self._auth():
                    return
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/api/markx/answers":
                    with stub.lock:
                        if stub.fail_posts > 0:
                            stub.fail_posts -= 1
                            return self._send(503, {"detail": "down"})
                    self._send(200, stub.answers(body))
                elif self.path == "/api/markx/release":
                    self._send(200, stub.release(body))
                else:
                    self._send(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def add(self, kind, n, start=1, ids=None, post=None):
        for k in range(n):
            tid = ids[k] if ids else start + k
            self.tasks[str(tid)] = {"id": tid, "kind": kind, "guide": KIND_GUIDE[kind], "priority": 0,
                                    "input": f"platform: test\ntitle: post {tid}\ntext: something happened",
                                    "status": "open", "lease_until": None, "leased_by": None, "attempts": 0,
                                    "last_error": None}
            if post is not None:          # 0176: a long post's windows carry their post
                self.tasks[str(tid)]["post"] = post

    def _expire(self, now):
        for t in self.tasks.values():
            if t["status"] == "leased" and t["lease_until"] < now:
                t.update(status="open", lease_until=None, leased_by=None)

    def work(self, q):
        now = datetime.now(timezone.utc)
        with self.lock:
            self.works.append(q)
            self._expire(now)
            kinds = q["kinds"].split(",")
            until = now + timedelta(seconds=self.lease_seconds)
            pick = [t for t in self.tasks.values() if t["status"] == "open" and t["kind"] in kinds]
            pick = pick[:int(q["limit"])]
            self.picked.append(len(pick))
            for t in pick:
                t.update(status="leased", lease_until=until, leased_by=q["worker"])
            return {"lease_until": until.isoformat(), "guides": {t["guide"]: self.guides[t["guide"]] for t in pick},
                    "tasks": [dict({"id": t["id"], "kind": t["kind"], "guide": t["guide"], "input": t["input"]},
                                   **({"post": t["post"]} if "post" in t else {}),
                                   **({"model": t["model"]} if "model" in t else {})) for t in pick]}

    def check(self, answer):
        err = W.schema_error(SCHEMA, answer) if isinstance(answer, dict) else "not an object"
        if not err and answer.get("headline") == "SERVER-BAD":
            err = "headline: a figure that does not occur in the input"
        return err

    def answers(self, body):
        with self.lock:
            self.posts.append(body)
            invalid, nvalid = [], 0
            for a in body["answers"]:
                t = self.tasks[str(a["task_id"])]
                err = self.check(a["answer"])
                self.calls.append({**a, "worker": body["worker"], "executor": body["executor"],
                                   "model": body["model"], "valid": err is None, "error": err})
                if t["status"] == "answered":
                    continue                       # a second answer: kept as a call, changes nothing
                if err is None:
                    nvalid += 1
                    t.update(status="answered", lease_until=None, leased_by=None)
                else:
                    invalid.append({"task_id": a["task_id"], "error": err})
                    t["attempts"] += 1
                    t.update(status="failed" if t["attempts"] >= 3 else "open", lease_until=None,
                             leased_by=None, last_error=err)
            return {"stored": len(body["answers"]), "valid": nvalid, "invalid": invalid}

    def release(self, body):
        with self.lock:
            self.releases.append(body)
            ids = set(map(str, body["task_ids"])) if "task_ids" in body else None
            n = 0
            for k, t in self.tasks.items():
                if t["status"] == "leased" and t["leased_by"] == body["worker"] and (ids is None or k in ids):
                    t.update(status="open", lease_until=None, leased_by=None)
                    n += 1
            return {"released": n}

    def status(self):
        with self.lock:
            out = {}
            for t in self.tasks.values():
                out.setdefault(t["kind"], {}).setdefault(t["status"], 0)
                out[t["kind"]][t["status"]] += 1
            return {"queue": out}

    def by_status(self, status):
        return sorted((t["id"] for t in self.tasks.values() if t["status"] == status), key=str)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------------------------- the runs

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="markx-worker-test-"))
        (self.tmp / "bin").mkdir()
        (self.tmp / "bin" / "claude").symlink_to(FAKE)     # a bare `claude` is the fake too
        (self.tmp / "state").mkdir()
        self.token_file = self.tmp / "token"
        self.token_file.write_text(TOKEN + "\n")
        self.token_file.chmod(0o600)
        self.log = self.tmp / "worker.jsonl"
        self.spool = self.tmp / "spool.jsonl"
        self.fake_log = self.tmp / "fake.jsonl"
        self.stub = Stub()
        self.addCleanup(self.stub.close)

    def run_worker(self, *extra, plan="valid", server=None, cmd="cycle", timeout=60):
        env = {**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ.get('PATH', '')}",
               "FAKE_CLAUDE_PLAN": plan, "FAKE_CLAUDE_STATE": str(self.tmp / "state"),
               "FAKE_CLAUDE_LOG": str(self.fake_log), "MARKX_CLAUDE": str(FAKE)}
        argv = [sys.executable, str(WORKER), cmd, "--server", server or self.stub.url,
                "--token-file", str(self.token_file), "--worker", "test-device", "--log", str(self.log), "--quiet"]
        if cmd == "cycle":
            argv += ["--claude", str(FAKE), "--spool", str(self.spool), "--retry-wait", "0"]
        p = subprocess.run(argv + list(extra), env=env, capture_output=True, text=True, timeout=timeout)
        return p

    def fake_calls(self):
        if not self.fake_log.exists():
            return []
        return [json.loads(x) for x in self.fake_log.read_text().splitlines()]

    def events(self, name=None):
        if not self.log.exists():
            return []
        ev = [json.loads(x) for x in self.log.read_text().splitlines()]
        return [e for e in ev if name is None or e["event"] == name]

    def done(self):
        return self.events("done")[-1]


class TestSystemPrompt(unittest.TestCase):
    """v10.0.1: the guide's answer schema goes with its body, so the field names are never left to the prose."""

    def test_the_body_then_the_schema_with_its_exact_field_names(self):
        g = GUIDES["read-v2"]
        s = W.system_for(g)
        self.assertTrue(s.startswith(g["body"]))
        self.assertIn("with exactly these field names:", s)
        self.assertEqual(json.loads(s.rsplit("\n", 1)[1]), SCHEMA)

    def test_a_guide_without_a_schema_is_its_body(self):
        self.assertEqual(W.system_for({"body": "B", "schema": None}), "B")
        self.assertEqual(W.system_for({"body": "B"}), "B")


class TestValid(Base):
    def test_every_task_answered_in_batches_of_20_three_at_a_time(self):
        self.stub.add("read", 45)
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 45)
        calls = self.fake_calls()
        self.assertEqual(sorted(c["stdin"].count("### ITEM id:") for c in calls), [5, 20, 20])
        for c in calls:
            self.assertEqual(c["argv"], ["-p", "--model", "haiku", "--tools", "", "--system-prompt",
                                         W.system_for(GUIDES["read-v2"]), "--output-format", "json",
                                         "--no-session-persistence", "--strict-mcp-config"])
            self.assertTrue(c["stdin"].startswith(W.HEAD))
        for w in self.stub.works:
            self.assertEqual(w["kinds"], "read")
            self.assertEqual(w["limit"], "20")
            self.assertEqual(w["worker"], "test-device")
        self.assertEqual(self.stub.releases, [])
        self.assertTrue(all(c["valid"] for c in self.stub.calls))

    def test_a_kinds_model_from_the_server_is_the_one_asked(self):
        """v10.18: a task the server names a model for (entity_bands.json `models`) is asked with it, else --model."""
        self.stub.add("read", 3)
        for t in list(self.stub.tasks.values())[:3]:
            t["model"] = "sonnet"
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual({c["argv"][2] for c in self.fake_calls()}, {"sonnet"})

    def test_days_goes_with_every_lease_and_without_it_none(self):
        """0112 Decided 9: `--days <N|all>` makes the server plan that window first; without it the page's holds."""
        self.stub.add("read", 5)
        p = self.run_worker("--kinds", "read", "--days", "120")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.stub.works)
        self.assertTrue(all(w.get("days") == "120" for w in self.stub.works), self.stub.works)
        self.stub.works.clear()
        self.stub.add("read", 5)
        self.assertEqual(self.run_worker("--kinds", "read", "--days", "all").returncode, 0)
        self.assertTrue(all(w.get("days") == "all" for w in self.stub.works))
        self.stub.works.clear()
        self.stub.add("read", 5)
        self.assertEqual(self.run_worker("--kinds", "read").returncode, 0)
        self.assertTrue(all("days" not in w for w in self.stub.works))
        for bad in ("0", "soon", "-3"):
            self.assertEqual(self.run_worker("--kinds", "read", "--days", bad).returncode, 2, bad)

    def test_tokens_and_cost_from_claude_codes_json_logged_and_posted(self):
        self.stub.add("read", 45)
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        # the fake reports, per call: 100 + 2000 + 300 in, 40 per item out, $0.002 per item
        posted_in = sum(c["tokens_in"] for c in self.stub.calls)
        posted_out = sum(c["tokens_out"] for c in self.stub.calls)
        posted_cost = sum(c["cost_usd"] for c in self.stub.calls)
        self.assertEqual(posted_in, 3 * 2400)
        self.assertEqual(posted_out, 45 * 40)
        self.assertAlmostEqual(posted_cost, 45 * 0.002, places=6)
        for c in self.stub.calls:
            self.assertEqual(c["executor"], "claude-code")
            self.assertEqual(c["model"], "claude-haiku-fake")
            self.assertEqual(c["tokens_out"], 40)
            self.assertIn("ms", c)
        logged = self.events("call")
        self.assertEqual(sum(e["tokens_in"] for e in logged), 3 * 2400)
        self.assertEqual(sum(e["tokens_out"] for e in logged), 45 * 40)
        d = self.done()
        self.assertEqual((d["tokens_in"], d["tokens_out"], d["valid"], d["exit"]), (7200, 1800, 45, 0))

    def test_drain_keeps_the_old_order(self):
        """--drain: a kind until it runs dry, then the next (the order before v10.12.1)."""
        self.stub.add("read", 25, start=1)
        self.stub.add("entities", 25, start=101)
        p = self.run_worker("--kinds", "read,entities", "--parallel", "1", "--batches", "10", "--drain")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([w["kinds"] for w in self.stub.works], ["read", "read", "entities", "entities"])

    def test_a_long_queue_does_not_starve_the_kinds_after_it(self):
        """v10.12.1: with a long first queue and a batch budget it can fill alone, every kind still gets a turn."""
        self.stub.add("read", 200, start=1)
        self.stub.add("entities", 5, start=1001)
        p = self.run_worker("--kinds", "read,entities", "--parallel", "1", "--batches", "3")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("entities", [w["kinds"] for w in self.stub.works])

    def test_one_kind_per_batch_in_the_kinds_order(self):
        self.stub.add("read", 25, start=1)
        self.stub.add("entities", 25, start=101)
        p = self.run_worker("--kinds", "read,entities", "--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 50)
        self.assertEqual([w["kinds"] for w in self.stub.works], ["read", "entities", "read", "entities"])   # v10.12.1: turns
        for c in self.fake_calls():
            ids = [int(x) for x in __import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)]
            kinds = {self.stub.tasks[str(i)]["kind"] for i in ids}
            self.assertEqual(len(kinds), 1)
            self.assertEqual(c["system"], W.system_for(GUIDES[KIND_GUIDE[kinds.pop()]]))

    def test_merges_are_asked_one_per_call_and_leased_twenty_at_a_time(self):
        """0112 Decided 8: a merge is asked alone (313 of 313 answered live at --batch 1); --batches still counts
        leases, and the other kinds keep 20 a call. v10.13.3: a merge lease takes --parallel (4 here), the calls the
        callers start at once, so no merge waits out its lease in the queue."""
        self.stub.add("merge", 7, start=1)
        self.stub.add("read", 25, start=101)
        p = self.run_worker("--kinds", "merge,read", "--parallel", "4", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 32)
        sizes = {}
        for c in self.fake_calls():
            ids = [int(x) for x in __import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)]
            kind = self.stub.tasks[str(ids[0])]["kind"]
            sizes.setdefault(kind, []).append(len(ids))
        self.assertEqual(sizes["merge"], [1] * 7)
        self.assertEqual(sorted(sizes["read"]), [5, 20])
        self.assertEqual([(w["kinds"], w["limit"]) for w in self.stub.works][:1], [("merge", "4")])

    def test_two_windows_of_one_post_are_never_in_one_call(self):
        """0176 (0150 B): a long post's entities windows (the server's "post") are asked in different calls."""
        for k, post in enumerate(("p-a", "p-b", "p-c")):
            self.stub.add("entities", 4, start=100 + 10 * k, post=post)
        self.stub.add("entities", 8, start=1)
        p = self.run_worker("--kinds", "entities", "--parallel", "1", "--batches", "5")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        for c in self.fake_calls():
            ids = [x for x in __import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)]
            posts = [self.stub.tasks[i].get("post") for i in ids if self.stub.tasks[i].get("post")]
            self.assertEqual(len(posts), len(set(posts)), posts)
        self.assertEqual(len(self.fake_calls()), 4)                    # 4 windows of a post: 4 calls, no more

    def test_split_calls_keeps_order_and_size(self):
        ts = [{"id": 1, "post": "a"}, {"id": 2, "post": "a"}, {"id": 3}, {"id": 4, "post": "b"}, {"id": 5, "post": "a"}]
        self.assertEqual([[t["id"] for t in c] for c in W.split_calls(ts, 3)], [[1, 3, 4], [2], [5]])
        self.assertEqual([[t["id"] for t in c] for c in W.split_calls([{"id": k} for k in range(5)], 2)],
                         [[0, 1], [2, 3], [4]])

    def test_per_call_sets_a_kinds_call_size(self):
        self.stub.add("merge", 7)
        p = self.run_worker("--kinds", "merge", "--per-call", "merge=3")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(sorted(c["stdin"].count("### ITEM id:") for c in self.fake_calls()), [1, 3, 3])
        for bad in ("merge", "merge=0", "merge=x", "=2"):
            self.assertEqual(self.run_worker("--kinds", "merge", "--per-call", bad).returncode, 2, bad)

    def test_batches_caps_the_leases(self):
        self.stub.add("read", 100)
        p = self.run_worker("--kinds", "read", "--batches", "2")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 40)
        self.assertEqual(len(self.stub.by_status("open")), 60)
        self.assertEqual(len(self.stub.works), 2)

    def test_string_ids_fenced_and_nested_lines(self):
        ids = [f"6f1c2b9e-0000-4000-8000-{k:012d}" for k in range(5)]
        self.stub.add("read", 5, ids=ids)
        p = self.run_worker("--kinds", "read", plan="fence+nested")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.stub.by_status("answered"), sorted(ids))
        self.assertEqual({c["answer"]["kind"] for c in self.stub.calls}, {"news"})

    def test_nothing_to_do(self):
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.fake_calls(), [])
        self.assertEqual(self.stub.posts, [])


class TestRetry(Base):
    def test_invalid_then_retried(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", plan="invalid:2,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.fake_calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["stdin"].count("### ITEM id:"), 2)
        self.assertIn("### ITEM id: 1\n", calls[1]["stdin"])
        self.assertIn("### ITEM id: 2\n", calls[1]["stdin"])
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        # the first try's invalid lines are not posted (the lease is kept for the retry)
        self.assertEqual(len(self.stub.calls), 20)
        self.assertTrue(all(c["valid"] for c in self.stub.calls))
        # a retried task carries its share of both calls
        retried = [c for c in self.stub.calls if c["task_id"] in (1, 2)]
        self.assertEqual({c["tokens_out"] for c in retried}, {80})
        first = self.events("call")[0]
        self.assertEqual((first["ok"], first["invalid"], first["missing"]), (18, 2, 0))

    def test_still_invalid_after_the_retry_is_posted_with_its_error(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", plan="invalid:1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.fake_calls()), 2)            # one retry, not more
        bad = [c for c in self.stub.calls if not c["valid"]]
        self.assertEqual([c["task_id"] for c in bad], [1])
        self.assertEqual(self.stub.tasks["1"]["status"], "open")
        self.assertEqual(self.stub.tasks["1"]["attempts"], 1)
        self.assertEqual(len(self.stub.by_status("answered")), 19)

    def test_missing_lines_retried(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", plan="missing:3,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.fake_calls()
        self.assertEqual([c["stdin"].count("### ITEM id:") for c in calls], [20, 3])
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        self.assertEqual(self.stub.releases, [])

    def test_missing_after_the_retry_is_released(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", plan="missing:3,missing:1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 19)
        self.assertEqual(self.stub.by_status("open"), [20])
        self.assertEqual(self.stub.releases, [{"worker": "test-device", "task_ids": [20]}])
        self.assertEqual(self.stub.tasks["20"]["attempts"], 0)

    def test_retries_combine_into_batches_of_one_kind(self):
        self.stub.add("read", 60)
        p = self.run_worker("--kinds", "read", plan="missing:2,missing:2,missing:2,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 60)
        self.assertEqual(sorted(c["stdin"].count("### ITEM id:") for c in self.fake_calls()), [2, 2, 2, 20, 20, 20])

    def test_no_retry_flag(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", "--no-retry", plan="missing:3")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.fake_calls()), 1)
        self.assertEqual(len(self.stub.by_status("open")), 3)

    def test_server_invalid_is_left_to_the_server(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", plan="serverbad:1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.fake_calls()), 1)
        self.assertEqual(self.stub.tasks["1"]["status"], "open")
        self.assertEqual(self.stub.tasks["1"]["attempts"], 1)
        ev = self.events("server-invalid")
        self.assertEqual([e["task"] for e in ev], [1])
        self.assertEqual(self.done()["server_invalid"], 1)

    def test_a_non_fatal_call_error_releases_and_goes_on(self):
        self.stub.add("read", 40)
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="error,error,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        # batch 1 fails twice (call and retry), batch 2 answers
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        self.assertEqual(len(self.stub.by_status("open")), 20)
        self.assertEqual(len(self.stub.releases), 1)

    def test_a_refused_batch_is_halved_until_the_refused_post_stands_alone(self):
        # 2026-11-08: Haiku refused whole batches of 20 for one post ("can't help with this"); the 20 were released
        # and leased again every round. The retry halves a refused batch; a single refused task is posted as an
        # empty answer, which the server stores as a failed try (three and it fails), so the other 19 are answered.
        self.stub.add("read", 20)
        self.stub.tasks["7"]["input"] += " FORBIDDEN"
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="refuse:FORBIDDEN")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 19)
        self.assertGreaterEqual(self.stub.tasks["7"]["attempts"], 1, "the refused one: a failed try a lease")
        self.assertIn(self.stub.tasks["7"]["status"], ("open", "failed"))
        self.assertEqual(len(self.stub.by_status("open")) + len(self.stub.by_status("failed")), 1, "only it is left")

    def test_unparsable_output(self):
        self.stub.add("read", 5)
        p = self.run_worker("--kinds", "read", plan="garbage")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("open")), 5)
        self.assertIn("unparsable", self.events("call")[0]["error"])


class TestStops(Base):
    def test_usage_limit_releases_and_exits_non_zero(self):
        self.stub.add("read", 60)
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="valid,usage")
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertEqual(len(self.fake_calls()), 2)              # no call after the limit
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        self.assertEqual(self.stub.by_status("leased"), [])
        self.assertEqual(self.stub.releases[-1], {"worker": "test-device"})
        self.assertEqual(self.done()["stopped"], "usage")
        self.assertIn("usage limit", self.done()["why"])

    def test_usage_limit_with_calls_in_flight(self):
        self.stub.add("read", 60)
        p = self.run_worker("--kinds", "read", plan="usage,valid,valid")
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertEqual(len(self.fake_calls()), 3)              # the three already started finish
        self.assertEqual(len(self.stub.by_status("answered")), 40)
        self.assertEqual(self.stub.by_status("leased"), [])
        # nothing leased after it: v10.13.3's leaser runs ahead of the calls, so it may have asked once more,
        # and found nothing (the 60 were leased); every task is answered or released
        self.assertLessEqual(len(self.stub.works), 4)
        self.assertEqual(self.stub.picked[:3], [20, 20, 20])
        self.assertEqual(sum(self.stub.picked[3:]), 0)

    def test_auth_error(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", plan="auth")
        self.assertEqual(p.returncode, 5, p.stderr)
        self.assertEqual(len(self.fake_calls()), 1)              # no retry
        self.assertEqual(self.stub.by_status("leased"), [])
        self.assertEqual(self.stub.releases, [{"worker": "test-device"}])

    def test_auth_error_without_json(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", plan="authraw")
        self.assertEqual(p.returncode, 5, p.stderr)
        self.assertEqual(self.stub.by_status("leased"), [])

    def test_claude_not_found(self):
        self.stub.add("read", 3)
        p = self.run_worker("--kinds", "read", "--claude", str(self.tmp / "no-such-claude"))
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertEqual(self.stub.by_status("leased"), [])


class TestLeases(Base):
    def test_no_call_on_a_lease_about_to_end(self):
        self.stub.lease_seconds = 30
        self.stub.add("read", 10)
        p = self.run_worker("--kinds", "read", "--lease-margin", "60")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.fake_calls(), [])
        self.assertEqual(len(self.events("lease-expiring")), 1)
        self.assertEqual(len(self.stub.by_status("open")), 10)
        self.assertEqual(self.stub.posts, [])

    def test_lease_ending_during_the_call(self):
        self.stub.lease_seconds = 2
        self.stub.add("read", 10)
        p = self.run_worker("--kinds", "read", "--lease-margin", "0", plan="sleep:3+missing:2+invalid:1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.fake_calls()), 1)              # no retry on a lost lease
        ev = self.events("call")[0]
        self.assertTrue(ev["late"])
        # the paid-for answers are posted: 7 valid, 1 invalid stored with its error
        self.assertEqual(len(self.stub.calls), 8)
        self.assertEqual(len(self.stub.by_status("answered")), 7)
        self.assertEqual(self.stub.tasks["1"]["last_error"] is not None, True)

    def test_call_timeout(self):
        self.stub.add("read", 4)
        p = self.run_worker("--kinds", "read", "--timeout", "2", "--no-retry", plan="sleep:10")
        self.assertEqual(p.returncode, 0, p.stderr)
        ev = self.events("call")[0]
        self.assertEqual(ev["error"], "timeout")
        self.assertLess(ev["ms"], 8000)
        self.assertEqual(self.stub.posts, [])
        self.assertEqual(len(self.stub.by_status("open")), 4)

    def test_guide_that_does_not_match_its_sha256(self):
        self.stub.guides["read-v2"] = {**GUIDES["read-v2"], "sha256": "0" * 64}
        self.stub.add("read", 5)
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.fake_calls(), [])
        self.assertEqual(len(self.events("guide-sha256-mismatch")), 1)
        self.assertEqual(len(self.stub.by_status("open")), 5)


class TestServer(Base):
    def test_server_unreachable(self):
        p = self.run_worker("--kinds", "read", server=f"http://127.0.0.1:{free_port()}")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(self.fake_calls(), [])
        self.assertIn("/api/markx/work", self.done()["why"])

    def test_each_lease_logs_the_servers_time(self):
        self.stub.add("read", 20)
        self.stub.slow_kinds = set()
        p = self.run_worker("--kinds", "read,entities", "--batches", "2")
        self.assertEqual(p.returncode, 0, p.stderr)
        got = {}
        for e in self.events("leased"):
            got.setdefault(e["kind"], e)                              # each kind's first lease
        self.assertEqual(got["read"]["tasks"], 20)
        self.assertEqual(got["entities"]["tasks"], 0)                 # an empty lease is logged too
        self.assertTrue(all(isinstance(e["ms"], int) and e["ms"] >= 0 for e in got.values()))

    def test_a_lease_of_100_is_asked_in_calls_of_the_batch(self):
        self.stub.add("read", 100)
        p = self.run_worker("--kinds", "read", "--batch", "20", "--lease", "100", "--batches", "1", "--parallel", "5")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([w["limit"] for w in self.stub.works], ["100"])
        self.assertEqual(len(self.fake_calls()), 5)
        self.assertEqual(len(self.stub.by_status("answered")), 100)

    def test_a_slow_call_holds_back_no_other_batch(self):
        """v10.13.3: the pipeline: with 2 callers, while the first call sleeps the other caller asks the rest;
        rounds (before) waited for the slowest call of each round, so two slow calls in two rounds took twice."""
        self.stub.add("read", 80)
        t = time.monotonic()
        p = self.run_worker("--kinds", "read", "--batches", "4", "--parallel", "2", plan="sleep:3,valid,valid,sleep:3")
        took = time.monotonic() - t
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 80)
        self.assertLess(took, 5.5, took)           # rounds: 3 s + 3 s at least; the pipeline: about 3 s

    def test_a_merge_lease_takes_no_more_than_the_callers_start(self):
        self.stub.add("merge", 30)
        p = self.run_worker("--kinds", "merge", "--lease", "100", "--batches", "1", "--parallel", "4")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.stub.works[0]["limit"], "4")       # merge is one a call: 4 callers, 4 tasks

    def test_a_bad_lease_size_is_refused(self):
        for bad in ("0", "-5", "101"):
            p = self.run_worker("--kinds", "read", "--lease", bad)
            self.assertEqual(p.returncode, 2, (bad, p.stderr))
            self.assertIn("--lease", p.stderr)

    def test_a_bug_in_a_batch_stops_the_cycle_with_exit_1(self):
        """v10.13.3: a batch that raises is never swallowed into exit 0; its tasks are released."""
        from unittest import mock
        self.stub.add("read", 40)
        argv = ["cycle", "--server", self.stub.url, "--token-file", str(self.token_file), "--worker", "test-device",
                "--log", str(self.log), "--quiet", "--claude", str(FAKE), "--spool", str(self.spool),
                "--retry-wait", "0", "--kinds", "read", "--parallel", "1"]
        with mock.patch.object(W.Worker, "first", side_effect=RuntimeError("boom")):
            code = W.main(argv)
        self.assertEqual(code, 1)
        self.assertEqual(self.events("bug")[0]["where"], "batch")
        self.assertEqual(self.stub.by_status("leased"), [])     # released

    def test_a_slow_lease_skips_its_kind_and_the_others_go_on(self):
        self.stub.add("read", 20)
        self.stub.add("entities", 5, start=100)
        self.stub.slow_kinds = {"entities"}
        p = self.run_worker("--kinds", "entities,read", "--server-timeout", "0.5")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 20)          # every read answered
        self.assertEqual([e["kind"] for e in self.events("lease-slow")], ["entities"])

    def test_a_kind_the_server_does_not_know_sits_out_and_the_others_go_on(self):
        """v10.14: a worker newer than its server: the unknown kind is skipped, never a stop for every kind."""
        self.stub.add("read", 20)
        self.stub.unknown_kinds = {"rename"}
        p = self.run_worker("--kinds", "rename,read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        self.assertEqual([e["kind"] for e in self.events("kind-unknown")], ["rename"])

    def test_slow_leases_in_a_row_count_as_unreachable(self):
        self.stub.add("read", 5)
        self.stub.slow_kinds = {"read", "entities", "merge"}
        p = self.run_worker("--kinds", "read,entities,merge", "--server-timeout", "0.5")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(len(self.events("lease-slow")), 3)
        self.assertEqual(self.fake_calls(), [])

    def test_post_fails_answers_spooled_then_posted_next_cycle(self):
        self.stub.add("read", 20)
        self.stub.fail_posts = 3
        p = self.run_worker("--kinds", "read", "--post-tries", "3")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(self.stub.posts, [])
        spooled = [json.loads(x) for x in self.spool.read_text().splitlines()]
        self.assertEqual(len(spooled[0]["answers"]), 20)
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        self.assertEqual(len(self.fake_calls()), 1)              # never asked twice
        self.assertEqual(self.spool.read_text().strip(), "")

    def test_post_retried_once_down(self):
        self.stub.add("read", 20)
        self.stub.fail_posts = 1
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        self.assertEqual(len(self.events("post-failed")), 1)

    def test_spool_with_server_still_down(self):
        self.spool.write_text(json.dumps({"worker": "w", "executor": "claude-code", "model": "m",
                                          "answers": [{"task_id": 1, "answer": {}}]}) + "\n")
        p = self.run_worker("--kinds", "read", server=f"http://127.0.0.1:{free_port()}")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(len(self.spool.read_text().splitlines()), 1)
        self.assertEqual(self.fake_calls(), [])

    def test_wrong_token(self):
        self.stub.token = "another"
        self.stub.add("read", 5)
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 6, p.stderr)
        self.assertEqual(self.fake_calls(), [])
        self.assertNotIn(TOKEN, p.stderr + self.log.read_text())

    def test_token_file_missing_or_empty(self):
        self.token_file.unlink()
        self.assertEqual(self.run_worker("--kinds", "read").returncode, 2)
        self.token_file.write_text("\n")
        self.assertEqual(self.run_worker("--kinds", "read").returncode, 2)

    def test_status_and_release(self):
        self.stub.add("read", 5)
        self.stub.work({"kinds": "read", "limit": "3", "worker": "test-device"})
        p = self.run_worker(cmd="status")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {"queue": {"read": {"leased": 3, "open": 2}}})
        p = self.run_worker(cmd="release")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.stub.releases, [{"worker": "test-device"}])
        self.assertEqual(len(self.stub.by_status("open")), 5)


class TestParts(unittest.TestCase):
    def test_parse_lines(self):
        text = 'prose\n```json\n{"id": 7, "kind": "news"}\n{"task_id": "a", "answer": {"kind": "x"}}\n' \
               '{"id": 8, "kind": \n{"kind": "no id"}\n[1, 2]\n```'
        self.assertEqual(W.parse_lines(text), {"7": {"kind": "news"}, "a": {"kind": "x"}})

    def test_schema_subset(self):
        s = {"type": "object", "required": ["a"], "properties": {
            "a": {"type": "array", "maxItems": 2, "items": {"type": "integer", "minimum": 0}},
            "b": {"type": ["string", "null"], "maxLength": 3}, "c": {"anyOf": [{"const": 1}, {"enum": ["x"]}]}}}
        self.assertIsNone(W.schema_error(s, {"a": [0, 1], "b": None, "c": "x"}))
        self.assertIn("a missing", W.schema_error(s, {}))
        self.assertIn("more than 2", W.schema_error(s, {"a": [1, 2, 3]}))
        self.assertIn("below 0", W.schema_error(s, {"a": [-1]}))
        self.assertIn("not integer", W.schema_error(s, {"a": [True]}))
        self.assertIn("longer than 3", W.schema_error(s, {"a": [], "b": "abcd"}))
        self.assertIn("none of anyOf", W.schema_error(s, {"a": [], "c": 2}))
        self.assertEqual(W.check_answer(None, ["x"]), "answer: not an object")
        self.assertIsNone(W.check_answer(None, {"x": 1}))

    def test_shares_add_up(self):
        self.assertEqual(W.shares(10, 3), [4, 3, 3])
        self.assertEqual(sum(W.shares(2401, 20)), 2401)

    def test_classify(self):
        self.assertEqual(W.classify("Claude AI usage limit reached|1762300000"), "usage")
        self.assertEqual(W.classify("You've hit your limit · resets 3pm"), "usage")
        self.assertEqual(W.classify("success: You've hit your weekly limit · resets Nov 15, 3pm (Asia/Tbilisi)"), "usage")
        self.assertIsNone(W.classify("success: API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)"))
        self.assertEqual(W.classify("Invalid API key · Please run /login"), "auth")
        self.assertEqual(W.classify("OAuth token has expired"), "auth")
        self.assertIsNone(W.classify("API Error: 500 Internal server error"))
        self.assertIsNone(W.classify("timeout"))

    def test_lease_times(self):
        self.assertEqual(W.parse_time("2026-11-05T12:00:00Z"), datetime(2026, 11, 5, 12, tzinfo=timezone.utc))
        self.assertEqual(W.parse_time("2026-11-05T12:00:00"), datetime(2026, 11, 5, 12, tzinfo=timezone.utc))


class TestTracks(Base):
    """0145: the track judge and the sub-topic proposal are default kinds, 10 posts a call and one track a call."""

    def setUp(self):
        super().setUp()
        for kind, gid in (("track", "track-v1"), ("subtopics", "subtopics-v2")):
            KIND_GUIDE[kind] = gid
            self.addCleanup(KIND_GUIDE.pop, kind)
            self.stub.guides[gid] = guide(gid, f"GUIDE {gid}")

    def test_track_and_subtopics_are_default_kinds_with_their_call_sizes(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertEqual(kinds[-7:-3], ["track", "subtopics", "subtopic_place", "digest"])   # 0207: + placement, digest
        per = W.per_call_arg(W.PER_CALL)
        self.assertEqual((per["track"], per["subtopics"], per["subtopic_place"], per["digest"]), (10, 1, 1, 1))

    def test_the_track_briefer_kinds_are_default_kinds_with_their_call_sizes(self):
        """0245: a track's schema and a post window's things one a call, five same-claim pairs a call."""
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertEqual(kinds[-3:], ["track_schema", "track_things", "track_same"])
        per = W.per_call_arg(W.PER_CALL)
        self.assertEqual((per["track_schema"], per["track_things"], per["track_same"]), (1, 1, 5))

    def test_the_worker_salvages_a_things_answer_as_the_server_does(self):
        """0245: a value whose number is not in its quote is dropped (kept under "dropped"), the rest stays."""
        kinds = {"kinds": [{"kind": "recipe", "fields": [{"name": "name", "type": "text", "key": True},
                                                        {"name": "time", "type": "number"}]}]}
        text = ("SCHEMA: t v1\nTRACK: T\nBelongs: b\nExcludes: (none)\nKINDS: " + json.dumps(kinds)
                + "\n\nPOST\nTitle: x\nText: A lentil soup that takes 40 minutes.")
        answer = {"things": [{"kind": "recipe", "fields": {
            "name": {"value": "Lentil soup", "quote": "A lentil soup"},
            "time": {"value": {"number": 45, "unit": "minutes"}, "quote": "takes 40 minutes"}}}]}
        got, dropped = W.salvage("track_things", answer, text, "track-things-v1")
        self.assertEqual(dropped, 1)
        self.assertEqual(list(got["things"][0]["fields"]), ["name"])

    def test_tracks_asked_ten_a_call_subtopics_one(self):
        self.stub.add("track", 25, start=1)
        self.stub.add("subtopics", 2, start=101)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 27)
        sizes = {}
        for c in self.fake_calls():
            ids = [int(x) for x in __import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)]
            sizes.setdefault(self.stub.tasks[str(ids[0])]["kind"], []).append(len(ids))
        self.assertEqual(sorted(sizes["track"]), [5, 10, 10])
        self.assertEqual(sizes["subtopics"], [1, 1])


class TestProbes(Base):
    """0147: a track's example posts (probes-v1) are a default kind, leased before the track judge, one track a call."""

    def setUp(self):
        super().setUp()
        for kind, gid in (("probes", "probes-v1"), ("track", "track-v1")):
            KIND_GUIDE[kind] = gid
            self.addCleanup(KIND_GUIDE.pop, kind)
            self.stub.guides[gid] = guide(gid, f"GUIDE {gid}")

    def test_probes_is_a_default_kind_before_the_judge_one_a_call(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertIn("probes", kinds)
        self.assertLess(kinds.index("probes"), kinds.index("track"))
        self.assertEqual(W.per_call_arg(W.PER_CALL)["probes"], 1)

    def test_probes_asked_one_track_a_call(self):
        self.stub.add("probes", 3, start=1)
        self.stub.add("track", 4, start=101)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 7)
        sizes = {}
        for c in self.fake_calls():
            ids = [int(x) for x in __import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)]
            sizes.setdefault(self.stub.tasks[str(ids[0])]["kind"], []).append(len(ids))
        self.assertEqual(sizes["probes"], [1, 1, 1])
        self.assertEqual(sizes["track"], [4])


class TestRename(Base):
    """0165 B: the rename judge (rename-v1) is a default kind, after the collision judge, five items a call."""

    def setUp(self):
        super().setUp()
        KIND_GUIDE["rename"] = "rename-v1"
        self.addCleanup(KIND_GUIDE.pop, "rename")
        self.stub.guides["rename-v1"] = guide("rename-v1", "GUIDE rename-v1")

    def test_rename_is_a_default_kind_five_a_call(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertIn("rename", kinds)
        self.assertEqual(kinds.index("rename"), kinds.index("collide") + 1)
        self.assertEqual(W.per_call_arg(W.PER_CALL)["rename"], 5)

    def test_renames_asked_five_a_call(self):
        self.stub.add("rename", 7, start=1)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 7)
        sizes = [len(__import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)) for c in self.fake_calls()]
        self.assertEqual(sorted(sizes), [2, 5])


class TestScout(Base):
    """0148: a track's scout question (scout-v1) is a default kind, asked one track a call, before the track judge."""

    def setUp(self):
        super().setUp()
        for kind, gid in (("scout", "scout-v1"), ("track", "track-v1")):
            KIND_GUIDE[kind] = gid
            self.addCleanup(KIND_GUIDE.pop, kind)
            self.stub.guides[gid] = guide(gid, f"GUIDE {gid}")

    def test_scout_is_a_default_kind_one_a_call(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertIn("scout", kinds)
        self.assertLess(kinds.index("scout"), kinds.index("track"))
        self.assertEqual(W.per_call_arg(W.PER_CALL)["scout"], 1)

    def test_scout_asked_one_track_a_call(self):
        self.stub.add("scout", 2, start=1)
        self.stub.add("track", 3, start=101)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 5)
        sizes = {}
        for c in self.fake_calls():
            ids = [int(x) for x in __import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)]
            sizes.setdefault(self.stub.tasks[str(ids[0])]["kind"], []).append(len(ids))
        self.assertEqual(sizes["scout"], [1, 1])
        self.assertEqual(sizes["track"], [3])


class TestIdentity(Base):
    """0162: research's same-maker question (identity-v1) is a default kind, five pairs a call."""

    def setUp(self):
        super().setUp()
        KIND_GUIDE["identity"] = "identity-v1"
        self.addCleanup(KIND_GUIDE.pop, "identity")
        self.stub.guides["identity-v1"] = guide("identity-v1", "GUIDE identity-v1")

    def test_identity_is_a_default_kind_five_a_call(self):
        self.assertIn("identity", W.DEFAULT_KINDS.split(","))
        self.assertEqual(W.per_call_arg(W.PER_CALL)["identity"], 5)

    def test_identity_pairs_asked_five_a_call(self):
        self.stub.add("identity", 7, start=1)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 7)
        sizes = [len(__import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)) for c in self.fake_calls()]
        self.assertEqual(sorted(sizes), [2, 5])


class TestSourceJudge(Base):
    """0173: "Is this worth it?" (source-judge-v1) is a default kind leased first (the owner waits), one candidate a
    call, with no tool."""

    def setUp(self):
        super().setUp()
        KIND_GUIDE["source_judge"] = "source-judge-v1"
        self.addCleanup(KIND_GUIDE.pop, "source_judge")
        self.stub.guides["source-judge-v1"] = guide("source-judge-v1", "GUIDE source-judge-v1")

    def test_source_judge_is_the_first_default_kind_one_a_call(self):
        # 0275: the reader's question first (the search page waits), then the source judge (the owner waits)
        self.assertEqual(W.DEFAULT_KINDS.split(",")[:2], ["question", "source_judge"])
        self.assertEqual(W.per_call_arg(W.PER_CALL)["source_judge"], 1)
        self.assertEqual(W.per_call_arg(W.PER_CALL)["question"], 1)
        argv = W.claude_argv("claude", "haiku", "S", "source_judge")
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_candidates_asked_one_a_call(self):
        self.stub.add("source_judge", 3, start=1)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 3)
        sizes = [len(__import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)) for c in self.fake_calls()]
        self.assertEqual(sizes, [1, 1, 1])


class TestNewsSections(Base):
    """0174: News' sections (news-sections-v1) is a default kind, after the headlines, one question a call (each holds
    every row of the page), with no tool."""

    def setUp(self):
        super().setUp()
        KIND_GUIDE["news_sections"] = "news-sections-v1"
        self.addCleanup(KIND_GUIDE.pop, "news_sections")
        self.stub.guides["news-sections-v1"] = guide("news-sections-v1", "GUIDE news-sections-v1")

    def test_news_sections_is_a_default_kind_after_the_headlines_one_a_call(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertEqual(kinds.index("news_sections"), kinds.index("headline") + 1)
        self.assertEqual(W.per_call_arg(W.PER_CALL)["news_sections"], 1)
        argv = W.claude_argv("claude", "haiku", "S", "news_sections")
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_questions_asked_one_a_call(self):
        self.stub.add("news_sections", 2, start=1)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 2)
        sizes = [len(__import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)) for c in self.fake_calls()]
        self.assertEqual(sizes, [1, 1])


class TestNewsPlace(Base):
    """0197: the new rows' placement (news-place-v1) is a default kind right after News' sections, one question a call,
    with no tool; a server older than the worker (no news_place yet) has it skipped, the others go on."""

    def setUp(self):
        super().setUp()
        KIND_GUIDE["news_place"] = "news-place-v1"
        self.addCleanup(KIND_GUIDE.pop, "news_place")
        self.stub.guides["news-place-v1"] = guide("news-place-v1", "GUIDE news-place-v1")

    def test_news_place_is_a_default_kind_after_the_sections_one_a_call(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertEqual(kinds.index("news_place"), kinds.index("news_sections") + 1)
        self.assertEqual(W.per_call_arg(W.PER_CALL)["news_place"], 1)
        argv = W.claude_argv("claude", "haiku", "S", "news_place")
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_questions_asked_one_a_call(self):
        self.stub.add("news_place", 2, start=1)
        p = self.run_worker("--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 2)
        sizes = [len(__import__("re").findall(r"^### ITEM id: (\d+)$", c["stdin"], 8)) for c in self.fake_calls()]
        self.assertEqual(sizes, [1, 1])

    def test_an_older_server_skips_it(self):
        self.stub.add("read", 5)
        self.stub.unknown_kinds = {"news_place"}
        p = self.run_worker("--kinds", "news_place,read")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 5)
        self.assertEqual([e["kind"] for e in self.events("kind-unknown")], ["news_place"])


WEB_SCHEMA = {"type": "object", "required": ["candidates", "queries"],
              "properties": {"candidates": {"type": "array", "maxItems": 15, "items": {
                  "type": "object", "required": ["url", "why"],
                  "properties": {"url": {"type": "string", "minLength": 8}, "title": {"type": ["string", "null"]},
                                 "why": {"type": "string", "minLength": 1}}}},
                  "queries": {"type": "array", "maxItems": 5, "items": {"type": "string", "minLength": 1}}}}


class TestWebSearch(Base):
    """0171: research's web search (websearch-v1) is asked of this worker: its calls, and only its, get Claude Code's
    web search tool (no fetch, no other tool), allowed without a prompt and their turns capped; one question a call."""

    def setUp(self):
        super().setUp()
        KIND_GUIDE["websearch"] = "websearch-v1"
        self.addCleanup(KIND_GUIDE.pop, "websearch")
        self.stub.guides["websearch-v1"] = {**guide("websearch-v1", "GUIDE websearch-v1"), "schema": WEB_SCHEMA}
        plain = self.stub.check
        self.stub.check = lambda a: (W.schema_error(WEB_SCHEMA, a) if isinstance(a, dict) and "candidates" in a
                                     else plain(a))

    def test_websearch_is_a_default_kind_one_a_call(self):
        self.assertIn("websearch", W.DEFAULT_KINDS.split(","))
        self.assertEqual(W.per_call_arg(W.PER_CALL)["websearch"], 1)

    def test_only_the_websearch_kind_gets_the_web_search_tool(self):
        web = W.claude_argv("claude", "haiku", "S", "websearch")
        self.assertEqual(web[web.index("--tools") + 1], "WebSearch")
        self.assertEqual(web[web.index("--allowedTools") + 1], "WebSearch")
        self.assertEqual(web[web.index("--max-turns") + 1], str(W.WEB_MAX_TURNS))
        self.assertNotIn("WebFetch", " ".join(web))
        for kind in [k for k in W.DEFAULT_KINDS.split(",") if k != "websearch"] + [None]:
            with self.subTest(kind=kind):
                argv = W.claude_argv("claude", "haiku", "S", kind)
                self.assertEqual(argv[argv.index("--tools") + 1], "")
                self.assertNotIn("--allowedTools", argv)
                self.assertNotIn("WebSearch", argv)

    def test_a_websearch_cycle_answers_with_candidates_and_the_tool_only_there(self):
        self.stub.add("websearch", 2, start=1)
        self.stub.add("read", 3, start=10)
        p = self.run_worker("--kinds", "websearch,read", "--parallel", "1", "--batches", "10")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.stub.by_status("answered")), 5)
        calls = self.fake_calls()
        web = [c for c in calls if "GUIDE websearch-v1" in c["system"]]
        other = [c for c in calls if "GUIDE websearch-v1" not in c["system"]]
        self.assertEqual(len(web), 2)                                       # one question a call
        for c in web:
            self.assertEqual(c["stdin"].count("### ITEM id:"), 1)
            self.assertEqual(c["argv"][3:5], ["--tools", "WebSearch"])
            self.assertEqual(c["argv"][-4:], ["--allowedTools", "WebSearch", "--max-turns", "8"])
        self.assertTrue(other)
        for c in other:
            self.assertEqual(c["argv"][3:5], ["--tools", ""])
            self.assertNotIn("--allowedTools", c["argv"])
        posted = [a for a in self.stub.calls if str(a["task_id"]) in ("1", "2")]
        self.assertTrue(all(a["valid"] for a in posted))
        self.assertEqual(posted[0]["answer"]["candidates"][0]["why"], "the result names the product")

    def test_an_answer_the_schema_refuses_is_asked_once_more(self):
        self.stub.add("websearch", 1, start=1)
        p = self.run_worker("--kinds", "websearch", plan="invalid:1,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.stub.by_status("answered"), [1])
        self.assertEqual(len(self.fake_calls()), 2)


class TestCost0191(Base):
    """0191: thinking effort by kind, the prompt cache, refusals isolated at once and remembered, and the server's
    own answer checks run by the worker so a refused answer is asked again in the same cycle."""

    def setUp(self):
        super().setUp()
        GUIDES.setdefault("cite-v1", {"sha256": hashlib.sha256(b"GUIDE cite-v1").hexdigest(), "body": "GUIDE cite-v1",
                                      "schema": None})
        KIND_GUIDE.setdefault("cite", "cite-v1")

    def test_each_kind_asked_at_its_effort_and_effort_overrides_it(self):
        self.stub.add("entities", 3)
        self.stub.add("read", 3, start=101)
        p = self.run_worker("--kinds", "entities,read", "--parallel", "1")
        self.assertEqual(p.returncode, 0, p.stderr)
        want = W.effort_arg(W.EFFORT)
        for c in self.fake_calls():
            kind = "entities" if "GUIDE ent-v3" in c["system"] else "read"
            self.assertEqual(c["effort"], None if want.get(kind) in (None, "default") else want[kind], kind)
        self.fake_log.unlink()
        self.stub.add("read", 2, start=201)
        p = self.run_worker("--kinds", "read", "--effort", "read=low")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([c["effort"] for c in self.fake_calls()], ["low"])
        self.assertEqual([e["effort"] for e in self.events("call")][-1], "low")

    def test_a_bad_effort_is_refused(self):
        p = self.run_worker("--kinds", "read", "--effort", "read=extreme")
        self.assertEqual(p.returncode, 2)

    def test_the_prompt_cache_setting_goes_to_claude_codes_environment(self):
        self.stub.add("read", 2)
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        modes = W.cache_arg(W.DEFAULT_PROMPT_CACHE)
        self.assertEqual(self.fake_calls()[0]["cache_env"], W.PROMPT_CACHE[modes.get("read", modes["*"])])
        for mode in ("off", "default"):
            self.fake_log.unlink()
            self.stub.add("read", 1, start=10 if mode == "off" else 20)
            p = self.run_worker("--kinds", "read", "--prompt-cache", mode)
            self.assertEqual(p.returncode, 0, p.stderr)
            env = self.fake_calls()[0]["cache_env"]
            self.assertEqual(env.get("DISABLE_PROMPT_CACHING"), "1" if mode == "off" else None, mode)

    def test_the_prompt_cache_by_kind(self):
        self.assertEqual(W.cache_arg("off,relate=default"), {"*": "off", "relate": "default"})
        self.assertEqual(W.cache_arg("relate=5m"), {"*": "default", "relate": "5m"})
        for bad in ("forever", "relate=forever", "=off"):
            with self.assertRaises(W.argparse.ArgumentTypeError):
                W.cache_arg(bad)
        self.stub.add("read", 1)
        self.stub.add("entities", 1, start=2)
        p = self.run_worker("--kinds", "read,entities", "--prompt-cache", "off,entities=default", "--parallel", "1")
        self.assertEqual(p.returncode, 0, p.stderr)
        got = {("ent" if "GUIDE ent-v3" in c["system"] else "read"): c["cache_env"] for c in self.fake_calls()}
        self.assertEqual(got, {"read": {"DISABLE_PROMPT_CACHING": "1"}, "ent": {}})

    def test_under_the_5_minute_cache_a_kinds_first_call_goes_alone(self):
        # four merges, one a call, four callers: the first call alone (it writes the guide), then the other three at once
        self.stub.add("merge", 4)
        p = self.run_worker("--kinds", "merge", "--parallel", "4", "--prompt-cache", "off,merge=5m",
                            plan="valid+sleep:0.4")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.fake_calls()
        self.assertEqual(len(calls), 4)
        self.assertEqual({c["cache_env"].get("CLAUDE_CODE_PROMPT_CACHE_TTL") for c in calls}, {"5m"})
        self.assertEqual(len(self.stub.by_status("answered")), 4)
        starts = sorted(c["t"] for c in calls)   # the first call returned (0.4 s) before any other started
        self.assertGreaterEqual(starts[1] - starts[0], 0.35, starts)
        self.assertLess(starts[3] - starts[1], 0.35, starts)   # then the other three at once

    def test_a_calls_cache_and_thinking_tokens_are_logged(self):
        self.stub.add("read", 4)
        p = self.run_worker("--kinds", "read")
        self.assertEqual(p.returncode, 0, p.stderr)
        e = self.events("call")[0]
        self.assertEqual((e["cache_read"], e["cache_write"], e["thinking"]), (2000, 300, 40))

    def test_a_first_refusal_is_halved_at_once_and_the_refused_task_asked_alone_next_time(self):
        self.stub.add("read", 20)
        self.stub.tasks["7"]["input"] += " FORBIDDEN"
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="refuse:FORBIDDEN")
        self.assertEqual(p.returncode, 0, p.stderr)
        sizes = [len(re.findall(r"^### ITEM id: ", c["stdin"], re.M)) for c in self.fake_calls()]
        self.assertEqual(sizes.count(20), 1, f"the refused batch of 20 is never asked whole again: {sizes}")
        self.assertLessEqual(len(sizes), 1 + 2 * 5, sizes)
        self.assertEqual(len(self.stub.by_status("answered")), 19)
        refused = self.events("refused")
        self.assertEqual([e["task"] for e in refused], [7])
        self.assertEqual(refused[0]["platform"], None)   # the stub's input has no "Platform: " line
        kept = json.loads((self.tmp / "refused.json").read_text())
        self.assertEqual(list(kept["tasks"]), ["7"])
        # the next cycle: task 7 again, with 19 new ones: 7 is asked alone, the 19 in one call
        self.fake_log.unlink()
        self.stub.add("read", 19, start=101)
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="refuse:FORBIDDEN")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = [re.findall(r"^### ITEM id: (\S+)$", c["stdin"], re.M) for c in self.fake_calls()]
        self.assertEqual(sorted(len(c) for c in calls), [1, 19], calls)
        self.assertIn(["7"], calls)
        self.assertTrue(self.events("refused")[-1]["again"])

    def test_an_answer_the_servers_checks_refuse_is_asked_again_in_the_same_cycle(self):
        self.stub.add("cite", 5)
        p = self.run_worker("--kinds", "cite", plan="spanbad:2,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.events("call")
        self.assertEqual([(e["attempt"], e["size"], e["rule_invalid"]) for e in calls], [(1, 5, 2), (2, 2, None)])
        self.assertIn("does not occur in the post", calls[0]["invalid_errors"][0])
        self.assertEqual(self.done()["rule_invalid"], 2)
        # --no-server-rules: the schema alone (none here), nothing asked again
        self.fake_log.unlink()
        self.stub.add("cite", 5, start=11)
        p = self.run_worker("--kinds", "cite", "--no-server-rules", plan="spanbad:2,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.fake_calls()), 1)

    def test_v1020_one_bad_entry_is_dropped_and_the_answer_posted_once(self):
        self.stub.add("cite", 5)
        p = self.run_worker("--kinds", "cite", plan="spanhalf:2")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.events("call")
        self.assertEqual([(e["attempt"], e["size"], e["ok"], e["dropped"]) for e in calls], [(1, 5, 5, 2)])
        posted = [a for payload in self.stub.posts for a in payload["answers"]]
        self.assertEqual(len(posted), 5)
        salvaged = [a["answer"] for a in posted if a["answer"].get("dropped")]
        self.assertEqual(len(salvaged), 2)
        for a in salvaged:   # the good entry stored, the bad one kept under "dropped" with why
            self.assertEqual([e["name"] for e in a["entities"]], ["A study"])
            self.assertEqual(a["dropped"][0]["item"]["name"], "A report")
            self.assertIn("does not occur in the post", a["dropped"][0]["why"])

    def test_v1020_salvage_is_the_servers(self):
        answer = {"entities": [{"span": "Acme", "name": "Acme", "type": "org", "role": "subject"},
                               {"span": "Nowhere Inc", "name": "Nowhere", "type": "org", "role": "mention"}]}
        out, n = W.salvage("entities", answer, "Title: Acme ships")
        self.assertEqual((n, [e["name"] for e in out["entities"]]), (1, ["Acme"]))
        self.assertIsNone(W.salvage_refused("entities", out))
        lost, _ = W.salvage("entities", {"entities": [dict(answer["entities"][1], role="subject")]}, "Title: Acme")
        self.assertIn("every entity was dropped", W.salvage_refused("entities", lost))
        self.assertEqual(W.salvage("read", {"kind": "news"}, "x"), ({"kind": "news"}, 0))

    def test_rule_error_is_the_servers_check_or_no_opinion(self):
        bad = {"entities": [{"span": "Nowhere Inc", "name": "Nowhere", "type": "org", "role": "subject"}]}
        good = {"entities": [{"span": "Acme", "name": "Acme", "type": "org", "role": "subject"}]}
        self.assertIn("does not occur in the post", W.rule_error("entities", bad, "Title: Acme ships"))
        self.assertIsNone(W.rule_error("entities", good, "Title: Acme ships"))
        self.assertIsNone(W.rule_error("entities", {"something": "else"}, "Title: Acme"), "unreadable: no opinion")
        self.assertIsNone(W.rule_error("no-such-kind", good, "Title: Acme"))

    def test_the_servers_checks_need_only_the_standard_library(self):
        # one source of truth: the worker imports the server's validate.py, so it must stay standard library only
        # (back's and subtopics' checks import more lazily; the worker has no opinion on those)
        backend = HERE.parent.parent / "backend"
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from insight_core.markx import validate, schemas; "
                "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('psycopg', 'fastapi', 'pydantic', 'numpy'));"
                "print(bad); sys.exit(1 if bad else 0)")
        p = subprocess.run([sys.executable, "-I", "-c", code, str(backend)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class TestChain0219(unittest.TestCase):
    """0219: the story chain question, asked as it was measured (Haiku, effort low, 10 a call), after relate; the
    server's rules accept a reason and refuse an empty one or a successor (identity's, never the judge's)."""

    def test_the_chain_kind_is_asked_with_the_measured_settings(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertEqual(kinds.index("chain"), kinds.index("relate") + 1)
        self.assertEqual(W.per_call_arg(W.PER_CALL)["chain"], 10)
        self.assertEqual(W.effort_arg(W.EFFORT)["chain"], "low")

    def test_the_answer_passes_the_workers_checks(self):
        rules = W.server_rules()
        schema = rules.schemas.CHAIN_SCHEMA
        ok = {"reason": "The launch, then its weights a week later.", "relation": "same_release", "confidence": 80}
        self.assertIsNone(W.check_answer(schema, ok))
        self.assertIsNone(W.rule_error("chain", ok, "THING: x", "chain-v1"))
        self.assertIsNotNone(W.check_answer(schema, dict(ok, relation="next_version")))
        self.assertIn("reason", W.rule_error("chain", dict(ok, reason="  "), "THING: x", "chain-v1") or "")


class TestJudgeQuotes0258(unittest.TestCase):
    """0258 (v10.30): join and pair ask judge-read-v2, whose answer quotes the POST; the worker refuses, as the server
    does, an answer whose quote is not in its own question's POST (one written from another question of its batch),
    and asks it again in the same cycle."""

    TEXT = ("STORY\nHeadline: Cursor adds Fable 5.2\nMembers (earliest first):\n"
            "- [Example Dev News, x] Cursor adds Fable 5.2 — Cursor added Claude Fable 5.2, scoring 56.9% on CursorBench"
            "\n\nPOST\nPlatform: telegram | Source: Example Physics\nTitle: Black holes\n"
            "Text: In 1983, physicists showed that black holes form very abruptly.\n"
            "Reading of the post: kind=commentary, events=one, main=Physics result; mentions=")

    def test_the_answer_passes_the_workers_checks(self):
        rules = W.server_rules()
        schema = rules.schemas.schema_for("pair", "judge-read-v2")
        ok = {"relation": "different", "confidence": 90, "post_quote": "black holes form very abruptly",
              "reason": "A physics result, not the model's release."}
        self.assertIsNone(W.check_answer(schema, ok))
        self.assertIsNone(W.rule_error("pair", ok, self.TEXT, "judge-read-v2"))
        cross = dict(ok, relation="same_event", post_quote="Cursor added Claude Fable 5.2, scoring 56.9% on CursorBench")
        self.assertIn("not in this question's POST", W.rule_error("pair", cross, self.TEXT, "judge-read-v2") or "")
        self.assertIn("not in this question's POST", W.rule_error("join", cross, self.TEXT, "judge-read-v2") or "")
        self.assertIsNotNone(W.check_answer(schema, {"relation": "different", "confidence": 90}))   # no quote
        v1 = {"relation": "same_event", "confidence": 90}
        self.assertIsNone(W.check_answer(rules.schemas.schema_for("pair", "judge-read-v1"), v1))
        self.assertIsNone(W.rule_error("pair", v1, self.TEXT, "judge-read-v1"))   # v1's open tasks: as before


class TestCollideMakers0250(unittest.TestCase):
    """0250 (v10.28): two maker groups of one bare name, the collide kind's guide collide-makers-v1: the worker checks
    it by its own schema and the server's guide check (a verdict of three, its evidence never empty), not collide-v1's
    senses."""

    def test_the_answer_passes_the_workers_checks(self):
        rules = W.server_rules()
        schema = rules.schemas.schema_for("collide", "collide-makers-v1")
        text = 'NAME "Vexa" (5 posts; two groups)\nA makers: ["Kestrel"] (3 mentions) | types: software 3'
        ok = {"evidence": "A: a code tool; B: the same tool after its sale", "verdict": "same", "why": "owner_change",
              "confidence": 0.8}
        self.assertIsNone(W.check_answer(schema, ok))
        self.assertIsNone(W.rule_error("collide", ok, text, "collide-makers-v1"))
        self.assertIsNotNone(W.check_answer(schema, dict(ok, verdict="maybe")))
        self.assertIn("evidence", W.rule_error("collide", dict(ok, evidence=" "), text, "collide-makers-v1") or "")


class TestDerive0234(unittest.TestCase):
    """0234: the based_on check (a thing and its predecessor in one post), asked as it was measured (Haiku, effort low,
    10 a call), after chain; the server's rules accept a reason and a relation of its four, refuse an empty reason."""

    def test_the_derive_kind_is_asked_with_the_measured_settings(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertEqual(kinds.index("derive"), kinds.index("chain") + 1)
        self.assertEqual(W.per_call_arg(W.PER_CALL)["derive"], 10)
        self.assertEqual(W.effort_arg(W.EFFORT)["derive"], "low")

    def test_the_answer_passes_the_workers_checks(self):
        rules = W.server_rules()
        schema = rules.schemas.DERIVE_SCHEMA
        ok = {"reason": "The post says A is a fine-tune of B.", "relation": "derived", "confidence": 90}
        self.assertIsNone(W.check_answer(schema, ok))
        self.assertIsNone(W.rule_error("derive", ok, "A: x", "derive-v1"))
        self.assertIsNotNone(W.check_answer(schema, dict(ok, relation="based_on")))
        self.assertIn("reason", W.rule_error("derive", dict(ok, reason="  "), "A: x", "derive-v1") or "")


class TestReading0212(unittest.TestCase):
    """0212: ent-v5's kind `reading`, asked with the settings it was measured at (d7), checked by the server's rules."""
    WINDOW = ("Platform: site | Source: Example\nTitle: T\nWindow: 2 of 3 of the post's text (characters 5,801-11,800 "
              "of 15,000)\nText: […] Later the Kestrel Lab answered.")

    def test_the_reading_kind_is_asked_with_the_measured_settings(self):
        self.assertIn("reading", W.DEFAULT_KINDS.split(","))
        self.assertEqual(W.per_call_arg(W.PER_CALL)["reading"], 20)
        self.assertEqual(W.effort_arg(W.EFFORT)["reading"], "low")

    def test_a_later_windows_answer_without_a_reading_passes_the_workers_checks(self):
        rules = W.server_rules()
        schema = rules.schemas.READING_V5_SCHEMA
        answer = {"entities": [{"span": "Kestrel Lab", "name": "Kestrel Lab", "type": "org", "role": "mention"}]}
        out, dropped = W.salvage("reading", answer, self.WINDOW, "ent-v5")
        self.assertEqual((out["reading"], out["event"], dropped), (None, None, 0))
        self.assertIsNone(W.check_answer(schema, out))
        self.assertIsNone(W.salvage_refused("reading", out))
        self.assertIsNone(W.rule_error("reading", out, self.WINDOW, "ent-v5"))
        first = "Platform: site | Source: Example\nTitle: Kestrel Lab answered"
        self.assertIn("reading is null", W.rule_error("reading", dict(out, reading=None), first, "ent-v5"))


class TestLogRotation(unittest.TestCase):
    """v10.17: the JSON-lines log rotates by size and keeps a few old files; every line lands in one of them."""

    def test_rotates_and_keeps(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "log.jsonl"
            log = W.Log(str(path), quiet=True, max_bytes=300, keep=2)
            for i in range(40):
                log("tick", n=i)
            files = sorted(p.name for p in Path(d).iterdir() if not p.name.endswith(".lock"))
            self.assertEqual(files, ["log.jsonl", "log.jsonl.1", "log.jsonl.2"])
            for name in files:
                self.assertLessEqual((Path(d) / name).stat().st_size, 300 + 100)
                for line in (Path(d) / name).read_text().splitlines():
                    self.assertEqual(json.loads(line)["event"], "tick")
            last = [json.loads(x)["n"] for x in path.read_text().splitlines()]
            self.assertEqual(last[-1], 39)

    def test_two_writers_lose_no_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "log.jsonl"
            logs = [W.Log(str(path), quiet=True, max_bytes=10_000_000) for _ in range(2)]
            threads = [threading.Thread(target=lambda lg=lg, k=k: [lg("w", k=k, n=i) for i in range(200)])
                       for k, lg in enumerate(logs)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            lines = [json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(len(lines), 400)


class Test0214(Base):
    """0214: missing lines asked again halved at once, other output shapes read, the unreachable API waited out then a
    stop (exit 3), the output of a call with missing lines logged, the weekly limit a stop within one round."""

    def sizes(self):
        return [len(re.findall(r"^### ITEM id: ", c["stdin"], re.M)) for c in self.fake_calls()]

    def ids(self):
        return [re.findall(r"^### ITEM id: (\S+)$", c["stdin"], re.M) for c in self.fake_calls()]

    def test_missing_lines_asked_again_in_calls_of_half_never_with_the_answered(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="missing:12,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.sizes(), [20, 10, 2])                     # the 12 missing: calls of at most ceil(20/2)
        self.assertTrue(all(int(i) > 8 for c in self.ids()[1:] for i in c), "only the missing are asked again")
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        self.assertEqual(len(self.stub.calls), 20)                      # the first 8 posted once, never asked again
        self.assertEqual(self.stub.releases, [])
        first = self.events("call")[0]
        self.assertEqual((first["ok"], first["missing"]), (8, 12))
        self.assertIn('{"id": 1, "kind": "news"', first["missing_text"])  # the output kept, to count why
        self.assertIsNone(self.events("call")[1]["missing_text"])          # a complete call keeps none

    def test_missing_text_is_the_first_4000_characters(self):
        self.stub.add("read", 100)
        self.stub.tasks["100"]["input"] += " SKIP"
        p = self.run_worker("--kinds", "read", "--parallel", "1", "--batch", "100", plan="skip:SKIP")
        self.assertEqual(p.returncode, 0, p.stderr)
        first = self.events("call")[0]
        self.assertEqual((first["size"], first["missing"]), (100, 1))
        self.assertEqual(len(first["missing_text"]), W.MISSING_TEXT)   # the output is longer; its start is kept
        self.assertTrue(first["missing_text"].startswith('{"id": 1, '))

    def test_a_task_still_missing_after_its_call_alone_is_released(self):
        self.stub.add("read", 20)
        for tid in ("5", "6"):
            self.stub.tasks[tid]["input"] += " SKIP"
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="skip:SKIP")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.ids(), [[str(i) for i in range(1, 21)], ["5", "6"], ["5"], ["6"]])
        self.assertEqual(len(self.stub.by_status("answered")), 18)
        self.assertEqual(self.stub.releases, [{"worker": "test-device", "task_ids": [5, 6]}])
        self.assertEqual((self.stub.tasks["5"]["attempts"], self.stub.tasks["6"]["attempts"]), (0, 0))

    def test_missing_ones_are_halved_down_to_one_task_a_call(self):
        self.stub.add("read", 20)
        skipped = {str(i) for i in (2, 4, 6, 8, 10, 12, 14)}
        for tid in skipped:
            self.stub.tasks[tid]["input"] += " SKIP"
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="skip:SKIP")
        self.assertEqual(p.returncode, 0, p.stderr)
        # 20 -> the 7 (at most 10) -> 4, 3 -> 2, 2, 2, 1 -> 1 each: every one asked alone exactly once
        self.assertEqual(sorted(self.sizes()), sorted([20, 7, 4, 2, 1, 1, 2, 1, 1, 3, 2, 1, 1, 1]))
        alone = [c[0] for c in self.ids() if len(c) == 1]
        self.assertEqual(sorted(alone), sorted(skipped))
        self.assertTrue(all(set(c) <= skipped for c in self.ids()[1:]))
        self.assertEqual(sorted(map(str, self.stub.by_status("open"))), sorted(skipped))
        self.assertEqual(len(self.stub.by_status("answered")), 13)

    def test_an_output_with_no_readable_line_is_asked_again_halved(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", "--parallel", "1", plan="prose,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.sizes(), [20, 10, 10])
        self.assertEqual(len(self.stub.by_status("answered")), 20)
        first = self.events("call")[0]
        self.assertEqual(first["missing"], 20)
        self.assertTrue(first["missing_text"].startswith("I read the items"))

    def test_an_array_or_an_object_keyed_by_id_is_read(self):
        for n, plan in enumerate(("array", "keyed", "array+fence", "keyed+fence")):
            self.stub.add("read", 20, start=100 * (n + 1))
            if self.fake_log.exists():
                self.fake_log.unlink()
            p = self.run_worker("--kinds", "read", plan=plan)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(self.sizes(), [20], plan)
            self.assertEqual(len(self.stub.by_status("answered")), 20 * (n + 1), plan)

    def test_parse_lines_reads_the_other_shapes(self):
        arr = '[\n  {"id": 1, "kind": "news"},\n  {"task_id": "b", "answer": {"kind": "x"}},\n  {"no": "id"},\n  3\n]'
        self.assertEqual(W.parse_lines(arr), {"1": {"kind": "news"}, "b": {"kind": "x"}})
        self.assertEqual(W.parse_lines("Here:\n```json\n" + arr + "\n```\nDone."), {"1": {"kind": "news"}, "b": {"kind": "x"}})
        keyed = '{\n  "7": {"kind": "news"},\n  "8": {"answer": {"kind": "x"}}\n}'
        self.assertEqual(W.parse_lines(keyed), {"7": {"kind": "news"}, "8": {"kind": "x"}})
        self.assertEqual(W.parse_lines("Sure. " + keyed + " That is all."), {"7": {"kind": "news"}, "8": {"kind": "x"}})
        one = '{\n  "id": 9,\n  "kind": "news"\n}'                          # one answer over several lines
        self.assertEqual(W.parse_lines(one), {"9": {"kind": "news"}})
        # a line read wins over the same id elsewhere; prose is nothing
        self.assertEqual(W.parse_lines('{"id": 1, "kind": "news", "list": [1]}'), {"1": {"kind": "news", "list": [1]}})
        self.assertEqual(W.parse_lines("no answer here"), {})
        self.assertEqual(W.parse_lines('{"kind": "news", "headline": "x"}'), {})   # no id: nothing to match

    def test_unreachable_api_the_same_call_asked_again_after_a_wait(self):
        self.stub.add("read", 20)
        p = self.run_worker("--kinds", "read", "--parallel", "1", "--unreachable-wait", "0.01,0.02,0.04",
                            plan="unreachable,unreachable,valid")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.sizes(), [20, 20, 20])                    # not halved
        self.assertEqual(len(set(c["stdin"] for c in self.fake_calls())), 1)   # the same prompt
        self.assertEqual([e["attempt"] for e in self.events("call")], [1, 1, 1])   # not an attempt
        self.assertEqual([e["unreachable"] for e in self.events("call")], [True, True, None])
        self.assertEqual([(e["run"], e["wait"]) for e in self.events("unreachable")], [(1, 0.01), (2, 0.02)])
        self.assertEqual(len(self.stub.by_status("answered")), 20)

    def test_three_unreachable_in_a_row_release_the_leases_and_exit_3(self):
        self.stub.add("read", 60)
        p = self.run_worker("--kinds", "read", "--parallel", "1", "--unreachable-wait", "0.01,0.01,0.01",
                            plan="unreachable")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(self.sizes(), [20, 20, 20])                    # three tries of one call, then no call
        self.assertEqual(self.stub.by_status("leased"), [])
        self.assertEqual(self.stub.releases[-1], {"worker": "test-device"})
        self.assertEqual(self.done()["stopped"], "api")
        self.assertIn("unreachable 3 times in a row", self.done()["why"])
        self.assertTrue(all(t["attempts"] == 0 for t in self.stub.tasks.values()))

    def test_unreachable_results_count_across_calls(self):
        self.stub.add("read", 100)
        p = self.run_worker("--kinds", "read", "--parallel", "3", "--unreachable-wait", "20,20,20",
                            plan="sleep:0.3+unreachable", timeout=30)
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(len(self.fake_calls()), 3)                     # the waits end at the stop; no call after
        self.assertEqual(self.stub.by_status("leased"), [])

    def test_the_weekly_limit_ends_the_cycle_within_one_round_of_calls(self):
        self.assertEqual(W.classify("You've hit your weekly limit · resets Nov 15, 3pm (Asia/Tbilisi)"), "usage")
        self.stub.add("read", 800)
        p = self.run_worker("--kinds", "read", "--parallel", "20", "--batches", "40", plan="sleep:0.5+weekly")
        self.assertEqual(p.returncode, 4, p.stderr)
        self.assertLessEqual(len(self.fake_calls()), 20)                # the calls in flight, none after
        self.assertEqual(self.stub.by_status("leased"), [])
        self.assertEqual(self.stub.releases[-1], {"worker": "test-device"})
        self.assertEqual(self.done()["stopped"], "usage")
        self.assertIn("weekly limit", self.done()["why"])
        self.assertTrue(all(t["attempts"] == 0 for t in self.stub.tasks.values()))


if __name__ == "__main__":
    unittest.main()
