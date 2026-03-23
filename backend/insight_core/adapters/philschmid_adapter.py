"""Phil Schmid Cloud Attention newsletter adapter."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter


class PhilSchmidCloudAttentionAdapter(BaseSourceAdapter):
    """Archive Cloud Attention through paginated issue pages."""

    adapter_type = "philschmid_cloud_attention"
    HOSTS = {"www.philschmid.de", "philschmid.de"}
    PATH_PREFIX = "/cloud-attention"
    PAGE_SIZE = 8
    PAGE_DELAY_SECONDS = 1
    ISSUE_RE = re.compile(r'href="(?P<href>/cloud-attention/issue-\d+)"', re.IGNORECASE)
    PAGE_RE = re.compile(r"[?&]page=(\d+)")
    JSON_LD_RE = re.compile(r'(?is)<script type="application/ld\+json">\s*(?P<payload>\{.*?\})\s*</script>')
    META_CONTENT_RE = re.compile(
        r'(?is)<meta\b[^>]+(?:name|property)="(?P<name>[^"]+)"[^>]+content="(?P<content>[^"]*)"[^>]*>'
    )

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in self.HOSTS and (parsed.path or "").startswith(self.PATH_PREFIX)

    def default_rate_limit(self) -> Dict[str, Any]:
        return {"page_delay_seconds": self.PAGE_DELAY_SECONDS}

    def checkpoint_is_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "site_index" and checkpoint.get("next_index") is not None

    async def inspect_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        entries = await self._discover_entries(source)
        first_post_date = None
        if entries:
            oldest_post = await self._fetch_issue_post(source, entries[-1], include_html=False)
            first_post_date = self.service._isoformat((oldest_post or {}).get("date"))

        return {
            "available_posts": len(entries),
            "page_size": self.PAGE_SIZE,
            "first_post_date": first_post_date,
            "rate_limit": self.default_rate_limit(),
        }

    async def fetch_live_posts(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        entries = await self._discover_entries(source)
        posts: List[Dict[str, Any]] = []
        for entry in entries[: max(1, limit)]:
            post = await self._fetch_issue_post(source, entry)
            if post:
                posts.append(post)
        return posts[:limit]

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
        entries = await self._discover_entries(source)
        next_index = int((checkpoint or {}).get("next_index") or 0)
        pages_fetched = int(initial_pages_fetched or 0)
        collected: List[Dict[str, Any]] = []

        while (len(collected) + initial_collected) < target_posts and next_index < len(entries):
            batch_limit = min(self.PAGE_SIZE, target_posts - (len(collected) + initial_collected))
            batch_entries = entries[next_index: next_index + batch_limit]
            if not batch_entries:
                break

            batch_posts: List[Dict[str, Any]] = []
            for entry in batch_entries:
                post = await self._fetch_issue_post(source, entry)
                if post:
                    batch_posts.append(post)
                    collected.append(post)

            next_index += len(batch_entries)
            pages_fetched += 1
            checkpoint_payload = {
                "mode": "site_index",
                "adapter": self.adapter_type,
                "next_index": next_index,
                "pages_fetched": pages_fetched,
                "collected_posts": len(collected) + initial_collected,
                "total_candidates": len(entries),
            }
            progress_payload = {
                "stage": "page_fetched",
                "platform": "philschmid",
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "next_index": next_index,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100.0),
                "message": f"Fetched Cloud Attention batch {pages_fetched}",
            }
            await self.service._emit_page(page_callback, batch_posts, checkpoint_payload, progress_payload)
            await self.service._emit_progress(progress_callback, progress_payload)

            if (len(collected) + initial_collected) < target_posts and next_index < len(entries):
                await asyncio.sleep(int((rate_limit or {}).get("page_delay_seconds", self.PAGE_DELAY_SECONDS)))

        final_checkpoint = {
            "mode": "site_index",
            "adapter": self.adapter_type,
            "next_index": next_index,
            "pages_fetched": pages_fetched,
            "collected_posts": len(collected) + initial_collected,
            "total_candidates": len(entries),
        }
        return collected[: max(0, target_posts - initial_collected)], pages_fetched, final_checkpoint

    async def _discover_entries(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        base = self._archive_url(source)
        first_html, _ = await self.service._fetch_text(base)
        max_page = self._extract_max_page(first_html)
        urls: List[str] = []
        seen = set()

        for page in range(1, max_page + 1):
            if page == 1:
                html = first_html
            else:
                html, _ = await self.service._fetch_text(f"{base}?page={page}")
            for match in self.ISSUE_RE.finditer(html):
                absolute_url = urllib.parse.urljoin(base, match.group("href"))
                if absolute_url in seen:
                    continue
                seen.add(absolute_url)
                urls.append(absolute_url)

        return [{"url": url} for url in urls]

    async def _fetch_issue_post(
        self,
        source: Dict[str, Any],
        entry: Dict[str, Any],
        *,
        include_html: bool = True,
    ) -> Optional[Dict[str, Any]]:
        url = str(entry.get("url") or "")
        if not url:
            return None

        html, _ = await self.service._fetch_text(url)
        metadata = self._extract_json_ld(html)
        article_html = self.service._extract_article_html(html) if include_html else ""
        content = self.service._strip_html(article_html or "")
        if not content.strip():
            content = str(metadata.get("description") or self._extract_meta_content(html, "description") or "").strip()
        if not content.strip():
            return None

        parsed = urllib.parse.urlparse(url)
        issue_slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or self._archive_url(source)),
            "url": url,
            "external_id": issue_slug,
            "guid": url,
            "title": str(metadata.get("headline") or self._extract_meta_content(html, "og:title") or url).strip(),
            "content": content,
            "content_html": article_html,
            "date": self.service._parse_datetime_value(str(metadata.get("datePublished") or "")),
            "media_urls": [self._extract_meta_content(html, "og:image")] if self._extract_meta_content(html, "og:image") else [],
            "categories": ["Cloud Attention"],
            "metadata": {
                "adapter": self.adapter_type,
                "issue_slug": issue_slug,
                "description": metadata.get("description") or self._extract_meta_content(html, "description"),
                "author": ((metadata.get("author") or {}).get("name") if isinstance(metadata.get("author"), dict) else None),
            },
        }

    def _archive_url(self, source: Dict[str, Any]) -> str:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://www.philschmid.de/cloud-attention"))
        return f"{parsed.scheme or 'https'}://{parsed.netloc or 'www.philschmid.de'}{self.PATH_PREFIX}"

    def _extract_max_page(self, html: str) -> int:
        pages = [int(value) for value in self.PAGE_RE.findall(html or "")]
        return max(pages) if pages else 1

    def _extract_json_ld(self, html: str) -> Dict[str, Any]:
        for match in self.JSON_LD_RE.finditer(html or ""):
            try:
                payload = json.loads(match.group("payload"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("@type") == "BlogPosting":
                return payload
        return {}

    def _extract_meta_content(self, html: str, meta_name: str) -> str:
        meta_name = meta_name.lower()
        for match in self.META_CONTENT_RE.finditer(html or ""):
            if (match.group("name") or "").lower() == meta_name:
                return match.group("content") or ""
        return ""
