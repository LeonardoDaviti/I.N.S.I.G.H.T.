"""Pure parsing helpers shared by the source kinds (moved off SourceFetchService in B3).

No I/O and no state: every function here is a plain transformation of text, XML or
datetimes, so kinds and site adapters can share them without holding a service.
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from insight_core.utils.media import clean_url

TELEGRAM_BASE_URL = "https://telegram.local"
IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)


def strip_html(html_text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html_text or "")
    return re.sub(r"\s+", " ", text).strip()


def isoformat(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.isoformat()


def parse_datetime_value(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        dt = parsedate_to_datetime(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def child_text(node: ET.Element, child_name: str) -> Optional[str]:
    for child in node:
        if local_name(child.tag) == child_name:
            return (child.text or "").strip()
    return None


def child_inner_xml(node: ET.Element, child_name: str) -> str:
    for child in node:
        if local_name(child.tag) != child_name:
            continue

        if len(child) == 0:
            return child.text or ""

        text = child.text or ""
        for subchild in child:
            text += ET.tostring(subchild, encoding="unicode")
        return text

    return ""


def normalize_telegram_resources(value: str, telegram_origin: Optional[str] = None) -> str:
    target_origin = telegram_origin or TELEGRAM_BASE_URL
    replacements = (
        ("http://127.0.0.1:9504", target_origin),
        ("http://telegram.local:9504", target_origin),
        ("https://telegram.local:9504", target_origin),
        (TELEGRAM_BASE_URL, target_origin),
        ("http://telegram.local", target_origin),
    )

    normalized = value
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    return normalized


def normalize_feed_urls(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return normalize_telegram_resources(value)


def normalize_media_url(value: Any) -> Optional[str]:
    """A media URL as stored: HTML entities decoded (an `&amp;` breaks signed CDN URLs)."""
    return normalize_feed_urls(clean_url(value))


def extract_html_image_urls(html_text: str) -> List[str]:
    media_urls: List[str] = []
    seen = set()
    for image_url in IMG_SRC_RE.findall(html_text or ""):
        normalized = normalize_media_url(image_url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            media_urls.append(normalized)
    return media_urls


def extract_article_html(html_text: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript|iframe|svg).*?</\1>", "", html_text or "")
    candidate_patterns = [
        r"(?is)<article\b[^>]*>(.*?)</article>",
        r"(?is)<main\b[^>]*>(.*?)</main>",
        r'(?is)<div\b[^>]+id="markdownBody"[^>]*>(.*?)</div>\s*(?:</main>|<footer\b|</body>|$)',
        r'(?is)<div\b[^>]+class="[^"]*(?:entry-content|post-content|article-content|content-body|prose|single-post-content)[^"]*"[^>]*>(.*?)</div>',
    ]

    candidate = ""
    for pattern in candidate_patterns:
        match = re.search(pattern, cleaned)
        if match:
            candidate = match.group(1)
            break

    if not candidate:
        body_match = re.search(r"(?is)<body\b[^>]*>(.*?)</body>", cleaned)
        candidate = body_match.group(1) if body_match else cleaned

    blocks = re.findall(r"(?is)<(?:h1|h2|h3|p|blockquote|li)[^>]*>.*?</(?:h1|h2|h3|p|blockquote|li)>", candidate)
    if not blocks:
        blocks = re.findall(r"(?is)<(?:h1|h2|h3|p|blockquote|li)[^>]*>.*?</(?:h1|h2|h3|p|blockquote|li)>", cleaned)

    text_size = len(strip_html(" ".join(blocks)))
    if text_size < 500:
        return ""

    return "\n".join(blocks)


def origin_from_source(source_url: str, fallback: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return fallback


def path_segments(url: str) -> List[str]:
    return [segment for segment in urllib.parse.urlparse(url).path.split("/") if segment]


# ---------------------------------------------------------------- RSS / Atom feeds


def parse_feed_posts(feed_text: str, source_url: str) -> List[Dict[str, Any]]:
    """Parse an RSS 2.0 or Atom document into post drafts, newest first."""
    root = ET.fromstring(feed_text)
    posts: List[Dict[str, Any]] = []

    if local_name(root.tag) == "rss":
        channel = next((child for child in root if local_name(child.tag) == "channel"), None)
        items = [child for child in (channel if channel is not None else []) if local_name(child.tag) == "item"]
        for item in items:
            content_html = normalize_feed_urls(
                child_inner_xml(item, "description") or child_inner_xml(item, "encoded")
            )
            url = normalize_feed_urls(child_text(item, "link") or source_url)
            posts.append({
                "platform": "rss",
                "source": source_url,
                "url": url,
                "guid": child_text(item, "guid"),
                "title": normalize_feed_urls(child_text(item, "title") or ""),
                "content": strip_html(content_html),
                "content_html": content_html,
                "date": parse_datetime_value(child_text(item, "pubDate") or child_text(item, "updated")),
                "media_urls": _extract_xml_media_urls(item, content_html),
                "categories": _extract_xml_categories(item),
                "metadata": {},
            })
    elif local_name(root.tag) == "feed":
        entries = [child for child in root if local_name(child.tag) == "entry"]
        for entry in entries:
            content_html = normalize_feed_urls(
                child_inner_xml(entry, "content") or child_inner_xml(entry, "summary")
            )
            url = normalize_feed_urls(_extract_atom_link(entry) or source_url)
            posts.append({
                "platform": "rss",
                "source": source_url,
                "url": url,
                "guid": child_text(entry, "id"),
                "title": normalize_feed_urls(child_text(entry, "title") or ""),
                "content": strip_html(content_html),
                "content_html": content_html,
                "date": parse_datetime_value(child_text(entry, "published") or child_text(entry, "updated")),
                "media_urls": _extract_xml_media_urls(entry, content_html),
                "categories": _extract_xml_categories(entry),
                "metadata": {},
            })

    posts.sort(key=lambda post: post.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return posts


def _extract_xml_media_urls(node: ET.Element, content_html: str) -> List[str]:
    media_urls: List[str] = []

    for child in node.iter():
        name = local_name(child.tag)
        if name in {"enclosure", "content"}:
            media_url = child.attrib.get("url") or child.attrib.get("href")
            if media_url:
                media_urls.append(normalize_media_url(media_url))

        if name == "link":
            rel = child.attrib.get("rel")
            media_type = child.attrib.get("type", "")
            href = child.attrib.get("href")
            if href and (rel == "enclosure" or media_type.startswith("image/") or media_type.startswith("video/")):
                media_urls.append(normalize_media_url(href))

    for image_url in IMG_SRC_RE.findall(content_html or ""):
        media_urls.append(normalize_media_url(image_url))

    deduped = []
    seen = set()
    for media_url in media_urls:
        if media_url and media_url not in seen:
            seen.add(media_url)
            deduped.append(media_url)

    return deduped


def _extract_xml_categories(node: ET.Element) -> List[str]:
    categories: List[str] = []
    for child in node:
        if local_name(child.tag) != "category":
            continue
        term = child.attrib.get("term") or child.attrib.get("label") or (child.text or "")
        if term:
            categories.append(term)

    return sorted({category.strip() for category in categories if category and category.strip()})


def _extract_atom_link(entry: ET.Element) -> Optional[str]:
    fallback_href = None
    for child in entry:
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if not href:
            continue
        if child.attrib.get("rel") in (None, "", "alternate"):
            return href
        fallback_href = fallback_href or href
    return fallback_href
