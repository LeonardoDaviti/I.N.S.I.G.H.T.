"""The app's functions the checks call, imported so an older checkout still runs them (issue 0075:
realdata-check.sh copies this package into main's tree, or a past commit's, to snapshot it). A version
that stores each post's parts (issue 0076) is read from them, as its pages read it; the parsers are
imported here on purpose (the import guard of tests/test_post_parts.py exempts this file)."""
from __future__ import annotations

from typing import Callable, Optional, Tuple

TITLE_TEXT_CHARS = 4000
TITLE_HTML_CHARS = 2000


def title_function() -> Callable[..., str]:
    """The title every page shows a stored post by: post_title (0072 D1), else display_title."""
    try:
        from insight_core.utils.post_fields import post_title
        return post_title
    except ImportError:   # before 0072 D1
        from insight_core.utils.post_fields import display_title
        return display_title


def title_window() -> Tuple[int, int]:
    """How much of the text and the HTML a title reads (title_columns): (text chars, HTML chars)."""
    try:
        from insight_core.utils.post_fields import TITLE_HTML_CHARS as html, TITLE_TEXT_CHARS as text
        return text, html
    except ImportError:
        return TITLE_TEXT_CHARS, TITLE_HTML_CHARS


def reading_function() -> Optional[Callable[..., Tuple[str, Optional[str], Optional[str]]]]:
    """reading_text(title, content, html) -> (title, text, html) as the post page shows them, if this
    version has it."""
    try:
        from insight_core.utils.post_fields import reading_text
        return reading_text
    except ImportError:
        return None


def link_target_function() -> Optional[Callable[[Optional[str]], Optional[str]]]:
    try:
        from insight_core.utils.post_fields import link_post_target
        return link_post_target
    except ImportError:
        return None


def stored_parts():
    """(BODY_COLUMNS, body) when this version reads each post's stored parts (issue 0076: post_parts, as
    every page reads them), else None: the checks read what the pages read."""
    try:
        from insight_core.db.repo_post_parts import BODY_COLUMNS, body
        return BODY_COLUMNS, body
    except ImportError:
        return None


def normalize(url: str) -> str:
    from insight_core.utils.url_normalization import normalize_url
    try:
        return normalize_url(url) or url
    except ValueError:
        return url


def phrases_function() -> Optional[Callable[[Optional[str]], set]]:
    """news_rules.phrases(title): where a title says a name, as this version's name rule reads it (issue 0104)."""
    try:
        from insight_core.utils.news_rules import phrases
        return phrases
    except ImportError:
        return None
