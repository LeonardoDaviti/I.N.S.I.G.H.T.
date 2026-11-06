import os, sys, json, hashlib
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
from insight_core.utils.post_fields import COLLECTED_KEY, MOVED_KEY, SAVED_KEY, STORY_ONLY_KEY, build_post_fields
from insight_core.utils.story_rules import date_alone
from insight_core.utils.json_safe import json_default
from insight_core.db.repo_page_watch import UPDATE_KEY, PageWatchRepository
from insight_core.db.repo_post_parts import PostPartsRepository
from insight_core.db.repo_stories import StoriesRepository

# metadata key of a body read from the article page (ingestion/full_text.py)
FULL_TEXT_FLAG = "full_content_fetched"
FULL_TEXT_CHECKED = "full_text_checked_at"
# metadata key of how well a page was read (parsing.read_fidelity; issue 0032): page watch
# and full text set it, source health sums the newest ones per source.
PAGE_READ_KEY = "page_read"
# metadata key of a teaser's page reads (issue 0062): {"count", "last_at", "failed"}. A re-fetch
# of the feed keeps it (_post_update_assignments); ingestion/full_text.py reads and writes it.
PAGE_TRIES_KEY = "page_tries"
# A Telegram post's address (the bridge links each item to t.me): its channel's albums are folded.
TELEGRAM_POST_PREFIX = "https://t.me/"


def published_precision(post: Dict[str, Any]) -> str:
    """How precise a post's date is (issue 0076, posts.published_precision): "none" (the source gave no
    date), "date" (no time of day: as its kind read it, or stored as 00:00:00 UTC), else "exact"."""
    date = post.get("date")
    if not isinstance(date, datetime):
        return "none"
    told = post.get("date_precision")
    return told if told in ("date", "exact") else "date" if date_alone(date) else "exact"


def _env_commit_batch() -> int:
    # INSIGHT_SAVE_COMMIT_BATCH, renamed from SAFE_INGEST_SAVE_COMMIT_BATCH (still read as a
    # fallback for one version).
    raw = os.getenv("INSIGHT_SAVE_COMMIT_BATCH") or os.getenv("SAFE_INGEST_SAVE_COMMIT_BATCH") or "20"
    try:
        return max(1, int(raw))
    except ValueError:
        return 20


# Commit every N attempted drafts. Deliberately small: upsert_post opens one writing
# SAVEPOINT per post (two on the rare external_id collision path - its lookup savepoint is
# read-only and so is never assigned an XID), and Postgres caches only 64 subtransaction ids
# per backend. Past that the backend's snapshot is suboverflowed and EVERY OTHER backend in
# the cluster falls back to pg_subtrans lookups for as long as the transaction stays open.
# RELEASE SAVEPOINT does not hand the id back; only the top-level commit does, which is why
# this is a commit interval and not a savepoint-stack depth.
SAVE_COMMIT_BATCH = _env_commit_batch()

_PQ_INERROR = psycopg.pq.TransactionStatus.INERROR


def _transaction_is_poisoned(conn) -> bool:
    """True when the connection sits in aborted-transaction state and accepts nothing."""
    return conn.info.transaction_status == _PQ_INERROR


# A post dict's key a kind sets on a page it read from its site's backlog (page watch's sitemap),
# not from the site's own list of what is new: such a page is never "new to you" (issue 0039).
BACKLOG_KEY = "_backlog"
# A page first seen this long after its date is new to you: it sorts at when it was first seen.
NEW_TO_YOU_AFTER = "2 days"
# The stored bodies the repair reads at a time (drop_hidden_link_labels): ~15 MB of HTML on the lab.
# Not tuned; any batch far below the 2,958 bodies bounds the peak.
BODIES_BATCH = 200
# Issue 0058: known news is not new. A page one of your other sources linked before it was first
# seen already reached you (0050's post_links, target_url normalized as posts.normalized_url):
# it keeps its date. p is the page; migration 0043 clears what was surfaced before with the
# same condition, written out again there.
LINKED_BEFORE_SQL = """EXISTS (SELECT 1 FROM post_links l JOIN posts q ON q.id = l.post_id
                         WHERE l.target_url = p.normalized_url AND q.source_id <> p.source_id
                           AND q.fetched_at < p.fetched_at)"""
