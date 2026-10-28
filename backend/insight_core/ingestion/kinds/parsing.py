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


# Where a page says when it was last changed, in the order read (issue 0039).
MODIFIED_METAS = ("dcterms.modified", "article:modified_time", "og:updated_time", "last-modified")
JSON_LD_MODIFIED_RE = re.compile(r'"dateModified"\s*:\s*"([^"]+)"')


def page_modified(page: Optional[str]) -> Optional[str]:
    """When the page says it last changed (meta dcterms.modified, article:modified_time,
    og:updated_time, last-modified, then JSON-LD dateModified), as an ISO string so two reads
    compare equal; None when it says nothing readable. Only a page's head is needed."""
    json_ld = JSON_LD_MODIFIED_RE.search(page or "")
    for value in (*(meta_content(page, name) for name in MODIFIED_METAS), json_ld and json_ld.group(1)):
        if value and (date := parse_datetime_value(value.strip())) is not None:
            return date.isoformat()
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


# ---------------------------------------------------------------- the article reader
#
# extract_article_html / read_article_page: a page's article, as its text blocks and images
# in page order. Shared by full text, page watch, saved pages and five site adapters, and
# checked against a corpus of real pages (tests/fixtures/pages, issue 0032): every change
# here runs against every page there.
#
# 1. <script>, <style>, <noscript>, <iframe>, <svg>, <audio> and <video> go, with their
#    fallback text ("Your browser does not support the audio element").
# 2. Chrome goes, with everything inside it (_ChromeStripper): the CHROME_TAGS, and any
#    element (but <html> and <body>) with a class or id token that starts with one of the
#    prefixes, is one of the tokens, holds one of the parts (a table of contents, a badge),
#    names an author's box ("author-bio", "author-mini-bio"), or ends in "-tags",
#    "-categories" or "-newsletter" after a theme prefix ("nvidia-tags",
#    "uni-article-newsletter"). Only those endings are matched inside a token: a plugin wraps
#    whole articles in "has-highlight-and-share", WordPress gives <article> itself
#    "category-ai tag-agents", Substack's article is "newsletter-post". A component part
#    ("block__element") is judged on its own. A picture's dark-mode copy goes too; an
#    article's own <header> goes but keeps its images (the cover).
#    No rule drops an element holding more than half of the page's paragraph text: the Old
#    New Thing's posts are in "entry-content sharepostcontent".
# 3. The article is the first candidate long enough (<article>, <main>, a content class),
#    each read whole; with none, the smallest element holding most of the paragraph text
#    (ai.meta.com). Its text blocks (TEXT_BLOCKS and list items) and images are kept in page
#    order; an image keeps only its address and alt (_article_image), and pixels, icons,
#    badges and avatars go.
# 4. Its structure is kept, not only its words (_Structure, issue 0042): a data table as a
#    table (header cells, rows and columns, no attributes but colspan and rowspan), a figure
#    with its images and caption together. A table that lays out the page is unwrapped, its
#    blocks read like any others: one holding a heading or another table, marked
#    role="presentation", or with a single cell. Inside a table or a figure no tag keeps a
#    style or an event attribute. A heading with nothing under it goes: no text or image
#    before the next heading of a higher level, or the end (section titles whose content a
#    script fills in, a closing "Related" title). Not the next of the same level: a title
#    over a same-level subtitle or a note's title is no empty section (gov.uk, the
#    PostgreSQL docs; the before/after on 50 pages, issue 0042).
CHROME_TAGS = frozenset({"nav", "header", "footer", "aside", "form"})
CHROME_PREFIXES = ("nav", "menu", "footer", "related", "share", "subscribe", "sidebar",
                   "comments", "comment-", "ad-", "advert")
