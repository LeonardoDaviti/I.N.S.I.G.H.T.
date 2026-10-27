"""KindHttp: the one HTTP client every source kind uses (moved from SourceFetchService).

It owns the User-Agent and TLS-skip policy and the politeness sleep, so tests swap the
whole network edge with one fake (tests/_kind_fakes.FakeHttp) and record every delay a
kind asks for through the injected sleeper instead of waiting it out.

urllib is blocking, so every request runs in a worker thread (asyncio.to_thread).

It only classifies failures: every one is an HttpError (a ValueError), carrying the status,
the Retry-After seconds and whether it timed out. Retrying and slowing down are the
caller's, where the host is known (issue 0016).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Awaitable, Callable, Dict, Iterator, Optional, Tuple

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_USER_AGENT = "INSIGHT Archive Fetcher/1.0"


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


def _env_hosts(name: str, default: str = "") -> set[str]:
    return {host.strip().lower() for host in os.getenv(name, default).split(",") if host.strip()}


class KindHttp:
    def __init__(
        self,
        *,
        timeout: Optional[int] = None,
        user_agent: Optional[str] = None,
        reddit_user_agent: Optional[str] = None,
        insecure_tls_hosts: Optional[set[str]] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
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

    # ------------------------------------------------------------------ requests

    async def get_text(
        self, url: str, *, user_agent: Optional[str] = None, headers: Optional[Dict[str, str]] = None
    ) -> Tuple[str, Dict[str, str]]:
        """GET url; returns (body, lower-cased headers). Raises HttpError on HTTP/network errors.

        headers are extra request headers (e.g. a Cookie); they never appear in errors or logs.
        """
        return await asyncio.to_thread(self._get_text_sync, url, user_agent, headers)

    async def get_start(self, url: str, max_bytes: int) -> Tuple[bytes, str]:
        """GET url, reading at most max_bytes of the body: (those bytes, the final URL after
        redirects). For a quick look at a page or a feed (the feed finder). Raises HttpError."""
        return await asyncio.to_thread(self._get_start_sync, url, max_bytes)

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
        return await asyncio.to_thread(self._post_json_sync, url, payload, user_agent, extra_headers)

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

    def _context_for(self, url: str):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "https" and self.should_skip_tls_verify(parsed.hostname):
            return ssl._create_unverified_context()
        return None

    def _get_text_sync(
        self, url: str, user_agent: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None
    ) -> Tuple[str, Dict[str, str]]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent or self.user_agent, "Accept": "*/*", **(extra_headers or {})},
        )
        with _classified("fetching", url):
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context_for(url)) as response:
                body = response.read().decode("utf-8", errors="replace")
                headers = {key.lower(): value for key, value in response.headers.items()}
                return body, headers

    def _get_start_sync(self, url: str, max_bytes: int) -> Tuple[bytes, str]:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "*/*"})
        with _classified("fetching", url):
            with urllib.request.urlopen(request, timeout=self.timeout, context=self._context_for(url)) as response:
                return response.read(max_bytes), response.geturl()

    def _post_json_sync(
        self,
        url: str,
        payload: Dict[str, Any],
        user_agent: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
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
