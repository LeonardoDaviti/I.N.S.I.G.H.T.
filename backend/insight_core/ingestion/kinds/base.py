"""The source-kind seam (spec §D.1).

A source kind is the fetch strategy resolved from a source's platform and URL. Exactly one
adapter exists per kind; it owns live fetch, inspection and archive pages, and declares
how hard it may hit its sources in a PolitenessProfile. FetchGates (ingestion/gates.py)
is the only place a profile is turned into concurrency acquisitions. An archive's pause
between pages (RateLimit.delay_after) is not slept by the kind: the archive loop hands it to
the host's gate slot, so the wait between two pages is max(host gap, pause), never the sum.
Pauses inside one request's worth of work (a live fetch reading several pages, Substack's
post bodies) are slept by the kind, through KindHttp.sleep.

Import-light on purpose: adapters/*.py import this module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, AsyncIterator, Literal, Mapping, Optional, Protocol, runtime_checkable

# A source row as the services return it: id, platform, handle_or_url, settings, ...
Source = Mapping[str, Any]

# What a kind's inspected available_posts means (the archive UI words it from this):
#   exact        the source reports its full size
#   upper_bound  a number that can only overcount (the newest post number)
#   estimate     an approximate count (a profile counter, discovered candidate pages)
#   listing_cap  the source is bigger, but its listings stop at this many
#   feed_window  only what the feed lists right now; nothing older is reachable
#   unknown      the source reports no total
AvailableBasis = Literal["exact", "upper_bound", "estimate", "listing_cap", "feed_window", "unknown"]

_RATE_KEYS = ("page_delay_seconds", "batch_size", "batch_cooldown_seconds")


@dataclass(frozen=True)
class RateLimit:
    """The effective archive pacing for one run."""

    page_delay_s: float
    batch_size: int                      # 0 = no batch cooldown
    batch_cooldown_s: float

    def delay_after(self, pages_fetched: int) -> float:
        """The pause after the pages_fetched-th page: a batch cooldown on batch boundaries."""
        if self.batch_size and pages_fetched % self.batch_size == 0:
            return self.batch_cooldown_s
        return self.page_delay_s

    def as_settings(self) -> dict[str, int | float]:
        """The persisted settings.archive.rate_limit shape (Mark VIII keys)."""
        settings: dict[str, int | float] = {"page_delay_seconds": _tidy(self.page_delay_s)}
        if self.batch_size:
            settings["batch_size"] = self.batch_size
            settings["batch_cooldown_seconds"] = _tidy(self.batch_cooldown_s)
        return settings


def _tidy(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


@dataclass(frozen=True)
class PolitenessProfile:
    """How hard a kind may hit its sources. Holds nothing host-keyed (see gates.HOST_FLOORS)."""

    concurrency_pool: Literal["host-lock", "ytdlp"]
    page_delay_s: float = 0.0
    batch_size: int = 0                  # 0 = no batch cooldown
    batch_cooldown_s: float = 0.0
    live_pages_rate_limited: bool = False
    cadence_floor: timedelta = timedelta(0)
    min_posts_per_fetch: int = 0
    requires: Literal["none", "ytdlp", "telegram_creds"] = "none"
    blocking_io: bool = False            # the kind's fetch/inspect/archive run in a thread

    def rate_limit(self, *layers: Optional[Mapping[str, Any]]) -> RateLimit:
        """Profile defaults <- each layer in order (persisted settings, then request overrides).

        Layers use the persisted keys (page_delay_seconds / batch_size /
        batch_cooldown_seconds). None values are ignored, negatives clamp to 0, and batch
        keys only apply to kinds that have a batch cooldown at all (Mark VIII semantics).
        """
        values: dict[str, float] = {
            "page_delay_seconds": self.page_delay_s,
            "batch_size": self.batch_size,
            "batch_cooldown_seconds": self.batch_cooldown_s,
        }
        for layer in layers:
            for key, value in (layer or {}).items():
                if value is None or key not in _RATE_KEYS:
                    continue
                if key != "page_delay_seconds" and not self.batch_size:
                    continue
                try:
                    values[key] = max(0, int(value))
                except (TypeError, ValueError):
                    continue
        batch_size = int(values["batch_size"])
        if self.batch_size:
            batch_size = max(1, batch_size)
        return RateLimit(
            page_delay_s=values["page_delay_seconds"],
            batch_size=batch_size,
            batch_cooldown_s=values["batch_cooldown_seconds"],
        )

    def estimate_seconds(self, pages: int, rate: Optional[RateLimit] = None, host_gap_s: float = 0.0) -> int:
        """One second per page plus every wait between pages: max(host gap, the pause), as the
        archive loop's gate slot waits it."""
        if pages <= 0:
            return 0
        rate = rate or self.rate_limit()
        return int(pages + sum(max(host_gap_s, rate.delay_after(n)) for n in range(1, pages)))


@dataclass(frozen=True)
class Inspection:
    available_posts: Optional[int]
    page_size: Optional[int]
    first_post_date: Optional[str]
    raw: dict = field(default_factory=dict)   # kind-specific extras persisted into settings.archive

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.raw,
            "available_posts": self.available_posts,
            "page_size": self.page_size,
            "first_post_date": self.first_post_date,
        }


