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

4. **0138, an entity's original** (under the same switch): a Mark X entity's original (its paper or release page,
   markx/entity_addresses.py) that 2+ voices made the subject of their posts in 7 days, or one voice's News lead, not
   stored: read as 0123 reads a page, recorded once in story_originals (kind `entity`, its entity_id). After 0123's.
5. **0138 C, Look up unlinked originals** (its own switch `lookup_originals`, default off): a document entity of 2+
   voices with no address: one title lookup (the arXiv API, else Crossref), recorded once (kind `lookup`).
6. **0138 D2**: the sites that were the address of 3+ originals in 30 days, kept for Discover (`originals_suppliers`).

All spend one credit (originals_rules.credit_after: 1% of the schedule's fetches, at most 3 at once, 6 while an
entity's original has waited over 72 hours); 0114's asks go first.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_fetch_state import FetchStateRepository
from insight_core.db.repo_linked import _followed, _own_pages, linked_not_stored
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.utils import originals_rules as rules
from insight_core.utils import entity_originals as E
from insight_core.utils.addresses import host_of, site_of
from insight_core.utils.discover_rules import (app_address, archive_address, discover_address, document_address,
                                              reference_address)
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.originals")

SCHEDULER_KEY = "scheduler_config"   # OperationsService.SETTINGS_KEY_SCHEDULER: the row the dialog writes (0126: 0123 read "scheduler")
READS_KEY = "discover_reads"
COLLECT_SETTING = "collect_originals"   # read by originals_rules.collect_setting
BUDGET_KEY = "originals_budget"   # the shared credit (originals_rules.credit_after): {credit, counted_at}
CITED_KEY = "longread_citations"   # 0138 F3: {key: {n, posts}}: the sites the long-reads you opened cite
SUPPLIERS_KEY = "originals_suppliers"   # 0138 D2: {at, current: {key: {n, urls, since}}, suggested: {key: first at}}
EARLY_INTERVAL = timedelta(hours=24)   # at most one early fetch a day per source (was schedule.TIER_INTERVAL_MIN until 2026-11-11)


def collect_on(cur: Any) -> bool:
    """Collect originals (issue 0123): the scheduler's setting, on unless you switched it off (0126)."""
    row = SystemSettingsRepository.get(cur, SCHEDULER_KEY)
    return rules.collect_setting(row[0] if row else None)


def lookup_on(cur: Any) -> bool:
    """Look up unlinked originals (issue 0138 C): off unless you switched it on."""
    row = SystemSettingsRepository.get(cur, SCHEDULER_KEY)
    return rules.lookup_setting(row[0] if row else None)


def classics_on(cur: Any) -> bool:
    """Store Classics (issue 0138 E1): on unless you switched it off."""
    row = SystemSettingsRepository.get(cur, SCHEDULER_KEY)
    return rules.classics_setting(row[0] if row else None)


def accrue(cur: Any, now: datetime, cap: float = rules.EXTRA_CREDIT_CAP) -> float:
    """The shared credit now (originals_rules.credit_after), kept in system_settings: the schedule's fetches since
    it was last counted are the sources attempted since (a source attempted twice between two runs counts once,
    and page reads not at all: the credit errs low). The first count starts an hour back."""
    row = SystemSettingsRepository.get(cur, BUDGET_KEY)
    kept = (row[0] if row else None) or {}
    counted = datetime.fromisoformat(kept["counted_at"]) if kept.get("counted_at") else now - timedelta(hours=1)
    cur.execute("SELECT count(*) FROM source_fetch_state WHERE last_attempt_at > %s AND last_attempt_at <= %s", (counted, now))
    credit = rules.credit_after(float(kept.get("credit") or 0.0), cur.fetchone()[0], cap)
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


class _NeverFront:
    """{site word: the types of the entities whose key squashes to it, of NEVER_FRONT_TYPES} (E5), asked per word of
    a page's book (v10.17, 0186: was a walk of the whole book)."""

    def __init__(self, book: Any) -> None:
        self.book, self.got = book, {}

    def get(self, word: Any, default: Any = None) -> Any:
        from insight_core.utils import entity_originals as E
        if word not in self.got:
            ids = self.book.by_squashed_key([word]) if word else []
            self.got[word] = {t for t in (self.book.ents[x].type for x in ids) if t in E.NEVER_FRONT_TYPES} or None
        got = self.got[word]
        return default if got is None else got


class OriginalsService:
    def __init__(self, db_url: str, *, saved: Any = None, gates: Any = None,
                 budget: Optional[Callable[[Any, datetime], float]] = None,
                 clock: Optional[Callable[[], datetime]] = None, sleep: Any = None) -> None:
        self.db_url = db_url
        self.saved = saved
        self.gates = gates
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cap = rules.EXTRA_CREDIT_CAP
        self.sleep = sleep or asyncio.sleep
        self.budget = budget or (lambda cur, now: accrue(cur, now, self.cap))   # the credit now (tests give their own)

    # ---- the run ------------------------------------------------------------------------

    async def run(self, http: Any = None) -> Dict[str, Any]:
        """Settle, then ask: 0114's early fetches, then (when on) 0123's collections and 0138's entity originals, and
        (when its switch is on) 0138's title lookups, within the credit."""
        now = self.clock()
        with db.transaction(self.db_url) as cur:
            settled = self.settle(cur, now)
            on = collect_on(cur)
            entities, lookups = self.plan_entities(cur, now) if on else ([], [])
            waits = [now - e["first_at"] for e in entities if e["kind"] == rules.PAGE]
            self.cap = E.credit_cap(max(waits) if waits else None, rules.EXTRA_CREDIT_CAP)
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
            collects = self.plan_collect(cur, now) if on else []
            looking = lookup_on(cur)
            storing = classics_on(cur)
            allowance = self.backfill_left(cur, now) if storing else 0
            backfill: List[Dict[str, Any]] = []
            if allowance and http is not None:
                kind_of = self._classifier(cur)
                backfill = ((self.plan_works(cur, now, kind_of) if on else []) + self.plan_references(cur, now, kind_of)
                            + self.plan_missed(cur, now, kind_of) + self.plan_classics(cur, now, kind_of))
                taken = {c["url"] for c in collects + entities}   # asked above under the credit (0123, B)
                backfill = [c for c in backfill if c["url"] not in taken and not taken.add(c["url"])]   # once each
        collected = await self._collect(collects + entities, http, left, now) if collects or entities else []
        made = sum(c["requests"] for c in collected)
        looked: List[Dict[str, Any]] = []
        if looking and lookups:
            looked = await self._lookups(lookups, http, left - made, now)
            made += sum(c["requests"] for c in looked)
        if made:
            with db.transaction(self.db_url) as cur:
                spend(cur, made)
        stored = await self._collect(backfill, http, allowance, now, pause=E.PAGE_DELAY_S) if backfill else []
        try:
            with db.transaction(self.db_url) as cur:
                supplying = self.keep_suppliers(cur, now)
                supplying["cited"] = self.keep_cited(cur)
        except Exception:  # noqa: BLE001 - derived, for Discover; the next run makes it again
            logger.exception("Originals: the supplying sites were not kept")
            supplying = None
        summary = {"settled": settled, "credit": round(credit, 2), "fetch_linked": len(asked),
                   "linked_wanted": len(linked), "collect_on": on, "collect": collected,
                   "entity_wanted": len(entities), "lookup_on": looking, "lookup": looked, "cap": self.cap,
                   "entity_wait_hours": round(max(waits).total_seconds() / 3600, 1) if waits else None,
                   "suppliers": supplying, "classics_on": storing, "backfill": stored}
        if asked or collected or looked or stored:
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
        # The members' links as written (0126: a gift link's token is out of target_url, kept in shared_url).
        cur.execute("""SELECT sp.story_id::text, COALESCE(pl.shared_url, pl.target_url) FROM story_posts sp JOIN post_links pl ON pl.post_id = sp.post_id
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
        kind_of = self._classifier(cur)
        out = []
        for story_id, voices, first_at, url, title in rows:
            same = [t for t in linked_as.get(story_id, ()) if (normalize_url(t) or t) == url]
            words = quoted.get(story_id, {}).get(url)
            kind = kind_of(url, same, words)
            out.append({"url": rules.strip_access_tokens(url), "story_id": story_id, "voices": voices,
                        "first_at": first_at, "kind": kind, "title": title, "quoted": words})
        out.sort(key=lambda c: (-c["voices"], -c["first_at"].timestamp(), c["url"]))
        return out

    @staticmethod
    def _classifier(cur: Any) -> Callable[..., str]:
        """originals_rules.trigger_kind with what it reads of the database: the followed sources' own pages, the
        server's reads of each site, Discover's platforms. A paper's page is an article here (0138 B3: none of the
        not-an-article shapes is a paper's)."""
        followed = _followed(cur)
        own = _own_pages(cur, followed)[0] if followed else None
        reads = site_reads(cur)
        kept = DiscoverRepository.kept(cur) or {}
        platforms = {host: tuple(prefix) for host, prefix in (kept.get("platforms") or {}).items()}

        def kind_of(url: str, linked_as: Any = (), quoted: Optional[str] = None) -> str:
            return rules.trigger_kind(url, owner=own.owner(url) if own else None,
                                      names_account=discover_address(url, platforms)[0] is not None,
                                      article=not (archive_address(url) or app_address(url) or document_address(url)
                                                   or reference_address(url)),
                                      reads=reads.get(site_of(host_of(url)), rules.SiteReads()),
                                      linked_as=list(linked_as), quoted=quoted)
        kind_of.owner = (lambda url: own.owner(url) if own else None)   # type: ignore[attr-defined]  # 0138 F2
        return kind_of

    # ---- 0138 ----------------------------------------------------------------------------

    def plan_entities(self, cur: Any, now: datetime, *, listing: bool = False
                      ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """(the entities' originals to collect, the document entities to look up by title). `listing` (Discover's
        Pages, 0138 D1): every original not stored, asked before or not, unclassified (no `kind`).

        An entity triggers (entity_originals.triggered) when it is the `subject` of current Mark X mentions on posts
        of 2+ voices (sources, Saved aside) in the last 7 days, or of one voice's post that leads a News row (the
        row's first report by position). Its original (markx/entity_addresses.py: a paper page, else a release
        page), not stored and not asked before (as 0123's or 0138's), is planned like 0123's page; `first_at` is when
        it triggered (the second voice's first post, else the lead). A document entity of 2+ voices with no address
        is a lookup (C). Entities by voices, then the newest."""
        from insight_core.markx import entity_addresses as EA, identity as I, schemas
        from insight_core.markx.pairing import SPECIFIC_TYPES
        since = now - E.TRIGGER_WITHIN
        cur.execute("""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, p.source_id::text,
                              COALESCE(p.surfaced_at, p.published_at, p.fetched_at), m.by_name, m.type
                         FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id JOIN sources s ON s.id = p.source_id
                        WHERE m.guide = ANY(%s) AND m.role = 'subject' AND m.type = ANY(%s) AND m.entity_id IS NOT NULL
                          AND s.platform <> 'saved' AND COALESCE(p.surfaced_at, p.published_at, p.fetched_at) >= %s""",
                    (schemas.mention_guides(), schemas.stored_types(SPECIFIC_TYPES), since))
        rows = cur.fetchall()
        if not rows:
            return [], []
        cur.execute("""SELECT DISTINCT ON (news_id) post_id::text FROM news_posts
                        ORDER BY news_id, role <> 'report', position NULLS LAST, post_id""")
        leads = {r[0] for r in cur.fetchall()}
        book = I.lazy_book(cur)   # v10.17 (0186): the mentions' entities, not the whole book
        book.prime(ids=[book.pins.get((pid, guide, n), eid) for pid, guide, n, eid, *_ in rows])
        ents: Dict[str, Dict[str, Any]] = {}
        for pid, guide, n, eid, source, at, by, type_ in rows:
            root = book.root(book.pins.get((pid, guide, n), eid))
            if root not in book.ents or book.ents[root].status == "not_entity":
                continue
            e = ents.setdefault(root, {"first": {}, "lead": None, "by": [], "document": False})
            e["first"][source] = min(at, e["first"].get(source, at))
            if pid in leads:
                e["lead"] = min(at, e["lead"] or at)
            if by and by not in e["by"]:
                e["by"].append(by)
            e["document"] |= schemas.entity_type(type_) == "document"
        due: Dict[str, Dict[str, Any]] = {}
        for root, e in ents.items():
            voices = len(e["first"])
            if not E.triggered(voices, e["lead"] is not None):
                continue
            firsts = sorted(e["first"].values())
            due[root] = {**e, "voices": voices, "at": firsts[1] if voices >= E.TRIGGER_VOICES else e["lead"]}
        if not due:
            return [], []
        found = EA.current(cur, book, due)
        originals: Dict[str, str] = {}
        lookups = []
        for root, d in due.items():
            got = E.original_of(E.pick((k, u, r, at) for k, u, r, at, _ in found.get(root, ())))
            if got:
                originals[root] = normalize_url(got[1]) or got[1]
            elif d["document"] and d["voices"] >= E.TRIGGER_VOICES and not found.get(root):
                lookups.append({"entity_id": root, "name": book.ents[root].name, "by": d["by"], "voices": d["voices"],
                                "first_at": d["at"]})
        out = []
        if originals:
            urls = sorted(set(originals.values()))
            cur.execute("SELECT normalized_url FROM posts WHERE normalized_url = ANY(%s)", (urls,))
            stored = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT url FROM story_originals WHERE kind IN ('collect', 'entity') AND url = ANY(%s)", (urls,))
            asked = set() if listing else {r[0] for r in cur.fetchall()}
            kind_of = None if listing else self._classifier(cur)
            planned: set = set()
            for root, url in originals.items():
                url = rules.strip_access_tokens(url)
                if url in stored or url in asked or url in planned:
                    continue
                planned.add(url)
                d = due[root]
                out.append({"url": url, "story_id": None, "voices": d["voices"], "first_at": d["at"],
                            "kind": kind_of(url) if kind_of else None, "title": None, "quoted": None,
                            "record": "entity", "entity_id": root, "name": book.ents[root].name,
                            "sources": sorted(d["first"])})
        if lookups:
            cur.execute("SELECT url FROM story_originals WHERE kind = 'lookup'")
            asked = {r[0] for r in cur.fetchall()}
            lookups = [x for x in lookups if f"entity:{x['entity_id']}" not in asked]
        order = lambda x: (-x["voices"], -x["first_at"].timestamp(), x.get("url") or x["entity_id"])  # noqa: E731
        return sorted(out, key=order), sorted(lookups, key=order)

    async def _lookups(self, plan: List[Dict[str, Any]], http: Any, left: int, now: datetime) -> List[Dict[str, Any]]:
        """0138 C: each document entity's title looked up (the arXiv API, then Crossref when it found none), one credit
        a request; a match (entity_originals.lookup_match: the title by the name key and an author of `by`) is stored
        as its address (rule `lookup`) and collected by the next run. Recorded once: found or not_found."""
        from insight_core.markx import entity_addresses as EA
        from insight_core.markx import names as N
        done = []
        for x in plan:
            by = [n for b in x["by"] for n in E.by_names(b)]
            if not by or http is None or left <= 0:
                continue   # no author to check a match by, or no credit now: asked on a later run
            url, requests, detail = None, 0, None
            for query, parse, as_json in ((E.arxiv_query(x["name"]), E.parse_arxiv, False),
                                          (E.crossref_query(x["name"]), E.parse_crossref, True)):
                if left - requests <= 0:
                    break
                requests += 1
                try:
                    answer = await (http.get_json(query) if as_json else http.get_text(query))
                except Exception as error:  # noqa: BLE001 - recorded, never raised
                    detail = str(error)[:200]
                    continue
                url = E.lookup_match(x["name"], by, parse(answer if as_json else (answer[0] if isinstance(answer, tuple) else str(answer))), N.key)
                if url:
                    break
            left -= requests
            outcome = "found" if url else "not_found"
            with db.transaction(self.db_url) as cur:
                if url:
                    EA.add(cur, root=x["entity_id"], url=normalize_url(url) or url, kind=E.PAPER, rule=E.LOOKUP,
                           post_id=None, now=now)
                cur.execute("""INSERT INTO story_originals (kind, url, asked_at, requests, outcome, detail, settled_at, entity_id)
                               VALUES ('lookup', %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (kind, url) DO NOTHING""",
                            (f"entity:{x['entity_id']}", now, requests, outcome, url or detail, now, x["entity_id"]))
            done.append({"entity_id": x["entity_id"], "outcome": outcome, "url": url, "requests": requests})
        return done

    def keep_suppliers(self, cur: Any, now: datetime) -> Dict[str, int]:
        """0138 D2: each site (Discover's address key) that was the address of 3+ originals in 30 days (0123's and
        0138's asks, and the other pages an entity's title names beside its paper original: a summariser's), kept
        for Discover with the first time each was suggested (D3). Returns {current, suggested}."""
        from insight_core.db.repo_stories import SourceFacts, StoriesRepository
        since = now - E.SUPPLY_WITHIN
        cur.execute("""SELECT url, asked_at FROM story_originals WHERE kind IN ('collect', 'entity') AND asked_at >= %s
                          AND outcome NOT IN ('walled', 'no_article', 'tweet_unheld', 'followed')""", (since,))
        rows = list(cur.fetchall())
        cur.execute("""SELECT a.url, a.first_at FROM mx_entity_addresses a
                        WHERE a.kind = 'release' AND a.rule = 'title' AND a.first_at >= %s
                          AND EXISTS (SELECT 1 FROM mx_entity_addresses b WHERE b.entity_id = a.entity_id AND b.kind = 'paper')""",
                    (since,))
        rows += cur.fetchall()
        kept = DiscoverRepository.kept(cur) or {}
        platforms = {host: tuple(prefix) for host, prefix in (kept.get("platforms") or {}).items()}
        facts = SourceFacts(cur)
        followed = facts.followed() | facts.followed_accounts()
        current = E.suppliers(((discover_address(u, platforms)[0], u, at) for u, at in rows), now=now,
                              followed=followed, hidden=StoriesRepository.hidden(cur))
        row = SystemSettingsRepository.get(cur, SUPPLIERS_KEY)
        before = (row[0] if row else None) or {}
        suggested = dict(before.get("suggested") or {})
        for key in current:
            suggested.setdefault(key, now.isoformat())
        value = {"at": now.isoformat(), "suggested": suggested,
                 "current": {k: {"n": s["n"], "urls": s["urls"][:20], "since": s["since"].isoformat()}
                             for k, s in current.items()}}
        if value["current"] != before.get("current") or suggested != before.get("suggested"):
            SystemSettingsRepository.upsert(cur, SUPPLIERS_KEY, value)
        return {"current": len(current), "suggested": len(suggested)}

    async def _collect(self, plan: List[Dict[str, Any]], http: Any, left: int, now: datetime,
                       pause: float = 0.0) -> List[Dict[str, Any]]:
        """Each planned original: a quote stored, a page read (while the budget lasts), or the reason none is.
        `pause`: seconds between two page reads (0138 E's backfill: one host at a time, PAGE_DELAY_S apart)."""
        done = []
        read_before = False
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
                if pause and read_before:
                    await self.sleep(pause)
                read_before = True
                try:
                    result = await self._read(http, c)
                except Exception as error:  # noqa: BLE001 - one page's failure is recorded, never raised
                    result = {"status": "failed", "reason": str(error)[:200], "requests": 1}
                outcome, post_id = result["status"], result.get("post_id")
                requests, detail = int(result.get("requests", 1)), result.get("reason")
                left -= requests
            with db.transaction(self.db_url) as cur:
                cur.execute("""INSERT INTO story_originals (kind, url, story_id, post_id, asked_at, requests, outcome, detail,
                                                            settled_at, entity_id, source_id, from_post_id)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (kind, url) DO NOTHING""",
                            (c.get("record", "collect"), c["url"], c["story_id"], post_id, now, requests, outcome, detail,
                             now, c.get("entity_id"), c.get("source_id"), c.get("from_post_id")))
            done.append({"url": c["url"], "outcome": outcome, "requests": requests,
                         **({"entity_id": c["entity_id"]} if c.get("entity_id") else {}),
                         **({"as": c["collected_as"]} if c.get("collected_as") else {})})
        return done

    async def _read(self, http: Any, c: Dict[str, Any]) -> Dict[str, Any]:
        """One page through the save path's reader, holding its host's gate as a fetch does."""
        extra = {"collected_as": c["collected_as"]} if c.get("collected_as") else {}

        async def read() -> Dict[str, Any]:
            if c.get("record") == "missed":   # 0138 F2: the followed source's own post
                return await self.saved.collect_for_source(http, c["url"], c["source_id"])
            return await self.saved.collect(http, c["url"], c["title"], **extra)
        if self.gates is None:
            return await read()
        from insight_core.ingestion.kinds.base import PolitenessProfile

        async with self.gates.slot(PolitenessProfile(concurrency_pool="host-lock"), host_of(c["url"])):
            return await read()

    # ---- 0138 E: the backfill (Classics stored, work sites) ----------------------------------

    @staticmethod
    def backfill_left(cur: Any, now: datetime) -> int:
        """E1's allowance now: CLASSICS_DAILY pages in the last 24 hours (Classics and works together), at most a run's
        share. Apart from 0114 and 0123's credit."""
        cur.execute("""SELECT COALESCE(sum(requests), 0) FROM story_originals
                        WHERE kind IN ('classic', 'work') AND asked_at > %s""", (now - timedelta(hours=24),))
        used = int(cur.fetchone()[0])
        return max(0, min(E.BACKFILL_PER_RUN, E.CLASSICS_DAILY - used))

    def plan_works(self, cur: Any, now: datetime, kind_of: Callable[..., str]) -> List[Dict[str, Any]]:
        """E2: each work site (an entity's `work` address: a document's front page, A's rules) linked by 2+ voices,
        not stored and not asked, never one whose site word names a product, app, model, org or person (E5); with its
        own pages your posts link (the same host, never another front page), at most WORK_PAGES_MAX, the most linked
        first. The front page first, then its pages; sites by their voices."""
        from insight_core.markx import entity_addresses as EA, identity as I
        cur.execute("SELECT 1 FROM mx_entity_addresses WHERE kind = 'work' LIMIT 1")
        if cur.fetchone() is None:
            return []
        book = I.lazy_book(cur)   # v10.17 (0186): the addresses' entities, not the whole book
        never = _NeverFront(book)
        fronts: Dict[str, str] = {}
        for root, rows in EA.current(cur, book).items():
            for kind, url, _rule, _at, _pid in rows:
                if kind == E.WORK and E.work_front_allowed(url, never):
                    fronts.setdefault(url, root)
        if not fronts:
            return []
        cur.execute("""SELECT l.target_url, count(DISTINCT p.source_id) FROM post_links l JOIN posts p ON p.id = l.post_id
                         JOIN sources s ON s.id = p.source_id
                        WHERE l.target_url = ANY(%s) AND NOT l.boilerplate AND s.platform <> 'saved' GROUP BY 1""",
                    (sorted(fronts),))
        voices = {u: n for u, n in cur.fetchall() if n >= E.TRIGGER_VOICES}
        if not voices:
            return []
        cur.execute("SELECT url FROM story_originals WHERE kind IN ('collect', 'entity', 'classic', 'work')")
        asked = {r[0] for r in cur.fetchall()}
        out = []
        for front in sorted(voices, key=lambda u: (-voices[u], u)):
            host = host_of(front)
            cur.execute("""SELECT l.target_url, count(DISTINCT l.post_id) FROM post_links l
                            WHERE l.target_url LIKE %s AND NOT l.boilerplate AND l.kind = 'link' GROUP BY 1""",
                        (front.rstrip("/") + "/%",))
            pages = [u for u, _ in sorted(cur.fetchall(), key=lambda r: (-r[1], r[0]))
                     if host_of(u) == host and not E.front_page(u)][:E.WORK_PAGES_MAX]
            urls = [front] + pages
            cur.execute("SELECT normalized_url FROM posts WHERE normalized_url = ANY(%s)", (urls,))
            stored = {r[0] for r in cur.fetchall()}
            for url in urls:
                if url in stored or url in asked:
                    continue
                out.append({"url": url, "story_id": None, "voices": voices[front], "first_at": now, "kind": kind_of(url),
                            "title": None, "quoted": None, "record": "work", "entity_id": fronts[front],
                            "collected_as": "work"})
        return out

    @staticmethod
    def longreads(cur: Any) -> Dict[str, List[str]]:
        """F1: the curated long-reads you opened or kept: {post: its outside article pages}. A post is one when its own
        text is LONGREAD_CHARS+ long, Mark X reads it as commentary or a roundup (its reading's kind), and it cites
        LONGREAD_LINKS+ outside article pages (another site's, not a front page, not an archive or an app's)."""
        cur.execute(f"""
            WITH yours AS (SELECT post_id FROM post_interactions WHERE interaction_type IN ('opened', 'reading_session')
                           UNION SELECT post_id FROM post_reader_state WHERE starred_at IS NOT NULL)
            SELECT p.id::text, COALESCE(p.normalized_url, p.url) FROM posts p JOIN yours y ON y.post_id = p.id
             WHERE char_length(COALESCE(p.content, '')) >= %s
               AND EXISTS (SELECT 1 FROM mx_readings r WHERE r.post_id = p.id AND r.kind = ANY(%s))""",
                    (E.LONGREAD_CHARS, list(E.LONGREAD_KINDS)))
        posts = dict(cur.fetchall())
        if not posts:
            return {}
        cur.execute("""SELECT post_id::text, target_url FROM post_links WHERE post_id = ANY(%s::uuid[])
                         AND NOT boilerplate AND kind = 'link' ORDER BY post_id, position""", (sorted(posts),))
        cited: Dict[str, List[str]] = {}
        for pid, url in cur.fetchall():
            if E.cited_page(url, posts[pid]) and url not in cited.setdefault(pid, []):
                cited[pid].append(url)
        return {pid: urls for pid, urls in cited.items() if len(urls) >= E.LONGREAD_LINKS}

    def plan_references(self, cur: Any, now: datetime, kind_of: Callable[..., str]) -> List[Dict[str, Any]]:
        """F1: each curated long-read's cited pages (at most REFERENCES_MAX a post), not stored and not asked. A followed
        source's page is read as F2 reads one (its source's post, kind `missed`, the citing post kept)."""
        found = self.longreads(cur)
        if not found:
            return []
        urls = sorted({u for us in found.values() for u in us})
        cur.execute("SELECT normalized_url FROM posts WHERE normalized_url = ANY(%s)", (urls,))
        stored = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT url FROM story_originals WHERE url = ANY(%s) AND kind IN ('collect', 'entity', 'classic', 'work', "
                    "'reference', 'missed')", (urls,))
        asked = {r[0] for r in cur.fetchall()}
        out, planned = [], set()
        for pid in sorted(found):
            for url in found[pid][:E.REFERENCES_MAX]:
                url = rules.strip_access_tokens(url)
                if url in stored or url in asked or url in planned:
                    continue
                kind = kind_of(url)
                planned.add(url)
                if kind == rules.FOLLOWED:   # a followed source's page: read as F2 reads one, its source's post
                    from insight_core.utils.addresses import is_tweet
                    sid = getattr(kind_of, "owner", lambda u: None)(url)
                    if sid and not is_tweet(url):
                        out.append({"url": url, "story_id": None, "voices": 1, "first_at": now, "kind": rules.PAGE,
                                    "title": None, "quoted": None, "record": "missed", "source_id": sid,
                                    "from_post_id": pid})
                    continue
                out.append({"url": url, "story_id": None, "voices": 1, "first_at": now, "kind": kind, "title": None,
                            "quoted": None, "record": "reference", "from_post_id": pid, "collected_as": "reference"})
        return out

    def plan_missed(self, cur: Any, now: datetime, kind_of: Callable[..., str]) -> List[Dict[str, Any]]:
        """F2: a followed source's page (0084 B's own pages) that a post of another source linked in the last 30 days
        and that its feed never carried: not stored, not asked; read as that source's post."""
        owner = getattr(kind_of, "owner", None)
        if owner is None:
            return []
        # A post listing ROUNDUP_ANCHORS+ links is about its first only (Mark IX's rule, story_rules.ROUNDUP_ANCHORS):
        # measured on the server's copy, a meetups list's 60 event pages were half of what was wanted without it.
        from insight_core.utils.story_rules import ROUNDUP_ANCHORS
        cur.execute("""SELECT target_url, source_id FROM (
                           SELECT pl.target_url, p.source_id::text AS source_id, pl.position,
                                  count(*) OVER (PARTITION BY pl.post_id) AS links,
                                  min(pl.position) OVER (PARTITION BY pl.post_id) AS first
                             FROM post_links pl JOIN posts p ON p.id = pl.post_id
                            WHERE NOT pl.boilerplate AND pl.kind = 'link'
                              AND COALESCE(p.published_at, p.fetched_at) >= %s) x
                        WHERE links < %s OR position = first""", (now - E.MISSED_WITHIN, ROUNDUP_ANCHORS))
        want: Dict[str, str] = {}
        from insight_core.utils.addresses import is_tweet
        for url, linker in cur.fetchall():
            if E.front_page(url) or url in want or is_tweet(url):
                continue   # a tweet is never read (x.com's app shell): it comes from a quote (0123)
            sid = owner(url)
            if sid and sid != linker:
                want[url] = sid
        if not want:
            return []
        urls = sorted(want)
        cur.execute("SELECT normalized_url FROM posts WHERE normalized_url = ANY(%s)", (urls,))
        stored = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT url FROM story_originals WHERE url = ANY(%s) AND kind = 'missed'", (urls,))
        asked = {r[0] for r in cur.fetchall()}
        return [{"url": url, "story_id": None, "voices": 1, "first_at": now, "kind": rules.PAGE, "title": None,
                 "quoted": None, "record": "missed", "source_id": sid}
                for url, sid in sorted(want.items()) if url not in stored and url not in asked]

    def keep_cited(self, cur: Any) -> int:
        """F3: each site (Discover's address key) the long-reads you opened cite: {key: {n, posts}} kept for Discover
        (`longread_citations`), the keys cited twice or more. Returns how many."""
        found = self.longreads(cur)
        kept = DiscoverRepository.kept(cur) or {}
        platforms = {host: tuple(prefix) for host, prefix in (kept.get("platforms") or {}).items()}
        by: Dict[str, Dict[str, Any]] = {}
        for pid, urls in found.items():
            for url in urls:
                key = discover_address(url, platforms)[0]
                if key:
                    got = by.setdefault(key, {"n": 0, "posts": set()})
                    got["n"] += 1
                    got["posts"].add(pid)
        value = {k: {"n": v["n"], "posts": len(v["posts"])} for k, v in by.items() if v["n"] >= 2}
        row = SystemSettingsRepository.get(cur, CITED_KEY)
        if ((row[0] if row else None) or {}) != value:
            SystemSettingsRepository.upsert(cur, CITED_KEY, value)
        return len(value)

    def plan_classics(self, cur: Any, now: datetime, kind_of: Callable[..., str]) -> List[Dict[str, Any]]:
        """E1: every Classic not stored and not hidden, not asked before (as any original): biggest voices first."""
        cur.execute("""SELECT c.target_url, c.voices, c.title, c.first_at FROM classics c
                        WHERE c.post_id IS NULL
                          AND NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)
                          AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.normalized_url = c.target_url)
                          AND NOT EXISTS (SELECT 1 FROM story_originals o WHERE o.url = c.target_url
                                             AND o.kind IN ('collect', 'entity', 'classic', 'work'))
                        ORDER BY c.voices DESC, c.first_at, c.target_url""")
        return [{"url": rules.strip_access_tokens(url), "story_id": None, "voices": voices, "first_at": first,
                 "kind": kind_of(url), "title": title, "quoted": None, "record": "classic", "collected_as": "classic"}
                for url, voices, title, first in cur.fetchall()]


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


__all__ = ["OriginalsService", "accrue", "classics_on", "collect_on", "lookup_on", "run_originals", "site_reads", "spend"]
