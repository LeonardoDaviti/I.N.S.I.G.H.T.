#!/usr/bin/env python3
"""Restore INSIGHT's own export (issue 0079) into a new or empty database.

    python insight_core/db/import_export.py insight-….zip --into insight_restored

DATABASE_URL names the server (and the database, without --into).

The export (services/export_service.py, Settings → Data) is a zip: one CSV per table, written
by `COPY … TO STDOUT (FORMAT csv, HEADER)`; schema.sql, the migrations it was made at;
manifest.json; README.txt. The restore:
  1. checks the manifest: an INSIGHT export of a format this code reads, and every migration
     it was made at is here (an export from a newer INSIGHT is refused);
  2. creates the database if it doesn't exist, and refuses one that has a table of its own:
     a restore never replaces data;
  3. in one transaction: the export's migrations (only those), every table emptied (a
     migration may seed rows), each CSV loaded with `COPY … FROM STDIN` in the order the
     foreign keys need, with the tables' own triggers off while it loads (the rows come back
     as they were: nothing queued, nothing refilled), each count checked against the
     manifest, the sequences set;
  4. then the normal migrations (migrate.py) bring it up to this version.
A failure before the commit leaves the database empty. Logins left out of the export are
re-entered in Sources → Connections; included ones read only with the same secret key.

The catalog reads here (the tables in load order, the sequences) are the export's too.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import zipfile
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any, Dict, List

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

FORMAT = "insight-export"
FORMAT_VERSION = 1
BOOKKEEPING = "schema_migrations"      # in the manifest (migrations), not a CSV
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
CHUNK = 1 << 20


def tables_in_load_order(cur: psycopg.Cursor) -> List[str]:
    """Every table in the app's schema but the migrations' bookkeeping, each after the tables its
    foreign keys point to (a table pointing to itself loads in one COPY: checked at its end)."""
    cur.execute(
        """SELECT relname FROM pg_class
            WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r' AND relname <> %s
            ORDER BY relname""", (BOOKKEEPING,))
    graph: Dict[str, set] = {name: set() for (name,) in cur.fetchall()}
    cur.execute(
        """SELECT child.relname, parent.relname FROM pg_constraint k
             JOIN pg_class child ON child.oid = k.conrelid JOIN pg_class parent ON parent.oid = k.confrelid
            WHERE k.contype = 'f' AND k.connamespace = current_schema()::regnamespace""")
    for child, parent in cur.fetchall():
        if child in graph and parent in graph and child != parent:
            graph[child].add(parent)
    return list(TopologicalSorter(graph).static_order())


def sequences(cur: psycopg.Cursor) -> Dict[str, int]:
    """{sequence: last value} of the app's sequences that have handed out a value."""
    cur.execute("SELECT sequencename, last_value FROM pg_sequences "
                "WHERE schemaname = current_schema() AND last_value IS NOT NULL ORDER BY 1")
    return {name: int(value) for name, value in cur.fetchall()}


def read_manifest(archive: zipfile.ZipFile) -> Dict[str, Any]:
    """The export's manifest, checked against this code: ValueError says why it can't be restored."""
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except KeyError:
        raise ValueError("not an INSIGHT export: no manifest.json") from None
    if manifest.get("format") != FORMAT:
        raise ValueError("not an INSIGHT export: the manifest's format is not insight-export")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"export format {manifest.get('format_version')}: this INSIGHT reads {FORMAT_VERSION}")
    here = {path.name for path in MIGRATIONS_DIR.glob("*.sql")}
    missing = [m["version"] for m in manifest["migrations"] if m["version"] not in here]
    if missing:
        raise ValueError(f"the export was made at migrations this INSIGHT lacks ({', '.join(missing)}): "
                         f"restore it with INSIGHT {manifest.get('insight_version') or 'of the export'} or later")
    names = set(archive.namelist())
    absent = [t["file"] for t in manifest["tables"] if t["file"] not in names]
    if absent:
        raise ValueError(f"the export is incomplete: {', '.join(absent)} missing")
    return manifest


