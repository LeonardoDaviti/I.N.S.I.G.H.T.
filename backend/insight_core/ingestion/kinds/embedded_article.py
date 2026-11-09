"""An article a page carries as data rather than as markup (issue 0140): a page built by a script holds
its text in an embedded data block the reader (parsing.read_article_page) never sees: a JSON-LD object's
`articleBody`, Next.js's `__NEXT_DATA__`, any `<script type="application/json">` block, or a framework's
hydration assignment (`window.__NUXT__ = {...}`, `window.__INITIAL_STATE__ = {...}`).

Pure: no request. `embedded_articles(page)` lists the long prose strings those blocks hold, each with the
title of the object holding it (a JSON-LD `headline`, a post's `title`), longest first; `as_html` turns one
into the markup the reader reads (HTML as it is; markdown or plain text as paragraphs). Which of them is the
post's article is full_text's call (it checks each against the post).

A page that needs a script and holds no such block (its text fetched by the script after it loads) is
`script_rendered`: full_text records it `needs_script` (a headless read is not in this issue: 0081).
"""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterator, List, Optional

from insight_core.utils.content_fingerprints import strip_html

SCRIPT_RE = re.compile(r"(?is)<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>")
TYPE_RE = re.compile(r"""(?i)\btype\s*=\s*["']?([^"'\s>]+)""")
DATA_TYPES = ("application/ld+json", "application/json")
# A framework's state assigned in a plain script: `window.__NUXT__ = {...};`, `__INITIAL_STATE__={...}`.
ASSIGNED_RE = re.compile(r"(?s)^\s*(?:window\.|self\.|var\s+|const\s+|let\s+)?(__[A-Z0-9_]+__|__INITIAL_STATE__|__PRELOADED_STATE__|__APOLLO_STATE__)\s*=\s*(?P<json>[\[{].*?)\s*;?\s*$")
# The keys whose string may be an article's text, by a part of their name (articleBody, bodyHtml, post_content,
# markdown, contentHtml, rawText); never a description, an excerpt or a summary (a feed's teaser again).
TEXT_KEY_RE = re.compile(r"(?i)(body|content|html|markdown|^text$|^raw$|^source$|^mdx?$)")
NOT_TEXT_KEY_RE = re.compile(r"(?i)(description|excerpt|summary|teaser|abstract|snippet|preview|meta|seo|css|style|script)")
TITLE_KEYS = ("headline", "title", "name")
# A string shorter than this is no article (the reader keeps 700 and more: full_text.read_article).
MIN_CHARS = 700
# Prose, not code: at most this share of its characters are code's punctuation ({ } ; = < > ( )); not measured.
CODE_SHARE = 0.03
HTML_BLOCK_RE = re.compile(r"(?i)<(?:p|h[1-6]|div|section|ul|ol|li|blockquote|pre|figure|br)\b")
# The markers of a page whose content a script builds: an app root, a framework's runtime or a <noscript> asking for one.
SCRIPT_ROOT_RE = re.compile(
    r"""(?is)<(?:div|main|body)\b[^>]*\bid\s*=\s*["'](?:__next|__nuxt|root|app|svelte|___gatsby)["']"""
    r"""|\bdata-reactroot\b|\bng-version\s*=|\b__NEXT_DATA__\b|\bself\.__next_f\b|\bwindow\.__NUXT__\b"""
    r"""|<noscript\b[^>]*>[^<]{0,300}\b(?:javascript|enable js)\b""")


@dataclass(frozen=True)
class Embedded:
    """One long prose string a data block holds: its value, the key it was under, and the title of the object holding it."""
    value: str
    key: str
    title: Optional[str]

    @property
    def is_html(self) -> bool:
        return bool(HTML_BLOCK_RE.search(self.value))

    @property
    def text(self) -> str:
        return strip_html(self.value) if self.is_html else " ".join(self.value.split())


def _script_type(attrs: str) -> str:
    found = TYPE_RE.search(attrs or "")
    return found.group(1).lower() if found else ""


def data_blocks(page: Optional[str]) -> Iterator[Any]:
    """The parsed JSON of every data block on the page: JSON-LD, application/json (Next.js's __NEXT_DATA__ is one),
    a framework's state assigned in a plain script. A block that is not JSON is passed over."""
    for match in SCRIPT_RE.finditer(page or ""):
        kind, body = _script_type(match.group("attrs")), match.group("body").strip()
        if not body:
            continue
        if kind in DATA_TYPES:
            raw = body
        elif kind in ("", "text/javascript", "module"):
            assigned = ASSIGNED_RE.match(body)
            if not assigned:
                continue
            raw = assigned.group("json")
        else:
            continue
        try:
            yield json.loads(raw)
        except ValueError:
            continue


