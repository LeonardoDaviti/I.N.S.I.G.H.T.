"""Base for the seven site adapters. BaseSourceAdapter implements SourceKind directly.

A site adapter is a source kind like any other (spec §D.2): it takes the shared KindHttp,
uses the pure helpers in ingestion/kinds/parsing.py, and yields one ArchivePage per page
of its archive. Its politeness profile is a host lock with PAGE_DELAY_SECONDS between pages.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, ClassVar, Dict, List, Optional, Sequence

from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    SKIP_NO_POST,
    SKIP_STORED,
    SKIP_UNREADABLE,
    UNREADABLE,
    RateLimit,
    Source,
    resume_counts,
    skipped_counts,
)


class BaseSourceAdapter(BaseKind):
    """Shared contract for non-standard source acquisition paths."""

    adapter_type: ClassVar[str] = "base"
    # The discovered index is the whole archive; Gwern overrides (candidate pages).
    available_basis = "exact"
    page_based = True        # its posts come from the site's own lists (issue 0039)
    reads_posts = True       # read_post: one page of its site, as the site reader reads it (issue 0084 B)
    PAGE_DELAY_SECONDS: ClassVar[float] = 1
    # Checkpoint modes this adapter writes; a checkpoint is resumable when its mode is one
    # of these and it carries RESUME_KEY.
    CHECKPOINT_MODES: ClassVar[frozenset[str]] = frozenset({"site_index"})
    RESUME_KEY: ClassVar[str] = "next_index"
    PAGE_SIZE: ClassVar[int] = 20
    # Every entry its index lists is a post (an issue of a newsletter): a run of them read as no post means the
    # site's layout changed, not that they are category pages (issue 0130 B2).
    LISTS_ONLY_POSTS: ClassVar[bool] = False

    def __init__(self, http: Any):
        self.http = http

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.name = cls.adapter_type
        cls.profile = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=cls.PAGE_DELAY_SECONDS)

    async def read_post(self, source: Source, url: str) -> Optional[Dict[str, Any]]:
        """One page of the site as its post, read as any website's (page_watch.read_page_post)."""
        from insight_core.ingestion.kinds.page_watch import read_page_post   # page_watch imports this module

        return await read_page_post(self.http, source, url, adapter=self.adapter_type)

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return (
            isinstance(checkpoint, dict)
            and checkpoint.get("mode") in self.CHECKPOINT_MODES
            and checkpoint.get(self.RESUME_KEY) is not None
        )

    async def index_pages(
        self,
        source: Source,
        entries: Sequence[Any],
        target: int,
        checkpoint: Optional[dict],
        fetch_one: Callable[[Source, Any], Awaitable[Any]],
        *,
        stored: Optional[set] = None,
    ) -> AsyncIterator[ArchivePage]:
        """Archive a discovered entry list in PAGE_SIZE batches, one ArchivePage per batch.

        The checkpoint carries next_index into `entries`, so a resumed run continues where
        the last page ended. Entries whose fetch yields nothing still advance the index.
        `stored`: the addresses already stored, left unread (issue 0130 B4). The checkpoint's
        "skipped" counts why an entry added nothing: stored, no post (fetch_one answered None),
        unreadable (it answered UNREADABLE).
        """
        collected, pages_fetched = resume_counts(checkpoint)
        skipped = skipped_counts(checkpoint)
        next_index = int((checkpoint or {}).get("next_index") or 0)
        mode = next(iter(self.CHECKPOINT_MODES))

        while collected < target and next_index < len(entries):
            batch = entries[next_index: next_index + min(self.PAGE_SIZE, target - collected)]
            if not batch:
                break

            posts: List[Dict[str, Any]] = []
            for entry in batch:
                if stored and _entry_url(entry) in stored:
                    skipped[SKIP_STORED] += 1
                    continue
                post = await fetch_one(source, entry)
                if isinstance(post, dict):
                    posts.append(post)
                else:
                    skipped[SKIP_UNREADABLE if post == UNREADABLE else SKIP_NO_POST] += 1
            collected += len(posts)
            next_index += len(batch)
            pages_fetched += 1

            page_checkpoint: Dict[str, Any] = {"mode": mode}
            if mode == "site_index":
                page_checkpoint["adapter"] = self.adapter_type
            page_checkpoint.update({
                "next_index": next_index,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
                "total_candidates": len(entries),
                "skipped": dict(skipped),
            })
            yield ArchivePage(posts, page_checkpoint)

    # Subclasses implement matches, fetch_latest, inspect and archive_pages.
    def matches(self, source: Source) -> bool:  # pragma: no cover - always overridden
        raise NotImplementedError

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    async def inspect(self, source: Source) -> Inspection:  # pragma: no cover
        raise NotImplementedError

    def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):  # pragma: no cover
        raise NotImplementedError


def _entry_url(entry: Any) -> Optional[str]:
    """An index entry's address: the entry itself (page watch's), or its public_url / url."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("public_url") or entry.get("url")
    return None
