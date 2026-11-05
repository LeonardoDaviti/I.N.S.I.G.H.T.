"""One story, many sources (issue 0050): the story job and Discover.

The story job runs after each fetch run that saved posts (IngestionRunner's `stories` port) and
once when the backend starts (main.py, in the background), each time in a process of its own
(in_own_process, issue 0072). It is incremental (issue 0072 A):
1. it reads the links of every post never read (the posts stored before 0050), 500 a transaction;
2. it takes the posts saved, changed or removed since the last run (`story_queue`, written by
   migration 0059's triggers), a batch a transaction, and regroups only what they touch: the
   posts holding a key they hold (story_rules.keys: a text, a title, an address, a page they link)
   and the stories those are in, then whatever the rules join to those (`_neighbourhood`). Only the
   rows that differ are written: stories, their posts and mentions, the connections (`post_edges`),
   News for the stories and names touched and the window's moving edge, Classics for the pages
   linked, Discover's counts for the keys linked. A new story keeps its id when an earlier post joins.
3. a rule change (another `rules_stamp`, issue 0071) regroups every post the same way, in bounded
   batches, in the background: the posts' keys and the threads first, then every post queued
   (`redo:`). The rows of the old rules are served until each batch replaces them.
`recompute(full=True)` regroups every post at once (`regroup`): the oracle the incremental job is
measured against, row by row (the same stories, News, Classics and Discover). Deterministic and
idempotent. One job at a time (an advisory lock); a job that finds one running skips. No AI, no fetch.
"""
from __future__ import annotations

import hashlib
import logging
import multiprocessing
import sys
import time
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_post_parts import catch_up_safely
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services import page_titles
from insight_core.services.news_service import NewsService
from insight_core.utils import stamps
from insight_core.utils.news_rules import news, surges
from insight_core.utils.addresses import host_of, site_of, x_account
from insight_core.utils.post_links import PLATFORM_KINDS
from insight_core.utils.discover_rules import (DISCOVER_MIN_ARTICLES, DISCOVER_MIN_VOICES, FIRST_PAGE, Origin,
                                              REFERENCE_KINDS, discover_address, discover_open, discover_place, federation,
                                              one_card_per_domain, order, origins, owner_domain, own_names,
                                              place_kind, same_owner, score)
from insight_core.utils.story_rules import (LINK_POST_KINDS, NOT_PUBLISHERS, SAME_TEXT_WITHIN, THREAD_WITHIN, Edge, Grouping, StoryPost,
                                            date_alone, grouping, keys, page_key, threads)
from insight_core.utils.tree_rules import _PAGE, slug_title
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger(__name__)

STORY_WINDOW = SAME_TEXT_WITHIN   # News keeps the stories begun in it (NewsService.NEWS_KEEP)
SETTINGS_KEY = "stories"
LOCK_KEY = "insight.stories"
STORY_BATCH = 1000    # queued posts a batch starts from (a fetch run's are fewer; a rule change's are all)
KEYS_BATCH = 2000     # posts a rule change reads the keys of a transaction
CLOSURE_KEYS = ("h:", "t:", "u:", "g:")   # the keys a post joins another by (story_rules.keys)
KEYED_EDGES = ("text", "title", "address", "link", "quote")   # the connections a key makes (story_rules.Edge.via)
DISCOVER_ARTICLES_SHOWN = 20
ORIGIN_STORIES_SHOWN = 3      # the stories a suggestion started, shown on its card (issue 0065)
STOPPED_DAYS = 183            # an archive row's source whose newest post is this old: its feed stopped (issue 0109)


