"""KindHttp: the one HTTP client every source kind uses (moved from SourceFetchService).

It owns the User-Agent and TLS-skip policy and the politeness sleep, so tests swap the
whole network edge with one fake (tests/_kind_fakes.FakeHttp) and record every delay a
kind asks for through the injected sleeper instead of waiting it out.

urllib is blocking, so every request runs in a worker thread: the loop's default executor,
or the executor given (the Add source dialog's client has its own few threads, so a slow
site it is asked about never holds up ingestion's).

It requests only http and https addresses, and only where AddressGuard lets it (issue 0187): a host must resolve to
public addresses only, unless it is one of the owner's LAN bridges (bridge_hosts()); the connection goes to the
address that was checked (no second DNS answer can move it), every redirect hop is checked the same way (at most
MAX_REDIRECTS, http and https only, a Cookie or Authorization header never follows to another host), and no
environment proxy is used. TLS is verified everywhere except on a bridge that resolves to a LAN address (its
self-signed certificate) and the hosts RSS_SKIP_TLS_VERIFY_HOSTS names. The media proxy opens through the same guard.

A body is read to MAX_BODY_BYTES at most, raw and unpacked alike (a gzip bomb is an HttpError, not a full
memory); a caller that truly needs more passes a larger max_bytes, with its reason.

It only classifies failures: every one (a dropped connection or a truncated body too) is an HttpError (a ValueError), carrying the status,
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
import ipaddress
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import (Any, Awaitable, Callable, Dict, FrozenSet, Iterable, Iterator, List, Mapping, Optional, Tuple,
                    TypeVar)

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = "INSIGHT Archive Fetcher/1.0"
READ_CHUNK = 64 * 1024    # get_start reads its body in pieces of at most this, checking its deadline
VALIDATORS_MAX_AGE = timedelta(days=7)   # older validators are not sent: the address is read in full
MAX_BODY_BYTES = 10 * 1024 * 1024        # a body's cap, raw and unpacked (issue 0187); raised only by a caller with a reason
ERROR_BODY_BYTES = 64 * 1024              # an error answer's body: only its first 200 characters are kept
MAX_REDIRECTS = 3
# The owner's LAN bridges (the Telegram RSS bridge, Nitter): fetched though they resolve to private addresses.
DEFAULT_BRIDGE_HOSTS = ("telegram.local", "nitter.local")
BRIDGE_HOST_ENVS = ("NITTER_HOSTS", "TELEGRAM_RSS_HOSTS", "INSIGHT_MEDIA_PRIVATE_HOSTS", "RSS_SKIP_TLS_VERIFY_HOSTS")

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
    def their_trouble(self) -> bool:
        """The other server's trouble (issue 0088): an HTTP 5xx or no answer in time, usually over within hours."""
        return self.timed_out or (self.status or 0) >= 500

    @property
    def limiting(self) -> bool:
        """The host is limiting us (429) or not answering in time: wait, slow down, retry once."""
        return self.status == 429 or self.timed_out


def _retry_after(headers: Any) -> Optional[int]:
    value = str((headers.get("Retry-After") if headers is not None else None) or "").strip()
    return int(value) if value.isdigit() else None


