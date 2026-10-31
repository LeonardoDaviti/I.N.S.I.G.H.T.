"""The fields computed for every post on save (content hash, URLs, host and language), and the
title the reader shows."""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
from typing import Any, Dict, List, Tuple
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


def _starts_line(title: str, i: int) -> bool:
    """Whether title[i] can open a line glued on: not punctuation that ends or continues a phrase
    (a body's "@user !" or "ИИ , знают" has a space from a tag, not a line break), and not right
    after an opening bracket or quote ("«Смит" is one word)."""
    return title[i] not in ".,;:!?…)]}»”’\"'" and not (unicodedata.category(title[i - 1]) in ("Ps", "Pi") or title[i - 1] in "\"'")


def _glued_first_line(cut: str, content: str | None, whole: bool = False) -> str | None:
    """A cut title that is the body's start with its line breaks dropped (the Telegram bridge joins
    "…у SpaceX" and "Датацентр…" into "SpaceXДатацентр"): the body up to the first space the title
    lacks, which is where the post's first line ended. None when the title keeps every space.

    A `whole` title (not cut, issue 0069: "$500Изменения уже действуют.") ends only where the title
    runs on into the next line's first character; a space a tag left in the body ("@user !",
    "ИИ , знают", "« Смит") is not a line's end. Its own spacing is kept."""
    title, body = clean_text(cut), clean_text(content)
    i = j = 0
    while i < len(title) and j < len(body):
        if title[i] == body[j]:
            i, j = i + 1, j + 1
        elif body[j].isspace() and not title[i].isspace():
            if len(_WORD_RE.findall(body[:j])) >= 2 and (not whole or (_starts_line(title, i) and body[j + 1:j + 2] == title[i])):
                return (title[:i] if whole else body[:j]).rstrip()
            j += 1   # a space after a leading emoji or one word ("🌸 Релизим"), or a tag's
        else:
            return None
    return None


# Words that stand in for a post's text (issue 0069), told by shape: a bracketed word ("[Photo]",
# the Telegram bridge's album pieces), the name of a media kind alone ("Image", Nitter's tweet with no
# words), or a bare address. Such a title says nothing of the post, so the text says it instead.
_ADDRESS = r"(?:https?://|[\w-]+(?:\.[\w-]+)+/)\S*"
_PLACEHOLDER_RE = re.compile(
    r"^(?:\[[^\W\d_]+\]|(?i:photo|video|gif|image|media|audio|sticker|document|file)"
    rf"|{_ADDRESS})$")
_LEADING_ADDRESS_RE = re.compile(rf"^(?:{_ADDRESS}\s+)+")   # a link's preview: its address, then its words
_FINISHED_RE = re.compile(r"[.!?…][\"'»”’)\]]*$")


def _words(line: str, preview: bool = False) -> str:
    """A line as a title's words, a placeholder nothing. `preview`: the text under a placeholder
    title, where a leading address is the link the post shares, its words after it."""
    line = _LEADING_ADDRESS_RE.sub("", line) if preview else line
    return "" if _PLACEHOLDER_RE.match(line) else line


def display_title(title: str | None, content: str | None) -> str:
    """The title the feed and the post page show; the stored title is never changed.

    The text is the title, or the body when the title is empty, a placeholder ("[Photo]", "Image",
    a bare address: issue 0069) or the body's start cut with "…" or "[...]" (a tweet, a Telegram
    post, a GitHub commit). Nitter's "RT by @…: " and "R to @…: " are dropped (who reposted or
    whom it answers is said beside it). Only the first line with words counts. A title's first
    line under 20 characters that ends unfinished ("Day 25/", "BREAKING:": a tweet's title is its
    whole text) runs on into its next lines; a body's short first line is its heading. A title
    the Telegram bridge glued from two lines ("$500Изменения") ends where the body's first line
    did. Title and body are stored plain text, so nothing in them is read as a tag. When the text
    has no words, the stored title stands.
    """
    stored = REPLY_TO_RE.sub("", REPOST_BY_RE.sub("", (title or "").strip()))   # issue 0066
    cut = TRAILING_ELLIPSIS_RE.sub("", stored).strip()
    placeholder = bool(stored) and not _words(clean_text(stored))
    glued = _glued_first_line(cut, content, whole=cut == stored) if cut and not placeholder else None
    from_body = not stored or placeholder or (
        cut != stored and bool(cut) and clean_text(content).startswith(clean_text(cut))
    )
    lines = [words for raw in ((content if from_body else stored) or "").splitlines()
             if (words := _words(clean_text(raw), placeholder))]
    if glued or not lines:
        return _cut(glued or clean_text(stored), False)
    line = lines[0]
    run_on = (not from_body and len(lines) > 1 and len(line) < TITLE_MIN_SENTENCE_CHARS
              and not _FINISHED_RE.search(line))
    return _cut(" ".join(lines) if run_on else line, run_on)


