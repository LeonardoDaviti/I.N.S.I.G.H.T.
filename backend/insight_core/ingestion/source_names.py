"""A source's own name (issue 0178): every source gets one, from what its feed or page calls itself.

    name = await own_name(http, source)       # "Example Weekly", or None
    name = clean_name(raw_title, address)      # a title made fit to be a name, or None

A source added without a name showed its feed address everywhere a name is shown (Discover's voices, a post's
source line). Where the name comes from, by what the source reads:
  - a feed (generic RSS, Substack, a Telegram bridge's channel feed): the feed's own <title>, else the site's
    home page (og:site_name, else its <title>);
  - a followed page (page watching): the site's home page's og:site_name, else the page's own <title>;
  - a subreddit: "r/<name>" (its address says it);
  - anything else (a native Telegram channel, YouTube, X): none here; the repair (scripts/repair_source_names)
    takes the name another source of the same account has (a bridge's feed of the channel).
A fetch names an unnamed feed source too, from the feed it just read (kinds.base.FetchedPosts.title).
A title is a name when, once tidied (entities, spaces, a "RSS feed" / "Atom" tail), it says something an
address doesn't: not empty, not a generic word ("Feed", "Blog", "Home", "RSS"), not an address. Nothing here
ever writes over a name: a name the owner set is kept (the callers write only where none is set).
"""
from __future__ import annotations

import html
import logging
import re
import urllib.parse
from typing import Any, Mapping, Optional

from insight_core.ingestion.feed_finder import FEED_BYTES, feed_title
from insight_core.ingestion.kinds import parsing

logger = logging.getLogger("insight.ingestion.source_names")

PAGE_BYTES = 256 * 1024     # a page's head holds its <title> and og:site_name
MAX_NAME = 120
GENERIC = frozenset({"rss", "atom", "feed", "feeds", "rss feed", "atom feed", "blog", "the blog", "posts", "news",
                     "home", "index", "untitled", "articles", "latest", "latest posts", "updates", "recent posts",
                     "all posts", "home page", "homepage", "main", "default", "rss 2.0"})
# A feed format named in a title's tail: "Example Blog | RSS Feed", "Example Blog - Atom", "Example RSS feed" ->
# "Example Blog"; a title that only ends in the word ("The Atom") keeps it.
FORMAT_TAIL_RE = re.compile(r"\s*[|\-–—:·»]\s*(?:(?:rss|atom)(?:\s*2\.0)?(?:\s+feed)?|feed)\s*$"
                            r"|\s+(?:rss|atom)(?:\s*2\.0)?\s+feed\s*$", re.IGNORECASE)
# An address, not a name: a scheme or www. first, or a host and a path ("example.com/feed").
ADDRESS_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|www\.)\S+$|^[^\s/]+\.[a-z]{2,}/\S*$", re.IGNORECASE)
TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")


def clean_name(title: Optional[str], address: str = "") -> Optional[str]:
    """`title` tidied into a name, or None when it is no name: empty, a generic word, an address with a path or
    a scheme. A site that calls itself by its host ("example.com") is named so: that is its own choice."""
    text = " ".join(html.unescape(str(title or "")).split())
    text = FORMAT_TAIL_RE.sub("", text).strip(" |-–—:·»")
    if not text or text.casefold() in GENERIC or ADDRESS_RE.match(text):
        return None
    if address and text.casefold() == address.strip().casefold():
        return None
    return text[:MAX_NAME].rstrip()


def home_page(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(path="/", params="", query="", fragment=""))


def page_name(page: str, url: str) -> Optional[str]:
    """A page's own name: og:site_name, else its <title>."""
    site = clean_name(parsing.meta_content(page, "og:site_name"), url)
    if site:
        return site
    match = TITLE_RE.search(page or "")
    return clean_name(match.group(1), url) if match else None


async def _start(http: Any, url: str, size: int) -> Optional[bytes]:
    try:
        body, _ = await http.get_start(url, size)
        return body
    except Exception as exc:  # noqa: BLE001 - no name from there
        logger.info("Source names: %s not read (%s)", url, str(exc)[:160])
        return None


async def _home_name(http: Any, url: str) -> Optional[str]:
    body = await _start(http, home_page(url), PAGE_BYTES)
    return page_name(body.decode("utf-8", errors="replace"), url) if body else None


def address_name(platform: Optional[str], address: str) -> Optional[str]:
    """A name the address itself says, with no request: a subreddit's "r/<name>"."""
    if (platform or "").lower() == "reddit" or "reddit.com/r/" in address.lower():
        from insight_core.ingestion.kinds import reddit
        try:
            return "r/" + reddit.subreddit_name(address)
        except Exception:  # noqa: BLE001 - not a subreddit address
            return None
    return None


async def own_name(http: Any, source: Mapping[str, Any]) -> Optional[str]:
    """What the source calls itself (the module's order), or None. Never raises for a site's failure."""
    platform = str(source.get("platform") or "")
    address = str(source.get("handle_or_url") or "").strip()
    settings = source.get("settings") or {}
    if not address or platform == "saved":
        return None
    named = address_name(platform, address)
    if named or platform != "rss" or "://" not in address:
        return named
    if isinstance(settings.get("page_watch"), dict):
        name = await _home_name(http, address)
        if name:
            return name
        body = await _start(http, address, PAGE_BYTES)
        return page_name(body.decode("utf-8", errors="replace"), address) if body else None
    body = await _start(http, address, FEED_BYTES)
    if body is None:
        return None   # the feed did not answer: its site is not asked either
    return clean_name(feed_title(body), address) or await _home_name(http, address)


__all__ = ["address_name", "clean_name", "own_name", "page_name"]
