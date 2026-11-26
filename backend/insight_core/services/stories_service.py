"""One story, many sources (0050): the story job and Discover.

The story job runs in insight-ingestion's jobs runner (markx/jobs.py, "stories", in its own process), wanted by each
fetch run that saved posts, the backend's start and a voice change. It is incremental: it reads the links and refs of
posts never read, then regroups only what the queued posts (`story_queue`) touch (`_neighbourhood`) and writes only
the rows that differ: stories, their posts and mentions, `post_edges`, News, Classics and Discover's counts. A new
story keeps its id when an earlier post joins. A rule change (`rules_stamp`, three parts) redoes only what the changed
parts need (`redo_for`) in bounded background batches; the old rows are served until replaced.
`recompute(full=True)` regroups every post at once (`regroup`): the oracle the incremental job must match row by row.
Deterministic and idempotent; one job at a time (an advisory lock; a job that finds one running skips). No AI, no fetch.
"""
from __future__ import annotations

import hashlib
import logging
import multiprocessing
import sys
import time
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_post_parts import catch_up_safely
from insight_core.db.repo_post_refs import PostRefsRepository
from insight_core.db.repo_series import SeriesRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services import page_titles
from insight_core.services.news_service import NewsService
from insight_core.utils import stamps
from insight_core.utils.news_rules import news, surges
from insight_core.utils.addresses import host_of, is_tweet, site_of
from insight_core.utils import voice
from insight_core.utils.byline import tweet_account
from insight_core.utils.post_links import PLATFORM_KINDS
from insight_core.utils.discover_rules import (DISCOVER_MIN_ARTICLES, DISCOVER_MIN_VOICES, FIRST_PAGE, FOLLOWABLE,
                                              PAGES_WITHIN_DAYS, UNFOLLOWABLE, Origin,
                                              REFERENCE_KINDS, channel_names, discover_address, discover_open, discover_place,
                                              federation, follow_url, not_channel, one_card_per_domain, order, origins,
                                              other_channel, owner_domain, place_kind, reader_fit, score, site_unit)
from insight_core.utils.story_rules import (LINK_POST_KINDS, NOT_PUBLISHERS, THREAD_WITHIN, Edge, Grouping, StoryPost,
                                            date_alone, grouping, keys, page_key, threads)
from insight_core.utils.discover_rules import GROWTH_DAYS, growth, page_key_of, page_kind, pages as pages_of, split
from insight_core.utils.entity_originals import supplier_reason
from insight_core.utils.originals_rules import SiteReads, site_reads_of, strip_access_tokens, tokened
from insight_core.utils.tree_rules import _PAGE, slug_title
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger(__name__)

SETTINGS_KEY = "stories"
LOCK_KEY = "insight.stories"
# a run works STEP_BUDGET_S at most, then yields and rests REST_AFTER_YIELD_S, so a decision run gets the lock
STEP_BUDGET_S = 180.0
REST_AFTER_YIELD_S = 90.0
YIELD_KEY = "stories_yield"   # system_settings: {"at": ISO} of the last run that yielded
# runs follow each other at once; a run skips once a decision run has waited this long (jobs.decision_waits)
DECISION_WAIT_S = 600.0
STORY_BATCH = 1000    # queued posts a batch starts from (a fetch run's are fewer; a rule change's are all)
# a rule change's batch: more posts share the context read around them (measured: plan/issues/0215)
REBUILD_BATCH = 2000
KEYS_BATCH = 2000     # posts a rule change reads the keys of a transaction
CLOSURE_KEYS = ("h:", "t:", "u:", "g:")   # the keys a post joins another by (story_rules.keys)
KEYED_EDGES = ("text", "title", "address", "link", "quote")   # the connections a key makes (story_rules.Edge.via)
DISCOVER_ARTICLES_SHOWN = 20
CITED_MIN, CITED_POSTS = 3, 2   # a site cited this often, by this many long-reads you read, is suggested
ORIGIN_STORIES_SHOWN = 3      # the stories a suggestion started, shown on its card
STOPPED_DAYS = 183            # an archive row's source whose newest post is this old: its feed stopped
# the served answer is rebuilt when an open finds it this old: Mark X's originals rows move between story runs
REFRESH_AFTER = timedelta(minutes=30)
READS_EVERY = timedelta(hours=1)   # a first page asks the jobs process for its web reads at most this often
REPO_MIN_VOICES = 2   # a repository this many voices link is suggested as its releases
READ_DAYS = 90        # the sources you read (opened or read a post of) in this long: discover_rules.reader_fit


