#!/usr/bin/env python3
import os
import sys
import glob
from dotenv import load_dotenv
import psycopg
from pathlib import Path
from datetime import datetime, timezone
from typing import Set, List

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.db.ensure_db import ensure_database


setup_logging(debug_mode=True)
logger = get_component_logger("db_migrate")


def get_conn() -> psycopg.Connection:
    load_dotenv()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set in environment")
    return psycopg.connect(dsn)


def ensure_schema_migrations(cur: psycopg.Cursor) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


MIGRATION_LOCK_KEY = "insight.migrate"


def acquire_migration_lock(cur: psycopg.Cursor) -> None:
    """Serialize migrations across processes/containers. Must be the transaction's first statement.

    The backend and ingestion containers both run migrate.py at start. Two concurrent
    transactions running the same `CREATE TABLE IF NOT EXISTS` can still fail with a
    duplicate pg_type key, so the second one waits here until the first commits - and
    then sees every version already applied. A transaction-scoped lock: Postgres releases
    it at commit or rollback, so a crashed migrator can never leave it held.
    """
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))


def release_migration_lock(cur: psycopg.Cursor) -> None:
    """No-op: the xact lock taken by acquire_migration_lock ends with the transaction."""
    return None

def applied_versions(cur: psycopg.Cursor) -> Set[str]:
    cur.execute("SELECT version FROM schema_migrations")
    return {r[0] for r in cur.fetchall()}

def discover_migrations(mig_dir: Path) -> List[Path]:
    """Return sorted list of migration SQL files in the given directory."""
    files = sorted(glob.glob(str(mig_dir / "*.sql")))
    return [Path(f) for f in files]

def apply_one(cur: psycopg.Cursor, path: Path, version: str) -> bool:
    """Apply a single SQL migration and record it in schema_migrations.

    Returns True when this process recorded the migration version itself and
    False when the version was already present.
    """
    sql = path.read_text(encoding="utf-8")
    cur.execute(sql)
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

def pending_migrations(cur: psycopg.Cursor, mig_dir: Path) -> List[Path]:
    """The migration files this database hasn't applied; on a new database, every one."""
    cur.execute("SELECT to_regclass('schema_migrations') IS NOT NULL")
    already = applied_versions(cur) if cur.fetchone()[0] else set()
    return [p for p in discover_migrations(mig_dir) if p.name not in already]


def print_pending(mig_dir: Path) -> None:
    """--pending (`update` runs it before the start that migrates, issue 0071): each pending
    migration with its header's first line, on stdout. Changes nothing."""
    with get_conn() as conn, conn.cursor() as cur:
        pending = pending_migrations(cur, mig_dir)
    for path in pending:
        first = (path.read_text(encoding="utf-8").splitlines() or [""])[0]
        print("  " + (first.lstrip("- ").strip() if first.startswith("--") else path.name))
    print(f"{len(pending)} migration(s) will run at the start" if pending else "No migration to run")


def main():
    """Entry point: apply any pending migrations automaically"""
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
        with get_conn() as conn:
            with conn.cursor() as cur:
                acquire_migration_lock(cur)
                ensure_schema_migrations(cur)

                already = applied_versions(cur)
                all_files = discover_migrations(mig_dir)
                versions = [f.name for f in all_files]
                pending = [(v, p) for v, p in zip(versions, all_files) if v not in already]

                logger.info("Found %s migration(s); %d already applied; %d pending",
                            len(all_files), len(already), len(pending))
                logger.debug("Already applied: %s", sorted(already))
                logger.debug("Pending %s", [v for v, _ in pending])

                if not pending:
                    logger.info("Up to date")
                    # print("Up to date")
                    return
                
                for version, path in pending:
                    logger.info("Applying %s...", version)
                    try:
                        recorded = apply_one(cur, path, version)
                        if recorded:
                            logger.info("Applied %s", version)
                        else:
                            logger.info("Migration %s was already recorded; SQL was still executed idempotently", version)
                    except Exception as e:
                        logger.error("Failed applying %s; %s", version, e)
                        raise
                release_migration_lock(cur)
                
            conn.commit()
            logger.info("All Pending migrations applied successfully")
        
    except Exception:
        # Psycopg context manager rolls back automatically on exception.
        logger.exception("Migration failed with an exception")
        # Optionally print the stack trace for console runs
        # traceback.print_exc()
        sys.exit(1)
    
if __name__ == "__main__":
    main()
