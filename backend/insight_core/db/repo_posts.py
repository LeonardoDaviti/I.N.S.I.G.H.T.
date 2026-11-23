import os, sys, json, hashlib, re
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, Iterable, Iterator, List, Literal, Sequence, Set, Tuple, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import Connection, Cursor

from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.db import database as db
from insight_core.db.ensure_db import ensure_database
from insight_core.utils.content_fingerprints import hash_post_content
from insight_core.utils.post_fields import (CITES_KEY, COLLECTED_KEY, MOVED_KEY, SAVED_KEY, STORY_ONLY_KEY, TAKEN_KEY,
                                           build_post_fields)
from insight_core.utils import own_pages
from insight_core.utils.url_normalization import canonicalize_url, extract_url_host, normalize_url
from insight_core.utils.story_rules import date_alone
from insight_core.utils.json_safe import json_default
from insight_core.db.repo_page_watch import UPDATE_KEY, PageWatchRepository
from insight_core.db.repo_post_parts import PostPartsRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.markx import pairing

# metadata key of a body read from the article page (ingestion/full_text.py)
FULL_TEXT_FLAG = "full_content_fetched"
FULL_TEXT_CHECKED = "full_text_checked_at"
# metadata key of how well a page was read (parsing.read_fidelity): source health sums the newest per source
PAGE_READ_KEY = "page_read"
# metadata key of a teaser's page reads: {"count", "last_at", "failed"}; a re-fetch keeps it
PAGE_TRIES_KEY = "page_tries"
# metadata keys of a teaser's last page read ({"outcome", "at"}) and the full_text.FULL_TEXT_RULE version it
# was read by (the repair reads a post again once per version); a re-fetch keeps both
PAGE_OUTCOME_KEY = "page_read_outcome"
FULL_TEXT_RULE_KEY = "full_text_rule"
# metadata key of an X Article read for a link-only tweet (ingestion/kinds/x_articles.py)
X_ARTICLE_KEY = "x_article"
# A Telegram post's address (the bridge links each item to t.me): its channel's albums are folded.
TELEGRAM_POST_PREFIX = "https://t.me/"


def published_precision(post: Dict[str, Any]) -> str:
    """How precise a post's date is (posts.published_precision): "none" (no date), "seen" (dated when first
    seen), "date" (no time of day, or stored as 00:00:00 UTC), else "exact"."""
    date = post.get("date")
    if not isinstance(date, datetime):
        return "seen" if post.get("date_precision") == "seen" else "none"
    told = post.get("date_precision")
    if told == "before":   # no date given; bounded by the feed's next older dated item (parsing._bound_undated)
        return "none"
    return told if told in ("date", "exact") else "date" if date_alone(date) else "exact"


def _env_commit_batch() -> int:
    # SAFE_INGEST_SAVE_COMMIT_BATCH is the old name, still read as a fallback
    raw = os.getenv("INSIGHT_SAVE_COMMIT_BATCH") or os.getenv("SAFE_INGEST_SAVE_COMMIT_BATCH") or "20"
    try:
        return max(1, int(raw))
    except ValueError:
        return 20


# Commit every N attempted drafts. Small on purpose: each post opens a writing SAVEPOINT, Postgres caches only
# 64 subtransaction ids per backend, and past that every other backend falls back to pg_subtrans lookups while
# the transaction stays open. Only the top-level commit hands the ids back, hence a commit interval.
SAVE_COMMIT_BATCH = _env_commit_batch()

_PQ_INERROR = psycopg.pq.TransactionStatus.INERROR


def _transaction_is_poisoned(conn) -> bool:
    """True when the connection sits in aborted-transaction state and accepts nothing."""
    return conn.info.transaction_status == _PQ_INERROR


# Set on a post a kind read from its site's backlog (page watch's sitemap): never "new to you" (0039).
BACKLOG_KEY = "_backlog"
# A page first seen this long after its date is new to you: it sorts at when it was first seen.
NEW_TO_YOU_AFTER = "2 days"
# A post a live read first sees, dated more than this before the source's previous successful read, was added
# to its feed late: it is new to you and sorts at when it was first seen. The slack covers the previous read's
# own length and clock rounding.
ADDED_LATE_SLACK = "15 minutes"
# Stored bodies the repair reads at a time (drop_hidden_link_labels): bounds the peak memory.
BODIES_BATCH = 200
# Known news is not new (0058): a page another source linked before it was first seen keeps its date.
# Migration 0043 repeats this condition.
LINKED_BEFORE_SQL = """EXISTS (SELECT 1 FROM post_links l JOIN posts q ON q.id = l.post_id
                         WHERE l.target_url = p.normalized_url AND q.source_id <> p.source_id
                           AND q.fetched_at < p.fetched_at)"""
# A source's first fetch is its backlog (0070): its undated posts (%(ids)s, in feed order) sort below its dated
# posts, a microsecond apart to keep the feed's order. Migration 0053 places stored ones the same way.
UNDATED_BACKLOG_SQL = """
    UPDATE posts p SET surfaced_at = date_trunc('day', LEAST(p.fetched_at, (SELECT min(d.published_at)
               FROM posts d WHERE d.source_id = p.source_id)) - interval '1 second', 'UTC')
           + (cardinality(%(ids)s::uuid[]) - u.n + 1) * interval '1 microsecond'
      FROM unnest(%(ids)s::uuid[]) WITH ORDINALITY AS u(id, n)
     WHERE p.id = u.id AND p.published_at IS NULL AND p.surfaced_at IS NULL"""


@dataclass(frozen=True)
class PostDraft:
    """A normalized post dict (url, title, content, date, ...) before it is saved.

    watch: the source watches its pages (0039): a meaningful text change brings the post back. surface: a
    page-based source's live fetch after its first: a new post first seen long after its date sorts at when it
    was first seen."""

    source_id: str
    post: dict
    watch: bool = False
    surface: bool = False


class Saved(tuple):
    """upsert_post's (post_id, was_inserted), plus `changed`: False when the post was stored as it is (nothing
    written, so its parts, links and refs need no reading again)."""
    changed: bool = True

    def __new__(cls, pair: Tuple[str, bool], *, changed: bool = True) -> "Saved":
        saved = super().__new__(cls, pair)
        saved.changed = changed
        return saved


@dataclass(frozen=True)
class PostSaveFailure:
    url: Optional[str]
    source_id: str
    stage: Literal["upsert", "discarded"]   # discarded = lost to a poisoned-txn rollback
    error: str


@dataclass
class SaveBatchResult:
    inserted_ids: List[str] = field(default_factory=list)
    updated_ids: List[str] = field(default_factory=list)
    resurfaced_ids: List[str] = field(default_factory=list)   # watched posts that changed meaningfully
    failures: List[PostSaveFailure] = field(default_factory=list)
    by_source: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def inserted(self) -> int:
        return len(self.inserted_ids)

    @property
    def updated(self) -> int:
        return len(self.updated_ids)

    @property
    def failed(self) -> int:
        return len(self.failures)

    def _count(self, source_id: str, key: str, delta: int = 1) -> None:
        counts = self.by_source.setdefault(source_id, {"inserted": 0, "updated": 0, "failed": 0})
        counts[key] += delta

    def merge(self, other: "SaveBatchResult") -> None:
        """Add another save's result to this one (the runner saves one source at a time)."""
        self.inserted_ids.extend(other.inserted_ids)
        self.updated_ids.extend(other.updated_ids)
        self.resurfaced_ids.extend(other.resurfaced_ids)
        self.failures.extend(other.failures)
        for source_id, counts in other.by_source.items():
            for key, delta in counts.items():
                self._count(source_id, key, delta)