class StoriesService:
    def __init__(self, db_url: str, *, repo: StoriesRepository | None = None,
                 clock: Callable[[], datetime] | None = None, news: NewsService | None = None):
        self.db_url = db_url
        self.repo = repo or StoriesRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.news = news or NewsService(db_url, clock=self.clock)
        self._discovered: tuple = ("", None)
        self._unsettled: Optional[tuple] = None
        code_stamp()

    # ---- the job ------------------------------------------------------------------------

    def fill_links(self) -> int:
        """Read the links of every post never read, a batch a transaction, until none is left. Returns how many."""
        return db.fill_until_done(self.db_url, self.repo.fill_missing_links, self.repo.missing_links)

    def fill_refs(self) -> int:
        """Read the refs of every post never read (resumable), then the signature pass once. Returns how many posts."""
        filled = db.fill_until_done(self.db_url, PostRefsRepository.fill_missing, PostRefsRepository.missing)
        if filled:
            with db.transaction(self.db_url) as cur:
                PostRefsRepository.mark_boilerplate(cur)
        return filled

    def fill_series(self) -> Optional[Dict[str, Any]]:
        """The series pass (db/repo_series.py) over sources with new posts. None when another run holds it."""
        with db.transaction(self.db_url) as cur:
            if not SeriesRepository.lock(cur):
                return None
            return SeriesRepository.run(cur, self.clock())

    def recompute(self, *, full: bool = False) -> Dict[str, Any]:
        """The story job: what the queue holds, a batch a transaction (a rule change's rebuild first),
        or with `full` every post at once (the oracle). Returns a summary."""
        started = time.monotonic()
        if not full and self._resting():
            return {"skipped": "resting after a yield"}
        if not full and self._decision_waiting():
            return {"skipped": "a decision run's turn"}
        catch_up_safely(self.db_url)   # every post's parts read first: what the job and the pages read
        filled = self.fill_links()
        self.fill_refs()
        try:   # the series pass never holds the stories back
            self.fill_series()
        except Exception:
            logger.exception("Series pass failed; the story job goes on")
        if full:
            with db.transaction(self.db_url) as cur:
                if not self._lock(cur):
                    return {"skipped": True, "links_filled": filled}
                summary = {**self.full_on(cur), "links_filled": filled, "seconds": round(time.monotonic() - started, 2)}
            self.fill_discover_addresses()
            return summary
        totals: Counter = Counter()
        while True:
            with db.transaction(self.db_url) as cur:
                if not self._lock(cur):
                    return {**totals, "links_filled": filled} if totals else {"skipped": True, "links_filled": filled}
                if not self.advance(cur, totals, links_filled=filled, started=started):
                    self.settle_slice(cur)
                    return {"computed_at": self.clock().isoformat(), "full": False, **totals, "links_filled": filled,
                            "batches": totals["batches"], "seconds": round(time.monotonic() - started, 2)}
                if time.monotonic() - started >= STEP_BUDGET_S:
                    self.settle_slice(cur)
                    SystemSettingsRepository.upsert(cur, YIELD_KEY, {"at": self.clock().isoformat()})
                    logger.info("Stories: yielded after %.0f s with work left (%d batches)",
                                time.monotonic() - started, totals["batches"])
                    return {"computed_at": self.clock().isoformat(), "full": False, **totals, "links_filled": filled,
                            "batches": totals["batches"], "yielded": True,
                            "seconds": round(time.monotonic() - started, 2)}

    def _decision_waiting(self) -> bool:
        """Whether Mark X's decision run is wanted, not running, and has waited DECISION_WAIT_S or more
        (markx/jobs.decision_waits decides). False when Mark X has no jobs table or no such row."""
        from insight_core.markx import jobs
        try:
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                return jobs.decision_waits(cur, self.clock(), DECISION_WAIT_S)
        except Exception:  # noqa: BLE001 - Mark X absent: nothing waits
            return False

    def _resting(self) -> bool:
        """Whether the last run yielded less than REST_AFTER_YIELD_S ago (the decision run's turn)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            got = SystemSettingsRepository.get(cur, YIELD_KEY)
        value = (got or ({}, None))[0] or {}
        at = value.get("at") if isinstance(value, dict) else None
        if not at:
            return False
        try:
            since = (self.clock() - datetime.fromisoformat(at)).total_seconds()
        except ValueError:
            return False
        return 0 <= since < REST_AFTER_YIELD_S

    def full_on(self, cur: Any) -> Dict[str, Any]:
        """Every post at once (`regroup`), on the caller's transaction, and the setting that says so."""
        now = self.clock()
        summary = {"computed_at": now.isoformat(), "full": True, **self.regroup(cur)}
        self._settle(cur, SourceFacts(cur), summary, now, {"rules": rules_stamp(), "full_at": now.isoformat(), "rebuild": None})
        return summary

    def advance(self, cur: Any, totals: Counter, *, links_filled: int = 0, started: Optional[float] = None) -> bool:
        """One step of the incremental job on the caller's transaction (`step`), its counts added to
        `totals` and its setting kept, then Discover for it. False when nothing was left."""
        now = self.clock()
        previous = (SystemSettingsRepository.get(cur, SETTINGS_KEY) or ({}, None))[0] or {}
        sources = SourceFacts(cur)
        step = self.step(cur, sources, previous, now, window=not totals)
        if step is None:
            return False
        counts = step.pop("counts")
        totals.update(counts)
        if counts.get("boilerplate_changed"):
            step["links_changed"] = True
        summary = {"computed_at": now.isoformat(), "full": False, "links_filled": links_filled, **totals,
                   "batches": totals["batches"], "seconds": round(time.monotonic() - (started or time.monotonic()), 2)}
        if step.pop("quiet", False):
            self._unsettled = (sources, summary, now, step)
            return True
        self._unsettled = None
        self._settle(cur, sources, summary, now, step)
        self._discover_step(cur, sources, step.get("discover"))
        return True

    def settle_slice(self, cur: Any) -> None:
        """At a slice's end, keep the progress its last quiet batches left unkept (`advance`)."""
        pending, self._unsettled = self._unsettled, None
        if pending is None:
            return
        sources, summary, now, step = pending
        if step.get("rebuild"):
            step = {**step, "rebuild": {**step["rebuild"], **self.repo.regrouped(cur)}}
        self._settle(cur, sources, summary, now, step)

    def update(self, cur: Any) -> Dict[str, Any]:
        """The incremental job on the caller's transaction, every step until none is left. Returns its counts."""
        totals: Counter = Counter()
        while self.advance(cur, totals):
            pass
        self.settle_slice(cur)
        return dict(totals)

    @staticmethod
    def _lock(cur: Any) -> bool:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        return cur.fetchone()[0]

    def _settle(self, cur: Any, sources: SourceFacts, summary: Dict[str, Any], now: datetime,
                state: Dict[str, Any]) -> None:
        """Write the run's setting: its summary, what the stored rows are (rules, sources' facts, News's window,
        Discover's inputs' time) and a rebuild's progress (Background work reads it)."""
        previous = (SystemSettingsRepository.get(cur, SETTINGS_KEY) or ({}, None))[0] or {}
        value = {**{k: v for k, v in previous.items() if k in ("rules", "full_at", "facts", "rebuild", "news_since",
                                                                "discover_at")},
                 **summary, **self.repo.counts(cur)}
        # a rebuild's keys, threads and names steps leave Discover's inputs (and its kept counts) as they were
        value["discover_at"] = previous.get("discover_at") or previous.get("computed_at") or now.isoformat()
        if (summary.get("full") or state.get("discover") is not None or state.get("links_changed")
                or summary.get("links_filled")):
            value["discover_at"] = now.isoformat()
        for key in ("rules", "full_at", "rebuild"):
            if key in state:
                value[key] = state[key]
        value["facts"] = self._facts(sources)
        value["news_since"] = (now - self.news.keep).isoformat()
        if value.get("rebuild") is None:
            value.pop("rebuild", None)
        SystemSettingsRepository.upsert(cur, SETTINGS_KEY, value)

    def regroup(self, cur: Any) -> Dict[str, int]:
        """Every post at once, on the caller's transaction (the oracle): boilerplate, stories, connections, keys,
        threads, News, Classics. Returns counts and rows changed."""
        sources = SourceFacts(cur)
        boilerplate = len(self.repo.mark_boilerplate(cur, sources))
        posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources)]
        found = grouping(posts)
        made_by = rules_stamp()["grouping"]
        changed = self.repo.write_stories(cur, found.stories)
        edges = (self.repo.write_edges(cur, found.edges, made_by=made_by)
                 + self.repo.write_edges(cur, found.edges, made_by=made_by, threads=True))
        keys_changed = self.repo.write_keys(cur, {p.id: self.stored_keys(p) for p in posts})
        news_counts = self.news.refresh(cur, posts=posts, stories=found.stories, sources=sources)
        self.repo.clear_queue(cur)
        return {"posts": len(posts), "stories": len(found.stories), "changed": changed, "edges_changed": edges,
                "keys_changed": keys_changed, "boilerplate_changed": boilerplate, **news_counts}

    def step(self, cur: Any, sources: SourceFacts, previous: Dict[str, Any], now: datetime, *,
             window: bool = True) -> Optional[Dict[str, Any]]:
        """One bounded step on the caller's transaction: a rule change's next step (`redo_for` says which redo), else
        a batch of the queue, else (with `window`) News's window edge. None when nothing is left. Returns the state to
        keep and `counts`."""
        stamp = rules_stamp()
        rebuild = previous.get("rebuild")
        if rebuild and rebuild.get("rules") != stamp:
            adopted = self._adopt(cur, sources, previous, rebuild, stamp, now)
            if adopted is not None:
                return adopted
            rebuild = None   # a rebuild by other rules than these: begin again from the rows' own
        if not rebuild:
            stored = stored_rules(previous.get("rules"))
            legacy = previous.get("rules") != stamp and not isinstance(previous.get("rules"), dict)
            if legacy and stored.get("grouping") == stamp["grouping"]:
                self.repo.relabel_edges(cur, stamp["grouping"])
            redo = redo_for(stored, stamp)
            if redo is not None:
                return self._begin_redo(cur, sources, stored, redo, stamp, now)
            if legacy:
                return {"rules": dict(stamp), "counts": Counter(batches=1)}
        if rebuild and rebuild["phase"] != "stories":
            return self._rebuild_step(cur, sources, rebuild, stamp)
        self._facts_changed(cur, sources, previous.get("facts"))
        batch = self._batch(cur, sources, previous, now, stamp["grouping"], redo=bool(rebuild), window=window)
        if batch is not None:
            if rebuild and not batch.get("quiet"):
                rebuild = {**rebuild, **self.repo.regrouped(cur)}
            if rebuild:
                batch["rebuild"] = rebuild
            return batch
        if rebuild:
            counts = Counter(batches=1)
            counts.update(self._news_window(cur, sources, now))
            done: Dict[str, Any] = {"rebuild": None, "rules": dict(stamp), "counts": counts}
            if rebuild.get("redo", "grouping") == "grouping":
                done.update(full_at=now.isoformat(), discover="all")
            return done
        return None

    def _begin_redo(self, cur: Any, sources: SourceFacts, stored: Dict[str, str], redo: str, stamp: Dict[str, str],
                    now: datetime) -> Dict[str, Any]:
        """A rule change's redo begins (`redo_for` said which): its first step."""
        rebuild: Dict[str, Any] = {"rules": dict(stamp), "redo": redo, "phase": "names" if redo == "news" else "keys",
                                   "after": None, "started_at": now.isoformat(), "total": self.repo.count_posts(cur),
                                   "done": 0}
        counts = Counter(batches=1)
        if redo != "news":
            counts["boilerplate_changed"] = len(self.repo.mark_boilerplate(cur, sources))
        if redo == "grouping":
            self.repo.relabel_edges(cur, stamp["grouping"])
        logger.info("Stories: a rule change (%s) begins: %s", redo, {p: (stored.get(p), stamp[p]) for p in PARTS})
        return {"rebuild": rebuild, "counts": counts}

    def _adopt(self, cur: Any, sources: SourceFacts, previous: Dict[str, Any], rebuild: Dict[str, Any],
               stamp: Dict[str, str], now: datetime) -> Optional[Dict[str, Any]]:
        """Adopt a rebuild in progress kept under these rules' legacy stamp, else None (the redo begins again). It
        goes on regrouping every post, newest first; or, when its rows differ from these rules in News alone, it ends
        after its names step and one News pass over the window."""
        if stored_rules(rebuild.get("rules")) != stamp:
            return None
        self.repo.relabel_edges(cur, stamp["grouping"])
        rest = {k: v for k, v in rebuild.items() if k not in ("after", "left")}
        if redo_for(stored_rules(previous.get("rules")), stamp) in (None, "news"):
            if rebuild.get("phase") != "stories":
                return {"rebuild": {**rest, "rules": dict(stamp), "redo": "news", "phase": "names"},
                        "counts": Counter(batches=1)}
            counts = Counter(batches=1, redo_dropped=self.repo.drop_redo(cur))
            counts.update(self._news_window(cur, sources, now))
            logger.info("Stories: the rebuild in progress differed in News only; ended (%s posts no longer queued)",
                        counts["redo_dropped"])
            return {"rebuild": None, "rules": dict(stamp), "discover": "all", "counts": counts}
        counts = Counter(batches=1, redo_reordered=self.repo.newest_first(cur))
        return {"rebuild": {**rebuild, "rules": dict(stamp), "redo": "grouping"}, "counts": counts}

    def _news_window(self, cur: Any, sources: SourceFacts, now: datetime) -> Dict[str, int]:
        """News over every post of its window (all of them seeds of `NewsService.update`): what a full run's News
        makes of the stories as stored."""
        from insight_core.utils.news_rules import NEWS_EDGE
        since = now - self.news.keep
        seeds = set(self.news.repo.window_posts(cur, since - NEWS_EDGE))
        posts: Dict[str, StoryPost] = {}

        def load(ids: Iterable[str]) -> None:
            missing = sorted(set(ids) - posts.keys())
            if missing:
                posts.update((row["id"], self._story_post(row, sources))
                             for row in self.repo.load_posts(cur, sources, missing))
        load(seeds)
        return self.news.update(cur, sources=sources, posts=posts, load=load, touched=seeds, titles=[], urls=[],
                                since=since, before=None)

    def _rebuild_step(self, cur: Any, sources: SourceFacts, rebuild: Dict[str, Any],
                      stamp: Dict[str, str]) -> Dict[str, Any]:
        """A rule change's steps before its batches: the keys (KEYS_BATCH a step), each X source's threads, the
        names' surges, then every post queued. A "keys" redo queues only the posts whose joins moved; "news" runs the
        names step alone."""
        rebuild = dict(rebuild)
        redo = rebuild.get("redo", "grouping")
        counts: Counter = Counter(batches=1)
        if rebuild["phase"] == "keys":
            ids = self.repo.post_ids(cur, rebuild["after"], KEYS_BATCH)
            posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources, ids)]
            if redo == "grouping":
                counts["keys_changed"] = self.repo.write_keys(cur, {p.id: self.stored_keys(p) for p in posts})
            else:
                moved = self.repo.keys_moved(cur, {p.id: self.stored_keys(p) for p in posts})
                regroup = {pid for pid, (was, now) in moved.items() if _joins(was) != _joins(now)}
                self.repo.queue_regroup(cur, sorted(regroup))
                counts["keys_changed"] = self.repo.write_keys(
                    cur, {pid: now for pid, (_, now) in moved.items() if pid not in regroup})
                counts["keys_queued"] = len(regroup)
            rebuild["after"] = ids[-1] if ids else None
            if len(ids) < KEYS_BATCH:
                if redo == "grouping":
                    rebuild.update(phase="threads", left=sorted(sources.of_kind("x")))
                else:   # the names its titles say may have moved too: judged again, News over the window
                    rebuild["phase"] = "names"
        elif rebuild["phase"] == "threads":
            left = list(rebuild["left"])
            if left:
                source_id = left.pop(0)
                ids = self.repo.timeline(cur, source_id, datetime.min.replace(tzinfo=timezone.utc),
                                         datetime.max.replace(tzinfo=timezone.utc))
                posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources, ids)]
                counts["edges_changed"] = self.repo.write_edges(
                    cur, [Edge(c, p, "thread") for c, p in threads(posts).items()], made_by=stamp["grouping"],
                    post_ids=ids, threads=True)
            rebuild["left"] = left
            if not left:
                rebuild.pop("left")
                rebuild["phase"] = "names"
        elif rebuild["phase"] == "names":
            counts["surges_changed"] = self.news.judge_names(cur, sources, None)
            # News by the new rules at once: the batches that follow take minutes and row it only around their stories
            counts.update(self._news_window(cur, sources, self.clock()))
            if redo == "news":
                return {"rebuild": None, "rules": dict(stamp), "counts": counts}
            if redo == "grouping":
                rebuild["queued"] = self.repo.redo_every_post(cur)
            rebuild.update(phase="stories", **self.repo.regrouped(cur))
        return {"rebuild": rebuild, "counts": counts}

    def _facts_changed(self, cur: Any, sources: SourceFacts, before: Optional[Dict[str, Any]]) -> None:
        """Queue the posts of a source whose facts changed, and of X posts naming an account followed or left."""
        if before is None:
            return
        now = self._facts(sources)
        changed = sorted(s for s in set(now["sources"]) | set(before.get("sources", {}))
                         if now["sources"].get(s) != before.get("sources", {}).get(s))
        accounts = set(now["accounts"]) ^ set(before.get("accounts", []))
        if changed or accounts:
            self.repo.queue_posts(cur, changed, sorted(accounts))

    @staticmethod
    def _facts(sources: SourceFacts) -> Dict[str, Any]:
        """What the rules read of each source, as a fingerprint, and the accounts followed. Owner and voice are added
        only when set, so a change queues only that source's posts."""
        owner = getattr(sources, "owner", {})
        voice_of = getattr(sources, "voice_of", {})
        return {"sources": {s: stamps.fingerprint([sources.kind[s], sources.publication(s), sources.own_site(s),
                                                   sources.home_site(s), sources.account.get(s), sources.name.get(s),
                                                   sources.own_site(s) in sources.shared_sites,
                                                   *([owner[s]] if s in owner else []),
                                                   *([{"voice": voice_of[s]}] if s in voice_of else [])])
                            for s in sorted(sources.kind)},
                "accounts": sorted(a for a in sources.of_account)}

    def _batch(self, cur: Any, sources: SourceFacts, previous: Dict[str, Any], now: datetime, made_by: str, *,
               redo: bool, window: bool) -> Optional[Dict[str, Any]]:
        """A batch of the queue (else, in a rebuild, a rule change's) and what it touches, regrouped; then News,
        Classics and Discover for them. None when the queue is empty and News's window has not moved."""
        taken = self.repo.take_queue(cur, STORY_BATCH)
        rebuilding = not taken and redo
        if rebuilding:
            taken = self.repo.take_queue(cur, REBUILD_BATCH, redo=True)
        since = now - self.news.keep
        edge = window and previous.get("news_since") != since.isoformat()
        if not taken and not edge:
            return None
        seeds: Set[str] = set()
        gone: Set[str] = set()
        titles: List[Optional[str]] = []
        points: List[Tuple[str, datetime]] = []
        was_at: Dict[str, str] = {}
        for key, was in taken:
            seeds.add(key.split(":", 1)[1])
            if was and was.get("url"):
                was_at[key.split(":", 1)[1]] = was["url"]
            if was:
                gone |= set(was.get("keys") or ())
                titles.append(was.get("title"))
                if was.get("t"):
                    points.append((was["source_id"], datetime.fromisoformat(was["t"])))
        posts: Dict[str, StoryPost] = {}

        def load(ids: Iterable[str]) -> None:
            missing = sorted(set(ids) - posts.keys())
            if missing:
                posts.update((row["id"], self._story_post(row, sources))
                             for row in self.repo.load_posts(cur, sources, missing))

        load(seeds)
        if seeds and not rebuilding:   # a source's signature counts its own posts (repo.mark_boilerplate)
            flipped = self.repo.mark_boilerplate(cur, sources, sorted({posts[s].source_id for s in seeds if s in posts}
                                                                      | {s for s, _ in points}))
            self.repo.take_keys(cur, ["post:" + pid for pid in flipped])
            seeds |= set(flipped)
            for pid in flipped:
                posts.pop(pid, None)
            load(seeds)
        points += [(posts[s].source_id, posts[s].t) for s in seeds if s in posts]
        threaded = self._threads(cur, sources, points, made_by)
        seeds |= threaded
        load(seeds)
        seeds = {s for s in seeds if s in posts}
        # a rule change's batch changes no title: its names step judged them all
        if not rebuilding:
            titles += [posts[s].title for s in seeds if s in posts]
        before = self.repo.stored_keys(cur, sorted(seeds))
        touched = gone | {k for s in seeds for k in before.get(s, set()) | self.stored_keys(posts[s])}
        moved = gone | {k for s in seeds for url in (posts[s].url, was_at.get(s)) if url
                        for k in ("u:" + url, page_key(url)) if k}
        self.rounds: List[Tuple[int, int, int]] = []
        found, scope = self._neighbourhood(cur, posts, load, seeds, moved)
        stories = [s for s in found.stories if s.posts[0].id in scope]
        counts: Counter = Counter(batches=1, posts=len(scope), seeds=len(seeds), rounds=len(self.rounds),
                                  context=self.rounds[-1][2])
        roots = {found.root[pid] for pid in scope if pid in found.root}
        nodes = {node for node, root in found.root.items() if root in roots} | scope
        outside = {n for pid, listed in found.listed.items() if pid in scope for n in listed if n not in nodes}
        # Read past the scope: a page only its posts linked is in no story now.
        held = self.repo.stories_holding(cur, sorted(outside), besides=sorted(scope))
        mentioned = self.repo.mentioned_by(cur, sorted(scope))
        mentions = [Edge(pid, n, "mention") for pid, listed in found.listed.items() if pid in scope
                    for n in dict.fromkeys(listed) if n in held]
        counts["changed"] = self.repo.write_stories(cur, stories, post_ids=sorted(scope),
                                                    mentions={(held[e.dst], e.src) for e in mentions})
        nodes |= {_PAGE + url for url in self.repo.pages_linked(cur, sorted(scope))}
        counts["edges_changed"] = self.repo.write_edges(
            cur, [e for e in found.edges if e.dst in nodes and (e.src in scope or e.kind == "mention")
                  or e.src in scope and e.kind != "mention"] + mentions,
            made_by=made_by, post_ids=sorted(scope), mentioned=sorted(nodes))
        counts["keys_changed"] = self.repo.write_keys(cur, {pid: self.stored_keys(posts[pid]) for pid in scope})
        if rebuilding:
            self.repo.done(cur, scope)
            # nothing changed: News, Classics and Discover count from these, so nothing more is written (`quiet`)
            if not (edge or threaded or counts["changed"] or counts["edges_changed"] or counts["keys_changed"]):
                return {"counts": counts, "discover": None, "quiet": True}
        urls = {k[2:] for k in touched if k.startswith(("u:", "l:"))}
        own = {posts[s].url for s in seeds if posts[s].url}
        urls |= {t for p in posts.values() if any(target in own for target, _ in p.links) for t, _ in p.links}
        mentioned |= self.repo.story_mates(cur, [n for n in held if not n.startswith(_PAGE)])
        mentioned |= self.repo.story_mates(cur, self.repo.linking(cur, sorted(n[len(_PAGE):] for n in held if n.startswith(_PAGE))))
        counts.update(self.news.update(cur, sources=sources, posts=posts, load=load, touched=scope | mentioned, titles=titles,
                                       urls=sorted(urls), since=since,
                                       before=datetime.fromisoformat(previous["news_since"])
                                       if previous.get("news_since") else None))
        return {"counts": counts, "discover": sorted(urls)}

    def _threads(self, cur: Any, sources: SourceFacts, points: List[Tuple[str, datetime]], made_by: str) -> Set[str]:
        """Rewrite the X thread edges within THREAD_WITHIN of these (source, time) points (story_rules.threads).
        Returns the posts whose edge changed, with their old and new parents."""
        by_source: Dict[str, List[datetime]] = defaultdict(list)
        for source_id, t in points:
            if sources.kind.get(str(source_id)) == "x":
                by_source[str(source_id)].append(t)
        changed: Set[str] = set()
        for source_id, times in by_source.items():
            ids: Set[str] = set()
            for t in times:
                ids |= set(self.repo.timeline(cur, source_id, t - 2 * THREAD_WITHIN, t + 2 * THREAD_WITHIN))
            window = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources, ids)]
            found = threads(window)
            children = sorted(p.id for p in window if any(abs(p.t - t) <= THREAD_WITHIN for t in times))
            have = self.repo.replies(cur, children)
            for child in children:
                if have.get(child) != found.get(child):
                    changed |= {child, have.get(child), found.get(child)} - {None}
            self.repo.write_edges(cur, [Edge(c, found[c], "thread") for c in children if c in found], made_by=made_by,
                                  post_ids=children, threads=True)
        return changed

    def _neighbourhood(self, cur: Any, posts: Dict[str, StoryPost], load: Callable[[Iterable[str]], None],
                       seeds: Set[str], moved: Set[str]) -> Tuple[Grouping, Set[str]]:
        """What a batch regroups (`scope`) and the rules' grouping of it: from the seeds, the posts linking a `moved`
        address and their stories, grown with what the rules read around it until whole, so each connection is the one
        a full run makes (BACKEND.md, "The incremental story job")."""
        scope = self.repo.story_mates(cur, seeds | self.repo.holders(cur, moved))
        held: Set[str] = set()
        near: Set[str] = set()
        context: Set[str] = set()
        replies: Dict[str, str] = {}
        keyed: Set[str] = set()
        linked: Set[str] = set()
        threaded: Set[str] = set()
        found, grouped = None, -1
        while True:
            load(scope)
            stored = self.repo.stored_keys(cur, sorted(scope - keyed))
            new = {k for pid in scope - keyed for k in self.stored_keys(posts[pid]) | stored.get(pid, set())
                   if k.startswith(CLOSURE_KEYS)} - held
            keyed |= scope
            held |= new
            near |= scope | self.repo.holders(cur, new)
            load(near)
            context |= near | self._context(cur, posts, near - linked)
            linked |= near
            load(context)
            replies.update(self.repo.replies(cur, sorted(context - threaded)))
            threaded |= context
            if len(context) != grouped:
                found, grouped = grouping([posts[pid] for pid in context], replies=replies), len(context)
            grows = self._grows(cur, posts, found, scope, near - scope, held)
            self.rounds.append((len(scope), len(near), len(context)))
            if not grows:
                return found, scope
            scope |= grows

    def _context(self, cur: Any, posts: Dict[str, StoryPost], ids: Set[str]) -> Set[str]:
        """The posts at the addresses these posts link, and at another path of their pages (page_aliases)."""
        urls = {t for pid in ids for t, _ in posts[pid].links}
        pages = {"a:" + k[2:] for url in urls | {posts[pid].url for pid in ids} if url and (k := page_key(url))}
        return self.repo.at_addresses(cur, sorted(urls)) | self.repo.holders(cur, pages)

    def _grows(self, cur: Any, posts: Dict[str, StoryPost], found: Grouping, scope: Set[str], near: Set[str],
               held: Set[str]) -> Set[str]:
        """What the scope must take in so its stories are whole (`_neighbourhood`), with their old stories."""
        roots = {found.root[pid] for pid in scope if pid in found.root}
        grows = {node for node, root in found.root.items() if root in roots and not node.startswith(_PAGE)} - scope
        pages = {node[len(_PAGE):] for node, root in found.root.items() if root in roots and node.startswith(_PAGE)}
        for pid, nodes in found.listed.items():
            if posts[pid].kind in PLATFORM_KINDS and (pid in scope or pid in near
                                                      and any(found.root.get(n) in roots for n in nodes)):
                grows |= {pid} | {n for n in nodes if not n.startswith(_PAGE)}
                pages |= {n[len(_PAGE):] for n in nodes if n.startswith(_PAGE)}
        computed = {(e.src, e.dst, e.kind) for e in found.edges if e.via in held and e.src in near}
        stored = {(e.src, e.dst, e.kind) for e in self.repo.edges_of(cur, sorted(near), KEYED_EDGES)
                  if e.via in held and e.src in near}
        grows |= {node for src, dst, _ in computed ^ stored for node in (src, dst) if not node.startswith(_PAGE)}
        grows |= self.repo.linking(cur, sorted(pages))
        return self.repo.story_mates(cur, grows) - scope

    @staticmethod
    def stored_keys(post: StoryPost) -> Set[str]:
        """A post's stored keys: what it joins by (story_rules.keys), its page key ("a:"), its title's names ("n:")
        and the pages it links ("l:": no join; Classics and Discover count them)."""
        out = keys(post)
        if post.url and page_key(post.url):
            out.add("a:" + page_key(post.url)[2:])
        out |= {"l:" + target for target, _ in post.links if "u:" + target not in out}
        return out | {"n:" + name for name in NewsService.names_of(post)}

    @staticmethod
    def _story_post(row: Dict[str, Any], sources: SourceFacts) -> StoryPost:
        """Every field the story job reads of a post, from its stored row and parts (load_posts) and its source's
        facts; built here only."""
        kind = sources.kind.get(row["source_id"], "site")
        author_source = sources.of_account.get(tweet_account(row["author"])) if kind == "x" and row["author"] else None
        post = StoryPost(
            id=row["id"], source_id=row["source_id"], kind=kind, own_site=sources.publication(row["source_id"]),
            t=row["t"], title=row["title"] if row["shown_title"] is None else row["shown_title"], opening=row.get("opening"),
            content_hash=row["content_hash"], text_chars=row["text_chars"],
            words=row["words"] if kind in LINK_POST_KINDS else None,
            author=row["poster"] if kind == "reddit" else row["author"],
            url=row["url"], links=row["links"],
            moved_to=row.get("moved_to") if row.get("moved_to") != row["url"] else None,
            link_texts=row["link_texts"], updated=row["updated"], home_site=sources.home_site(row["source_id"]),
            reposted=kind == "x" and bool(row["author"])
            and sources.account.get(row["source_id"]) != tweet_account(row["author"]),
            reply_to=row["reply_to"] if kind == "x" else None,
            quoted=row["quoted"] if kind == "x" else None,
            quoted_words=row["quoted_words"],
            reposters=tuple(sorted({sources.of_account.get(tweet_account(by)) for by in row["reposted_by"]}
                                   - {None, row["source_id"], author_source})),
            author_source=author_source if author_source != row["source_id"] else None,
            stored_at=row.get("stored_at"),
            date_alone=row["precision"] == "date" if row.get("precision") in ("date", "exact") else date_alone(row["t"]),
            undated=row.get("precision") in ("none", "seen"),
            month_alone=row.get("precision") == "month",
            roundup=bool(row.get("roundup")),   # Mark X's round-up tag: it joins no story by its links
        )
        post.owner = sources.owner_voice(post.voice)
        post.other_owners = tuple(sources.owner_voice(voice.source_key(s)) for s in post.other_sources)
        if not any(post.other_owners):
            post.other_owners = ()
        return post

    def recompute_safely(self, *, full: bool = False) -> Optional[Dict[str, Any]]:
        """The job, logged and never raising (after a fetch run, at start)."""
        try:
            summary = self.recompute(full=full)
            logger.info("Stories: %s", summary)
        except Exception:  # noqa: BLE001 - stories are derived; the next run recomputes them
            logger.exception("Stories: the story job failed")
            return None
        if not summary.get("skipped"):
            self.keep_discover()
        return summary

    def keep_discover(self) -> None:
        """After a story run: build and keep Discover's answer, so an open reads one row. Never raises."""
        try:
            self.refresh()
        except Exception:  # noqa: BLE001 - derived; Discover makes it on its next open
            logger.exception("Stories: Discover's list was not kept")

    # ---- Discover -----------------------------------------------------------------------

    def fill_discover_addresses(self) -> int:
        """After a full story run: fill the addresses Discover has not met and keep its counts. Never raises."""
        try:
            with db.transaction(self.db_url) as cur:
                sources = SourceFacts(cur)
                kept = DiscoverRepository.kept(cur, found=False)
                filled = DiscoverRepository.fill_addresses(cur, sources.platform_accounts(), platforms=_platforms(kept))
                self._counted(cur, sources, kept=kept)
                return filled
        except Exception:  # noqa: BLE001 - derived; Discover fills what is missing
            logger.exception("Stories: Discover's addresses were not filled")
            return 0

    def map_videos(self, channels: Dict[str, str]) -> int:
        """Map videos to the channels Discover's reads found and count those channels again. Returns addresses moved."""
        if not channels:
            return 0
        with db.transaction(self.db_url) as cur:
            moved = DiscoverRepository.map_videos(cur, channels)
            if moved:
                self._counted(cur, SourceFacts(cur), moved=moved)
        return len(moved)

    def _discover_step(self, cur: Any, sources: SourceFacts, urls: Any) -> None:
        """After a batch, on its transaction: Discover's addresses and counts for `urls`, or every one ("all").
        Never raises: a savepoint keeps the batch when it fails."""
        if urls is None:
            return
        try:
            with cur.connection.transaction():
                kept = DiscoverRepository.kept(cur, found=False)
                DiscoverRepository.fill_addresses(cur, sources.platform_accounts(), urls=None if urls == "all" else urls,
                                                  platforms=_platforms(kept))
                self._counted(cur, sources, urls=None if urls == "all" else urls, kept=kept)
        except Exception:  # noqa: BLE001 - derived; Discover fills what is missing
            logger.exception("Stories: Discover's counts were not updated")

    @staticmethod
    def _counted(cur: Any, sources: SourceFacts, urls: Optional[List[str]] = None, *, keep: bool = True,
                 kept: Optional[Dict[str, Any]] = None, moved: Sequence[str] = ()) -> Dict[str, Any]:
        """Discover's counts by links, counted in the database: the kept ones when their inputs are unchanged, else
        counted now (with `urls`, only those addresses' keys, while the rules, mirrors and platforms hold) and kept.
        Without `keep` nothing is written. `kept`: the caller's read of them, with or without their found rows (read
        only where used: the kept counts returned, and an incremental count; 0283); `moved`: addresses whose key moved.
        Returns {stamp, base, found, mirrors, platforms, scanned_to}."""
        accounts = sources.platform_accounts()
        own_sites = {i: sources.publication(i) for i in sources.kind}
        selves = {i: sorted(sources.selves(i)) for i in sources.kind}
        ask = dict(kinds=sources.kind, own_sites=own_sites, accounts=accounts, shown=DISCOVER_ARTICLES_SHOWN, selves=selves)
        facts = sorted((i, sources.kind[i], own_sites[i], accounts.get(i, ""), selves[i], sources.suggestable(i))
                       for i in sources.site)
        stamp, base = DiscoverRepository.stamp(cur, facts), DiscoverRepository.base(cur)
        tags = DiscoverRepository.tags(cur)
        kept = DiscoverRepository.kept(cur, found=False) if kept is None else kept
        if kept and kept["stamp"] == stamp and kept.get("tags") == tags and not moved:
            return kept if "found" in kept else {**kept, "found": DiscoverRepository.kept_found(cur)}
        retagged = DiscoverRepository.retagged(cur, kept, tags)
        if urls is None and kept and kept["stamp"] == stamp and retagged is not None:
            urls = []
        if urls is not None and moved:
            urls = list(urls) + [u for u in moved if u not in set(urls)]
        mirrors, scanned_to = DiscoverRepository.mirrors(cur, kept)
        off = sorted(sources.off)   # a source switched off or on moves every key it linked, not a run's
        if (urls is not None and kept and kept.get("base") == base and mirrors == kept["mirrors"] and "platforms" in kept
                and kept.get("off", []) == off and retagged is not None):
            platforms = _platforms(kept)
            if "found" not in kept:
                kept = {**kept, "found": DiscoverRepository.kept_found(cur)}
            keys = (DiscoverRepository.keys_of(cur, urls, platforms)
                    | DiscoverRepository.keys_linked_by(cur, retagged, platforms))
            found, _ = DiscoverRepository.counts(cur, mirrors=mirrors, keys=keys, platforms=platforms, **ask)
            titled = {a[0]: a[2] for s in kept["found"] for a in s["articles"] if a[0] not in set(urls)}
            StoriesService._title_articles(cur, sources, found, titled)
            found += [s for s in kept["found"] if s["key"] not in keys]
            DiscoverRepository.name_voices(cur, found, ask["kinds"], ask["own_sites"])
        else:
            platforms = DiscoverRepository.platforms(cur, kinds=sources.kind, own_sites=own_sites, selves=selves)
            found, unknown = DiscoverRepository.counts(cur, mirrors=mirrors, platforms=platforms, **ask)
            if unknown and keep:
                DiscoverRepository.fill_addresses(cur, accounts, platforms=platforms)
                found, _ = DiscoverRepository.counts(cur, mirrors=mirrors, platforms=platforms, **ask)
            elif unknown:
                logger.info("Discover: %d linked addresses not worked out yet, read as the story job left them", unknown)
            StoriesService._title_articles(cur, sources, found)
        found.sort(key=lambda s: s["key"])
        kept = {"stamp": stamp, "base": base, "tags": tags, "found": found, "mirrors": mirrors, "scanned_to": scanned_to,
                "platforms": {host: list(prefix) for host, prefix in sorted(platforms.items())}, "off": off}
        if keep:
            DiscoverRepository.keep(cur, kept)
            DiscoverRepository.keep_tagged(cur, tags)
        return kept

    @staticmethod
    def _title_articles(cur: Any, sources: SourceFacts, found: List[Dict[str, Any]],
                        titled: Optional[Dict[str, Optional[str]]] = None) -> None:
        """Title each shown article: a stored post's own, else the evidence of the posts linking it (origin_title),
        never its slug. `titled`: the kept titles, which hold."""
        titled = titled or {}
        urls = sorted({url for s in found for url, _ in s["articles"] if url not in titled})
        titles = page_titles.evidence(cur, sources, urls)
        for s in found:
            s["articles"] = [(url, voices, titled[url] if url in titled else titles[url]) for url, voices in s["articles"]]

    def discover(self, *, offset: int = 0, limit: Optional[int] = None, q: Optional[str] = None) -> Dict[str, Any]:
        """Sites and accounts your sources keep linking that you don't follow, ranked (discover_rules.order), with the
        references and the stories your sources miss. `offset`/`limit`: the page; `q`: a word filter. Writes nothing
        on a read-only connection; the API serves `discover_served` instead."""
        return self._page(self._fresh(persist=self._writable()), offset=offset, limit=limit, q=q)

    def discover_kept(self) -> Dict[str, Any]:
        """What Discover's reads choose from (discover_reads._todo), from the served answer (`refresh`'s) so it is not
        built twice: its suggestions in `_page`'s order (`_by_fit`), whole where the reads' first page takes them
        (discover_reads.to_read), else only their key and order fields (DiscoverRepository.served_outline); the apart
        rows' keys; the archives as `_page` shows them. The whole answer is never read (0283: ~75 MB of objects on
        the server's copy, on every run). Before the first build, `discover`."""
        from insight_core.services.discover_reads import to_read
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            outline = DiscoverRepository.served_outline(cur)
            if outline is None:
                whole = None
            else:
                ranked = self._by_fit(outline["suggestions"])
                whole = DiscoverRepository.served_rows(cur, outline["built_at"],
                                                       [s["at"] for s in to_read({"suggestions": ranked})])
        if outline is None:
            return self.discover()
        if whole is None:   # rebuilt between the two reads: read the new one
            return self.discover_kept()
        ranked = [dict(whole[s["at"]], **{k: s[k] for k in ("fit", "section") if k in s}) if s["at"] in whole else s
                  for s in ranked]
        return self._page({"suggestions": ranked, "apart": outline["apart"], "archives": outline["archives"]},
                          ordered=True)

    def _writable(self) -> bool:
        """Whether this service's connections may write (the checks open every one read-only)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            return cur.fetchone()[0] != "on"

    def discover_served(self, *, offset: int = 0, limit: Optional[int] = None,
                        q: Optional[str] = None) -> Dict[str, Any]:
        """Discover's page as the API serves it: the last answer built (`refresh`), never made on the request, with
        `built_at` and `refreshing`. An answer due again, or a first page whose web reads are READS_EVERY old, wants
        the jobs process's "discover" job; nothing is made or kept in the API process."""
        from insight_core.markx import jobs
        page_one = offset == 0 and not q
        with db.transaction(self.db_url) as cur:
            stamp, due = self._served_due(cur)
            answer, total = None, None
            if stamp is not None and not q and limit is not None:
                got = DiscoverRepository.served_window(cur, offset, limit)
                answer, total = got if got is not None else (None, None)
            elif stamp is not None:
                kept = DiscoverRepository.served(cur)
                answer = kept["answer"] if kept else None
            if answer is None:
                total = None
                answer = DiscoverRepository.any_list(cur) or {}
            due = due or "built_at" not in answer
            state = jobs.state(cur).get("discover") or {}
            last = state.get("started_at")
            if due or (page_one and (last is None or self.clock() - last >= READS_EVERY)):
                jobs.want(cur, "discover")
                state = jobs.state(cur).get("discover") or {}
            refreshing = state.get("stage") is not None or state.get("wanted_at") is not None
        if stamp is None or "built_at" not in answer:
            empty = {"success": True, "suggestions": [], "also": [], "archives": [], "unnamed": [], "pages": [],
                     "references": [], "first_page": FIRST_PAGE, "apart": {}}
            answer = {**empty, **answer, "built_at": None}
        return {**self._page(answer, offset=offset, limit=limit, q=q, total=total), "refreshing": refreshing}

    def served_due(self) -> bool:
        """Whether the answer served is due again (the jobs process's "discover" view)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self._served_due(cur)[1]

    def _served_due(self, cur: Any) -> Tuple[Optional[Tuple[str, str]], bool]:
        """(the served answer's stamp, whether it is due again: missing, inputs or code moved, REFRESH_AFTER old)."""
        inputs = self.repo.discover_inputs(cur) + "|" + code_stamp()
        stamp = DiscoverRepository.served_stamp(cur)
        if stamp is None:
            return None, True
        try:
            age = self.clock() - datetime.fromisoformat(stamp[1])
        except ValueError:
            age = REFRESH_AFTER
        return stamp, stamp[0] != inputs or age >= REFRESH_AFTER or age < timedelta(0)

    def refresh(self) -> Dict[str, Any]:
        """Build Discover's answer now and keep it as the one served, with `built_at`. Returns it. Background only.
        A build starts from the memory the process freed handed back (collected and trimmed: v10.48, measured on the
        server's copy, the job's second build peaked ~100 MB lower), so two builds in one job do not stack."""
        import gc
        from insight_core.utils.idle_trim import libc_trim
        gc.collect()
        trim = libc_trim()
        if trim is not None:
            trim()
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            inputs = self.repo.discover_inputs(cur) + "|" + code_stamp()
        answer = self._fresh()
        built_at = self.clock().isoformat()
        answer = {**answer, "built_at": built_at}
        try:
            with db.transaction(self.db_url) as cur:
                DiscoverRepository.keep_served(cur, inputs, built_at, answer)
        except Exception:  # noqa: BLE001 - derived; the next refresh keeps it
            logger.exception("Discover: the answer was not kept")
        # v10.48: the list (~150 MB of objects on the server's data) is kept in the database; the jobs process holds
        # no copy of it between builds (its next build follows new reads, so new inputs: it never hit)
        self._discovered = ("", None)
        return answer

    def _fresh(self, *, persist: bool = True) -> Dict[str, Any]:
        """The list (`_discover_all`) with Mark X's originals rows read now. Without `persist`, nothing is written."""
        result = self._discover_all(persist=persist)
        result = self._from_originals(result)
        # 0280: the main list apart from the unfollowable and quiet rows (C1); Pages' reference and product pages
        # marked (C2)
        main, apart = split(self._by_fit(result["suggestions"]))
        pages = [dict(p, kind=page_kind(p["url"])) for p in result.get("pages") or []]
        return {**result, "suggestions": main, "apart": apart, "pages": pages}

    def _page(self, result: Dict[str, Any], *, offset: int = 0, limit: Optional[int] = None,
              q: Optional[str] = None, total: Optional[int] = None, ordered: bool = False) -> Dict[str, Any]:
        """One page of the answer. `total`: `result`'s suggestions are already the page's (sliced in Postgres,
        DiscoverRepository.served_window) out of `total`."""
        if total is not None:
            got = self._page({**result, "suggestions": [None] * offset + result["suggestions"]}, offset=offset,
                             limit=limit, ordered=True)
            end = offset + max(0, limit or 0)
            return {**got, "total": total, "more": end < total}
        if result["archives"]:   # each archive row follows its source's archive, read now (it runs on its own)
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                states = DiscoverRepository.archive_states(cur, {a["source_id"]: a["pages"] for a in result["archives"]})
            result = {**result, "archives": _archive_rows(result["archives"], states, self.clock())}
        ranked, also = result["suggestions"], result.get("also", [])
        if not ordered:   # a served window (sliced in Postgres, padded) is in _fresh's fit order already
            ranked = self._by_fit(ranked)
        if q:
            words = q.casefold().split()
            ranked = [s for s in ranked if all(w in _words(s) for w in words)]
            also = [s for s in also if all(w in _words(s) for w in words)]
            result = {**result, "apart": {kind: {"total": len(rows), "rows": rows} for kind, got in
                                          (result.get("apart") or {}).items()
                                          for rows in [[s for s in got["rows"] if all(w in _words(s) for w in words)]]}}
        end = len(ranked) if limit is None else offset + max(0, limit)
        return {**result, "suggestions": ranked[offset:end], "also": also if offset == 0 else [], "total": len(ranked),
                "offset": offset, "more": end < len(ranked)}

    def _by_fit(self, ranked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Discover ranked by the worker's `fit` judgement (markx/source_judge) via discover_rules.order. A failure
        leaves the order as it was."""
        if not ranked:
            return ranked
        from insight_core.markx import source_judge
        from insight_core.utils.discover_rules import order
        try:
            keys = sorted({source_judge.cache_key(s["key"]) for s in ranked})
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                cur.execute("""SELECT DISTINCT ON (key) key, verdict, (answer->>'fits')::boolean FROM mx_source_judgements
                                WHERE key = ANY(%s) AND status = 'answered' ORDER BY key, asked_at DESC""", (keys,))
                fits = {k: ("not_fit" if f is False else v) for k, v, f in cur.fetchall()}
        except Exception:  # noqa: BLE001 - Discover's own order stands
            logger.exception("Discover: the judgements could not be read")
            return ranked
        if not fits:
            return ranked
        out = [dict(s, fit=fits[source_judge.cache_key(s["key"])]) if source_judge.cache_key(s["key"]) in fits else s
               for s in ranked]
        return order(out)

    def _from_originals(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Add Mark X's rows, read on each open: entities' originals as Pages rows, original suppliers and long-read
        citations as suggestions, `supplied` and `worlds` (markx/rabbit_hole.py). A failure leaves the list as is."""
        from insight_core.db import repo_discover
        try:
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                sources = repo_discover.light_facts(cur)
                hidden = self.repo.hidden(cur)
                now = self.clock()
                pages = list(result.get("pages") or [])
                pages += repo_discover.entity_pages(cur, self.db_url, now, hidden=hidden,
                                                    names=lambda sid: sources.name.get(sid, ""),
                                                    skip={p["url"] for p in pages})
                from insight_core.markx import rabbit_hole
                worlds = rabbit_hole.discover_rows(cur)
                kept = repo_discover.suppliers(cur)
                cited = repo_discover.longread_citations(cur)
                supplied = repo_discover.supplied_first(cur, kept.get("suggested") or {}, facts=sources)
                conn.rollback()
        except Exception:  # noqa: BLE001 - Discover's own list stands without them
            logger.exception("Discover: the originals' rows were not read")
            return result
        pubs = set(result.get("publication_sites") or sources.shared_sites)
        followed = sources.followed(pubs) | sources.followed_accounts()
        ranked = [dict(s) for s in result["suggestions"]]
        by_key = {s["key"]: s for s in ranked}
        cards: Dict[str, Dict[str, Any]] = {}
        for s in ranked:
            for place in s.get("places") or [s["key"]]:
                domain = owner_domain(place, pubs)
                if domain:
                    cards.setdefault(domain, s)
        elsewhere = {a["key"] for a in result.get("also", ())}

        def closed(key: str) -> bool:
            site = key.split("/", 1)[0]
            return (key in followed or site in followed or site_of(site) in followed or key.lower() in hidden
                    or site in hidden or site_of(site) in hidden or key in elsewhere)

        def card_of(key: str) -> Optional[Dict[str, Any]]:
            s = by_key.get(key)
            domain = owner_domain(key, pubs) if s is None else None
            if s is None and domain in cards:
                s = by_key[key] = cards[domain]
                s["places"] = list(dict.fromkeys([*(s.get("places") or [s["key"]]), key]))
            return s

        for key, got in (kept.get("current") or {}).items():
            if closed(key):
                continue
            s = card_of(key)
            if s is None and (place_kind(key, got["urls"]) is not None or not_channel(key, None)):
                continue
            if s is None:
                s = by_key[key] = {"key": key, "url": "https://" + key, "voices": 0, "voice_names": [],
                                   "article_count": got["n"], "link_count": got["n"], "classics": 0, "opened": 0,
                                   "origins": 0, "articles": [{"url": u, "title": None, "linked_by": []}
                                                              for u in got["urls"][:DISCOVER_ARTICLES_SHOWN]],
                                   "score": round(score(origins=got["n"], classics=0, opened=0, voices=0, days=None), 3)}
                ranked.append(s)
                cards.setdefault(owner_domain(key, pubs) or key, s)
            s["originals"] = got["n"]
            s["originals_reason"] = supplier_reason(got["n"])
        for key, got in cited.items():
            if closed(key):
                continue
            s = card_of(key)
            if s is None:
                if got["n"] < CITED_MIN or got["posts"] < CITED_POSTS:
                    continue   # below today's bar it takes 3+ citations from 2+ long-reads
                s = by_key[key] = {"key": key, "url": "https://" + key, "voices": 0, "voice_names": [],
                                   "article_count": got["n"], "link_count": got["n"], "classics": 0, "opened": 0,
                                   "origins": 0, "articles": [],
                                   "score": round(score(origins=0, classics=0, opened=got["n"], voices=got["posts"],
                                                        days=None), 3)}
                ranked.append(s)
                cards.setdefault(owner_domain(key, pubs) or key, s)
            s["cited_by_longreads"] = got["n"]
        return {**result, "suggestions": order(ranked), "pages": pages, "supplied": supplied, "worlds": worlds}

    def _discover_all(self, *, persist: bool = True) -> Dict[str, Any]:
        """The whole list: this process's last when its inputs and code are unchanged, else the database's, else made
        now and kept. Without `persist` nothing is written."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            inputs = self.repo.discover_inputs(cur) + "|" + code_stamp()
            if self._discovered[0] == inputs and self._discovered[1] is not None:
                return self._discovered[1]
            self._discovered = ("", None)   # an older list is let go before this one is read or made (v10.48)
            kept = DiscoverRepository.kept_list(cur, inputs)
            if kept is not None:
                self._discovered = (inputs, kept)
                return kept
            sources = SourceFacts(cur)
            counted = self._counted(cur, sources, keep=persist)
            platforms = _platforms(counted)
            reads = DiscoverRepository.reads(cur)
            channels = DiscoverRepository.video_channels(cur, reads)
            publication_sites = self._publication_sites(cur, sources, counted["found"])
            followed = sources.followed(publication_sites)
            hidden, classics = self.repo.hidden(cur), set(self.news.classic_urls(cur))
            roots = DiscoverRepository.story_origins(cur, kinds=sources.kind,
                                                     own_sites={i: sources.publication(i) for i in sources.kind})
            held = self._held(cur, sources, roots, followed, platforms, publication_sites)
            started = origins(roots, followed=followed, held=held, mirrors=set(counted["mirrors"]), platforms=platforms,
                              publication_sites=publication_sites, channels=channels)
            first_posts = DiscoverRepository.first_posts(cur, started.missing)
            repos = self._repos(cur, sources)
            activity = DiscoverRepository.activity(cur, [s["key"] for s in counted["found"]], platforms,
                                                   since=self.clock() - timedelta(days=GROWTH_DAYS))
            read_sources = DiscoverRepository.read_sources(cur, self.clock() - timedelta(days=READ_DAYS))
            title_of = self._title_map(cur, sources, counted, started, reads.get("titles", {}))
        now = self.clock()
        saved = set(sources.of_kind("saved"))
        out, references, last, weight, grown = [], {}, {}, {}, {}
        linkers: Dict[str, Set[str]] = defaultdict(set)
        for s in counted["found"]:
            if not discover_open(s["key"], site_of(s["key"]), "/" in s["key"], followed=followed, hidden=hidden,
                                 followed_accounts=sources.followed_accounts(), publication_sites=publication_sites):
                continue   # followed or hidden (a platform's key is its account, x.com/nn_teacher; a site's its host)
            names = {voice: sources.voice_name(voice, source_id or "") for voice, source_id in s["voices"]}
            linking = _linking(sources, ((v, i, v in s["roundups"]) for v, i in s["voices"]), s.get("sources", ()), saved)
            weight[s["key"]] = len(linking) - sum(1 for only, _ in linking if only) / 2
            last[s["key"]], _, new, old = activity.get(s["key"], (None, 0, 0, 0))
            half = weight[s["key"]] / len(linking) if linking else 1.0
            grown[s["key"]] = growth(new=new * half, old=old * half)
            linkers[s["key"]].update(i for _, i in s["voices"] if i)
            suggestion = {
                "key": s["key"],
                "url": "https://" + s["key"],
                "voices": len(linking),
                "voice_names": [name for _, name in linking],
                "article_count": s["article_count"],
                "link_count": s["link_count"],
                "classics": len(classics.intersection(s["classics"])),
                "articles": [{"url": url, "title": title, "linked_by": sorted({names[v] for v in voices})}
                             for url, voices, title in s["articles"]],
                "origins": 0,
                "opened": activity.get(s["key"], (None, 0, 0, 0))[1],
            }
            kind = place_kind(s["key"], [a["url"] for a in suggestion["articles"]])
            if kind in REFERENCE_KINDS:
                references[s["key"]] = len(linking)
            if kind is None:
                out.append(suggestion)
        by_key = {s["key"]: s for s in out}
        for r in repos:
            key = r["key"]
            if key in by_key or not discover_open(key, "github.com", True, followed=followed, hidden=hidden,
                                                  followed_accounts=sources.followed_accounts()):
                continue
            linking = _linking(sources, ((v, i, False) for v, i in r["voices"]), (), saved)
            if len(linking) < REPO_MIN_VOICES:
                continue
            weight[key] = len(linking)
            last[key] = r["last_at"]
            linkers[key].update(r["sources"])
            out.append(by_key.setdefault(key, {
                "key": key, "url": r["url"], "voices": len(linking), "voice_names": [n for _, n in linking],
                "article_count": len(r["urls"]), "link_count": len(r["urls"]), "classics": 0, "opened": 0, "origins": 0,
                "releases": True,
                "articles": [{"url": u, "title": None, "linked_by": []} for u in r["urls"][:DISCOVER_ARTICLES_SHOWN]]}))
        for key, stories in started.references.items():
            references.setdefault(key, len({v for root in stories for v in root.voices}))
        for key, stories in started.suggest.items():
            names = {v: sources.voice_name(v, source_id) for root in stories for v, source_id in root.voices.items()}
            linkers[key].update(i for root in stories for i in root.voices.values() if i)
            pages = sorted({root.url for root in stories})
            suggestion = by_key.get(key)
            if suggestion is None:
                site = key.split("/", 1)[0]
                if (len(pages) < DISCOVER_MIN_ARTICLES or len(names) < DISCOVER_MIN_VOICES
                        or key.lower() in hidden or site in hidden or site_of(site) in hidden
                        or place_kind(key, pages) is not None):
                    continue
                linking = _linking(sources, ((v, i, False) for root in stories for v, i in root.voices.items()),
                                   [(i, False) for root in stories for i in root.reddit_sources], saved)
                weight[key] = len(linking)
                suggestion = by_key[key] = {
                    "key": key, "url": "https://" + key, "voices": len(linking), "voice_names": [n for _, n in linking],
                    "article_count": len(pages), "link_count": len(pages), "classics": 0, "opened": 0,
                    "articles": [{"url": root.url, "title": None,
                                  "linked_by": sorted({names[v] for v in root.voices})}
                                 for root in _first(stories, pages=True)[:DISCOVER_ARTICLES_SHOWN]],
                }
                out.append(suggestion)
            suggestion["origins"] = len(stories)
            suggestion["origin_stories"] = [_story(root, title_of) for root in _first(stories)[:ORIGIN_STORIES_SHOWN]]
            newest = max(root.first_at for root in stories)
            last[key] = max(filter(None, (last.get(key), newest)))
        follow = reads.get("follow", {})
        for s in out:
            days = (now - last[s["key"]]).total_seconds() / 86400 if last.get(s["key"]) else None
            s["growth"] = round(grown.get(s["key"], 0.0), 3)
            s["score"] = round(score(origins=s["origins"], classics=s["classics"], opened=s["opened"],
                                     voices=weight[s["key"]], days=days, grown=s["growth"]), 3)
            s["days"] = days
            test = follow.get(s["key"])
            if test:
                s["follow_test"] = {"label": test["label"], "at": test["at"]}
                if test.get("url") and test["label"] in FOLLOWABLE:
                    s["url"] = test["url"]
                if test.get("account") and test["label"] in UNFOLLOWABLE:
                    s["account"] = test["account"]
            for a in s["articles"]:
                a["title"] = title_of(a["url"])
        # A followed site's old or moved address is that source's, never new; a non-channel (not_channel) is dropped.
        moved: List[Dict[str, Any]] = []
        kept_out = []
        for s in out:
            test = follow.get(s["key"]) or {}
            landed = test.get("moved_to")
            if landed and (site_of(landed) in followed or landed in followed):
                moved.append({**s, "of": sources.name.get(_site_source(sources, landed), "") or landed,
                              "source_id": _site_source(sources, landed), "moved_to": landed})
            elif not_channel(s["key"], test.get("label")):
                continue
            else:
                kept_out.append(s)
        out = kept_out
        days_of = {s["key"]: s.get("days") for s in out}
        out = one_card_per_domain(out, federations=publication_sites)
        for s in out:
            places = list(dict.fromkeys([s["key"], *s.get("places", ())]))
            for place in places[1:]:
                linkers[s["key"]] |= linkers.get(place, set())
            s.pop("days", None)
            # 0280 C1: the days since your sources last linked it (any of its places): a quiet row sits apart
            known = [days_of[p] for p in places if days_of.get(p) is not None]
            s["last_days"] = round(min(known), 1) if known else None
            s["reader_fit"] = reader_fit(linkers.get(s["key"], set()), read_sources)
        out, also = self._other_channels(sources, out, linkers)
        also = sorted(also + moved, key=lambda s: (-s["score"], s["key"]))
        out = order(out)
        missing = {source_id: [root for root in stories if _own_page(sources, source_id, root.url, platforms)]
                   for source_id, stories in started.missing.items()
                   if sources.suggestable(source_id)}
        archives = [{
            "source_id": source_id, "name": sources.name.get(source_id, ""),
            "places": sorted({discover_place(root.url, platforms) for root in stories}),
            "origins": len(stories),
            "since": first_posts[source_id].isoformat() if source_id in first_posts else None,
            "older": sum(1 for root in stories if first_posts.get(source_id) and root.first_at < first_posts[source_id]),
            "origin_stories": [_story(root, title_of) for root in _first(stories)[:ORIGIN_STORIES_SHOWN]],
            "pages": sorted({root.url for root in stories}),
            "page_dates": {root.url: min(r.first_at for r in stories if r.url == root.url).isoformat() for root in stories},
        } for source_id, stories in missing.items() if len(stories) >= DISCOVER_MIN_ARTICLES]
        archives.sort(key=lambda a: (-a["origins"], a["name"].lower()))
        unnamed = sorted(({"place": place, "origins": len(stories)} for place, stories in started.unnamed.items()
                          if len(stories) >= DISCOVER_MIN_ARTICLES), key=lambda u: (-u["origins"], u["place"]))
        walls = site_reads_of(reads)
        page_list = list(pages_of(started, since=now - timedelta(days=PAGES_WITHIN_DAYS), hidden=hidden))
        # A page its posts link by a gift link is walled (its address is shown without the token).
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            gifted = DiscoverRepository.gifted(cur, [url for url, _, _ in page_list])
        page_rows = [{
            "url": strip_access_tokens(url), "title": title_of(url), "site": site_of(host_of(url)), "hide_key": page_key_of(url),
            "follow_url": follow_url(url, platforms),
            "video": video, "tweet": is_tweet(url), "first_linked_at": min(r.first_at for r in roots).isoformat(),
            "voices": len({v for root in roots for v in root.voices}),
            "readable": not (tokened(url) or url in gifted or walls.get(site_of(host_of(url)), SiteReads()).walled),
            "stories": [_story(root, title_of) for root in _first(roots)[:ORIGIN_STORIES_SHOWN]],
        } for url, roots, video in page_list]
        result = {"success": True, "suggestions": out, "also": also, "archives": archives, "unnamed": unnamed,
                  "pages": page_rows, "publication_sites": sorted(publication_sites),
                  "references": [{"key": key, "voices": n} for key, n in sorted(references.items(), key=lambda kv: (-kv[1], kv[0]))],
                  "first_page": FIRST_PAGE}
        if persist:
            try:
                with db.transaction(self.db_url) as cur:
                    DiscoverRepository.keep_list(cur, inputs, result)
            except Exception:  # noqa: BLE001 - derived; the next open makes it again
                logger.exception("Discover: the list was not kept")
        self._discovered = (inputs, result)
        return result

    @staticmethod
    def _other_channels(sources: SourceFacts, found: List[Dict[str, Any]],
                        linkers: Dict[str, Set[str]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """(the suggestions, a followed source's other channels): a suggestion named like one of its linking sources
        (discover_rules.other_channel) is that source's (`of`, `source_id`). NOT_PUBLISHERS own nothing they link."""
        names: Dict[str, Tuple[Set[str], Set[str], Set[str]]] = {}

        def of(source_id: str) -> Tuple[Set[str], Set[str], Set[str]]:
            if source_id not in names:
                kind = sources.kind.get(source_id)
                names[source_id] = (set(), set(), set()) if kind in NOT_PUBLISHERS or kind is None else channel_names(
                    sources.name.get(source_id, ""), account="" if kind == "site" else sources.account.get(source_id) or "",
                    publication=sources.publication(source_id) if kind == "site" else "",
                    shared_sites=sources.shared_sites)
            return names[source_id]

        out, also = [], []
        for s in found:
            owners = sorted((sources.name.get(i, ""), i) for i in linkers.get(s["key"], ()) if other_channel(s["key"], *of(i)))
            if owners:
                also.append({**s, "of": owners[0][0], "source_id": owners[0][1]})
            else:
                out.append(s)
        also.sort(key=lambda s: (-s["score"], s["key"]))
        return out, also

    @staticmethod
    def _title_map(cur: Any, sources: SourceFacts, counted: Dict[str, Any], started: Any,
                   read: Dict[str, Any]) -> Callable[[str], Optional[str]]:
        """One url -> title map for the whole answer, so every line titles a page alike: its story's title, else the
        evidence of the posts linking it (page_titles), else the page's own title as read."""
        titles: Dict[str, Optional[str]] = {url: title for s in counted["found"] for url, _, title in s["articles"] if title}
        roots: Dict[str, Origin] = {}
        for stories in (*started.suggest.values(), *started.missing.values()):
            for root in _first(stories)[:ORIGIN_STORIES_SHOWN] + _first(stories, pages=True)[:DISCOVER_ARTICLES_SHOWN]:
                roots.setdefault(root.url, root)
        titles.update({url: _shown(root) for url, root in roots.items() if _shown(root)})
        found = page_titles.evidence(cur, sources, sorted(url for url in roots if not titles.get(url)))
        titles.update({url: title for url, title in found.items() if title})

        shared = page_titles.shared_titles(read)

        def title_of(url: str) -> Optional[str]:
            return titles.get(url) or page_titles.read(read, url, shared)
        return title_of

    @staticmethod
    def _publication_sites(cur: Any, sources: SourceFacts, found: Iterable[Dict[str, Any]]) -> Set[str]:
        """The sites of publications, where each host is a site of its own (discover_rules.site_unit): the candidate
        multi-host sites the data says are federations (discover_rules.federation); one company's sections are not."""
        hosts = [s["key"] for s in found if "/" not in s["key"]]
        multi = Counter(site_of(h) for h in hosts)
        followed = sources.followed()
        candidates = {site for site, n in multi.items() if n > 1 or site in followed} | set(sources.shared_sites)
        spread = DiscoverRepository.site_hosts(cur, candidates)
        return {site for site, (n, posts) in spread.items() if federation(hosts=n, posts=posts)}

    def _repos(self, cur: Any, sources: SourceFacts) -> List[Dict[str, Any]]:
        """The repositories REPO_MIN_VOICES+ voices link, as their releases channel (markx/official.channel), not
        those already followed: [{key, url, voices, sources, last_at, urls}]."""
        from insight_core.markx import official
        own_sites = {i: sources.publication(i) for i in sources.kind}
        got = DiscoverRepository.repos(cur, kinds=sources.kind, own_sites=own_sites,
                                       selves={i: sorted(sources.selves(i)) for i in sources.kind},
                                       min_voices=REPO_MIN_VOICES, shown=DISCOVER_ARTICLES_SHOWN)
        if not got:
            return []
        followed = official._releases_followed(cur)
        out = []
        for r in got:
            ch = official.channel("https://github.com/" + r["repo"])
            if ch is None or ch.kind != "releases" or ch.key in followed:
                continue
            DiscoverRepository.name_voices(cur, [r], sources.kind, own_sites)
            out.append({**r, "key": ch.key, "url": ch.address})
        return out

    @staticmethod
    def _held(cur: Any, sources: SourceFacts, roots: List[Origin], followed: Set[str],
              platforms: Optional[Dict[str, Tuple[str, ...]]] = None,
              publication_sites: Iterable[str] = frozenset()) -> Dict[str, str]:
        """The places your sources hold (discover_place -> source): their platform accounts and, on followed sites,
        the sections their own posts are in (the source with the most posts there)."""
        platforms = platforms or {}
        held = {account: source_id for source_id, account in sorted(sources.platform_accounts().items())}
        hosts = set()
        for root in roots:
            key, site, platform = discover_address(root.url, platforms)
            root.own = root.stored and sources.home_site(root.source_id) == site
            if key and not platform and site_unit(key, publication_sites) in followed and not root.own:
                hosts.add(host_of(root.url))
        posts: Counter = Counter()
        for source_id, url in DiscoverRepository.posts_on(cur, hosts):
            if site_of(host_of(url)) == sources.home_site(source_id):
                posts[(discover_place(url, platforms), source_id)] += 1
        for (place, source_id), _ in sorted(posts.items(), key=lambda item: (item[1], item[0][1])):
            held[place] = source_id   # the most posts last, so it stays
        return held

    def untitled_classics(self) -> List[str]:
        """The classics the stored data leaves untitled: Discover's reads read their page's title."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.news.untitled_classics(cur)

    def linked_articles(self, address: str) -> List[str]:
        """The articles on an address's host your sources linked (Follow ranks by them). Read only."""
        host = host_of(normalize_url(address) or "")
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.linked_articles(cur, host)

    def hide(self, key: str) -> Dict[str, Any]:
        """Not interested: the suggestion is never shown again."""
        key = (key or "").strip().lower()
        if not key or len(key) > (2048 if key.startswith("page:") else 300):
            raise ValueError("key must be a suggestion's key")
        with db.transaction(self.db_url) as cur:
            self.repo.hide(cur, [key], "not_interested")
        return {"success": True, "key": key}


PARTS = ("keys", "grouping", "news")
# the legacy single stamps as the parts they are on the sample (measured: plan/issues/0216). One not listed reads as
# every part changed; a listed part that later differs simply differs (a rebuild), so the table never needs updating.
LEGACY_RULES: Dict[str, Dict[str, str]] = {
    "7269997ccd26": {"keys": "981f771dc640", "grouping": "377c7f2fc789", "news": "408df32be571"},
    "084d186130fb": {"keys": "981f771dc640", "grouping": "377c7f2fc789"},
}


def _sample_stamps() -> Tuple[Dict[str, str], str]:
    """What the job makes of the sample (utils/stamps.py), read as a run reads its rows (SourceFacts, _story_post),
    fingerprinted by part, and the legacy single stamp (`LEGACY_RULES`)."""
    sources = SourceFacts.of((s[:4] for s in stamps.SOURCES), stamps.HOSTS, stamps.LINKED)
    posts = [StoriesService._story_post(row, sources) for row in stamps.posts()]
    found = grouping(posts)
    stories = found.stories
    names = surges(posts, {s[0]: s[4] for s in stamps.SOURCES})
    made = news(posts, stories, names)
    parts = {"keys": stamps.fingerprint({p.id: sorted(StoriesService.stored_keys(p)) for p in posts}),
             "grouping": stamps.fingerprint([stories, found.edges]),
             "news": stamps.fingerprint([names, made])}
    whole = stamps.fingerprint([stories, found.edges, {p.id: sorted(keys(p)) for p in posts}, names, made])
    return parts, whole


@lru_cache(maxsize=1)
def rules_stamp() -> Dict[str, str]:
    """The rules stories are grouped by, in three parts, each a fingerprint of its own outputs of the sample: `keys`
    (every post's stored keys), `grouping` (the stories and their connections) and `news` (the name surges and News).
    A rule change changes the parts it shows in; a rename or a move changes none. Never mutate it."""
    return _sample_stamps()[0]


@lru_cache(maxsize=1)
def whole_stamp() -> str:
    """These rules' legacy single stamp (the five outputs in one fingerprint)."""
    return _sample_stamps()[1]


def stored_rules(value: Any) -> Dict[str, str]:
    """The rules the stored rows were made by (the setting's `rules`), as parts: a dict as kept; a legacy single stamp
    as this code's parts when it is this code's (`whole_stamp`), else as `LEGACY_RULES` lists it; else no part known."""
    if isinstance(value, dict):
        return {p: value[p] for p in PARTS if isinstance(value.get(p), str)}
    if isinstance(value, str):
        return dict(rules_stamp()) if value == whole_stamp() else dict(LEGACY_RULES.get(value, {}))
    return {}


def redo_for(stored: Dict[str, str], now: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The smallest redo that brings rows made by `stored` rules to `now`'s (rules_stamp()): "grouping" (every post
    regrouped), "keys" (only the posts whose keys moved), "news" (the names and News over the window), or None."""
    now = now or rules_stamp()
    return next((p for p in ("grouping", "keys", "news") if stored.get(p) != now[p]), None)


def rebuild_due(setting: Dict[str, Any]) -> Optional[str]:
    """The redo the story job's setting says is due (`redo_for`), or None; a setting with no rules needs every part."""
    return redo_for(stored_rules(setting.get("rules")))


@lru_cache(maxsize=1)
def code_stamp() -> str:
    """The code Discover's kept list was made by (insight_core's modules, tests aside): other code's list is remade."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha1()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] != "tests":
            digest.update(str(relative).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:16]


def in_own_process(job: Callable[..., Any], *args: Any) -> None:
    """Run `job(*args)` in a fresh process and wait, so its memory goes back to the OS (0072). `job` must be
    module-level (the child imports it by name). A killed child is logged. Never raises."""
    try:
        process = multiprocessing.get_context("spawn").Process(target=job, args=args, name=job.__name__, daemon=True)
        process.start()
        process.join()
        if process.exitcode:
            logger.error("Stories: %s ended with exit code %s", job.__name__, process.exitcode)
    except Exception:  # noqa: BLE001 - derived; the next run recomputes it
        logger.exception("Stories: %s could not run in its own process", job.__name__)


def recompute_job(db_url: str, full: bool = False) -> None:
    """The story job after a fetch run, in its own process (in_own_process); with `full`, every post at
    once (a hand-run rebuild: `python -m insight_core.services.stories_service full`)."""
    logging.basicConfig(level=logging.INFO)
    StoriesService(db_url).recompute_safely(full=full)


def _joins(keys: Set[str]) -> Set[str]:
    """The keys a post is regrouped by when they move: all but its title's names ("n:": they join nothing)."""
    return {k for k in keys if not k.startswith("n:")}


def _first(stories: List[Origin], *, pages: bool = False) -> List[Origin]:
    """A place's stories, the most voices first, then the newest; with `pages`, one per page."""
    ordered = sorted(stories, key=lambda root: (-len(root.voices), -root.first_at.timestamp(), root.url))
    if not pages:
        return ordered
    once: Dict[str, Origin] = {}
    for root in ordered:
        once.setdefault(root.url, root)
    return list(once.values())


def _linking(sources: SourceFacts, voices: Iterable[Tuple[str, Optional[str], bool]], linkers: Iterable[Tuple[str, bool]],
             saved: Set[str]) -> List[Tuple[bool, str]]:
    """The sources linking a suggestion as (only in roundups, name): each voice once, one name once, a Reddit source
    once, never Saved; own-post linkers first. `voices`: (voice, its source, only in roundups); `linkers`: (source,
    only in roundups)."""
    units: Dict[str, Tuple[bool, str]] = {}
    for key, source_id, only in voices:
        if voice.is_poster(key) or voice.source_of(key) in saved:
            continue
        was = units.get(key, (True, ""))[0]
        units[key] = (was and only, sources.voice_name(key, source_id or ""))
    for source_id, only in linkers:
        if sources.kind.get(source_id) == "reddit":
            key = voice.source_key(source_id)
            was = units.get(key, (True, ""))[0]
            units[key] = (was and only, sources.name.get(source_id, ""))
    named: Dict[str, Tuple[bool, str]] = {}
    for unit, (only, name) in units.items():
        key = name.casefold() if name else unit
        was = named.get(key)
        named[key] = (was[0] and only, was[1]) if was else (only, name)
    return sorted(named.values())


def _archive_rows(rows: List[Dict[str, Any]], states: Dict[str, Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    """The archive rows as shown, by each source's archive now: `origins` (pages its stories started at that it
    doesn't store; a row with none left goes), `stored` (stored since), `stopped` (its newest post, when STOPPED_DAYS
    old), `watches` (its page-watch prefix and the missing pages' sections outside it), `archivable` (reachable)."""
    out = []
    for a in rows:
        state = dict(states.get(a["source_id"], {"state": None, "found": 0}))
        stored = set(state.pop("stored_urls", ()))
        newest, prefix, host = state.pop("newest", None), _prefix(state.pop("prefix", None)), state.pop("host", None)
        missing = [url for url in a["pages"] if url not in stored]
        if not missing:
            continue
        row = {k: v for k, v in a.items() if k not in ("pages", "page_dates")}
        since = datetime.fromisoformat(a["since"]) if a.get("since") else None
        dates = a.get("page_dates") or {}
        row.update(origins=len(missing), stored=len(stored),
                   older=sum(1 for url in missing if since and url in dates and datetime.fromisoformat(dates[url]) < since),
                   origin_stories=[o for o in a["origin_stories"] if o["url"] not in stored], archive=state)
        if isinstance(newest, str):
            newest = datetime.fromisoformat(newest)
        stopped = newest is not None and (now - newest).days >= STOPPED_DAYS
        if stopped:
            row["stopped"] = newest.isoformat()
        def own(url: str) -> bool:
            return not host or host_of(url).removeprefix("www.") == host
        under = [url for url in missing if not prefix or (own(url) and _url_path(url).startswith(prefix))]
        if prefix and len(under) < len(missing):
            row["watches"] = {"prefix": prefix, "not": sorted({("/" + _url_path(url).strip("/").split("/")[0]) if own(url)
                                                               else host_of(url).removeprefix("www.")
                                                               for url in missing if url not in under})}
        row["archivable"] = 0 if stopped else len(under)
        out.append(row)
    out.sort(key=lambda a: (-a["origins"], a["name"].lower()))
    return out


def _site_source(sources: SourceFacts, host: str) -> Optional[str]:
    """The source that follows a site (by its own site or its address's), the first by id; None when none."""
    site = site_of(host)
    for source_id in sorted(sources.kind):
        if sources.kind.get(source_id) in NOT_PUBLISHERS:
            continue
        if site in (sources.own_site(source_id), sources.handle_site.get(source_id)):
            return source_id
    return None


def _own_page(sources: SourceFacts, source_id: str, url: str, platforms: Dict[str, Tuple[str, ...]]) -> bool:
    """Whether a page is a source's own: on a platform, its account's; else on its site (its posts' or address's)."""
    key, site, platform = discover_address(url, platforms)
    if platform:
        return key is not None and key == sources.account.get(source_id)
    return bool(site) and site in (sources.own_site(source_id), sources.handle_site.get(source_id))


def _prefix(value: Optional[str]) -> Optional[str]:
    """A page-watch prefix as /a/b/ (page_watch.normalise_prefix's form), None when there is none."""
    if not value or not str(value).strip("/"):
        return None
    return "/" + str(value).strip("/") + "/"


def _url_path(url: str) -> str:
    _, _, rest = url.split("://", 1)[-1].partition("/")
    return "/" + rest.split("?", 1)[0].split("#", 1)[0]


def _shown(root: Origin) -> Optional[str]:
    """A story origin's title as Discover shows it: never its address's slug."""
    return root.title if root.stored or root.title != slug_title(root.url) else None


def _story(root: Origin, title_of: Callable[[str], Optional[str]]) -> Dict[str, Any]:
    """A story a place started, as Discover lists it, titled by the answer's one map."""
    return {"url": root.url, "title": title_of(root.url), "voices": len(root.voices), "stored": root.stored}


def _platforms(kept: Optional[Dict[str, Any]]) -> Dict[str, Tuple[str, ...]]:
    """The data's platforms Discover's kept counts were keyed by."""
    return {host: tuple(prefix) for host, prefix in ((kept or {}).get("platforms") or {}).items()}


def _words(s: Dict[str, Any]) -> str:
    """What Discover's search box matches: the key, the sources linking it, its articles' and stories' titles."""
    parts = [s["key"], *s["voice_names"], *(f"{a['title'] or ''} {a['url']}" for a in s["articles"]),
             *(f"{o['title'] or ''} {o['url']}" for o in s.get("origin_stories", ()))]
    return " ".join(parts).casefold()


if __name__ == "__main__":
    import os
    if sys.argv[1:] != ["full"]:
        sys.exit("usage: python -m insight_core.services.stories_service full")
    in_own_process(recompute_job, os.environ["DATABASE_URL"], True)
