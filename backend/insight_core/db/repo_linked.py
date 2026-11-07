"""Linked, not stored (issue 0084 B, decision 1): per followed source, its own pages that stored posts
link and that no stored post is.

One function, `linked_not_stored`, for the Archive section's count, the job that fetches them, and
0114's wanted links (the same set with `since`: only the links of posts published since then). And
`page_source`, the same rule for one address: the followed source a page you save belongs to (issue 0122).

- **Whose page** a link is: utils/linked_rules.OwnPages, learned from every source's stored posts (the
  shapes of its post pages on its publication; on a platform, the account it follows, as 0065 reads it).
  A followed source is an enabled one.
- **The links**: every stored post's kept links (post_links, not a source's signature), and each post's
  links to its own publication, which post_links never keeps (linked_rules.own_links, read from the
  stored HTML), its signature left out.
- **Not stored**: no post is at that address (normalized_url, or its url normalized when it has none:
  issue 0129), was moved there (metadata.moved_to, issue 0108), or names it as its canonical address.
- **One page at two hosts** (issue 0129): a source's page at two of its publications (its platform's
  address and its own domain) is one page (OwnPages.same_page), counted by its distinct linking posts,
  at the address OwnPages.preferred puts first; a post of the source stored at either is it stored.

Read only; takes the caller's cursor.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from psycopg import Cursor

from insight_core.db.repo_stories import SourceFacts, source_account
from insight_core.utils.addresses import host_of, site_of
from insight_core.utils.linked_rules import OwnPages, own_links, signature_links
from insight_core.utils.post_links import source_kind
from insight_core.utils.url_normalization import normalize_url

POST_DATE = "COALESCE(p.published_at, p.fetched_at)"
HTML_BATCH = 500
LAST = datetime.max.replace(tzinfo=timezone.utc)
PageKey = Tuple[str, str, str]   # OwnPages.same_page: (source, path, query)


@dataclass(frozen=True)
class LinkedPage:
    url: str                                  # normalized
    source_id: str                            # the followed source whose page it is
    posts: int                                # stored posts linking it
    first_linked_at: Optional[datetime]       # the first of them, by its date
    last_linked_at: Optional[datetime]
    by: Tuple[str, ...] = ()                  # the linking posts (issue 0114: is one of them in a story?)


def linked_not_stored(cur: Cursor, *, source_ids: Optional[Iterable[str]] = None,
                      since: Optional[datetime] = None) -> Dict[str, List[LinkedPage]]:
    """{followed source: its pages linked and not stored, the most linked first, then the first linked},
    for every followed source or those of `source_ids`; with `since`, only links of posts published
    since then. A source with none is left out."""
    followed = _followed(cur)
    wanted = set(followed) if source_ids is None else set(followed) & {str(s) for s in source_ids}
    if not wanted:
        return {}
    own, addresses, homes = _own_pages(cur, followed)

    # A page is its OwnPages.same_page key: one page at two of a source's publications is one (0129).
    links: Dict[PageKey, Dict[str, Optional[datetime]]] = defaultdict(dict)   # page -> {linking post: its date}
    forms: Dict[PageKey, Set[str]] = defaultdict(set)                          # page -> its addresses seen

    def keep(url: str, post_id: str, at: Optional[datetime]) -> None:
        found = own.page(url)
        if found and found[0] in wanted:
            key = own.same_page(found[1])
            forms[key].add(found[1])
            links[key][post_id] = at

    # Kept links, on the sites the wanted sources' pages are on (a tweet's is x.com).
    sites = sorted({site_of(host_of(url)) for sid in wanted for url in addresses.get(sid, ())
                    if site_of(host_of(url)) in homes[sid] or own.owner(url) == sid} - {""})
    cur.execute(f"""SELECT pl.target_url, p.id::text, {POST_DATE} FROM post_links pl JOIN posts p ON p.id = pl.post_id
                    WHERE NOT pl.boilerplate AND pl.target_site = ANY(%s)
                      AND (%s::timestamptz IS NULL OR {POST_DATE} >= %s)""", (sites, since, since))
    for url, post_id, at in cur.fetchall():
        keep(url, post_id, at)
    # Links to a post's own publication, read from the HTML of the posts on the wanted sources' hosts.
    hosts = sorted({host_of(url) for sid in wanted for url in addresses.get(sid, ()) if own.owner(url) == sid} - {""})
    for source_links, dates in _own_links(cur, hosts, since):
        noise = signature_links(source_links)
        for post_id, urls in source_links.items():
            for url in urls:
                if url not in noise:
                    keep(url, post_id, dates[post_id])
    # Stored: at an address seen, or a post of the source at another of its forms (a page at its own
    # domain stored, linked at its platform's address).
    stored = {own.same_page(url) for url in _stored(cur, sorted({url for urls in forms.values() for url in urls}))}
    stored |= {own.same_page(url) for sid in wanted for url in addresses.get(sid, ())}
    out: Dict[str, List[LinkedPage]] = defaultdict(list)
    for key, by in links.items():
        if key in stored:
            continue
        source_id = key[0]
        url = min(forms[key], key=lambda form: own.preferred(source_id, form))
        dates = [at for at in by.values() if at is not None]
        out[source_id].append(LinkedPage(url, source_id, len(by), min(dates, default=None), max(dates, default=None),
                                         tuple(sorted(by))))
    for pages in out.values():
        pages.sort(key=lambda page: (-page.posts, page.first_linked_at or LAST, page.url))
    return dict(out)


def page_source(cur: Cursor, url: str) -> Optional[str]:
    """The followed (enabled) source whose post page this address is (OwnPages.owner, the rule above),
    else None. Issue 0122: a page you save is first looked for under its source."""
    followed = _followed(cur)
    if not followed or not normalize_url(url):
        return None
    own, _, _ = _own_pages(cur, followed)
    return own.owner(url)


def _followed(cur: Cursor) -> Dict[str, Tuple[str, Optional[str], Optional[str]]]:
    """The followed sources: enabled, not Saved. {id: (kind, platform, address)}."""
    cur.execute("SELECT id::text, platform, handle_or_url, enabled FROM sources")
    out = {}
    for sid, platform, handle, enabled in cur.fetchall():
        kind = source_kind(platform, handle)
        if enabled and kind != "saved":
            out[sid] = (kind, platform, handle)
    return out


def _own_pages(cur: Cursor, followed: Dict[str, Tuple[str, Optional[str], Optional[str]]]
               ) -> Tuple[OwnPages, Dict[str, List[str]], Dict[str, Set[str]]]:
    """(OwnPages learned from the followed sources' stored posts, their posts' addresses, their sites)."""
    cur.execute("SELECT source_id::text, COALESCE(normalized_url, url) FROM posts WHERE source_id = ANY(%s::uuid[])",
                (sorted(followed),))
    addresses: Dict[str, List[str]] = defaultdict(list)
    for sid, url in cur.fetchall():
        addresses[sid].append(url)
    facts = SourceFacts(cur)
    homes = {sid: {facts.handle_site.get(sid), facts.home_site(sid)} - {None, ""} for sid in followed}
    own = OwnPages({sid: (kind, source_account(platform, handle), homes[sid], addresses.get(sid, ()))
                    for sid, (kind, platform, handle) in followed.items()},
                   address_publications={sid: facts.handle_host.get(sid, "") for sid in followed})
    return own, addresses, homes


def _own_links(cur: Cursor, hosts: List[str], since: Optional[datetime]
               ) -> Iterable[Tuple[Dict[str, List[str]], Dict[str, Optional[datetime]]]]:
    """Per source, ({post: its links to its own publication}, {post: its date}) of the posts on these
    hosts with HTML, a batch of rows at a time (the HTML stays in the database's pages until read)."""
    if not hosts:
        return
    cur.execute(f"""SELECT p.source_id::text, p.id::text, COALESCE(p.normalized_url, p.url), p.content_html, {POST_DATE}
                    FROM posts p WHERE p.url_host = ANY(%s) AND p.content_html IS NOT NULL
                      AND (%s::timestamptz IS NULL OR {POST_DATE} >= %s)
                    ORDER BY p.source_id""", (hosts, since, since))
    current: Optional[str] = None
    found: Dict[str, List[str]] = {}
    dates: Dict[str, Optional[datetime]] = {}
    while True:
        rows = cur.fetchmany(HTML_BATCH)
        for sid, post_id, url, content_html, at in rows:
            if sid != current:
                if current is not None:
                    yield found, dates
                current, found, dates = sid, {}, {}
            found[post_id] = own_links(content_html, url)
            dates[post_id] = at
        if not rows:
            break
    if current is not None:
        yield found, dates


def _stored(cur: Cursor, urls: List[str]) -> Set[str]:
    """Which of these normalized addresses a stored post is at, moved to, or names as its canonical."""
    if not urls:
        return set()
    cur.execute("SELECT normalized_url FROM posts WHERE normalized_url = ANY(%s)", (urls,))
    stored = {url for (url,) in cur.fetchall()}
    # A post stored with no normalized address (1,146 of 49k on the server's copy, 2026-11-05): its
    # address, normalized as the links are.
    wanted = set(urls)
    cur.execute("SELECT url FROM posts WHERE normalized_url IS NULL")
    stored |= {url for (raw,) in cur.fetchall() if (url := normalize_url(raw)) in wanted}
    cur.execute("SELECT metadata->>'moved_to' FROM posts WHERE metadata->>'moved_to' = ANY(%s)", (urls,))
    stored |= {url for (url,) in cur.fetchall()}
    # A canonical address other than the post's own (128 of 49k posts on the server's copy).
    cur.execute("SELECT canonical_url FROM posts WHERE canonical_url IS DISTINCT FROM normalized_url AND canonical_url <> url")
    stored |= {url for (canonical,) in cur.fetchall() if (url := normalize_url(canonical)) in wanted}
    return stored


__all__ = ["LinkedPage", "linked_not_stored", "page_source"]
