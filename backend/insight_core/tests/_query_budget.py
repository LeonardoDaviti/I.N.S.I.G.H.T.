"""Statement counting for the query-count guards (0279): how many statements a block sends through psycopg.

`statements()` counts every Cursor.execute / executemany in the block (any connection of this process), by the
calling module and function (`markx/repo.py:add_task`), so a guard can say which code grew. A guard builds the same world at two sizes and asserts
the count does not grow with the world (an N+1 is a count that grows with N).
"""
from __future__ import annotations

import sys
from collections import Counter
from contextlib import contextmanager
from typing import Iterator

import psycopg


class Count:
    def __init__(self) -> None:
        self.total = 0
        self.by_line: Counter = Counter()

    def __repr__(self) -> str:
        return f"Count({self.total}, top={self.by_line.most_common(5)})"


def _caller() -> str:
    f = sys._getframe(2)
    while f is not None and ("psycopg" in f.f_code.co_filename or f.f_code.co_filename.endswith("_query_budget.py")):
        f = f.f_back
    if f is None:
        return "?"
    name = f.f_code.co_filename
    cut = name.rfind("insight_core/")
    return f"{name[cut + len('insight_core/'):] if cut >= 0 else name}:{f.f_code.co_name}"


@contextmanager
def statements() -> Iterator[Count]:
    """Counts the statements sent in the block (`Count.total`, `Count.by_line`)."""
    count = Count()
    execute, executemany = psycopg.Cursor.execute, psycopg.Cursor.executemany

    def counted_execute(self, query, params=None, **kw):
        count.total += 1
        count.by_line[_caller()] += 1
        return execute(self, query, params, **kw)

    def counted_executemany(self, query, params_seq, **kw):
        count.total += 1
        count.by_line[_caller()] += 1
        return executemany(self, query, params_seq, **kw)

    psycopg.Cursor.execute, psycopg.Cursor.executemany = counted_execute, counted_executemany
    try:
        yield count
    finally:
        psycopg.Cursor.execute, psycopg.Cursor.executemany = execute, executemany


def grown(small: Count, big: Count, slack: int = 0) -> Counter:
    """The callers whose count grew from the small world to the big one by more than `slack` (an N+1's code)."""
    return Counter({k: big.by_line[k] - small.by_line.get(k, 0) for k in big.by_line
                    if big.by_line[k] - small.by_line.get(k, 0) > slack})
