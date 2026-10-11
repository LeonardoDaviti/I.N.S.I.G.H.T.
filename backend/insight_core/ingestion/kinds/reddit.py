"""reddit_subreddit: a subreddit given as a bare r/<sub> handle (or a non-feed /r/ URL).

Live fetch reads /r/<sub>/new/.rss through the generic feed parser: the unauthenticated
JSON API answers 403 on every cycle regardless of User-Agent (measured 2026-08-14), while
the .rss endpoint answers 200. The archive still pages the JSON listing, best-effort; its
failures surface as archive errors. The 8s spacing is a host floor (gates.HOST_FLOORS:
reddit.com and platform:reddit), so it also covers the generic_rss .rss reddit feeds.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    RateLimit,
    Source,
    resume_counts,
)

REDDIT_BASE_URL = "https://www.reddit.com"
REDDIT_HOSTS = frozenset({"www.reddit.com", "reddit.com", "old.reddit.com"})

REDDIT_PROFILE = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=2)

_POST_URL_PREFIXES = ("https://reddit.com", "https://www.reddit.com", "http://reddit.com", "http://www.reddit.com")


def subreddit_name(source_handle: str) -> str:
    if "reddit.com" in source_handle:
        segments = parsing.path_segments(source_handle)
        if len(segments) >= 2 and segments[0] == "r":
            return segments[1]
    return source_handle.replace("r/", "").strip("/")


class RedditKind(BaseKind):
    name = "reddit_subreddit"
    available_basis = "listing_cap"
    profile = REDDIT_PROFILE

    def __init__(self, http: KindHttp) -> None:
        self.http = http

    def matches(self, source: Source) -> bool:
        if source.get("platform") == "reddit":
            return True
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        if (parsed.hostname or "").lower() not in REDDIT_HOSTS or "/r/" not in parsed.path:
            return False
        # A subreddit URL that is already a feed is read as RSS (kind generic_rss).
        return not parsed.path.endswith((".rss", ".xml"))

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "reddit_after" and checkpoint.get(
            "after"
        ) is not None

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        subreddit = subreddit_name(str(source["handle_or_url"]))
        url = f"{REDDIT_BASE_URL}/r/{subreddit}/new/.rss"
        body, _ = await self.http.get_text(url, user_agent=self.http.reddit_user_agent)
        posts = parsing.parse_feed_posts(body, url)[:limit]
        for post in posts:
            post["platform"] = "reddit"
            post["source"] = f"r/{subreddit}"
            guid = str(post.get("guid") or "")
            # The listing id ("t3_abc") minus its type prefix is the id the JSON archive stores.
            if guid:
                post["external_id"] = guid[3:] if guid.startswith("t3_") else guid
            if subreddit not in post.get("categories", []):
                post["categories"] = [subreddit, *post.get("categories", [])]
        return posts

    async def inspect(self, source: Source) -> Inspection:
        # The listing endpoints stop at ~250 items regardless of the subreddit's real size.
        return Inspection(available_posts=250, page_size=100, first_post_date=None)

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        subreddit = subreddit_name(str(source["handle_or_url"]))
        collected, pages_fetched = resume_counts(checkpoint)
        current_after: Optional[str] = (checkpoint or {}).get("after")

        while collected < target:
            page_limit = min(100, target - collected)
            page_posts, next_after = await self._fetch_listing(subreddit, after=current_after, limit=page_limit)
            if not page_posts:
                break

            pages_fetched += 1
            collected += len(page_posts)
            yield ArchivePage(page_posts, {
                "mode": "reddit_after",
                "after": next_after,
                "last_after": current_after,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            })

            if not next_after:
                break
            current_after = next_after
            if collected < target:
                await self.http.sleep(rate.delay_after(pages_fetched))

    async def _fetch_listing(
        self,
        subreddit: str,
        after: Optional[str] = None,
        limit: int = 100,
        sort_method: str = "top",
        time_filter: Optional[str] = "all",
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params = {"limit": str(limit)}
        if sort_method == "top" and time_filter:
            params["t"] = time_filter
        if after:
            params["after"] = after

        url = f"{REDDIT_BASE_URL}/r/{subreddit}/{sort_method}.json?{urllib.parse.urlencode(params)}"
        body, _ = await self.http.get_text(url, user_agent=self.http.reddit_user_agent)
        data = json.loads(body).get("data", {})

        posts: List[Dict[str, Any]] = []
        for child in data.get("children", []):
            if child.get("kind") != "t3":
                continue
            post_data = child.get("data", {})
            permalink = post_data.get("permalink", "")
            media_urls = []
            if post_data.get("url") and not str(post_data["url"]).startswith(_POST_URL_PREFIXES):
                media_urls.append(post_data["url"])

            posts.append({
                "platform": "reddit",
                "source": f"r/{subreddit}",
                "url": f"https://reddit.com{permalink}" if permalink else post_data.get("url"),
                "external_id": post_data.get("id"),
                "title": post_data.get("title", ""),
                "content": post_data.get("selftext", "") or post_data.get("title", ""),
                "content_html": post_data.get("selftext_html"),
                "date": datetime.fromtimestamp(post_data.get("created_utc", 0), tz=timezone.utc),
                "media_urls": media_urls,
                "categories": [subreddit] + ([post_data["link_flair_text"]] if post_data.get("link_flair_text") else []),
                "metadata": {},
            })
        return posts, data.get("after")


# ------------------------------------------------------------------ comments (post detail)


def reddit_post_json_url(post_url: str, limit: int) -> str:
    parsed = urllib.parse.urlparse(post_url)
    path = parsed.path.rstrip("/")
    if not path.endswith(".json"):
        path = f"{path}.json"
    query = urllib.parse.urlencode({"limit": str(limit), "depth": "8", "sort": "top", "raw_json": "1"})
    return urllib.parse.urlunparse((parsed.scheme or "https", parsed.netloc or "www.reddit.com", path, "", query, ""))


async def fetch_reddit_comments(http: KindHttp, post_url: str, limit: int = 80) -> List[Dict[str, Any]]:
    """A Reddit post's discussion thread, flattened depth-first, via the public JSON endpoint."""
    json_url = reddit_post_json_url(post_url, limit=max(1, min(limit, 250)))
    body, _ = await http.get_text(json_url, user_agent=http.reddit_user_agent)
    payload = json.loads(body)
    if not isinstance(payload, list) or len(payload) < 2:
        return []

    comments: List[Dict[str, Any]] = []

    def visit(nodes: List[Dict[str, Any]], depth: int = 0) -> None:
        for node in nodes:
            if len(comments) >= limit:
                return
            if node.get("kind") != "t1":
                continue
            data = node.get("data", {}) or {}
            body_text = str(data.get("body") or "").strip()
            if not body_text or body_text in {"[deleted]", "[removed]"}:
                continue

            comments.append({
                "id": data.get("id"),
                "author": data.get("author"),
                "body": body_text,
                "score": data.get("score"),
                "depth": depth,
                "created_at": datetime.fromtimestamp(data.get("created_utc", 0), tz=timezone.utc).isoformat(),
                "permalink": f"https://reddit.com{data.get('permalink', '')}" if data.get("permalink") else None,
            })
            replies = data.get("replies")
            if isinstance(replies, dict):
                visit(replies.get("data", {}).get("children", []), depth + 1)

    visit(payload[1].get("data", {}).get("children", []), 0)
    return comments[:limit]
