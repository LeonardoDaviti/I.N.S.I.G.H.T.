"""The fields computed for every post on save (content hash, URLs, host and language), and the
title the reader shows."""

from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from .content_fingerprints import clean_text, hash_post_content, strip_html
from .language_detection import detect_language
from .url_normalization import TWEET_PATH, canonicalize_url, extract_url_host, normalize_url

TITLE_MAX_CHARS = 120
TITLE_MIN_SENTENCE_CHARS = 20
SENTENCE_END_RE = re.compile(r"[.!?…](?=\s|$)")
# "…", "..." or, from the Telegram RSS bridge, "[...]" / "[…]".
TRAILING_ELLIPSIS_RE = re.compile(r"(?:…|\.\.\.|\[(?:…|\.\.\.)\])\s*$")


# Nitter's titles say what a tweet is (issue 0066): "RT by @user: …" a repost by user, "R to @user: …"
# a reply to user. The text after them is the tweet's.
REPOST_BY_RE = re.compile(r"^RT by @(\w+): ")
REPLY_TO_RE = re.compile(r"^R to @(\w+): ")
_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.U)   # a word: two letters or more


def _glued_first_line(cut: str, content: str | None) -> str | None:
    """A cut title that is the body's start with its line breaks dropped (the Telegram bridge joins
    "…у SpaceX" and "Датацентр…" into "SpaceXДатацентр"): the body up to the first space the title
    lacks, which is where the post's first line ended. None when the title keeps every space."""
    title, body = clean_text(cut), clean_text(content)
    i = j = 0
    while i < len(title) and j < len(body):
        if title[i] == body[j]:
            i, j = i + 1, j + 1
        elif body[j].isspace() and not title[i].isspace():
            if len(_WORD_RE.findall(body[:j])) >= 2:
                return body[:j].rstrip()
            j += 1   # a space after a leading emoji or one word ("🌸 Релизим"), not a line's end
        else:
            return None
    return None


def display_title(title: str | None, content: str | None) -> str:
    """The title the feed and the post page show; the stored title is never changed.

    The text is the title, or the body when the title is empty or is the body's start cut with
    "…" or "[...]" (a tweet, a Telegram post, a GitHub commit). Only its first non-empty line counts. A
    line over 120 characters is cut at its first sentence end (after 20 characters at least),
    else at the last space within 117 characters, with "…". Title and body are stored plain
    text, so nothing in them is read as a tag.
    """
    stored = REPOST_BY_RE.sub("", (title or "").strip())   # who reposted it is said beside it (issue 0066)
    cut = TRAILING_ELLIPSIS_RE.sub("", stored).strip()
    glued = _glued_first_line(cut, content) if cut != stored and cut else None
    from_body = not stored or (
        cut != stored and bool(cut) and clean_text(content).startswith(clean_text(cut))
    )
    text = content if from_body else stored
    line = glued or next((plain for plain in (clean_text(raw) for raw in (text or "").splitlines()) if plain), "")
    if len(line) <= TITLE_MAX_CHARS:
        return line
    sentence = SENTENCE_END_RE.search(line, TITLE_MIN_SENTENCE_CHARS - 1)
    if sentence and sentence.end() <= TITLE_MAX_CHARS:
        return line[: sentence.end()]
    head = line[: TITLE_MAX_CHARS - 3]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip() + "…"


def tweet_author(url: str | None) -> str | None:
    """A tweet's account, as its address writes it (issue 0066): `user` of /<user>/status/<id>."""
    match = TWEET_PATH.match(urlparse(url or "").path)
    return match.group(1) if match else None


def reposted_by(title: str | None, author: str | None) -> List[str]:
    """Who reposted a tweet, by its title: "RT by @user: …", the author reposting itself aside."""
    match = REPOST_BY_RE.match(title or "")
    return [match.group(1)] if match and author and match.group(1).lower() != author.lower() else []


def build_post_fields(post: Dict[str, Any]) -> Dict[str, Any]:
    """Build the normalised fields reading and deduplication rely on, for one post."""
    title = post.get("title") if isinstance(post, dict) else None
    content = post.get("content") if isinstance(post, dict) else None
    content_html = post.get("content_html") if isinstance(post, dict) else None
    url = post.get("url") if isinstance(post, dict) else None
    raw_lang = post.get("lang") if isinstance(post, dict) else None

    normalized_url = normalize_url(url)
    author = tweet_author(url)
    canonical_url = canonicalize_url(url)
    url_host = extract_url_host(url)
    language_input = "\n".join(
        part
        for part in [title or "", content or "", strip_html(content_html, entities="decode_first")]
        if part
    )
    detected = detect_language(language_input)

    return {
        "lang": raw_lang,
        "language_code": detected["language_code"],
        "language_confidence": float(detected["confidence"] or 0.0),
        "normalized_url": normalized_url,
        "canonical_url": canonical_url or normalized_url,
        "url_host": url_host,
        "content_hash": hash_post_content(title, content, content_html),
        # Attribution (issue 0066): a tweet's account, and the accounts that reposted it.
        "author": author,
        "reposted_by": reposted_by(title, author),
    }