@dataclass(frozen=True)
class ArchivePage:
    posts: list[dict]
    checkpoint: Optional[dict]               # None = finished (single-shot kinds)


class KindUnavailable(Exception):
    """The kind needs something this process does not have (outcome UNAVAILABLE, never backoff)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@runtime_checkable
class KindSession(Protocol):
    """A kind's per-run session (B8). The runner opens it lazily, before the kind's first due
    source, and closes it in a finally once the run is done with the kind."""

    async def open(self) -> None: ...        # may raise KindUnavailable(reason); never prompts

    async def close(self) -> None: ...       # idempotent


class NullKindSession:
    """The session of every kind that needs none (all but telegram_mtproto): a no-op."""

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


@runtime_checkable
class SourceKind(Protocol):
    name: str                                # persisted as settings.archive.source_type
    profile: PolitenessProfile
    available_basis: AvailableBasis          # what inspect()'s available_posts means
    archive_refused: str | None              # why the host refuses every archive (None: it archives)

    def matches(self, source: Source) -> bool: ...

    def host_key(self, source: Source) -> str: ...

    async def fetch_latest(self, source: Source, limit: int) -> list[dict]: ...

    async def inspect(self, source: Source) -> Inspection: ...

    def archive_pages(
        self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit
    ) -> AsyncIterator[ArchivePage]: ...

    def checkpoint_resumable(self, checkpoint: Any) -> bool: ...

    async def start_checkpoint(self, source: Source, stored: Mapping[str, Any]) -> Optional[dict]: ...

    def estimate_pages(self, remaining: int, page_size: Optional[int]) -> int: ...

    def session(self) -> KindSession: ...


def source_host_key(source: Source) -> str:
    """The host-limiter bucket for a source (HOST_FLOORS keys).

    Only a URL has a host: extract_url_host would parse bare handles as hosts ("@chan" ->
    "chan", "r/MachineLearning" -> "r"), handing nearly every handle source a private bucket.
    For URLs it applies HOST_ALIASES and strips "www.", the same as posts.url_host, so
    www.reddit.com and old.reddit.com share one bucket. Bare handles group per platform.
    """
    handle = str(source.get("handle_or_url") or "")
    if "://" in handle:
        from insight_core.utils.url_normalization import extract_url_host

        hostname = extract_url_host(handle)
        if hostname:
            return hostname
    return f"platform:{source.get('platform')}"


def start_at(**position: Any) -> dict:
    """A start checkpoint (kind.start_checkpoint): a position, nothing collected yet."""
    return {**position, "collected_posts": 0, "pages_fetched": 0}


def resume_counts(checkpoint: Optional[Mapping[str, Any]]) -> tuple[int, int]:
    """(collected_posts, pages_fetched) carried by a resume checkpoint; (0, 0) for a fresh run."""
    if not isinstance(checkpoint, Mapping):
        return 0, 0
    return int(checkpoint.get("collected_posts") or 0), int(checkpoint.get("pages_fetched") or 0)


class BaseKind:
    """Shared defaults for kinds; subclasses set name and profile and implement the fetches."""

    name: str = "base"
    profile: PolitenessProfile = PolitenessProfile(concurrency_pool="host-lock")
    available_basis: AvailableBasis = "unknown"
    # Why this kind's host refuses every archive request (None: it can archive).
    archive_refused: str | None = None

    def matches(self, source: Source) -> bool:  # pragma: no cover - always overridden
        raise NotImplementedError

    def host_key(self, source: Source) -> str:
        return source_host_key(source)

    async def fetch_latest(self, source: Source, limit: int) -> list[dict]:  # pragma: no cover
        raise NotImplementedError

    async def inspect(self, source: Source) -> Inspection:  # pragma: no cover
        raise NotImplementedError

    def archive_pages(
        self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit
    ) -> AsyncIterator[ArchivePage]:  # pragma: no cover
        raise NotImplementedError

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return False

    async def start_checkpoint(self, source: Source, stored: Mapping[str, Any]) -> Optional[dict]:
        """Where an archive starts so it continues below the stored posts: this kind's own
        checkpoint shape with collected_posts 0, or None (it starts at the newest post).

        `stored` is PostsService.get_source_post_stats: post_count, oldest_published_at,
        oldest_external_id. Called only when the source has stored posts. A position jump
        starts one page early; the URL upsert absorbs the overlap (issue 0015).
        """
        return None

    def session(self) -> KindSession:
        return NullKindSession()

    def estimate_pages(self, remaining: int, page_size: Optional[int]) -> int:
        if remaining <= 0:
            return 0
        return max(1, math.ceil(remaining / max(page_size or 1, 1)))


class SingleShotArchive:
    """Mixin: the archive is one live fetch of `target` posts (generic RSS, YouTube)."""

    async def archive_pages(self, source, target, checkpoint, rate):
        yield ArchivePage(await self.fetch_latest(source, target), None)  # type: ignore[attr-defined]
