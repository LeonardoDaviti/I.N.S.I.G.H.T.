"""The source-kind seam: one adapter per kind owns live fetch, inspection and archive pages.

A kind declares how hard it may hit its sources in a PolitenessProfile; FetchGates (ingestion/gates.py) is the only
place a profile becomes concurrency. An archive's pause between pages (RateLimit.delay_after) is not slept by the
kind: the archive loop hands it to the host's gate slot, so the wait is max(host gap, pause), never the sum. Pauses
inside one request's work are slept by the kind through KindHttp.sleep. Import-light: adapters/*.py import it.
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
        """The persisted settings.archive.rate_limit shape."""
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
    requires: Literal["none", "ytdlp", "telegram_creds", "reddit_creds"] = "none"
    blocking_io: bool = False            # the kind's fetch/inspect/archive run in a thread
    fetches: bool = True                 # False: never due, its posts come by hand (Saved)

    def rate_limit(self, *layers: Optional[Mapping[str, Any]]) -> RateLimit:
        """Profile defaults <- each layer in order (persisted settings, then request overrides), by the persisted
        keys. None values are ignored, negatives clamp to 0, batch keys apply only to kinds with a batch cooldown.
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
        """One second per page plus every wait between pages: max(host gap, the pause), as the gate slot waits."""
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
    """A kind's per-run session. The runner opens it lazily, before the kind's first due source, and closes it in
    a finally once the run is done with the kind."""

    async def open(self) -> None: ...        # may raise KindUnavailable(reason); never prompts

    async def close(self) -> None: ...       # idempotent


class NullKindSession:
    """The session of every kind that needs none (all but telegram_mtproto): a no-op."""

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


@dataclass(frozen=True)
class ReadCheck:
    """A test read that failed (BaseKind.test_read): its reason; `gone` (the platform says the account is not
    there) refuses the add, any other failure adds the source with the reason as a warning."""
    reason: str
    gone: bool = False


# A platform's answer that the account is not there ("yt-dlp ... HTTP Error 404").
GONE_STATUSES = (404, 410)
GONE_WORDS = ("http error 404", "http error 410", "does not exist", "not found")


def gone_reason(reason: str) -> bool:
    """Whether a failed read's message says the account is not there (GONE_WORDS)."""
    text = reason.lower()
    return any(word in text for word in GONE_WORDS)


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
    """The host-limiter bucket for a source (HOST_FLOORS keys): a URL's host with HOST_ALIASES and no "www.", as
    posts.url_host; bare handles group per platform (parsed as hosts they would each get a private bucket).
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


# Why an archive's pages added nothing: the counts a kind keeps in its checkpoint's "skipped", carried across a
# resume (already stored, no post, unreadable).
SKIP_STORED = "stored"
SKIP_NO_POST = "no_post"
SKIP_UNREADABLE = "unreadable"
SKIP_KEYS = (SKIP_STORED, SKIP_NO_POST, SKIP_UNREADABLE)
# What a fetch_one of BaseSourceAdapter.index_pages answers for a page it could not read (None: no post).
UNREADABLE = "unreadable"


def layout_changed_line(pages: int) -> str:
    """What an archive or a fetch says when a reader's listed posts read as no post."""
    return (f"The site's layout changed: {pages} listed page{'' if pages == 1 else 's'} read and no post found on any; "
            "its reader needs an update")


class EmptyFetch(ValueError):
    """A fetch that worked and stored nothing it should have (no item read, every video skipped). Raised by the
    kind, so the fetch is an error with this reason: health shows it and backoff applies."""


# Over this share of a fetch's items skipped, the fetch says so as a warning.
SKIPPED_WARNING_SHARE = 0.5


class FetchedPosts(list):
    """A fetch's posts (a plain list to every caller) with `warning` when over SKIPPED_WARNING_SHARE of its items
    were skipped, and `failure` when the feed collapsed: the runner saves the posts and records a failing fetch."""

    warning: Optional[str] = None
    failure: Optional[str] = None
    # what the fetch learned the source is ({"substack": True}): merged into its settings, read by that kind next
    recognised: Optional[dict] = None
    # what the feed calls itself: the runner names a source that has no name by it
    title: Optional[str] = None


# A feed collapses when over this share of its distinct items fold into another item's address; not tuned: the
# middle between the two server cases (2% and 99.8%, 0242).
COLLAPSED_SHARE = 0.5


def _address_groups(posts: list) -> dict:
    """{normalized address: the identities of the items that have it} (identity: the guid, else the title)."""
    from insight_core.utils.url_normalization import normalize_url

    groups: dict = {}
    for post in posts:
        url = post.get("url") if isinstance(post, Mapping) else None
        if isinstance(url, str):
            key = normalize_url(url) or url
            groups.setdefault(key, set()).add(post.get("guid") or " ".join(str(post.get("title") or "").split()))
    return groups


def _shared_line(groups: dict) -> str:
    shared = [identities for identities in groups.values() if len(identities) > 1]
    return f"{sum(map(len, shared))} items share {len(shared)} address{'es' if len(shared) != 1 else ''}"


