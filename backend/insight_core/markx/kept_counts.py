"""Mark X's totals, kept (issue 0195, migration 0132): the tasks by kind and status, and the calls' number, tokens and
cost. /api/markx/overview and /api/markx/status counted them over every task (~1M on the server) and every call on
each request. The triggers on mx_tasks and mx_calls log each statement's change (mx_counts_delta, append-only: no
counter row is locked by a worker); a read is the folded totals plus those deltas, so it always equals the GROUP BY.
`fold` (after each ingestion run) moves the deltas into the totals in one statement.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple

from psycopg import Cursor

_SUMS = """SELECT key, sum(n), sum(tokens_in), sum(tokens_out), sum(cost_usd)
             FROM (SELECT key, n, tokens_in, tokens_out, cost_usd FROM mx_counts WHERE key LIKE %(like)s
                   UNION ALL
                   SELECT key, n, tokens_in, tokens_out, cost_usd FROM mx_counts_delta WHERE key LIKE %(like)s) x
            GROUP BY key"""


def queue_counts(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """{kind: {status: tasks}}, ordered by kind and status, as the GROUP BY over mx_tasks answers it (a kind and status
    with no task left is not listed)."""
    cur.execute(f"""SELECT regexp_replace(key, '^task:(.*):[^:]*$', '\\1') AS kind, regexp_replace(key, '^.*:', '') AS status,
                           s.n
                      FROM ({_SUMS}) s (key, n, ti, tt, c)
                     WHERE s.n <> 0 ORDER BY kind, status""", {"like": "task:%"})
    out: Dict[str, Dict[str, int]] = {}
    for kind, status, n in cur.fetchall():
        out.setdefault(kind, {})[status] = int(n)
    return out


def call_totals(cur: Cursor) -> Tuple[int, int, int, Decimal]:
    """(calls, tokens in, tokens out, cost in USD) over every call, as count and sums over mx_calls answer them."""
    cur.execute(_SUMS, {"like": "calls"})
    row = cur.fetchone()
    if row is None:
        return 0, 0, 0, Decimal(0)
    _key, n, ti, to, cost = row
    return int(n or 0), int(ti or 0), int(to or 0), Decimal(cost or 0)


def fold(cur: Cursor) -> int:
    """The deltas into the totals, in one statement (one snapshot: the deltas it takes are the ones it adds; a delta
    committed after stays logged). Safe beside writers and another fold. The rows folded; the caller commits."""
    cur.execute("""
        WITH taken AS (DELETE FROM mx_counts_delta RETURNING key, n, tokens_in, tokens_out, cost_usd),
             summed AS (SELECT key, sum(n) AS n, sum(tokens_in) AS ti, sum(tokens_out) AS tt, sum(cost_usd) AS c,
                               count(*) AS rows
                          FROM taken GROUP BY key)
        INSERT INTO mx_counts AS m (key, n, tokens_in, tokens_out, cost_usd)
        SELECT key, n, ti, tt, c FROM summed
        ON CONFLICT (key) DO UPDATE SET n = m.n + EXCLUDED.n, tokens_in = m.tokens_in + EXCLUDED.tokens_in,
                                        tokens_out = m.tokens_out + EXCLUDED.tokens_out,
                                        cost_usd = m.cost_usd + EXCLUDED.cost_usd
        RETURNING key""")
    return len(cur.fetchall())


def check(cur: Cursor) -> Dict[str, Any]:
    """The kept totals against the GROUP BY they replace: {} when equal, else what differs (the real-data check)."""
    cur.execute("SELECT kind, status, count(*) FROM mx_tasks GROUP BY kind, status ORDER BY kind, status")
    counted: Dict[str, Dict[str, int]] = {}
    for kind, status, n in cur.fetchall():
        counted.setdefault(kind, {})[status] = n
    cur.execute("SELECT count(*), COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), COALESCE(sum(cost_usd), 0) "
                "FROM mx_calls")
    n, ti, to, cost = cur.fetchone()
    out: Dict[str, Any] = {}
    if queue_counts(cur) != counted:
        out["tasks"] = {"kept": queue_counts(cur), "counted": counted}
    if call_totals(cur) != (int(n), int(ti), int(to), Decimal(cost)):
        out["calls"] = {"kept": call_totals(cur), "counted": (int(n), int(ti), int(to), Decimal(cost))}
    return out