@contextlib.contextmanager
def _classified(action: str, url: str) -> Iterator[None]:
    """urllib's failures as HttpError ("HTTP <code> while <action> <url>: <body>"). A body that
    is a web page ("<html>…", a proxy's 502 page) is no message: its status line's reason is."""
    try:
        yield
    except urllib.error.HTTPError as exc:
        body = exc.read(ERROR_BODY_BYTES).decode("utf-8", errors="replace").strip()
        detail = (exc.reason or "") if body.startswith("<") else body[:200]
        raise HttpError(f"HTTP {exc.code} while {action} {url}: {detail}", status=exc.code,
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


def _host_of(item: str) -> str:
    """"https://tg.example:8443/x", "tg.example" -> "tg.example"."""
    item = item.strip()
    try:
        return (urllib.parse.urlsplit(item if "://" in item else f"//{item}").hostname or "").lower()
    except ValueError:
        return ""


def _env_hosts(*names: str, env: Optional[Mapping[str, str]] = None) -> set[str]:
    """The hosts of comma lists of hosts or origins in the environment variables `names`."""
    env = os.environ if env is None else env
    return {host for name in names for host in map(_host_of, (env.get(name) or "").split(",")) if host}


def bridge_hosts(env: Optional[Mapping[str, str]] = None) -> FrozenSet[str]:
    """The hosts fetched although they resolve to private addresses: the LAN bridges (telegram.local, nitter.local)
    and every host NITTER_HOSTS, TELEGRAM_RSS_HOSTS, INSIGHT_MEDIA_PRIVATE_HOSTS or RSS_SKIP_TLS_VERIFY_HOSTS names."""
    return frozenset(DEFAULT_BRIDGE_HOSTS) | frozenset(_env_hosts(*BRIDGE_HOST_ENVS, env=env))


def is_public_address(address: str) -> bool:
    """Globally routable: not private (Docker's networks too), loopback, link-local (169.254.169.254, the cloud
    metadata address), CGNAT/Tailscale (100.64/10), unspecified, reserved or multicast. An IPv4 address written
    as IPv6 (::ffff:127.0.0.1) is judged as the IPv4 one."""
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class AddressNotAllowed(HttpError):
    """The host resolves to an address INSIGHT never fetches from (a private, loopback, link-local... one)."""


def _resolve(host: str, port: int) -> List[str]:
    return list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


class AddressGuard:
    """Where INSIGHT's outgoing requests may connect (issue 0187), decided at the moment of connecting.

    connect() resolves the host once, refuses it unless every address is public or the host is a bridge
    (bridge_hosts()), and connects to one of the addresses it checked: a second DNS answer (rebinding) is
    never asked. opener() is a urllib opener whose every connection, redirects included, goes through it."""

    def __init__(self, *, bridges: Optional[Iterable[str]] = None, insecure_tls_hosts: Optional[Iterable[str]] = None,
                 resolve: Optional[Callable[[str, int], List[str]]] = None) -> None:
        self.bridges = frozenset(h.lower() for h in bridges) if bridges is not None else bridge_hosts()
        self.insecure_tls_hosts = (frozenset(h.lower() for h in insecure_tls_hosts) if insecure_tls_hosts is not None
                                   else frozenset(_env_hosts("RSS_SKIP_TLS_VERIFY_HOSTS")))
        self._resolve = resolve or _resolve

    def addresses(self, host: str, port: int) -> Tuple[List[str], bool]:
        """(the addresses to connect to, whether any is private). Raises AddressNotAllowed, or HttpError when the
        host doesn't resolve."""
        host = (host or "").lower().rstrip(".")
        try:
            found = self._resolve(host, port)
        except OSError as exc:
            raise HttpError(f"Cannot resolve {host}: {getattr(exc, 'strerror', None) or exc}") from None
        if not found:
            raise HttpError(f"Cannot resolve {host}")
        private = not all(is_public_address(a) for a in found)
        if private and host not in self.bridges:
            raise AddressNotAllowed(f"{host} is not a public host")
        return found, private

    def insecure_tls(self, host: str, private: bool) -> bool:
        """TLS unverified only for a bridge on the LAN (a self-signed certificate) or a host the owner listed."""
        host = (host or "").lower().rstrip(".")
        return host in self.insecure_tls_hosts or (private and host in self.bridges)

    def connect(self, host: str, port: int, timeout: Any, source_address: Any = None) -> Tuple[socket.socket, bool]:
        """A socket connected to a checked address of host, and whether its TLS may skip verification."""
        found, private = self.addresses(host, port)
        error: Optional[OSError] = None
        for address in found:
            try:
                return socket.create_connection((address, port), timeout, source_address), \
                    self.insecure_tls(host, private)
            except OSError as exc:
                error = exc
        raise error or OSError(f"cannot connect to {host}")

    def opener(self) -> urllib.request.OpenerDirector:
        """http and https only, no environment proxy (it would connect for us, unchecked), redirects by _Redirects."""
        opener = urllib.request.OpenerDirector()
        for handler in (urllib.request.UnknownHandler(), urllib.request.HTTPDefaultErrorHandler(), _Redirects(),
                        urllib.request.HTTPErrorProcessor(), _GuardedHTTPHandler(self), _GuardedHTTPSHandler(self)):
            opener.add_handler(handler)
        return opener


def _guarded_connection(base: type) -> type:
    """http.client's connection whose socket comes from AddressGuard.connect (and, for https, whose TLS context
    is the unverified one when the guard says so: HTTPSConnection wraps the socket right after)."""

    class Guarded(base):   # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, guard: AddressGuard, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._guard = guard
            self._create_connection = self._connect_checked

        def _connect_checked(self, address: Tuple[str, int], timeout: Any = None, source_address: Any = None):
            sock, insecure = self._guard.connect(address[0], address[1], timeout, source_address)
            if insecure and isinstance(self, http.client.HTTPSConnection):
                self._context = ssl._create_unverified_context()
            return sock

    Guarded.__name__ = f"Guarded{base.__name__}"
    return Guarded


_GuardedHTTPConnection = _guarded_connection(http.client.HTTPConnection)
_GuardedHTTPSConnection = _guarded_connection(http.client.HTTPSConnection)


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, guard: AddressGuard) -> None:
        super().__init__()
        self.guard = guard

    def http_open(self, req):
        return self.do_open(functools.partial(_GuardedHTTPConnection, guard=self.guard), req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, guard: AddressGuard) -> None:
        super().__init__()
        self.guard = guard

    def https_open(self, req):
        return self.do_open(functools.partial(_GuardedHTTPSConnection, guard=self.guard), req)


