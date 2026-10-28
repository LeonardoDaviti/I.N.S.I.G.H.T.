"""KindHttp: the one HTTP client every source kind uses (moved from SourceFetchService).

It owns the User-Agent and TLS-skip policy and the politeness sleep, so tests swap the
whole network edge with one fake (tests/_kind_fakes.FakeHttp) and record every delay a
kind asks for through the injected sleeper instead of waiting it out.

urllib is blocking, so every request runs in a worker thread: the loop's default executor,
or the executor given (the Add source dialog's client has its own few threads, so a slow
site it is asked about never holds up ingestion's).

It requests only http and https addresses, and only classifies failures: every one (a dropped connection or a truncated body too) is an HttpError (a ValueError), carrying the status,
the Retry-After seconds and whether it timed out. Retrying and slowing down are the
caller's, where the host is known (issue 0016).

A conditional GET (get_conditional, issue 0044) sends what the server said last time (ETag ->
If-None-Match, Last-Modified -> If-Modified-Since) and gets back either "not modified" (a 304,
never an error, no body) or the body with its new validators. AddressMemory is one fetch's
validators, per address: what it may send (none when asked to read in full, or when they are
older than VALIDATORS_MAX_AGE, so a server answering 304 wrongly cannot hide new posts for
long) and what it learned, for the caller to keep once the fetch's posts are safe.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import http.client
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Iterator, Mapping, Optional, Tuple, TypeVar

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = "INSIGHT Archive Fetcher/1.0"
READ_CHUNK = 64 * 1024    # get_start reads its body in pieces of at most this, checking its deadline
VALIDATORS_MAX_AGE = timedelta(days=7)   # older validators are not sent: the address is read in full

T = TypeVar("T")


class HttpError(ValueError):
    """A failed request: status (None for a network error), retry_after (integer seconds from
    the Retry-After header, else None), timed_out (a connect or read timeout)."""

    def __init__(self, message: str, *, status: Optional[int] = None, retry_after: Optional[int] = None,
                 timed_out: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.timed_out = timed_out

    @property
    def limiting(self) -> bool:
        """The host is limiting us (429) or not answering in time: wait, slow down, retry once."""
        return self.status == 429 or self.timed_out


def _retry_after(headers: Any) -> Optional[int]:
    value = str((headers.get("Retry-After") if headers is not None else None) or "").strip()
    return int(value) if value.isdigit() else None


@contextlib.contextmanager
def _classified(action: str, url: str) -> Iterator[None]:
    """urllib's failures as HttpError ("HTTP <code> while <action> <url>: <body>")."""
    try:
        yield
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise HttpError(f"HTTP {exc.code} while {action} {url}: {body[:200]}", status=exc.code,
                        retry_after=_retry_after(exc.headers)) from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Failed {action} {url}: {exc.reason}",
                        timed_out=isinstance(exc.reason, TimeoutError)) from exc
    except TimeoutError as exc:   # a read timeout escapes urllib unwrapped
        raise HttpError(f"Timed out {action} {url}", timed_out=True) from exc
    except (OSError, http.client.HTTPException) as exc:   # a dropped connection, a truncated body
        raise HttpError(f"Failed {action} {url}: {type(exc).__name__}") from exc


def _web(url: str) -> None:
    """Only http and https are requested: a file:// or ftp:// address is an HttpError."""
    if urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
        raise HttpError(f"Not a web address: {url}")


def _env_hosts(name: str, default: str = "") -> set[str]:
    return {host.strip().lower() for host in os.getenv(name, default).split(",") if host.strip()}


def _unpacked(body: bytes, encoding: Optional[str], max_bytes: Optional[int] = None) -> bytes:
    """The body as the server meant it: gzip or deflate undone. A server may compress a body
    nobody asked to compress, with a Content-Encoding header or without one (then gzip's own
    1f 8b start gives it away). A cut-off body (a byte cap) unpacks as far as it goes; one that
    isn't really compressed passes as it came."""
    unpack = _unpacker(body, encoding)
    if unpack is None:
        return body
    try:
        return unpack.decompress(body, max_bytes or 0)
    except zlib.error:
        return body


def _unpacker(start: bytes, encoding: Optional[str]) -> Any:
    """A decompressor for a body that starts with `start`, or None when it isn't compressed."""
    encoding = (encoding or "").strip().lower()
    if encoding in ("gzip", "x-gzip") or start[:2] == b"\x1f\x8b":
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        return zlib.decompressobj(zlib.MAX_WBITS if start[:1] == b"\x78" else -zlib.MAX_WBITS)  # zlib-wrapped, or raw
    return None


