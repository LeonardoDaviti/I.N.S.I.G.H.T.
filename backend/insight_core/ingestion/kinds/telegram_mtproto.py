"""telegram_mtproto: bare Telegram handles (platform telegram, no "://") read over MTProto.

B3 ships the kind's resolution, host key and politeness profile only. Every fetch raises
KindUnavailable; none is reached, because Availability.telegram_credentials stays False
until B8 builds the real kind (session lifecycle, flood-wait handling) from
connectors/telegram_connector.py. Telethon is never imported here.

Mark VIII classify_source had no MTProto branch, so these handles fell through to
generic_rss and failed as RSS URLs; resolving them here is the intentional divergence.
"""
from __future__ import annotations

from typing import Any, Dict, List

from insight_core.ingestion.kinds.base import BaseKind, Inspection, KindUnavailable, PolitenessProfile, Source

# The connector's 10-request / 18s throttle becomes the batch cooldown. Every MTProto source
# shares one client, so the host key is one constant (2s floor in gates.HOST_FLOORS).
TELEGRAM_MTPROTO_PROFILE = PolitenessProfile(
    concurrency_pool="host-lock",
    page_delay_s=1,
    batch_size=10,
    batch_cooldown_s=18,
    live_pages_rate_limited=True,
    requires="telegram_creds",
)

TELEGRAM_HOST_KEY = "platform:telegram"
NOT_YET = "Telegram MTProto is not wired up yet (Mark IX slice B8)"


class TelegramMtprotoKind(BaseKind):
    name = "telegram_mtproto"
    profile = TELEGRAM_MTPROTO_PROFILE

    def matches(self, source: Source) -> bool:
        return source.get("platform") == "telegram" and "://" not in str(source.get("handle_or_url") or "")

    def host_key(self, source: Source) -> str:
        return TELEGRAM_HOST_KEY

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        raise KindUnavailable(NOT_YET)

    async def inspect(self, source: Source) -> Inspection:
        raise KindUnavailable(NOT_YET)

    async def archive_pages(self, source, target, checkpoint, rate):
        raise KindUnavailable(NOT_YET)
        yield  # pragma: no cover - makes this an async generator
