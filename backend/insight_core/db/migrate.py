#!/usr/bin/env python3
import os
import sys
import glob
from dotenv import load_dotenv
import psycopg
from pathlib import Path
from datetime import datetime
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


def acquire_migration_lock(cur: psycopg.Cursor) -> None:
    """Serialize migrations across multiple processes/containers."""
    # The local psycopg shim does not handle advisory locks cleanly.
    # Migrations in this environment are single-process, so a no-op is sufficient.
    return None


def release_migration_lock(cur: psycopg.Cursor) -> None:
    """Release the migration advisory lock."""
    return None

def applied_versions(cur: psycopg.Cursor) -> Set[str]:
    cur.execute("SELECT version FROM schema_migrations")
    return {r[0] for r in cur.fetchall()}

def discover_migrations(mig_dir: Path) -> List[Path]:
    """Return sorted list of migration SQL files in the given directory."""
    files = sorted(glob.glob(str(mig_dir / "*.sql")))
    return [Path(f) for f in files]

def apply_one(cur: psycopg.Cursor, path: Path, version: str) -> None:
    """Apply a single SQL migration and record it in schema_migrations."""
    sql = path.read_text(encoding="utf-8")
    cur.execute(sql)
    cur.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (%s, %s)",
        (version, datetime.utcnow()),
    )

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
                        apply_one(cur, path, version)
                        logger.info("Applied %s", version)
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
