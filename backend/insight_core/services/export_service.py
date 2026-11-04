"""Export everything (issue 0079): the whole database as one zip, streamed to the browser.

The zip (`insight-YYYY-MM-DD-HHMM.zip`, written as it streams; nothing is kept on the server):
  - one CSV per table (`posts.csv`, …), written by `COPY … TO STDOUT (FORMAT csv, HEADER)` and
    read in chunks, so no table is ever held whole; every table in the app's schema but the
    migrations' bookkeeping, which goes in the manifest;
  - schema.sql: the migrations it was made at, in order;
  - manifest.json: the version and commit, the migrations, the time, each table's rows, whether
    logins are included;
  - README.txt: how to restore it (db/import_export.py) and how to explore it alone.
All of it reads one snapshot (a repeatable-read, read-only transaction on a connection of its
own, with no statement timeout), so the tables agree with each other.

Logins (the `credentials` table: the Substack cookie, the Telegram API id, hash and sign-in
session) are written as an empty CSV unless asked for; even then they are the stored ciphertext,
which reads only with this server's secret key.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from psycopg import IsolationLevel, sql

from insight_core.db import database as db
from insight_core.db.import_export import (BOOKKEEPING, CHUNK, FORMAT, FORMAT_VERSION, MIGRATIONS_DIR,
                                           sequences, tables_in_load_order)

logger = logging.getLogger(__name__)

LOGIN_TABLES = ("credentials",)
LOGINS_INCLUDE = ("the Substack session cookie and the Telegram API id, hash and sign-in session, "
                  "encrypted: they work after a restore only with this server's secret key")
# The estimate before the click, from the tables' stored size (heap and TOAST, no indexes).
# Measured 2026-11-05 on two lab copies (issue 0079's Built section): the zip is 0.44-0.46 of
# it, written at ~20 MB of it a second.
SIZE_RATIO = 0.45
TABLE_BYTES_PER_SECOND = 20e6
TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
KEPT_PROGRESS = 20

README = """INSIGHT export
==============

Every table of an INSIGHT database, as it was at {exported_at}.
manifest.json says the version, the migrations and each table's rows.
Stored logins: {logins}.

Restore it into INSIGHT (a new database: a restore never replaces data)
-----------------------------------------------------------------------
Copy the zip to the server, into the INSIGHT folder, then from that folder:

  docker compose run --rm -v "$PWD/{name}:/tmp/{name}:ro" backend \
    python insight_core/db/import_export.py /tmp/{name} --into insight_restored

