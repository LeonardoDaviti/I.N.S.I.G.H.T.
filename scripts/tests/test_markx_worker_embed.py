"""Tests for scripts/markx-worker's `embed` kind (0086 B, the build plan's corrections 6) against a stub of
POST /api/markx/embeddings and a fake embedder (a llama-server's /embedding and /props on 127.0.0.1, fixed
vectors from each text's hash). Never the GGUF, never the real `claude`.

    python3 -m unittest discover -s scripts/tests -p 'test_markx_worker_embed.py'
"""
import base64
import hashlib
import json
import math
import struct
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from test_markx_worker import TOKEN, W, Base

GUIDE_BODY = "GUIDE embed-v1: no model reads this guide."
GUIDE = {"sha256": hashlib.sha256(GUIDE_BODY.encode()).hexdigest(), "body": GUIDE_BODY,
         "schema": {"type": "object", "required": ["vector"]}}


def fake_vector(text, n=1024):
    """The fake embedder's vector for a text: fixed, not of length 1 (the worker scales it)."""
    seed = hashlib.sha256(text.encode()).digest()
    return [3.0 * ((seed[k % 32] - 127.5) / 128 + k / 4096) for k in range(n)]


def unpack(b64):
    return list(struct.unpack("<1024e", base64.b64decode(b64)))


class Http:
    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _send(h, code, body):
    raw = json.dumps(body).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(raw)))
    h.end_headers()
    h.wfile.write(raw)


class Embedder(Http):
    """llama-server --embedding --pooling cls, faked: one pooled vector a text ([[...]]), or flat ([...])."""

    def __init__(self, model_path=None, flat=False, dims=1024, refuse="BAD"):
        self.requests, self.model_path, self.flat, self.dims, self.refuse = [], model_path, flat, dims, refuse
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/props":
                    return _send(self, 200, {"model_path": fake.model_path} if fake.model_path else {})
                _send(self, 404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                texts = body["content"]
                fake.requests.append(texts)
                if any(fake.refuse in t for t in texts):
                    return _send(self, 500, {"error": "input is too large"})
                out = []
                for n, t in enumerate(texts):
                    v = fake_vector(t, fake.dims)
                    out.append({"index": n, "embedding": v if fake.flat else [v]})
                _send(self, 200, out)

        super().__init__(H)


class Server(Http):
    """0086 C's /work, /release and S2's /embeddings, in memory."""

    def __init__(self, build=None):
        self.tasks, self.uploads, self.releases, self.stored = {}, [], [], {}
        self.build, self.fail_posts, self.lock = build, 0, threading.Lock()
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return _send(self, 401, {})
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if u.path == "/api/markx/work":
                    return _send(self, 200, srv.work(q))
                _send(self, 404, {})

            def do_POST(self):
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return _send(self, 401, {})
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/api/markx/embeddings":
                    with srv.lock:
                        srv.uploads.append(body)
                        if srv.fail_posts > 0:
                            srv.fail_posts -= 1
                            return _send(self, 503, {"detail": "down"})
                        if srv.build and body["model_sha256"] != srv.build:
                            return _send(self, 409, {"detail": "another build"})
                        srv.build = body["model_sha256"]
                        for v in body["vectors"]:
                            srv.stored[str(v["task_id"])] = v["vector"]
                            srv.tasks[str(v["task_id"])]["status"] = "answered"
                    return _send(self, 200, {"stored": len(body["vectors"]), "invalid": [], "repeated": 0})
                if self.path == "/api/markx/release":
                    with srv.lock:
                        srv.releases.append(body)
                        n = 0
                        for t in srv.tasks.values():
                            if t["status"] == "leased" and t["by"] == body["worker"] and \
                                    ("task_ids" not in body or t["id"] in body["task_ids"]):
                                t["status"], n = "open", n + 1
                    return _send(self, 200, {"released": n})
                _send(self, 404, {})

        super().__init__(H)

    def add(self, n, bad=()):
        for k in range(n):
            tid = f"6f1c2b9e-0000-4000-8000-{len(self.tasks):012d}"
            text = f"Acme released Widget 4.{k}" + (" BAD" if k in bad else "")
            self.tasks[tid] = {"id": tid, "kind": "embed", "guide": "embed-v1", "input": text, "status": "open", "by": None}

    def work(self, q):
        with self.lock:
            pick = [t for t in self.tasks.values() if t["status"] == "open" and t["kind"] in q["kinds"].split(",")]
            pick = pick[:int(q["limit"])]
            for t in pick:
                t["status"], t["by"] = "leased", q["worker"]
            until = datetime.now(timezone.utc) + timedelta(minutes=30)
            return {"lease_until": until.isoformat(), "guides": {"embed-v1": GUIDE} if pick else {},
                    "tasks": [{k: t[k] for k in ("id", "kind", "guide", "input")} for t in pick]}

    def by_status(self, status):
        return sorted(t["id"] for t in self.tasks.values() if t["status"] == status)


class EmbedBase(Base):
    def setUp(self):
        super().setUp()
        self.server = Server()
        self.addCleanup(self.server.close)
        self.gguf = self.tmp / "bge-m3-q8_0.gguf"
        self.gguf.write_bytes(b"GGUF not a model" * 1000)
        self.sha = hashlib.sha256(self.gguf.read_bytes()).hexdigest()
        self.embedder = Embedder(model_path=str(self.gguf))
        self.addCleanup(self.embedder.close)

    def embed(self, *extra, gguf=True, embedder=None):
        args = ["--kinds", "embed", "--batch", "20", "--batches", "10"]
        if embedder is not False:
            args += ["--embedder", embedder or self.embedder.url]
        if gguf:
            args += ["--embedder-gguf", str(self.gguf)]
        return self.run_worker(*args, *extra, server=self.server.url,
                               plan="must-not-run")   # the fake claude: never called for embed

    def run_worker(self, *extra, **kw):
        env_state = {"XDG_STATE_HOME": str(self.tmp / "xdg")}
        import os
        old = {k: os.environ.get(k) for k in env_state}
        os.environ.update(env_state)
        try:
            return super().run_worker(*extra, **kw)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestEmbed(EmbedBase):
    def test_every_task_embedded_scaled_packed_and_posted_with_the_build(self):
        self.server.add(45)
        p = self.embed()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.server.by_status("answered")), 45)
        self.assertEqual(sorted(len(r) for r in self.embedder.requests), [5, 20, 20])
        for up in self.server.uploads:
            self.assertEqual((up["worker"], up["model"], up["model_sha256"]), ("test-device", "bge-m3", self.sha))
        for tid, b64 in self.server.stored.items():
            v = unpack(b64)
            want = fake_vector(self.server.tasks[tid]["input"])
            norm = math.sqrt(sum(x * x for x in want))
            self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0, places=2)
            self.assertTrue(all(abs(a - b / norm) < 1e-3 for a, b in zip(v, want)))
        self.assertEqual(self.fake_calls(), [])
        d = self.done()
        self.assertEqual((d["vectors"], d["exit"]), (45, 0))
        self.assertTrue(all("ms" in v for up in self.server.uploads for v in up["vectors"]))

    def test_the_build_from_props_when_no_gguf_is_given_and_remembered(self):
        self.server.add(3)
        self.assertEqual(self.embed(gguf=False).returncode, 0)
        self.assertEqual(self.server.uploads[0]["model_sha256"], self.sha)
        memo = json.loads((self.tmp / "xdg" / "insight" / "markx-worker" / "gguf-sha256.json").read_text())
        self.assertEqual(list(memo.values()), [self.sha])

    def test_flat_vectors_are_read_too(self):
        flat = Embedder(flat=True)
        self.addCleanup(flat.close)
        self.server.add(2)
        self.assertEqual(self.embed(embedder=flat.url).returncode, 0)
        self.assertEqual(len(self.server.stored), 2)

    def test_a_refused_batch_goes_one_text_at_a_time(self):
        self.server.add(5, bad=(2,))
        p = self.embed()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.server.by_status("answered")), 4)
        self.assertEqual(len(self.server.by_status("open")), 1)            # released at the end of the cycle
        self.assertEqual([len(r) for r in self.embedder.requests], [5, 1, 1, 1, 1, 1])
        self.assertEqual(len(self.events("embed-refused")), 1)


