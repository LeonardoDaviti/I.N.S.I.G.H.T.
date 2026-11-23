"""What a title is when two are compared (one rule, never what is shown): its HTML entities decoded, styled letters
as plain (NFKC: "𝙻𝙵𝙼𝟹" is "LFM3"), lower case, curly quotes straight, its spaces one. The story job, News's names
(`comparable`, which keeps the case), the reader and the saver (SQL's post_title_key: the same steps) compare by it.
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