class StoriesService:
    def __init__(self, db_url: str, *, repo: StoriesRepository | None = None,
                 clock: Callable[[], datetime] | None = None, news: NewsService | None = None):
        self.db_url = db_url
        self.repo = repo or StoriesRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # News and Classics (issue 0051) are refreshed by this job, on its transaction.
        self.news = news or NewsService(db_url, clock=self.clock)
        # Discover counts every kept link in the database (138k on the server's data), and its inputs change only
        # with a story run, a source or a hidden suggestion: the last list is kept until they do, here and in the
        # database (issue 0080 cold open: a fresh process reads it, the story job makes it).
        self._discovered: tuple = ("", None)
        code_stamp()   # read at start, not on an open

    # ---- the job ------------------------------------------------------------------------

    def fill_links(self) -> int:
        """Read the links of every post never read, a batch a transaction, until none is left
        (issue 0069: the search refill may hold some for a moment). Returns how many."""
        return db.fill_until_done(self.db_url, self.repo.fill_missing_links, self.repo.missing_links)

    def recompute(self, *, full: bool = False) -> Dict[str, Any]:
        """The story job: what the queue holds, a batch a transaction (a rule change's rebuild first),
        or with `full` every post at once (the oracle). Returns a summary."""
        started = time.monotonic()
        catch_up_safely(self.db_url)   # every post read once first (issue 0076): what the job and the pages read
        filled = self.fill_links()
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
                    return {"computed_at": self.clock().isoformat(), "full": False, **totals, "links_filled": filled,
                            "batches": totals["batches"], "seconds": round(time.monotonic() - started, 2)}

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
        if counts.get("boilerplate_changed"):   # kept links became boilerplate or stopped being: Discover counts them
            step["links_changed"] = True
        summary = {"computed_at": now.isoformat(), "full": False, "links_filled": links_filled, **totals,
                   "batches": totals["batches"], "seconds": round(time.monotonic() - (started or time.monotonic()), 2)}
        self._settle(cur, sources, summary, now, step)
        self._discover_step(cur, sources, step.get("discover"))
        return True

    def update(self, cur: Any) -> Dict[str, Any]:
        """The incremental job on the caller's transaction, every step until none is left (recompute
        commits each step on its own). Returns its counts."""
        totals: Counter = Counter()
        while self.advance(cur, totals):
            pass
        return dict(totals)

    @staticmethod
    def _lock(cur: Any) -> bool:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        return cur.fetchone()[0]

    def _settle(self, cur: Any, sources: SourceFacts, summary: Dict[str, Any], now: datetime,
                state: Dict[str, Any]) -> None:
        """The run's setting: its summary, what the stored rows are (their rules, the sources' facts,
        News's window, when Discover's inputs last changed) and a rebuild's progress (Background work reads it)."""
        previous = (SystemSettingsRepository.get(cur, SETTINGS_KEY) or ({}, None))[0] or {}
        value = {**{k: v for k, v in previous.items() if k in ("rules", "full_at", "facts", "rebuild", "news_since",
                                                                "discover_at")},
                 **summary, **self.repo.counts(cur)}
        # When what Discover counts from last changed (issue 0080 speed): a batch (its links, stories and
        # Classics), a full run, links read. A rebuild's other steps (keys, threads, names) change none of it,
        # so Discover's kept counts and its list stay valid through them.
        # Settings from before discover_at keep their last run's time as it, so the counts kept by it hold.
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
        """Every post at once, on the caller's transaction (the oracle): boilerplate, stories, their
        connections and keys, the thread edges, News, Classics. Returns what it counted and how many
        rows changed."""
        sources = SourceFacts(cur)
        boilerplate = len(self.repo.mark_boilerplate(cur, sources))
        posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources)]
        found = grouping(posts)
        stamp = rules_stamp()
        changed = self.repo.write_stories(cur, found.stories)
        edges = (self.repo.write_edges(cur, found.edges, made_by=stamp)
                 + self.repo.write_edges(cur, found.edges, made_by=stamp, threads=True))
        keys_changed = self.repo.write_keys(cur, {p.id: self._keys(p) for p in posts})
        news_counts = self.news.refresh(cur, posts=posts, stories=found.stories, sources=sources)
        self.repo.clear_queue(cur)
        return {"posts": len(posts), "stories": len(found.stories), "changed": changed, "edges_changed": edges,
                "keys_changed": keys_changed, "boilerplate_changed": boilerplate, **news_counts}

    # ---- one step of the incremental job (issue 0072 A) ------------------------------------

    def step(self, cur: Any, sources: SourceFacts, previous: Dict[str, Any], now: datetime, *,
             window: bool = True) -> Optional[Dict[str, Any]]:
        """One bounded step on the caller's transaction: a rule change's next step, else a batch of the
        queue, else (with `window`) News's window edge. None when nothing is left. Returns the state
        to keep and `counts`."""
        stamp = rules_stamp()
        rebuild = previous.get("rebuild")
        if previous.get("rules") != stamp and (rebuild or {}).get("rules") != stamp:
            rebuild = {"rules": stamp, "phase": "keys", "after": None, "started_at": now.isoformat(),
                       "total": self.repo.count_posts(cur), "done": 0}
            boilerplate = len(self.repo.mark_boilerplate(cur, sources))   # by the new rules, once
            return {"rebuild": rebuild, "counts": Counter(boilerplate_changed=boilerplate, batches=1)}
        if rebuild and rebuild["phase"] != "stories":
            return self._rebuild_step(cur, sources, rebuild, stamp)
        self._facts_changed(cur, sources, previous.get("facts"))
        batch = self._batch(cur, sources, previous, now, stamp, redo=bool(rebuild), window=window)
        if batch is not None:
            if rebuild:
                rebuild = {**rebuild, "done": rebuild["total"] - self.repo.queued(cur)["redo"]}
                batch["rebuild"] = rebuild
            return batch
        if rebuild:   # every post regrouped by the new rules: they are the rows now
            return {"rebuild": None, "rules": stamp, "full_at": now.isoformat(), "discover": "all",
                    "counts": Counter(batches=1)}
        return None

    def _rebuild_step(self, cur: Any, sources: SourceFacts, rebuild: Dict[str, Any], stamp: str) -> Dict[str, Any]:
        """A rule change's steps before its batches: every post's keys (KEYS_BATCH a step), each X
        source's thread edges (one source a step), every name's surges, then every post queued."""
        rebuild = dict(rebuild)
        counts: Counter = Counter(batches=1)
        if rebuild["phase"] == "keys":
            ids = self.repo.post_ids(cur, rebuild["after"], KEYS_BATCH)
            posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources, ids)]
            counts["keys_changed"] = self.repo.write_keys(cur, {p.id: self._keys(p) for p in posts})
            rebuild["after"] = ids[-1] if ids else None
            if len(ids) < KEYS_BATCH:
                rebuild.update(phase="threads", left=sorted(sources.of_kind("x")))
        elif rebuild["phase"] == "threads":
            left = list(rebuild["left"])
            if left:
                source_id = left.pop(0)
                ids = self.repo.timeline(cur, source_id, datetime.min.replace(tzinfo=timezone.utc),
                                         datetime.max.replace(tzinfo=timezone.utc))
                posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources, ids)]
                counts["edges_changed"] = self.repo.write_edges(
                    cur, [Edge(c, p, "thread") for c, p in threads(posts).items()], made_by=stamp, post_ids=ids,
                    threads=True)
            rebuild["left"] = left
            if not left:
                rebuild.pop("left")
                rebuild["phase"] = "names"
        elif rebuild["phase"] == "names":
            counts["surges_changed"] = self.news.judge_names(cur, sources, None)
            rebuild["queued"] = self.repo.redo_every_post(cur)
            rebuild["phase"] = "stories"
        return {"rebuild": rebuild, "counts": counts}

    def _facts_changed(self, cur: Any, sources: SourceFacts, before: Optional[Dict[str, Any]]) -> None:
        """A source whose facts changed (its kind, site, publication, account or name: a rule input)
        has its posts queued; an account followed or left, the posts of X that name it."""
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
        """What the rules read of each source, as a fingerprint, and the accounts followed."""
        return {"sources": {s: stamps.fingerprint([sources.kind[s], sources.publication(s), sources.own_site(s),
                                                   sources.home_site(s), sources.account.get(s), sources.name.get(s),
                                                   sources.own_site(s) in sources.shared_sites])
                            for s in sorted(sources.kind)},
                "accounts": sorted(a for a in sources.of_account)}

    def _batch(self, cur: Any, sources: SourceFacts, previous: Dict[str, Any], now: datetime, stamp: str, *,
               redo: bool, window: bool) -> Optional[Dict[str, Any]]:
        """A batch of the queue: the posts saved, changed or removed (else, in a rebuild, a rule
        change's), and what they touch, regrouped; then News, Classics and Discover for them. None
        when the queue is empty and News's window has not moved."""
        taken = self.repo.take_queue(cur, STORY_BATCH)
        rebuilding = not taken and redo
        if rebuilding:
            taken = self.repo.take_queue(cur, STORY_BATCH, redo=True)
        since = now - self.news.keep
        edge = window and previous.get("news_since") != since.isoformat()
        if not taken and not edge:
            return None
        seeds: Set[str] = set()
        gone: Set[str] = set()     # the keys of removed posts
        titles: List[Optional[str]] = []
        points: List[Tuple[str, datetime]] = []   # where a timeline changed: (source, time)
        was_at: Dict[str, str] = {}   # a changed post's address before
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
        seeds |= self._threads(cur, sources, points, stamp)
        load(seeds)
        seeds = {s for s in seeds if s in posts}   # a removed post is no seed: its keys are (`gone`)
        titles += [posts[s].title for s in seeds if s in posts]
        before = self.repo.stored_keys(cur, sorted(seeds))
        touched = gone | {k for s in seeds for k in before.get(s, set()) | self._keys(posts[s])}
        # Where a seed is or was: the posts linking there read their links again (an own page moved).
        moved = gone | {k for s in seeds for url in (posts[s].url, was_at.get(s)) if url
                        for k in ("u:" + url, page_key(url)) if k}
        self.rounds: List[Tuple[int, int, int]] = []
        found, scope = self._neighbourhood(cur, posts, load, seeds, moved)
        stories = [s for s in found.stories if s.posts[0].id in scope]
        counts: Counter = Counter(batches=1, posts=len(scope), seeds=len(seeds), rounds=len(self.rounds),
                                  context=self.rounds[-1][2])   # what the rules read around the scope
        roots = {found.root[pid] for pid in scope if pid in found.root}
        nodes = {node for node, root in found.root.items() if root in roots} | scope
        # A roundup of the scope mentions the stories outside it as they are stored (they are unchanged).
        outside = {n for pid, listed in found.listed.items() if pid in scope for n in listed if n not in nodes}
        # Read past the scope: a page only its posts linked is in no story now (issue 0110).
        held = self.repo.stories_holding(cur, sorted(outside), besides=sorted(scope))
        mentioned = self.repo.mentioned_by(cur, sorted(scope))   # the stories its roundups mentioned before
        mentions = [Edge(pid, n, "mention") for pid, listed in found.listed.items() if pid in scope
                    for n in dict.fromkeys(listed) if n in held]
        counts["changed"] = self.repo.write_stories(cur, stories, post_ids=sorted(scope),
                                                    mentions={(held[e.dst], e.src) for e in mentions})
        # The scope's connections, and the mentions of its nodes (now and before) by roundups outside it.
        nodes |= {_PAGE + url for url in self.repo.pages_linked(cur, sorted(scope))}
        counts["edges_changed"] = self.repo.write_edges(
            cur, [e for e in found.edges if e.dst in nodes and (e.src in scope or e.kind == "mention")
                  or e.src in scope and e.kind != "mention"] + mentions,
            made_by=stamp, post_ids=sorted(scope), mentioned=sorted(nodes))
        counts["keys_changed"] = self.repo.write_keys(cur, {pid: self._keys(posts[pid]) for pid in scope})
        if rebuilding:
            self.repo.done(cur, scope)
        urls = {k[2:] for k in touched if k.startswith(("u:", "l:"))}
        # A post stored at an address another links can make that one a roundup or not: its pages too.
        own = {posts[s].url for s in seeds if posts[s].url}
        urls |= {t for p in posts.values() if any(target in own for target, _ in p.links) for t, _ in p.links}
        # News regroups the scope's stories, and those a roundup of it mentions (their mentions count in News).
        mentioned |= self.repo.story_mates(cur, [n for n in held if not n.startswith(_PAGE)])
        mentioned |= self.repo.story_mates(cur, self.repo.linking(cur, sorted(n[len(_PAGE):] for n in held if n.startswith(_PAGE))))
        counts.update(self.news.update(cur, sources=sources, posts=posts, load=load, touched=scope | mentioned, titles=titles,
                                       urls=sorted(urls), since=since,
                                       before=datetime.fromisoformat(previous["news_since"])
                                       if previous.get("news_since") else None))
        return {"counts": counts, "discover": sorted(urls)}

    def _threads(self, cur: Any, sources: SourceFacts, points: List[Tuple[str, datetime]], stamp: str) -> Set[str]:
        """The thread edges around these points of X timelines (a post saved, changed or removed at
        that time): each post within THREAD_WITHIN of one is the post its predecessor continues, or
        none, read from its source's posts within twice that (story_rules.threads). Returns the posts
        whose edge changed, and their old and new parents."""
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
            self.repo.write_edges(cur, [Edge(c, found[c], "thread") for c in children if c in found], made_by=stamp,
                                  post_ids=children, threads=True)
        return changed

    def _neighbourhood(self, cur: Any, posts: Dict[str, StoryPost], load: Callable[[Iterable[str]], None],
                       seeds: Set[str], moved: Set[str]) -> Tuple[Grouping, Set[str]]:
        """What a batch regroups (`scope`), and the rules' grouping of it. The scope starts at the seeds,
        the posts linking an address one is or was at (`moved`: its own page changes where their links
        lead), and the stories those are in; then it grows until it is whole. Each round groups the scope
        with what the rules read around it: every post holding a key a post of the scope holds (`near`),
        and the posts at the addresses those link (`_context`), so that each connection the rules make
        through those keys is the one a full run makes. The scope takes in each group of the rules that
        holds a post of it, and every post near it whose connection through such a key differs from the
        stored one (a new post in a chain of copies, or a page's first linker), with their old stories
        (BACKEND.md, "The incremental story job")."""
        scope = self.repo.story_mates(cur, seeds | self.repo.holders(cur, moved))
        held: Set[str] = set()
        near: Set[str] = set()
        context: Set[str] = set()
        replies: Dict[str, str] = {}
        keyed: Set[str] = set()      # each post's keys, links and thread edges are read once
        linked: Set[str] = set()
        threaded: Set[str] = set()
        found, grouped = None, -1
        while True:
            load(scope)
            stored = self.repo.stored_keys(cur, sorted(scope - keyed))
            new = {k for pid in scope - keyed for k in self._keys(posts[pid]) | stored.get(pid, set())
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
            if len(context) != grouped:   # the same posts read: the same grouping
                found, grouped = grouping([posts[pid] for pid in context], replies=replies), len(context)
            grows = self._grows(cur, posts, found, scope, near - scope, held)
            self.rounds.append((len(scope), len(near), len(context)))
            if not grows:
                return found, scope
            scope |= grows

    def _context(self, cur: Any, posts: Dict[str, StoryPost], ids: Set[str]) -> Set[str]:
        """The posts the rules read to resolve these posts' links and addresses: those stored at the
        addresses they link, and those at another path of one of their pages (story_rules.page_aliases)."""
        urls = {t for pid in ids for t, _ in posts[pid].links}
        pages = {"a:" + k[2:] for url in urls | {posts[pid].url for pid in ids} if url and (k := page_key(url))}
        return self.repo.at_addresses(cur, sorted(urls)) | self.repo.holders(cur, pages)

    def _grows(self, cur: Any, posts: Dict[str, StoryPost], found: Grouping, scope: Set[str], near: Set[str],
               held: Set[str]) -> Set[str]:
        """What the scope must take in so its stories are whole (`_neighbourhood`), with their old stories."""
        roots = {found.root[pid] for pid in scope if pid in found.root}
        grows = {node for node, root in found.root.items() if root in roots and not node.startswith(_PAGE)} - scope
        pages = {node[len(_PAGE):] for node, root in found.root.items() if root in roots and node.startswith(_PAGE)}
        # A platform roundup may be a member of the one story it lists (story_rules): of the scope, the
        # stories it lists are read; near the scope, it joins when it lists one of the scope's stories.
        for pid, nodes in found.listed.items():
            if posts[pid].kind in PLATFORM_KINDS and (pid in scope or pid in near
                                                      and any(found.root.get(n) in roots for n in nodes)):
                grows |= {pid} | {n for n in nodes if not n.startswith(_PAGE)}
                pages |= {n[len(_PAGE):] for n in nodes if n.startswith(_PAGE)}
        # A post near the scope whose connection through a key the scope holds is not the stored one.
        computed = {(e.src, e.dst, e.kind) for e in found.edges if e.via in held and e.src in near}
        stored = {(e.src, e.dst, e.kind) for e in self.repo.edges_of(cur, sorted(near), KEYED_EDGES)
                  if e.via in held and e.src in near}
        grows |= {node for src, dst, _ in computed ^ stored for node in (src, dst) if not node.startswith(_PAGE)}
        grows |= self.repo.linking(cur, sorted(pages))
        return self.repo.story_mates(cur, grows) - scope

    def _keys(self, post: StoryPost) -> Set[str]:
        """A post's stored keys: what it joins by (story_rules.keys), its address's page key ("a:": the
        posts at another path of it), the names in its title (News: "n:"), and the home pages it links
        ("l:": no join, but Classics and Discover count them)."""
        out = keys(post)
        if post.url and page_key(post.url):
            out.add("a:" + page_key(post.url)[2:])
        out |= {"l:" + target for target, _ in post.links if "u:" + target not in out}
        return out | {"n:" + name for name in self.news.names_of(post)}

    @staticmethod
    def _story_post(row: Dict[str, Any], sources: SourceFacts) -> StoryPost:
        """Every field the story job reads of a post, from its stored row and parts (load_posts: issue 0076,
        read once, when it was saved) and its source's facts, here only (issue 0072)."""
        kind = sources.kind.get(row["source_id"], "site")
        author_source = sources.of_account.get(x_account(row["author"])) if kind == "x" and row["author"] else None
        return StoryPost(
            id=row["id"], source_id=row["source_id"], kind=kind, own_site=sources.publication(row["source_id"]),
            # Issue 0076: one post for everyone, the title every page shows (its stored one until parsed).
            t=row["t"], title=row["title"] if row["shown_title"] is None else row["shown_title"], opening=row.get("opening"),
            content_hash=row["content_hash"], text_chars=row["text_chars"],
            words=row["words"] if kind in LINK_POST_KINDS else None,
            author=row["poster"] if kind == "reddit" else row["author"],
            url=row["url"], links=row["links"],
            # Where its page moved (issue 0108, metadata.moved_to): one page with the post stored there.
            moved_to=row.get("moved_to") if row.get("moved_to") != row["url"] else None,
            # The tree's evidence (issue 0064): link words, a page updated since its date, its own site.
            link_texts=row["link_texts"], updated=row["updated"], home_site=sources.home_site(row["source_id"]),
            # On X (issue 0066): a tweet of another account (a repost), the account a reply answers, a quote.
            reposted=kind == "x" and bool(row["author"])
            and sources.account.get(row["source_id"]) != x_account(row["author"]),
            reply_to=row["reply_to"] if kind == "x" else None,
            quoted=row["quoted"] if kind == "x" else None,
            quoted_words=row["quoted_words"],   # the words of the pages it quotes (issue 0070)
            # Who else of your sources put it before you (issue 0068): its author's own source, when
            # another source holds it, and the sources that reposted it. Voices of its story.
            reposters=tuple(sorted({sources.of_account.get(x_account(by)) for by in row["reposted_by"]}
                                   - {None, row["source_id"], author_source})),
            author_source=author_source if author_source != row["source_id"] else None,
            # How precise its date is (issue 0076: posts.published_precision, as the source said it at
            # ingestion; a post stored before it, told by its time as before).
            stored_at=row.get("stored_at"),
            date_alone=row["precision"] == "date" if row.get("precision") in ("date", "exact") else date_alone(row["t"]),
            undated=row.get("precision") == "none",
        )

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
        """After a story run, in its process: Discover's list made for what the run changed and kept, so the
        first open after it reads one row (issue 0080 cold open: making it reads ~16k pages of posts and links,
        13.6 s on the lab when they had left the cache and the disk was busy). Never raises."""
        try:
            self._discover_all()
        except Exception:  # noqa: BLE001 - derived; Discover makes it on its next open
            logger.exception("Stories: Discover's list was not kept")

    # ---- Discover -----------------------------------------------------------------------

    def fill_discover_addresses(self) -> int:
        """After a full story run: work out the addresses its links point to, and its platform posts are
        at, that Discover has not met (issue 0062), and count and keep Discover's counts (issue 0067),
        so Discover's first open after the run needn't. Never raises: Discover does both itself
        when they are missing."""
        try:
            with db.transaction(self.db_url) as cur:
                sources = SourceFacts(cur)
                filled = DiscoverRepository.fill_addresses(cur, sources.platform_accounts(),
                                                           platforms=_platforms(DiscoverRepository.kept(cur)))
                self._counted(cur, sources)
                return filled
        except Exception:  # noqa: BLE001 - derived; Discover fills what is missing
            logger.exception("Stories: Discover's addresses were not filled")
            return 0

    def _discover_step(self, cur: Any, sources: SourceFacts, urls: Any) -> None:
        """After a batch, on its transaction: Discover's addresses and counts for the addresses its posts
        link and are at (issue 0072 A), or every one ("all": a rule change done). Never raises: a
        savepoint keeps the batch when it fails, and Discover does both itself when they are missing."""
        if urls is None:
            return
        try:
            with cur.connection.transaction():
                DiscoverRepository.fill_addresses(cur, sources.platform_accounts(), urls=None if urls == "all" else urls,
                                                  platforms=_platforms(DiscoverRepository.kept(cur)))
                self._counted(cur, sources, urls=None if urls == "all" else urls)
        except Exception:  # noqa: BLE001 - derived; Discover fills what is missing
            logger.exception("Stories: Discover's counts were not updated")

    @staticmethod
    def _counted(cur: Any, sources: SourceFacts, urls: Optional[List[str]] = None) -> Dict[str, Any]:
        """Discover's counts by links (issue 0062), grouped and counted in the database: the kept ones
        when what they are counted from is unchanged (issue 0067: the story job keeps them), else
        counted now and kept. With `urls` (a story run's addresses, issue 0072 A), while the rules, the
        mirrors and the platforms hold, only the keys of those addresses are counted again (a source whose
        facts change has its posts queued, so the addresses they link are a run's too), by the kept
        platforms; a full count finds the platforms the data finds again (issue 0080: 2.3 s on the lab, and a
        story run's few links don't move them).
        {stamp, base, found (DiscoverRepository.counts, by key), mirrors, platforms, scanned_to}."""
        accounts = sources.platform_accounts()
        own_sites = {i: sources.publication(i) for i in sources.kind}
        selves = {i: sorted(sources.selves(i)) for i in sources.kind}
        ask = dict(kinds=sources.kind, own_sites=own_sites, accounts=accounts, shown=DISCOVER_ARTICLES_SHOWN, selves=selves)
        facts = sorted((i, sources.kind[i], own_sites[i], accounts.get(i, ""), selves[i]) for i in sources.site)
        stamp, base = DiscoverRepository.stamp(cur, facts), DiscoverRepository.base()
        kept = DiscoverRepository.kept(cur)
        if kept and kept["stamp"] == stamp:
            return kept
        mirrors, scanned_to = DiscoverRepository.mirrors(cur, kept)
        if urls is not None and kept and kept.get("base") == base and mirrors == kept["mirrors"] and "platforms" in kept:
            platforms = _platforms(kept)
            keys = DiscoverRepository.keys_of(cur, urls, platforms)
            found, _ = DiscoverRepository.counts(cur, mirrors=mirrors, keys=keys, platforms=platforms, **ask)
            # An article's title changes only with the posts at it or linking it: those of the run's addresses.
            titled = {a[0]: a[2] for s in kept["found"] for a in s["articles"] if a[0] not in set(urls)}
            StoriesService._title_articles(cur, sources, found, titled)
            found += [s for s in kept["found"] if s["key"] not in keys]
            DiscoverRepository.name_voices(cur, found, ask["kinds"], ask["own_sites"])   # a site's namer may move
        else:
            platforms = DiscoverRepository.platforms(cur, kinds=sources.kind, own_sites=own_sites, selves=selves)
            found, unknown = DiscoverRepository.counts(cur, mirrors=mirrors, platforms=platforms, **ask)
            if unknown:   # addresses no story run has worked out yet (the job does it after reading links)
                DiscoverRepository.fill_addresses(cur, accounts, platforms=platforms)
                found, _ = DiscoverRepository.counts(cur, mirrors=mirrors, platforms=platforms, **ask)
            StoriesService._title_articles(cur, sources, found)
        found.sort(key=lambda s: s["key"])
        kept = {"stamp": stamp, "base": base, "found": found, "mirrors": mirrors, "scanned_to": scanned_to,
                "platforms": {host: list(prefix) for host, prefix in sorted(platforms.items())}}
        DiscoverRepository.keep(cur, kept)
        return kept

    @staticmethod
    def _title_articles(cur: Any, sources: SourceFacts, found: List[Dict[str, Any]],
                        titled: Optional[Dict[str, Optional[str]]] = None) -> None:
        """Each shown article's title (issue 0070): a stored post's own, as the reader shows it, else
        by the evidence a story's outside origin is titled by (origin_title), from every post linking it,
        in time order as a story's are (issue 0071: link words written two ways as often are a tie the
        first one wins, and the database returns rows in any order); never its address's slug (issue
        0080), and a tweet only by its own words as a post quotes them (else the line names its account).
        `titled`: the titles kept, which hold (an incremental run's addresses aside)."""
        titled = titled or {}
        urls = sorted({url for s in found for url, _ in s["articles"] if url not in titled})
        titles = page_titles.evidence(cur, sources, urls)   # one title for a page you don't follow (issue 0106)
        for s in found:
            s["articles"] = [(url, voices, titled[url] if url in titled else titles[url]) for url, voices in s["articles"]]

    def discover(self, *, offset: int = 0, limit: Optional[int] = None, q: Optional[str] = None) -> Dict[str, Any]:
        """Sites and accounts your sources keep linking that you don't follow, each with why, ranked
        (issue 0080: discover_rules.score; issue 0109: discover_rules.order, the tested followable first, then
        the ones that can't be followed as a feed, `section: "unfollowable"`, then the untested); the
        references they use and the stories the sources you follow miss beside them. `offset` and
        `limit`: the page asked for (the first holds FIRST_PAGE); `q`: only those whose words match."""
        result = self._discover_all()
        if result["archives"]:   # each archive row follows its source's archive, read now (it runs on its own)
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                states = DiscoverRepository.archive_states(cur, {a["source_id"]: a["pages"] for a in result["archives"]})
            result = {**result, "archives": _archive_rows(result["archives"], states, self.clock())}
        ranked, also = result["suggestions"], result.get("also", [])
        if q:
            words = q.casefold().split()
            ranked = [s for s in ranked if all(w in _words(s) for w in words)]
            also = [s for s in also if all(w in _words(s) for w in words)]
        end = len(ranked) if limit is None else offset + max(0, limit)
        # A followed source's other channels are one folded group, with the first page (issue 0109).
        return {**result, "suggestions": ranked[offset:end], "also": also if offset == 0 else [], "total": len(ranked),
                "offset": offset, "more": end < len(ranked)}

    def _discover_all(self) -> Dict[str, Any]:
        """The whole list: this process's last when its inputs and code are unchanged, else the one the
        database keeps for them (a story run's, another process's), else made now and kept."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            inputs = self.repo.discover_inputs(cur) + "|" + code_stamp()
            if self._discovered[0] == inputs and self._discovered[1] is not None:
                return self._discovered[1]
            kept = DiscoverRepository.kept_list(cur, inputs)
            if kept is not None:
                self._discovered = (inputs, kept)
                return kept
            # Grouped and counted in the database (issue 0062): the kept links never come to Python.
            sources = SourceFacts(cur)
            counted = self._counted(cur, sources)
            platforms = _platforms(counted)
            followed, hidden, classics = sources.followed(), self.repo.hidden(cur), set(self.news.classic_urls(cur))
            roots = DiscoverRepository.story_origins(cur, kinds=sources.kind,
                                                     own_sites={i: sources.publication(i) for i in sources.kind})
            held = self._held(cur, sources, roots, followed, platforms)
            started = origins(roots, followed=followed, held=held, mirrors=set(counted["mirrors"]), platforms=platforms)
            first_posts = DiscoverRepository.first_posts(cur, started.missing)
            activity = DiscoverRepository.activity(cur, [s["key"] for s in counted["found"]], platforms)
            reads = DiscoverRepository.reads(cur)
            title_of = self._title_map(cur, sources, counted, started, reads.get("titles", {}))
        now = self.clock()
        saved = set(sources.of_kind("saved"))
        out, references, last, weight = [], {}, {}, {}
        linkers: Dict[str, Set[str]] = defaultdict(set)   # a key -> the sources whose posts link it (issue 0109)
        for s in counted["found"]:
            if not discover_open(s["key"], site_of(s["key"]), "/" in s["key"], followed=followed, hidden=hidden,
                                 followed_accounts=sources.followed_accounts()):
                continue   # followed or hidden (a platform's key is its account, x.com/karpathy; a site's its host)
            names = {voice: sources.voice_name(voice, source_id or "") for voice, source_id in s["voices"]}
            linking = _linking(sources, ((v, i, v in s["roundups"]) for v, i in s["voices"]), s.get("sources", ()), saved)
            weight[s["key"]] = len(linking) - sum(1 for only, _ in linking if only) / 2
            last[s["key"]] = activity.get(s["key"], (None, 0))[0]
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
                "opened": activity.get(s["key"], (None, 0))[1],
            }
            kind = place_kind(s["key"], [a["url"] for a in suggestion["articles"]])
            if kind in REFERENCE_KINDS:   # help, docs, records and data (issue 0109): a quiet line
                references[s["key"]] = len(linking)
            if kind is None:
                out.append(suggestion)
        by_key = {s["key"]: s for s in out}
        for key, stories in started.references.items():
            references.setdefault(key, len({v for root in stories for v in root.voices}))
        for key, stories in started.suggest.items():
            names = {v: sources.voice_name(v, source_id) for root in stories for v, source_id in root.voices.items()}
            linkers[key].update(i for root in stories for i in root.voices.values() if i)
            pages = sorted({root.url for root in stories})
            suggestion = by_key.get(key)
            if suggestion is None:
                # Not linked enough to be suggested by links: its stories are its reason, held to the
                # same bar (2+ pages, 3+ voices), unless you hid it.
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
            s["score"] = round(score(origins=s["origins"], classics=s["classics"], opened=s["opened"],
                                     voices=weight[s["key"]], days=days), 3)
            s["days"] = days
            test = follow.get(s["key"])
            if test:
                s["follow_test"] = {"label": test["label"], "at": test["at"]}
            for a in s["articles"]:   # one title per page in the answer (issue 0106)
                a["title"] = title_of(a["url"])
        # One card per owner domain (issue 0109): its hosts its places, outside a domain of many owners.
        multi = Counter(owner_domain(s["key"]) for s in out)
        candidates = {site for site, n in multi.items() if site and n > 1}
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            spread = DiscoverRepository.site_hosts(cur, candidates)
        federations = set(sources.shared_sites) | {site for site, (hosts, posts) in spread.items()
                                                    if federation(hosts=hosts, posts=posts)}
        out = one_card_per_domain(out, federations=federations)
        for s in out:
            for place in s.get("places", ()):
                if place != s["key"]:
                    linkers[s["key"]] |= linkers.get(place, set())
            s.pop("days", None)
        out, also = self._other_channels(sources, out, linkers)
        # The most stories started there, classics, posts you opened, sources and the newest links first
        # (discover_rules.score): those tested followable first, then those their follow test can't follow
        # (headlines only, blocks readers) as a section of their own, then the untested (issue 0109).
        out = order(out)
        archives = [{
            "source_id": source_id, "name": sources.name.get(source_id, ""),
            "places": sorted({discover_place(root.url, platforms) for root in stories}),
            "origins": len(stories),
            "since": first_posts[source_id].isoformat() if source_id in first_posts else None,
            "older": sum(1 for root in stories if first_posts.get(source_id) and root.first_at < first_posts[source_id]),
            "origin_stories": [_story(root, title_of) for root in _first(stories)[:ORIGIN_STORIES_SHOWN]],
            "pages": sorted({root.url for root in stories}),
            "page_dates": {root.url: min(r.first_at for r in stories if r.url == root.url).isoformat() for root in stories},
        } for source_id, stories in started.missing.items() if len(stories) >= DISCOVER_MIN_ARTICLES]
        archives.sort(key=lambda a: (-a["origins"], a["name"].lower()))
        unnamed = sorted(({"place": place, "origins": len(stories)} for place, stories in started.unnamed.items()
                          if len(stories) >= DISCOVER_MIN_ARTICLES), key=lambda u: (-u["origins"], u["place"]))
        result = {"success": True, "suggestions": out, "also": also, "archives": archives, "unnamed": unnamed,
                  "references": [{"key": key, "voices": n} for key, n in sorted(references.items(), key=lambda kv: (-kv[1], kv[0]))],
                  "first_page": FIRST_PAGE}
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
        """(the suggestions, a followed source's other channels) (issue 0109 W3 A): a suggestion one of its
        linking sources holds a name of (discover_rules.own_names, same_owner) is that source's, shown as
        "also <source>'s" (`of`, `source_id`, the first such source by name), never as a suggestion.
        Aggregators and Saved own nothing they link (NOT_PUBLISHERS)."""
        names: Dict[str, Set[str]] = {}

        def of(source_id: str) -> Set[str]:
            if source_id not in names:
                kind = sources.kind.get(source_id)
                names[source_id] = set() if kind in NOT_PUBLISHERS or kind is None else own_names(
                    sources.name.get(source_id, ""), account="" if kind == "site" else sources.account.get(source_id) or "",
                    publication=sources.publication(source_id) if kind == "site" else "",
                    shared_sites=sources.shared_sites)
            return names[source_id]

        out, also = [], []
        for s in found:
            owners = sorted((sources.name.get(i, ""), i) for i in linkers.get(s["key"], ()) if same_owner(s["key"], of(i)))
            if owners:
                also.append({**s, "of": owners[0][0], "source_id": owners[0][1]})
            else:
                out.append(s)
        also.sort(key=lambda s: (-s["score"], s["key"]))
        return out, also

    @staticmethod
    def _title_map(cur: Any, sources: SourceFacts, counted: Dict[str, Any], started: Any,
                   read: Dict[str, Any]) -> Callable[[str], Optional[str]]:
        """One url -> title map for the whole answer (issue 0106): articles, the stories a suggestion started
        and the archive rows' lines title one page alike. A page that starts a story has the title its story
        page shows (its stored post's, or its origin's by the story's evidence, never its slug); else, as
        every page you don't follow (page_titles), the evidence of every post linking it (the articles' as
        counted; worked out here for the lines shown that no article titles); else the page's own title
        read once."""
        titles: Dict[str, Optional[str]] = {url: title for s in counted["found"] for url, _, title in s["articles"] if title}
        roots: Dict[str, Origin] = {}
        for stories in (*started.suggest.values(), *started.missing.values()):
            for root in _first(stories)[:ORIGIN_STORIES_SHOWN] + _first(stories, pages=True)[:DISCOVER_ARTICLES_SHOWN]:
                roots.setdefault(root.url, root)
        titles.update({url: _shown(root) for url, root in roots.items() if _shown(root)})
        found = page_titles.evidence(cur, sources, sorted(url for url in roots if not titles.get(url)))
        titles.update({url: title for url, title in found.items() if title})

        shared = page_titles.shared_titles(read)   # a host's name read off its pages (issue 0109)

        def title_of(url: str) -> Optional[str]:
            return titles.get(url) or page_titles.read(read, url, shared)
        return title_of

    @staticmethod
    def _held(cur: Any, sources: SourceFacts, roots: List[Origin], followed: Set[str],
              platforms: Optional[Dict[str, Tuple[str, ...]]] = None) -> Dict[str, str]:
        """The places your sources hold (discover_rules.discover_place -> a source): the platform
        accounts they follow, and on the sites you follow where stories start, the sections their
        own posts are in (the source with the most posts there)."""
        platforms = platforms or {}
        held = {account: source_id for source_id, account in sorted(sources.platform_accounts().items())}
        hosts = set()
        for root in roots:
            key, site, platform = discover_address(root.url, platforms)
            root.own = root.stored and sources.home_site(root.source_id) == site
            if key and not platform and site in followed and not root.own:
                hosts.add(host_of(root.url))
        posts: Counter = Counter()
        for source_id, url in DiscoverRepository.posts_on(cur, hosts):
            if site_of(host_of(url)) == sources.home_site(source_id):
                posts[(discover_place(url, platforms), source_id)] += 1
        for (place, source_id), _ in sorted(posts.items(), key=lambda item: (item[1], item[0][1])):
            held[place] = source_id   # the most posts last, so it stays
        return held

    def untitled_classics(self) -> List[str]:
        """The classics the stored data leaves untitled (issue 0106): Discover's reads read their page's title."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.news.untitled_classics(cur)

    def linked_articles(self, address: str) -> List[str]:
        """The articles on an address's host your sources linked (issue 0060): Follow ranks the
        site's findings by how many of them each holds. Read only."""
        host = host_of(normalize_url(address) or "")
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.repo.linked_articles(cur, host)

    def hide(self, key: str) -> Dict[str, Any]:
        """Not interested: the suggestion is never shown again."""
        key = (key or "").strip().lower()
        if not key or len(key) > 300:
            raise ValueError("key must be a suggestion's key")
        with db.transaction(self.db_url) as cur:
            self.repo.hide(cur, [key], "not_interested")
        return {"success": True, "key": key}


@lru_cache(maxsize=1)
def rules_stamp() -> str:
    """The rules stories are grouped by (issue 0071): a fingerprint of the stories, trees and News the
    job makes of the sample (utils/stamps.py), read as a run reads its rows (SourceFacts, _story_post).
    Any rule change that changes them (story_rules, tree_rules, news_rules, post_links, how a voice
    is told) changes it; a rename or a move doesn't."""
    sources = SourceFacts.of((s[:4] for s in stamps.SOURCES), stamps.HOSTS)
    posts = [StoriesService._story_post(row, sources) for row in stamps.posts()]
    found = grouping(posts)
    stories = found.stories
    names = surges(posts, {s[0]: s[4] for s in stamps.SOURCES})
    return stamps.fingerprint([stories, found.edges, {p.id: sorted(keys(p)) for p in posts}, names,
                               news(posts, stories, names)])


@lru_cache(maxsize=1)
def code_stamp() -> str:
    """The code Discover's kept list was made by (issue 0080 cold open): every module of insight_core, its
    tests aside. A list kept by other code (a deploy, a branch on a copy) is made again."""
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha1()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if relative.parts[0] != "tests":
            digest.update(str(relative).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()[:16]


def in_own_process(job: Callable[..., Any], *args: Any) -> None:
    """Run `job(*args)` in a fresh process and wait for it (issue 0072 A): what the job read goes
    back to the OS when the process ends. A long-lived process keeps it: glibc and Python reuse
    freed memory but seldom return it, so the API held 531-547 MB after its first start on a copy
    of the lab (41,637 posts; ~45 MB of it live) and 184 MB after a plain restart; with the job
    here, 45 MB after either. A child costs 0.4-0.9 s to start. One killed (out of memory) is
    logged; its open transaction is rolled back and its lock freed, so the next run recomputes.
    `job` is a module-level function (the child imports it by name). Never raises."""
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
    """The sources linking a suggestion, as "linked by N of your sources" names them (issue 0080): each
    voice once, sources of one name once (issue 0109), a Reddit source once for all its posts' authors, never Saved; each (whether it links it
    only in roundups, its name), those that link it in their own posts first (issue 0067).
    `voices`: (voice, the source naming it, only in roundups); `linkers`: (source, only in roundups), its
    Reddit sources read."""
    units: Dict[str, Tuple[bool, str]] = {}
    for voice, source_id, only in voices:
        if voice.startswith("reddit:") or (voice.startswith("source:") and voice[7:] in saved):
            continue
        was = units.get(voice, (True, ""))[0]
        units[voice] = (was and only, sources.voice_name(voice, source_id or ""))
    for source_id, only in linkers:
        if sources.kind.get(source_id) == "reddit":
            was = units.get("source:" + source_id, (True, ""))[0]
            units["source:" + source_id] = (was and only, sources.name.get(source_id, ""))
    # One owner named once (issue 0109 W10): sources of one name (a feed and its bridge, both "<handle>") are one.
    named: Dict[str, Tuple[bool, str]] = {}
    for unit, (only, name) in units.items():
        key = name.casefold() if name else unit
        was = named.get(key)
        named[key] = (was[0] and only, was[1]) if was else (only, name)
    return sorted(named.values())


def _archive_rows(rows: List[Dict[str, Any]], states: Dict[str, Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    """The archive rows as shown (issue 0109 W8), each by its source's archive as stored now: the pages its
    stories started at that the source doesn't store (`origins`, pages, not stories; `stored`: those it has
    stored since, whose stories join at the next story run), a row with none left gone; `stopped`: its newest
    post, when it is STOPPED_DAYS old (an archive can't reach what the feed never had: 0108's moved blog);
    `watches`: the page-watch prefix it reads and the sections of the missing pages outside it; `archivable`:
    the missing pages an archive can reach (none when the feed stopped, those under the prefix)."""
    out = []
    for a in rows:
        state = dict(states.get(a["source_id"], {"state": None, "found": 0}))
        stored = set(state.pop("stored_urls", ()))
        newest, prefix = state.pop("newest", None), _prefix(state.pop("prefix", None))
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
        under = [url for url in missing if not prefix or _url_path(url).startswith(prefix)]
        if prefix and len(under) < len(missing):
            row["watches"] = {"prefix": prefix, "not": sorted({"/" + _url_path(url).strip("/").split("/")[0]
                                                               for url in missing if url not in under})}
        row["archivable"] = 0 if stopped else len(under)
        out.append(row)
    out.sort(key=lambda a: (-a["origins"], a["name"].lower()))
    return out


def _prefix(value: Optional[str]) -> Optional[str]:
    """A page-watch prefix as /a/b/ (page_watch.normalise_prefix's form), None when there is none."""
    if not value or not str(value).strip("/"):
        return None
    return "/" + str(value).strip("/") + "/"


def _url_path(url: str) -> str:
    _, _, rest = url.split("://", 1)[-1].partition("/")
    return "/" + rest.split("?", 1)[0].split("#", 1)[0]


def _shown(root: Origin) -> Optional[str]:
    """A story origin's title as Discover shows it: never its address's slug (issue 0080)."""
    return root.title if root.stored or root.title != slug_title(root.url) else None


def _story(root: Origin, title_of: Callable[[str], Optional[str]]) -> Dict[str, Any]:
    """A story a place started, as Discover lists it, titled by the answer's one map (issue 0106)."""
    return {"url": root.url, "title": title_of(root.url), "voices": len(root.voices), "stored": root.stored}


def _platforms(kept: Optional[Dict[str, Any]]) -> Dict[str, Tuple[str, ...]]:
    """The data's platforms Discover's kept counts were keyed by (issue 0080)."""
    return {host: tuple(prefix) for host, prefix in ((kept or {}).get("platforms") or {}).items()}


def _words(s: Dict[str, Any]) -> str:
    """What Discover's search box matches: the key, the sources linking it, its articles' and stories' titles."""
    parts = [s["key"], *s["voice_names"], *(f"{a['title'] or ''} {a['url']}" for a in s["articles"]),
             *(f"{o['title'] or ''} {o['url']}" for o in s.get("origin_stories", ()))]
    return " ".join(parts).casefold()



if __name__ == "__main__":   # a hand-run full rebuild: python -m insight_core.services.stories_service full
    import os
    if sys.argv[1:] != ["full"]:
        sys.exit("usage: python -m insight_core.services.stories_service full")
    in_own_process(recompute_job, os.environ["DATABASE_URL"], True)