_CREDENTIAL_HEADERS = ("cookie", "authorization")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """At most MAX_REDIRECTS, to http or https only (each hop's host is checked as it connects); a Cookie or an
    Authorization header goes along only while the host stays the same."""

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme.lower() not in ("http", "https"):
            raise HttpError(f"Redirected to a non-web address: {newurl}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        source_host = (urllib.parse.urlsplit(req.full_url).hostname or "").lower()
        if new is not None and (target.hostname or "").lower() != source_host:
            for name in list(new.headers):
                if name.lower() in _CREDENTIAL_HEADERS:
                    del new.headers[name]
        return new


class BodyTooLarge(HttpError):
    """A body over its cap (MAX_BODY_BYTES unless the caller raised it), raw or unpacked."""


def body_cap(max_bytes: Optional[int] = None) -> int:
    """A body's cap: MAX_BODY_BYTES, or more when a caller asks for more (never less: a short read is get_start's)."""
    return max(MAX_BODY_BYTES, max_bytes or 0)


def read_capped(response: Any, cap: int, url: str) -> bytes:
    """The whole body as the server meant it (gzip and deflate undone), raw and unpacked each at most cap bytes:
    past it, BodyTooLarge."""
    raw = response.read(cap + 1)
    if len(raw) > cap:
        raise BodyTooLarge(f"Larger than {cap // (1024 * 1024)} MB: {url}")
    headers = getattr(response, "headers", None)
    body = _unpacked(raw, headers.get("Content-Encoding") if headers is not None else None, cap + 1)
    if len(body) > cap:
        raise BodyTooLarge(f"Larger than {cap // (1024 * 1024)} MB unpacked: {url}")
    return body


def _unpacked(body: bytes, encoding: Optional[str], max_bytes: int) -> bytes:
    """The body as the server meant it: gzip or deflate undone, at most max_bytes of it. A server may compress a
    body nobody asked to compress, with a Content-Encoding header or without one (then gzip's own 1f 8b start
    gives it away). A cut-off body (a byte cap) unpacks as far as it goes; one that isn't really compressed
    passes as it came."""
    unpack = _unpacker(body, encoding)
    if unpack is None:
        return body
    try:
        return unpack.decompress(body, max_bytes)
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
        guard: Optional[AddressGuard] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        executor: Optional[Executor] = None,
    ) -> None:
        self.timeout = timeout if timeout is not None else int(
            os.getenv("RSS_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
        self.user_agent = user_agent or os.getenv("RSS_USER_AGENT", DEFAULT_USER_AGENT)
        self.reddit_user_agent = reddit_user_agent or os.getenv("REDDIT_USER_AGENT", DEFAULT_USER_AGENT)
        self.guard = guard or AddressGuard()
        self._opener = self.guard.opener()
        self._sleep = sleep
        self._executor = executor

    # ------------------------------------------------------------------ requests

    async def get_text(
        self, url: str, *, user_agent: Optional[str] = None, headers: Optional[Dict[str, str]] = None,
        max_bytes: Optional[int] = None,
    ) -> Tuple[str, Dict[str, str]]:
        """GET url; returns (body, lower-cased headers). Raises HttpError on HTTP/network errors, and
        BodyTooLarge past MAX_BODY_BYTES (max_bytes raises that cap: a caller that needs more says why).

        headers are extra request headers (e.g. a Cookie); they never appear in errors or logs.
        """
        return await self._in_thread(self._get_text_sync, url, user_agent, headers, max_bytes)

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
        are followed (the validators go along). max_bytes cuts the body there, read as get_start reads
        it (within the timeout overall); None reads it all, to MAX_BODY_BYTES (BodyTooLarge past it).
        AddressMemory.get remembers the answer."""
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

    # ------------------------------------------------------------------ blocking halves

    async def _in_thread(self, fn: Callable[..., T], *args: Any) -> T:
        """asyncio.to_thread on this client's executor."""
        call = functools.partial(contextvars.copy_context().run, fn, *args)
        return await asyncio.get_running_loop().run_in_executor(self._executor, call)

    def _open(self, request: urllib.request.Request) -> Any:
        """The one way out: the guard's opener (every connection and redirect hop checked)."""
        return self._opener.open(request, timeout=self.timeout)

    def _get_text_sync(
        self, url: str, user_agent: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None,
        max_bytes: Optional[int] = None,
    ) -> Tuple[str, Dict[str, str]]:
        _web(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent or self.user_agent, "Accept": "*/*", **(extra_headers or {})},
        )
        with _classified("fetching", url):
            with self._open(request) as response:
                body = read_capped(response, body_cap(max_bytes), url)
                headers = {key.lower(): value for key, value in response.headers.items()}
                return body.decode("utf-8", errors="replace"), headers

    def _get_start_sync(self, url: str, max_bytes: int) -> Tuple[bytes, str]:
        _web(url)
        deadline = time.monotonic() + self.timeout
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
        with _classified("fetching", url):
            with self._open(request) as response:
                return _read_start(response, max_bytes, deadline), response.geturl()

    def _get_conditional_sync(self, url: str, validators: Optional[Validators],
                              max_bytes: Optional[int]) -> Conditional:
        _web(url)
        deadline = time.monotonic() + self.timeout
        request = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent, "Accept": "*/*", **(validators.request_headers() if validators else {})})
        with _classified("fetching", url):
            try:
                with self._open(request) as response:
                    headers = {key.lower(): value for key, value in response.headers.items()}
                    if max_bytes is None:
                        body = read_capped(response, body_cap(), url)
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
            with self._open(request) as response:
                return json.loads(read_capped(response, body_cap(), url).decode("utf-8", errors="replace"))
