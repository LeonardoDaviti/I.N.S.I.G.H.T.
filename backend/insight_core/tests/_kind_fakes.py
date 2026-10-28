"""Test adapters for the source-kind seam (spec §3): FakeHttp, RecordingSleeper, FakeKind.

No network: FakeHttp answers from a dict and records every request; RecordingSleeper
records the politeness delays a kind asked for instead of waiting them out.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Mapping

from insight_core.ingestion.http import Conditional, KindHttp, Validators
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    KindSession,
    KindUnavailable,
    NullKindSession,
    PolitenessProfile,
)


class RecordingKindSession:
    """A KindSession that records open/close; open_raises makes open() fail."""

    def __init__(self, open_raises: BaseException | None = None) -> None:
        self.open_raises = open_raises
        self.events: list[str] = []

    async def open(self) -> None:
        self.events.append("open")
        if self.open_raises is not None:
            raise self.open_raises

    async def close(self) -> None:
        self.events.append("close")


class RecordingSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# str | (str, headers) | Exception | dict (JSON) | Conditional (get_conditional's answer as is)
# | callable(url) -> one of these (or awaits one)
Response = Any


class FakeHttp(KindHttp):
    """KindHttp answering from {url: response}. Unknown URLs fail like a 404."""

    def __init__(
        self,
        responses: Mapping[str, Response] | Callable[[str], Response] | None = None,
        *,
        sleep: RecordingSleeper | None = None,
        redirects: Mapping[str, str] | None = None,
    ) -> None:
        self.sleeper = sleep or RecordingSleeper()
        super().__init__(sleep=self.sleeper, timeout=1, user_agent="test-agent")
        self.responses = responses if responses is not None else {}
        self.requests: list[str] = []
        self.request_headers: list[tuple[str, dict[str, str]]] = []
        self.posts: list[tuple[str, dict]] = []
        self.redirects = dict(redirects or {})   # url -> the final URL get_start reports
        self.byte_caps: dict[str, int] = {}      # url -> the max_bytes get_start was asked for
        self.validators_sent: list[tuple[str, Validators | None]] = []   # get_conditional's

    def _answer(self, url: str) -> Response:
        if callable(self.responses):
            answer = self.responses(url)
        elif url in self.responses:
            answer = self.responses[url]
        else:
            raise ValueError(f"HTTP 404 while fetching {url}: (FakeHttp has no response)")
        if callable(answer):
            answer = answer(url)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def get_text(
        self, url: str, *, user_agent: str | None = None, headers: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        self.requests.append(url)
        self.request_headers.append((url, dict(headers or {})))
        answer = self._answer(url)
        if isinstance(answer, tuple):
            return answer
        return str(answer), {}

    async def get_start(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        self.requests.append(url)
        self.byte_caps[url] = max_bytes
        answer = self._answer(url)
        if inspect.isawaitable(answer):
            answer = await answer
        body = answer[0] if isinstance(answer, tuple) else answer
        return str(body).encode("utf-8")[:max_bytes], self.redirects.get(url, url)

    async def get_conditional(self, url: str, validators: Validators | None = None, *,
                              max_bytes: int | None = None) -> Conditional:
        """A Conditional answer as is; anything else a 200, its headers giving the validators."""
        self.requests.append(url)
        self.validators_sent.append((url, validators))
        if max_bytes is not None:
            self.byte_caps[url] = max_bytes
        answer = self._answer(url)
        if inspect.isawaitable(answer):
            answer = await answer
        if isinstance(answer, Conditional):
            return answer
        body, headers = answer if isinstance(answer, tuple) else (answer, {})
        headers = {key.lower(): value for key, value in headers.items()}
        data = str(body).encode("utf-8")
        return Conditional(data[:max_bytes] if max_bytes is not None else data, self.redirects.get(url, url),
                           headers, Validators.of(headers))

    def headers_for(self, url: str) -> dict[str, str]:
        """The extra headers of the last GET of url."""
        return next((h for u, h in reversed(self.request_headers) if u == url), {})

    async def post_json(
        self,
        url: str,
        payload: dict,
        *,
        user_agent: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        self.requests.append(url)
        self.posts.append((url, payload))
        answer = self._answer(url)
        return answer(payload) if callable(answer) else answer


class FakeKind(BaseKind):
    """A scripted SourceKind: returns posts, raises, or raises KindUnavailable."""

    def __init__(
        self,
        name: str = "fake",
        profile: PolitenessProfile | None = None,
        behaviour: Callable[[Mapping[str, Any], int], list[dict]] | None = None,
        *,
        matches: Callable[[Mapping[str, Any]], bool] | None = None,
        inspection: Inspection | None = None,
        pages: list[ArchivePage] | None = None,
        session: KindSession | None = None,
    ) -> None:
        self.name = name
        self.profile = profile or PolitenessProfile(concurrency_pool="host-lock")
        self._behaviour = behaviour or (lambda _source, _limit: [])
        self._matches = matches or (lambda _source: True)
        self._inspection = inspection or Inspection(None, None, None, {})
        self._pages = list(pages or [])
        self._session = session
        self.events: list[str] = []      # "fetch" / "inspect" / "page", interleaved with session events
        self.fetch_calls: list[tuple[str, int]] = []
        self.resumable_calls: list[Any] = []
        self.estimate_calls: list[tuple[int, int | None]] = []

    def matches(self, source: Mapping[str, Any]) -> bool:
        return self._matches(source)

    def session(self) -> KindSession:
        return self._session if self._session is not None else NullKindSession()

    def _event(self, name: str) -> None:
        self.events.append(name)
        if isinstance(self._session, RecordingKindSession):
            self._session.events.append(name)

    async def fetch_latest(self, source: Mapping[str, Any], limit: int) -> list[dict]:
        self.fetch_calls.append((str(source.get("handle_or_url")), limit))
        self._event("fetch")
        return self._behaviour(source, limit)

    async def inspect(self, source: Mapping[str, Any]) -> Inspection:
        self._event("inspect")
        return self._inspection

    async def archive_pages(self, source, target, checkpoint, rate):
        for page in self._pages:
            self._event("page")
            yield page

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        self.resumable_calls.append(checkpoint)
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "fake"

    def estimate_pages(self, remaining: int, page_size: int | None) -> int:
        self.estimate_calls.append((remaining, page_size))
        return super().estimate_pages(remaining, page_size)


def unavailable(reason: str) -> Callable[[Mapping[str, Any], int], list[dict]]:
    def raise_unavailable(_source, _limit):
        raise KindUnavailable(reason)

    return raise_unavailable