def _cut(line: str, run_on: bool) -> str:
    """A line over 120 characters, or run on, cut at its first sentence end (after 20 characters at
    least), else at the last space within 117 characters, with "…"."""
    if len(line) <= TITLE_MAX_CHARS and not run_on:
        return line
    sentence = SENTENCE_END_RE.search(line, TITLE_MIN_SENTENCE_CHARS - 1)
    if sentence and sentence.end() <= TITLE_MAX_CHARS:
        return line[: sentence.end()]
    if len(line) <= TITLE_MAX_CHARS:
        return line
    head = line[: TITLE_MAX_CHARS - 3]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip() + "…"


_TAG_RE = re.compile(r"(<[^>]*>)")
_BLOCK_TAG_RE = re.compile(r"</?(?:p|br|h[1-6]|div|li|ul|ol|blockquote|hr|figure|section|header|article|table|tr|pre)\b", re.I)
# What a title taken out of a body leaves at its start: breaks, and elements left empty.
_LEFT_AT_START_RE = re.compile(r"^((?:\s*<(?!br\b)[a-z][^>]*>)*)\s*(?:<br\s*/?>\s*|<([a-z][a-z0-9]*)\b[^>]*>\s*</\2>\s*)+", re.I)


def _block_follows(parts: List[str]) -> bool:
    """Whether a line or a block ends here: a break or a block's tag comes before any more words."""
    for part in parts:
        if part.startswith("<"):
            if _BLOCK_TAG_RE.match(part):
                return True
        elif part.strip():
            return False
    return False


def body_after_title(title: str, body: str | None, *, html: bool = False, line: bool = False) -> str | None:
    """The body without the title it starts with (issue 0070: a title taken from the body isn't read
    twice: the post page's heading, then its text). Whitespace and, in HTML, tags and entities don't
    count (HTML codes are read as what they say). The title must be a whole line or sentence of the
    body: it ends a sentence, a line or a block ends with it, or (`line`) it is known to be a line.
    Unchanged when the title is cut ("…"), isn't the body's start, or is all of it."""
    want = re.sub(r"\s+", "", title or "")
    if not body or not want or TRAILING_ELLIPSIS_RE.search(title):
        return body
    parts = _TAG_RE.split(body) if html else [body]
    out, matched = [], 0
    for index, part in enumerate(parts):
        if matched == len(want) or (html and part.startswith("<")):
            out.append(part)
            continue
        text = html_lib.unescape(part)
        at = 0
        while at < len(text) and matched < len(want):
            if not text[at].isspace():
                if text[at] != want[matched]:
                    return body
                matched += 1
            at += 1
        tail = text[at:]
        # "Notes" is not the title of "Notes on X".
        if matched == len(want) and not (line or _FINISHED_RE.search(title) or "\n" in tail[:len(tail) - len(tail.lstrip())]
                                          or (not tail.strip() and _block_follows(parts[index + 1:]))):
            return body
        out.append(html_lib.escape(tail, quote=False) if html else tail)
    rest = "".join(out)
    rest = _LEFT_AT_START_RE.sub(r"\1", rest).strip() if html else rest.strip()
    words = strip_html(rest) if html else rest
    return rest if matched == len(want) and _WORD_RE.search(words or "") else body


# hnrss's item body (issue 0070): four labelled lines, the article's and the discussion's addresses,
# then the points and the comments ("Points: 1675", "# Comments: 1628"). They are the row's counts,
# never its text; a body with both counts is that shape.
_HNRSS_COUNTS_RE = re.compile(r"Points: (\d+)\s*(?:</p>\s*<p>\s*)?# Comments: (\d+)")
_HNRSS_LINE_RE = re.compile(r"(?:<hr\s*/?>\s*)?<p>\s*(?:Article URL|Comments URL|Points|# Comments):.*?</p>\s*"
                            r"|(?:Article URL|Comments URL): \S+\s*|(?:Points|# Comments): \d+\s*", re.S)


def hnrss_counts(content: str | None) -> Dict[str, int] | None:
    """{points, comments} of a Hacker News item as hnrss writes it, else None."""
    match = _HNRSS_COUNTS_RE.search(content or "")
    return {"points": int(match.group(1)), "comments": int(match.group(2))} if match else None


def body_without_feed_lines(body: str | None) -> str | None:
    """A body (text or HTML) without hnrss's four lines; any other body as it is."""
    return _HNRSS_LINE_RE.sub("", body).strip() if body and _HNRSS_COUNTS_RE.search(body) else body


def reading_text(title: str | None, content: str | None, html: str | None = None
                 ) -> Tuple[str, str | None, str | None]:
    """(the title the reader shows, the text and the HTML under it): a feed's own lines out (hnrss),
    and the title out of the body's start when it was taken from it (issue 0070). Where the stored
    text has lost its line breaks (a tweet's, an RSS body's), its HTML says where the first line
    ended: `html` may be only the HTML's start."""
    content, html = body_without_feed_lines(content), body_without_feed_lines(html)
    shown = display_title(title, content)
    html_after = body_after_title(shown, html, html=True)
    return shown, body_after_title(shown, content, line=html_after != html), html_after


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
