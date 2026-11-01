"""News and Classics (issue 0051): what many of your sources cover now, and what they keep citing.

Both are measured from your own sources, with no AI and no reading history:
- **News:** several independent sources cover the same thing within days. The story job finds the
  names surging in titles (over the last 32 days of titles) and joins 0050's stories by them, for
  News only, then scores each story (utils/news_rules.py). GET /api/news reads the stories whose
  first post is in the last 7 days.
- **Classics:** your sources keep linking the same page over months. The story job aggregates the
  kept post links into `classics`; GET /api/classics reads them, cited again this week first.
- **Background:** a post that links a classic says so (at most 2, in the post's detail).
- **Discover** counts each suggestion's classics (StoriesService.discover).

The job part (`refresh`) runs inside the story job's transaction (StoriesService.regroup). The
Main feed is never reordered: News and Classics are views next to it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from insight_core.db import database as db
from insight_core.db.repo_news import NewsRepository
from insight_core.db.repo_reader import FeedScope, ReaderRepository
from insight_core.db.repo_stories import SourceFacts
from insight_core.utils.classic_rules import Citation, cited_again, classic_order, classics
from insight_core.utils.news_rules import NAME_TITLES, NEWS_DAYS, NEWS_RECENT, lead, news, surges
from insight_core.utils.addresses import x_account
from insight_core.utils.post_fields import display_title
from insight_core.utils.post_links import reddit_author
from insight_core.utils.url_normalization import normalize_url
from insight_core.utils.story_rules import Story, StoryPost

PARTS = ("recent", "earlier")    # "Last 48 hours", "Earlier this week"


class NewsService:
    def __init__(self, db_url: str, *, repo: NewsRepository | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db_url = db_url
        self.repo = repo or NewsRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---- the job ------------------------------------------------------------------------

    def refresh(self, cur: Any, *, posts: Sequence[StoryPost], stories: Sequence[Story], sources: SourceFacts,
                full: bool) -> Dict[str, Any]:
        """News over the job's posts (`posts`, grouped into `stories`) and every classic, on the
        caller's transaction. Returns what it counted and how many rows changed."""
        since = None if full else self.clock() - NAME_TITLES
        titled = [
            StoryPost(id=row["id"], source_id=row["source_id"], kind=sources.kind.get(row["source_id"], "site"),
                      own_site=sources.publication(row["source_id"]), t=row["t"], title=row["title"])
            for row in self.repo.load_titles(cur, since)
        ]
        found = surges(titled, self.repo.followed_since(cur))
        stories_now = news(posts, stories, found)
        news_changed = self.repo.write_news(cur, stories_now)
        found_classics = classics(*self._citations(cur, sources))
        classics_changed = self.repo.write_classics(cur, found_classics)
        return {"names": len(found), "news": len(stories_now), "news_changed": news_changed,
                "classics": len(found_classics), "classics_changed": classics_changed}

    def _citations(self, cur: Any, sources: SourceFacts):
        rows = self.repo.citations(cur, reddit=sources.of_kind("reddit"), saved=sources.of_kind("saved"))
        authors: Dict[str, Optional[str]] = {}
        out = []
        for row in rows:
            if row["post_id"] not in authors:
                authors[row["post_id"]] = reddit_author(row["html"]) if row["html"] else None
            voice = self._voice(sources, row["source_id"], authors[row["post_id"]])
            out.append(Citation(voice=voice, name=sources.voice_name(voice, row["source_id"]),
                                source_id=row["source_id"], t=row["t"], target=row["target"], stored=row["stored"],
                                text=row["text"]))
        stored = {}
        for row in self.repo.stored_posts(cur, sorted({c.stored for c in out if c.stored})):
            stored[row["id"]] = (self._voice(sources, row["source_id"], None), row["t"],
                                 display_title(row["title"], row["content"]))
        return out, stored

    @staticmethod
    def _voice(sources: SourceFacts, source_id: str, author: Optional[str]) -> str:
        return StoryPost(id="", source_id=source_id, kind=sources.kind.get(source_id, "site"),
                         own_site=sources.publication(source_id), t=datetime.min, author=author).voice

    # ---- News ---------------------------------------------------------------------------

    def news(self, scope: str | None = None) -> Dict[str, Any]:
        """The News of a scope (the Main feed or a track): the stories with 2+ voices begun in the
        last NEWS_DAYS, with a post from the scope's sources (the score counts every source), in
        two parts ("recent": the last 48 hours; "earlier"), each by score, then the newest.
        Each item is its story's lead as a feed row, with `story` (who covered it, its other
        posts) and `news` {part, reports, shares, mentions, score}."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.news_on(cur, scope)

    def news_on(self, cur: Any, scope: str | None = None) -> Dict[str, Any]:
        """`news` on the caller's cursor."""
        feed_scope = FeedScope.parse(scope)
        now = self.clock()
        rows = self.repo.news_posts(cur, feed_scope, now - timedelta(days=NEWS_DAYS))
        followed = ReaderRepository.followed_accounts(cur) if any(row["repost"] for row in rows) else {}
        by_story: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_story[row["_news"]].append(row)
        items = []
        for posts in by_story.values():
            shown = [p for p in posts if p["_in_scope"]]
            # The lead is the origin (issue 0064): a post its 0050 story's tree starts from.
            origins = [p["id"] for p in posts if p["_origin"]]
            lead_id = lead([(p["id"], p["role"]) for p in shown], origins) or lead([(p["id"], p["role"]) for p in posts], origins)
            first_report = lead([(p["id"], p["role"]) for p in posts], origins)
            head = next(p for p in posts if p["id"] == lead_id)
            covered = sorted(posts, key=lambda p: p["id"] != first_report)   # stable: time order after
            sources: List[Dict[str, str]] = []
            # Every voice the count holds is named (issue 0069): your sources that wrote or reposted a
            # tweet a post holds are voices too, as on the feed row (issue 0068).
            for p in covered:
                accounts = [p["repost"]["author"] or "", *p["repost"]["by"]] if p["repost"] else []
                held = [followed[x_account(a)] for a in accounts if x_account(a) in followed]
                for source in [{"id": p["source_id"], "name": p["source_display_name"]}, *held]:
                    if not any(s["id"] == source["id"] for s in sources):
                        sources.append(source)
            item = {k: v for k, v in head.items() if not k.startswith("_") and k != "role"}
            # A post that only quotes a post of the story is no line (issue 0072): it was read there.
            addresses = {normalize_url(p["url"]) for p in posts} - {None}
            item["story"] = {
                "id": head["_news"], "voices": head["_voices"], "sources": sources,
                "posts": [{
                    "id": p["id"], "title": p["title"], "url": p["url"], "source_id": p["source_id"],
                    "source_display_name": p["source_display_name"], "platform": p["platform"],
                    "sort_at": p["sort_at"], "published_at": p["published_at"], "read_at": p["read_at"],
                    "role": p["role"], "repost": p["repost"],   # issue 0070: its line names the author
                    "reposted_by": (p["repost"] or {}).get("by") or None,   # issue 0068
                } for p in posts if p["id"] != lead_id and p["_quotes"] not in addresses],
            }
            item["news"] = {
                "part": "recent" if head["_first_at"] >= now - NEWS_RECENT else "earlier",
                "first_at": head["_first_at"], "reports": head["_reports"], "shares": head["_shares"],
                "mentions": head["_mentions"], "score": head["_score"],
            }
            items.append(item)
        items.sort(key=lambda i: (PARTS.index(i["news"]["part"]), -i["news"]["score"],
                                  -i["news"]["first_at"].timestamp(), i["id"]))
        return {"success": True, "items": items, "next_cursor": None}

    # ---- Classics -----------------------------------------------------------------------

    def classics(self, scope: str | None = None) -> Dict[str, Any]:
        """The classics a source of the scope cited and you did not hide: cited again this week
        first (`cited_again`), then most voices, then cited longest. Each {url, post_id (the stored
        post, when it is one), title, voices, days, first_at, last_at, cited_again, citers [{name,
        at}] (each voice once, first citation first), read_at, later_at}."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return self.classics_on(cur, scope)

    def classics_on(self, cur: Any, scope: str | None = None) -> Dict[str, Any]:
        """`classics` on the caller's cursor."""
        feed_scope = FeedScope.parse(scope)
        now = self.clock()
        rows = self.repo.classics(cur, feed_scope)
        out = []
        for row in sorted(rows, key=lambda r: classic_order(r["last_at"], r["voices"], r["days"], r["url"], now)):
            title = display_title(row["post_title"], row["content"]) if row["post_id"] else row["title"]
            out.append({
                "url": row["url"], "post_id": row["post_id"], "title": title or None, "voices": row["voices"],
                "days": row["days"], "first_at": row["first_at"], "last_at": row["last_at"],
                "cited_again": cited_again(row["last_at"], now),
                "citers": [{"name": c["name"], "at": c["at"]} for c in row["citers"]],
                "read_at": row["read_at"], "later_at": row["later_at"],
            })
        return {"success": True, "classics": out}

    def hide(self, url: str) -> Dict[str, Any]:
        """Hide a classic ("I know it", "not for me"): it never comes back."""
        url = (url or "").strip()
        if not url or len(url) > 2000:
            raise ValueError("url must be a classic's address")
        with db.transaction(self.db_url) as cur:
            self.repo.hide_classic(cur, url)
        return {"success": True, "url": url}

    def background(self, cur: Any, post_id: str) -> List[Dict[str, Any]]:
        """The classics a post links, on the caller's cursor: [{url, post_id, title, voices}]."""
        return [{
            "url": row["url"], "post_id": row["post_id"], "voices": row["voices"],
            "title": (display_title(row["post_title"], row["content"]) if row["post_id"] else row["title"]) or None,
        } for row in self.repo.background(cur, post_id)]

    def classic_urls(self, cur: Any) -> List[str]:
        return self.repo.classic_urls(cur)
