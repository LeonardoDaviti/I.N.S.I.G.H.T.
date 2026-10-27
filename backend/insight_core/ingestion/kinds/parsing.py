"""Pure parsing helpers shared by the source kinds (moved off SourceFetchService in B3).

No I/O and no state: every function here is a plain transformation of text, XML or
datetimes, so kinds and site adapters can share them without holding a service.
"""
from __future__ import annotations

import html as html_lib
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from insight_core.utils.content_fingerprints import strip_html
from insight_core.utils.media import clean_url

TELEGRAM_BASE_URL = "https://telegram.local"
IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
META_CONTENT_RE = re.compile(
    r'(?is)<meta\b[^>]+(?:name|property)="(?P<name>[^"]+)"[^>]+content="(?P<content>[^"]*)"[^>]*>'
)


def meta_content(html: str | None, meta_name: str) -> str:
    """The content of the first <meta name|property="meta_name">, or "" (the name in any case)."""
    meta_name = meta_name.lower()
    for match in META_CONTENT_RE.finditer(html or ""):
        if (match.group("name") or "").lower() == meta_name:
            return match.group("content") or ""
    return ""


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


# Page chrome, dropped with everything inside it before the article is chosen: these
# elements, and any element (but <html> and <body>) whose class or id token starts with
# one of the prefixes, or ends in "-tags" / "-categories" after a theme prefix
# ("nvidia-tags"). Only that ending is matched inside a token: a plugin wraps whole
# articles in "has-highlight-and-share", and WordPress gives <article> itself
# "category-ai tag-agents".
CHROME_TAGS = frozenset({"nav", "header", "footer", "aside", "form"})
CHROME_PREFIXES = ("nav", "menu", "footer", "related", "share", "subscribe", "sidebar")
CHROME_ENDINGS = ("-tags", "_tags", "-categories", "_categories")
# A table of contents is a menu too (anthropic.com's "StickyTableOfContents-module__Trigger").
CHROME_PARTS = ("tableofcontents", "table-of-contents", "table_of_contents")
CHROME_TOKENS = frozenset({"toc"})
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                       "param", "source", "track", "wbr"})
TEXT_BLOCKS = "h1|h2|h3|p|blockquote"


def _is_chrome(tag: str, attrs: List[Tuple[str, Optional[str]]]) -> bool:
    if tag in CHROME_TAGS:
        return True
    if tag in ("html", "body"):
        return False
    tokens = " ".join(value or "" for name, value in attrs if name in ("class", "id")).lower().split()
    return any(token.startswith(CHROME_PREFIXES) or token.endswith(CHROME_ENDINGS) or token in CHROME_TOKENS
               or any(part in token for part in CHROME_PARTS) for token in tokens)


class _ChromeStripper(HTMLParser):
    """Re-emits the page without its chrome. Regex can't find where a nested element ends:
    `dropping` is the stack of elements open inside the dropped one."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.kept: List[str] = []
        self.dropping: List[str] = []

    def _keep(self, text: str) -> None:
        if not self.dropping:
            self.kept.append(text)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag not in VOID_TAGS and (self.dropping or _is_chrome(tag, attrs)):
            self.dropping.append(tag)
        else:
            self._keep(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._keep(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if not self.dropping:
            self.kept.append(f"</{tag}>")
        elif tag in self.dropping:  # closes it and whatever was left open inside it
            del self.dropping[len(self.dropping) - 1 - self.dropping[::-1].index(tag):]

    def handle_data(self, data: str) -> None:
        self._keep(data)

    def handle_entityref(self, name: str) -> None:
        self._keep(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._keep(f"&#{name};")


def _without_chrome(html_text: str) -> str:
    stripper = _ChromeStripper()
    stripper.feed(html_text)
    stripper.close()
    return "".join(stripper.kept)


IMG_TAG_RE = re.compile(r"(?is)<img\b[^>]*>")
IMG_ATTR_RE = re.compile(r"""(?is)\b(src|data-src|alt|width|height)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _article_image(tag: str, base_url: str) -> str:
    """An <img> as an article keeps it: its real address (a lazy image's data-src; Next.js's
    /_next/image?url= unwrapped; made absolute against base_url) and its alt. '' for a
    tracking pixel or an address that can't be fetched."""
    attrs = {name.lower(): html_lib.unescape(dq or sq) for name, dq, sq in IMG_ATTR_RE.findall(tag)}
    if "1" in (attrs.get("width"), attrs.get("height")):
        return ""
    src = attrs.get("data-src") or attrs.get("src") or ""
    if src.startswith("data:"):
        return ""
    if urllib.parse.urlparse(src).path.endswith("/_next/image"):
        src = (urllib.parse.parse_qs(urllib.parse.urlparse(src).query).get("url") or [src])[0]
    src = urllib.parse.urljoin(base_url, src) if base_url else src
    if not src.startswith(("http://", "https://")):
        return ""
    return f'<img src="{html_lib.escape(src)}" alt="{html_lib.escape(attrs.get("alt", ""))}">'


