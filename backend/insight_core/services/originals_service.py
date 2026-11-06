"""A story's original, fetched when INSIGHT lacks it (issues 0114 and 0123). The rules are
utils/originals_rules.py; this file reads what they need, asks, and records every ask in story_originals.

    summary = await OriginalsService(db_url, saved=saved_service).run(http)

Run by ingestion after each story job (ingestion.default_runner), never by the API:
1. **Settle** the early fetches asked before: a page stored since is `found`, else, once its source was
   fetched after the ask, `missing` (its feed doesn't hold it: Discover's archive row shows it, 0114 decided 1).
2. **0114, a followed source's page a story links** (always on: the owner's decision, 2026-11-05): the
   source's fetch state gets `linked_wanted_at`, so the next tick's schedule decides `fetch_linked` for it
   and it goes through the normal fetch path (the fetcher, the host gates, the learned budgets, backoff).
3. **0123, a News story's original** (only when Collect originals is on, the scheduler's setting
   `collect_originals`, default off): a tweet from the quote a member holds (no request), else one page
   read through the save path's reader, under the host's gate; walled, no-article and unquoted-tweet
   originals are recorded with their reason and never asked again.

Both spend one credit (originals_rules.credit_after: 1% of the schedule's fetches, at most 3 at once); 0114's asks go first.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_fetch_state import FetchStateRepository
from insight_core.db.repo_linked import _followed, _own_pages, linked_not_stored
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.utils import originals_rules as rules
from insight_core.utils.addresses import host_of, site_of
from insight_core.utils.discover_rules import (app_address, archive_address, discover_address, document_address,
                                              reference_address)
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.originals")

SCHEDULER_KEY = "scheduler_config"   # OperationsService.SETTINGS_KEY_SCHEDULER: the row the dialog writes (0126: 0123 read "scheduler")
READS_KEY = "discover_reads"
COLLECT_SETTING = "collect_originals"   # read by originals_rules.collect_setting
BUDGET_KEY = "originals_budget"   # the shared credit (originals_rules.credit_after): {credit, counted_at}
EARLY_INTERVAL = timedelta(hours=24)   # schedule.TIER_INTERVAL_MIN: every tier's interval is at least this


def collect_on(cur: Any) -> bool:
    """Collect originals (issue 0123): the scheduler's setting, on unless you switched it off (0126)."""
    row = SystemSettingsRepository.get(cur, SCHEDULER_KEY)
    return rules.collect_setting(row[0] if row else None)


def accrue(cur: Any, now: datetime) -> float:
    """The shared credit now (originals_rules.credit_after), kept in system_settings: the schedule's fetches since
    it was last counted are the sources attempted since (a source attempted twice between two runs counts once,
    and page reads not at all: the credit errs low). The first count starts an hour back."""
    row = SystemSettingsRepository.get(cur, BUDGET_KEY)
    kept = (row[0] if row else None) or {}
    counted = datetime.fromisoformat(kept["counted_at"]) if kept.get("counted_at") else now - timedelta(hours=1)
    cur.execute("SELECT count(*) FROM source_fetch_state WHERE last_attempt_at > %s AND last_attempt_at <= %s", (counted, now))
    credit = rules.credit_after(float(kept.get("credit") or 0.0), cur.fetchone()[0])
    SystemSettingsRepository.upsert(cur, BUDGET_KEY, {"credit": credit, "counted_at": now.isoformat()})
    return credit


def spend(cur: Any, requests: int) -> None:
    """Spend extra requests from the credit."""
    if requests <= 0:
        return
    row = SystemSettingsRepository.get(cur, BUDGET_KEY)
    kept = (row[0] if row else None) or {}
    SystemSettingsRepository.upsert(cur, BUDGET_KEY, {**kept, "credit": float(kept.get("credit") or 0.0) - requests})


def site_reads(cur: Any) -> Dict[str, rules.SiteReads]:
    """What the server read of each site (Discover's reads): pages read and titled, the follow test."""
    row = SystemSettingsRepository.get(cur, READS_KEY)
    return rules.site_reads_of((row[0] if row else None) or {})


