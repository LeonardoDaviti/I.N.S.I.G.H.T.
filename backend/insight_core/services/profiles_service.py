"""Channel profiles (issue 0132 C2): each source's profile or about page fetched once a month, every answer kept.

    summary = await ProfilesService(db_url, http=KindHttp(), gates=FetchGates.shared(), registry=registry).run()

Run by the ingestion scheduler after its tick (scripts/run_scheduler.py), never by the API, while the switch is on
(system_settings `channel_profiles` {on}; **on by default**, the owner's ask of 2026-11-08):
- **Which:** the enabled sources with a profile (ingestion/profiles.ask_for: Nitter, YouTube, the Telegram bridge or
  MTProto, a site's home page; never Reddit, Hacker News or Saved) never read, read over PROFILE_EVERY ago, or failed
  over FAILED_RETRY ago; never read first, then the oldest. At most PER_RUN a run, so the profiles never crowd the
  hourly fetches (an hourly tick reads 6: a server of 250 sources is read in two days, then a month later).
- **How:** the normal fetch path: KindHttp, the source's host gate (its floor: Nitter 10 s, the bridge 5 s), a
  limiting host (429, a timeout) waited out by the host limiter and left for the run; MTProto on its own session
  (a session another run holds: the channels wait for the next run).
- **Kept:** source_profiles (migration 0086): a new answer closes the source's last (valid_to) and adds a row; a
  failure is a row closed at once. Nothing is deleted.

What reads them: the voices' suggestions (utils/voice_rules.profile_verdicts, not_followed) and the Audience card
(markx/source_stats.py).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from insight_core.db import database as db
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.ingestion import profiles as P
from insight_core.utils.post_links import source_kind

logger = logging.getLogger("insight.profiles")

SETTING_KEY = "channel_profiles"
DEFAULT_ON = True
PROFILE_EVERY = timedelta(days=30)
FAILED_RETRY = timedelta(days=7)
PER_RUN = 6
HOME_HOST_SHARE = 0.5   # a site whose posts live on another host than its feed: its home is that host's


def setting_on(cur: Any) -> bool:
    row = SystemSettingsRepository.get(cur, SETTING_KEY)
    value = (row[0] if row else None) or {}
    return bool(value.get("on", DEFAULT_ON))


def set_setting(cur: Any, on: bool) -> bool:
    SystemSettingsRepository.upsert(cur, SETTING_KEY, {"on": bool(on)})
    return bool(on)


def table_exists(cur: Any) -> bool:
    cur.execute("SELECT to_regclass('public.source_profiles') IS NOT NULL")
    return bool(cur.fetchone()[0])


def current(cur: Any, source_ids: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, Any]]:
    """source id -> its current profile {kind, url, name, bio, website, links, followers, followers_label,
    fetched_at}; {} when migration 0086 is not there."""
    if not table_exists(cur):
        return {}
    cur.execute("""SELECT source_id::text, kind, url, name, bio, website, links, followers, followers_label, fetched_at
                     FROM source_profiles WHERE valid_to IS NULL AND status = 'ok'
                      AND (%(ids)s::uuid[] IS NULL OR source_id = ANY(%(ids)s::uuid[]))""",
                {"ids": list(source_ids) if source_ids is not None else None})
    out = {}
    for sid, kind, url, name, bio, website, links, followers, label, at in cur.fetchall():
        out[sid] = {"kind": kind, "url": url, "name": name, "bio": bio, "website": website, "links": list(links or []),
                    "followers": followers, "followers_label": label, "fetched_at": at.isoformat() if at else None}
    return out


def due(cur: Any, now: datetime, limit: int) -> List[Dict[str, Any]]:
    """The enabled sources whose profile is due (never read, read PROFILE_EVERY ago, failed FAILED_RETRY ago),
    never read first, then the oldest; with `home`, a site's posts' own host when it is not its feed's."""
    cur.execute("""
        SELECT s.id::text, s.platform, s.handle_or_url, s.settings, last.fetched_at, last.status
          FROM sources s
          LEFT JOIN LATERAL (SELECT fetched_at, status FROM source_profiles sp WHERE sp.source_id = s.id
                              ORDER BY fetched_at DESC LIMIT 1) last ON TRUE
         WHERE s.enabled AND s.platform <> ALL(%(skip)s)
           AND (last.fetched_at IS NULL
                OR (last.status = 'ok' AND last.fetched_at <= %(ok)s)
                OR (last.status = 'failed' AND last.fetched_at <= %(failed)s))
         ORDER BY last.fetched_at NULLS FIRST, s.created_at, s.id""",
                {"skip": ["reddit", "saved", "hn"], "ok": now - PROFILE_EVERY, "failed": now - FAILED_RETRY})
    rows = [{"id": sid, "platform": platform, "handle_or_url": handle, "settings": settings or {}}
            for sid, platform, handle, settings, _, _ in cur.fetchall()
            if source_kind(platform, handle) not in ("reddit", "hn", "saved")]
    # A site's home: the host half its posts live on, when it is not its feed's (a feed elsewhere).
    sites = [r["id"] for r in rows if source_kind(r["platform"], r["handle_or_url"]) == "site"]
    if sites:
        cur.execute("""SELECT source_id::text, lower(substring(url from '^https?://([^/?#:]+)')) AS host, count(*)
                         FROM posts WHERE source_id = ANY(%s::uuid[]) AND url IS NOT NULL GROUP BY 1, 2""", (sites,))
        hosts: Dict[str, Dict[str, int]] = {}
        for sid, host, n in cur.fetchall():
            if host:
                hosts.setdefault(sid, {})[host] = n
        for r in rows:
            got = hosts.get(r["id"])
            if got:
                host, n = max(got.items(), key=lambda kv: (kv[1], kv[0]))
                if n / sum(got.values()) >= HOME_HOST_SHARE:
                    r["home"] = f"https://{host}/"
    return rows[:limit] if limit else rows


