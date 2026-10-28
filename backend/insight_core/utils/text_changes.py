"""What changed in a page's article text between two reads (issue 0039): the text hash a
watched page is compared by, and the short summary an update shows ("+2 sections, 1,400 words").

Pure functions over the shared reader's output (a post's content and content_html), so ads,
menus and timestamps outside the article never count. No version is kept: the summary is all
that is left of the old text once the new one is saved.
"""
from __future__ import annotations

import difflib
import hashlib
import re
from typing import Any, Dict, List, Optional

from insight_core.utils.content_fingerprints import WHITESPACE_RE, strip_html

# A change smaller than this many words, with no section added or removed, is tiny (a typo,
# a link, a reworded sentence): the new text is kept, the post does not come back.
MIN_CHANGED_WORDS = 50
# Two replaced runs longer than this are counted whole, not word by word (difflib is quadratic).
WORD_DIFF_MAX = 5000

BLOCK_END_RE = re.compile(r"(?is)</(?:p|h[1-6]|li|blockquote|pre|figcaption|tr|div)>|<br\s*/?>|\n")
HEADING_RE = re.compile(r"(?is)<h[1-6]\b[^>]*>(.*?)</h[1-6]>")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def text_hash(content: Optional[str]) -> str:
    """The article text's fingerprint: whitespace runs as one space, so re-wrapping is no change."""
    return hashlib.sha256(WHITESPACE_RE.sub(" ", content or "").strip().encode("utf-8")).hexdigest()


def _blocks(content: Optional[str], content_html: Optional[str]) -> List[str]:
    """The text's paragraphs: the article html's blocks, else its sentences (plain text has no
    line breaks: strip_html makes every run of whitespace one space)."""
    if content_html:
        blocks = [strip_html(part) for part in BLOCK_END_RE.split(content_html)]
    else:
        blocks = SENTENCE_RE.split(WHITESPACE_RE.sub(" ", content or "").strip())
    return [block for block in blocks if block]


def _headings(content_html: Optional[str]) -> List[str]:
    return [text for match in HEADING_RE.finditer(content_html or "") if (text := strip_html(match.group(1)))]


def _words(blocks: List[str]) -> List[str]:
    return " ".join(blocks).split()


def change_summary(old_content: Optional[str], new_content: Optional[str],
                   old_html: Optional[str] = None, new_html: Optional[str] = None) -> Dict[str, int]:
    """{words, words_added, words_removed, sections_added, sections_removed}: words is the new
    text's length; added and removed are counted paragraph by paragraph, then word by word
    inside a replaced paragraph, so a fixed typo is one word, not the paragraph twice."""
    old, new = _blocks(old_content, old_html), _blocks(new_content, new_html)
    added = removed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        before, after = _words(old[i1:i2]), _words(new[j1:j2])
        if op == "replace" and len(before) <= WORD_DIFF_MAX and len(after) <= WORD_DIFF_MAX:
            for word_op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
                if word_op != "equal":
                    removed += a2 - a1
                    added += b2 - b1
        else:
            removed += len(before)
            added += len(after)
    old_heads, new_heads = set(_headings(old_html)), set(_headings(new_html))
    return {
        "words": len(_words(new)),
        "words_added": added,
        "words_removed": removed,
        "sections_added": len(new_heads - old_heads),
        "sections_removed": len(old_heads - new_heads),
    }


def meaningful(summary: Dict[str, Any]) -> bool:
    """Worth bringing the post back: a section added or removed, or MIN_CHANGED_WORDS words changed."""
    return bool(summary.get("sections_added") or summary.get("sections_removed")
                or (summary.get("words_added") or 0) + (summary.get("words_removed") or 0) >= MIN_CHANGED_WORDS)


__all__ = ["MIN_CHANGED_WORDS", "change_summary", "meaningful", "text_hash"]