class PostsRepository:
    """Database access layer for the posts table."""

    def __init__(self, db_url: str):
        self.db_url = db_url

        self.logger = get_component_logger("repo_posts")
        self.logger.info(f"PostsRepository initialized")
        self.watch = PageWatchRepository()
        self.stories = StoriesRepository()

    # posts has TWO unique keys: posts_url_key (url) and the partial posts_source_external_unique (source_id,
    # external_id). ON CONFLICT (url) leaves the second uncovered: a post whose url moved but external_id stayed
    # (a LessWrong rename) raised unique_violation and once aborted a whole cycle's save. Everything below exists
    # so one post can never cost a whole cycle.
    _CONFLICT_INDEX = "posts_source_external_unique"
    # A post whose link comes back in another form (utm_ tags, http, www., trailing slash, a fragment) is the same
    # post only with the same title (post_title_key, 0049): one normalized_url can hold different posts (#fn1-).
    # No index can express that, so _other_form takes an advisory lock on the address before it looks; such a row
    # is updated by id through the resolver, never inserted twice.
    _ADDRESS_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended('insight.post:' || %(normalized_url)s::text, 0))"
    _OTHER_FORM_SQL = """
        SELECT EXISTS (
            SELECT 1 FROM posts
             WHERE normalized_url = %(normalized_url)s::text
               AND post_title_key(title) = post_title_key(%(title)s::text)
        )
    """

    # One source's post under another address altogether (host move, renamed slug; 0070): same title, posted within
    # a day, same body (same_post_body), not a platform's post address. The newer address wins. Locked on the
    # source and title.
    _TITLE_LOCK_SQL = ("SELECT pg_advisory_xact_lock(hashtextextended("
                       "'insight.post-title:' || %(source_id)s::text || post_title_key(%(title)s::text), 0))")
    _ELSEWHERE_SQL = f"""
        SELECT id, length(content) FROM posts
         WHERE source_id = %(source_id)s::uuid AND album_of IS NULL
           AND {pairing.ix_date('')} BETWEEN COALESCE(%(published_at)s::timestamptz, now()) - interval '1 day'
                                                      AND COALESCE(%(published_at)s::timestamptz, now()) + interval '1 day'
           AND post_title_key(title) = post_title_key(%(title)s::text)
           AND normalized_url IS DISTINCT FROM %(normalized_url)s::text AND NOT platform_post_address(normalized_url)
           AND same_post_body(content_hash, content, %(content_hash)s::text, %(content)s::text)
         ORDER BY fetched_at DESC, id
         LIMIT 1
    """

    # A page you saved that a feed now brings (0122): the Saved source's rows at the address and this source's own
    # saved rows; _saved_copy decides.
    _SAVED_COPY_SQL = """
        SELECT p.id, p.url = %(url)s, p.source_id = %(source_id)s::uuid, s.platform = 'saved'
          FROM posts p JOIN sources s ON s.id = p.source_id
         WHERE (p.url = %(url)s OR p.normalized_url = %(normalized_url)s::text) AND p.album_of IS NULL
           AND (s.platform = 'saved' OR (p.source_id = %(source_id)s::uuid AND p.metadata ? '{saved}'))
         ORDER BY p.url = %(url)s DESC, p.fetched_at, p.id
         LIMIT 1
    """.replace("{saved}", SAVED_KEY)

    # Bounded: a retry only happens when another writer moved the rows; every resolver branch converges.
    _CONFLICT_MAX_ATTEMPTS = 4

    _CONFLICT_LOOKUP_SQL = """
        WITH url_row AS (
            SELECT id, source_id
              FROM posts
             WHERE url = %(url)s
                OR (%(normalized_url)s::text IS NOT NULL AND normalized_url = %(normalized_url)s::text
                    AND post_title_key(title) = post_title_key(%(title)s::text))
             ORDER BY url = %(url)s DESC, fetched_at, created_at, id
             LIMIT 1
        )
        SELECT id, TRUE AS matched_by_url
          FROM url_row
        UNION ALL
        SELECT id, FALSE
          FROM posts
         WHERE %(external_id)s::text IS NOT NULL
           AND external_id = %(external_id)s::text
           AND source_id = COALESCE(
                   (SELECT source_id FROM url_row),
                   %(source_id)s::uuid
               )
    """
    # UNION ALL rather than OR so each arm uses its own index; the casts are required for untyped parameters.
    # Arm 2 is scoped to the URL ROW's source_id, not the incoming one: ON CONFLICT (url) never reassigns
    # source_id, so the violated entry is (that owner, external_id); scoping to the incoming source would see
    # "no blocker" and replay a doomed UPDATE. The url row is the exact url's, else the same normalized_url and
    # title's (0049).

    def upsert_post(self, cur: Cursor, post: Dict[str, Any], source_id: str) -> Tuple[str, bool]:
        """Save a single post. Returns (post_id, was_inserted).

        Never raises on a post that already exists under either unique key: the write runs inside a savepoint and
        a posts_source_external_unique violation is resolved by identity.
        """

        url = post['url']
        content = post.get("content", "")
        published_at = post.get("date", None)
        precision = published_precision(post)
        external_id = post.get("external_id", None)

        media_urls = self._json_dumps(post.get("media_urls", []))
        categories = self._json_dumps(post.get("categories", []))

        title = post.get("title", None)
        content_html = post.get("content_html", None)
        lang = post.get("lang", None)
        metadata = self._json_dumps(post.get("metadata", {}))
        fields = build_post_fields(post)
        content_hash = fields.get("content_hash") or self._build_content_hash(title, content, content_html)
        language_code = fields.get("language_code")
        language_confidence = fields.get("language_confidence")
        normalized_url = fields.get("normalized_url")
        canonical_url = fields.get("canonical_url")
        url_host = fields.get("url_host")

        # Named parameters so the INSERT and the recovery UPDATEs can share one dict.
        params: Dict[str, Any] = {
            "source_id": source_id,
            "url": url,
            "external_id": external_id,
            "published_at": published_at,
            "published_precision": precision,
            "title": title,
            "content": content,
            "content_html": content_html,
            "lang": lang,
            "content_hash": content_hash,
            "language_code": language_code,
            "language_confidence": language_confidence,
            "normalized_url": normalized_url,
            "canonical_url": canonical_url,
            "url_host": url_host,
            "author": fields.get("author"),
            "reposted_by": fields.get("reposted_by") or [],
            "metadata": metadata,
            "media_urls": media_urls,
            "categories": categories,
        }

        query = """
            INSERT INTO posts (
                source_id,
                url,
                external_id,
                published_at,
                published_precision,
                title,
                content,
                content_html,
                lang,
                content_hash,
                language_code,
                language_confidence,
                normalized_url,
                canonical_url,
                url_host,
                author,
                reposted_by,
                metadata,
                media_urls,
                categories
            )
            VALUES (
                %(source_id)s,
                %(url)s,
                %(external_id)s,
                COALESCE(%(published_at)s::timestamptz,
                         CASE WHEN %(published_precision)s::text = 'seen' THEN now() END),
                %(published_precision)s,
                %(title)s,
                %(content)s,
                %(content_html)s,
                %(lang)s,
                %(content_hash)s,
                %(language_code)s,
                %(language_confidence)s,
                %(normalized_url)s,
                %(canonical_url)s,
                %(url_host)s,
                %(author)s,
                NULLIF(%(reposted_by)s::text[], '{{}}'),
                %(metadata)s::jsonb,
                %(media_urls)s::jsonb,
                %(categories)s::jsonb
            )
            ON CONFLICT (url) DO UPDATE SET
                {assignments}
            WHERE {changes}
            RETURNING id, (xmax = 0) AS inserted
        """.format(assignments=self._post_update_assignments(row_prefix="posts."), changes=self._post_update_changes())

        for attempt in range(self._CONFLICT_MAX_ATTEMPTS):
            other_form = False
            try:
                # The savepoint stops one bad row from aborting the transaction (25P02) and losing the batch.
                with self._savepoint(cur, "insight_upsert_post"):
                    row = self._saved_copy(cur, params)
                    if row is None:
                        row = self._own_page(cur, params)   # a page's own source takes it back (0167)
                    other_form = row is None and self._other_form(cur, params)
                    row = row if row is not None or other_form else self._same_post_elsewhere(cur, params)
                    if not other_form and row is None:
                        # Stored as it is: nothing written. Read first: an ON CONFLICT that updates nothing
                        # still locks the stored row.
                        cur.execute(f"SELECT id FROM posts WHERE url = %(url)s AND NOT ({self._post_update_changes()})",
                                    params)
                        same = cur.fetchone()
                        if same is not None:
                            return Saved((str(same[0]), False), changed=False)
                        cur.execute(query, params)
                        row = cur.fetchone()
                        if row is None:   # another writer made it as stored meanwhile
                            cur.execute("SELECT id FROM posts WHERE url = %s", (url,))
                            return Saved((str(cur.fetchone()[0]), False), changed=False)
                    if row is not None:
                        PostPartsRepository.write(cur, [str(row[0])])   # read once, when it is saved
            except psycopg.errors.UniqueViolation as exc:
                # ON CONFLICT (url) absorbs posts_url_key; anything but the uncovered index must stay loud.
                if exc.diag.constraint_name != self._CONFLICT_INDEX:
                    raise
                resolved = self._resolve_external_id_collision(cur, params, attempt=attempt)
                if resolved is not None:
                    return resolved
                continue
            if other_form:
                resolved = self._resolve_external_id_collision(cur, params, attempt=attempt)
                if resolved is not None:
                    return resolved
                continue

            post_id = str(row[0])
            was_inserted = row[1]

            action = "Inserted" if was_inserted else "Updated"
            self.logger.debug(f"{action} post: {url[:60]}...")

            return (post_id, was_inserted)

        raise RuntimeError(
            f"upsert_post could not resolve {self._CONFLICT_INDEX} or another form of {url} "
            f"after {self._CONFLICT_MAX_ATTEMPTS} attempts"
        )

    def _other_form(self, cur: Cursor, params: Dict[str, Any]) -> bool:
        """Whether this post is stored under another form of its url with the same title.

        An exact-url post takes ON CONFLICT (url) and costs no lock. Otherwise the address is locked until the
        transaction ends (_ADDRESS_LOCK_SQL) so a concurrent save of another form cannot insert it twice.
        """
        if params.get("normalized_url") is None:
            return False
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE url = %(url)s)", params)
        if cur.fetchone()[0]:
            return False
        cur.execute(self._ADDRESS_LOCK_SQL, params)
        cur.execute(self._OTHER_FORM_SQL, params)
        return bool(cur.fetchone()[0])

    @staticmethod
    def _owns_page(cur: Cursor, params: Dict[str, Any]) -> bool:
        """Whether the incoming post's source owns its page (own_pages.owns, 0167)."""
        cur.execute("SELECT platform, handle_or_url FROM sources WHERE id = %(source_id)s::uuid", params)
        found = cur.fetchone()
        return found is not None and own_pages.owns(found[0], found[1], params["url"])

    def _saved_copy(self, cur: Cursor, params: Dict[str, Any]) -> Optional[Tuple[Any, bool]]:
        """A page you saved that this post is (0122): that row, updated with this post, as (id, False); else None.

        - Saved as this source's post at another form of the address: the feed's form and title win.
        - Saved under the Saved source when this source owns the page (repo_linked.page_source): the row moves to
          this source and stays saved. A source that doesn't own it (link blog, aggregator) leaves it.

        One row, its id kept; nothing is deleted. Left alone when another row holds the address or external_id."""
        if params.get("normalized_url") is None:
            return None
        cur.execute(self._SAVED_COPY_SQL, params)
        found = cur.fetchone()
        if found is None:
            return None
        target, exact, here, in_saved = found
        if here and (exact or in_saved):
            return None   # the same row by ON CONFLICT (url), or the Saved source's own save
        if not here:
            from insight_core.db.repo_linked import page_source   # repo_linked reads the sources' facts
            if not in_saved:
                return None
            owner = page_source(cur, params["url"])
            # a source with no post of the page's shape yet teaches page_source nothing: own_pages decides
            if owner is None and not self._owns_page(cur, params):
                return None
            if owner is not None and owner != str(params["source_id"]):
                return None
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE id <> %(target)s::uuid AND (url = %(url)s"
                    " OR (%(external_id)s::text IS NOT NULL AND source_id = %(source_id)s::uuid"
                    " AND external_id = %(external_id)s::text)))", dict(params, target=target))
        if cur.fetchone()[0]:
            return None
            # A page INSIGHT collected (0123) moves too, though you never saved it: it becomes a row of its feed.
        cur.execute(f"UPDATE posts SET source_id = %(source_id)s::uuid, metadata = (metadata - '{STORY_ONLY_KEY}') || jsonb_strip_nulls(jsonb_build_object("
                    f"'{SAVED_KEY}', COALESCE(metadata -> '{SAVED_KEY}', CASE WHEN metadata ? '{COLLECTED_KEY}' THEN NULL"
                    f" ELSE to_jsonb(fetched_at) END))) WHERE id = %(target)s::uuid",
                    dict(params, target=target))
        cur.execute("UPDATE posts SET {assignments} WHERE id = %(target_id)s::uuid RETURNING id".format(
            assignments=self._post_update_assignments(set_url=True)), dict(params, target_id=target))
        self.logger.info("A saved page is the post of source %s now: %s", params["source_id"], params["url"][:80])
        return (cur.fetchone()[0], False)

    # The row another source holds at this address (0167): exact, or normalised when the held one has no fragment
    # (a link blog's #fn1 rows are other posts), with both sources.
    _HELD_SQL = """
        SELECT p.id, p.url, hs.id::text, hs.platform, hs.handle_or_url, ins.platform, ins.handle_or_url
          FROM posts p JOIN sources hs ON hs.id = p.source_id, sources ins
         WHERE ins.id = %(source_id)s::uuid AND p.source_id <> %(source_id)s::uuid AND p.album_of IS NULL
           AND (p.url = %(url)s OR (p.normalized_url = %(normalized_url)s::text AND strpos(p.url, '#') = 0))
           AND NOT platform_post_address(%(normalized_url)s::text)
         ORDER BY p.url = %(url)s DESC, p.fetched_at, p.id
         LIMIT 1
    """

    def _own_page(self, cur: Cursor, params: Dict[str, Any]) -> Optional[Tuple[Any, bool]]:
        """A page another source holds (0167, utils/own_pages). This source owns it and the holder doesn't: the row
        moves here (hand_over) and is updated, as (id, False). The holder owns it and this source doesn't: `params`
        is pointed at this source's citation of it and None is returned. Else None (the holder's row is updated)."""
        if params.get("normalized_url") is None or own_pages.is_citation_address(params.get("url")):
            return None
        cur.execute(self._HELD_SQL, params)
        found = cur.fetchone()
        if found is None:
            return None
        row_id, held_url, holder, holder_platform, holder_handle, platform, handle = found
        if (holder_platform or "").lower() == "saved":
            return None   # a saved page: _saved_copy's
        incoming_owns = own_pages.owns(platform, handle, params["url"])
        holder_owns = own_pages.owns(holder_platform, holder_handle, params["url"])
        if incoming_owns and not holder_owns:
            if held_url != params["url"]:
                cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE url = %(url)s)", params)
                if cur.fetchone()[0]:
                    return None   # this source's own row is at this address: the other paths decide
            if not self.hand_over(cur, str(row_id), str(params["source_id"]), external_id=params.get("external_id")):
                return None
            cur.execute("UPDATE posts SET {assignments} WHERE id = %(target_id)s::uuid RETURNING id".format(
                assignments=self._post_update_assignments(set_url=held_url != params["url"])),
                dict(params, target_id=row_id))
            return (cur.fetchone()[0], False)
        if holder_owns and not incoming_owns:
            self._as_citation(params, str(row_id))
        return None

    def _as_citation(self, params: Dict[str, Any], page_id: str) -> None:
        """Point an incoming post of a source that doesn't own its page at its citation of it (0167)."""
        page = params["normalized_url"]
        cite = own_pages.citation_address(page, str(params["source_id"]))
        metadata = json.loads(params.get("metadata") or "{}")
        metadata[CITES_KEY] = {"url": params["url"], "normalized_url": page, "post_id": page_id}
        params.update(url=cite, normalized_url=normalize_url(cite), canonical_url=canonicalize_url(cite),
                      url_host=extract_url_host(cite), metadata=self._json_dumps(metadata))

    def hand_over(self, cur: Cursor, post_id: str, owner_id: str, *, external_id: Optional[str] = None) -> bool:
        """Move a stored post to the source that owns its page (0167); the holder keeps a citing post
        (`own_pages.citation_address`) with the post's title, text, dates and read state. One row, its id kept:
        everything attached stays; nothing is deleted. Its external id goes when it would clash with the owner's.
        False when the post is gone, already the owner's, or `external_id` is another of the owner's rows'."""
        cur.execute("SELECT source_id::text, url, COALESCE(normalized_url, url) FROM posts WHERE id = %s::uuid FOR UPDATE",
                    (post_id,))
        found = cur.fetchone()
        if found is None or found[0] == owner_id:
            return False
        holder, url, normalized = found
        cur.execute(self._ADDRESS_LOCK_SQL, {"normalized_url": normalized})
        if external_id is not None:
            cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE source_id = %s::uuid AND external_id = %s AND id <> %s::uuid)",
                        (owner_id, external_id, post_id))
            if cur.fetchone()[0]:
                return False
        cite = own_pages.citation_address(normalized, holder)
        cited = {"url": url, "normalized_url": normalized, "post_id": post_id}
        cur.execute(
            f"""INSERT INTO posts (source_id, url, published_at, published_precision, fetched_at, surfaced_at, title,
                                   content, content_html, lang, content_hash, language_code, language_confidence,
                                   normalized_url, canonical_url, url_host, author, reposted_by, metadata, media_urls,
                                   categories)
                SELECT source_id, %(cite)s, published_at, published_precision, fetched_at, surfaced_at, title, content,
                       content_html, lang, content_hash, language_code, language_confidence, %(cite_normalized)s,
                       %(cite_canonical)s, url_host, author, reposted_by,
                       (metadata - '{TAKEN_KEY}' - '{SAVED_KEY}') || jsonb_build_object('{CITES_KEY}', %(cited)s::jsonb),
                       media_urls, categories
                  FROM posts WHERE id = %(id)s::uuid
                ON CONFLICT (url) DO NOTHING
                RETURNING id""",
            {"cite": cite, "cite_normalized": normalize_url(cite), "cite_canonical": canonicalize_url(cite),
             "cited": json.dumps(cited), "id": post_id})
        made = cur.fetchone()
        if made is None:
            cur.execute("SELECT id FROM posts WHERE url = %s AND source_id = %s::uuid", (cite, holder))
            made = cur.fetchone()
            if made is None:
                return False   # another source's row at the citation's address
        citation = str(made[0])
        cur.execute("""INSERT INTO post_reader_state (post_id, read_at, updated_at)
                       SELECT %s::uuid, read_at, now() FROM post_reader_state WHERE post_id = %s::uuid AND read_at IS NOT NULL
                       ON CONFLICT (post_id) DO NOTHING""", (citation, post_id))
        taken = {"source_id": holder, "at": datetime.now().astimezone().isoformat(), "citation": citation}
        cur.execute(f"""UPDATE posts SET source_id = %(owner)s::uuid,
                               external_id = CASE WHEN EXISTS (SELECT 1 FROM posts o WHERE o.source_id = %(owner)s::uuid
                                                                 AND o.external_id = posts.external_id AND o.id <> posts.id)
                                                  THEN NULL ELSE external_id END,
                               metadata = metadata || jsonb_build_object('{TAKEN_KEY}', %(taken)s::jsonb)
                         WHERE id = %(id)s::uuid""",
                    {"owner": owner_id, "taken": json.dumps(taken), "id": post_id})
        self.logger.info("Issue 0167: %s is the post of its own source %s now (was %s's, which cites it)",
                         url[:80], owner_id, holder)
        return True

    def _same_post_elsewhere(self, cur: Cursor, params: Dict[str, Any]) -> Optional[Tuple[Any, bool]]:
        """This post stored by its source under another address (_ELSEWHERE_SQL): that row, moved to this url and
        updated, as (id, False); else None. A body shorter than the stored one leaves the stored text."""
        if params.get("normalized_url") is None or not params.get("title"):
            return None
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE url = %(url)s)"
                    " OR platform_post_address(%(normalized_url)s::text)", params)
        if cur.fetchone()[0]:
            return None   # stored as it is, or a platform's post (its id is the post)
        cur.execute(self._TITLE_LOCK_SQL, params)
        cur.execute(self._ELSEWHERE_SQL, params)
        found = cur.fetchone()
        if found is None:
            return None
        update = dict(params, target_id=found[0])
        if len(params.get("content") or "") < (found[1] or 0):
            update.update(content=None, content_html=None, content_hash=None)
        cur.execute("UPDATE posts SET {assignments} WHERE id = %(target_id)s::uuid RETURNING id".format(
            assignments=self._post_update_assignments(set_url=True, set_external_id=False)), update)
        return (cur.fetchone()[0], False)

    def _resolve_external_id_collision(
        self, cur: Cursor, params: Dict[str, Any], *, attempt: int = 0
    ) -> Optional[Tuple[str, bool]]:
        """Settle a (source_id, external_id) or normalized_url clash by identity. Returns None to retry the insert,
        else (post_id, False). `attempt`: the caller's retry count, used to stop writing external_id once a replay
        proved that write cannot land.
        """
        # A read-only savepoint: any failure (statement_timeout, a bad ::uuid cast) would otherwise abort the
        # transaction and lose the batch. A SELECT-only savepoint gets no XID, so it costs no subxid cache slot.
        # fetchall() must run inside the block: RELEASE on this cursor discards the pending result.
        with self._savepoint(cur, "insight_upsert_lookup"):
            cur.execute(self._CONFLICT_LOOKUP_SQL, params)
            lookup_rows = cur.fetchall()

        url_row_id: Optional[str] = None
        external_row_id: Optional[str] = None
        for row in lookup_rows:
            if row[1]:
                url_row_id = str(row[0])
            else:
                external_row_id = str(row[0])

        if url_row_id is None and external_row_id is None:
            # Both rows vanished (a race with another writer): let the caller replay the insert.
            return None

        if url_row_id is not None and external_row_id is not None and url_row_id != external_row_id:
            # Two rows: the url belongs to one, the external_id to another. external_id is NOT written (it would
            # violate against the other row) and url has nowhere to go, so the url row wins, the clash is stamped
            # into metadata for a human to merge, and neither row is deleted (reader state would cascade away).
            self.logger.warning(
                "external_id collision: post %s holds url %s while post %s holds "
                "(source_id=%s, external_id=%s); updating the url row and leaving its "
                "external_id untouched",
                url_row_id,
                params["url"],
                external_row_id,
                params["source_id"],
                params["external_id"],
            )
            statement = """
                UPDATE posts SET
                    {assignments}
                WHERE id = %(target_id)s::uuid
                RETURNING id
            """.format(
                assignments=self._post_update_assignments(
                    set_external_id=False,
                    metadata_expr=self._COLLISION_METADATA_EXPR,
                )
            )
            resolved = dict(params, target_id=url_row_id, conflicting_post_id=external_row_id)
        elif url_row_id is not None:
            # The plain url-keyed update. attempt > 0: this write already violated the index once, so external_id
            # is dropped from the SET list rather than replaying a failed statement.
            statement = """
                UPDATE posts SET
                    {assignments}
                WHERE id = %(target_id)s::uuid
                RETURNING id
            """.format(assignments=self._post_update_assignments(set_external_id=attempt == 0))
            resolved = dict(params, target_id=url_row_id)
        else:
            # Same post, moved url (a LessWrong rename): repair the url so the next cycle takes the fast path.
            statement = """
                UPDATE posts SET
                    {assignments}
                WHERE id = %(target_id)s::uuid
                RETURNING id
            """.format(assignments=self._post_update_assignments(set_url=True, set_external_id=False))
            resolved = dict(params, target_id=external_row_id)

        try:
            with self._savepoint(cur, "insight_upsert_resolve"):
                cur.execute(statement, resolved)
                row = cur.fetchone()
                if row is not None:
                    PostPartsRepository.write(cur, [str(row[0])])
        except psycopg.errors.UniqueViolation:
            # Another writer took the url or external_id meanwhile. Replaying converges: the next lookup takes the
            # two-row branch, which writes neither unique column.
            return None

        if row is None:
            return None
        return (str(row[0]), False)

    # The incoming metadata merged as the normal path does, plus the clash.
    _COLLISION_METADATA_EXPR = (
        "COALESCE(COALESCE(%(metadata)s::jsonb, metadata), jsonb_build_object()) || "
        "jsonb_build_object('external_id_conflict', jsonb_build_object("
        "'external_id', %(external_id)s::text, "
        "'conflicting_post_id', %(conflicting_post_id)s::text, "
        "'detected_at', now()))"
    )

    def _post_update_assignments(self, **kwargs: Any) -> str:
        """The SET list shared by ON CONFLICT DO UPDATE and the recovery UPDATEs (`_post_update_pairs`)."""
        return ",\n                ".join(f"{column} = {value}" for column, value in self._post_update_pairs(**kwargs))

    def _post_update_changes(self) -> str:
        """ON CONFLICT DO UPDATE's condition: the update would change the stored row (updated_at aside). A re-fetched
        feed item is nearly always as stored; rewriting it cost row versions and link reads (0215)."""
        pairs = [(column, value) for column, value in self._post_update_pairs(row_prefix="posts.")
                 if column != "updated_at"]
        return (f"({', '.join('posts.' + column for column, _ in pairs)}) IS DISTINCT FROM "
                f"({', '.join(value for _, value in pairs)})")

    def _post_update_pairs(
        self,
        *,
        row_prefix: str = "",
        set_url: bool = False,
        set_external_id: bool = True,
        metadata_expr: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """The (column, value) pairs of the SET list shared by ON CONFLICT DO UPDATE and the recovery UPDATEs, so a
        repaired post gets exactly the fast path's columns. row_prefix is "posts." inside ON CONFLICT (a bare name
        is ambiguous against EXCLUDED) and "" in a plain UPDATE.
        """
        row = row_prefix
        # A body read from the article page is kept when the feed brings its summary again.
        keep = (f"({row}metadata ? '{FULL_TEXT_FLAG}' AND NOT "
                f"COALESCE(%(metadata)s::jsonb, '{{}}'::jsonb) ? '{FULL_TEXT_FLAG}')")
        # Kept across a re-fetch unless the kind brings newer: the last meaningful change, page tries, where the
        # page moved, its last page read and rules' version, saved/taken/cites/collected keys.
        moved = (f"({row}metadata ? '{MOVED_KEY}' AND NOT "
                 f"COALESCE(%(metadata)s::jsonb, '{{}}'::jsonb) ? '{MOVED_KEY}')")
        metadata = (f"jsonb_strip_nulls(jsonb_build_object('{PAGE_TRIES_KEY}', {row}metadata -> '{PAGE_TRIES_KEY}',"
                    f" '{MOVED_KEY}', {row}metadata -> '{MOVED_KEY}',"
                    f" '{PAGE_OUTCOME_KEY}', {row}metadata -> '{PAGE_OUTCOME_KEY}',"
                    f" '{FULL_TEXT_RULE_KEY}', {row}metadata -> '{FULL_TEXT_RULE_KEY}'))"
                    f" || ({metadata_expr or f'COALESCE(%(metadata)s::jsonb, {row}metadata)'})"
                    f" || jsonb_strip_nulls(jsonb_build_object('{UPDATE_KEY}', {row}metadata -> '{UPDATE_KEY}',"
                    f" '{SAVED_KEY}', {row}metadata -> '{SAVED_KEY}',"
                    f" '{TAKEN_KEY}', {row}metadata -> '{TAKEN_KEY}', '{CITES_KEY}', {row}metadata -> '{CITES_KEY}',"
                    f" '{COLLECTED_KEY}', {row}metadata -> '{COLLECTED_KEY}'))")
        assignments: List[str] = []
        if set_url:
            assignments.append("url = %(url)s")
        if set_external_id:
            assignments.append(f"external_id = COALESCE(%(external_id)s, {row}external_id)")
        assignments.extend([
            # An undated item is dated when first seen; a stored date is never moved by "seen".
            f"published_at = COALESCE(%(published_at)s, {row}published_at,"
            f" CASE WHEN %(published_precision)s::text = 'seen' THEN {row}fetched_at END)",
            f"published_precision = CASE WHEN %(published_at)s::timestamptz IS NOT NULL THEN %(published_precision)s"
            f" WHEN {row}published_at IS NULL AND %(published_precision)s::text = 'seen' THEN 'seen'"
            f" ELSE {row}published_precision END",
            f"title = COALESCE(%(title)s, {row}title)",
            f"content = CASE WHEN {keep} THEN {row}content ELSE COALESCE(%(content)s, {row}content) END",
            f"content_html = CASE WHEN {keep} THEN {row}content_html ELSE COALESCE(%(content_html)s, {row}content_html) END",
            f"lang = COALESCE(%(lang)s, {row}lang)",
            f"content_hash = CASE WHEN {keep} THEN {row}content_hash ELSE COALESCE(%(content_hash)s, {row}content_hash) END",
            "language_code = %(language_code)s",
            "language_confidence = %(language_confidence)s::real",   # the column's type: compared as stored
            "normalized_url = %(normalized_url)s",
            f"canonical_url = CASE WHEN {moved} THEN {row}canonical_url ELSE %(canonical_url)s END",
            "url_host = %(url_host)s",
            # every feed that brings a tweet as its repost adds its account
            f"author = COALESCE(%(author)s, {row}author)",
            f"reposted_by = NULLIF(ARRAY(SELECT DISTINCT a FROM unnest(COALESCE({row}reposted_by, '{{}}')"
            f" || %(reposted_by)s::text[]) a ORDER BY 1), '{{}}')",
            # A kept body keeps how well its page was read too.
            f"metadata = CASE WHEN {keep} THEN ({metadata}) || jsonb_build_object('{FULL_TEXT_FLAG}', true)"
            f" || jsonb_strip_nulls(jsonb_build_object('{PAGE_READ_KEY}', {row}metadata -> '{PAGE_READ_KEY}'))"
            f" ELSE {metadata} END",
            "media_urls = %(media_urls)s::jsonb",
            "categories = %(categories)s::jsonb",
            # fetched_at (first seen) never moves: for an undated feed it is the post's only date.
            "updated_at = now()",
        ])
        return [(column, value) for column, value in (a.split(" = ", 1) for a in assignments)]

    @contextmanager
    def _savepoint(self, cur: Cursor, name: str) -> Iterator[None]:
        """Isolate one statement so its failure cannot poison the caller's transaction.

        Raw SAVEPOINT rather than conn.transaction(), which would emit BEGIN/COMMIT per post and move the batch's
        commit boundary. Released on both paths so the stack does not grow.
        """
        conn = cur.connection
        if getattr(conn, "autocommit", False):
            # No transaction to protect (SAVEPOINT outside one makes ROLLBACK TO fail): open one for the statement.
            with conn.transaction():
                yield
            return

        cur.execute(f"SAVEPOINT {name}")
        try:
            yield
        except Exception:
            cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
            cur.execute(f"RELEASE SAVEPOINT {name}")
            raise
        cur.execute(f"RELEASE SAVEPOINT {name}")

    @staticmethod
    def place_undated_backlog(cur: Cursor, post_ids: Sequence[str]) -> None:
        """Undated older posts stored outside save_batch sort as its undated backlog does: before their source's
        oldest post, never at the time they were read."""
        ids = [str(post_id) for post_id in post_ids if post_id]
        if ids:
            cur.execute(UNDATED_BACKLOG_SQL, {"ids": ids})

    def save_batch(
        self,
        conn: Connection,
        drafts: Sequence[PostDraft],
        *,
        commit_every: Optional[int] = None,
        live: bool = False,
    ) -> SaveBatchResult:
        """Upsert many drafts with per-post isolation; owns the transaction on `conn`.

        live: a live read's drafts: a new post dated before the source's previous successful read (ADDED_LATE_SLACK)
        sorts at when it was first seen; not on a first fetch or for a backlog page (BACKLOG_KEY).

        Precondition: `conn` is not autocommit and is idle. Commits every `commit_every` attempted drafts and at the
        end. A post that raises costs that post; if it aborted the transaction, everything since the last commit
        is rolled back and reported as `discarded`, and the batch carries on.
        """
        commit_every = max(1, int(commit_every or SAVE_COMMIT_BATCH))
        result = SaveBatchResult()
        # saved since the last commit: (draft, post_id, was_inserted)
        window: List[Tuple[PostDraft, str, bool]] = []
        channels: Set[str] = set()   # Telegram sources with a new post: their albums are folded at the end
        backlog_undated: Dict[str, List[str]] = {}   # a first fetch's undated posts, in its order

        def commit() -> None:
            conn.commit()
            window.clear()

        with conn.cursor() as cur:
            cur.execute("SELECT s FROM unnest(%s::uuid[]) s WHERE EXISTS (SELECT 1 FROM posts WHERE source_id = s)",
                        (list({str(draft.source_id) for draft in drafts}),))
            fetched_before = {str(row[0]) for row in cur.fetchall()}
            read_before: Dict[str, Any] = {}   # source -> its previous successful read
            if live:
                cur.execute("SELECT source_id, last_success_at FROM source_fetch_state"
                            " WHERE source_id = ANY(%s::uuid[]) AND last_success_at IS NOT NULL",
                            (list({str(draft.source_id) for draft in drafts}),))
                read_before = {str(source_id): at for source_id, at in cur.fetchall()}
            for index, draft in enumerate(drafts, start=1):
                post = dict(draft.post)
                post.pop("_source_id", None)
                backlog = bool(post.pop(BACKLOG_KEY, False))
                try:
                    old = self._stored_text(cur, post["url"]) if draft.watch else None
                    saved = self.upsert_post(cur, post, draft.source_id)
                    post_id, was_inserted = saved
                except Exception as exc:
                    result.failures.append(PostSaveFailure(post.get("url"), draft.source_id, "upsert", str(exc)))
                    result._count(draft.source_id, "failed")
                    self.logger.error("Failed to save post %s (source %s): %s", post.get("url"), draft.source_id, exc)
                    # verify rather than assume the savepoint left the transaction usable
                    if _transaction_is_poisoned(conn):
                        conn.rollback()
                        self._discard(result, window)
                        window.clear()
                else:
                    post_id = str(post_id)
                    window.append((draft, post_id, was_inserted))
                    if self._after_save(cur, draft, post, post_id, was_inserted, old,
                                        changed=getattr(saved, "changed", True),
                                        surface=draft.surface and not backlog,
                                        read_before=None if backlog else read_before.get(str(draft.source_id))):
                        result.resurfaced_ids.append(post_id)
                    if was_inserted:
                        result.inserted_ids.append(post_id)
                        result._count(draft.source_id, "inserted")
                        if str(post.get("url") or "").startswith(TELEGRAM_POST_PREFIX):
                            channels.add(draft.source_id)
                        # an undated post of a first fetch, or an undated older post, sorts before the source's
                        # oldest post, never at its fetch time
                        if not post.get("date") and (backlog or str(draft.source_id) not in fetched_before):
                            backlog_undated.setdefault(str(draft.source_id), []).append(post_id)
                    else:
                        result.updated_ids.append(post_id)
                        result._count(draft.source_id, "updated")

                if index % commit_every == 0:
                    commit()
            self._fold_albums(cur, channels)
            for ids in backlog_undated.values():
                cur.execute(UNDATED_BACKLOG_SQL, {"ids": ids})
            if result.inserted_ids:   # a source's item filter hides the new posts it matches (never deletes)
                from insight_core.utils import item_filter
                try:
                    with conn.transaction():
                        item_filter.mark(cur, result.inserted_ids)
                except Exception as exc:  # noqa: BLE001 - the posts are stored; shown is the safe side
                    self.logger.error("Item filter: could not mark the new posts: %s", exc)
        commit()
        return result

    def _fold_albums(self, cur: Cursor, source_ids: Iterable[str]) -> None:
        """A Telegram album is one post (0069): fold_telegram_albums joins the bridge's picture items to the post they
        follow. A failure costs only the folding, which the next batch does again."""
        for source_id in sorted(source_ids):
            try:
                with self._savepoint(cur, "insight_fold_albums"):
                    cur.execute("SELECT fold_telegram_albums(%s::uuid)", (source_id,))
            except Exception as exc:  # noqa: BLE001 - the posts are saved
                self.logger.error("Could not fold the albums of source %s: %s", source_id, exc)

    def _stored_text(self, cur: Cursor, url: str) -> Optional[Dict[str, Any]]:
        """A stored post's text before a watched draft overwrites it, or None (a new post)."""
        cur.execute("SELECT content, content_html FROM posts WHERE url = %s", (url,))
        row = cur.fetchone()
        return {"content": row[0], "content_html": row[1]} if row else None

    def _after_save(self, cur: Cursor, draft: PostDraft, post: Dict[str, Any], post_id: str,
                    was_inserted: bool, old: Optional[Dict[str, Any]], *, surface: bool,
                    read_before: Optional[Any] = None, changed: bool = True) -> bool:
        """After a post is written: a new post first seen NEW_TO_YOU_AFTER past its date (surface), or dated
        ADDED_LATE_SLACK before its source's previous read (read_before), sorts at when it was first seen, unless
        another source's post linked it before (LINKED_BEFORE_SQL); its outside links are recorded; a watched post
        comes back when it changed meaningfully. One savepoint; a failure is logged and costs neither the post nor
        the batch. Returns whether the post came back. `changed` False: links and refs stand."""
        try:
            with self._savepoint(cur, "insight_after_save"):
                if changed:
                    self.stories.save_post_links(cur, post_id)
                if was_inserted and (surface or read_before is not None):
                    cur.execute(
                        f"""UPDATE posts p SET surfaced_at = p.fetched_at
                             WHERE p.id = %(id)s::uuid
                               AND ((%(surface)s AND p.published_at < p.fetched_at - interval '{NEW_TO_YOU_AFTER}')
                                    OR p.published_at < %(read_before)s::timestamptz - interval '{ADDED_LATE_SLACK}')
                               AND NOT {LINKED_BEFORE_SQL}""",
                        {"id": post_id, "surface": surface, "read_before": read_before},
                    )
                if draft.watch:
                    return self.watch.saved(cur, post_id, draft.source_id, post, None if was_inserted else old)
        except Exception as exc:  # noqa: BLE001 - the post is saved; only its links or watch state are not
            self.logger.error("Could not record the links or watch state of post %s: %s", post_id, exc)
        return False

    def _discard(self, result: SaveBatchResult, window: List[Tuple[PostDraft, str, bool]]) -> None:
        """Move every draft saved since the last commit into failures as `discarded`."""
        if not window:
            return
        lost_ids = {post_id for _, post_id, _ in window}
        result.inserted_ids = [i for i in result.inserted_ids if i not in lost_ids]
        result.updated_ids = [i for i in result.updated_ids if i not in lost_ids]
        result.resurfaced_ids = [i for i in result.resurfaced_ids if i not in lost_ids]
        for draft, _post_id, was_inserted in window:
            result._count(draft.source_id, "inserted" if was_inserted else "updated", -1)
            result._count(draft.source_id, "failed")
            result.failures.append(PostSaveFailure(
                draft.post.get("url"), draft.source_id, "discarded",
                "discarded: transaction rolled back after a failed post",
            ))
        self.logger.error("Transaction left in error state; rolled back %s uncommitted posts", len(window))

    def get_source_post_stats(self, cur: Cursor, source_id: str) -> Dict[str, Any]:
        """Aggregate storage stats for one source; oldest_external_id is where an archive continues from."""
        query = """
            SELECT
                COUNT(*) AS post_count,
                MIN(published_at) AS oldest_published_at,
                MAX(published_at) AS latest_published_at,
                MAX(fetched_at) AS latest_fetched_at,
                (SELECT external_id FROM posts
                  WHERE source_id = %s AND published_at IS NOT NULL
                  ORDER BY published_at ASC LIMIT 1) AS oldest_external_id
            FROM posts
            WHERE source_id = %s
        """
        cur.execute(query, (source_id, source_id))
        row = cur.fetchone()

        return {
            "post_count": row[0] or 0,
            "oldest_published_at": row[1],
            "latest_published_at": row[2],
            "latest_fetched_at": row[3],
            "oldest_external_id": row[4],
        }

    def stored_urls(self, urls: Sequence[str]) -> set:
        """Which of these urls are already stored."""
        if not urls:
            return set()
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT url FROM posts WHERE url = ANY(%s)", (list(urls),))
            return {row[0] for row in cur.fetchall()}

    def kept_urls(self, urls: Sequence[str], source_id: str) -> set:
        """Which of these urls a fetch of this source leaves unread (page watch): stored as its post, or held by
        another source it would not take them from (one its save would take back is read)."""
        if not urls:
            return set()
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT platform, handle_or_url FROM sources WHERE id = %s::uuid", (source_id,))
            found = cur.fetchone()
            cur.execute("""SELECT p.url, p.source_id::text, s.platform, s.handle_or_url
                             FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.url = ANY(%s)""", (list(urls),))
            rows = cur.fetchall()
        if found is None:
            return {row[0] for row in rows}
        platform, handle = found
        return {url for url, holder, holder_platform, holder_handle in rows
                if holder == source_id or not own_pages.owns(platform, handle, url)
                or own_pages.owns(holder_platform, holder_handle, url)}

    def stored_x_articles(self, urls: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """These urls stored with their X Article read: {url: {title, content, content_html, media_urls, metadata}}."""
        if not urls:
            return {}
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(f"""SELECT url, title, content, content_html, media_urls, metadata FROM posts
                            WHERE url = ANY(%s) AND metadata ? '{X_ARTICLE_KEY}'""", (list(urls),))
            return {row[0]: {"title": row[1], "content": row[2] or "", "content_html": row[3],
                             "media_urls": row[4] or [], "metadata": row[5] or {}} for row in cur.fetchall()}

    def drop_story_only(self, post_id: str) -> None:
        """A post shown only inside its story (0126) becomes a row of its feed: you saved it."""
        with db.transaction(self.db_url) as cur:
            cur.execute(f"UPDATE posts SET metadata = metadata - '{STORY_ONLY_KEY}' WHERE id = %s::uuid AND metadata ? '{STORY_ONLY_KEY}'",
                        (post_id,))

    def teasers_to_read_again(self, source_id: str, *, now: datetime, max_tries: int, apart: timedelta,
                              limit: int) -> List[Dict[str, Any]]:
        """The source's stored teasers whose last page read failed, tried fewer than max_tries times, the last at
        least `apart` ago; oldest try first. Each as a post the saver writes back in place (date None)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT url, title, content, content_html, media_urls, categories, metadata
                  FROM posts
                 WHERE source_id = %(source)s::uuid
                   AND NOT metadata ? '{FULL_TEXT_FLAG}'
                   AND NOT metadata ? '{CITES_KEY}'
                   AND metadata -> '{PAGE_TRIES_KEY}' @> '{{"failed": true}}'
                   AND (metadata -> '{PAGE_TRIES_KEY}' ->> 'count')::int < %(max_tries)s
                   AND (metadata -> '{PAGE_TRIES_KEY}' ->> 'last_at')::timestamptz <= %(before)s
                 ORDER BY (metadata -> '{PAGE_TRIES_KEY}' ->> 'last_at')::timestamptz, id
                 LIMIT %(limit)s
                """,
                {"source": source_id, "max_tries": max_tries, "before": now - apart, "limit": limit},
            )
            return [{"url": row[0], "title": row[1], "content": row[2] or "", "content_html": row[3],
                     "date": None, "media_urls": row[4] or [], "categories": row[5] or [],
                     "metadata": row[6] or {}} for row in cur.fetchall()]

    def full_text_candidates(self, cur: Cursor, *, short_chars: int, source_id: Optional[str] = None,
                             retry: bool = False, limit: Optional[int] = None,
                             rule: Optional[int] = None, outcomes: Sequence[str] = (),
                             skip_hosts: Sequence[str] = ()) -> List[Dict[str, Any]]:
        """Stored posts shorter than short_chars, or a paid teaser, never read from their page, newest first, each
        with its source. retry includes those a repair already tried.

        With `rule`: instead, posts never read in full whose metadata.full_text_rule is older than `rule` and whose
        last read ended in `outcomes` or none; short, or linking to their own address; no paid teaser; none at or
        under `skip_hosts`."""
        if rule is not None:
            hosts = "|".join(re.escape(host) for host in skip_hosts) or r"no-host\.invalid"
            cur.execute(
                f"""
                SELECT p.id, p.url, p.title, p.content, p.content_html, p.metadata,
                       s.id, s.platform, s.handle_or_url, s.settings
                FROM posts p JOIN sources s ON s.id = p.source_id
                WHERE NOT p.metadata ? '{FULL_TEXT_FLAG}'
                  AND NOT p.metadata ? '{CITES_KEY}'
                  AND NOT p.metadata @> '{{"paywalled": true}}'
                  AND COALESCE((p.metadata ->> '{FULL_TEXT_RULE_KEY}')::int, 0) < %(rule)s
                  AND (NOT p.metadata ? '{PAGE_OUTCOME_KEY}'
                       OR p.metadata -> '{PAGE_OUTCOME_KEY}' ->> 'outcome' = ANY(%(outcomes)s))
                  AND (length(coalesce(p.content, '')) < %(short)s
                       OR (p.url ~ '^https?://' AND strpos(coalesce(p.content_html, ''),
                           split_part(split_part(p.url, '#', 1), '?', 1)) > 0))
                  AND coalesce(p.url, '') !~* %(skip)s
                  AND (%(source_id)s::uuid IS NULL OR s.id = %(source_id)s::uuid)
                ORDER BY p.published_at DESC NULLS LAST, p.id
                LIMIT %(limit)s
                """,
                {"short": short_chars, "rule": rule, "outcomes": list(outcomes), "source_id": source_id, "limit": limit,
                 "skip": rf"^https?://([^/?#]*\.)?({hosts})([/:?#]|$)"},
            )
        else:
            cur.execute(
                f"""
                SELECT p.id, p.url, p.title, p.content, p.content_html, p.metadata,
                       s.id, s.platform, s.handle_or_url, s.settings
                FROM posts p JOIN sources s ON s.id = p.source_id
                WHERE (length(coalesce(p.content, '')) < %(short)s OR p.metadata @> '{{"paywalled": true}}')
                  AND NOT p.metadata ? '{FULL_TEXT_FLAG}'
                  AND NOT p.metadata ? '{CITES_KEY}'
                  AND (%(retry)s OR NOT p.metadata ? '{FULL_TEXT_CHECKED}')
                  AND (%(source_id)s::uuid IS NULL OR s.id = %(source_id)s::uuid)
                ORDER BY p.published_at DESC NULLS LAST, p.id
                LIMIT %(limit)s
                """,
                {"short": short_chars, "retry": retry, "source_id": source_id, "limit": limit},
            )
        return [
            {
                "id": str(row[0]), "url": row[1], "title": row[2], "content": row[3],
                "content_html": row[4], "metadata": row[5] or {},
                "source": {"id": str(row[6]), "platform": row[7], "handle_or_url": row[8],
                           "settings": row[9] or {}},
            }
            for row in cur.fetchall()
        ]

    def save_full_text(self, cur: Cursor, post_id: str, post: Dict[str, Any]) -> None:
        """Store the full body of a stored post; metadata is merged, never replaced. An undated post takes the page's
        date and sorts at it."""
        fields = build_post_fields(post)
        cur.execute(
            """
            UPDATE posts SET
                surfaced_at = CASE WHEN published_at IS NULL AND %(date)s::timestamptz IS NOT NULL
                                   THEN NULL ELSE surfaced_at END,
                published_precision = CASE WHEN published_at IS NULL AND %(date)s::timestamptz IS NOT NULL
                                           THEN %(precision)s ELSE published_precision END,
                published_at = COALESCE(published_at, %(date)s::timestamptz),
                -- An X Article read for its tweet (kinds/x_articles.py) brings its title; a page, none.
                title = COALESCE(%(title)s, title),
                content = %(content)s,
                content_html = %(content_html)s,
                content_hash = %(content_hash)s,
                language_code = %(language_code)s,
                language_confidence = %(language_confidence)s,
                metadata = metadata || %(metadata)s::jsonb,
                -- A page that moved (issue 0108): its canonical is where it moved.
                canonical_url = CASE WHEN %(metadata)s::jsonb ? %(moved_key)s THEN %(canonical_url)s ELSE canonical_url END,
                links_scanned_at = NULL,
                updated_at = now()
            WHERE id = %(id)s::uuid
            """,
            {
                "id": post_id,
                "date": post.get("date"),
                "precision": published_precision(post),
                "title": post.get("title"),
                "content": post.get("content") or "",
                "content_html": post.get("content_html"),
                "content_hash": fields["content_hash"],
                "language_code": fields["language_code"],
                "language_confidence": fields["language_confidence"],
                "metadata": self._json_dumps(post.get("metadata") or {}),
                "moved_key": MOVED_KEY,
                "canonical_url": fields["canonical_url"],
            },
        )
        PostPartsRepository.write(cur, [post_id])

    def merge_metadata(self, cur: Cursor, post_id: str, metadata: Dict[str, Any]) -> None:
        """Merge keys into a stored post's metadata (a repair's read: checked, its page tries)."""
        cur.execute("UPDATE posts SET metadata = metadata || %s::jsonb WHERE id = %s::uuid",
                    (self._json_dumps(metadata), post_id))

    def contents_with_entities(self, cur: Cursor, *, source_id: Optional[str] = None) -> List[Tuple[str, str]]:
        """(id, content) of the stored posts whose plain text holds an HTML code (&#39;)."""
        cur.execute(
            """
            SELECT id, content FROM posts
            WHERE content ~ '&[#a-zA-Z0-9]+;'
              AND (%(source_id)s::uuid IS NULL OR source_id = %(source_id)s::uuid)
            """,
            {"source_id": source_id},
        )
        return [(str(row[0]), row[1]) for row in cur.fetchall()]

    def save_contents(self, cur: Cursor, contents: Sequence[Tuple[str, str]]) -> None:
        """New plain text for stored posts, and its content hash."""
        new = dict(contents)
        if not new:
            return
        cur.execute("SELECT id, title, content_html FROM posts WHERE id = ANY(%s::uuid[])", (list(new),))
        rows = [(new[str(post_id)], hash_post_content(title, new[str(post_id)], content_html), str(post_id))
                for post_id, title, content_html in cur.fetchall()]
        cur.executemany("UPDATE posts SET content = %s, content_hash = %s, updated_at = now() WHERE id = %s::uuid",
                        rows)

    @staticmethod
    def drop_hidden_link_labels(cur: Cursor) -> int:
        """Take screen-reader labels inside links (parsing._without_hidden_link_labels) out of stored HTML bodies;
        nothing is fetched. The plain text and hash follow. Returns how many changed. Reads a batch at a time to
        bound memory (0072)."""
        from insight_core.ingestion.kinds.parsing import HIDDEN_HINT_RE, _without_hidden_link_labels, strip_html

        rows = []
        with cur.connection.cursor(name="hidden_link_labels") as read:
            read.itersize = BODIES_BATCH
            read.execute("SELECT id, title, content, content_html FROM posts WHERE content_html ~* %s",
                         (HIDDEN_HINT_RE.pattern.removeprefix("(?i)"),))
            for post_id, title, content, html in read:
                new = _without_hidden_link_labels(html)
                if new != html:
                    text = strip_html(new) if content == strip_html(html) else content
                    rows.append((new, text, hash_post_content(title, text, new), str(post_id)))
        cur.executemany(
            """UPDATE posts SET content_html = %s, content = %s, content_hash = %s, links_scanned_at = NULL,
                   updated_at = now() WHERE id = %s::uuid""",
            rows,
        )
        return len(rows)

    def _build_content_hash(self, title: Optional[str], content: str, content_html: Optional[str]) -> str:
        """Create a stable digest for dedupe and update tracking."""
        payload = "\n".join(
            part.strip()
            for part in [
                title or "",
                content or "",
                content_html or "",
            ]
            if part
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else ""

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(value, default=json_default)