def extract_article_html(html_text: str, base_url: str = "") -> str:
    """The article's text blocks and images, in page order. base_url (the page's address)
    makes relative image addresses absolute; without it they are left out."""
    cleaned = re.sub(r"(?is)<(script|style|noscript|iframe|svg).*?</\1>", "", html_text or "")
    cleaned = _without_chrome(cleaned)
    candidate_patterns = [
        r"(?is)<article\b[^>]*>(.*?)</article>",
        r"(?is)<main\b[^>]*>(.*?)</main>",
        r'(?is)<div\b[^>]+id="markdownBody"[^>]*>(.*?)</div>\s*(?:</main>|<footer\b|</body>|$)',
        r'(?is)<div\b[^>]+class="[^"]*(?:entry-content|post-content|article-content|content-body|prose|single-post-content)[^"]*"[^>]*>(.*?)</div>',
    ]

    # The first candidate long enough to be the article: a page's first <article> can be a
    # 4-word "related" card while the post is in <main> (deepmind.google, 2026-10-27). The
    # whole body only when no candidate matched: a short <article> is no article, not a reason
    # to read the page's other lists as one (issue 0029).
    candidates = [match.group(1) for pattern in candidate_patterns if (match := re.search(pattern, cleaned))]
    if not candidates:
        body_match = re.search(r"(?is)<body\b[^>]*>(.*?)</body>", cleaned)
        candidates = [body_match.group(1) if body_match else cleaned]
    for candidate in candidates:
        # \b: "<li" must not match "<link", nor "<p" "<path".
        blocks = re.findall(rf"(?is)<(?:{TEXT_BLOCKS}|li)\b[^>]*>.*?</(?:{TEXT_BLOCKS}|li)>|<img\b[^>]*>", candidate)
        if not blocks:  # list items count only inside the chosen candidate
            blocks = re.findall(rf"(?is)<(?:{TEXT_BLOCKS})\b[^>]*>.*?</(?:{TEXT_BLOCKS})>", cleaned)
        if len(strip_html(" ".join(blocks))) >= 500:
            return IMG_TAG_RE.sub(lambda match: _article_image(match.group(0), base_url), "\n".join(blocks))
    return ""


def web_address(value: Any, needed: str) -> str:
    """An address as the owner typed it ("a.com/blog"), stripped, with https:// when it has no
    scheme. ValueError(needed) when it is empty."""
    address = str(value or "").strip()
    if not address:
        raise ValueError(needed)
    return address if "://" in address else f"https://{address}"


def origin_from_source(source_url: str, fallback: str) -> str:
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return fallback


def path_segments(url: str) -> List[str]:
    return [segment for segment in urllib.parse.urlparse(url).path.split("/") if segment]


# ---------------------------------------------------------------- RSS / Atom feeds


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
# The Telegram RSS bridge prefixes a media post's title: "[Photo] first words... [...]".
TELEGRAM_MEDIA_TAG_RE = re.compile(r"^\[[A-Z][A-Za-z ]{1,20}\]\s+(?=\S)")


def readable_title(title: str, url: Optional[str]) -> str:
    """A title that is only the URL's slug ("levers-in-the-brain") as words ("Levers in the brain").

    Some sites (Quartz/Obsidian gardens) put the file name in <title>. Only a hyphenated,
    lowercase title of two or more words, equal to the URL's last path segment, is touched.
    """
    candidate = (title or "").strip()
    if not SLUG_RE.match(candidate):
        return title
    # Two or more words with letters: a release tag ("2024-11-05", "2024-11-05-final") stays.
    if sum(1 for word in candidate.split("-") if any(ch.isalpha() for ch in word)) < 2:
        return title
    segments = path_segments(url or "")
    if not segments or urllib.parse.unquote(segments[-1]).lower() != candidate:
        return title
    words = candidate.replace("-", " ")
    return words[0].upper() + words[1:]


def strip_telegram_media_tag(title: str) -> str:
    """'[Photo] Text' -> 'Text'. A title that is only the tag ('[Photo]') is kept."""
    return TELEGRAM_MEDIA_TAG_RE.sub("", title or "", count=1)


def parse_feed_posts(feed_text: str, source_url: str) -> List[Dict[str, Any]]:
    """Parse an RSS 2.0 or Atom document into post drafts, newest first."""
    root = ET.fromstring(feed_text)
    posts: List[Dict[str, Any]] = []

    if local_name(root.tag) == "rss":
        channel = next((child for child in root if local_name(child.tag) == "channel"), None)
        items = [child for child in (channel if channel is not None else []) if local_name(child.tag) == "item"]
        for item in items:
            # <content:encoded> is the full article, <description> often only a summary.
            content_html = normalize_feed_urls(
                child_inner_xml(item, "encoded") or child_inner_xml(item, "description")
            )
            url = normalize_feed_urls(child_text(item, "link") or source_url)
            posts.append({
                "platform": "rss",
                "source": source_url,
                "url": url,
                "guid": child_text(item, "guid"),
                "title": readable_title(normalize_feed_urls(child_text(item, "title") or ""), url),
                "content": strip_html(content_html),
                "content_html": content_html,
                "date": parse_datetime_value(child_text(item, "pubDate") or child_text(item, "updated")),
                "media_urls": _extract_xml_media_urls(item, content_html),
                "categories": _extract_xml_categories(item),
                # <comments>: the item's discussion page (on Hacker News, the HN thread).
                "metadata": {"comments_url": comments} if (comments := child_text(item, "comments")) else {},
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
                "title": readable_title(normalize_feed_urls(child_text(entry, "title") or ""), url),
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
