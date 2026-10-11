import os, sys, json, hashlib
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Iterator, List, Literal, Sequence, Tuple, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import Connection, Cursor

from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.db.ensure_db import ensure_database
from insight_core.utils.post_fields import build_post_fields
from insight_core.utils.json_safe import json_default


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


@dataclass(frozen=True)
class PostDraft:
    """A normalized post dict (url, title, content, date, ...) before it is saved."""

    source_id: str
    post: dict


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


class PostsRepository:
    """
    Database access layer for posts table.
    Handles all SQL operations for storing and retrieving posts.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url

        self.logger = get_component_logger("repo_posts")
        self.logger.info(f"PostsRepository initialized")

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

    # Bounded because each retry only happens when another writer moved the rows under us.
    # Every resolver branch converges (see _resolve_external_id_collision), so exhausting
    # this means something is genuinely wrong rather than merely contended.
    _CONFLICT_MAX_ATTEMPTS = 4

    _CONFLICT_LOOKUP_SQL = """
        WITH url_row AS (
            SELECT id, source_id
              FROM posts
             WHERE url = %(url)s
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
                metadata,
                media_urls,
                categories
            )
            VALUES (
                %(source_id)s,
                %(url)s,
                %(external_id)s,
                %(published_at)s,
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
                %(metadata)s::jsonb,
                %(media_urls)s::jsonb,
                %(categories)s::jsonb
            )
            ON CONFLICT (url) DO UPDATE SET
                {assignments}
            RETURNING id, (xmax = 0) AS inserted
        """.format(assignments=self._post_update_assignments(row_prefix="posts."))

        for attempt in range(self._CONFLICT_MAX_ATTEMPTS):
            try:
                # The savepoint is what stops one bad row from poisoning the whole batch.
                # Without it Postgres puts the backend in aborted-transaction state and every
                # later statement fails with 25P02, so the caller's single terminal commit is
                # never reached and every post gathered that cycle is rolled back.
                with self._savepoint(cur, "insight_upsert_post"):
                    cur.execute(query, params)
                    row = cur.fetchone()
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

            post_id = str(row[0])  # UUID → string
            was_inserted = row[1]  # Boolean

            # Log action
            action = "Inserted" if was_inserted else "Updated"
            self.logger.debug(f"{action} post: {url[:60]}...")

            return (post_id, was_inserted)

        raise RuntimeError(
            f"upsert_post could not resolve {self._CONFLICT_INDEX} for {url} "
            f"after {self._CONFLICT_MAX_ATTEMPTS} attempts"
        )

    def _resolve_external_id_collision(
        self, cur: Cursor, params: Dict[str, Any], *, attempt: int = 0
    ) -> Optional[Tuple[str, bool]]:
        """Settle a (source_id, external_id) clash by identity. Returns None to retry the insert.

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
        assignments: List[str] = []
        if set_url:
            assignments.append("url = %(url)s")
        if set_external_id:
            assignments.append(f"external_id = COALESCE(%(external_id)s, {row}external_id)")
        assignments.extend([
            f"published_at = COALESCE(%(published_at)s, {row}published_at)",
            f"title = COALESCE(%(title)s, {row}title)",
            f"content = COALESCE(%(content)s, {row}content)",
            f"content_html = COALESCE(%(content_html)s, {row}content_html)",
            f"lang = COALESCE(%(lang)s, {row}lang)",
            f"content_hash = COALESCE(%(content_hash)s, {row}content_hash)",
            "language_code = %(language_code)s",
            "language_confidence = %(language_confidence)s",
            "normalized_url = %(normalized_url)s",
            "canonical_url = %(canonical_url)s",
            "url_host = %(url_host)s",
            f"metadata = {metadata_expr or f'COALESCE(%(metadata)s::jsonb, {row}metadata)'}",
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

        def commit() -> None:
            conn.commit()
            window.clear()

        with conn.cursor() as cur:
            for index, draft in enumerate(drafts, start=1):
                post = dict(draft.post)
                post.pop("_source_id", None)
                try:
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
                    if was_inserted:
                        result.inserted_ids.append(post_id)
                        result._count(draft.source_id, "inserted")
                    else:
                        result.updated_ids.append(post_id)
                        result._count(draft.source_id, "updated")

                if index % commit_every == 0:
                    commit()
        commit()
        return result

    def _discard(self, result: SaveBatchResult, window: List[Tuple[PostDraft, str, bool]]) -> None:
        """Move every draft saved since the last commit into failures as `discarded`."""
        if not window:
            return
        lost_ids = {post_id for _, post_id, _ in window}
        result.inserted_ids = [i for i in result.inserted_ids if i not in lost_ids]
        result.updated_ids = [i for i in result.updated_ids if i not in lost_ids]
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
        """Return aggregate storage stats for a single source."""
        query = """
            SELECT
                COUNT(*) AS post_count,
                MIN(published_at) AS oldest_published_at,
                MAX(published_at) AS latest_published_at,
                MAX(fetched_at) AS latest_fetched_at
            FROM posts
            WHERE source_id = %s
        """
        cur.execute(query, (source_id,))
        row = cur.fetchone()

        return {
            "post_count": row[0] or 0,
            "oldest_published_at": row[1],
            "latest_published_at": row[2],
            "latest_fetched_at": row[3],
        }

    def update_post_metadata(self, cur: Cursor, post_id: str, metadata: Dict[str, Any]) -> bool:
        """Persist metadata for a single post."""
        query = """
            UPDATE posts
            SET metadata = %s::jsonb,
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(query, (self._json_dumps(metadata), post_id))
        return cur.fetchone() is not None

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