It creates the database insight_restored, runs the export's migrations, loads every CSV in
the order the foreign keys need, then migrates up to the running version. To read it, set
DB_NAME=insight_restored in .env and run docker compose up -d (DEPLOYMENT.md, "Restoring an
export").

Explore it on its own
---------------------
Each CSV has a header row and opens in any tool:
  DuckDB:      SELECT * FROM 'posts.csv';
  pandas:      pandas.read_csv("posts.csv")
  SQLite:      .import --csv posts.csv posts
  spreadsheet: the small tables (sources.csv, folders.csv, ...)
Or into any PostgreSQL with the pgvector extension:
  psql -d mydb -f schema.sql
  psql -d mydb -c "\\copy posts FROM 'posts.csv' (FORMAT csv, HEADER)"   (one per CSV, in
  manifest.json's table order)
"""


class _Sink:
    """The zip's output: what was written since the last take(). No seek or tell, so zipfile
    writes each entry's sizes after its data (a stream)."""

    def __init__(self) -> None:
        self.parts: List[bytes] = []
        self.size = 0

    def write(self, data: bytes) -> int:
        self.parts.append(bytes(data))
        self.size += len(data)
        return len(data)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        out = b"".join(self.parts)
        self.parts.clear()
        return out


def _entry(name: str, when: datetime) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=when.timetuple()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def schema_sql(versions: List[str]) -> str:
    parts = ["-- The schema this export's data belongs to: INSIGHT's migrations, in order.\n"]
    for version in versions:
        path = MIGRATIONS_DIR / version
        body = path.read_text(encoding="utf-8") if path.exists() else "-- (not in this version's files)\n"
        parts.append(f"\n-- ==== {version} ====\n{body.rstrip()}\n")
    return "".join(parts)


class ExportService:
    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def info(self) -> Dict[str, Any]:
        """Shown before the click: the database's size, and the zip's estimated size and time."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            tables = tables_in_load_order(cur)
            cur.execute("SELECT pg_database_size(current_database()), "
                        "coalesce(sum(pg_table_size(format('%%I', t)::regclass)), 0)::bigint FROM unnest(%s::text[]) t",
                        (tables,))
            database_bytes, table_bytes = cur.fetchone()
        return {
            "database_bytes": int(database_bytes),
            "estimate_bytes": int(table_bytes * SIZE_RATIO),
            "estimate_seconds": max(1, round(table_bytes / TABLE_BYTES_PER_SECOND)),
            "tables": len(tables),
            "login_tables": list(LOGIN_TABLES),
            "logins_include": LOGINS_INCLUDE,
        }

    @staticmethod
    def file_name(now: Optional[datetime] = None) -> str:
        return f"insight-{(now or datetime.now(timezone.utc)).strftime('%Y-%m-%d-%H%M')}.zip"

    def progress(self, token: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            state = self._progress.get(token)
            return dict(state) if state else None

    def _track(self, token: Optional[str], name: str) -> Dict[str, Any]:
        state = {"file_name": name, "bytes": 0, "done": False, "error": None}
        if token and TOKEN.match(token):
            with self._lock:
                self._progress[token] = state
                for old in list(self._progress)[:-KEPT_PROGRESS]:
                    del self._progress[old]
        return state

    def stream(self, *, include_logins: bool = False, token: Optional[str] = None,
               name: Optional[str] = None) -> Iterator[bytes]:
        """The zip, in pieces as it is written (a generator: nothing runs until the first is asked for)."""
        now = datetime.now(timezone.utc)
        name = name or self.file_name(now)
        state = self._track(token, name)
        sink = _Sink()
        conn = db.session_connection(self.db_url)
        try:
            conn.isolation_level = IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            with conn.cursor() as cur, zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                tables = tables_in_load_order(cur)
                cur.execute(f"SELECT version, applied_at FROM {BOOKKEEPING} ORDER BY version")
                migrations = [{"version": v, "applied_at": at.isoformat()} for v, at in cur.fetchall()]
                logins = "included (" + LOGINS_INCLUDE + ")" if include_logins else "left out (re-enter them in Sources → Connections)"
                archive.writestr(_entry("README.txt", now), README.format(exported_at=now.isoformat(timespec="seconds"),
                                                                          logins=logins, name=name))
                archive.writestr(_entry("schema.sql", now), schema_sql([m["version"] for m in migrations]))
                yield self._sent(state, sink)
                listed = []
                for table in tables:
                    left_out = table in LOGIN_TABLES and not include_logins
                    query = (sql.SQL("COPY (SELECT * FROM {} LIMIT 0) TO STDOUT (FORMAT csv, HEADER)") if left_out
                             else sql.SQL("COPY {} TO STDOUT (FORMAT csv, HEADER)")).format(sql.Identifier(table))
                    with archive.open(_entry(f"{table}.csv", now), "w", force_zip64=True) as entry:
                        buffer = bytearray()
                        with cur.copy(query) as copy:
                            for data in copy:
                                buffer += data
                                if len(buffer) >= CHUNK:
                                    entry.write(buffer)
                                    buffer.clear()
                                    if sink.size:
                                        yield self._sent(state, sink)
                        entry.write(buffer)
                    listed.append({"name": table, "file": f"{table}.csv", "rows": 0 if left_out else cur.rowcount})
                    yield self._sent(state, sink)
                manifest = {
                    "format": FORMAT, "format_version": FORMAT_VERSION,
                    "insight_version": os.getenv("INSIGHT_VERSION") or None,
                    "commit": os.getenv("INSIGHT_COMMIT") or None,
                    "exported_at": now.isoformat(timespec="seconds"),
                    "last_migration": migrations[-1]["version"] if migrations else None,
                    "migrations": migrations,
                    "logins_included": include_logins,
                    "login_tables": list(LOGIN_TABLES),
                    "tables": listed,
                    "sequences": sequences(cur),
                }
                archive.writestr(_entry("manifest.json", now), json.dumps(manifest, indent=2) + "\n")
            yield self._sent(state, sink)
            state["done"] = True
        except GeneratorExit:
            state["error"] = "stopped before the end"
            raise
        except Exception:
            state["error"] = "failed: check the backend logs"
            logger.exception("Export: %s failed", name)
            raise
        finally:
            conn.close()

    @staticmethod
    def _sent(state: Dict[str, Any], sink: _Sink) -> bytes:
        state["bytes"] += sink.size
        sink.size = 0
        return sink.take()