class TestEmbedStops(EmbedBase):
    def test_embed_needs_an_embedder(self):
        self.server.add(3)
        p = self.embed(embedder=False)
        self.assertEqual(p.returncode, W.EXIT_SETUP)
        self.assertEqual(self.server.by_status("open"), sorted(self.server.tasks))

    def test_the_embedder_unreachable_releases_the_leases(self):
        self.server.add(3)
        down = Embedder()
        url = down.url
        down.close()
        p = self.embed(embedder=url)
        self.assertEqual(p.returncode, W.EXIT_SETUP)
        self.assertEqual(len(self.server.by_status("open")), 3)

    def test_wrong_dimensions(self):
        small = Embedder(dims=384)
        self.addCleanup(small.close)
        self.server.add(3)
        p = self.embed(embedder=small.url)
        self.assertEqual(p.returncode, W.EXIT_SETUP)
        self.assertEqual(self.server.uploads, [])
        self.assertEqual(len(self.server.by_status("open")), 3)

    def test_another_build_stops_without_spooling(self):
        self.server.build = "b" * 64
        self.server.add(25)
        p = self.embed("--parallel", "1")
        self.assertEqual(p.returncode, W.EXIT_BUILD)
        self.assertEqual(len(self.server.uploads), 1)
        self.assertEqual(len(self.server.by_status("open")), 25)
        self.assertFalse(self.spool.exists() and self.spool.read_text().strip())

    def test_a_failed_post_is_spooled_and_posted_first_next_cycle(self):
        self.server.add(3)
        self.server.fail_posts = 3
        p = self.embed("--post-tries", "3")
        self.assertEqual(p.returncode, W.EXIT_SERVER)
        self.assertEqual(len(json.loads(self.spool.read_text())["vectors"]), 3)
        p = self.embed()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.server.stored), 3)
        self.assertEqual(self.spool.read_text().strip(), "")
        self.assertEqual(len(self.embedder.requests), 1)                  # never embedded twice


class TestPack(unittest.TestCase):
    def test_pack_scales_to_one_and_is_2048_bytes(self):
        b64 = W.pack([3.0, 4.0] + [0.0] * 1022)
        self.assertEqual(len(base64.b64decode(b64)), 2048)
        self.assertEqual(unpack(b64)[:2], [0.60009765625, 0.7998046875])
        with self.assertRaises(W.EmbedderError):
            W.pack([0.0] * 1024)


if __name__ == "__main__":
    unittest.main()