def collapsed(posts: list) -> Optional[str]:
    """"the feed has 282 items but 1 would be stored (282 items share 1 address)" when over COLLAPSED_SHARE of its
    distinct items fold into another item's address, else None. Duplicates (same guid, or same title) are no
    failure."""
    groups = _address_groups(posts)
    distinct = sum(len(identities) for identities in groups.values())
    stored = len(groups)
    if distinct - stored <= distinct * COLLAPSED_SHARE:
        return None
    return f"the feed has {distinct} items but {stored} would be stored ({_shared_line(groups)})"


def shared_addresses(posts: list) -> Optional[str]:
    """"2 of 48 items share 1 address: 47 posts stored" when some items share an address and the feed does not
    collapse (a warning), else None."""
    groups = _address_groups(posts)
    distinct = sum(len(identities) for identities in groups.values())
    stored = len(groups)
    if stored >= distinct or collapsed(posts):
        return None
    shared = sum(len(identities) for identities in groups.values() if len(identities) > 1)
    return f"{shared} of {distinct} items share {_shared_line(groups).split(' share ', 1)[1]}: {stored} posts stored"


def skip_reasons(skipped: Mapping[str, int]) -> str:
    """"14 the bot check, 1 timed out": the skip reasons, the most first."""
    return ", ".join(f"{count} {reason}" for reason, count in sorted(skipped.items(), key=lambda kv: (-kv[1], kv[0])))


BROKEN_ITEMS_SHOWN = 3


def broken_items_line(broken: list) -> Optional[str]:
    """"1 broken item skipped: the item "X" (line 2189): unclosed CDATA section", None for none."""
    if not broken:
        return None
    shown = "; ".join(broken[:BROKEN_ITEMS_SHOWN]) + ("; ..." if len(broken) > BROKEN_ITEMS_SHOWN else "")
    return f"{len(broken)} broken item{'' if len(broken) == 1 else 's'} skipped: {shown}"


def checked_fetch(posts: list, items: int, skipped: Mapping[str, int], *, noun: str = "items",
                  broken: Optional[list] = None) -> "FetchedPosts":
    """The fetch's posts, or EmptyFetch when it had items and none became a post. Over half skipped is the posts
    with a warning; `broken` (the items parsing.read_feed skipped) is always a warning."""
    total_skipped = sum(skipped.values())
    if items and not posts:
        if total_skipped >= items:
            raise EmptyFetch(f"every item was skipped ({items} {noun}): {skip_reasons(skipped)}")
        raise EmptyFetch(f"the feed has {items} {noun} but 0 were stored"
                         + (f" ({skip_reasons(skipped)} skipped)" if total_skipped else ""))
    result = FetchedPosts(posts)
    result.failure = collapsed(posts)
    warnings = [broken_items_line(broken or []), shared_addresses(posts)]
    if items and total_skipped > items * SKIPPED_WARNING_SHARE:
        warnings.append(f"{total_skipped} of {items} {noun} skipped: {skip_reasons(skipped)}")
    result.warning = "; ".join(filter(None, warnings)) or None
    return result


def skipped_counts(checkpoint: Optional[Mapping[str, Any]]) -> dict[str, int]:
    """The checkpoint's "skipped" counts (every key, 0 when absent)."""
    found = (checkpoint or {}).get("skipped") if isinstance(checkpoint, Mapping) else None
    found = found if isinstance(found, Mapping) else {}
    return {key: int(found.get(key) or 0) for key in SKIP_KEYS}


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
    # fetch_latest takes memory= (an http.AddressMemory) and fetches conditionally.
    conditional: bool = False
    # Its posts are pages read from a site's own lists, not a feed's items: one first seen long after its date is
    # new to you.
    page_based: bool = False
    # Its stored pages can be re-read for changes (page_post), when the owner switches it on.
    watches: bool = False
    # read_post reads one of its pages as a post (a page its posts link, not stored).
    reads_posts: bool = False
    # Its archive pages go newest to oldest: an archive "back to a date" stops once a page passes the date.
    chronological: bool = False

    def matches(self, source: Source) -> bool:  # pragma: no cover - always overridden
        raise NotImplementedError

    def page_post(self, source: Source, url: str, page: str) -> Optional[dict]:
        """The post the page html at url is, read the way a fetch reads it; None when it is no article. Kinds that
        set watches implement it."""
        return None

    def host_key(self, source: Source) -> str:
        return source_host_key(source)

    async def test_read(self, source: Source) -> Optional["ReadCheck"]:
        """Why this kind cannot read the source being added; None when it read it or has no read of its own (feeds
        go through the feed finder). Never raises."""
        return None

    async def read_post(self, source: Source, url: str) -> Optional[dict]:
        """One page of this source read as its post, with the page's own date; None when it is no post. Kinds that
        set reads_posts implement it. Raises what the request raises."""
        return None

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
        """Where an archive starts so it continues below the stored posts: this kind's checkpoint shape with
        collected_posts 0, or None (start at the newest). `stored`: PostsService.get_source_post_stats. A position
        jump starts one page early; the URL upsert absorbs the overlap.
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
