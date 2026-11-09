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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from insight_core.utils.addresses import host_of, publication_of, same_site
from insight_core.utils.content_fingerprints import strip_html
from insight_core.utils.media import clean_url
from insight_core.utils.titles import title_key
from insight_core.utils.url_normalization import normalize_url

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


MOVED_TAG_RE = re.compile(r"(?is)<(meta|link)\b([^>]*)>")
MOVED_ATTR_RE = re.compile(r"""(?s)([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
REFRESH_URL_RE = re.compile(r"""(?is)^\s*\d*(?:\.\d*)?\s*[;,]?\s*url\s*=\s*['"]?([^'"]+)""")


def moved_to(page: Optional[str], url: str) -> Optional[str]:
    """Where a page says it now is (issue 0108), absolute: its meta refresh's address, else its
    <link rel="canonical"> when that is another address (by normalize_url). None when it names none,
    names itself, or only a script moves the reader (a `location=` script is never followed)."""
    refresh = canonical = None
    for tag, attributes in MOVED_TAG_RE.findall((page or "")[:200_000]):
        values: Dict[str, str] = {}
        for name, double, single, bare in MOVED_ATTR_RE.findall(attributes):
            values.setdefault(name.lower(), double or single or bare)
        if tag.lower() == "meta" and values.get("http-equiv", "").lower() == "refresh" and refresh is None:
            found = REFRESH_URL_RE.match(html_lib.unescape(values.get("content", "")))
            refresh = found.group(1).strip() if found else None
        elif tag.lower() == "link" and "canonical" in values.get("rel", "").lower().split() and canonical is None:
            canonical = html_lib.unescape(values.get("href", "")).strip() or None
    here = normalize_url(url)
    for candidate in (refresh, canonical):
        if not candidate:
            continue
        try:
            target = urllib.parse.urldefrag(urllib.parse.urljoin(url, candidate))[0]
        except ValueError:
            continue
        if urllib.parse.urlparse(target).scheme in ("http", "https") and normalize_url(target) not in (None, here):
            return target
    return None


def page_addresses(page: Optional[str], url: str) -> set:
    """The addresses a page says it is (issue 0140), normalized: its <link rel="canonical"> and its og:url."""
    found = set()
    for tag, attributes in MOVED_TAG_RE.findall((page or "")[:200_000]):
        values: Dict[str, str] = {}
        for name, double, single, bare in MOVED_ATTR_RE.findall(attributes):
            values.setdefault(name.lower(), double or single or bare)
        if tag.lower() == "link" and "canonical" in values.get("rel", "").lower().split():
            candidate = values.get("href", "")
        elif tag.lower() == "meta" and values.get("property", values.get("name", "")).lower() == "og:url":
            candidate = values.get("content", "")
        else:
            continue
        try:
            normalized = normalize_url(urllib.parse.urljoin(url, html_lib.unescape(candidate).strip()))
        except ValueError:
            continue
        if normalized:
            found.add(normalized)
    return found


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


_TIME_OF_DAY_RE = re.compile(r"\d{1,2}:\d{2}")


def date_precision(value: Optional[str]) -> Optional[str]:
    """What a source's date says (issue 0076, posts.published_precision): "none" when it says no date,
    "date" when it has no time of day ("2026-11-03"); else None: the saver tells it by its time (a date
    alone is stored as 00:00:00 UTC)."""
    if parse_datetime_value(value) is None:
        return "none"
    return None if _TIME_OF_DAY_RE.search(value or "") else "date"


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
#    fallback text ("Your browser does not support the audio element"). Text outside any
#    block is made readable (_LooseText, issue 0053): runs of loose text an element breaks
#    with double <br>s become paragraphs (paulgraham.com's table cell, incompleteideas.net's
#    <body>), and a <code> standing alone (several lines, or in a <figure>) a code block
#    (fasterthanli.me).
#    A link's label for screen readers goes (_without_hidden_link_labels, issue 0063): an
#    element a link hides from the eye ("(opens in a new window)" after its words), read from
#    how it is hidden (_visually_hidden: a screen-reader class, an inline clip to nothing),
#    when the link shows words of its own. Hidden text anywhere else stays: it stands for
#    something the reader drops (a chart's "66 %", a comparison table's "No TrueDepth camera
#    system" under an icon), and an icon-only link keeps its hidden name.
# 2. Chrome goes, with everything inside it (_ChromeStripper): the CHROME_TAGS, and any
#    element (but <html> and <body>) with a class or id token that starts with one of the
#    prefixes, is one of the tokens, holds one of the parts (a table of contents, a badge),
#    names an author's box ("author-bio", "author-mini-bio"), or ends in "-tags",
#    "-categories", "-newsletter" or "-nav" after a theme prefix ("nvidia-tags",
#    "uni-article-newsletter", "bottom-nav"). Only those endings are matched inside a token: a plugin wraps
#    whole articles in "has-highlight-and-share", WordPress gives <article> itself
#    "category-ai tag-agents", Substack's article is "newsletter-post". A component part
#    ("block__element") is judged on its own. A picture's dark-mode copy goes too; an
#    article's own <header> goes but keeps its images (the cover).
#    No rule drops an element holding more than half of the page's paragraph text (the Old
#    New Thing's posts are in "entry-content sharepostcontent"), nor one around a candidate
#    article holding a fifth of it (lesswrong.com's "MultiToCLayout-tableOfContents").
# 3. The article is the first candidate long enough (<article>, <main>, a content class),
#    each read whole; with none, the smallest element holding most of the paragraph text
#    (ai.meta.com). Its text blocks (TEXT_BLOCKS and list items) and images are kept in page
#    order; an image keeps only its address and alt (_article_image), and pixels, icons,
#    badges and avatars go. The notes it links to that follow it outside it are read after
#    it (_notes_after: blog.google's footnotes).
# 4. Its structure is kept, not only its words (_Structure, issue 0042): a data table as a
#    table (header cells, rows and columns, no attributes but colspan and rowspan), a figure
#    with its images and caption together. A table that lays out the page is unwrapped, its
#    blocks read like any others: one holding a heading or another table, marked
#    role="presentation", or with a single cell. Inside a table or a figure no tag keeps a
#    style or an event attribute. A heading with nothing under it goes: no text or image
#    before the next heading of a higher level, or the end (section titles whose content a
#    script fills in, a closing "Related" title). Not the next of the same level: a title
#    over a same-level subtitle or a note's title is no empty section (gov.uk, the
#    PostgreSQL docs; the before/after on 50 pages, issue 0042). A table with no word in it
#    goes; a text block inside a link (a card) is marked so step 5 reads it as a link.
# 5. The chrome at its edges goes (_without_edge_chrome, issue 0053), judged by links and
#    length the way Readability judges unnamed blocks: labels, in-site links and the title
#    again before the first paragraph; a tail of links with its labels, card pictures and
#    excerpts after the last one.
CHROME_TAGS = frozenset({"nav", "header", "footer", "aside", "form"})
CHROME_PREFIXES = ("nav", "menu", "footer", "related", "share", "subscribe", "sidebar",
                   "comments", "comment-", "ad-", "advert")
CHROME_ENDINGS = ("-tags", "_tags", "-categories", "_categories", "-newsletter", "_newsletter", "-nav", "_nav")
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
# The reader's values were measured together on the page corpus (0032: 93 -> 113 of 123 checks;
# 0053: 367 -> 404 of 420), never one value against another: "not measured" below means that.
MAIN_TEXT_SHARE = 0.5      # no chrome rule drops an element holding more of the paragraph text
FALLBACK_TEXT_SHARE = 0.8  # with no candidate, the smallest element holding this much of it
CANDIDATE_TEXT_SHARE = 0.2 # nor one around a candidate article holding this much of it
ARTICLE_MIN_CHARS = 500    # not measured


# How a page hides text from the eye but not from a screen reader (issue 0063), never a
# responsive or script toggle ("hidden", "md:sr-only", "not-sr-only": that text shows). A class token,
# lower-cased, its "-" and "_" removed, that holds one of SCREEN_READER_PARTS (Bootstrap's and
# Drupal's visually-hidden, WordPress's screen-reader-text, h5bp's visuallyhidden, GOV.UK's
# govuk-visually-hidden), or ends in "sronly" (Tailwind's and Bootstrap 4's sr-only, a plugin's
# "wt-cli-sr-only"). A token with a ":" is a breakpoint or state variant, shown somewhere.
SCREEN_READER_PARTS = ("visuallyhidden", "hiddenvisually", "screenreader")
SCREEN_READER_ENDING = "sronly"
# An inline clip to nothing: clip: rect(0 0 0 0) or rect(1px, 1px, 1px, 1px), clip-path: inset(50%).
CLIPPED_RE = re.compile(r"(?i)(?<![-\w])clip\s*:\s*rect\(\s*(?:[01](?:px)?[\s,]*){4}\)"
                        r"|clip-path\s*:\s*inset\(\s*(?:50|100)%\s*\)")


def _visually_hidden(attrs: List[Tuple[str, Optional[str]]]) -> bool:
    """Whether the element hides its text from the eye for screen readers: a screen-reader
    class (none undone by a "not-sr-only" at some breakpoint) or an inline clip to nothing."""
    for name, value in attrs:
        if name == "class":
            tokens = [token.replace("-", "").replace("_", "") for token in (value or "").lower().split()]
            if any("notsronly" in token for token in tokens):
                return False
            if any(":" not in token and (token.endswith(SCREEN_READER_ENDING)
                                         or any(part in token for part in SCREEN_READER_PARTS))
                   for token in tokens):
                return True
        elif name == "style" and value and CLIPPED_RE.search(value):
            return True
    return False


HIDDEN_HINT_RE = re.compile(r"(?i)sr[-_]?only|hidden|screen[-_]?reader|clip")


class _HiddenParts(HTMLParser):
    """A link's inner html re-emitted without its visually hidden elements (kept), the text
    left showing (shown) and how many went (dropped)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.kept: List[str] = []
        self.shown: List[str] = []
        self.dropping: List[str] = []
        self.dropped = 0

    def _keep(self, text: str, shown: str = "") -> None:
        if not self.dropping:
            self.kept.append(text)
            self.shown.append(shown)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        text = self.get_starttag_text() or ""
        if tag in VOID_TAGS:
            self._keep(text)
        elif self.dropping:
            self.dropping.append(tag)
        elif _visually_hidden(attrs):
            self.dropping.append(tag)
            self.dropped += 1
        else:
            self.kept.append(text)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._keep(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if not self.dropping:
            self.kept.append(f"</{tag}>")
        elif tag in self.dropping:  # closes it and whatever was left open inside it
            del self.dropping[len(self.dropping) - 1 - self.dropping[::-1].index(tag):]

    def handle_data(self, data: str) -> None:
        self._keep(data, data)

    def handle_entityref(self, name: str) -> None:
        self._keep(f"&{name};", "&")

    def handle_charref(self, name: str) -> None:
        self._keep(f"&#{name};", "#")


def _without_hidden_link_labels(html_text: str) -> str:
    """The page with the visually hidden elements of each link that shows words of its own
    taken out (see step 1)."""
    def mend(match: "re.Match[str]") -> str:
        inner = match.group("text")
        if not HIDDEN_HINT_RE.search(inner):
            return match.group(0)
        parts = _HiddenParts()
        parts.feed(inner)
        parts.close()
        if not parts.dropped or not "".join(parts.shown).strip():
            return match.group(0)
        start, end = match.start("text") - match.start(), match.end("text") - match.start()
        whole = match.group(0)
        return whole[:start] + "".join(parts.kept) + whole[end:]
    return LINK_RE.sub(mend, html_text)


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


# Tags that flow inside a line of text: a loose run is made of them and its text (step 1).
INLINE_TAGS = frozenset({"a", "abbr", "b", "bdi", "bdo", "big", "cite", "code", "data", "del", "dfn", "em",
                         "font", "i", "ins", "kbd", "mark", "q", "s", "samp", "small", "span", "strike",
                         "strong", "sub", "sup", "time", "tt", "u", "var", "wbr", "br", "img"})
# Inside these loose text is already read (a text block, a caption, a form's controls) or
# never is (the head): no run in them is made into a paragraph (step 1).
TEXT_HOLDERS = frozenset({"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "figcaption",
                          "caption", "dt", "dd", "button", "label", "select", "option", "textarea", "title",
                          "head", "map"})
# Elements whose own text is only the space between their children.
TEXTLESS = frozenset({"ul", "ol", "dl", "table", "thead", "tbody", "tfoot", "tr", "picture", "colgroup"})


class _LooseText(HTMLParser):
    """Re-emits the page with the text it holds outside any block made readable (step 1).

    - Loose text: a page laid out with <br>s and no <p> (paulgraham.com in a table cell,
      incompleteideas.net in <body>) keeps its words in an element's own runs of text. In an
      element that breaks them with a double <br>, each run (its text and inline tags, up to a
      double <br> or a block) becomes a <p>; an inline tag the run does not both open and close
      (a <font> around the whole page) is left out of it. An element with no double <br> is left
      as it is: a byline or a date in a <div> is no paragraph.
    - A code block with no <pre>: a <code> outside any text block that runs over several lines,
      or stands in a <figure> (fasterthanli.me's <figure><code>), becomes <pre><code>.
    A first pass (measure=True) finds `breaks`, the elements (by start order) whose own runs
    hold a double <br>, and `code_blocks`, the <code>s to read as blocks; the second re-emits."""

    def __init__(self, measure: bool, breaks: frozenset = frozenset(), code_blocks: frozenset = frozenset()) -> None:
        super().__init__(convert_charrefs=False)
        self.measure = measure
        self.breaks, self.code_blocks = breaks, code_blocks
        self.found_breaks: set = set()
        self.found_code: set = set()
        self.kept: List[str] = []
        self.open: List[Tuple[str, int]] = []     # (tag, start order) of the open elements
        self.started = 0
        self.run: List[Tuple[str, str]] = []      # the current run: (start|end|text, its html)
        self.run_owner = -1                       # the element whose run it is
        self.last_br = False                      # the run's last token was a <br> (or whitespace after one)
        self.codes: List[Tuple[int, bool, List[str]]] = []   # open <code>s: (order, alone, its text)

    def _owner(self) -> Tuple[str, int]:
        """The innermost open element that is no inline tag, or the page itself."""
        for tag, order in reversed(self.open):
            if tag not in INLINE_TAGS or order in self.code_blocks:
                return tag, order
        return "", -1

    def _in_text_block(self) -> bool:
        return (any(tag in TEXT_HOLDERS or order in self.code_blocks for tag, order in self.open)
                or self._owner()[0] in TEXTLESS)

    def _emit(self, value: str) -> None:
        if not self.measure:
            self.kept.append(value)

    def _flush(self) -> None:
        run, self.run, self.last_br = self.run, [], False
        if self.measure or not run:
            return
        if self.run_owner not in self.breaks or not "".join(v for kind, v in run if kind == "text").strip():
            self.kept.extend(value for _, value in run)
            return
        opened: List[Tuple[str, int]] = []    # only the inline tags the run both opens and closes
        keep = [True] * len(run)
        for index, (kind, value) in enumerate(run):
            if kind == "text":
                continue
            name = re.match(r"</?\s*([a-zA-Z0-9-]+)", value).group(1).lower()
            if kind == "start" and name not in VOID_TAGS:
                opened.append((name, index))
            elif kind == "end":
                match = next((i for i in range(len(opened) - 1, -1, -1) if opened[i][0] == name), None)
                if match is None:
                    keep[index] = False
                else:
                    del opened[match:]
        for _, index in opened:
            keep[index] = False
        body = "".join(value for (_, value), kept in zip(run, keep) if kept)
        body = re.sub(r"(?is)^(?:\s|<br\b[^>]*>)+|(?:\s|<br\b[^>]*>)+$", "", body)
        self.kept.append(f"<p>{body}</p>")

    def _inline(self, kind: str, value: str) -> None:
        if self._in_text_block():
            self._flush()
            self._emit(value)
            return
        owner = self._owner()[1]
        if owner != self.run_owner:
            self._flush()
            self.run_owner = owner
        self.run.append((kind, value))

    def _block(self, value: str) -> None:
        self._flush()
        self._emit(value)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        text = self.get_starttag_text() or ""
        if tag == "br" and not self._in_text_block():
            owner = self._owner()[1]
            if self.last_br and owner == self.run_owner:     # a double <br>: the run ends
                self.found_breaks.add(owner)
                self._flush()
                self.run_owner = owner
                return
            self._inline("start", text)
            self.last_br = True
            return
        if tag in VOID_TAGS:
            if tag in INLINE_TAGS:
                self._inline("start", text)
            else:
                self._block(text)
            return
        order, self.started = self.started, self.started + 1
        if tag == "code":
            alone = not self._in_text_block()
            self.codes.append((order, alone, []))
            if alone and self._owner()[0] == "figure":
                self.found_code.add(order)
        if order in self.code_blocks:
            self._block("<pre>" + text)
        elif tag in INLINE_TAGS:
            self._inline("start", text)
        else:
            self._block(text)
        self.open.append((tag, order))
        self.last_br = False

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.open and self.open[-1][0] == tag:
            self.open.pop()

    def handle_endtag(self, tag: str) -> None:
        if not any(open_tag == tag for open_tag, _ in self.open):
            return                                   # a stray end tag
        while self.open:                             # closes it and whatever was left open inside it
            open_tag, order = self.open[-1]
            if open_tag == "code" and self.codes:
                code_order, alone, text = self.codes.pop()
                if alone and "\n" in "".join(text).strip():
                    self.found_code.add(code_order)
            if order in self.code_blocks:
                self.open.pop()
                self._block(f"</{open_tag}></pre>")
            elif open_tag in INLINE_TAGS:
                self._inline("end", f"</{open_tag}>")
                self.open.pop()
            else:
                self.open.pop()
                self._block(f"</{open_tag}>")
            if open_tag == tag:
                break
        self.last_br = False

    def handle_data(self, data: str) -> None:
        if self.codes:
            self.codes[-1][2].append(data)
        self._inline("text", data)
        if data.strip():
            self.last_br = False

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def close(self) -> None:
        super().close()
        self._flush()


def _with_loose_text(html_text: str) -> str:
    """The page with its loose text as paragraphs and its lone <code>s as code blocks
    (_LooseText); the page itself when it has neither."""
    measure = _LooseText(measure=True)
    measure.feed(html_text)
    measure.close()
    if not measure.found_breaks and not measure.found_code:
        return html_text
    loose = _LooseText(measure=False, breaks=frozenset(measure.found_breaks),
                       code_blocks=frozenset(measure.found_code))
    loose.feed(html_text)
    loose.close()
    return "".join(loose.kept)


def _without_chrome(html_text: str) -> str:
    """The page without its chrome (_ChromeStripper). Protected: an element holding most of
    the paragraph text, and every element around a candidate article (CANDIDATES) holding at
    least CANDIDATE_TEXT_SHARE of it: lesswrong.com lays its post out inside a grid named
    "MultiToCLayout-tableOfContents", and its comments hold three quarters of the page's text."""
    text = _ParagraphText(html_text)
    protected = {index for index, size in enumerate(text.sizes) if size > text.total * MAIN_TEXT_SHARE}
    for index, (element, size) in enumerate(zip(text.elements, text.sizes)):
        if size >= text.total * CANDIDATE_TEXT_SHARE and any(test(*element) for test in CANDIDATES):
            start, end = text.spans[index]
            protected.update(outer for outer in range(index) if text.spans[outer][0] <= start and end <= text.spans[outer][1])
    protected = frozenset(protected)
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
        self.open: List[str] = []                 # the open elements' tags
        self.links: List[Tuple[str, int]] = []    # open <a>s around blocks: (href, depth)

    def _keep(self, text: str) -> None:
        self.kept.append(text)

    def _card_mark(self, text: str, tag: str) -> str:
        """A text block that starts inside a link (a card: <a><img><h2>Title</h2></a>) carries
        the link's address in CARD_MARK, so the edge rule reads it as a link (step 5)."""
        if not self.links or tag not in CARD_BLOCKS or not text.endswith(">"):
            return text
        end = -2 if text.endswith("/>") else -1
        return f'{text[:end]} {CARD_MARK}="{html_lib.escape(self.links[-1][0])}"{text[end:]}'

    def _starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> str:
        if self.tables or self.figures:
            return _tag(tag, attrs)
        return self.get_starttag_text() or ""

    def _part(self, text: str) -> None:
        """One of the innermost open table's own parts, judged when the table closes."""
        self.tables[-1]["parts"].append(len(self.kept))
        self.kept.append(text)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag not in VOID_TAGS:
            self.open.append(tag)
        if tag == "a" and (href := (dict(attrs).get("href") or "").strip()):
            self.links.append((href, len(self.open)))
        if tag == "table":
            for table in self.tables:   # a table holding a table lays it out
                table["layout"] = True
            role = (dict(attrs).get("role") or "").strip().lower()
            self.tables.append({"parts": [], "layout": role in LAYOUT_ROLES, "cells": 0, "text": False})
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
            self._keep(self._card_mark(self._starttag(tag, attrs), tag))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if not (self.tables and tag in TABLE_WIDTHS):
            self._keep(self._starttag(tag, attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag in self.open:            # closes it and whatever was left open inside it
            del self.open[len(self.open) - 1 - self.open[::-1].index(tag):]
            while self.links and self.links[-1][1] > len(self.open):
                self.links.pop()
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
        # A table with no word in it (fabiensanglard.net's palette, its colours in styles that
        # go) is no table either.
        layout = table["layout"] or table["cells"] < 2 or not table["text"]
        for index in table["parts"] if layout else ():
            self.kept[index] = ""

    def close(self) -> None:
        super().close()
        while self.tables:              # never closed: no table
            self.tables[-1]["layout"] = True
            self._close_table()
        self.kept.append("</figure>" if self.figures else "")

    def handle_data(self, data: str) -> None:
        if self.tables and data.strip():
            for table in self.tables:
                table["text"] = True
        self._keep(data)

    def handle_entityref(self, name: str) -> None:
        if self.tables and name != "nbsp":
            for table in self.tables:
                table["text"] = True
        self._keep(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.tables and name not in ("160", "xa0", "xA0"):
            for table in self.tables:
                table["text"] = True
        self._keep(f"&#{name};")


CARD_MARK = "data-insight-card"
CARD_MARK_RE = re.compile(rf'\s{CARD_MARK}="[^"]*"')
CARD_BLOCKS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"})


def _with_structure(html_text: str) -> str:
    structure = _Structure()
    structure.feed(html_text)
    structure.close()
    return "".join(structure.kept)


# "instapaper_body" marks an article body for read-later tools (lesswrong.com).
CONTENT_CLASSES = ("entry-content", "post-content", "article-content", "content-body", "prose", "single-post-content",
                   "instapaper_body")
CANDIDATES = (
    lambda tag, id_, classes: tag == "article",
    lambda tag, id_, classes: tag == "main",
    lambda tag, id_, classes: tag == "div" and id_ == "markdownBody",
    lambda tag, id_, classes: tag == "div" and any(name in classes for name in CONTENT_CLASSES),
)


def _candidates(page: "_ParagraphText", html_text: str) -> List[Tuple[int, int]]:
    """Where the article may be (spans of html_text), in this order: the page's first
    <article>, its first <main>, #markdownBody, the first <div> with a CONTENT_CLASSES class,
    each whole (a card nested in the post no longer ends it). With none, the smallest element
    holding FALLBACK_TEXT_SHARE of the paragraph text (the whole page when it has none)."""
    found = [next((i for i, element in enumerate(page.elements) if test(*element)), None) for test in CANDIDATES]
    if any(index is not None for index in found):
        return [page.spans[index] for index in found if index is not None]
    spans = [span for size, span in zip(page.sizes, page.spans)
             if page.total and size >= page.total * FALLBACK_TEXT_SHARE]
    return [min(spans, key=lambda span: span[1] - span[0], default=(0, len(html_text)))]


# A link to a note: its text a number or a mark ("1", "[2]", "*", "†").
NOTE_REF_RE = re.compile(rf"""(?is)<a\b{ATTRS}?\bhref\s*=\s*["']#([^"']+)["']{ATTRS}>\s*(?:<[^>]+>\s*)*"""
                         r"""\[?(?:\d{1,3}|[*†‡§])\]?\s*(?:</[^>]+>\s*)*</a>""")


def _notes_after(page: "_ParagraphText", html_text: str, span: Tuple[int, int]) -> List[str]:
    """The notes the article points to that sit after it, outside it (blog.google's footnotes
    follow its <article>): the blocks of each element, after the article's end, whose id a
    note mark in the article links to ("#footnote-1"), in page order."""
    wanted = set(NOTE_REF_RE.findall(html_text[span[0]:span[1]]))
    blocks: List[str] = []
    after = span[1]
    for (_, id_, _), (start, end) in zip(page.elements, page.spans):
        if id_ in wanted and start >= after:
            blocks.extend(_blocks(_with_structure(html_text[start:end])))
            after = end                  # a note inside a note is read once
    return blocks


IMG_TAG_RE = re.compile(rf"(?is)<img\b{ATTRS}>")
IMG_ATTR_RE = re.compile(r"""(?is)\b(src|data-src|data-lazy-src|data-original|srcset|data-srcset|alt|width|height|class|style)"""
                         r"""\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
# Where an <img> keeps its address, in this order: a lazy image's real one first; a srcset's
# first candidate last (an image known only by its srcset).
IMAGE_ADDRESSES = ("data-src", "data-lazy-src", "data-original", "src", "srcset", "data-srcset")
ICON_MAX_PX = 64           # an image this wide or high is an icon, an avatar or a badge; not measured
STYLE_PX_RE = re.compile(r"(?i)(?<![-\w])(?:max-)?(?:width|height)\s*:\s*(\d+)px")


def _px(value: Optional[str]) -> Optional[int]:
    match = re.match(r"\s*(\d+)", value or "")
    return int(match.group(1)) if match else None


def _image_attrs(tag: str) -> Dict[str, str]:
    return {name.lower(): html_lib.unescape(dq or sq or bare) for name, dq, sq, bare in IMG_ATTR_RE.findall(tag)}


def _is_article_image(attrs: Dict[str, str]) -> bool:
    """Not a tracking pixel, an icon, a badge or an avatar."""
    sizes = [px for px in (_px(attrs.get("width")), _px(attrs.get("height"))) if px is not None]
    # A size in its style counts too: about.fb.com's share icons are style="max-width:24px".
    sizes += [int(px) for px in STYLE_PX_RE.findall(attrs.get("style", ""))]
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
SHORT_OPENING_CHARS = 25   # a first block shorter than this is a hint of chrome left in ("Share:"); not measured


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


LINK_RE = re.compile(rf"(?is)<a\b(?P<attrs>{ATTRS})>(?P<text>.*?)</a>")
HREF_RE = re.compile(r"""(?is)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
TITLE_TAG_RE = re.compile(r"(?is)<title\b[^>]*>(.*?)</title>")
LABEL_MAX_CHARS = 50       # a block shorter than this, with no sentence end, is a label ("Share:", "5 min read")
EXCERPT_MAX_CHARS = 200    # a paragraph this short may be a card's excerpt in a related list (neither measured)
# A block with this share of its text in links is a link: a card's title or a related
# list's item is all link (measured, 0053: 0.97-1.0 on the corpus), a reference ("[3] Rosenfeld et al. “A
# Constructive Prediction …” ICLR 2020.") about three quarters.
LINK_SHARE = 0.8
SENTENCE_END = (".", "!", "?", "…", ".”", ".\"", "?”", "!”", ".)", ".’")
LABEL_COLON_WORDS = 3      # not measured
CONTENT_TAGS = frozenset({"pre", "table", "blockquote"})
TITLE_SEPARATORS = ("|", "-", "–", "—", ":", "·", "•", "/")


def _same_site(href: str, host: str) -> bool:
    """A link within the page's own site (relative, or on its site: addresses.same_site): menus,
    breadcrumbs, authors and related posts are; a link post's subject is not."""
    target = urllib.parse.urlparse(href).hostname
    return not target or same_site(target, host)


def _block_kind(block: str, host: str) -> Tuple[str, bool]:
    """(what an edge block is, whether its links stay on the site): "link" (most of its text
    in links, or a short block of several links, a row of icons), "label" (short, no sentence
    end: "Share:", "5 min read", "Related posts"), "empty" (no letter: "0%", "+23"), "image"
    (a figure, or images with no text), "short" (a paragraph under EXCERPT_MAX_CHARS) or
    "text". A table, a code block or a quote is always text."""
    tag = (re.match(r"<([a-zA-Z0-9]+)", block) or [None, ""])[1].lower()
    text = " ".join(strip_html(block).split())
    if tag in CONTENT_TAGS or re.search(r"(?i)<(?:table|pre|blockquote)\b", block):
        return "text", False
    if tag in ("figure", "img") or (not text and "<img" in block.lower()):
        return "image", False
    card = re.match(rf'<[^>]*\s{CARD_MARK}="([^"]*)"', block)
    if card:
        return "link", _same_site(html_lib.unescape(card.group(1)), host)
    links = []
    for match in LINK_RE.finditer(block):
        href = next((value for value in HREF_RE.search(match.group("attrs")).groups() if value is not None), "") \
            if HREF_RE.search(match.group("attrs")) else ""
        href = html_lib.unescape(href).strip()
        if href and not href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            links.append((href, " ".join(strip_html(match.group("text")).split())))
    linked = sum(len(link_text) for _, link_text in links)
    same_site = all(_same_site(href, host) for href, _ in links)
    # A whole sentence linking to another site ("Learn more about how LogistiVIEW is driving
    # … smart glasses.") is the article's own; a card's title links within the site.
    sentence = not same_site and len(text) >= LABEL_MAX_CHARS and text.endswith((".", ".”", ".)", ".’"))
    if links and not sentence and (
            (text and linked >= len(text) * LINK_SHARE) or (len(links) >= 2 and len(text) < LABEL_MAX_CHARS)):
        return "link", same_site
    if not any(char.isalpha() for char in text):
        return "empty", False
    # A colon ends a sentence that introduces what follows ("The simplest file could look like
    # this:"), not a label of a word or two ("Share:", "Tags:", "News Summary:").
    ends = SENTENCE_END + ((":",) if len(text.split()) > LABEL_COLON_WORDS else ())
    if len(text) < LABEL_MAX_CHARS and not text.rstrip("*").endswith(ends):
        return "label", False
    return ("short" if len(text) <= EXCERPT_MAX_CHARS else "text"), False


def _title_key(text: str) -> str:
    """A title as compared (utils/titles.py): its words, in any case, with straight quotes."""
    return title_key(strip_html(text))


def _repeats_title(block: str, titles: List[str]) -> bool:
    """A heading that is the page's title again (its <title> or og:title, perhaps with a
    " | Site" after it)."""
    if not HEADING_RE.match(block):
        return False
    heading = _title_key(block)
    return bool(heading) and any(
        title == heading or (title.startswith(heading) and title[len(heading):].lstrip().startswith(TITLE_SEPARATORS))
        for title in titles)


def _page_titles(page: str) -> List[str]:
    found = [meta_content(page, "og:title"), (TITLE_TAG_RE.search(page) or [None, ""])[1]]
    return [_title_key(html_lib.unescape(title)) for title in found if title and title.strip()]


H1_RE = re.compile(r"(?is)<h1\b[^>]*>(.*?)</h1>")


def page_title_keys(page: Optional[str]) -> List[str]:
    """The titles a page gives itself (issue 0140), as compared (title_key): its og:title, its <title> and
    its <h1>s (scripts and styles aside)."""
    cleaned = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", "", page or "")
    return [key for key in _page_titles(cleaned) + [_title_key(h1) for h1 in H1_RE.findall(cleaned)[:3]] if key]


def same_title(title: Optional[str], page_titles: Sequence[str]) -> bool:
    """Whether a post's title is one of a page's titles (page_title_keys): the same words, or the same words
    with the site's name after or before a separator ("Title | Site", "Site — Title")."""
    key = _title_key(title or "")
    if not key:
        return False
    for page_title in page_titles:
        if page_title == key:
            return True
        if page_title.startswith(key) and page_title[len(key):].lstrip().startswith(TITLE_SEPARATORS):
            return True
        if page_title.endswith(key) and page_title[:-len(key)].rstrip().endswith(TITLE_SEPARATORS):
            return True
    return False


PICTURE_RUN = 3            # list items in a row, each only a linked picture (a blog's 6-22 upvoters); not measured
PICTURE_ITEM_RE = re.compile(rf"(?is)<li\b{ATTRS}>\s*<a\b(?P<attrs>{ATTRS})>\s*(?P<img><img\b{ATTRS}>)\s*</a>\s*</li>")
IMAGE_FILE_RE = re.compile(r"(?i)\.(?:jpe?g|png|gif|webp|avif|svg)$")


def _linked_picture(block: str) -> bool:
    """A list item that is only a picture linking to a page (a person's profile: an upvoter,
    an author), by shape. Never a picture declared larger than an icon, nor one linking to an
    image file (a gallery's thumbnail opening its picture)."""
    match = PICTURE_ITEM_RE.fullmatch(block.strip())
    if not match:
        return False
    href = HREF_RE.search(match.group("attrs"))
    target = html_lib.unescape(next((v for v in href.groups() if v is not None), "") if href else "").strip()
    if not target or target.startswith("#") or IMAGE_FILE_RE.search(urllib.parse.urlparse(target).path):
        return False
    attrs = _image_attrs(match.group("img"))
    sizes = [px for px in (_px(attrs.get("width")), _px(attrs.get("height"))) if px is not None]
    return all(px <= ICON_MAX_PX for px in sizes)


def _without_edge_chrome(blocks: List[str], titles: List[str], base_url: str) -> List[str]:
    """The blocks without the chrome at the article's edges (step 5), the way Readability
    judges unnamed blocks by their links and their length, but only where chrome sits:
    - Before the first paragraph: labels (an eyebrow, "Back to Blog", a date, "5 min read",
      "Share:"), links within the site (breadcrumbs, the author's page) and blocks with no
      letter go; images (the cover) and headings stay, but for a heading that is the page's
      title again (the reader shows the title). A link to another site (a link post's subject)
      ends the opening.
    - After the last paragraph, a tail of links (related posts, a "More on …" list, share and
      social rows, a product grid) goes with its labels ("Related posts", "Tags:") and what lies
      between its links (the cards' images and short excerpts): it begins at its first link,
      or the labels just before it, and must hold two links or end on a link or a label, so an
      article's own closing link ("Watch the keynote") stays. Blocks with no letter at the very
      end ("0%") go.
    - Anywhere: a run of PICTURE_RUN list items that are each only a picture linking to a page
      (_linked_picture: an upvoters or authors list) goes."""
    pictures = [_linked_picture(block) for block in blocks]
    run = [False] * len(blocks)
    start = 0
    for index in range(len(blocks) + 1):
        if index == len(blocks) or not pictures[index]:
            if index - start >= PICTURE_RUN:
                run[start:index] = [True] * (index - start)
            start = index + 1
    blocks = [block for block, in_run in zip(blocks, run) if not in_run]
    host = publication_of(host_of(base_url))
    kinds = [_block_kind(block, host) for block in blocks]
    keep = [True] * len(blocks)
    # The opening.
    title_seen = False
    for index, (block, (kind, same_site)) in enumerate(zip(blocks, kinds)):
        if HEADING_RE.match(block) and kind != "link":
            if not title_seen and _repeats_title(block, titles):
                keep[index] = False
                title_seen = True
            continue
        if kind in ("label", "empty") or (kind == "link" and same_site):
            keep[index] = False
        elif kind == "image" and re.match(r"(?i)<li\b", block):
            keep[index] = False         # a list of pictures with no words: avatars, logos
        elif kind != "image":
            break
    # The tail: the longest run of links, labels, images, letterless and short blocks at the end.
    start = len(blocks)
    while start and kinds[start - 1][0] in ("link", "label", "image", "empty", "short"):
        start -= 1
    first_link = next((i for i in range(start, len(blocks)) if kinds[i][0] == "link"), None)
    if first_link is not None:
        begin = first_link
        while begin > start and kinds[begin - 1][0] in ("label", "empty", "image"):
            begin -= 1
        while begin < first_link and kinds[begin][0] in ("image", "empty"):
            begin += 1
        # Cards (a picture, then its title): the first card's picture goes with it.
        pairs = sum(1 for i in range(begin + 1, len(blocks)) if kinds[i][0] == "link" and kinds[i - 1][0] == "image")
        if begin == first_link and begin > start and kinds[begin - 1][0] == "image" and pairs >= 1:
            begin -= 1
        tail = [(kind, block) for (kind, _), block in zip(kinds[begin:], blocks[begin:]) if kind not in ("empty", "image")]
        if tail and (tail[-1][0] in ("link", "label")
                     or (tail[-1][0] == "short" and len(tail) > 1 and tail[-2][0] == "link"
                         and HEADING_RE.match(tail[-2][1]) and sum(kind == "link" for kind, _ in tail) >= 2)):
            keep[begin:] = [False] * (len(blocks) - begin)
    end = len(blocks)
    while end and keep[end - 1] and kinds[end - 1][0] == "empty":
        keep[end - 1] = False
        end -= 1
    return [block for block, kept in zip(blocks, keep) if kept]


def read_article_page(html_text: str, base_url: str = "") -> Tuple[str, Dict[str, Any]]:
    """(the article's html, its reading fidelity). The html is extract_article_html's; the
    fidelity (read_fidelity) is {} when no article was found."""
    cleaned = re.sub(r"(?is)<(script|style|noscript|iframe|svg|audio|video)\b.*?</\1>", "", html_text or "")
    titles = _page_titles(cleaned)
    cleaned = _without_hidden_link_labels(cleaned)
    cleaned = _without_chrome(_with_loose_text(cleaned))
    # The first candidate long enough to be the article: a page's first <article> can be a
    # 4-word "related" card while the post is in <main> (deepmind.google, 2026-10-27). The
    # main block only when no candidate matched: a short <article> is no article, not a reason
    # to read the page's other lists as one (issue 0029).
    page = _ParagraphText(cleaned)
    for span in _candidates(page, cleaned):
        blocks = _blocks(_with_structure(cleaned[span[0]:span[1]]))
        if not blocks:  # list items count only inside the chosen candidate
            blocks = PAGE_BLOCK_RE.findall(cleaned)
        blocks += _notes_after(page, cleaned, span)
        # Long enough to be the article is judged before its edges go: a short post (a
        # summary under a shop's product grid) is still the post.
        long_enough = len(strip_html(" ".join(_with_headings_over_content(blocks)))) >= ARTICLE_MIN_CHARS
        blocks = _with_headings_over_content(_without_edge_chrome(blocks, titles, base_url))
        if long_enough and strip_html(" ".join(blocks)).strip():
            html = IMG_TAG_RE.sub(lambda match: _article_image(match.group(0), base_url),
                                  CARD_MARK_RE.sub("", "\n".join(blocks)))
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


LOST_IMAGES_MIN = 3        # a page "lost most of its images" with at least this many, under half kept; not measured


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


# Where each feed shape keeps its items (issue 0135): RSS 2.0 under its channel, Atom's entries,
# RSS 1.0 (RDF) items beside its channel. The feed finder reads a candidate by the same paths, so a
# feed it accepts is one this parser reads.
ITEM_PATHS = {"rss": ("rss", "channel", "item"), "feed": ("feed", "entry"), "rdf": ("rdf", "item")}


def item_path(names: Sequence[str]) -> bool:
    """Whether the element at this path (local names from the root, lower case) is an item
    parse_feed_posts reads."""
    return bool(names) and ITEM_PATHS.get(names[0]) == tuple(names)


# What a feed's XML may hold that a strict parser refuses (issue 0137 B4): an ampersand that starts no
# entity ("R&D"), and control characters XML 1.0 forbids. Both are repaired before giving up.
BARE_AMPERSAND_RE = re.compile(r"&(?!(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);)")
CONTROL_CHARS_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def repaired_xml(text: str) -> str:
    """text with its bare ampersands escaped and its forbidden control characters gone (issue 0137 B4)."""
    return CONTROL_CHARS_RE.sub("", BARE_AMPERSAND_RE.sub("&amp;", text))


def feed_root(feed_text: str) -> ET.Element:
    """The feed's root element. A document a strict parser refuses is read again repaired
    (repaired_xml); when that fails too, the first error is raised (the parser's own message)."""
    try:
        return ET.fromstring(feed_text)
    except ET.ParseError as first:
        try:
            return ET.fromstring(repaired_xml(feed_text))
        except ET.ParseError:
            raise first from None


def feed_items(feed_text: str) -> int:
    """How many items or entries the document holds, wherever they are (0 when it does not parse)."""
    try:
        root = feed_root(feed_text)
    except ET.ParseError:
        return 0
    return sum(1 for node in root.iter() if local_name(node.tag).lower() in ("item", "entry"))


# An item's identity (issue 0137 B1): its link, else its guid, else its enclosure's address, else its
# title and date. Never the feed's own address, nor a link items with other guids share (a podcast
# whose every episode links the show's page). A guid, or a title and date, that is no address is kept
# on the feed's address as ITEM_PARAM: each item a post of its own, the same post at every fetch.
ITEM_PARAM = "insight_item"
# A link this many items with other identities share is the show's or the site's, not an item's; two
# items sharing one (the same article posted twice) stay one post, as before.
SHARED_LINK_ITEMS = 3


def _is_address(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def item_address(source_url: str, token: str) -> str:
    """The address of an item that has none of its own: the feed's, with the item's token (ITEM_PARAM)."""
    return f"{source_url}{'&' if '?' in source_url else '?'}{ITEM_PARAM}={urllib.parse.quote(token, safe='')}"


def item_identity(link: Optional[str], guid: Optional[str], enclosure: Optional[str], title_date: Optional[str],
                  source_url: str, shared: bool = False) -> str:
    """The item's address by its identity (see ITEM_PARAM); shared: other items with other guids have this link."""
    own = normalize_url(source_url) or source_url
    if _is_address(link) and not shared and (normalize_url(link) or link) != own:
        return link  # type: ignore[return-value]
    if _is_address(guid) and (normalize_url(guid) or guid) != own:
        return guid  # type: ignore[return-value]
    if guid:
        return item_address(source_url, guid)
    if _is_address(enclosure):
        return enclosure  # type: ignore[return-value]
    if title_date:
        return item_address(source_url, title_date)
    return link or source_url


def _identities(drafts: List[Dict[str, Any]], source_url: str) -> None:
    """Each draft's url and title, in place, from its identity (item_identity); the candidates go."""
    others: Dict[str, set] = {}
    for draft in drafts:
        if draft.get("_link"):
            others.setdefault(draft["_link"], set()).add((draft.get("guid"), draft.get("_enclosure"), draft.get("_title_date")))
    for draft in drafts:
        link = draft.pop("_link", None)
        url = item_identity(link, draft.get("guid"), draft.pop("_enclosure", None), draft.pop("_title_date", None),
                            source_url, shared=bool(link) and len(others.get(link, ())) >= SHARED_LINK_ITEMS)
        draft["url"] = normalize_feed_urls(url)
        draft["title"] = readable_title(draft["title"], draft["url"])


def _enclosure(node: ET.Element) -> Optional[str]:
    """The item's enclosure address (an episode's audio), else None."""
    for child in node:
        name = local_name(child.tag)
        if name == "enclosure" and _is_address(child.attrib.get("url")):
            return child.attrib["url"].strip()
        if name == "link" and child.attrib.get("rel") == "enclosure" and _is_address(child.attrib.get("href")):
            return child.attrib["href"].strip()
    return None


def _title_date(title: Optional[str], when: Optional[str]) -> Optional[str]:
    title = " ".join((title or "").split())
    return f"{title}|{(when or '').strip()}" if title else None


# Authors (issue 0137 B7): one per name element; an affiliation or an identifier is no author.
AFFILIATION_TAGS = frozenset({"aff", "affiliation", "affiliations", "institution", "orgname", "orgdiv", "department",
                              "address", "addr-line", "ror", "orcid", "identifier", "email", "xref", "sup", "label",
                              "country", "city"})
NAME_TAGS = frozenset({"name", "string-name", "contrib", "author", "creator", "persname", "fullname"})
IDENTIFIER_URL_RE = re.compile(r"(?i)https?://(?:www\.)?(?:ror\.org|orcid\.org|isni\.org|viaf\.org)\S*")
AFFILIATION_WORDS = (r"Department|Dept\.|Division|School|Faculty|University|Institute|Institut|Centre|Center|"
                     r"Laboratory|Laboratoire|College|Hospital|Clinic|Academy|Research and Development")
# An affiliation glued to a name ("Sam B. KimDepartment of Psychology"), or an item of its own after a comma.
GLUED_AFFILIATION_RE = re.compile(rf"(?<=[a-z.)])(?=(?:{AFFILIATION_WORDS})\b)")
AFFILIATION_ITEM_RE = re.compile(rf"^(?:the\s+)?(?:{AFFILIATION_WORDS})\b|\b(?:{AFFILIATION_WORDS}) (?:of|for)\b")
GLUED_NAME_RE = re.compile(r"(?<=[a-z]{3})(?=[A-Z][a-z])")
AUTHOR_SEPARATORS_RE = re.compile(r"\s*(?:[;,]|\band\b|&)\s*")
AUTHOR_MAX_CHARS = 80


def author_names(text: str) -> List[str]:
    """The author names in one author line, affiliations and identifiers dropped (issue 0137 B7):
    "Jo Ann Lee, Sam B. KimDepartment of Psychology, University of X" -> ["Jo Ann Lee", "Sam B. Kim"].
    Names glued together ("Ann LeeSam Kim") are split only when every part reads as a name of two words
    or more ("Ian VanderWaal" stays one)."""
    text = html_lib.unescape(text or "")
    if "<" in text and ">" in text:
        text = _tagged_names(text)
    text = " ".join(text.split())
    for cut in (IDENTIFIER_URL_RE.search(text), GLUED_AFFILIATION_RE.search(text)):
        text = text[:cut.start()] if cut else text
    names: List[str] = []
    for piece in AUTHOR_SEPARATORS_RE.split(text):
        piece = piece.strip(" .*†‡§0123456789")
        if not piece:
            continue
        if AFFILIATION_ITEM_RE.search(piece):
            break       # the affiliations start here: no name follows them
        parts = GLUED_NAME_RE.split(piece)
        if len(parts) > 1 and all(len(part.split()) >= 2 for part in parts):
            names += [part.strip() for part in parts]
        else:
            names.append(piece)
    return list(dict.fromkeys(name[:AUTHOR_MAX_CHARS] for name in names if any(ch.isalpha() for ch in name)))


class _TaggedNames(HTMLParser):
    """An author line written as markup: each element's text apart, affiliations and labels dropped."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        marks = " ".join(value or "" for name, value in attrs if name in ("class", "id", "itemprop")).lower()
        if tag not in VOID_TAGS and (self.skip or tag in AFFILIATION_TAGS
                                     or any(word in marks for word in ("aff", "institution", "orcid", "ror"))):
            self.skip += 1
        self.parts.append(", ")

    def handle_endtag(self, tag: str) -> None:
        if self.skip and tag not in VOID_TAGS:
            self.skip -= 1
        self.parts.append(", ")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _tagged_names(markup: str) -> str:
    parser = _TaggedNames()
    parser.feed(markup)
    parser.close()
    return "".join(parser.parts)


def element_authors(node: ET.Element) -> List[str]:
    """The authors one author element names (issue 0137 B7): one per name child, its affiliation and
    identifier children dropped; else its own text (author_names)."""
    named = [child for child in node if local_name(child.tag).lower() in NAME_TAGS]
    if named:
        return list(dict.fromkeys(name for child in named for name in element_authors(child)))
    text = node.text or ""
    for child in node:
        if local_name(child.tag).lower() not in AFFILIATION_TAGS:
            text += ", " + "".join(child.itertext()) + ", "
        text += child.tail or ""
    return author_names(text)


def clean_authors(names: Sequence[Any]) -> List[str]:
    """A stored author list with each line read again by author_names (the repair of issue 0137 B7)."""
    return list(dict.fromkeys(name for line in names if isinstance(line, str) for name in author_names(line)))


def _undated(post: Dict[str, Any]) -> Dict[str, Any]:
    """An item with no date says it will be dated when first seen (issue 0137 B9: the saver keeps that time)."""
    if post.get("date") is None:
        post["date_precision"] = "seen"
    return post


def parse_feed_posts(feed_text: str, source_url: str) -> List[Dict[str, Any]]:
    """Parse an RSS 2.0, Atom or RSS 1.0 (RDF) document into post drafts, newest first. A document a
    strict parser refuses is read repaired (feed_root, issue 0137 B4); each item's address is its
    identity (item_identity, B1); an undated item is "seen" (B9)."""
    root = feed_root(feed_text)
    posts: List[Dict[str, Any]] = []

    if local_name(root.tag) == "rss":
        channel = next((child for child in root if local_name(child.tag) == "channel"), None)
        items = [child for child in (channel if channel is not None else []) if local_name(child.tag) == "item"]
        for item in items:
            # <content:encoded> is the full article, <description> often only a summary.
            content_html = normalize_feed_urls(
                child_inner_xml(item, "encoded") or child_inner_xml(item, "description")
            )
            when = child_text(item, "pubDate") or child_text(item, "updated") or child_text(item, "date")
            title = normalize_feed_urls(child_text(item, "title") or "")
            posts.append(_undated({
                "platform": "rss",
                "source": source_url,
                "_link": normalize_feed_urls(child_text(item, "link")) or None,
                "_enclosure": _enclosure(item),
                "_title_date": _title_date(title, when),
                "guid": child_text(item, "guid"),
                "title": title,
                "content": strip_html(content_html),
                "content_html": content_html,
                "date": parse_datetime_value(when),
                "date_precision": date_precision(when),
                "media_urls": _extract_xml_media_urls(item, content_html),
                "categories": _extract_xml_categories(item),
                # <comments>: the item's discussion page (on Hacker News, the HN thread).
                "metadata": {"comments_url": comments} if (comments := child_text(item, "comments")) else {},
            }))
    elif local_name(root.tag) == "feed":
        entries = [child for child in root if local_name(child.tag) == "entry"]
        for entry in entries:
            content_html = normalize_feed_urls(
                child_inner_xml(entry, "content") or child_inner_xml(entry, "summary")
            )
            when = child_text(entry, "published") or child_text(entry, "updated")
            title = normalize_feed_urls(child_text(entry, "title") or "")
            posts.append(_undated({
                "platform": "rss",
                "source": source_url,
                "_link": normalize_feed_urls(_extract_atom_link(entry)) or None,
                "_enclosure": _enclosure(entry),
                "_title_date": _title_date(title, when),
                "guid": child_text(entry, "id"),
                "title": title,
                "content": strip_html(content_html),
                "content_html": content_html,
                "date": parse_datetime_value(when),
                "date_precision": date_precision(when),
                "media_urls": _extract_xml_media_urls(entry, content_html),
                "categories": _extract_xml_categories(entry),
                "metadata": {},
            }))
    elif local_name(root.tag).lower() == "rdf":
        # RSS 1.0 (issue 0135): <rdf:RDF> holds its <item>s beside its <channel>, each dated by
        # Dublin Core (dc:date) or PRISM (prism:publicationDate), its authors dc:creator: one author
        # per name element, affiliations and identifiers dropped (issue 0137 B7).
        for item in (child for child in root if local_name(child.tag) == "item"):
            content_html = normalize_feed_urls(
                child_inner_xml(item, "encoded") or child_inner_xml(item, "description")
            )
            about = next((value for key, value in item.attrib.items() if local_name(key) == "about"), None)
            when = (child_text(item, "date") or child_text(item, "publicationDate")
                    or child_text(item, "coverDate") or child_text(item, "pubDate"))
            creators = list(dict.fromkeys(name for child in item if local_name(child.tag) == "creator"
                                          for name in element_authors(child)))
            title = normalize_feed_urls(" ".join((child_text(item, "title") or "").split()))
            posts.append(_undated({
                "platform": "rss",
                "source": source_url,
                "_link": normalize_feed_urls(child_text(item, "link") or about) or None,
                "_enclosure": _enclosure(item),
                "_title_date": _title_date(title, when),
                "guid": about or child_text(item, "identifier"),
                "title": title,
                "content": strip_html(content_html),
                "content_html": content_html,
                "date": parse_datetime_value(when),
                "date_precision": date_precision(when),
                "media_urls": _extract_xml_media_urls(item, content_html),
                "categories": _extract_xml_categories(item),
                "metadata": {"authors": creators} if creators else {},
            }))

    _identities(posts, source_url)
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
