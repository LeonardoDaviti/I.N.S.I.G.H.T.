#!/usr/bin/env python3
from __future__ import annotations

import os, socket
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import psycopg
from psycopg import Connection, Cursor
from psycopg import sql
import sys

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.logs.core.logger_config import setup_logging, get_component_logger

setup_logging(debug_mode=False)
logger = get_component_logger("db_bootstrap")

def env_get(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return env var value or default if unset/empty."""
    v = os.getenv(name)
    return v if v else default

def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Quick TCP probe to check if host:port is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _ensure_role(cur: Cursor, user: str, password: str) -> None:
    """Create a role if it does not exist; otherwise no-op."""
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,))
    if cur.fetchone():
        logger.info("Role %s already exists", user)
        return
    logger.info("Creating role %s", user)
    cur.execute(
        sql.SQL("CREATE USER {} WITH PASSWORD %s").format(sql.Identifier(user)),
        (password,),
    )

def _ensure_database(cur: Cursor, dbname: str, owner: str) -> None:
    """Create a database if it does not exist; otherwise no-op."""
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
    if cur.fetchone():
        logger.info("Database %s already exists", dbname)
        return
    logger.info("Creating database %s owned by %s", dbname, owner)
    cur.execute(
        sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(dbname), sql.Identifier(owner)
        )
    )

def ensure_database() -> str:
    """
    Ensure the application database exists and return a usable DATABASE_URL.
    If DATABASE_URL is already set in the env, return it unchanged.
    Otherwise, create role+db using ADMIN_DATABASE_URL (or a local default).
    """
    load_dotenv()

    # 1) Respect existing DATABASE_URL
    db_url = env_get("DATABASE_URL")
    if db_url:
        logger.info("DATABASE_URL already set")

    # 2) App DB parameters
    db_name = env_get("DB_NAME", "insight")
    db_user = env_get("DB_USER", "insight")
    db_pass = env_get("DB_PASSWORD", "insight")
    db_host = env_get("DB_HOST", "localhost")
    db_port = env_get("DB_PORT", "5432")

    # 3) Admin DSN and basic reachability hints
    admin_url = env_get("ADMIN_DATABASE_URL", "postgresql://postgres@localhost:5432/postgres")
    host_for_probe = db_host or "localhost"
    port_for_probe = int(db_port or "5432")

    if not is_port_open(host_for_probe, port_for_probe):
        logger.warning("PostgreSQL not reachable at %s:%s; ensure service is running", host_for_probe, port_for_probe)

    # Create role/database if needed
    try:
        with psycopg.connect(admin_url) as conn:
            with conn.cursor() as cur:
                _ensure_role(cur, db_user, db_pass)
                _ensure_database(cur, db_name, db_user)
            conn.commit()
    except Exception as e:
        logger.exception("Admin bootstrap failed. Set ADMIN_DATABASE_URL or start Postgres. Error: %s", e)
        raise

    # 4) Build and return the application DSN
    app_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    logger.info("Prepared application DATABASE_URL")
    return app_url

if __name__ == "__main__":
    try:
        url = ensure_database()
        print(url)
    except Exception:
        sys.exit(1)