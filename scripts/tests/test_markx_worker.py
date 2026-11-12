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

    def add(self, kind, n, start=1, ids=None):
        for k in range(n):
            tid = ids[k] if ids else start + k
            self.tasks[str(tid)] = {"id": tid, "kind": kind, "guide": KIND_GUIDE[kind], "priority": 0,
                                    "input": f"platform: test\ntitle: post {tid}\ntext: something happened",
                                    "status": "open", "lease_until": None, "leased_by": None, "attempts": 0,
                                    "last_error": None}

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
                    "tasks": [{"id": t["id"], "kind": t["kind"], "guide": t["guide"], "input": t["input"]}
                              for t in pick]}

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
        for kind, gid in (("track", "track-v1"), ("subtopics", "subtopics-v1")):
            KIND_GUIDE[kind] = gid
            self.addCleanup(KIND_GUIDE.pop, kind)
            self.stub.guides[gid] = guide(gid, f"GUIDE {gid}")

    def test_track_and_subtopics_are_default_kinds_with_their_call_sizes(self):
        kinds = W.DEFAULT_KINDS.split(",")
        self.assertEqual(kinds[-2:], ["track", "subtopics"])
        per = W.per_call_arg(W.PER_CALL)
        self.assertEqual((per["track"], per["subtopics"]), (10, 1))

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
        self.assertEqual(W.DEFAULT_KINDS.split(",")[0], "source_judge")
        self.assertEqual(W.per_call_arg(W.PER_CALL)["source_judge"], 1)
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


if __name__ == "__main__":
    unittest.main()