class OriginalsService:
    def __init__(self, db_url: str, *, saved: Any = None, gates: Any = None,
                 budget: Optional[Callable[[Any, datetime], float]] = None,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self.db_url = db_url
        self.saved = saved
        self.gates = gates
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.budget = budget or accrue   # the credit now (tests give their own)

    # ---- the run ------------------------------------------------------------------------

    async def run(self, http: Any = None) -> Dict[str, Any]:
        """Settle, then ask: 0114's early fetches, then (when on) 0123's collections, within the credit."""
        now = self.clock()
        with db.transaction(self.db_url) as cur:
            settled = self.settle(cur, now)
            credit = self.budget(cur, now)
            left = rules.whole(credit)
            linked = self.plan_linked(cur, now)
            asked = []
            for want in linked:
                if left <= 0:
                    break
                self._want_fetch(cur, want, now)
                asked.append(want["url"])
                left -= 1
            spend(cur, len(asked))
            on = collect_on(cur)
            collects = self.plan_collect(cur, now) if on else []
        collected = await self._collect(collects, http, left, now) if collects else []
        made = sum(c["requests"] for c in collected)
        if made:
            with db.transaction(self.db_url) as cur:
                spend(cur, made)
        summary = {"settled": settled, "credit": round(credit, 2), "fetch_linked": len(asked),
                   "linked_wanted": len(linked), "collect_on": on, "collect": collected}
        if asked or collected:
            logger.info("Originals: %s", summary)
        return summary

    # ---- 0114 ----------------------------------------------------------------------------

    def plan_linked(self, cur: Any, now: datetime) -> List[Dict[str, Any]]:
        """The followed sources to fetch early: one page each (its most linked), not asked before, linked by a
        story's post of another source in the last 72 hours, the source followed then; most linked first."""
        pages = linked_not_stored(cur, since=now - rules.LINK_RECENT)
        if not pages:
            return []
        by = sorted({pid for found in pages.values() for page in found for pid in page.by})
        cur.execute("SELECT p.id::text, p.source_id::text, p.created_at, sp.story_id::text FROM posts p "
                    "LEFT JOIN story_posts sp ON sp.post_id = p.id WHERE p.id = ANY(%s::uuid[])", (by,))
        posts = {pid: (sid, at, story) for pid, sid, at, story in cur.fetchall()}
        cur.execute("SELECT url FROM story_originals WHERE kind = 'fetch_linked'")
        asked = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT id::text, created_at FROM sources WHERE id = ANY(%s::uuid[])", (sorted(pages),))
        followed_at = dict(cur.fetchall())
        states = FetchStateRepository().load(cur, sorted(pages))
        out = []
        for source_id, found in pages.items():
            state = states.get(source_id)
            blocked = rules.early_fetch_blocked(
                now, last_attempt=state.last_attempt_at if state else None,
                failures=state.consecutive_failures if state else 0, retry_at=state.next_retry_at if state else None,
                linked_fetched_at=state.linked_fetched_at if state else None, interval=EARLY_INTERVAL)
            if blocked or (state and state.linked_wanted_at and (state.last_success_at is None
                                                                  or state.last_success_at < state.linked_wanted_at)):
                continue   # it waits for its schedule, or an early fetch is already wanted
            for page in found:
                url = rules.strip_access_tokens(page.url)
                if url in asked:
                    continue
                others = [posts[p] for p in page.by if p in posts and posts[p][0] != source_id]
                linking = [p for p in others if followed_at.get(source_id) and p[1] >= followed_at[source_id]]
                if not linking:
                    continue
                stories = sorted({p[2] for p in linking if p[2]})
                why = rules.linked_wanted(url, min(p[1] for p in linking), in_story=bool(stories),
                                          last_fetch=state.last_success_at if state else None)
                if why is None:
                    out.append({"source_id": source_id, "url": url, "story_id": stories[0], "posts": page.posts})
                    break
        out.sort(key=lambda w: (-w["posts"], w["url"]))
        return out

    @staticmethod
    def _want_fetch(cur: Any, want: Dict[str, Any], now: datetime) -> None:
        cur.execute("""INSERT INTO source_fetch_state (source_id, linked_wanted_at, linked_url, updated_at)
                       VALUES (%(s)s, %(now)s, %(url)s, %(now)s)
                       ON CONFLICT (source_id) DO UPDATE SET linked_wanted_at = EXCLUDED.linked_wanted_at,
                           linked_url = EXCLUDED.linked_url, updated_at = EXCLUDED.updated_at""",
                    {"s": want["source_id"], "now": now, "url": want["url"]})
        cur.execute("""INSERT INTO story_originals (kind, url, source_id, story_id, asked_at, requests, outcome)
                       VALUES ('fetch_linked', %s, %s, %s, %s, 1, 'wanted') ON CONFLICT (kind, url) DO NOTHING""",
                    (want["url"], want["source_id"], want["story_id"], now))

    @staticmethod
    def settle(cur: Any, now: datetime) -> int:
        """The early fetches asked: `found` when a post is at the page now, `missing` once the source was
        fetched after the ask and the page still isn't stored. Returns how many were settled."""
        cur.execute("""SELECT o.url, o.asked_at, st.last_success_at, (SELECT p.id FROM posts p WHERE p.normalized_url = o.url LIMIT 1)
                       FROM story_originals o LEFT JOIN source_fetch_state st ON st.source_id = o.source_id
                       WHERE o.kind = 'fetch_linked' AND o.outcome = 'wanted'""")
        n = 0
        for url, asked_at, success, post_id in cur.fetchall():
            if post_id is None and not (success and success > asked_at):
                continue
            cur.execute("UPDATE story_originals SET outcome = %s, post_id = %s, settled_at = %s WHERE kind = 'fetch_linked' AND url = %s",
                        ("found" if post_id else "missing", post_id, now, url))
            n += 1
        return n

    # ---- 0123 ----------------------------------------------------------------------------

    def plan_collect(self, cur: Any, now: datetime) -> List[Dict[str, Any]]:
        """Each News story's original not stored, not asked before, of a story started in the last week:
        {url, story_id, voices, kind, title, quoted}, the biggest stories first."""
        cur.execute("""
            WITH ns AS (SELECT n.id news_id, sp.story_id, s.voices, s.first_at, s.origin_url, s.origin_title
                        FROM news_stories n JOIN news_posts np ON np.news_id = n.id
                        JOIN story_posts sp ON sp.post_id = np.post_id JOIN stories s ON s.id = sp.story_id
                        GROUP BY 1, 2, 3, 4, 5, 6)
            SELECT DISTINCT ON (news_id) story_id::text, voices, first_at, origin_url, origin_title
            FROM ns ORDER BY news_id, voices DESC, story_id""")
        rows = [r for r in cur.fetchall() if r[3] and r[2] >= now - rules.COLLECT_WITHIN]
        if not rows:
            return []
        urls = sorted({r[3] for r in rows})
        cur.execute("SELECT normalized_url FROM posts WHERE normalized_url = ANY(%s)", (urls,))
        stored = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT url FROM story_originals WHERE kind = 'collect'")
        asked = {r[0] for r in cur.fetchall()}
        rows = [r for r in rows if r[3] not in stored and rules.strip_access_tokens(r[3]) not in asked]
        if not rows:
            return []
        stories = [r[0] for r in rows]
        cur.execute("""SELECT sp.story_id::text, pl.target_url FROM story_posts sp JOIN post_links pl ON pl.post_id = sp.post_id
                       WHERE sp.story_id = ANY(%s::uuid[])""", (stories,))
        linked_as: Dict[str, List[str]] = {}
        for story_id, target in cur.fetchall():
            linked_as.setdefault(story_id, []).append(target)
        cur.execute("""SELECT sp.story_id::text, pp.quoted_words FROM story_posts sp JOIN post_parts pp ON pp.post_id = sp.post_id
                       WHERE sp.story_id = ANY(%s::uuid[]) AND pp.quoted_words IS NOT NULL""", (stories,))
        quoted: Dict[str, Dict[str, str]] = {}
        for story_id, words in cur.fetchall():
            for url, text in (words or {}).items():
                if len(text or "") > len(quoted.setdefault(story_id, {}).get(url, "")):
                    quoted[story_id][url] = text
        followed = _followed(cur)
        own = _own_pages(cur, followed)[0] if followed else None
        reads = site_reads(cur)
        kept = DiscoverRepository.kept(cur) or {}
        platforms = {host: tuple(prefix) for host, prefix in (kept.get("platforms") or {}).items()}
        out = []
        for story_id, voices, first_at, url, title in rows:
            same = [t for t in linked_as.get(story_id, ()) if (normalize_url(t) or t) == url]
            words = quoted.get(story_id, {}).get(url)
            kind = rules.trigger_kind(url, owner=own.owner(url) if own else None,
                                      names_account=discover_address(url, platforms)[0] is not None,
                                      article=not (archive_address(url) or app_address(url) or document_address(url)
                                                   or reference_address(url)),
                                      reads=reads.get(site_of(host_of(url)), rules.SiteReads()),
                                      linked_as=same, quoted=words)
            out.append({"url": rules.strip_access_tokens(url), "story_id": story_id, "voices": voices,
                        "first_at": first_at, "kind": kind, "title": title, "quoted": words})
        out.sort(key=lambda c: (-c["voices"], -c["first_at"].timestamp(), c["url"]))
        return out

    async def _collect(self, plan: List[Dict[str, Any]], http: Any, left: int, now: datetime) -> List[Dict[str, Any]]:
        """Each planned original: a quote stored, a page read (while the budget lasts), or the reason none is."""
        done = []
        for c in plan:
            outcome, requests, post_id, detail = c["kind"], 0, None, None
            if c["kind"] == rules.FOLLOWED:
                continue   # 0114's: its source is fetched when a story links it
            if c["kind"] == rules.FROM_QUOTE and self.saved is not None:
                result = self.saved.collect_quote(c["url"], c["quoted"] or "", title=c["title"],
                                                  at=rules.tweet_time(c["url"]) or now)
                outcome, post_id = result["status"], result.get("post_id")
            elif c["kind"] == rules.PAGE:
                if left <= 0 or self.saved is None or http is None:
                    continue   # asked again on a later run, while its story is in its first week
                try:
                    result = await self._read(http, c)
                except Exception as error:  # noqa: BLE001 - one page's failure is recorded, never raised
                    result = {"status": "failed", "reason": str(error)[:200], "requests": 1}
                outcome, post_id = result["status"], result.get("post_id")
                requests, detail = int(result.get("requests", 1)), result.get("reason")
                left -= requests
            with db.transaction(self.db_url) as cur:
                cur.execute("""INSERT INTO story_originals (kind, url, story_id, post_id, asked_at, requests, outcome, detail, settled_at)
                               VALUES ('collect', %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (kind, url) DO NOTHING""",
                            (c["url"], c["story_id"], post_id, now, requests, outcome, detail, now))
            done.append({"url": c["url"], "outcome": outcome, "requests": requests})
        return done

    async def _read(self, http: Any, c: Dict[str, Any]) -> Dict[str, Any]:
        """One page through the save path's reader, holding its host's gate as a fetch does."""
        if self.gates is None:
            return await self.saved.collect(http, c["url"], c["title"])
        from insight_core.ingestion.kinds.base import PolitenessProfile

        async with self.gates.slot(PolitenessProfile(concurrency_pool="host-lock"), host_of(c["url"])):
            return await self.saved.collect(http, c["url"], c["title"])


def run_originals(db_url: str) -> Callable[[], Any]:
    """The ingestion runner's hook: an OriginalsService on the process's gates and a save path."""
    async def run() -> Dict[str, Any]:
        from insight_core.ingestion.gates import FetchGates
        from insight_core.ingestion.http import KindHttp
        from insight_core.ingestion.kinds import KindRegistry
        from insight_core.services.saved_service import SavedService
        from insight_core.services.source_config_sync_service import SourceConfigSyncService
        from insight_core.services.sources_service import SourcesService
        from insight_core.services.youtube_service import YouTubeService

        http = KindHttp()
        saved = SavedService(db_url, sources=SourcesService(db_url), source_config_sync=SourceConfigSyncService(db_url),
                             kinds=KindRegistry.default(http, YouTubeService(db_url), db_url=db_url))
        return await OriginalsService(db_url, saved=saved, gates=FetchGates.shared()).run(http)
    return run


__all__ = ["OriginalsService", "accrue", "collect_on", "run_originals", "site_reads", "spend"]
