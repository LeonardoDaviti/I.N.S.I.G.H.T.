"""One story, many sources (issue 0050): the story job and Discover.

The story job runs after each fetch run that saved posts (IngestionRunner's `stories` port) and
once when the backend starts (main.py, in the background):
1. it reads the links of every post never read (the posts stored before 0050), 500 a transaction;
2. it marks each source's signature links and links to its own site as boilerplate;
3. it groups the posts of the last 30 days (STORY_WINDOW) into stories and writes what changed.
   A story that began before the window is frozen. The first run (no `stories` setting yet)
   groups every post.
It is deterministic and idempotent: a second run over the same posts writes nothing. One job at a
time (an advisory lock); a job that finds one running skips. No AI, no fetch.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from insight_core.db import database as db
from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.utils.post_links import reddit_author
from insight_core.utils.story_rules import StoryPost, group, suggestions

logger = logging.getLogger(__name__)

STORY_WINDOW = timedelta(days=30)
SETTINGS_KEY = "stories"
LOCK_KEY = "insight.stories"
DISCOVER_ARTICLES_SHOWN = 20
_TAGS = re.compile(r"<[^>]+>")


def _voice_name(voice: str, sources: SourceFacts, source_id: str) -> str:
    return "u/" + voice.split(":", 1)[1] if voice.startswith("reddit:") else sources.name.get(source_id, "")


class StoriesService:
    def __init__(self, db_url: str, *, repo: StoriesRepository | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db_url = db_url
        self.repo = repo or StoriesRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---- the job ------------------------------------------------------------------------

    def fill_links(self) -> int:
        """Read the links of every post never read, a batch a transaction. Returns how many."""
        filled = 0
        while True:
            with db.transaction(self.db_url) as cur:
                batch = self.repo.fill_missing_links(cur)
            filled += batch
            if not batch:
                return filled

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
            full = full or settings is None
            summary = {"computed_at": now.isoformat(), "full": full, "links_filled": filled,
                       **self.regroup(cur, cutoff=None if full else now - STORY_WINDOW),
                       "seconds": round(time.monotonic() - started, 2)}
            previous = (settings or ({}, None))[0] or {}
            SystemSettingsRepository.upsert(cur, SETTINGS_KEY, {
                **summary, "full_at": now.isoformat() if full else previous.get("full_at"),
            })
        return summary

    def regroup(self, cur: Any, *, cutoff: Optional[datetime]) -> Dict[str, int]:
        """Steps 2 and 3 on the caller's transaction: the stories of the posts since `cutoff`
        (every post when None). Returns what it counted and how many rows changed."""
        sources = SourceFacts(cur)
        boilerplate = self.repo.mark_boilerplate(cur, sources)
        posts = [self._story_post(row, sources) for row in self.repo.load_posts(cur, sources, cutoff)]
        stories = group(posts)
        changed = self.repo.write_stories(cur, stories, post_ids=[p.id for p in posts], cutoff=cutoff)
        return {"posts": len(posts), "stories": len(stories), "changed": changed, "boilerplate_changed": boilerplate}

    @staticmethod
    def _story_post(row: Dict[str, Any], sources: SourceFacts) -> StoryPost:
        kind = sources.kind.get(row["source_id"], "site")
        html = row["html"]
        return StoryPost(
            id=row["id"], source_id=row["source_id"], kind=kind, own_site=sources.own_site(row["source_id"]),
            t=row["t"], title=row["title"], content_hash=row["content_hash"], text_chars=row["text_chars"],
            words=len(_TAGS.sub("", html or "").split()) if kind in ("reddit", "hn") else None,
            author=reddit_author(html) if kind == "reddit" else None,
            url=row["url"], links=row["links"],
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

    def discover(self) -> Dict[str, Any]:
        """Sites and accounts your sources keep linking that you don't follow, each with why."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            sources = SourceFacts(cur)
            links = self.repo.kept_links(cur, sources)
            hidden = self.repo.hidden(cur)
        pairs = []
        names: Dict[str, str] = {}
        linked_by: Dict[str, set] = defaultdict(set)
        texts: Dict[str, Counter] = defaultdict(Counter)
        for link in links:
            post = StoryPost(id="", source_id=link["source_id"], kind=sources.kind.get(link["source_id"], "site"),
                             own_site=sources.own_site(link["source_id"]), t=datetime.min, author=link["author"])
            names.setdefault(post.voice, _voice_name(post.voice, sources, link["source_id"]))
            pairs.append((post.voice, link["url"]))
            linked_by[link["url"]].add(post.voice)
            if link["text"]:
                texts[link["url"]][link["text"]] += 1
        found = suggestions(pairs, followed=sources.followed(), hidden=hidden)
        out = []
        for s in found:
            articles = sorted(s.articles, key=lambda url: (-len(linked_by[url]), url))[:DISCOVER_ARTICLES_SHOWN]
            out.append({
                "key": s.key,
                "url": "https://" + s.key,
                "voices": len(s.voices),
                "voice_names": sorted(names[v] for v in s.voices),
                "article_count": len(s.articles),
                "link_count": s.links,
                "articles": [{
                    "url": url,
                    "title": texts[url].most_common(1)[0][0] if texts[url] else None,
                    "linked_by": sorted(names[v] for v in linked_by[url]),
                } for url in articles],
            })
        return {"success": True, "suggestions": out}

    def hide(self, key: str) -> Dict[str, Any]:
        """Not interested: the suggestion is never shown again."""
        key = (key or "").strip().lower()
        if not key or len(key) > 300:
            raise ValueError("key must be a suggestion's key")
        with db.transaction(self.db_url) as cur:
            self.repo.hide(cur, [key], "not_interested")
        return {"success": True, "key": key}