def _read_start(response: Any, max_bytes: int, deadline: float) -> bytes:
    """At most max_bytes of a response's body (its own bytes, unpacked), read in pieces before
    the deadline: past it, TimeoutError (leaving the caller's with closes the connection)."""
    encoding = (getattr(response, "headers", None) or {}).get("Content-Encoding")
    unpack, chunks, size = None, [], 0
    while size < max_bytes:
        if time.monotonic() > deadline:
            raise TimeoutError
        chunk = response.read1(READ_CHUNK if unpack else min(READ_CHUNK, max_bytes - size))
        if not chunk:
            break
        if not chunks and unpack is None:
            unpack = _unpacker(chunk, encoding)
        if unpack:
            try:
                chunk = unpack.decompress(chunk, max_bytes - size)
            except zlib.error:
                break            # broken past this point: keep what unpacked so far
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class Validators:
    """What a server said identifies its answer: the ETag and Last-Modified headers, verbatim.
    learned_at: when a full answer (a 200) gave them; a 304 keeps it, so they still age."""

    etag: Optional[str] = None
    last_modified: Optional[str] = None
    learned_at: Optional[datetime] = None

    def __bool__(self) -> bool:
        return bool(self.etag or self.last_modified)

    @staticmethod
    def of(headers: Mapping[str, str]) -> "Validators":
        """The validators in an answer's lower-cased headers."""
        return Validators((headers.get("etag") or "").strip() or None,
                          (headers.get("last-modified") or "").strip() or None)

    def request_headers(self) -> Dict[str, str]:
        headers = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        return headers


@dataclass(frozen=True)
class Conditional:
    """A conditional GET's answer. body is None when the server said "not modified" (304);
    otherwise the body as the server meant it (gzip and deflate undone), cut at max_bytes.
    url is the final address after redirects; validators are this answer's own (learned_at unset)."""

    body: Optional[bytes]
    url: str
    headers: Dict[str, str]
    validators: Validators

    @property
    def not_modified(self) -> bool:
        return self.body is None

    @property
    def text(self) -> str:
        return (self.body or b"").decode("utf-8", errors="replace")


class AddressMemory:
    """The validators one fetch may send and has learned, per address (issue 0044).

    stored: what the last fetch learned ({url: Validators}). full: send none (the owner's
    "Fetch now" on one source). get() makes the conditional GET and learns its answer: a 200's
    validators dated now, a 304's (or, when it repeats none, the ones sent) keeping their date.
    learned is what to keep once the fetch's posts are saved; forget() keeps nothing (a fetch
    that left work for the next one, which must then read in full). unchanged: every address
    asked answered 304.
    """

    def __init__(self, stored: Optional[Mapping[str, Validators]] = None, *, now: datetime,
                 full: bool = False, max_age: timedelta = VALIDATORS_MAX_AGE) -> None:
        self.stored: Dict[str, Validators] = dict(stored or {})
        self.now = now
        self.full = full
        self.max_age = max_age
        self.learned: Dict[str, Validators] = {}
        self.asked = 0
        self.not_modified = 0

    def sending(self, url: str) -> Optional[Validators]:
        """What a GET of url sends: None when reading in full, nothing is stored, or it is stale."""
        stored = self.stored.get(url)
        if self.full or not stored or stored.learned_at is None or self.now - stored.learned_at > self.max_age:
            return None
        return stored

    async def get(self, http: "KindHttp", url: str, *, max_bytes: Optional[int] = None) -> Conditional:
        sent = self.sending(url)
        answer = await http.get_conditional(url, sent, max_bytes=max_bytes)
        self.asked += 1
        new = answer.validators
        if answer.not_modified and sent is not None:
            self.not_modified += 1
            self.learned[url] = Validators(new.etag or sent.etag, new.last_modified or sent.last_modified,
                                           sent.learned_at)
        elif new:
            self.learned[url] = Validators(new.etag, new.last_modified, self.now)
        else:
            self.learned.pop(url, None)
        return answer

    def forget(self) -> None:
        self.learned = {}

    @property
    def unchanged(self) -> bool:
        return self.asked > 0 and self.not_modified == self.asked

    @property
    def changed(self) -> bool:
        """learned differs from stored: worth writing."""
        return self.learned != self.stored


