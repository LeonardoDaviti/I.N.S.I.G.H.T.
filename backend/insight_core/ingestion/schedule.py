"""The fetch schedule: one pure answer to "should this source be fetched now?".

Pure: no DB, no clock, no environment reads except in availability_from_env and the
backoff constants. Every caller - the ingestion runner and the source health API - builds its CadenceStats with cadence_stats() and asks decide_fetch(),
so the UI and the runner cannot disagree about when a source is due.

Spec: plan/INSIGHT_mark_ix_plan.md §C.2.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping

from insight_core.ingestion.kinds.base import PolitenessProfile
from insight_core.ingestion.types import OutcomeStatus
from insight_core.utils.env import env_float

if TYPE_CHECKING:
    from insight_core.db.repo_fetch_state import FetchStateRow


# Backoff ladder: 1h, 2h, 4h, 8h, 16h, 24h, 24h, ... and a 7d cap once a source has failed
# DORMANT_AFTER times in a row (roughly a week of daily failures). 1h, not Mark VIII's 15m:
# the scheduler ticks hourly, so any shorter step only rounds up to "next tick".
BACKOFF_BASE = timedelta(minutes=env_float("INSIGHT_BACKOFF_BASE_MINUTES", 60))
BACKOFF_MAX = timedelta(hours=env_float("INSIGHT_BACKOFF_MAX_HOURS", 24))
BACKOFF_DORMANT_AFTER = int(env_float("INSIGHT_BACKOFF_DORMANT_AFTER", 10))
BACKOFF_DORMANT_MAX = timedelta(hours=env_float("INSIGHT_BACKOFF_DORMANT_MAX_HOURS", 168))

PROBATION_INTERVAL = timedelta(hours=24)
TIER_INTERVAL_MIN = timedelta(hours=24)
TIER_INTERVAL_MAX = timedelta(days=21)
BACKLOG_GUARD_MIN = timedelta(hours=1)
# A busy feed is polled before its window (mean_gap x the posts it exposes) is a quarter full.
BACKLOG_GUARD_SHARE = 4
# last_success_at is recorded when a fetch ends, ticks are anchored to their start: a source
# due up to this soon is due now, so a 1h source fetched 5 minutes into a tick is due at the
# next tick, not the one after.
DUE_SLACK = timedelta(minutes=10)

# Tier boundaries. refresh_cadence's SQL CASE (db/repo_fetch_state.py and migration 0019)
# must stay identical to these; a parity test pins them together.
FAST_BELOW = timedelta(hours=12)
MEDIUM_UP_TO = timedelta(days=7)
MIN_CADENCE_SAMPLES = 3

DEFAULT_MAX_POSTS_PER_FETCH = 20
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class DecisionKind(str, Enum):
    FETCH_NEW_SOURCE = "fetch_new_source"    # no last_success_at and no posts
    FETCH_DUE = "fetch_due"                  # interval elapsed since last_success_at
    FETCH_RETRY = "fetch_retry"              # in error state and next_retry_at elapsed
    FETCH_FORCED = "fetch_forced"            # request.force
    SKIP_NOT_DUE = "skip_not_due"
    SKIP_BACKOFF = "skip_backoff"
    SKIP_UNAVAILABLE = "skip_unavailable"    # yt-dlp off / no Telegram credentials or session
    SKIP_DISABLED = "skip_disabled"          # only reachable for selector 'all'/'folder' defensive path

    @property
    def fetches(self) -> bool:
        return self.value.startswith("fetch_")


class CadenceTier(str, Enum):
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CadenceStats:
    """Read model for one source: sources cadence columns + source_fetch_state + post count."""

    post_count: int
    mean_gap: timedelta | None
    sample_size: int
    tier: CadenceTier
    override_hours: float | None
    max_posts_per_fetch: int
    last_success_at: datetime | None
    last_outcome: OutcomeStatus | None
    consecutive_failures: int
    next_retry_at: datetime | None


@dataclass(frozen=True)
class Availability:
    """What this process can fetch at all. Unavailable is never backoff."""

    ytdlp_enabled: bool
    # Telegram API id + hash and a session stored in Connections (B8). An
    # unauthorised session is only known once the session opens: the runner reports it.
    telegram_credentials: bool
    telegram_reason: str | None = None   # why telegram_credentials is False (the skip reason)


IntervalBasis = Literal["override", "tier", "probation", "backlog_guard", "profile_floor"]


@dataclass(frozen=True)
class FetchDecision:
    kind: DecisionKind
    fetch: bool
    post_limit: int
    interval: timedelta              # the cadence interval in force (for display)
    interval_basis: IntervalBasis
    next_due_at: datetime | None     # when it would next be fetched (None if unavailable)
    next_retry_at: datetime | None   # backoff deadline if in error state
    detail: str                      # human text for logs/UI, never parsed


_TRUTHY_OFF = {"0", "false", "no", "off"}


def availability_from_env(
    env: Mapping[str, str] | None = None,
    *,
    credentials: Any = None,
) -> Availability:
    """What this process can fetch. Injected into callers as a callable, so the runner and
    its tests never read env or credentials themselves.

    - INSIGHT_YTDLP_ENABLED (default on)
    - telegram_mtproto: an API id (an int), a hash and the session saved by the browser
      sign-in; telegram_reason names what is missing. Credentials come from `credentials`
      (a CredentialProvider), default the Connections store; never from the environment.
    """
    from insight_core.ingestion.kinds.telegram_session import (
        LOGIN_HINT,
        telegram_credentials,
        telegram_session_string,
    )

    if credentials is None:
        from insight_core.ingestion.credentials import default_credentials

        credentials = default_credentials()
    env = os.environ if env is None else env
    ytdlp = str(env.get("INSIGHT_YTDLP_ENABLED", "1")).strip().lower() not in _TRUTHY_OFF
    _api_id, _api_hash, reason = telegram_credentials(credentials=credentials)
    if reason is None and not telegram_session_string(credentials):
        reason = f"no Telegram session; {LOGIN_HINT}"
    return Availability(
        ytdlp_enabled=ytdlp,
        telegram_credentials=reason is None,
        telegram_reason=reason,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def cadence_stats(source: Mapping[str, Any], state: "FetchStateRow | None") -> CadenceStats:
    """The ONLY CadenceStats constructor.

    `source` is a source mapping as SourcesRepository returns it (post_count, the cadence
    columns, merged settings). `state` is the source's fetch state row, or None when the
    source has never been decided or fetched.
    """
    settings = source.get("settings") or {}
    gap_seconds = _float_or_none(source.get("mean_gap_seconds"))
    try:
        tier = CadenceTier(source.get("cadence_tier") or "unknown")
    except ValueError:
        tier = CadenceTier.UNKNOWN
    try:
        max_posts = int(settings.get("max_posts_per_fetch") or DEFAULT_MAX_POSTS_PER_FETCH)
    except (TypeError, ValueError):
        max_posts = DEFAULT_MAX_POSTS_PER_FETCH

    last_outcome = None
    if state is not None and state.last_outcome:
        try:
            last_outcome = OutcomeStatus(state.last_outcome)
        except ValueError:
            last_outcome = None

    return CadenceStats(
        post_count=int(source.get("post_count") or 0),
        mean_gap=timedelta(seconds=gap_seconds) if gap_seconds is not None else None,
        sample_size=int(source.get("cadence_sample_size") or 0),
        tier=tier,
        override_hours=_float_or_none(source.get("fetch_interval_hours_override")),
        max_posts_per_fetch=max_posts,
        last_success_at=_aware(state.last_success_at) if state else None,
        last_outcome=last_outcome,
        consecutive_failures=max(0, int(state.consecutive_failures or 0)) if state else 0,
        next_retry_at=_aware(state.next_retry_at) if state else None,
    )


def tier_for(mean_gap: timedelta | None, sample_size: int) -> CadenceTier:
    if mean_gap is None or sample_size < MIN_CADENCE_SAMPLES:
        return CadenceTier.UNKNOWN
    if mean_gap < FAST_BELOW:
        return CadenceTier.FAST
    if mean_gap <= MEDIUM_UP_TO:
        return CadenceTier.MEDIUM
    return CadenceTier.SLOW


def fetch_interval(stats: CadenceStats, profile: PolitenessProfile) -> tuple[timedelta, IntervalBasis]:
    """How long a successfully fetched source waits before it is due again."""
    if stats.override_hours is not None and stats.override_hours > 0:
        # Manual override wins: no floor, no guard.
        return timedelta(hours=stats.override_hours), "override"

    basis: IntervalBasis
    if stats.tier == CadenceTier.UNKNOWN or stats.mean_gap is None:
        base, basis = PROBATION_INTERVAL, "probation"
    else:
        base = min(max(stats.mean_gap * 0.5, TIER_INTERVAL_MIN), TIER_INTERVAL_MAX)
        basis = "tier"

    # The profile floor applies to probation too: an unknown YouTube channel is still
    # a yt-dlp run, the most expensive fetch there is.
    if profile.cadence_floor > base:
        base, basis = profile.cadence_floor, "profile_floor"

    # Backlog guard, applied last and allowed to go below the floor: poll a feed that exposes
    # N items while it is a quarter full, long before it can push out posts we never saw.
    if stats.mean_gap is not None and stats.tier != CadenceTier.UNKNOWN:
        window = stats.mean_gap * max(stats.max_posts_per_fetch, profile.min_posts_per_fetch)
        cap = window / BACKLOG_GUARD_SHARE
        if base > cap:
            base, basis = max(cap, BACKLOG_GUARD_MIN), "backlog_guard"

    return base, basis


def backoff_delay(consecutive_failures: int, *, rand: Callable[[], float] = random.random) -> timedelta:
    """min(base * 2^(n-1), cap) * U(0.85, 1.0); the cap rises to 7d for dormant sources.

    Jitter is applied to the capped delay and only downward, so the cap is a bound an
    operator can read as one, and a cohort at the cap does not wake in the same second.
    """
    n = int(consecutive_failures or 0)
    if n <= 0:
        return timedelta(0)
    cap = BACKOFF_DORMANT_MAX if n >= BACKOFF_DORMANT_AFTER else BACKOFF_MAX
    # Exponent clamped so a counter in the hundreds cannot overflow timedelta.
    raw = BACKOFF_BASE * (2 ** min(n - 1, 30))
    return min(raw, cap) * (0.85 + 0.15 * rand())


def unavailable_reason(profile: PolitenessProfile, availability: Availability) -> str | None:
    if profile.requires == "ytdlp" and not availability.ytdlp_enabled:
        return "yt-dlp disabled (INSIGHT_YTDLP_ENABLED=0)"
    if profile.requires == "telegram_creds" and not availability.telegram_credentials:
        return availability.telegram_reason or "no Telegram credentials or session"
    return None


def _hours(value: timedelta) -> str:
    return f"{value.total_seconds() / 3600:.1f}h"


def decide_fetch(
    stats: CadenceStats,
    profile: PolitenessProfile,
    now: datetime,
    *,
    force: bool,
    availability: Availability,
    requested_limit: int | None = None,
) -> FetchDecision:
    """Rules, in order: unavailable, never fetches, force, error state, new source, due check (§C.2)."""
    interval, basis = fetch_interval(stats, profile)
    post_limit = max(requested_limit or stats.max_posts_per_fetch, profile.min_posts_per_fetch)
    retry_at = stats.next_retry_at

    def decision(kind: DecisionKind, next_due_at: datetime | None, detail: str) -> FetchDecision:
        return FetchDecision(
            kind=kind,
            fetch=kind.fetches,
            post_limit=post_limit,
            interval=interval,
            interval_basis=basis,
            next_due_at=next_due_at,
            next_retry_at=retry_at,
            detail=detail,
        )

    # 1. Unavailable - even when forced, and never counted as backoff.
    reason = unavailable_reason(profile, availability)
    if reason is not None:
        return decision(DecisionKind.SKIP_UNAVAILABLE, None, f"Unavailable: {reason}")

    # 1b. A kind that never fetches (the Saved pages, issue 0031): nothing is ever due, even forced.
    if not profile.fetches:
        return decision(DecisionKind.SKIP_NOT_DUE, None, "Pages saved by hand; never fetched")

    # 2. Force ignores cadence and backoff.
    if force:
        return decision(DecisionKind.FETCH_FORCED, now, "Forced fetch")

    # 3. Error state: the ladder applies regardless of tier.
    if stats.consecutive_failures > 0 and retry_at is not None:
        if now < retry_at:
            return decision(
                DecisionKind.SKIP_BACKOFF,
                retry_at,
                f"Backoff until {retry_at.isoformat()} ({stats.consecutive_failures} consecutive failures)",
            )
        return decision(
            DecisionKind.FETCH_RETRY,
            retry_at,
            f"Retry after {stats.consecutive_failures} consecutive failures",
        )

    # 4. New source.
    if stats.last_success_at is None and stats.post_count == 0:
        return decision(DecisionKind.FETCH_NEW_SOURCE, now, "New source (0 posts)")

    # 5. Due check, counted from the last successful fetch (empty fetches count), DUE_SLACK early.
    due = (stats.last_success_at or _EPOCH) + interval
    if now >= due - DUE_SLACK:
        if stats.last_success_at is None:
            detail = f"No recorded successful fetch ({stats.post_count} posts, {_hours(interval)} {basis})"
        else:
            detail = (
                f"Due: last success {_hours(now - stats.last_success_at)} ago "
                f"({_hours(interval)} {basis})"
            )
        return decision(DecisionKind.FETCH_DUE, due, detail)
    return decision(
        DecisionKind.SKIP_NOT_DUE,
        due,
        f"Fetched {_hours(now - stats.last_success_at)} ago; next due in {_hours(due - now)} "
        f"({_hours(interval)} {basis})",
    )
