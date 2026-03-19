"""
Minimal psycopg compatibility shim backed by the local `psql` CLI.

This environment does not ship the real `psycopg` package, but it does have
the PostgreSQL client binary and a working local server. The application only
uses a narrow slice of the psycopg API, so this shim provides that subset.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, List, Optional, Sequence


class Cursor:
    def __init__(self, connection: "Connection"):
        self.connection = connection
        self._rows: List[tuple] = []
        self._index = 0

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params: Optional[Sequence[Any]] = None) -> None:
        sql_text = _substitute_params(query, params)
        returns_rows = _query_returns_rows(sql_text)

        if returns_rows:
            wrapped_sql = f"WITH __codex_q AS ({_strip_trailing_semicolon(sql_text)}) SELECT row_to_json(__codex_q)::text FROM __codex_q;"
            output = _run_psql(self.connection.dsn, wrapped_sql, expect_output=True)
            self._rows = [_json_row_to_tuple(line) for line in output.splitlines() if line.strip()]
        else:
            _run_psql(self.connection.dsn, sql_text, expect_output=False)
            self._rows = []

        self._index = 0

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        rows = self._rows[self._index:]
        self._index = len(self._rows)
        return rows


class Connection:
    def __init__(self, dsn: str, autocommit: bool = False):
        self.dsn = dsn
        self.autocommit = autocommit

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> Cursor:
        return Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def connect(dsn: str, autocommit: bool = False) -> Connection:
    return Connection(dsn, autocommit=autocommit)


def _run_psql(dsn: str, sql_text: str, expect_output: bool) -> str:
    command = [
        "psql",
        dsn,
        "-X",
        "-q",
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
    ]

    if expect_output:
        command.extend(["-A", "-t"])

    # Large SQL payloads can exceed the OS argv limit when they are passed
    # through `-c`. Spill them to a temporary file so local development remains
    # stable even for large cached briefing payloads.
    if len(sql_text) > 12000:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".sql") as handle:
            handle.write(sql_text)
            handle.flush()
            result = subprocess.run(
                [*command, "-f", handle.name],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout

    result = subprocess.run(
        [*command, "-c", sql_text],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _strip_trailing_semicolon(sql_text: str) -> str:
    return sql_text.strip().rstrip(";")


def _query_returns_rows(sql_text: str) -> bool:
    normalized = _strip_trailing_semicolon(sql_text).lstrip().lower()
    if normalized.startswith("select") or normalized.startswith("with"):
        return True
    if normalized.startswith(("insert", "update", "delete")) and "returning" in normalized:
        return True
    return False


def _substitute_params(query: str, params: Optional[Sequence[Any]]) -> str:
    if not params:
        return query

    parts = query.split("%s")
    if len(parts) - 1 != len(params):
        raise ValueError("Parameter count does not match %s placeholders")

    sql_chunks = [parts[0]]
    for value, tail in zip(params, parts[1:]):
        sql_chunks.append(_quote(value))
        sql_chunks.append(tail)

    return "".join(sql_chunks)


def _quote(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return "'" + value.isoformat().replace("'", "''") + "'"
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value).replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _json_row_to_tuple(line: str) -> tuple:
    payload = json.loads(line)
    return tuple(_coerce_value(value) for value in payload.values())


def _coerce_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_coerce_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _coerce_value(item) for key, item in value.items()}
    if isinstance(value, str):
        for parser in (_parse_datetime, _parse_date):
            parsed = parser(value)
            if parsed is not None:
                return parsed
    return value


def _parse_datetime(value: str) -> Optional[datetime]:
    if "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: str) -> Optional[date]:
    if len(value) != 10 or value.count("-") != 2:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class _SQL:
    value: str

    def format(self, *parts: Any) -> "_SQL":
        return _SQL(self.value.format(*[str(part) for part in parts]))

    def __str__(self) -> str:
        return self.value


@dataclass
class _Identifier:
    value: str

    def __str__(self) -> str:
        escaped = self.value.replace('"', '""')
        return f'"{escaped}"'


@dataclass
class _Literal:
    value: Any

    def __str__(self) -> str:
        return _quote(self.value)


class _SQLNamespace:
    SQL = _SQL
    Identifier = _Identifier
    Literal = _Literal


sql = _SQLNamespace()
