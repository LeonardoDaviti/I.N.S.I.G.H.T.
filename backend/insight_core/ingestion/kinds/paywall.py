"""A page that says it is for paying readers (issue 0167, part 3): read from the page's own standard markers.

A page read that finds a paywall says so (metadata.paywalled, "for paid subscribers"), instead of "its page held
nothing longer". Only what a page states about itself counts, never a site's name:
  - **schema.org's `isAccessibleForFree`** false: the structured data publishers give search engines for paywalled
    content, as JSON-LD (`"isAccessibleForFree": false`, or "False"/"false" as a string, also inside `hasPart`) or as
    microdata (`itemprop="isAccessibleForFree" content="False"`);
  - **Open Graph's `article:content_tier`** "locked" (a metered page is readable: not a paywall);
  - **Substack's own answer for the post**: the page's `_preloads` names the post's `audience` "only_paid" or
    "founding" (paid) or "only_subscribers" (subscribers only). Read from the post's own object, never from another
    post the page lists (a paid recommendation on a free post's page is no paywall).
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

# schema.org's flag, as JSON (a boolean or its string) or as microdata, either attribute order.
_FREE_JSON = re.compile(r'"isAccessibleForFree"\s*:\s*(?:false|"false")', re.I)
_FREE_MICRODATA = re.compile(
    r"""<[^>]*\bitemprop\s*=\s*["']isAccessibleForFree["'][^>]*\bcontent\s*=\s*["']false["']"""
    r"""|<[^>]*\bcontent\s*=\s*["']false["'][^>]*\bitemprop\s*=\s*["']isAccessibleForFree["']""", re.I)
_CONTENT_TIER = re.compile(
    r"""<meta\b[^>]*(?:property|name)\s*=\s*["']article:content_tier["'][^>]*\bcontent\s*=\s*["']locked["']"""
    r"""|<meta\b[^>]*\bcontent\s*=\s*["']locked["'][^>]*(?:property|name)\s*=\s*["']article:content_tier["']""", re.I)
# Substack's page state: window._preloads = JSON.parse("<a JSON string>")
_PRELOADS = re.compile(r'window\._preloads\s*=\s*JSON\.parse\(\s*("(?:[^"\\]|\\.)*")\s*\)', re.S)
PAID_AUDIENCES = frozenset({"only_paid", "founding", "only_subscribers"})


def _preloaded_audience(page: str) -> Optional[str]:
    """The audience of the post a Substack page is (its _preloads' `post`), else None."""
    found = _PRELOADS.search(page)
    if not found:
        return None
    try:
        state: Any = json.loads(json.loads(found.group(1)))
    except (ValueError, TypeError):
        return None
    post = state.get("post") if isinstance(state, dict) else None
    audience = post.get("audience") if isinstance(post, dict) else None
    return audience if isinstance(audience, str) else None


def marker(page: Optional[str]) -> Optional[str]:
    """Why the page is for paying readers (the marker found), or None."""
    if not page:
        return None
    if _FREE_JSON.search(page) or _FREE_MICRODATA.search(page):
        return "isAccessibleForFree"
    if _CONTENT_TIER.search(page):
        return "content_tier"
    audience = _preloaded_audience(page)
    if audience in PAID_AUDIENCES:
        return f"audience:{audience}"
    return None


__all__ = ["PAID_AUDIENCES", "marker"]
