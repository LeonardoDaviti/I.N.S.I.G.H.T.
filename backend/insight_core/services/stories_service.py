"""One story, many sources (issue 0050): the story job and Discover.

The story job runs after each fetch run that saved posts (IngestionRunner's `stories` port) and
once when the backend starts (main.py, in the background):
1. it reads the links of every post never read (the posts stored before 0050), 500 a transaction;
2. it marks each source's signature links and links to its own site as boilerplate;
3. it groups the posts of the last 30 days (STORY_WINDOW) into stories and writes what changed.
   A story that began before the window is frozen. The first run (no `stories` setting yet)
   groups every post, and so does a run whose rules differ from the setting's (`rules_stamp`,
   issue 0069: a rule change reaches the frozen stories too; issue 0071: the stamp is derived).
4. it refreshes News (the names surging in titles join stories, for News only) and Classics
   (issue 0051, services/news_service.py), on the same transaction.
It is deterministic and idempotent: a second run over the same posts writes nothing. One job at a
time (an advisory lock); a job that finds one running skips. No AI, no fetch.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.services.news_service import NewsService
from insight_core.utils import stamps
from insight_core.utils.news_rules import news, surges
from insight_core.utils.post_fields import REPLY_TO_RE
from insight_core.utils.post_links import host_of, quoted_tweet, quoted_words, reddit_author, site_of
from insight_core.utils.story_rules import (DISCOVER_MIN_ARTICLES, DISCOVER_MIN_VOICES, DISCOVER_PLATFORMS,
                                           Origin, StoryPost, discover_address, discover_open, discover_place, group,
                                           origin_title, origins)
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger(__name__)

STORY_WINDOW = timedelta(days=30)
SETTINGS_KEY = "stories"
LOCK_KEY = "insight.stories"
DISCOVER_ARTICLES_SHOWN = 20
ORIGIN_STORIES_SHOWN = 3      # the stories a suggestion started, shown on its card (issue 0065)
_TAGS = re.compile(r"<[^>]+>")


class StoriesService:
    def __init__(self, db_url: str, *, repo: StoriesRepository | None = None,
                 clock: Callable[[], datetime] | None = None, news: NewsService | None = None):
        self.db_url = db_url
        self.repo = repo or StoriesRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # News and Classics (issue 0051) are refreshed by this job, on its transaction.
        self.news = news or NewsService(db_url, clock=self.clock)
        # Discover counts every kept link in the database (138k on the server's data), and its inputs change only
        # with a story run, a source or a hidden suggestion: the last list is kept until they do.
        self._discovered: tuple = ("", None)

    # ---- the job ------------------------------------------------------------------------

    def fill_links(self) -> int:
        """Read the links of every post never read, a batch a transaction, until none is left
        (issue 0069: the search refill may hold some for a moment). Returns how many."""
        return db.fill_until_done(self.db_url, self.repo.fill_missing_links, self.repo.missing_links)

    def recompute(self, *, full: bool = False) -> Dict[str, Any]:
        """The story job. `full` regroups every post (the first run always does). Returns a summary."""
        started = time.monotonic()
        filled = self.fill_links()
        with db.transaction(self.db_url) as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
            if not cur.fetchone()[0]:
                return {"skipped": True, "links_filled": filled}
            now = self.clock()
            settings = SystemSettingsRepository.get(cur, SETTINGS_KEY)
            previous = (settings or ({}, None))[0] or {}
            # Stories grouped by other rules are all regrouped, the frozen ones too (issue 0069).
            full = full or settings is None or previous.get("rules") != rules_stamp()
            summary = {"computed_at": now.isoformat(), "full": full, "links_filled": filled,
                       **self.regroup(cur, cutoff=None if full else now - STORY_WINDOW),
                       "seconds": round(time.monotonic() - started, 2)}
            SystemSettingsRepository.upsert(cur, SETTINGS_KEY, {
                **summary, "rules": rules_stamp(), "full_at": now.isoformat() if full else previous.get("full_at"),
            })
        self.fill_discover_addresses()
        return summary

    def regroup(self, cur: Any, *, cutoff: Optional[datetime]) -> Dict[str, int]:
        """Steps 2 and 3 on the caller's transaction: the stories of the posts since `cutoff`
        (every post when None). Returns what it counted and how many rows changed."""
        sources = SourceFacts(cur)
        boilerplate = self.repo.mark_boilerplate(cur, sources)
        posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources, cutoff)]
        stories = group(posts)
        changed = self.repo.write_stories(cur, stories, post_ids=[p.id for p in posts], cutoff=cutoff)
        news = self.news.refresh(cur, posts=posts, stories=stories, sources=sources, full=cutoff is None)
        return {"posts": len(posts), "stories": len(stories), "changed": changed, "boilerplate_changed": boilerplate,
                **news}

    @staticmethod
    def _story_post(row: Dict[str, Any], sources: SourceFacts) -> StoryPost:
        kind = sources.kind.get(row["source_id"], "site")
        html = row["html"]
        reply = REPLY_TO_RE.match(row["title"] or "") if kind == "x" else None
        author_source = sources.of_account.get("x.com/" + row["author"].lower()) if kind == "x" and row["author"] else None
        return StoryPost(
            id=row["id"], source_id=row["source_id"], kind=kind, own_site=sources.publication(row["source_id"]),
            t=row["t"], title=row["title"], content_hash=row["content_hash"], text_chars=row["text_chars"],
            words=len(_TAGS.sub("", html or "").split()) if kind in ("reddit", "hn") else None,
            author=reddit_author(html) if kind == "reddit" else row["author"],
            url=row["url"], links=row["links"],
            # The tree's evidence (issue 0064): link words, a page updated since its date, its own site.
            link_texts=row["link_texts"], updated=row["updated"], home_site=sources.home_site(row["source_id"]),
            # On X (issue 0066): a tweet of another account (a repost), the account a reply answers, a quote.
            reposted=kind == "x" and bool(row["author"])
            and sources.account.get(row["source_id"]) != "x.com/" + row["author"].lower(),
            reply_to=reply.group(1) if reply else None,
            quoted=quoted_tweet(html) if kind == "x" else None,
            quoted_words=quoted_words(html),   # the words of the pages it quotes (issue 0070)
            # Who else of your sources put it before you (issue 0068): its author's own source, when
            # another source holds it, and the sources that reposted it. Voices of its story.
            reposters=tuple(sorted({sources.of_account.get("x.com/" + by.lower()) for by in row["reposted_by"]}
                                   - {None, row["source_id"], author_source})),
            author_source=author_source if author_source != row["source_id"] else None,
        )

    def recompute_safely(self) -> Optional[Dict[str, Any]]:
        """The job, logged and never raising (after a fetch run, at start)."""
        try:
            summary = self.recompute()
            logger.info("Stories: %s", summary)
            return summary
        except Exception:  # noqa: BLE001 - stories are derived; the next run recomputes them
            logger.exception("Stories: the story job failed")
            return None

    # ---- Discover -----------------------------------------------------------------------

    def fill_discover_addresses(self) -> int:
        """After a story run: work out the addresses its links point to, and its platform posts are
        at, that Discover has not met (issue 0062), and count and keep Discover's counts (issue 0067),
        so Discover's first open after the run needn't. Never raises: Discover does both itself
        when they are missing."""
        try:
            with db.transaction(self.db_url) as cur:
                sources = SourceFacts(cur)
                filled = DiscoverRepository.fill_addresses(cur, sources.platform_accounts())
                self._counted(cur, sources)
                return filled
        except Exception:  # noqa: BLE001 - derived; Discover fills what is missing
            logger.exception("Stories: Discover's addresses were not filled")
            return 0

    @staticmethod
    def _counted(cur: Any, sources: SourceFacts) -> Dict[str, Any]:
        """Discover's counts by links (issue 0062), grouped and counted in the database: the kept ones
        when what they are counted from is unchanged (issue 0067: the story job keeps them), else
        counted now and kept. {stamp, found (DiscoverRepository.counts), mirrors, scanned_to}."""
        accounts = sources.platform_accounts()
        ask = dict(kinds=sources.kind, own_sites={i: sources.publication(i) for i in sources.kind}, accounts=accounts,
                   shown=DISCOVER_ARTICLES_SHOWN)
        stamp = DiscoverRepository.stamp(cur, sorted((i, sources.kind[i], ask["own_sites"][i], accounts.get(i, ""))
                                                     for i in sources.site))
        kept = DiscoverRepository.kept(cur)
        if kept and kept["stamp"] == stamp:
            return kept
        mirrors, scanned_to = DiscoverRepository.mirrors(cur, kept)
        found, unknown = DiscoverRepository.counts(cur, mirrors=mirrors, **ask)
        if unknown:   # addresses no story run has worked out yet (the job does it after reading links)
            DiscoverRepository.fill_addresses(cur, accounts)
            found, _ = DiscoverRepository.counts(cur, mirrors=mirrors, **ask)
        StoriesService._title_articles(cur, sources, found)
        kept = {"stamp": stamp, "found": found, "mirrors": mirrors, "scanned_to": scanned_to}
        DiscoverRepository.keep(cur, kept)
        return kept

    @staticmethod
    def _title_articles(cur: Any, sources: SourceFacts, found: List[Dict[str, Any]]) -> None:
        """Each shown article's title (issue 0070): a stored post's own, as the reader shows it, else
        by the evidence a story's outside origin is titled by (origin_title), from every post linking it."""
        urls = sorted({url for s in found for url, _ in s["articles"]})
        linking: Dict[str, Dict[str, StoryPost]] = defaultdict(dict)
        for row in StoriesRepository.load_posts(cur, sources, None, linking=urls):
            post = StoriesService._story_post(row, sources)
            for target, _ in post.links:
                linking[target][post.id] = post
        stored = DiscoverRepository.stored_titles(cur, urls)
        for s in found:
            s["articles"] = [(url, voices, stored.get(url) or origin_title(url, list(linking[url].values())))
                             for url, voices in s["articles"]]

    def discover(self) -> Dict[str, Any]:
        """Sites and accounts your sources keep linking that you don't follow, each with why; the
        ones your stories start from first (issue 0065), with the sources you follow that miss them."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            inputs = self.repo.discover_inputs(cur)
            if self._discovered[0] == inputs and self._discovered[1] is not None:
                return self._discovered[1]
            # Grouped and counted in the database (issue 0062): the kept links never come to Python.
            sources = SourceFacts(cur)
            counted = self._counted(cur, sources)
            followed, hidden, classics = sources.followed(), self.repo.hidden(cur), set(self.news.classic_urls(cur))
            roots = DiscoverRepository.story_origins(cur, kinds=sources.kind,
                                                     own_sites={i: sources.publication(i) for i in sources.kind})
            held = self._held(cur, sources, roots, followed)
            started = origins(roots, followed=followed, held=held, mirrors=set(counted["mirrors"]))
            first_posts = DiscoverRepository.first_posts(cur, started.missing)
        out, weight = [], {}
        for s in counted["found"]:
            if not discover_open(s["key"], site_of(s["key"]), "/" in s["key"], followed=followed, hidden=hidden,
                                 followed_accounts=sources.followed_accounts()):
                continue   # followed or hidden (a platform's key is its account, x.com/karpathy; a site's its host)
            names = {voice: sources.voice_name(voice, source_id or "") for voice, source_id in s["voices"]}
            roundups = set(s["roundups"])
            weight[s["key"]] = len(names) - len(roundups) / 2
            out.append({
                "key": s["key"],
                "url": "https://" + s["key"],
                "voices": len(names),
                # those that link it in their own posts first, then those that list it in roundups
                "voice_names": [name for _, name in sorted((v in roundups, name) for v, name in names.items())],
                "article_count": s["article_count"],
                "link_count": s["link_count"],
                "classics": len(classics.intersection(s["classics"])),
                "articles": [{"url": url, "title": title, "linked_by": sorted(names[v] for v in voices)}
                             for url, voices, title in s["articles"]],
                "origins": 0,
            })
        by_key = {s["key"]: s for s in out}
        for key, stories in started.suggest.items():
            names = {v: sources.voice_name(v, source_id) for root in stories for v, source_id in root.voices.items()}
            pages = sorted({root.url for root in stories})
            suggestion = by_key.get(key)
            if suggestion is None:
                # Not linked enough to be suggested by links: its stories are its reason, held to the
                # same bar (2+ pages, 3+ voices), unless you hid it.
                site = key.split("/", 1)[0]
                if (len(pages) < DISCOVER_MIN_ARTICLES or len(names) < DISCOVER_MIN_VOICES
                        or key.lower() in hidden or site in hidden or site_of(site) in hidden):
                    continue
                suggestion = by_key[key] = {
                    "key": key, "url": "https://" + key, "voices": len(names), "voice_names": sorted(names.values()),
                    "article_count": len(pages), "link_count": len(pages), "classics": 0,
                    "articles": [{"url": root.url, "title": root.title,
                                  "linked_by": sorted(names[v] for v in root.voices)}
                                 for root in _first(stories, pages=True)[:DISCOVER_ARTICLES_SHOWN]],
                }
                out.append(suggestion)
                weight[key] = len(names)
            suggestion["origins"] = len(stories)
            suggestion["origin_stories"] = [_story(root) for root in _first(stories)[:ORIGIN_STORIES_SHOWN]]
            host = key.split("/", 1)[0]
            if site_of(host) in followed and site_of(host) not in DISCOVER_PLATFORMS:
                # a section of a site you follow: the places of it your sources hold
                suggestion["follows"] = sorted({p for p in held if p.split("/", 1)[0] == host} - {key})
        # The stories you read that start there first (issue 0065), then a suggestion that holds
        # classics (issue 0051), then most voices, one linking it only in roundups counting half
        # (issue 0067), then all voices, articles, links, key (story_rules.suggestions).
        out.sort(key=lambda s: (-s["origins"], s["classics"] == 0, -weight[s["key"]], -s["voices"],
                                -s["article_count"], -s["link_count"], s["key"]))
        archives = [{
            "source_id": source_id, "name": sources.name.get(source_id, ""),
            "places": sorted({discover_place(root.url) for root in stories}),
            "origins": len(stories),
            "since": first_posts[source_id].isoformat() if source_id in first_posts else None,
            "older": sum(1 for root in stories if first_posts.get(source_id) and root.first_at < first_posts[source_id]),
            "origin_stories": [_story(root) for root in _first(stories)[:ORIGIN_STORIES_SHOWN]],
        } for source_id, stories in started.missing.items() if len(stories) >= DISCOVER_MIN_ARTICLES]
        archives.sort(key=lambda a: (-a["origins"], a["name"].lower()))
        unnamed = sorted(({"place": place, "origins": len(stories)} for place, stories in started.unnamed.items()
                          if len(stories) >= DISCOVER_MIN_ARTICLES), key=lambda u: (-u["origins"], u["place"]))
        result = {"success": True, "suggestions": out, "archives": archives, "unnamed": unnamed}
        self._discovered = (inputs, result)
        return result

    @staticmethod
    def _held(cur: Any, sources: SourceFacts, roots: List[Origin], followed: Set[str]) -> Dict[str, str]:
        """The places your sources hold (story_rules.discover_place -> a source): the platform
        accounts they follow, and on the sites you follow where stories start, the sections their
        own posts are in (the source with the most posts there)."""
        held = {account: source_id for source_id, account in sorted(sources.platform_accounts().items())}
        hosts = set()
        for root in roots:
            key, site, platform = discover_address(root.url)
            root.own = root.stored and sources.home_site(root.source_id) == site
            if key and not platform and site in followed and not root.own:
                hosts.add(host_of(root.url))
        posts: Counter = Counter()
        for source_id, url in DiscoverRepository.posts_on(cur, hosts):
            if site_of(host_of(url)) == sources.home_site(source_id):
                posts[(discover_place(url), source_id)] += 1
        for (place, source_id), _ in sorted(posts.items(), key=lambda item: (item[1], item[0][1])):
            held[place] = source_id   # the most posts last, so it stays
        return held

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
    Any rule change that changes them (story_rules, news_rules, post_links, how a voice is told)
    changes it; a rename or a move doesn't."""
    sources = SourceFacts.of((s[:4] for s in stamps.SOURCES), stamps.HOSTS)
    posts = [StoriesService._story_post(row, sources) for row in stamps.posts()]
    stories = group(posts)
    found = surges(posts, {s[0]: s[4] for s in stamps.SOURCES})
    return stamps.fingerprint([stories, found, news(posts, stories, found)])


def _first(stories: List[Origin], *, pages: bool = False) -> List[Origin]:
    """A place's stories, the most voices first, then the newest; with `pages`, one per page."""
    ordered = sorted(stories, key=lambda root: (-len(root.voices), -root.first_at.timestamp(), root.url))
    if not pages:
        return ordered
    once: Dict[str, Origin] = {}
    for root in ordered:
        once.setdefault(root.url, root)
    return list(once.values())


def _story(root: Origin) -> Dict[str, Any]:
    return {"url": root.url, "title": root.title, "voices": len(root.voices), "stored": root.stored}

