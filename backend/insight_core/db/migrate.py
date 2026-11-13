#!/usr/bin/env python3
"""The migration runner: every pending file in migrations/, in name order, at each container's start.

    python insight_core/db/migrate.py             # apply the pending migrations
    python insight_core/db/migrate.py --pending   # list them, the tables each touches and their rows; change nothing

- **One transaction per migration** (v10.17, 0188): each file and its schema_migrations row commit together, so a
  run that fails at the fifth file keeps the four before it, and a big early migration never waits on a later one.
  (Until v10.16 every pending file ran in one transaction committed at the end.)
- **One runner at a time:** the API and insight-ingestion both migrate at their start. The runner holds a
  session-level advisory lock (`hold_migration_lock`) on its own connection for the whole run, not a transaction's:
  with a commit per migration a transaction lock would end at the first commit and let a second runner in mid-run.
  Postgres ends a session lock with its connection, so a crashed runner never leaves it held. The second runner
  waits, then sees every version applied. (`acquire_migration_lock`, the transaction lock on the same key, stays for
  the archive restore, db/import_export.py; the two conflict, as they should.)
- **A lock timeout per migration:** `SET LOCAL lock_timeout` (INSIGHT_MIGRATION_LOCK_TIMEOUT, seconds, default 10),
  so a migration that needs a table a long query or a running job holds fails fast instead of queueing every
  request behind its lock; it is tried again INSIGHT_MIGRATION_LOCK_RETRIES times (default 5), RETRY_WAIT seconds
  apart and more each time, then the start fails (and Docker starts the container again).
- **`-- no transaction`** in a file's first lines (its header comment): the file runs outside a transaction, one
  statement at a time (split at top-level `;`), and its row is written after the last statement succeeds. For
  `CREATE INDEX CONCURRENTLY` on a big table (which a transaction refuses). Every statement must be safe to run again
  (IF NOT EXISTS), since a failure part-way is retried from the top; a CONCURRENTLY build that failed leaves an
  INVALID index, so such a file drops it first (`DROP INDEX CONCURRENTLY IF EXISTS ...`). The archive restore runs
  files in one transaction and can't take such a file.

**What belongs in a migration:** the schema, and data changes that are quick on the server's tables. A rewrite of
many rows (a backfill, a re-derivation) is a resumable job (a batch at a time, recording where it stopped, as the
Mark X backfills and repair scripts do), never one UPDATE in a migration: that one statement holds its locks and its
start for as long as it runs. A big index is built CONCURRENTLY in a `-- no transaction` migration. `--pending` (which
./update runs before the start that migrates) lists the tables each pending file touches with their row estimates,
so a heavy one is seen before it runs.
"""
import os
import re
import sys
import glob
import time
from dotenv import load_dotenv
import psycopg
from psycopg import errors as pg_errors
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.db.ensure_db import ensure_database


setup_logging(debug_mode=True)
logger = get_component_logger("db_migrate")

LOCK_TIMEOUT_SECONDS = 10.0      # INSIGHT_MIGRATION_LOCK_TIMEOUT: a migration waits this long for a table's lock
LOCK_RETRIES = 5                 # INSIGHT_MIGRATION_LOCK_RETRIES: then it is tried again this many times
RETRY_WAIT = 2.0                 # seconds before the first retry; the n-th waits n times this
NO_TRANSACTION = "-- no transaction"
HEADER_LINES = 5                 # the marker counts in a file's first lines only


def get_conn(*, autocommit: bool = False) -> psycopg.Connection:
    load_dotenv()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set in environment")
    return psycopg.connect(dsn, autocommit=autocommit)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        logger.warning("%s=%r is not a number; using %s", name, os.getenv(name), default)
        return default


def ensure_schema_migrations(cur: psycopg.Cursor) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


MIGRATION_LOCK_KEY = "insight.migrate"


