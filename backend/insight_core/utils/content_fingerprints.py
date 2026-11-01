"""Cheap deterministic content fingerprints: the post content hash, strip_html (HTML to plain
text) and clean_text (plain text tidied for display)."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Literal


HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
# A tag read as the HTML parser reads it: a ">" inside a quoted attribute value doesn't end it
# (Hugging Face's class="max-md:[&amp;>a]:hidden", issue 0072); a comment ends at "-->". A quote
# counts only after "=", as in HTML; a tag the rule can't read (an unclosed quote) ends at its
# first ">", as HTML_TAG_RE does.
TAG_RE = re.compile(r"""(?is)<!--.*?-->|<[a-z/!?](?:[^>"'=]|=\s*"[^"]*"|=\s*'[^']*'|=)*>|<[^>]+>""")
WHITESPACE_RE = re.compile(r"\s+")


def decode_entities(text: str) -> str:
    """HTML codes as characters ("That&#39;s" -> "That's"), twice for double-escaped text
    ("&amp;#39;"), which some feeds send."""
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def clean_text(value: str | None) -> str:
    """Plain text as shown: HTML codes decoded, every run of whitespace one space. Never read
    as HTML, so a literal "Option<T>" stays."""
    return WHITESPACE_RE.sub(" ", decode_entities(str(value or ""))).strip()


def strip_html(value: str | None, *, entities: Literal["decode", "decode_first"] = "decode") -> str:
    """Plain text from HTML: every tag becomes a space, every run of whitespace one space.

    entities: "decode" decodes &amp; and friends once the tags are gone (clean_text), so an
    escaped tag (&lt;b&gt;) stays as text, and reads a tag to its end past a ">" in a quoted
    value (TAG_RE); "decode_first" decodes them once, before, so escaped tags go too, and keeps
    the first-">" rule. The content hash uses "decode_first": what it returns is part of every
    stored hash, so it never changes.
    """
    if not value:
        return ""
    text = str(value)
    if entities == "decode_first":
        return WHITESPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", html.unescape(text))).strip()
    return clean_text(TAG_RE.sub(" ", text))


def normalize_text(value: str | None) -> str:
    """Normalize text for deterministic fingerprinting."""
    if not value:
        return ""

    text = html.unescape(str(value))
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip().casefold()


def hash_post_content(title: str | None, content: str | None, content_html: str | None) -> str:
    """Hash a post's textual payload for update tracking and dedupe seeds."""
    parts = [
        normalize_text(title),
        normalize_text(content),
        normalize_text(strip_html(content_html, entities="decode_first")),
    ]
    payload = "\n".join(part for part in parts if part)
    if not payload:
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