CHROME_ENDINGS = ("-tags", "_tags", "-categories", "_categories", "-newsletter", "_newsletter")
# A table of contents is a menu too (anthropic.com's "StickyTableOfContents-module__Trigger").
CHROME_PARTS = ("tableofcontents", "table-of-contents", "table_of_contents", "badge")
CHROME_TOKENS = frozenset({"toc", "newsletter", "ad", "ads"})
# The ending of a component part that is a share bar or a list of tags or topics.
PART_ENDINGS = ("-share", "_share", "-guides", "-topics") + CHROME_ENDINGS
DARK_COPY_PREFIX = "dark-mode"     # deepmind.google's <picture class="dark-mode-alternative">
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                       "param", "source", "track", "wbr"})
TEXT_BLOCKS = "h1|h2|h3|p|blockquote|pre"
# Blocks read whole up to their own end tag: a table's cells and a figure's caption hold <p>s.
STRUCTURE_BLOCKS = "table|figure|figcaption"
TABLE_PARTS = frozenset({"table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td"})
TABLE_WIDTHS = frozenset({"colgroup", "col"})      # column widths only: they go
CELL_ATTRS = ("colspan", "rowspan")
LAYOUT_ROLES = frozenset({"presentation", "none"})
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# A tag's attributes, quoted values and all: huggingface.co's class="max-md:[&>a]:hidden".
ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
MAIN_TEXT_SHARE = 0.5      # no chrome rule drops an element holding more of the paragraph text
FALLBACK_TEXT_SHARE = 0.8  # with no candidate, the smallest element holding this much of it
ARTICLE_MIN_CHARS = 500


def _is_chrome(tag: str, attrs: List[Tuple[str, Optional[str]]]) -> bool:
    if tag in CHROME_TAGS:
        return True
    if tag in ("html", "body"):
        return False
    tokens = " ".join(value or "" for name, value in attrs if name in ("class", "id")).lower().split()
    if tag in ("picture", "img") and any(token.startswith(DARK_COPY_PREFIX) for token in tokens):
        return True
    return any(_chrome_token(token) for token in tokens)


def _chrome_token(token: str) -> bool:
    if (token.startswith(CHROME_PREFIXES) or token.endswith(CHROME_ENDINGS) or token in CHROME_TOKENS
            or any(part in token for part in CHROME_PARTS)):
        return True
    # An author's box under the post: "author-bio" (9to5google, GitHub), "author-mini-bio" (Ars).
    if token.startswith("author") and token.endswith(("bio", "box")):
        return True
    # A component part ("block__element"): each part is judged on its own, so blog.google's
    # "article-share__title" and 9to5google's "article__meta-guides" go, while a whole-article
    # wrapper like "has-highlight-and-share" (no "__") stays. A bare "meta" part is no list:
    # blog.google keeps the standfirst in "uni-article-hero__meta-wrapper".
    parts = token.split("__")
    return len(parts) > 1 and any(part.startswith(CHROME_PREFIXES) or part.endswith(PART_ENDINGS) for part in parts)


