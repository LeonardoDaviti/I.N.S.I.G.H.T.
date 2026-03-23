"""LessWrong GraphQL-backed source adapter."""

from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter


class LessWrongAdapter(BaseSourceAdapter):
    """Archive LessWrong through its GraphQL posts list instead of shallow RSS only."""

    adapter_type = "lesswrong_graphql"
    GRAPHQL_URL = "https://www.lesswrong.com/graphql"
    PAGE_SIZE = 20
    PAGE_DELAY_SECONDS = 1
    HOSTS = {"www.lesswrong.com", "lesswrong.com"}

    POSTS_QUERY = """
    query InsightLessWrongPosts($limit: Int!, $offset: Int!) {
      posts(input: { terms: { view: "new", limit: $limit, offset: $offset } }) {
        results {
          _id
          title
          pageUrl
          postedAt
          htmlBody
          baseScore
          user {
            slug
            displayName
          }
        }
      }
    }
    """

    POSTS_META_QUERY = """
    query InsightLessWrongPostMeta($limit: Int!, $offset: Int!) {
      posts(input: { terms: { view: "new", limit: $limit, offset: $offset } }) {
        results {
          _id
          title
          pageUrl
          postedAt
        }
      }
    }
    """

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in self.HOSTS

    def default_rate_limit(self) -> Dict[str, Any]:
        return {"page_delay_seconds": self.PAGE_DELAY_SECONDS}

    def checkpoint_is_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "lesswrong_offset" and checkpoint.get("next_offset") is not None

    async def inspect_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        available_posts = await self._count_available_posts()
        oldest_post = None
        if available_posts > 0:
            page = await self._fetch_posts_meta_page(limit=1, offset=available_posts - 1)
            oldest_post = page[0] if page else None

        return {
            "available_posts": available_posts,
            "page_size": self.PAGE_SIZE,
            "first_post_date": self.service._isoformat((oldest_post or {}).get("date")),
            "rate_limit": self.default_rate_limit(),
        }

    async def fetch_live_posts(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        return await self._fetch_posts_page(limit=max(1, min(limit, 50)), offset=0, source_url=str(source.get("handle_or_url") or ""))

    async def archive_posts(
        self,
        source: Dict[str, Any],
        target_posts: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        *,
        checkpoint: Optional[Dict[str, Any]] = None,
        initial_collected: int = 0,
        initial_pages_fetched: int = 0,
        page_callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]], Awaitable[None] | None]] = None,
        rate_limit: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
        current_offset = int((checkpoint or {}).get("next_offset") or 0)
        pages_fetched = int(initial_pages_fetched or 0)
        collected: List[Dict[str, Any]] = []

        while (len(collected) + initial_collected) < target_posts:
            page_limit = min(self.PAGE_SIZE, target_posts - (len(collected) + initial_collected))
            page_posts = await self._fetch_posts_page(
                limit=page_limit,
                offset=current_offset,
                source_url=str(source.get("handle_or_url") or ""),
            )
            if not page_posts:
                break

            pages_fetched += 1
            collected.extend(page_posts)
            current_offset += len(page_posts)
            checkpoint_payload = {
                "mode": "lesswrong_offset",
                "next_offset": current_offset,
                "pages_fetched": pages_fetched,
                "collected_posts": len(collected) + initial_collected,
            }
            progress_payload = {
                "stage": "page_fetched",
                "platform": "lesswrong",
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "offset": current_offset,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100),
                "message": f"Fetched LessWrong page {pages_fetched}",
            }
            await self.service._emit_page(page_callback, page_posts, checkpoint_payload, progress_payload)
            await self.service._emit_progress(progress_callback, progress_payload)

            if (len(collected) + initial_collected) < target_posts:
                await asyncio.sleep(int((rate_limit or {}).get("page_delay_seconds", self.PAGE_DELAY_SECONDS)))

        final_checkpoint = {
            "mode": "lesswrong_offset",
            "next_offset": current_offset,
            "pages_fetched": pages_fetched,
            "collected_posts": len(collected) + initial_collected,
        }
        return collected[: max(0, target_posts - initial_collected)], pages_fetched, final_checkpoint

    async def _count_available_posts(self) -> int:
        if not await self._has_post_at_offset(0):
            return 0

        low = 0
        high = 1
        while await self._has_post_at_offset(high):
            low = high
            high *= 2

        while low + 1 < high:
            mid = (low + high) // 2
            if await self._has_post_at_offset(mid):
                low = mid
            else:
                high = mid

        return low + 1

    async def _has_post_at_offset(self, offset: int) -> bool:
        results = await self._graphql_posts_meta(limit=1, offset=offset)
        return bool(results)

    async def _fetch_posts_meta_page(self, limit: int, offset: int) -> List[Dict[str, Any]]:
        rows = await self._graphql_posts_meta(limit=max(1, limit), offset=max(0, offset))
        posts: List[Dict[str, Any]] = []
        for row in rows:
            posts.append(
                {
                    "external_id": row.get("_id"),
                    "title": str(row.get("title") or "").strip(),
                    "url": str(row.get("pageUrl") or ""),
                    "date": self.service._parse_datetime_value(row.get("postedAt")),
                }
            )
        return posts

    async def _fetch_posts_page(self, limit: int, offset: int, source_url: str = "https://www.lesswrong.com/feed.xml") -> List[Dict[str, Any]]:
        rows = await self._graphql_posts(limit=max(1, limit), offset=max(0, offset))
        posts: List[Dict[str, Any]] = []
        for row in rows:
            html_body = str(row.get("htmlBody") or "")
            title = str(row.get("title") or "").strip()
            url = str(row.get("pageUrl") or "")
            author = row.get("user") or {}
            media_urls = self.service._extract_html_image_urls(html_body)
            posts.append(
                {
                    "platform": "rss",
                    "source": source_url,
                    "url": url,
                    "external_id": row.get("_id"),
                    "guid": row.get("_id"),
                    "title": title,
                    "content": self.service._strip_html(html_body),
                    "content_html": html_body,
                    "date": self.service._parse_datetime_value(row.get("postedAt")),
                    "media_urls": media_urls,
                    "categories": [],
                    "metadata": {
                        "adapter": self.adapter_type,
                        "author_slug": author.get("slug"),
                        "author_display_name": author.get("displayName"),
                        "base_score": row.get("baseScore"),
                    },
                }
            )
        return posts

    async def _graphql_posts(self, *, limit: int, offset: int) -> List[Dict[str, Any]]:
        return await self._graphql_rows(self.POSTS_QUERY, limit=limit, offset=offset)

    async def _graphql_posts_meta(self, *, limit: int, offset: int) -> List[Dict[str, Any]]:
        return await self._graphql_rows(self.POSTS_META_QUERY, limit=limit, offset=offset)

    async def _graphql_rows(self, query: str, *, limit: int, offset: int) -> List[Dict[str, Any]]:
        payload = {
            "query": query,
            "variables": {
                "limit": int(limit),
                "offset": int(offset),
            },
        }
        response = await self.service._post_json(self.GRAPHQL_URL, payload)
        if response.get("errors"):
            raise ValueError(f"LessWrong GraphQL request failed: {response['errors'][0].get('message')}")
        data = response.get("data", {})
        posts = (((data.get("posts") or {}).get("results")) or [])
        return [row for row in posts if isinstance(row, dict)]