# Issue 0070: a source's first fetch is its backlog. Its undated posts (ids in the feed's order,
# %(ids)s) sort below the source's dated posts: at the start of the UTC day of the second before its
# oldest dated post, or before the fetch, which reads as a date alone (no time of day); a microsecond
# apart keeps the feed's order. A later fetch's undated post is new: it sorts at its fetch, as before.
# Migration 0053 places the stored ones the same way.
UNDATED_BACKLOG_SQL = """
    UPDATE posts p SET surfaced_at = date_trunc('day', LEAST(p.fetched_at, (SELECT min(d.published_at)
               FROM posts d WHERE d.source_id = p.source_id)) - interval '1 second', 'UTC')
           + (cardinality(%(ids)s::uuid[]) - u.n + 1) * interval '1 microsecond'
      FROM unnest(%(ids)s::uuid[]) WITH ORDINALITY AS u(id, n)
     WHERE p.id = u.id AND p.published_at IS NULL AND p.surfaced_at IS NULL"""


@dataclass(frozen=True)
class PostDraft:
    """A normalized post dict (url, title, content, date, ...) before it is saved.

    watch: its source watches its pages for changes (issue 0039): the text's hash is kept and
    a meaningful change brings the post back. surface: a page-based source's live fetch, after
    its first: a new post first seen long after its date sorts at when it was first seen."""

    source_id: str
    post: dict
    watch: bool = False
    surface: bool = False


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
    """
    Database access layer for posts table.
    Handles all SQL operations for storing and retrieving posts.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url

        self.logger = get_component_logger("repo_posts")
        self.logger.info(f"PostsRepository initialized")
        self.watch = PageWatchRepository()
        self.stories = StoriesRepository()

    # ===============================
    # WRITE OPERATIONS
    # ===============================

    # posts carries TWO unique keys: posts_url_key on (url) and the partial unique index
    # posts_source_external_unique on (source_id, external_id) WHERE external_id IS NOT NULL.
    # Postgres allows exactly one inference specification per INSERT, so ON CONFLICT (url)
    # leaves the second index completely uncovered. On 2026-07-22 two scheduler cycles hit
    # it with LessWrong post XLSWRFPdgPTjLtaj5 - stable _id, but pageUrl carries a title
    # slug that moves when the author renames the post - and each raised a real
    # unique_violation. Because the save loop commits once at the very end, that single row
    # aborted the transaction and discarded the ENTIRE ~30-minute fetch of every source,
    # silently: record_live_fetch never ran, so the Operations panel showed nothing wrong.
    # Ingestion stayed dead for 21 days. Everything below exists so one post can never again
    # cost a whole cycle.
    _CONFLICT_INDEX = "posts_source_external_unique"
    # Issue 0049: a post whose link comes back in another form (#atom-everything dropped, utm_
    # tags, http, www., a trailing slash) is the same post when it also has the same title
    # (post_title_key, migration 0038: case, whitespace, HTML entities). The address alone is
    # not enough: Daring Fireball links different posts under one normalized_url, told apart
    # by #fn1-..., #:~:text=... or utm_campaign, and their titles differ. No index can say
    # "same address and same title, where the title may change on a re-fetch", so
    # normalized_url is a plain index and _other_form takes a transaction-scoped advisory lock
    # on the address before it looks: two writers saving forms of one address are serialized,
    # and the second sees the first's row once it commits. Such a row is then updated by id
    # through the resolver below (it keeps its url and id), never inserted a second time.
    _ADDRESS_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended('insight.post:' || %(normalized_url)s::text, 0))"
    _OTHER_FORM_SQL = """
        SELECT EXISTS (
            SELECT 1 FROM posts
             WHERE normalized_url = %(normalized_url)s::text
               AND post_title_key(title) = post_title_key(%(title)s::text)
        )
    """

    # Issue 0070: one source's post found under another address altogether (a host move, a renamed
    # slug, ?src=feed): the same title (post_title_key), posted within a day, the same body
    # (same_post_body, migration 0052: the same hash, or one's opening is the other), not at a
    # platform's own post address. The newer address wins: that row is updated with this url.
    # Locked on the source and title, as _other_form locks the address.
    _TITLE_LOCK_SQL = ("SELECT pg_advisory_xact_lock(hashtextextended("
                       "'insight.post-title:' || %(source_id)s::text || post_title_key(%(title)s::text), 0))")
    _ELSEWHERE_SQL = """
        SELECT id, length(content) FROM posts
         WHERE source_id = %(source_id)s::uuid AND album_of IS NULL
           AND COALESCE(published_at, fetched_at) BETWEEN COALESCE(%(published_at)s::timestamptz, now()) - interval '1 day'
                                                      AND COALESCE(%(published_at)s::timestamptz, now()) + interval '1 day'
           AND post_title_key(title) = post_title_key(%(title)s::text)
           AND normalized_url IS DISTINCT FROM %(normalized_url)s::text AND NOT platform_post_address(normalized_url)
           AND same_post_body(content_hash, content, %(content_hash)s::text, %(content)s::text)
         ORDER BY fetched_at DESC, id
         LIMIT 1
    """

    # Issue 0122: a page you saved that a feed now brings. The Saved source's rows at the address
    # (normalised), and this source's own saved rows (saved_by_owner); _saved_copy decides.
    _SAVED_COPY_SQL = """
        SELECT p.id, p.url = %(url)s, p.source_id = %(source_id)s::uuid, s.platform = 'saved'
          FROM posts p JOIN sources s ON s.id = p.source_id
         WHERE (p.url = %(url)s OR p.normalized_url = %(normalized_url)s::text) AND p.album_of IS NULL
           AND (s.platform = 'saved' OR (p.source_id = %(source_id)s::uuid AND p.metadata ? '{saved}'))
         ORDER BY p.url = %(url)s DESC, p.fetched_at, p.id
         LIMIT 1
    """.replace("{saved}", SAVED_KEY)

    # Bounded because each retry only happens when another writer moved the rows under us.
    # Every resolver branch converges (see _resolve_external_id_collision), so exhausting
    # this means something is genuinely wrong rather than merely contended.
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
    # UNION ALL rather than OR so each arm uses its own index; a row matching both keys just
    # comes back twice and is deduped by id. The ::text/::uuid casts are required - psycopg
    # sends untyped parameters and Postgres cannot resolve `%(external_id)s IS NOT NULL`
    # without them.
    #
    # Arm 2 is scoped to the URL ROW's source_id, not the incoming one, and the difference is
    # what makes the retry loop terminate. ON CONFLICT (url) picks its victim by url alone and
    # _post_update_assignments never reassigns source_id, so when two sources carry the same
    # url the row being updated stays with its original owner - and the index entry it
    # violates is therefore (that owner, external_id), which a lookup scoped to the incoming
    # source_id cannot see. It would report "no blocker", the caller would replay the same
    # doomed UPDATE, and upsert_post would burn all four attempts and raise. Falling back to
    # the incoming source_id covers the no-url-row case, where the failed statement really was
    # a plain INSERT under this source.
    #
    # The url row is the exact url's, else the first seen under the same normalized_url and
    # title (issue 0049): to the resolver both are "the row this post already is".

    def upsert_post(self, cur: Cursor, post: Dict[str, Any], source_id: str) -> Tuple[str, bool]:
        """Save single post. Returns (post_id, was_inserted).

        Never raises on a post that already exists under either unique key: the write runs
        inside a savepoint, and a posts_source_external_unique violation is resolved by
        identity instead of aborting the caller's transaction.
        """
        # if new -> insert
        # if exists -> do nothing
        # if exists but different -> Update

        # Unified Structure
        url = post['url'] # Let KeyError happen
        content = post.get("content", "")
        published_at = post.get("date", None)
        precision = published_precision(post)
        external_id = post.get("external_id", None)

        # Lists -> JSON
        media_urls = self._json_dumps(post.get("media_urls", []))
        categories = self._json_dumps(post.get("categories", []))

        # Optional Fields
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

        # Named parameters (not positional) so the INSERT and the three recovery UPDATEs can
        # share one dict; the recovery statements touch different column subsets.
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

        # SQL QUERY
        # Build SQL query
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
                %(published_at)s,
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
            RETURNING id, (xmax = 0) AS inserted
        """.format(assignments=self._post_update_assignments(row_prefix="posts."))

        for attempt in range(self._CONFLICT_MAX_ATTEMPTS):
            other_form = False
            try:
                # The savepoint is what stops one bad row from poisoning the whole batch.
                # Without it Postgres puts the backend in aborted-transaction state and every
                # later statement fails with 25P02, so the caller's single terminal commit is
                # never reached and every post gathered that cycle is rolled back.
                with self._savepoint(cur, "insight_upsert_post"):
                    row = self._saved_copy(cur, params)
                    other_form = row is None and self._other_form(cur, params)
                    row = row if row is not None or other_form else self._same_post_elsewhere(cur, params)
                    if not other_form and row is None:
                        cur.execute(query, params)
                        row = cur.fetchone()
                    if row is not None:
                        PostPartsRepository.write(cur, [str(row[0])])   # read once, when it is saved (issue 0076)
            except psycopg.errors.UniqueViolation as exc:
                # ON CONFLICT (url) already absorbs posts_url_key, so the only violation that
                # can reach here is the uncovered index. Anything else is unexpected and must
                # stay loud rather than be swallowed by a resolver that cannot handle it.
                if exc.diag.constraint_name != self._CONFLICT_INDEX:
                    raise
                resolved = self._resolve_external_id_collision(cur, params, attempt=attempt)
                if resolved is not None:
                    return resolved
                continue
            if other_form:
                # Stored under another form of this address with the same title: update that row.
                resolved = self._resolve_external_id_collision(cur, params, attempt=attempt)
                if resolved is not None:
                    return resolved
                continue

            post_id = str(row[0])  # UUID → string
            was_inserted = row[1]  # Boolean

            # Log action
            action = "Inserted" if was_inserted else "Updated"
            self.logger.debug(f"{action} post: {url[:60]}...")

            return (post_id, was_inserted)

        raise RuntimeError(
            f"upsert_post could not resolve {self._CONFLICT_INDEX} or another form of {url} "
            f"after {self._CONFLICT_MAX_ATTEMPTS} attempts"
        )

    def _other_form(self, cur: Cursor, params: Dict[str, Any]) -> bool:
        """Whether this post is stored under another form of its url with the same title.

        A post stored under its exact url takes the INSERT's ON CONFLICT (url) path and costs no
        lock (every re-fetch of an unchanged feed). Otherwise the address is locked until the
        caller's transaction ends (see _ADDRESS_LOCK_SQL) before looking, so a concurrent save
        of another form cannot insert the same post twice.
        """
        if params.get("normalized_url") is None:
            return False
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE url = %(url)s)", params)
        if cur.fetchone()[0]:
            return False
        cur.execute(self._ADDRESS_LOCK_SQL, params)
        cur.execute(self._OTHER_FORM_SQL, params)
        return bool(cur.fetchone()[0])

    def _saved_copy(self, cur: Cursor, params: Dict[str, Any]) -> Optional[Tuple[Any, bool]]:
        """A page you saved that this post is (issue 0122): that row, updated with this post at its
        address, as (id, False); None when there is none (the other paths go on).

        - Saved as this source's post (metadata.saved_by_owner) at another form of the address: the
          feed's form and title win. At the same address ON CONFLICT (url) already updates it.
        - Saved under the Saved source at this address, normalised, when this source owns the page
          (repo_linked.page_source, 0084 B's rule): the row moves to this source and stays one you
          saved. A source that doesn't own the page (a link blog, an aggregator) leaves it as it was.

        One row, its id kept: the reader state, notes and opens stay; nothing is deleted. Left as it
        was when another row holds this address or this source's external_id (no unique clash)."""
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
            if not in_saved or page_source(cur, params["url"]) != str(params["source_id"]):
                return None
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE id <> %(target)s::uuid AND (url = %(url)s"
                    " OR (%(external_id)s::text IS NOT NULL AND source_id = %(source_id)s::uuid"
                    " AND external_id = %(external_id)s::text)))", dict(params, target=target))
        if cur.fetchone()[0]:
            return None
        # A page INSIGHT collected by itself (issue 0123) moves too, but you never saved it; shown only inside its
        # story until now (0126), it is a row of its source's feed.
        cur.execute(f"UPDATE posts SET source_id = %(source_id)s::uuid, metadata = (metadata - '{STORY_ONLY_KEY}') || jsonb_strip_nulls(jsonb_build_object("
                    f"'{SAVED_KEY}', COALESCE(metadata -> '{SAVED_KEY}', CASE WHEN metadata ? '{COLLECTED_KEY}' THEN NULL"
                    f" ELSE to_jsonb(fetched_at) END))) WHERE id = %(target)s::uuid",
                    dict(params, target=target))
        cur.execute("UPDATE posts SET {assignments} WHERE id = %(target_id)s::uuid RETURNING id".format(
            assignments=self._post_update_assignments(set_url=True)), dict(params, target_id=target))
        self.logger.info("A saved page is the post of source %s now: %s", params["source_id"], params["url"][:80])
        return (cur.fetchone()[0], False)

    def _same_post_elsewhere(self, cur: Cursor, params: Dict[str, Any]) -> Optional[Tuple[Any, bool]]:
        """This post stored by its source under another address (_ELSEWHERE_SQL): that row, moved to
        this url and updated, as (id, False); None when there is none. A body shorter than the
        stored one (a teaser of it) leaves the stored text."""
        if params.get("normalized_url") is None or not params.get("title"):
            return None
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE url = %(url)s)"
                    " OR platform_post_address(%(normalized_url)s::text)", params)
        if cur.fetchone()[0]:
            return None   # stored as it is (a re-fetch), or a platform's post: its id is the post
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
        """Settle a (source_id, external_id) or normalized_url clash by identity. Returns None to retry the insert.

        Returns (post_id, False) - the row demonstrably already existed, so it can never be
        an insert, and the `xmax = 0` trick only applies to the INSERT ... RETURNING path.

        `attempt` is the caller's retry counter, used only to give up on writing external_id
        once a replay has already proved that write cannot land.
        """
        # The collision lookup runs inside its own read-only savepoint. It cannot violate
        # anything, but any other failure (statement_timeout, pg_cancel_backend, a malformed
        # source_id failing the ::uuid cast) would otherwise leave the connection in
        # aborted-transaction state, and save_batch answers that by rolling back to the last
        # commit - turning one bad post back into
        # a lost batch of up to SAVE_COMMIT_BATCH good ones. Free in the currency that matters:
        # Postgres assigns an XID to a subtransaction only when it writes, so a SELECT-only
        # savepoint never enters the 64-entry per-backend subxid cache.
        # fetchall() has to happen inside the block: _savepoint's RELEASE runs on this same
        # cursor and discards the pending result set.
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
            # Both rows vanished between the violation and this lookup - we lost a race with
            # another writer. Nothing to resolve; let the caller replay the insert.
            return None

        if url_row_id is not None and external_row_id is not None and url_row_id != external_row_id:
            # THE TWO-ROW COLLISION. The incoming post's url belongs to one row and its
            # external_id to another. external_id is deliberately NOT assigned below: writing
            # it would violate posts_source_external_unique against the other row, and we
            # cannot instead move that row's url onto this one because url is NOT NULL and
            # totally unique - it has nowhere to go. So the url row wins the identity, the
            # clash is stamped into metadata for a human to merge, and neither row is
            # deleted: the reader state, interactions and notes cascade on delete and would
            # take the owner's reading history with them. Merging is a reviewable operation,
            # not an ingest-loop side effect.
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
            # The other row is gone or is the same row; the plain url-keyed update applies.
            # Second time through, it is not: attempt > 0 means this exact write already
            # violated the index once, so the blocking row exists but the lookup cannot see
            # it. Drop external_id from the SET list rather than replay a statement we have
            # watched fail - the loop is bounded, and exhausting it raises RuntimeError out
            # of upsert_post, which save_batch then reports as one failed post.
            statement = """
                UPDATE posts SET
                    {assignments}
                WHERE id = %(target_id)s::uuid
                RETURNING id
            """.format(assignments=self._post_update_assignments(set_external_id=attempt == 0))
            resolved = dict(params, target_id=url_row_id)
        else:
            # The common case: same post, moved url. LessWrong's pageUrl embeds a title slug
            # and _id does not, so a rename decouples the two keys. Repair the url here so
            # the next cycle takes the fast path instead of colliding again. external_id is
            # already the incoming value by definition of how this row was found.
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
            # Only the url-writing branches can land here, and only if another writer took
            # that url or external_id in the meantime. Replaying converges: the next lookup
            # now sees both rows and takes the two-row branch, which writes neither unique
            # column and therefore cannot violate anything.
            return None

        if row is None:
            # Row disappeared between lookup and update.
            return None
        return (str(row[0]), False)

    # Merges the incoming metadata exactly as the normal path does, then records the clash.
    _COLLISION_METADATA_EXPR = (
        "COALESCE(COALESCE(%(metadata)s::jsonb, metadata), jsonb_build_object()) || "
        "jsonb_build_object('external_id_conflict', jsonb_build_object("
        "'external_id', %(external_id)s::text, "
        "'conflicting_post_id', %(conflicting_post_id)s::text, "
        "'detected_at', now()))"
    )

    def _post_update_assignments(
        self,
        *,
        row_prefix: str = "",
        set_url: bool = False,
        set_external_id: bool = True,
        metadata_expr: Optional[str] = None,
    ) -> str:
        """Build the SET list shared by ON CONFLICT DO UPDATE and the recovery UPDATEs.

        One builder rather than four copies, because a post repaired through the collision
        resolver must end up with exactly the columns it would have got on the fast path.
        row_prefix is "posts." inside ON CONFLICT DO UPDATE - there a bare column name is
        ambiguous against EXCLUDED and Postgres rejects the statement - and "" in a plain
        UPDATE, where a bare name already means the pre-update row.
        """
        row = row_prefix
        # A body read from the article page (metadata.full_content_fetched) is kept when the
        # feed brings its summary again: the page is read once, when the post is new.
        keep = (f"({row}metadata ? '{FULL_TEXT_FLAG}' AND NOT "
                f"COALESCE(%(metadata)s::jsonb, '{{}}'::jsonb) ? '{FULL_TEXT_FLAG}')")
        # The last meaningful change (issue 0039) is the saver's, not the kind's: a re-fetch keeps it.
        # A teaser's page tries (issue 0062) are kept too, unless the kind brings newer ones.
        # Where its page moved (issue 0108) too, and its canonical with it, unless the kind brings it again.
        moved = (f"({row}metadata ? '{MOVED_KEY}' AND NOT "
                 f"COALESCE(%(metadata)s::jsonb, '{{}}'::jsonb) ? '{MOVED_KEY}')")
        metadata = (f"jsonb_strip_nulls(jsonb_build_object('{PAGE_TRIES_KEY}', {row}metadata -> '{PAGE_TRIES_KEY}',"
                    f" '{MOVED_KEY}', {row}metadata -> '{MOVED_KEY}'))"
                    f" || ({metadata_expr or f'COALESCE(%(metadata)s::jsonb, {row}metadata)'})"
                    f" || jsonb_strip_nulls(jsonb_build_object('{UPDATE_KEY}', {row}metadata -> '{UPDATE_KEY}',"
                    # A page you saved stays one you saved (issue 0122), whatever the feed brings.
                    f" '{SAVED_KEY}', {row}metadata -> '{SAVED_KEY}',"
                    # And a page INSIGHT collected stays collected (issue 0123).
                    f" '{COLLECTED_KEY}', {row}metadata -> '{COLLECTED_KEY}'))")
        assignments: List[str] = []
        if set_url:
            assignments.append("url = %(url)s")
        if set_external_id:
            assignments.append(f"external_id = COALESCE(%(external_id)s, {row}external_id)")
        assignments.extend([
            f"published_at = COALESCE(%(published_at)s, {row}published_at)",
            f"published_precision = CASE WHEN %(published_at)s::timestamptz IS NULL THEN {row}published_precision"
            f" ELSE %(published_precision)s END",
            f"title = COALESCE(%(title)s, {row}title)",
            f"content = CASE WHEN {keep} THEN {row}content ELSE COALESCE(%(content)s, {row}content) END",
            f"content_html = CASE WHEN {keep} THEN {row}content_html ELSE COALESCE(%(content_html)s, {row}content_html) END",
            f"lang = COALESCE(%(lang)s, {row}lang)",
            f"content_hash = CASE WHEN {keep} THEN {row}content_hash ELSE COALESCE(%(content_hash)s, {row}content_hash) END",
            "language_code = %(language_code)s",
            "language_confidence = %(language_confidence)s",
            "normalized_url = %(normalized_url)s",
            f"canonical_url = CASE WHEN {moved} THEN {row}canonical_url ELSE %(canonical_url)s END",
            "url_host = %(url_host)s",
            # Attribution (issue 0066): every feed that brings a tweet as its repost adds its account.
            f"author = COALESCE(%(author)s, {row}author)",
            f"reposted_by = NULLIF(ARRAY(SELECT DISTINCT a FROM unnest(COALESCE({row}reposted_by, '{{}}')"
            f" || %(reposted_by)s::text[]) a ORDER BY 1), '{{}}')",
            # A kept body keeps how well its page was read too.
            f"metadata = CASE WHEN {keep} THEN ({metadata}) || jsonb_build_object('{FULL_TEXT_FLAG}', true)"
            f" || jsonb_strip_nulls(jsonb_build_object('{PAGE_READ_KEY}', {row}metadata -> '{PAGE_READ_KEY}'))"
            f" ELSE {metadata} END",
            "media_urls = %(media_urls)s::jsonb",
            "categories = %(categories)s::jsonb",
            # fetched_at is when the post was first seen and is never moved: for a feed without
            # dates it is the post's only date, and bumping it on every re-fetch made the
            # same old posts jump to the top of the reader as new (chadnauseam.com).
            "updated_at = now()",
        ])
        return ",\n                ".join(assignments)

    @contextmanager
    def _savepoint(self, cur: Cursor, name: str) -> Iterator[None]:
        """Isolate one statement so its failure cannot poison the caller's transaction.

        Emits SAVEPOINT by hand instead of using psycopg's conn.transaction(): both ingest
        callers open a plain non-autocommit connection and upsert_post issues its very first
        statement, so conn.transaction() would emit BEGIN/COMMIT per post and silently move
        the batch's commit boundary. Raw SAVEPOINT rides on psycopg's implicit BEGIN and
        leaves the caller's single terminal commit exactly where it is. The savepoint is
        released on both paths so the stack does not grow across thousands of posts.
        """
        conn = cur.connection
        if getattr(conn, "autocommit", False):
            # No enclosing transaction to protect, and SAVEPOINT outside one is a no-op that
            # makes ROLLBACK TO fail. conn.transaction() opens a real one for the statement.
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


    def save_batch(
        self,
        conn: Connection,
        drafts: Sequence[PostDraft],
        *,
        commit_every: Optional[int] = None,
    ) -> SaveBatchResult:
        """Upsert many drafts with per-post isolation; owns the transaction on `conn`.

        Precondition: `conn` is not in autocommit mode and is idle. Commits every
        `commit_every` attempted drafts (failures included: a failed post costs savepoints
        too) and once at the end. A post that raises costs that post. If the failure left
        the transaction aborted, everything since the last commit is rolled back and
        reported as `discarded`, and the batch carries on.
        """
        commit_every = max(1, int(commit_every or SAVE_COMMIT_BATCH))
        result = SaveBatchResult()
        # Everything saved since the last commit: (draft, post_id, was_inserted).
        window: List[Tuple[PostDraft, str, bool]] = []
        channels: Set[str] = set()   # Telegram sources with a new post: their albums are folded at the end
        backlog_undated: Dict[str, List[str]] = {}   # a first fetch's undated posts, in its order (issue 0070)

        def commit() -> None:
            conn.commit()
            window.clear()

        with conn.cursor() as cur:
            cur.execute("SELECT s FROM unnest(%s::uuid[]) s WHERE EXISTS (SELECT 1 FROM posts WHERE source_id = s)",
                        (list({str(draft.source_id) for draft in drafts}),))
            fetched_before = {str(row[0]) for row in cur.fetchall()}
            for index, draft in enumerate(drafts, start=1):
                post = dict(draft.post)
                post.pop("_source_id", None)
                backlog = bool(post.pop(BACKLOG_KEY, False))
                try:
                    old = self._stored_text(cur, post["url"]) if draft.watch else None
                    post_id, was_inserted = self.upsert_post(cur, post, draft.source_id)
                except Exception as exc:
                    result.failures.append(PostSaveFailure(post.get("url"), draft.source_id, "upsert", str(exc)))
                    result._count(draft.source_id, "failed")
                    self.logger.error("Failed to save post %s (source %s): %s", post.get("url"), draft.source_id, exc)
                    # upsert_post normally leaves the transaction usable (its savepoints roll
                    # the bad statement back), but verify rather than assume: an aborted
                    # transaction rejects every later statement with 25P02, which would turn
                    # one bad row back into a lost batch.
                    if _transaction_is_poisoned(conn):
                        conn.rollback()
                        self._discard(result, window)
                        window.clear()
                else:
                    post_id = str(post_id)
                    window.append((draft, post_id, was_inserted))
                    if self._after_save(cur, draft, post, post_id, was_inserted, old,
                                        surface=draft.surface and not backlog):
                        result.resurfaced_ids.append(post_id)
                    if was_inserted:
                        result.inserted_ids.append(post_id)
                        result._count(draft.source_id, "inserted")
                        if str(post.get("url") or "").startswith(TELEGRAM_POST_PREFIX):
                            channels.add(draft.source_id)
                        if not post.get("date") and str(draft.source_id) not in fetched_before:
                            backlog_undated.setdefault(str(draft.source_id), []).append(post_id)
                    else:
                        result.updated_ids.append(post_id)
                        result._count(draft.source_id, "updated")

                if index % commit_every == 0:
                    commit()
            self._fold_albums(cur, channels)
            for ids in backlog_undated.values():
                cur.execute(UNDATED_BACKLOG_SQL, {"ids": ids})
        commit()
        return result

    def _fold_albums(self, cur: Cursor, source_ids: Iterable[str]) -> None:
        """A Telegram album is one post (issue 0069): the pictures the bridge sent as items of their
        own join the post they follow (migration 0051's fold_telegram_albums). A failure costs
        only the folding, which the channel's next batch does again."""
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
                    was_inserted: bool, old: Optional[Dict[str, Any]], *, surface: bool) -> bool:
        """Issue 0039, after a post is written: a new post first seen NEW_TO_YOU_AFTER past its
        date sorts at when it was first seen (surface), unless another source's post linked it
        before (0058: LINKED_BEFORE_SQL; only other posts' links count, so reading this post's
        own links first changes nothing); a watched post keeps its text's hash and
        comes back when it changed meaningfully. Issue 0050: its outside links are read from what
        was stored. In one savepoint (a post saved costs at most two; see SAVE_COMMIT_BATCH): a
        failure here is logged and costs neither the post nor the batch. Returns whether the post
        came back."""
        try:
            with self._savepoint(cur, "insight_after_save"):
                self.stories.save_post_links(cur, post_id)
                if surface and was_inserted:
                    cur.execute(
                        f"""UPDATE posts p SET surfaced_at = p.fetched_at
                             WHERE p.id = %s::uuid AND p.published_at < p.fetched_at - interval '{NEW_TO_YOU_AFTER}'
                               AND NOT {LINKED_BEFORE_SQL}""",
                        (post_id,),
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

    # ===============================
    # READ OPERATIONS
    # ===============================

    def get_source_post_stats(self, cur: Cursor, source_id: str) -> Dict[str, Any]:
        """Return aggregate storage stats for a single source.

        oldest_external_id is the oldest post's external_id: where an archive continues from
        (kind.start_checkpoint).
        """
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

    # ===============================
    # FULL TEXT (ingestion/full_text.py, scripts/repair_full_text.py)
    # ===============================

    def stored_urls(self, urls: Sequence[str]) -> set:
        """Which of these urls are already stored."""
        if not urls:
            return set()
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT url FROM posts WHERE url = ANY(%s)", (list(urls),))
            return {row[0] for row in cur.fetchall()}

    def drop_story_only(self, post_id: str) -> None:
        """A post shown only inside its story (issue 0126) becomes a row of its feed: you saved it."""
        with db.transaction(self.db_url) as cur:
            cur.execute(f"UPDATE posts SET metadata = metadata - '{STORY_ONLY_KEY}' WHERE id = %s::uuid AND metadata ? '{STORY_ONLY_KEY}'",
                        (post_id,))

    def teasers_to_read_again(self, source_id: str, *, now: datetime, max_tries: int, apart: timedelta,
                              limit: int) -> List[Dict[str, Any]]:
        """The source's stored teasers whose last page read failed (issue 0062), tried fewer than
        max_tries times, the last at least `apart` ago; oldest try first. Each as a post the saver
        writes back in place (its date None, so the stored one stays): url, title, bodies, media,
        categories and metadata as stored."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT url, title, content, content_html, media_urls, categories, metadata
                  FROM posts
                 WHERE source_id = %(source)s::uuid
                   AND NOT metadata ? '{FULL_TEXT_FLAG}'
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
                             retry: bool = False, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Stored posts whose body is shorter than short_chars, or a paid teaser of any length,
        never read from its page, newest first, each with its source. retry includes those a
        repair already tried."""
        cur.execute(
            f"""
            SELECT p.id, p.url, p.title, p.content, p.content_html, p.metadata,
                   s.id, s.platform, s.handle_or_url, s.settings
            FROM posts p JOIN sources s ON s.id = p.source_id
            WHERE (length(coalesce(p.content, '')) < %(short)s OR p.metadata @> '{{"paywalled": true}}')
              AND NOT p.metadata ? '{FULL_TEXT_FLAG}'
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
        """Store the full body of a stored post; its metadata is merged, never replaced. Its links
        are read again by the next story job (issue 0050). An undated post takes the page's date
        (issue 0070) and sorts at it, no longer where its first fetch placed it."""
        fields = build_post_fields(post)
        cur.execute(
            """
            UPDATE posts SET
                surfaced_at = CASE WHEN published_at IS NULL AND %(date)s::timestamptz IS NOT NULL
                                   THEN NULL ELSE surfaced_at END,
                published_precision = CASE WHEN published_at IS NULL AND %(date)s::timestamptz IS NOT NULL
                                           THEN %(precision)s ELSE published_precision END,
                published_at = COALESCE(published_at, %(date)s::timestamptz),
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
        """New plain text for stored posts, and the content hash it gives: the hash decodes
        codes only once, so a double-escaped body ("&amp;#39;") hashes differently decoded."""
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
        """Take the screen-reader labels inside links (0063's rule, parsing._without_hidden_link_labels)
        out of the bodies stored before the reader dropped them (issue 0068), from the stored HTML
        only: nothing is fetched. The plain text follows when it is that HTML's text; the hash
        follows, and the next story job reads the post's links again. Returns how many changed.
        The bodies are read a batch at a time (issue 0072: all at once, 2,958 of them, 214 MB on the
        lab, took the API to 796 MB)."""
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
