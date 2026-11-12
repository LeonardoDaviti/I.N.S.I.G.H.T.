"""Whose row a page is (issue 0167): a page's own source takes it back from a source that stored it first.

A post is stored once, at its address (posts.url is unique). An aggregator (Hacker News, a link blog, a trending
list) that stores a company's page first used to keep it for ever: the company's own followed source (its feed, its
page watch) fetched the same address later and only updated that row, which stayed the aggregator's.

The rule, one for the live save and the repair (scripts/repair_own_pages_0167.py):
  - **A source owns a page** when it is a website source (a feed, a page watch, a Substack: `source_kind` "site",
    never a platform account, Hacker News or Saved) whose own address is at the page's publication (`page_site`:
    the host without www., and without a blog., news. or newsroom. label, so a site's blog and its pages are one;
    two writers' subdomains of one platform are two). The live save adds the evidence that the source's own fetch
    brought the address (its feed or page watch lists it); the repair asks the listing.
  - **It takes the row back** from a holder that doesn't own it: the row (its id, so every story, reading, label,
    News row and reader state on it) moves to the owner; the holder keeps a post of its own that cites the page
    (`citation_address`): the page's address with CITATION_FRAGMENT and the holder's id, its text, date and
    read state as they were, and metadata.cites {url, normalized_url, post_id}.
  - **A holder that owns it too** (two sources of one site: a blog's feed and a page watch of one section) keeps it,
    as before. A platform's post address (a tweet, a Telegram or Reddit post) never moves: one post, its reposts by.
  - **The aggregator's later fetches** of a page its owner holds update its citation, never the owner's row.
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
