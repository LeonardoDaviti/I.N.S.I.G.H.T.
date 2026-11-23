"""Whose row a page is (0167): a page's own source takes it back from a source that stored it first. One rule for the
live save and the repair (scripts/repair_own_pages_0167.py).

A post is stored once, at its address. A source owns a page when it is a website source (`source_kind` "site") whose
own address is at the page's publication (`page_site`). It takes the row back from a holder that doesn't own it: the
row (its id, so every story, reading, label and reader state on it) moves to the owner; the holder keeps a post of its
own citing the page (`citation_address`, metadata.cites). A holder that owns it too keeps it. A platform's post address
never moves. The aggregator's later fetches update its citation, never the owner's row.
"""
from __future__ import annotations

from typing import Optional

from insight_core.utils.addresses import blog_site, host_of, publication_of
from insight_core.utils.post_fields import CITATION_FRAGMENT
from insight_core.utils.post_links import source_kind
from insight_core.utils.url_normalization import normalize_url

OWNER_KIND = "site"      # source_kind of a website source (a feed, a page watch, a Substack publication)


def page_site(url: Optional[str]) -> str:
    """Whose publication an address is at ("" for none): its host without www., and without a blog., news. or
    newsroom. label (addresses.blog_site). Not the registrable site: writers at two subdomains of one platform
    (a newsletter host's) are two publications."""
    host = publication_of(host_of(normalize_url(url) or url or ""))
    return blog_site(host) if host else ""


def owns(platform: Optional[str], handle: Optional[str], url: Optional[str]) -> bool:
    """Whether a source (platform, handle_or_url) owns the page at `url`: a website source whose own address is on
    the page's site."""
    if (platform or "").lower() == "saved" or source_kind(platform, handle) != OWNER_KIND:
        return False
    site = page_site(url)
    return bool(site) and site == page_site(handle)


def citation_address(normalized_page: str, holder_id: str) -> str:
    """The address of a holder's post citing a page its owner holds: the page's (normalized, no fragment), with
    CITATION_FRAGMENT and the holder's id. A fragment starting "!/" is kept by normalize_url, so the citation has an
    address of its own (never the page's), and a browser opening it opens the page."""
    return f"{normalized_page.split('#', 1)[0]}{CITATION_FRAGMENT}{holder_id}"


def is_citation_address(url: Optional[str]) -> bool:
    return CITATION_FRAGMENT in (url or "")


__all__ = ["OWNER_KIND", "citation_address", "is_citation_address", "owns", "page_site"]
