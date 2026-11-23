"""Watching stored pages for changes: the cheap checks, cheapest first.

A source with settings.watch_changes on a kind that watches has a rotating slice of its stored pages re-checked in
its fetch's host slot: a conditional GET (304: unchanged); else, when the page stated its modified date, its first
HEAD_BYTES; else the whole page through the kind's reader and its article text's hash (so ads and timestamps never
count). A changed page comes back as a post without its date, for the saver to judge; every check is recorded with
when to look again (db/repo_page_watch.py next_check).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Sequence

from insight_core.ingestion.http import AddressMemory, HttpError, KindHttp, Validators
from insight_core.ingestion.kinds import parsing
from insight_core.utils.text_changes import text_hash

logger = logging.getLogger("insight.ingestion.page_changes")

HEAD_BYTES = 48_000      # a page's start read for its modified date
WATCH_SLICE = 50         # pages one fetch re-checks, at most: a 700-page site in about two weeks
GONE_STATUSES = (404, 410)

CheckOutcome = Literal["unchanged", "changed", "gone", "failed"]
# The kind's reader: the post the page html at url is, or None when it is no article.
ReadPost = Callable[[str, str], Optional[Dict[str, Any]]]


@dataclass(frozen=True)
class WatchedPage:
    """One stored page due for a check. text_hash is of its stored article text; modified the
    date it stated last time (None: it states none, or was never checked); head_missed: that
    date was not within HEAD_BYTES last time, so the head alone cannot tell."""

    post_id: str
    url: str
    text_hash: str
    modified: Optional[str] = None
    validators: Validators = field(default_factory=Validators)
    head_missed: bool = False


@dataclass
class PageCheck:
    post_id: str
    url: str
    outcome: CheckOutcome
    text_hash: str
    modified: Optional[str]
    head_missed: bool
    validators: Optional[Validators] = None
    bytes_read: int = 0
    post: Optional[Dict[str, Any]] = None      # changed: the page as read, for the saver


async def check_page(http: KindHttp, page: WatchedPage, read_post: ReadPost, memory: AddressMemory) -> PageCheck:
    """One page through the cheap checks. Raises only a limiting HttpError (a 429 or a timeout)."""
    check = PageCheck(page.post_id, page.url, "unchanged", page.text_hash, page.modified, page.head_missed)
    head_first = bool(page.modified) and not page.head_missed
    try:
        answer = await memory.get(http, page.url, max_bytes=HEAD_BYTES if head_first else None)
        check.validators = memory.learned.get(page.url)
        if answer.not_modified:
            return check
        body = answer.body or b""
        check.bytes_read = len(body)
        if head_first:
            head_date = parsing.page_modified(answer.text)
            if head_date == page.modified:
                return check
            if len(body) >= HEAD_BYTES:      # cut: the article is past the head
                full, _ = await http.get_text(answer.url)
                check.bytes_read += len(full.encode("utf-8"))
            else:
                full = answer.text
        else:
            full = answer.text
    except HttpError as exc:
        if exc.limiting:
            raise
        check.outcome = "gone" if exc.status in GONE_STATUSES else "failed"
        logger.info("Change watch: %s could not be read (%s)", page.url, str(exc)[:200])
        return check
    check.modified = parsing.page_modified(full)
    # A date further in than HEAD_BYTES: the next check reads the whole page straight away.
    check.head_missed = bool(check.modified) and parsing.page_modified(full[:HEAD_BYTES]) is None
    post = read_post(page.url, full)
    if post is None:
        check.outcome = "gone"           # no article there now: the stored text stays
        return check
    check.text_hash = text_hash(post.get("content"))
    if check.text_hash != page.text_hash or check.modified != page.modified:
        # The stored address and date stay: the post is updated in place, never moved.
        check.outcome, check.post = "changed", {**post, "url": page.url, "date": None}
    return check


async def check_pages(http: KindHttp, pages: Sequence[WatchedPage], read_post: ReadPost, *,
                      now: datetime, delay_s: float = 1.0, full: bool = False,
                      sleep: Optional[Callable[[float], Awaitable[None]]] = None) -> List[PageCheck]:
    """Check pages in order, delay_s apart. A host limiting us ends the slice: the checks so far
    are returned and the rest wait for the next fetch. full sends no validators ("Fetch now")."""
    memory = AddressMemory({page.url: page.validators for page in pages if page.validators},
                           now=now, full=full)
    checks: List[PageCheck] = []
    for index, page in enumerate(pages):
        if index:
            await (sleep or http.sleep)(delay_s)
        try:
            checks.append(await check_page(http, page, read_post, memory))
        except HttpError as exc:
            logger.info("Change watch: %s is limiting us (%s); %s pages left for next time",
                        page.url, str(exc)[:200], len(pages) - index)
            break
    return checks


def watching(source: Any, kind: Any) -> bool:
    """Whether a fetch of this source re-checks its pages: the owner's switch, on a kind that can."""
    return bool(getattr(kind, "watches", False) and (source.get("settings") or {}).get("watch_changes"))


__all__ = ["HEAD_BYTES", "WATCH_SLICE", "PageCheck", "WatchedPage", "check_page", "check_pages", "watching"]
