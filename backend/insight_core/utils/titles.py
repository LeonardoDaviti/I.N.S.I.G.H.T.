"""What a title is when two are compared (issue 0071: one rule, never what is shown): its HTML
entities decoded, styled letters as plain (NFKC: "𝙻𝙵𝙼𝟹" is "LFM3", a no-break space a space,
issue 0070), lower case, curly quotes straight, its spaces one.

The story job (story_rules.title_key: the words of it), names in titles (news_rules: `comparable`,
which keeps the case a name is told by), the reader (a heading that repeats the page's title,
parsing) and the saver (SQL's post_title_key, migration 0055: the same steps) compare by it.
"""
from __future__ import annotations

import html
import unicodedata
from typing import Optional

QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def comparable(text: Optional[str]) -> str:
    """Text as it is compared, its case kept: entities decoded, styled letters as plain (NFKC)."""
    return unicodedata.normalize("NFKC", html.unescape(text or ""))


def title_key(text: Optional[str]) -> str:
    """A title as two are compared: comparable, lower case, straight quotes, single spaces."""
    return " ".join(comparable(text).lower().translate(QUOTES).split())


__all__ = ["QUOTES", "comparable", "title_key"]
