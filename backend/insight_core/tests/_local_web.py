"""A small web server on 127.0.0.1 and a fake DNS, for AddressGuard's tests (issue 0187).

The guard refuses 127.0.0.1, so the tests name the server by made-up hosts the fake DNS points at it
(origin.test, other.test: listed as bridges) and at addresses the guard must refuse (metadata.test ->
169.254.169.254 ...). Nothing leaves the machine: a refused host is never connected to.
"""
from __future__ import annotations

import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Sequence

from insight_core.ingestion.http import AddressGuard

BIG = 11 * 1024 * 1024   # over MAX_BODY_BYTES
BOMB = gzip.compress(b"\0" * BIG)   # ~11 KB on the wire


class FakeDns:
    """host -> addresses (a list, or a list of lists answered in turn); records every question."""

    def __init__(self, answers: Dict[str, Sequence]) -> None:
        self.answers = dict(answers)
        self.asked: List[str] = []

    def __call__(self, host: str, port: int) -> List[str]:
        self.asked.append(host)
        answer = self.answers.get(host)
        if answer is None:
            raise OSError("no such host")
        if answer and isinstance(answer[0], list):   # answered in turn (a rebinding name)
            turn = min(self.asked.count(host), len(answer)) - 1
            return list(answer[turn])
        return list(answer)


DNS = {"origin.test": ["127.0.0.1"], "other.test": ["127.0.0.1"], "metadata.test": ["169.254.169.254"],
       "docker.test": ["172.18.0.2"], "cgnat.test": ["100.64.1.2"], "mixed.test": ["93.184.216.34", "10.0.0.1"]}


def guard(dns: FakeDns | None = None) -> AddressGuard:
    return AddressGuard(bridges={"origin.test", "other.test"}, insecure_tls_hosts=set(), resolve=dns or FakeDns(DNS))


class _Site(BaseHTTPRequestHandler):
    port = 0

    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path
        if path == "/ok":
            return self._send(200, b"hello", "text/plain")
        if path == "/image":
            return self._send(200, b"png-bytes", "image/png")
        if path == "/to-image":
            return self._redirect("/image")
        if path == "/to-internal":
            return self._redirect(f"http://metadata.test:{self.port}/latest/meta-data")
        if path == "/to-file":
            return self._redirect("file:///etc/passwd")
        if path.startswith("/chain/"):
            left = int(path.rsplit("/", 1)[1])
            return self._redirect(f"/chain/{left - 1}") if left > 0 else self._send(200, b"end", "text/plain")
        if path == "/to-other":
            return self._redirect(f"http://other.test:{self.port}/cookie")
        if path == "/to-same":
            return self._redirect("/cookie")
        if path == "/cookie":
            return self._send(200, (self.headers.get("Cookie") or "none").encode(), "text/plain")
        if path == "/bomb":
            return self._send(200, BOMB, "application/rss+xml", {"Content-Encoding": "gzip"})
        if path == "/big":
            return self._send(200, b"a" * BIG, "text/plain")
        if path == "/small-gzip":
            return self._send(200, gzip.compress(b"<rss/>"), "application/rss+xml", {"Content-Encoding": "gzip"})
        self._send(404, b"no", "text/plain")

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, status: int, body: bytes, kind: str, headers: Dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:   # the client stopped reading at its cap
            pass


class LocalWeb:
    """with LocalWeb() as web: web.url("origin.test", "/ok")."""

    def __enter__(self) -> "LocalWeb":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
        self.port = self.server.server_address[1]
        _Site.port = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def url(self, host: str, path: str) -> str:
        return f"http://{host}:{self.port}{path}"

    def __exit__(self, *_exc) -> None:
        self.server.shutdown()
        self.server.server_close()
