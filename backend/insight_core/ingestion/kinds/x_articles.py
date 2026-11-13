"""X Articles (X's long-form posts) read for a tweet the Nitter bridge gives only as a link (v10.13.10).

Nitter shows an X Article as a link alone (x.com/i/article/<id>, or <its host>/i/article/<id>, or a t.co link
showing one), so the post stored had no text to read, search or understand. A tweet whose own text (its quoted
tweet aside) holds such a link is read again by its status id:

  1. the article's whole text, from X_ARTICLE_TEXT_URL (default fxtwitter's API: tweet.article.content.blocks,
     joined into paragraphs, headers and list items kept);
  2. else its title and first ~200 characters, from X_ARTICLE_PREVIEW_URL (default X's own embed endpoint,
     cdn.syndication.twimg.com: article.title, article.preview_text), marked a preview the way a teaser is
     (metadata.page_read_outcome "preview_only": the post page says "Summary only").

Each address is a template ({user}, {id}); set empty, that route is off (both empty: no lookups). A lookup that
fails, times out (LOOKUP_TIMEOUT_S) or finds no article leaves the post as the bridge gave it (logged): a fetch
never fails on one. The post keeps its address, date and author; its title becomes the article's (a retweet's
or reply's "RT by @x: " / "R to @x: " kept). metadata.x_article says which article, read how, and when.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Tuple

from insight_core.db.repo_posts import FULL_TEXT_FLAG, X_ARTICLE_KEY
from insight_core.ingestion import full_text
from insight_core.ingestion.kinds import parsing
from insight_core.utils.byline import RT_BY_PREFIX

logger = logging.getLogger("insight.ingestion.x_articles")

TEXT_URL_ENV = "X_ARTICLE_TEXT_URL"
PREVIEW_URL_ENV = "X_ARTICLE_PREVIEW_URL"
DEFAULT_TEXT_URL = "https://api.fxtwitter.com/{user}/status/{id}"
# The embed endpoint asks for a token; any value is taken (checked 2026-11-11).
DEFAULT_PREVIEW_URL = "https://cdn.syndication.twimg.com/tweet-result?id={id}&token=insight"
# At most this many articles looked up per fetch (an archive: per page of the bridge), LOOKUP_DELAY_S apart,
# each request given LOOKUP_TIMEOUT_S. Not measured.
MAX_PER_FETCH = 5
LOOKUP_DELAY_S = 2.0
LOOKUP_TIMEOUT_S = 10.0
# A stored preview is looked up again when its tweet is fetched again, at most once in this long.
PREVIEW_RETRY_APART = timedelta(days=1)
# The repair's host key (scripts/repair_full_text): its articles are read one at a time.
HOST_KEY = "x-articles"
VIA_TEXT, VIA_PREVIEW = "text", "preview"

ARTICLE_LINK_RE = re.compile(r"/i/article/\d")
ARTICLE_ANCHOR_RE = re.compile(r"(?is)<a\b[^>]*>(?:(?!</a>).)*?</a>")
ARTICLE_URL_RE = re.compile(r"(?i)[^\s<>\"]*/i/article/[^\s<>\"]*")
QUOTE_START_RE = re.compile(r"(?is)(?:<hr\s*/?>\s*)?<blockquote\b")
TITLE_PREFIX_RE = re.compile(r"^(?:" + RT_BY_PREFIX + r"|R to @\w+: )+")   # Byline's "RT by @x: " (0189)
HEADERS = {"header-one": "h2", "header-two": "h3", "header-three": "h4"}
LISTS = {"unordered-list-item": "ul", "ordered-list-item": "ol"}


def configured(env: Mapping[str, str] = os.environ) -> Tuple[str, str]:
    """(the full text's address template, the preview's): the defaults when unset, "" when set empty (off)."""
    return (env.get(TEXT_URL_ENV, DEFAULT_TEXT_URL).strip(), env.get(PREVIEW_URL_ENV, DEFAULT_PREVIEW_URL).strip())


def lookups_on(env: Mapping[str, str] = os.environ) -> bool:
    return any(configured(env))


def _split(content_html: str) -> Tuple[str, str]:
    """(the tweet's own html, its quoted tweet's: Nitter's <hr/><blockquote>…, "" when none)."""
    match = QUOTE_START_RE.search(content_html)
    return (content_html[:match.start()], content_html[match.start():]) if match else (content_html, "")


def is_article_post(post: Mapping[str, Any]) -> bool:
    """Whether the tweet's own text (its quoted tweet aside) links an X Article: its href or its shown text."""
    own, _ = _split(str(post.get("content_html") or ""))
    if not own.strip():
        own = str(post.get("content") or "")
    return bool(ARTICLE_LINK_RE.search(own))


def is_stub(post: Mapping[str, Any]) -> bool:
    """An article post whose own text is the link alone (what the reader got before v10.13.10)."""
    own, _ = _split(str(post.get("content_html") or ""))
    return is_article_post(post) and not _intro(own)


def _intro(own_html: str) -> str:
    """The tweet's own html without its article link, "" when nothing else is said."""
    kept = ARTICLE_ANCHOR_RE.sub(lambda m: "" if ARTICLE_LINK_RE.search(m.group(0)) else m.group(0), own_html)
    kept = ARTICLE_URL_RE.sub("", kept)
    return kept if parsing.strip_html(kept).strip() else ""


def status_of(url: str) -> Optional[Tuple[str, str]]:
    """(user, status id) of a Nitter tweet address (https://<nitter>/<user>/status/<id>#m)."""
    match = re.search(r"//[^/]+/([^/?#]+)/status/(\d+)", url or "")
    return (match.group(1), match.group(2)) if match else None


@dataclass(frozen=True)
class Article:
    title: str
    html: str
    text: str
    complete: bool
    via: str
    article_id: Optional[str] = None
    cover: Optional[str] = None


def _cover(article: Mapping[str, Any]) -> Optional[str]:
    media = article.get("cover_media")
    if not isinstance(media, dict):
        return None
    info = media.get("media_info") if isinstance(media.get("media_info"), dict) else media
    found = info.get("original_img_url") or info.get("url")
    return found if isinstance(found, str) and found.startswith("http") else None


def _escaped(text: str) -> str:
    return html_lib.escape(text.strip()).replace("\n", "<br>")


def blocks_html(blocks: List[Any]) -> Tuple[str, str]:
    """(html, plain text) of an article's blocks: paragraphs, headers, list items and quotes kept; a block with
    no text (an image, an embed) dropped. The text is the blocks one paragraph each, a list item "• " or "1. "."""
    parts: List[str] = []
    lines: List[str] = []
    open_list: Optional[str] = None
    number = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text, kind = str(block.get("text") or ""), str(block.get("type") or "unstyled")
        if not text.strip():
            continue
        tag = LISTS.get(kind)
        if tag != open_list:
            if open_list:
                parts.append(f"</{open_list}>")
            if tag:
                parts.append(f"<{tag}>")
            open_list, number = tag, 0
        if tag:
            number += 1
            parts.append(f"<li>{_escaped(text)}</li>")
            lines.append(f"{number}. {text.strip()}" if tag == "ol" else f"• {text.strip()}")
            continue
        if kind in HEADERS:
            parts.append(f"<{HEADERS[kind]}>{_escaped(text)}</{HEADERS[kind]}>")
        elif kind == "blockquote":
            parts.append(f"<blockquote><p>{_escaped(text)}</p></blockquote>")
        elif kind == "code-block":
            parts.append(f"<pre>{html_lib.escape(text)}</pre>")
        else:
            parts.append(f"<p>{_escaped(text)}</p>")
        lines.append(text.strip())
    if open_list:
        parts.append(f"</{open_list}>")
    return "".join(parts), "\n\n".join(lines)


def _from_text_answer(data: Any) -> Optional[Article]:
    article = ((data or {}).get("tweet") or {}).get("article") if isinstance(data, dict) else None
    if not isinstance(article, dict):
        return None
    blocks = (article.get("content") or {}).get("blocks") if isinstance(article.get("content"), dict) else None
    html, text = blocks_html(blocks if isinstance(blocks, list) else [])
    if not text:
        return None
    return Article(str(article.get("title") or "").strip(), html, text, True, VIA_TEXT,
                   str(article.get("id") or article.get("rest_id") or "") or None, _cover(article))


def _from_preview_answer(data: Any) -> Optional[Article]:
    article = data.get("article") if isinstance(data, dict) else None
    if not isinstance(article, dict):
        return None
    title = str(article.get("title") or "").strip()
    preview = str(article.get("preview_text") or "").strip()
    if not title and not preview:
        return None
    html, text = (f"<p>{_escaped(preview)}</p>", preview) if preview else ("", "")
    return Article(title, html, text, False, VIA_PREVIEW, str(article.get("rest_id") or "") or None, _cover(article))


async def _ask(http: Any, url: str, timeout: float) -> Any:
    body, _ = await asyncio.wait_for(http.get_text(url), timeout)
    return json.loads(body)


async def read_article(http: Any, user: str, status_id: str, *, env: Mapping[str, str] = os.environ,
                       timeout: Optional[float] = None) -> Optional[Article]:
    """The X Article of tweet status_id: its whole text (the text route), else its title and preview (the
    preview route), else None. Never raises: each route's failure is logged. Each request is given timeout
    seconds (LOOKUP_TIMEOUT_S by default)."""
    timeout = timeout or LOOKUP_TIMEOUT_S
    text_url, preview_url = configured(env)
    routes = ((text_url, _from_text_answer), (preview_url, _from_preview_answer))
    for template, read in routes:
        if not template:
            continue
        url = template.format(user=user, id=status_id)
        try:
            article = read(await _ask(http, url, timeout))
        except Exception as exc:  # noqa: BLE001 - a lookup never fails the fetch
            logger.info("X Article lookup failed for status %s at %s (%s): %s", status_id, url.split("?", 1)[0],
                        type(exc).__name__, str(exc)[:200])
            continue
        if article is not None:
            return article
        logger.info("X Article lookup found no article for status %s at %s", status_id, url.split("?", 1)[0])
    return None


def with_article(post: Dict[str, Any], article: Article, at: datetime) -> Dict[str, Any]:
    """The post with its article: title (its "RT by"/"R to" kept), the tweet's own words before the article,
    its quoted tweet after; the cover in its pictures. The whole text is read in full (metadata
    full_content_fetched, outcome "full"); a preview is a teaser (outcome "preview_only")."""
    own, quoted = _split(str(post.get("content_html") or ""))
    intro = _intro(own)
    cover = f'<p><img src="{html_lib.escape(article.cover, quote=True)}"></p>' if article.cover else ""
    heading = f"<h1>{html_lib.escape(article.title)}</h1>" if article.title else ""
    body = f"{intro}{heading}{cover}{article.html}{quoted}"
    intro_text = parsing.strip_html(intro).strip()
    text = "\n\n".join(part for part in (intro_text, article.title, article.text, parsing.strip_html(quoted).strip())
                       if part)
    prefix = TITLE_PREFIX_RE.match(str(post.get("title") or ""))
    title = f"{prefix.group(0) if prefix else ''}{article.title}" if article.title else post.get("title")
    media = list(post.get("media_urls") or [])
    if article.cover and article.cover not in media:
        media.insert(0, article.cover)
    read = {"id": article.article_id, "via": article.via, "complete": article.complete, "at": at.isoformat()}
    metadata = {**(post.get("metadata") or {}), X_ARTICLE_KEY: read}
    if article.complete:
        metadata[FULL_TEXT_FLAG] = True
    updated = {**post, "title": title, "content_html": body, "content": text, "media_urls": media, "metadata": metadata}
    return full_text.with_outcome(updated, full_text.FULL if article.complete else full_text.PREVIEW_ONLY, at)


def due_again(stored: Mapping[str, Any], now: datetime) -> bool:
    """Whether a stored article post is looked up again: a preview, read at least PREVIEW_RETRY_APART ago."""
    read = (stored.get("metadata") or {}).get(X_ARTICLE_KEY) or {}
    if read.get("complete"):
        return False
    try:
        return datetime.fromisoformat(str(read.get("at"))) <= now - PREVIEW_RETRY_APART
    except ValueError:
        return True


class ArticleUnavailable(Exception):
    """Neither route gave the article (the repair counts it a failed read)."""