class _ParagraphText(HTMLParser):
    """The page's elements and how much paragraph (<p>) text each holds. For the i-th non-void
    start tag, elements[i] is (tag, id, class), sizes[i] its paragraph characters and spans[i]
    its content's offsets in the page, nesting respected; total is the page's."""

    def __init__(self, html_text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.line_starts = [0] + [match.end() for match in re.finditer("\n", html_text)]
        self.elements: List[Tuple[str, str, str]] = []
        self.sizes: List[int] = []
        self.spans: List[Tuple[int, int]] = []
        self.open: List[Tuple[str, int, int]] = []     # (tag, index, paragraph chars before it)
        self.in_paragraph = 0
        self.total = 0
        self.feed(html_text)
        self.close()
        while self.open:                               # never closed: open to the end
            self._close_last(len(html_text))

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def _close_last(self, end: int) -> str:
        tag, index, before = self.open.pop()
        self.sizes[index] = self.total - before
        self.spans[index] = (self.spans[index][0], end)
        self.in_paragraph -= tag == "p"
        return tag

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in VOID_TAGS:
            return
        self.open.append((tag, len(self.sizes), self.total))
        names = dict(attrs)
        self.elements.append((tag, (names.get("id") or "").strip(), (names.get("class") or "").lower()))
        self.sizes.append(0)
        self.spans.append((self._offset() + len(self.get_starttag_text() or ""), 0))
        self.in_paragraph += tag == "p"

    def handle_endtag(self, tag: str) -> None:
        if any(open_tag == tag for open_tag, _, _ in self.open):
            end = self._offset()
            while self._close_last(end) != tag:  # closes it and whatever was left open inside it
                pass

    def handle_data(self, data: str) -> None:
        if self.in_paragraph:
            self.total += len(data.strip())


class _ChromeStripper(HTMLParser):
    """Re-emits the page without its chrome. Regex can't find where a nested element ends:
    `dropping` is the stack of elements open inside the dropped one. `protected` are the
    start tags (by order) of the elements holding most of the paragraph text. An article's
    own <header> goes but keeps its images: the cover of anthropic.com's and NVIDIA's posts."""

    def __init__(self, protected: frozenset) -> None:
        super().__init__(convert_charrefs=False)
        self.kept: List[str] = []
        self.dropping: List[str] = []
        self.protected = protected
        self.started = 0
        self.articles = 0               # <article> elements open (and kept)
        self.dropping_keeps_images = False

    def _keep(self, text: str) -> None:
        if not self.dropping:
            self.kept.append(text)

    def _image(self, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if not _is_chrome("img", attrs) and (not self.dropping or self.dropping_keeps_images):
            self.kept.append(self.get_starttag_text() or "")

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in VOID_TAGS:
            if tag == "img":
                self._image(attrs)
            else:
                self._keep(self.get_starttag_text() or "")
            return
        index, self.started = self.started, self.started + 1
        if self.dropping:
            self.dropping.append(tag)
        elif _is_chrome(tag, attrs) and index not in self.protected:
            self.dropping.append(tag)
            self.dropping_keeps_images = tag == "header" and self.articles > 0
        else:
            self.articles += tag == "article"
            self._keep(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "img":
            self._image(attrs)
        else:
            self._keep(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if not self.dropping:
            self.kept.append(f"</{tag}>")
            self.articles -= tag == "article" and self.articles > 0
        elif tag in self.dropping:  # closes it and whatever was left open inside it
            del self.dropping[len(self.dropping) - 1 - self.dropping[::-1].index(tag):]

    def handle_data(self, data: str) -> None:
        self._keep(data)

    def handle_entityref(self, name: str) -> None:
        self._keep(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._keep(f"&#{name};")


def _without_chrome(html_text: str) -> str:
    text = _ParagraphText(html_text)
    protected = frozenset(index for index, size in enumerate(text.sizes) if size > text.total * MAIN_TEXT_SHARE)
    stripper = _ChromeStripper(protected)
    stripper.feed(html_text)
    stripper.close()
    return "".join(stripper.kept)


def _tag(tag: str, attrs: List[Tuple[str, Optional[str]]]) -> str:
    """A start tag rebuilt from its attributes, without styles and event handlers."""
    kept = "".join(f' {name}="{html_lib.escape(value or "")}"' for name, value in attrs
                   if name != "style" and not name.startswith("on"))
    return f"<{tag}{kept}>"


class _Structure(HTMLParser):
    """Re-emits the article with its tables and figures as the reader keeps them (step 4).
    A table is judged when it closes: `tables` are the open ones, each with the positions in
    `kept` of its own parts (kept without attributes but CELL_ATTRS), emptied then when it
    lays out the page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.kept: List[str] = []
        self.tables: List[Dict[str, Any]] = []
        self.figures = 0

    def _keep(self, text: str) -> None:
        self.kept.append(text)

    def _starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> str:
        if self.tables or self.figures:
            return _tag(tag, attrs)
        return self.get_starttag_text() or ""

    def _part(self, text: str) -> None:
        """One of the innermost open table's own parts, judged when the table closes."""
        self.tables[-1]["parts"].append(len(self.kept))
        self.kept.append(text)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "table":
            for table in self.tables:   # a table holding a table lays it out
                table["layout"] = True
            role = (dict(attrs).get("role") or "").strip().lower()
            self.tables.append({"parts": [], "layout": role in LAYOUT_ROLES, "cells": 0})
            self._part("<table>")
        elif self.tables and tag in TABLE_PARTS:
            self.tables[-1]["cells"] += tag in ("th", "td")
            spans = "".join(f' {name}="{(value or "").strip()}"' for name, value in attrs
                            if name in CELL_ATTRS and (value or "").strip().isdigit())
            self._part(f"<{tag}{spans}>")
        elif self.tables and tag in TABLE_WIDTHS:
            pass
        elif tag == "figure":
            self._keep("" if self.figures else "<figure>")   # a figure in a figure is one figure
            self.figures += 1
        elif tag == "figcaption":
            self._keep("<figcaption>")
        else:
            if tag in HEADING_TAGS:
                for table in self.tables:
                    table["layout"] = True
            self._keep(self._starttag(tag, attrs))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if not (self.tables and tag in TABLE_WIDTHS):
            self._keep(self._starttag(tag, attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self.tables:
                self._part("</table>")
                self._close_table()
        elif self.tables and tag in TABLE_PARTS:
            self._part(f"</{tag}>")
        elif self.tables and tag in TABLE_WIDTHS:
            pass
        elif tag == "figure":
            if self.figures:
                self.figures -= 1
                self._keep("" if self.figures else "</figure>")
        else:
            self._keep(f"</{tag}>")

    def _close_table(self) -> None:
        table = self.tables.pop()
        layout = table["layout"] or table["cells"] < 2
        for index in table["parts"] if layout else ():
            self.kept[index] = ""

    def close(self) -> None:
        super().close()
        while self.tables:              # never closed: no table
            self.tables[-1]["layout"] = True
            self._close_table()
        self.kept.append("</figure>" if self.figures else "")

    def handle_data(self, data: str) -> None:
        self._keep(data)

    def handle_entityref(self, name: str) -> None:
        self._keep(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._keep(f"&#{name};")


def _with_structure(html_text: str) -> str:
    structure = _Structure()
    structure.feed(html_text)
    structure.close()
    return "".join(structure.kept)


CONTENT_CLASSES = ("entry-content", "post-content", "article-content", "content-body", "prose", "single-post-content")
CANDIDATES = (
    lambda tag, id_, classes: tag == "article",
    lambda tag, id_, classes: tag == "main",
    lambda tag, id_, classes: tag == "div" and id_ == "markdownBody",
    lambda tag, id_, classes: tag == "div" and any(name in classes for name in CONTENT_CLASSES),
)


def _candidates(html_text: str) -> List[str]:
    """What may be the article, in this order: the page's first <article>, its first <main>,
    #markdownBody, the first <div> with a CONTENT_CLASSES class, each whole (a card nested in
    the post no longer ends it). With none, the smallest element holding FALLBACK_TEXT_SHARE
    of the paragraph text (the whole page when it has none)."""
    page = _ParagraphText(html_text)
    found = [next((i for i, element in enumerate(page.elements) if test(*element)), None) for test in CANDIDATES]
    if any(index is not None for index in found):
        return [html_text[slice(*page.spans[index])] for index in found if index is not None]
    spans = [span for size, span in zip(page.sizes, page.spans)
             if page.total and size >= page.total * FALLBACK_TEXT_SHARE]
    start, end = min(spans, key=lambda span: span[1] - span[0], default=(0, len(html_text)))
    return [html_text[start:end]]


IMG_TAG_RE = re.compile(rf"(?is)<img\b{ATTRS}>")
IMG_ATTR_RE = re.compile(r"""(?is)\b(src|data-src|data-lazy-src|data-original|srcset|data-srcset|alt|width|height|class)"""
                         r"""\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
# Where an <img> keeps its address, in this order: a lazy image's real one first; a srcset's
# first candidate last (an image known only by its srcset).
IMAGE_ADDRESSES = ("data-src", "data-lazy-src", "data-original", "src", "srcset", "data-srcset")
ICON_MAX_PX = 64           # an image this wide or high is an icon, an avatar or a badge


def _px(value: Optional[str]) -> Optional[int]:
    match = re.match(r"\s*(\d+)", value or "")
    return int(match.group(1)) if match else None


def _image_attrs(tag: str) -> Dict[str, str]:
    return {name.lower(): html_lib.unescape(dq or sq or bare) for name, dq, sq, bare in IMG_ATTR_RE.findall(tag)}


def _is_article_image(attrs: Dict[str, str]) -> bool:
    """Not a tracking pixel, an icon, a badge or an avatar."""
    sizes = [px for px in (_px(attrs.get("width")), _px(attrs.get("height"))) if px is not None]
    if any(px <= ICON_MAX_PX for px in sizes):
        return False
    return not (any(token.startswith("avatar") for token in attrs.get("class", "").lower().split())
                or attrs.get("alt", "").lower().endswith("avatar"))


def _image_address(attrs: Dict[str, str]) -> str:
    """The image's address (IMAGE_ADDRESSES), '' when it has none but a data: placeholder."""
    for name in IMAGE_ADDRESSES:
        value = (attrs.get(name) or "").strip()
        if name.endswith("srcset"):
            value = value.split(",")[0].strip().split(" ")[0]
        if value and not value.startswith("data:"):
            return value
    return ""


def _article_image(tag: str, base_url: str) -> str:
    """An <img> as an article keeps it: its real address (_image_address; Next.js's
    /_next/image?url= unwrapped; made absolute against base_url) and its alt. '' for an image
    that is no article image (_is_article_image) or whose address can't be fetched."""
    attrs = _image_attrs(tag)
    if not _is_article_image(attrs):
        return ""
    src = _image_address(attrs)
    if not src:
        return ""
    if urllib.parse.urlparse(src).path.endswith("/_next/image"):
        src = (urllib.parse.parse_qs(urllib.parse.urlparse(src).query).get("url") or [src])[0]
    src = urllib.parse.urljoin(base_url, src) if base_url else src
    if not src.startswith(("http://", "https://")):
        return ""
    return f'<img src="{html_lib.escape(src)}" alt="{html_lib.escape(attrs.get("alt", ""))}">'


# \b: "<li" must not match "<link", nor "<p" "<path". A structure block (a table, a figure,
# a caption) first, read up to its own end tag.
BLOCK_RE = re.compile(rf"(?is)<(?P<block>{STRUCTURE_BLOCKS})\b{ATTRS}>.*?</(?P=block)>"
                      rf"|<(?:{TEXT_BLOCKS}|li)\b{ATTRS}>.*?</(?:{TEXT_BLOCKS}|li)>|<img\b{ATTRS}>")
PAGE_BLOCK_RE = re.compile(rf"(?is)<(?:{TEXT_BLOCKS}|figcaption)\b{ATTRS}>.*?</(?:{TEXT_BLOCKS}|figcaption)>")
HEADING_RE = re.compile(r"(?is)<h([1-6])\b")
# A figure left with no text and no image (its only image had no address it could keep).
EMPTY_FIGURE_RE = re.compile(r"(?is)\n?<figure>(?:\s|<(?!img\b)[^>]*>)*</figure>")
TAG_RE = re.compile(rf"<[a-zA-Z]{ATTRS}>")
QUOTED_RE = re.compile(r""""[^"]*"|'[^']*'""")
SHORT_OPENING_CHARS = 25   # a first block shorter than this is a hint of chrome left in ("Share:")


def _escaped_attributes(html: str) -> str:
    """A "<" or ">" inside an attribute value as an entity, so no later reader takes it for
    the tag's end (strip_html, the post's text)."""
    return TAG_RE.sub(lambda tag: QUOTED_RE.sub(
        lambda value: value.group(0).replace("<", "&lt;").replace(">", "&gt;"), tag.group(0)), html)


def _blocks(html_text: str) -> List[str]:
    """The article's blocks in page order (BLOCK_RE); a figure as its own blocks inside one
    <figure>, gone when it holds none."""
    blocks = []
    for match in BLOCK_RE.finditer(html_text):
        block = match.group(0)
        if match.group("block") == "figure":
            inner = [part.group(0) for part in BLOCK_RE.finditer(block[len("<figure>"):-len("</figure>")])]
            if not inner:
                continue
            block = "<figure>" + "".join(inner) + "</figure>"
        blocks.append(block)
    return blocks


def _with_headings_over_content(blocks: List[str]) -> List[str]:
    """The blocks without a heading that has nothing under it: no block with text or an image
    before the next heading of a higher level, or the end (step 4). Read from the end,
    `content[level]` says whether such a block comes before the next heading above that level."""
    content = [False] * 7
    kept: List[str] = []
    for block in reversed(blocks):
        heading = HEADING_RE.match(block)
        if not heading:
            if strip_html(block).strip() or "<img" in block.lower():
                content = [True] * 7
            kept.append(block)
            continue
        level = int(heading.group(1))
        if content[level]:
            kept.append(block)
        content[level + 1:] = [False] * (6 - level)
    return kept[::-1]


def read_article_page(html_text: str, base_url: str = "") -> Tuple[str, Dict[str, Any]]:
    """(the article's html, its reading fidelity). The html is extract_article_html's; the
    fidelity (read_fidelity) is {} when no article was found."""
    cleaned = re.sub(r"(?is)<(script|style|noscript|iframe|svg|audio|video)\b.*?</\1>", "", html_text or "")
    cleaned = _without_chrome(cleaned)
    # The first candidate long enough to be the article: a page's first <article> can be a
    # 4-word "related" card while the post is in <main> (deepmind.google, 2026-10-27). The
    # main block only when no candidate matched: a short <article> is no article, not a reason
    # to read the page's other lists as one (issue 0029).
    for candidate in _candidates(cleaned):
        blocks = _blocks(_with_structure(candidate))
        if not blocks:  # list items count only inside the chosen candidate
            blocks = PAGE_BLOCK_RE.findall(cleaned)
        blocks = _with_headings_over_content(blocks)
        if len(strip_html(" ".join(blocks))) >= ARTICLE_MIN_CHARS:
            html = IMG_TAG_RE.sub(lambda match: _article_image(match.group(0), base_url), "\n".join(blocks))
            html = EMPTY_FIGURE_RE.sub("", _escaped_attributes(html))
            return html, read_fidelity(blocks, html)
    return "", {}


def extract_article_html(html_text: str, base_url: str = "") -> str:
    """The article's text blocks and images, in page order. base_url (the page's address)
    makes relative image addresses absolute; without it they are left out."""
    return read_article_page(html_text, base_url)[0]


def read_fidelity(blocks: List[str], html: str) -> Dict[str, Any]:
    """How well a page was read, kept in a post's metadata (repo_posts.PAGE_READ_KEY):
      page_images    the article images in the chosen article block (no pixel, icon or
                     avatar): an estimate of what the site shows, from the block the reader
                     chose, so related cards and sidebars it dropped never count
      kept_images    the images kept: the others had no address the reader could fetch
                     (a lazy image's placeholder, an image known only by its srcset)
      text_chars     the kept text's length
      short_opening  the first block after the title is under SHORT_OPENING_CHARS: a hint of
                     chrome left in ("Share:", "Category")."""
    page_images = sum(1 for tag in IMG_TAG_RE.findall("\n".join(blocks))
                      if _is_article_image(attrs := _image_attrs(tag)) and _image_address(attrs))
    texts = [text for block in blocks if block[:4].lower() != "<img" and not re.match(r"(?is)<h1\b", block)
             if (text := " ".join(strip_html(block).split()))]
    return {
        "page_images": page_images,
        "kept_images": len(re.findall(r"<img\b", html)),
        "text_chars": len(strip_html(html)),
        "short_opening": bool(texts) and len(texts[0]) < SHORT_OPENING_CHARS,
    }


LOST_IMAGES_MIN = 3        # a page "lost most of its images" with at least this many, under half kept


def lost_most_images(fidelity: Any) -> bool:
    """The page had at least LOST_IMAGES_MIN article images and under half were kept."""
    if not isinstance(fidelity, dict):
        return False
    page, kept = int(fidelity.get("page_images") or 0), int(fidelity.get("kept_images") or 0)
    return page >= LOST_IMAGES_MIN and kept * 2 < page


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