def ensure_database_exists(url: str) -> None:
    """Create the database DATABASE_URL names when it doesn't exist yet (a new database)."""
    try:
        psycopg.connect(url, connect_timeout=10).close()
        return
    except psycopg.OperationalError as exc:
        if "does not exist" not in str(exc):
            raise
    params = conninfo_to_dict(url)
    name = params.pop("dbname")
    with psycopg.connect(make_conninfo(**{**params, "dbname": "postgres"}), autocommit=True, connect_timeout=10) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def refuse_unless_empty(cur: psycopg.Cursor) -> None:
    cur.execute("SELECT count(*) FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
                "AND relkind IN ('r', 'p') AND relname <> %s", (BOOKKEEPING,))
    tables = cur.fetchone()[0]
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (BOOKKEEPING,))
    migrated = cur.fetchone()[0] and cur.execute(f"SELECT count(*) FROM {BOOKKEEPING}").fetchone()[0]
    if tables or migrated:
        raise ValueError("the database is not empty: restore into a new database (a restore never replaces data)")


def _columns(archive: zipfile.ZipFile, name: str) -> List[str]:
    with archive.open(name) as raw:
        return next(csv.reader([io.TextIOWrapper(raw, encoding="utf-8", newline="").readline()]))


def restore(archive_path: str | Path, url: str) -> Dict[str, Any]:
    """Load the export into the empty database at `url` at the export's migrations (steps 1-3);
    {table: rows} loaded. ValueError for an export or a database it won't restore."""
    from insight_core.db import migrate

    with zipfile.ZipFile(archive_path) as archive:
        manifest = read_manifest(archive)
        expected = {t["name"]: t for t in manifest["tables"]}
        ensure_database_exists(url)
        loaded: Dict[str, int] = {}
        with psycopg.connect(url, connect_timeout=10) as conn, conn.cursor() as cur:
            migrate.acquire_migration_lock(cur)
            refuse_unless_empty(cur)
            migrate.ensure_schema_migrations(cur)
            for item in sorted(manifest["migrations"], key=lambda m: m["version"]):
                cur.execute((MIGRATIONS_DIR / item["version"]).read_text(encoding="utf-8"))
                cur.execute(f"INSERT INTO {BOOKKEEPING} (version, applied_at) VALUES (%s, %s) "
                            "ON CONFLICT (version) DO UPDATE SET applied_at = EXCLUDED.applied_at",
                            (item["version"], item["applied_at"]))
            order = tables_in_load_order(cur)
            unknown = sorted(set(expected) - set(order))
            if unknown:
                raise ValueError(f"the export has tables its migrations don't make: {', '.join(unknown)}")
            if order:
                cur.execute(sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(map(sql.Identifier, order))))
            for table in order:
                cur.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(sql.Identifier(table)))
            for table in order:
                if table not in expected:
                    continue
                started = time.monotonic()
                file = expected[table]["file"]
                columns = sql.SQL(", ").join(map(sql.Identifier, _columns(archive, file)))
                with archive.open(file) as source, cur.copy(
                        sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv, HEADER)").format(sql.Identifier(table), columns)) as copy:
                    while chunk := source.read(CHUNK):
                        copy.write(chunk)
                loaded[table] = cur.rowcount
                if loaded[table] != expected[table]["rows"]:
                    raise ValueError(f"{file}: {loaded[table]} rows loaded, the manifest says {expected[table]['rows']}")
                print(f"  {table}: {loaded[table]} rows, {time.monotonic() - started:.1f} s", flush=True)
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")   # the deferred foreign keys, checked before the triggers return
            for table in order:
                cur.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER USER").format(sql.Identifier(table)))
            for sequence, value in manifest.get("sequences", {}).items():
                cur.execute("SELECT setval(%s, %s)", (sequence, value))
        return loaded


def main(argv: List[str]) -> int:
    """<zip> [--into NAME]: restore into DATABASE_URL, or into the database NAME on its server."""
    args = list(argv)
    into = None
    if "--into" in args:
        at = args.index("--into")
        into = args[at + 1] if at + 1 < len(args) else ""
        del args[at:at + 2]
    url = os.getenv("DATABASE_URL")
    if len(args) != 1 or into == "" or not url:
        print("usage: python insight_core/db/import_export.py <insight-….zip> [--into <new database>]\n"
              "  DATABASE_URL names the server, and the database unless --into", file=sys.stderr)
        return 2
    if into:
        url = make_conninfo(url, dbname=into)
        os.environ["DATABASE_URL"] = url     # migrate.main() below reads it
    try:
        loaded = restore(args[0], url)
    except ValueError as exc:
        print(f"Not restored: {exc}", file=sys.stderr)
        return 1
    print(f"Restored {len(loaded)} tables, {sum(loaded.values())} rows; migrating up to this version", flush=True)
    from insight_core.db import migrate
    migrate.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