def _prose(text: str) -> bool:
    if len(text) < MIN_CHARS:
        return False
    code = sum(text.count(char) for char in "{};=()")
    return code / len(text) <= CODE_SHARE and sum(char.isalpha() for char in text) / len(text) >= 0.5


def _walk(node: Any, title: Optional[str], key: str, found: List[Embedded]) -> None:
    if isinstance(node, dict):
        here = next((node[name].strip() for name in TITLE_KEYS
                     if isinstance(node.get(name), str) and node[name].strip()), None) or title
        for name, value in node.items():
            _walk(value, here, str(name), found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, title, key, found)
    elif isinstance(node, str) and TEXT_KEY_RE.search(key) and not NOT_TEXT_KEY_RE.search(key):
        candidate = Embedded(node, key, title)
        if _prose(candidate.text):
            found.append(candidate)


def embedded_articles(page: Optional[str]) -> List[Embedded]:
    """The long prose strings the page's data blocks hold under a text key, each once, longest first."""
    found: List[Embedded] = []
    for block in data_blocks(page):
        _walk(block, None, "", found)
    seen, unique = set(), []
    for candidate in sorted(found, key=lambda c: -len(c.text)):
        if candidate.text not in seen:
            seen.add(candidate.text)
            unique.append(candidate)
    return unique


def script_rendered(page: Optional[str]) -> bool:
    """Whether the page is built by a script (an app root, a framework's runtime, a <noscript> asking for one)."""
    return bool(SCRIPT_ROOT_RE.search(page or ""))


# --------------------------------------------------------------------------- markdown or plain text as HTML

HEADING_MD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\((\S+?)(?:\s+\"[^\"]*\")?\)")
LINK_MD_RE = re.compile(r"\[([^\]]+)\]\((\S+?)(?:\s+\"[^\"]*\")?\)")
STRONG_MD_RE = re.compile(r"\*\*(.+?)\*\*")
EM_MD_RE = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
CODE_MD_RE = re.compile(r"`([^`]+)`")
FENCE_RE = re.compile(r"(?s)```[^\n]*\n(.*?)```")


def _inline(text: str) -> str:
    text = html_lib.escape(text, quote=False)
    text = IMAGE_MD_RE.sub(lambda m: f'<img src="{html_lib.escape(m.group(2))}" alt="{m.group(1)}">', text)
    text = LINK_MD_RE.sub(lambda m: f'<a href="{html_lib.escape(m.group(2))}">{m.group(1)}</a>', text)
    text = STRONG_MD_RE.sub(r"<strong>\1</strong>", text)
    text = EM_MD_RE.sub(r"<em>\1</em>", text)
    return CODE_MD_RE.sub(r"<code>\1</code>", text)


def as_html(candidate: Embedded) -> str:
    """The markup the reader reads: HTML as it is; markdown or plain text as paragraphs (a blank line between
    two, or each line when there are none), `#` lines as headings, fenced code as <pre>, lists as items."""
    if candidate.is_html:
        return candidate.value
    value = candidate.value.replace("\r\n", "\n")
    blocks: List[str] = []
    fences: List[str] = []

    def keep(match: re.Match) -> str:
        fences.append(match.group(1))
        return f"\n\n\x00{len(fences) - 1}\x00\n\n"

    value = FENCE_RE.sub(keep, value)
    parts = re.split(r"\n\s*\n", value) if "\n\n" in value else value.split("\n")
    for part in (p.strip() for p in parts):
        if not part:
            continue
        fence = re.fullmatch(r"\x00(\d+)\x00", part)
        if fence:
            blocks.append(f"<pre><code>{html_lib.escape(fences[int(fence.group(1))])}</code></pre>")
            continue
        heading = HEADING_MD_RE.match(part)
        if heading and "\n" not in part:
            level = min(len(heading.group(1)) + 1, 6)
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        lines = part.split("\n")
        if all(re.match(r"^\s*(?:[-*+]|\d+\.)\s+", line) for line in lines):
            items = "".join(f"<li>{_inline(re.sub(r'^\s*(?:[-*+]|\d+\.)\s+', '', line))}</li>" for line in lines)
            blocks.append(f"<ul>{items}</ul>")
            continue
        blocks.append(f"<p>{_inline(' '.join(line.strip() for line in lines))}</p>")
    return "\n".join(blocks)


__all__ = ["Embedded", "as_html", "data_blocks", "embedded_articles", "script_rendered"]
