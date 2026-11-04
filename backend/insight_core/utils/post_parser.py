"""A post is read once, when it is saved (issue 0076): the one parser, its result one `post_parts`
row per post that every page and the story job read.

The raw post (title, content, content_html) is what was observed and never changes; its parts are
derived from it by the rules here (post_fields, post_links), again whenever those rules change
(`parse_stamp`), so a parse can always be redone. Nothing else calls the read-time rules: a test
fails if a page imports them (tests/test_post_parts.py, checks/compat.py aside).

The shown bodies are stored as cut points into the raw columns (`Body`): the spans of the raw text
kept, read after decoding its HTML codes (`decode_entities`) and joined by line breaks where the
rule put one in for what it cut (`cut_leaves_break`); a copy only where neither says it. Measured
on the lab (41,637 posts): 60.5% need no cut at all.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from .addresses import tweet_author
from .content_fingerprints import clean_text, strip_html
from .post_fields import (REPOST_BY_RE, TRAILING_ELLIPSIS_RE, _squashed)
from .post_fields import (REPLY_TO_RE, TITLE_HTML_CHARS, TITLE_TEXT_CHARS, display_title, hnrss_counts, link_kind,
                          link_post_target, post_title, quote_only, reaction_title, reading_text)
from .post_links import quoted_tweet, quoted_words, reddit_author
from .post_parts import Body, shown

LEAD_CHARS = 300   # a row's or a card's text (the feed shows 280: repo_reader.EXCERPT_CHARS)
_TAGS = re.compile(r"<[^>]+>")
_ANCHOR = 32       # characters a cut is found again by (_cuts); not measured, any length is checked
# A tweet's quote card as Nitter writes it (post_links.QUOTED): a rule, then a <blockquote> citing the
# quoted tweet; and the quoted tweet's bare address in the text above it (issue 0070).
_QUOTE_CARD = re.compile(r"\s*(?:<hr\s*/?>\s*)?<blockquote>(?:(?!</blockquote>).)*?<cite>.*?</blockquote>", re.I | re.S)
_EMPTY_P = re.compile(r"<p>\s*</p>\s*", re.I)


def _cuts(raw: str, want: str, gap: str, here: bool) -> Optional[List[int]]:
    """The kept spans of `raw` that, joined by `gap`, make `want`, found left to right; None when none do.
    Each span is as long as it can be; the next starts where want's next characters are found again in
    raw, or (`here`) right where the last one ended when raw goes on with them (checked by building it:
    a wrong guess is None, never a wrong body)."""
    out: List[int] = []
    i = j = 0
    while j < len(want):
        if out and gap:
            if not want.startswith(gap, j):
                return None
            j += len(gap)
        at = i if here and raw[i:i + 1] == want[j:j + 1] else raw.find(want[j:j + _ANCHOR], i)
        if at < 0:
            return None
        end, k = at, j
        while end < len(raw) and k < len(want) and raw[end] == want[k]:
            end, k = end + 1, k + 1
        out += [at, end]
        i, j = end, k
    return out


def body_of(raw: Optional[str], want: Optional[str]) -> Body:
    """How to store `want`, the shown body of `raw` (Body): no cut, cut points with the fewest flags, else a copy."""
    if want == raw:
        return Body()
    if not want:
        return Body(cut=[])   # nothing shown (reading_text gives None only for no raw body, equal above)
    for decode in (False, True):
        base = html_lib.unescape(raw or "") if decode else raw or ""
        for brk in (False, True):
            for here in (True, False):
                body = Body(cut=_cuts(base, want, "\n" if brk else "", here), decode_entities=decode, cut_leaves_break=brk)
                if body.cut is not None and shown(raw, body) == want:
                    return body
    return Body(copy=want)


def without_quote(html: Optional[str]) -> str:
    """A tweet's HTML without its quote card and the quoted tweet's bare address (issue 0070)."""
    quoted = quoted_tweet(html) or ""
    status = re.escape(quoted.rsplit("/", 1)[-1])
    out = _QUOTE_CARD.sub("", html or "", count=1)
    out = re.sub(rf'<a\b[^>]*href="[^"]*/status/{status}\b[^"]*"[^>]*>[^<\s]*</a>', "", out)
    return _EMPTY_P.sub("", out).strip()


@dataclass
class Parts:
    """One post's `post_parts` row (migration 0060)."""
    title: str                          # the title every place shows (post_fields.post_title)
    title_from: str                     # feed field | first line | linked page | none
    lead: str                           # the shown text's start, as a row reads it (LEAD_CHARS)
    text: Body = field(default_factory=Body)   # the post page's text under its title
    html: Body = field(default_factory=Body)   # ... and its HTML
    quoted: Optional[str] = None        # the tweet it quotes (normalized)
    quote_only: Optional[str] = None    # ... when it has nothing of its own
    folds_into: Optional[str] = None    # ... and it is its own account's: no row of its own (issue 0076)
    subject: Optional[str] = None       # a short reaction's quoted words, "<Name>: <title>": News's lead title
    opening: Optional[str] = None       # the text's start its stored title covered, when more than the title
    folded: Optional[Dict[str, Any]] = None   # a quote's post without the card (the post page, a thread's reply)
    counts: Optional[Dict[str, int]] = None   # hnrss's points and comments, with the shown text's length
    link_target: Optional[str] = None   # the page a link post shares
    link_kind: Optional[str] = None     # page | picture | video
    reply_to: Optional[str] = None      # the account a tweet answers (Nitter's "R to @…")
    author: Optional[str] = None        # Reddit's poster (its footer)
    words: int = 0                      # the words of its HTML (a link post has few)
    quoted_words: Dict[str, str] = field(default_factory=dict)   # page -> its own words as quoted (0070)
    warnings: List[str] = field(default_factory=list)            # where a rule guessed

    def digest(self) -> str:
        """What the row says, hashed: a re-parse writes only the rows whose digest changed."""
        return hashlib.md5(json.dumps(asdict(self), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _title_from(title: Optional[str], shown_title: str) -> str:
    if not shown_title:
        return "none"
    stored = clean_text(REPLY_TO_RE.sub("", re.sub(r"^RT by @\w+: ", "", (title or "").strip())))
    squash = lambda s: re.sub(r"\s+", "", s.rstrip("…"))   # noqa: E731
    if stored and squash(stored).startswith(squash(shown_title)):
        return "feed field"
    return "linked page" if re.fullmatch(r"[\w.-]+\.[a-z]{2,}(?:/\S*)?", shown_title) else "first line"


def _opening(title: Optional[str], content: Optional[str], shown_title: str) -> Optional[str]:
    """The text's start as long as its stored title, when that title is the text's start (a bridge's: the
    post's first characters, its lines glued) and says more than the title shown; spaced as the text is."""
    stored = TRAILING_ELLIPSIS_RE.sub("", REPLY_TO_RE.sub("", REPOST_BY_RE.sub("", (title or "").strip()))).strip()
    want, text = _squashed(stored), clean_text(content)
    if not want or len(want) <= len(_squashed(shown_title.rstrip("…"))) or not _squashed(text).startswith(want):
        return None
    count = 0
    for i, ch in enumerate(text):
        count += not ch.isspace()
        if count == len(want):
            return text[:i + 1]
    return None


def parse(title: Optional[str], content: Optional[str], html: Optional[str], url: Optional[str] = None) -> Parts:
    """Every part of a stored post, from its raw title, text and HTML (and its address: whose tweet)."""
    shown_title, text, body = reading_text(title, content, html)
    text_head, html_head = content and content[:TITLE_TEXT_CHARS], html and html[:TITLE_HTML_CHARS]
    _, row_text, _ = reading_text(title, text_head, html_head)   # a row reads the bodies' start (repo_reader._item)
    counts = hnrss_counts(text_head)
    quoted = quoted_tweet(html)
    only = quote_only(html)
    folded = None
    if quoted:
        own = without_quote(html)
        folded = {"html": own}
        if not only:
            _, f_text, f_html = reading_text(title, strip_html(own), own)
            folded.update(text=f_text, body=f_html)
    target = link_post_target(html)
    reply = REPLY_TO_RE.match(title or "")
    title_from = _title_from(title, shown_title)
    account = tweet_author(url)
    folds = only if only and account and (tweet_author(only) or "").lower() == account.lower() else None
    warnings = ["title from the first line"] if title_from == "first line" else []
    if title_from == "first line" and html and "\n" not in (text_head or "") and post_title(title, content, None) != shown_title:
        warnings.append("line breaks recovered from HTML")
    return Parts(
        title=shown_title, title_from=title_from, lead=clean_text(row_text)[:LEAD_CHARS],
        text=body_of(content, text), html=body_of(html, body),
        quoted=quoted, quote_only=only, folds_into=folds, subject=reaction_title(html_head),
        opening=_opening(title, text_head, shown_title), folded=folded,
        counts={**counts, "chars": len(row_text or "")} if counts else None,
        link_target=target, link_kind=link_kind(target) if target else None,
        reply_to=reply.group(1) if reply else None, author=reddit_author(html),
        words=len(_TAGS.sub("", html or "").split()), quoted_words=quoted_words(html), warnings=warnings,
    )


@lru_cache(maxsize=1)
def parse_stamp() -> str:
    """The rules the stored parts were made by (issue 0071's stamps): what the parser makes of the
    sample's posts (utils/stamps.py). Another stamp parses every post again, writing only what changed."""
    from . import stamps
    return stamps.fingerprint([asdict(parse(*post)) for post in stamps.PARSED])


__all__ = ["Body", "Parts", "parse", "parse_stamp", "shown", "body_of", "without_quote", "LEAD_CHARS"]
