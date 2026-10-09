"""The source-kind seam.

B1 needs only the declarative PolitenessProfile, because decide_fetch reads its cadence
floor, minimum posts per fetch and requirement. B3 adds RateLimit, Inspection,
ArchivePage, the SourceKind protocol and KindUnavailable here, plus rate_limit() and
estimate_seconds() on the profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal


@dataclass(frozen=True)
class PolitenessProfile:
    """How hard a kind may hit its sources. Holds nothing host-keyed (see HOST_FLOORS)."""

    concurrency_pool: Literal["host-lock", "ytdlp"]
    page_delay_s: float = 0.0
    batch_size: int = 0                  # 0 = no batch cooldown
    batch_cooldown_s: float = 0.0
    live_pages_rate_limited: bool = False
    cadence_floor: timedelta = timedelta(0)
    min_posts_per_fetch: int = 0
    requires: Literal["none", "ytdlp", "telegram_creds"] = "none"
    blocking_io: bool = False            # run fetch/inspect in a thread
