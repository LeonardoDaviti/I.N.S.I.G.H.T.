#!/usr/bin/env python3
import os
import sys
import glob
from dotenv import load_dotenv
import psycopg
from pathlib import Path
from datetime import datetime

def get_conn():
    try:
        load_dotenv()
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            print("DATABASE_URL not set"); sys.exit(1)
        return psycopg.connect(dsn)
    except Exception as e:
        print(f"Error occured: {e}")


def ensure_schema_migrations(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

def applied_versions(cur):
    cur.execute("SELECT version FROM schema_migrations")
    return {r[0] for r in cur.fetchall()}

def apply_sql(cur, path, version):
    sql = Path(path).read_text(encoding="utf-8")
    cur.execute(sql)
    cur.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (%s, %s)",
        (version, datetime.utcnow()),
    )

def main():
    mig_dir = Path(__file__).resolve().parent / "migrations"
    files = sorted(glob.glob(str(mig_dir / "*.sql")))
    if not files:
        print("No migrations found"); return

    with get_conn() as conn:
        with conn.cursor() as cur:
            ensure_schema_migrations(cur)
            done = applied_versions(cur)
            to_apply = [(Path(p).name, p) for p in files if Path(p).name not in done]
            if not to_apply:
                print("Up to date"); return
            for version, path in to_apply:
                print(f"Applying {version} ...")
                apply_sql(cur, path, version)
        conn.commit()
    print("Migrations applied")

if __name__ == "__main__":
    main()