class KindHttp:
    def __init__(
        self,
        *,
        timeout: Optional[int] = None,
        user_agent: Optional[str] = None,
        reddit_user_agent: Optional[str] = None,
        insecure_tls_hosts: Optional[set[str]] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        executor: Optional[Executor] = None,
    ) -> None:
        self.timeout = timeout if timeout is not None else int(
            os.getenv("RSS_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
        self.user_agent = user_agent or os.getenv("RSS_USER_AGENT", DEFAULT_USER_AGENT)
        self.reddit_user_agent = reddit_user_agent or os.getenv("REDDIT_USER_AGENT", DEFAULT_USER_AGENT)
        self.insecure_tls_hosts = (
            insecure_tls_hosts if insecure_tls_hosts is not None else _env_hosts("RSS_SKIP_TLS_VERIFY_HOSTS")
        )
        self._sleep = sleep
        self._executor = executor

    # ------------------------------------------------------------------ requests

    async def get_text(
        self, url: str, *, user_agent: Optional[str] = None, headers: Optional[Dict[str, str]] = None
    ) -> Tuple[str, Dict[str, str]]:
        """GET url; returns (body, lower-cased headers). Raises HttpError on HTTP/network errors.

        headers are extra request headers (e.g. a Cookie); they never appear in errors or logs.
        """
        return await self._in_thread(self._get_text_sync, url, user_agent, headers)

    async def get_start(self, url: str, max_bytes: int) -> Tuple[bytes, str]:
        """GET url, reading at most max_bytes of the body: (those bytes, the final URL after
        redirects). For a quick look at a page or a feed (the feed finder). The body is read
        within the timeout overall, not per read, so a server dripping it slowly is a timeout
        (HttpError, timed_out) and its connection is closed. Raises HttpError."""
        return await self._in_thread(self._get_start_sync, url, max_bytes)

    async def get_conditional(self, url: str, validators: Optional[Validators] = None, *,
                              max_bytes: Optional[int] = None) -> Conditional:
        """GET url sending validators (If-None-Match / If-Modified-Since); any address. A 304 is
        a Conditional with no body, never an error; any other failure is an HttpError. Redirects
        are followed (the validators go along). max_bytes caps the body, read as get_start reads
        it (within the timeout overall); None reads it all. AddressMemory.get remembers the answer."""
        return await self._in_thread(self._get_conditional_sync, url, validators, max_bytes)

    async def get_json(self, url: str, *, user_agent: Optional[str] = None) -> Any:
        body, _ = await self.get_text(url, user_agent=user_agent)
        return json.loads(body)

    async def post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        *,
        user_agent: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return await self._in_thread(self._post_json_sync, url, payload, user_agent, extra_headers)

    async def sleep(self, seconds: float) -> None:
        """A politeness delay. Zero or negative is not a sleep (and is not recorded)."""
        if seconds and seconds > 0:
            await self._sleep(seconds)

    def should_skip_tls_verify(self, hostname: Optional[str]) -> bool:
        if not hostname:
            return False
        host = hostname.lower()
        if host in self.insecure_tls_hosts:
            return True
        return host.endswith(".local")

    # ------------------------------------------------------------------ blocking halves

    async def _in_thread(self, fn: Callable[..., T], *args: Any) -> T:
        """asyncio.to_thread on this client's executor."""
        call = functools.partial(contextvars.copy_context().run, fn, *args)
        return await asyncio.get_running_loop().run_in_executor(self._executor, call)

    def _context_for(self, url: str):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "https" and self.should_skip_tls_verify(parsed.hostname):
            return ssl._create_unverified_context()
        return None

    def _get_text_sync(
        self, url: str, user_agent: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None
    ) -> Tuple[str, Dict[str, str]]:
        _web(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent or self.user_agent, "Accept": "*/*", **(extra_headers or {})},
        )
        with _classified("fetching", url):
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context_for(url)) as response:
                raw = response.read()
                headers = {key.lower(): value for key, value in response.headers.items()}
                return _unpacked(raw, headers.get("content-encoding")).decode("utf-8", errors="replace"), headers

    def _get_start_sync(self, url: str, max_bytes: int) -> Tuple[bytes, str]:
        _web(url)
        deadline = time.monotonic() + self.timeout
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
        with _classified("fetching", url):
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context_for(url)) as response:
                return _read_start(response, max_bytes, deadline), response.geturl()

    def _get_conditional_sync(self, url: str, validators: Optional[Validators],
                              max_bytes: Optional[int]) -> Conditional:
        _web(url)
        deadline = time.monotonic() + self.timeout
        request = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent, "Accept": "*/*", **(validators.request_headers() if validators else {})})
        with _classified("fetching", url):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self._context_for(url)) as response:
                    headers = {key.lower(): value for key, value in response.headers.items()}
                    if max_bytes is None:
                        body = _unpacked(response.read(), headers.get("content-encoding"))
                    else:
                        body = _read_start(response, max_bytes, deadline)
                    return Conditional(body, response.geturl(), headers, Validators.of(headers))
            except urllib.error.HTTPError as exc:
                if exc.code != 304:
                    raise
                headers = {key.lower(): value for key, value in (exc.headers or {}).items()}
                exc.close()   # a 304 has no body: whatever Content-Encoding it names, nothing is unpacked
                return Conditional(None, exc.geturl() or url, headers, Validators.of(headers))

    def _post_json_sync(
        self,
        url: str,
        payload: Dict[str, Any],
        user_agent: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        _web(url)
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "User-Agent": user_agent or self.user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        headers.update(extra_headers or {})
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with _classified("posting to", url):
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context_for(url)) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