def record(cur: Any, source_id: str, ask: P.Ask, now: datetime, *, profile: Optional[P.Profile] = None,
           error: Optional[str] = None) -> None:
    """One answer kept: a profile closes the source's current one and is the current; a failure is closed at once."""
    if profile is not None:
        cur.execute("UPDATE source_profiles SET valid_to = %s WHERE source_id = %s AND valid_to IS NULL AND status = 'ok'",
                    (now, source_id))
        cur.execute("""INSERT INTO source_profiles (source_id, kind, url, status, name, bio, website, links, followers,
                                                    followers_label, fetched_at)
                       VALUES (%s, %s, %s, 'ok', %s, %s, %s, %s::jsonb, %s, %s, %s)""",
                    (source_id, profile.kind, profile.url, profile.name, profile.bio, profile.website,
                     json.dumps(profile.links), profile.followers, profile.followers_label, now))
    else:
        cur.execute("""INSERT INTO source_profiles (source_id, kind, url, status, error, fetched_at, valid_to)
                       VALUES (%s, %s, %s, 'failed', %s, %s, %s)""",
                    (source_id, ask.kind, ask.url, (error or "failed")[:500], now, now))


class ProfilesService:
    def __init__(self, db_url: str, *, http: Any, gates: Any, registry: Any, per_run: int = PER_RUN,
                 clock: Optional[Callable[[], datetime]] = None,
                 cursor: Optional[Callable[[], Any]] = None) -> None:
        self.db_url = db_url
        self.http = http
        self.gates = gates
        self.registry = registry
        self.per_run = per_run
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._cursor = cursor or (lambda: db.transaction(self.db_url))

    def plan(self) -> List[tuple]:
        """[(source, kind, ask)] for this run, at most per_run, or [] when the switch is off."""
        now = self.clock()
        with self._cursor() as cur:
            if not table_exists(cur) or not setting_on(cur):
                return []
            rows = due(cur, now, 0)
        out = []
        for source in rows:
            try:
                kind = self.registry.resolve(source)
            except LookupError:
                continue
            ask = P.ask_for(source, kind.name, kind.host_key(source), home=source.get("home"))
            if ask is not None:
                out.append((source, kind, ask))
            if len(out) >= self.per_run:
                break
        return out

    async def run(self) -> Dict[str, Any]:
        from insight_core.ingestion.http import HttpError
        from insight_core.ingestion.kinds.base import KindUnavailable, PolitenessProfile

        planned = self.plan()
        done: Dict[str, int] = {"ok": 0, "failed": 0, "waiting": 0}
        limited: set = set()
        sessions: Dict[str, Any] = {}
        try:
            for source, kind, ask in planned:
                if ask.host_key in limited:
                    done["waiting"] += 1
                    continue
                profile, error = None, None
                try:
                    if ask.kind == "telegram_mtproto":
                        if kind.name not in sessions:
                            session = kind.session()
                            try:
                                await session.open()
                            except KindUnavailable:
                                session = None
                            sessions[kind.name] = session
                        if sessions[kind.name] is None:
                            done["waiting"] += 1
                            continue
                        async with self.gates.slot(kind.profile, ask.host_key):
                            full = await kind.channel_full(source)
                        profile = P.parse_telegram_full(full, "t.me/" + str(source["handle_or_url"]).lstrip("@"))
                    else:
                        async with self.gates.slot(PolitenessProfile(concurrency_pool="host-lock"), ask.host_key):
                            body, final = await self.http.get_start(ask.url, P.PROFILE_MAX_BYTES)
                        page = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
                        profile = P.PARSERS[ask.kind](page, final or ask.url)
                except HttpError as exc:
                    error = str(exc)
                    if exc.limiting:
                        self.gates.host_limiter.limited(ask.host_key, exc.retry_after)
                        limited.add(ask.host_key)
                except Exception as exc:  # noqa: BLE001 - one profile's failure is recorded, never raised
                    error = f"{type(exc).__name__}: {exc}"
                with self._cursor() as cur:
                    record(cur, source["id"], ask, self.clock(), profile=profile, error=error)
                done["ok" if profile is not None else "failed"] += 1
        finally:
            for session in sessions.values():
                if session is not None:
                    try:
                        await session.close()
                    except Exception:  # noqa: BLE001
                        logger.exception("Profiles: the Telegram session did not close")
        summary = {"planned": len(planned), **done}
        if planned:
            logger.info("Channel profiles: %s", summary)
        return summary


async def run_after_tick(db_url: str, registry: Any = None) -> Dict[str, Any]:
    """The scheduler's hook: one capped run on the process's gates (shared with the ticks' fetches)."""
    from insight_core.ingestion.gates import FetchGates
    from insight_core.ingestion.http import KindHttp
    if registry is None:
        from insight_core.ingestion.kinds import KindRegistry
        from insight_core.services.youtube_service import YouTubeService
        registry = KindRegistry.default(KindHttp(), YouTubeService(db_url), db_url=db_url)
    return await ProfilesService(db_url, http=KindHttp(), gates=FetchGates.shared(), registry=registry).run()


__all__ = ["ProfilesService", "current", "due", "record", "run_after_tick", "set_setting", "setting_on",
           "SETTING_KEY", "PER_RUN", "PROFILE_EVERY"]