def acquire_migration_lock(cur: psycopg.Cursor) -> None:
    """The migration lock for one transaction (the archive restore, db/import_export.py, which loads every file in
    one): must be its first statement; Postgres releases it at commit or rollback."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))


def hold_migration_lock(conn: psycopg.Connection) -> None:
    """The runner's lock, held by `conn`'s session until `release_migration_lock` or the connection closes (a crashed
    runner's ends with it). Two runners at once (the API and ingestion start together): the second waits here, then
    finds every version applied. Same key as `acquire_migration_lock`, so a restore and a runner exclude each other."""
    conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))


def release_migration_lock(conn: psycopg.Connection) -> None:
    conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (MIGRATION_LOCK_KEY,))

def applied_versions(cur: psycopg.Cursor) -> Set[str]:
    cur.execute("SELECT version FROM schema_migrations")
    return {r[0] for r in cur.fetchall()}

def discover_migrations(mig_dir: Path) -> List[Path]:
    """Return sorted list of migration SQL files in the given directory."""
    files = sorted(glob.glob(str(mig_dir / "*.sql")))
    return [Path(f) for f in files]


def apply_one(cur: psycopg.Cursor, path: Path, version: str) -> bool:
    """Apply a single SQL migration and record it in schema_migrations, on the caller's transaction.

    Returns True when this process recorded the migration version itself and
    False when the version was already present.
    """
    cur.execute(path.read_text(encoding="utf-8"))
    return record(cur, version)


def record(cur: psycopg.Cursor, version: str) -> bool:
    cur.execute(
        """
        INSERT INTO schema_migrations(version, applied_at)
        VALUES (%s, %s)
        ON CONFLICT (version) DO NOTHING
        RETURNING version
        """,
        (version, datetime.now(timezone.utc)),
    )
    return cur.fetchone() is not None


def no_transaction(sql: str) -> bool:
    """Whether the file asks to run outside a transaction: `-- no transaction` in its first HEADER_LINES lines."""
    return any(line.strip().lower().startswith(NO_TRANSACTION) for line in sql.splitlines()[:HEADER_LINES])


def split_statements(sql: str) -> List[str]:
    """The file's statements, split at the `;` outside quotes, comments and dollar quotes (a `-- no transaction`
    file runs them one by one: Postgres runs a multi-statement string as one implicit transaction)."""
    out: List[str] = []
    buf: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            buf.append(sql[i:j])
            i = j
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            buf.append(sql[i:j])
            i = j
            continue
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:   # a doubled quote inside
                        j += 2
                        continue
                    break
                j += 1
            buf.append(sql[i:j + 1])
            i = j + 1
            continue
        m = re.match(r"\$[A-Za-z_]*\$", sql[i:i + 64]) if c == "$" else None
        if m:
            tag = m.group(0)
            j = sql.find(tag, i + len(tag))
            j = n if j < 0 else j + len(tag)
            buf.append(sql[i:j])
            i = j
            continue
        if c == ";":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    out.append("".join(buf))
    return [st.strip() for st in out if _has_code(st)]


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)


def _has_code(statement: str) -> bool:
    return bool(_strip_comments(statement).strip())


def run_one(conn: psycopg.Connection, path: Path, version: str, *, lock_timeout: Optional[float] = None,
            retries: Optional[int] = None, wait: float = RETRY_WAIT, sleep: Callable[[float], None] = time.sleep) -> bool:
    """One migration on `conn` (autocommit): in a transaction of its own with its row, or, marked `-- no
    transaction`, a statement at a time and its row after. Each waits at most `lock_timeout` seconds for a lock; one
    that times out is tried again `retries` times (waiting `wait`, then 2x, ...), then raises. True when this run
    recorded the version."""
    if lock_timeout is None:
        lock_timeout = _env_float("INSIGHT_MIGRATION_LOCK_TIMEOUT", LOCK_TIMEOUT_SECONDS)
    if retries is None:
        retries = int(_env_float("INSIGHT_MIGRATION_LOCK_RETRIES", LOCK_RETRIES))
    sql = path.read_text(encoding="utf-8")
    timeout_ms = str(max(0, int(lock_timeout * 1000)))
    attempt = 0
    while True:
        try:
            if no_transaction(sql):
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('lock_timeout', %s, false)", (timeout_ms,))
                    try:
                        for statement in split_statements(sql):
                            cur.execute(statement)
                    finally:
                        if not conn.closed:
                            cur.execute("RESET lock_timeout")
                    with conn.transaction():
                        return record(cur, version)
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SELECT set_config('lock_timeout', %s, true)", (timeout_ms,))   # SET LOCAL
                return apply_one(cur, path, version)
        except pg_errors.LockNotAvailable as exc:
            attempt += 1
            if attempt > retries:
                logger.error("%s: no lock within %s s, %d times; giving up", version, lock_timeout, attempt)
                raise
            logger.warning("%s: a lock it needs is held (%s); trying again in %.1f s (%d of %d)",
                           version, str(exc).strip().splitlines()[0], wait * attempt, attempt, retries)
            sleep(wait * attempt)


# The tables a statement names, best effort (--pending): what it creates, alters, indexes, writes or empties.
_TOUCH = re.compile(
    r"""\b(?:CREATE\s+(?:UNLOGGED\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?
         |ALTER\s+TABLE(?:\s+IF\s+EXISTS)?(?:\s+ONLY)?
         |CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+CONCURRENTLY)?(?:\s+IF\s+NOT\s+EXISTS)?(?:\s+[\w"]+)?\s+ON(?:\s+ONLY)?
         |UPDATE(?:\s+ONLY)?
         |INSERT\s+INTO
         |DELETE\s+FROM(?:\s+ONLY)?
         |TRUNCATE(?:\s+TABLE)?(?:\s+ONLY)?
         |DROP\s+TABLE(?:\s+IF\s+EXISTS)?
         |CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+[\w"]+\s+(?:BEFORE|AFTER|INSTEAD\s+OF)\s+[\w\s,]+?\s+ON
        )\s+((?:[\w"]+\.)?[\w"]+)""", re.I | re.X)
_NOT_TABLES = {"set", "select", "values", "only", "if", "on", "of"}


def touched_tables(sql: str) -> List[str]:
    """The tables `sql` names in a CREATE/ALTER/DROP TABLE, CREATE INDEX ... ON, UPDATE, INSERT INTO, DELETE FROM,
    TRUNCATE or CREATE TRIGGER ... ON, in first-seen order (comments ignored; a DO block's statements count)."""
    seen: Dict[str, None] = {}
    for m in _TOUCH.finditer(_strip_comments(sql)):
        name = m.group(1).replace('"', "").lower()
        if name.split(".")[-1] not in _NOT_TABLES:
            seen.setdefault(name, None)
    return list(seen)


def table_rows(cur: psycopg.Cursor, tables: List[str]) -> Dict[str, Optional[int]]:
    """Postgres's row estimate for each table (pg_class.reltuples, no scan): None for a table that doesn't exist yet,
    -1 for one never analyzed."""
    out: Dict[str, Optional[int]] = {}
    for t in tables:
        cur.execute("SELECT c.reltuples::bigint FROM pg_class c WHERE c.oid = to_regclass(%s)", (t,))
        row = cur.fetchone()
        out[t] = None if row is None else int(row[0])
    return out


def _rows_text(rows: Optional[int]) -> str:
    if rows is None:
        return "new"
    if rows < 0:
        return "rows unknown"
    return f"~{rows:,} rows"


def pending_migrations(cur: psycopg.Cursor, mig_dir: Path) -> List[Path]:
    """The migration files this database hasn't applied; on a new database, every one."""
    cur.execute("SELECT to_regclass('schema_migrations') IS NOT NULL")
    already = applied_versions(cur) if cur.fetchone()[0] else set()
    return [p for p in discover_migrations(mig_dir) if p.name not in already]


def pending_report(cur: psycopg.Cursor, mig_dir: Path) -> List[str]:
    """--pending's lines: each pending migration with its header's first line, then (v10.17) the tables it touches
    with their row estimates, so a migration that rewrites a big table is seen before it runs; the count last."""
    lines: List[str] = []
    pending = pending_migrations(cur, mig_dir)
    for path in pending:
        sql = path.read_text(encoding="utf-8")
        first = (sql.splitlines() or [""])[0]
        lines.append("  " + (first.lstrip("- ").strip() if first.startswith("--") else path.name)
                     + ("  [no transaction]" if no_transaction(sql) else ""))
        rows = table_rows(cur, touched_tables(sql))
        if rows:
            lines.append("      touches: " + ", ".join(f"{t} ({_rows_text(r)})" for t, r in rows.items()))
    lines.append(f"{len(pending)} migration(s) will run at the start" if pending else "No migration to run")
    return lines


def print_pending(mig_dir: Path) -> None:
    """--pending (`update` runs it before the start that migrates, issue 0071), on stdout. Changes nothing."""
    with get_conn() as conn, conn.cursor() as cur:
        lines = pending_report(cur, mig_dir)
    print("\n".join(lines))


def migrate(conn: psycopg.Connection, mig_dir: Path) -> List[str]:
    """Every pending migration on `conn` (autocommit), each in its own transaction, under the runner's session lock;
    the versions this run recorded."""
    hold_migration_lock(conn)
    try:
        with conn.transaction(), conn.cursor() as cur:
            ensure_schema_migrations(cur)
            already = applied_versions(cur)
        all_files = discover_migrations(mig_dir)
        pending = [(p.name, p) for p in all_files if p.name not in already]

        logger.info("Found %s migration(s); %d already applied; %d pending",
                    len(all_files), len(already), len(pending))
        logger.debug("Already applied: %s", sorted(already))
        logger.debug("Pending %s", [v for v, _ in pending])

        if not pending:
            logger.info("Up to date")
            return []

        applied: List[str] = []
        for version, path in pending:
            logger.info("Applying %s...", version)
            try:
                recorded = run_one(conn, path, version)
            except Exception as e:
                logger.error("Failed applying %s; %s (the migrations before it stay committed)", version, e)
                raise
            if recorded:
                applied.append(version)
                logger.info("Applied %s", version)
            else:
                logger.info("Migration %s was already recorded; SQL was still executed idempotently", version)
        logger.info("All Pending migrations applied successfully")
        return applied
    finally:
        if not conn.closed and not conn.broken:
            release_migration_lock(conn)


def main():
    """Entry point: apply any pending migrations, each in its own transaction, one runner at a time."""
    mig_dir = Path(__file__).resolve().parent / "migrations"

    logger.info("Starting migration runner")
    logger.debug("Migrations Directory: %s", mig_dir)

    # 2) Bootsrap DB / Database url
    try:
        db_url = ensure_database()
        os.environ["DATABASE_URL"] = db_url
        logger.info("Database was ensured and using")
    except Exception as e:
        logger.exception("Error {e}")
        sys.exit(1)

    if "--pending" in sys.argv[1:]:
        print_pending(mig_dir)
        return

    try:
        with get_conn(autocommit=True) as conn:
            migrate(conn, mig_dir)
    except Exception:
        # A failed migration's own transaction rolled back; the ones before it are committed.
        logger.exception("Migration failed with an exception")
        sys.exit(1)


if __name__ == "__main__":
    main()
