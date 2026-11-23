"""Each host's budget (N requests per M-minute window), learned from the limits an archive meets (0107).

The learned gap (gates) only doubles after a 429; this learns N per M. A measure is one busy stretch: the budget is
the requests through from a recovery (first success after a limit, or an archive's start) to the next limit; the
window is recovery to recovery (not 429 to success, which would undershoot). Only archives take measures; live
fetches in the same process only count; other processes' requests are unseen, so a measure can only be smaller
than the host allows. Once a window is known, later limits are measured from that window's start and the wait aims
at its refill (`refill_wait`). After LEARN_AFTER measures an archive paces to ARCHIVE_SHARE of the budget; measures
older than MEASURE_MAX_AGE are forgotten. Kept per host in system_settings (`host_budget:<host>`) by
DbHostBudgetStore, shared by the API's archive and the scheduler's continuation of it.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

LEARN_AFTER = 2                          # measured limits before an archive paces to them
ARCHIVE_SHARE = 0.8                      # of the learned budget per window an archive may use
MEASURES_KEPT = 5
MEASURE_MAX_AGE = timedelta(days=7)
PROBE_S = 5 * 60                         # a wait aimed at a refill goes this far past the latest refusal
MIN_WAIT_S = 60
TIMES_KEPT = 1000                        # a stretch's request times kept, to find a window's start

Record = Dict[str, Any]


class HostBudgetStore(Protocol):
    def load(self, host: str) -> Optional[Record]: ...

    def save(self, host: str, record: Record) -> None: ...

    def load_all(self) -> Dict[str, Record]: ...


class MemoryHostBudgetStore:
    """The store for tests and for a process without a database."""

    def __init__(self) -> None:
        self.records: Dict[str, Record] = {}

    def load(self, host: str) -> Optional[Record]:
        record = self.records.get(host)
        return dict(record) if record is not None else None

    def save(self, host: str, record: Record) -> None:
        self.records[host] = dict(record)

    def load_all(self) -> Dict[str, Record]:
        return {host: dict(record) for host, record in self.records.items()}


@dataclass(frozen=True)
class LearnedBudget:
    host: str
    requests: int        # that went through in one window
    window_s: float      # the window's length
    limits: int          # how many limits it was learned from

    def archive_gap_s(self) -> float:
        """Seconds between an archive's pages so it spends ARCHIVE_SHARE of the budget per window."""
        return self.window_s / max(1.0, ARCHIVE_SHARE * self.requests)

    def line(self) -> str:
        """"bridge.example: about 40 requests per 16 min, learned from 2 limits"."""
        minutes = max(1, round(self.window_s / 60))
        return (f"{self.host}: about {self.requests} request{'' if self.requests == 1 else 's'} per {minutes} min, "
                f"learned from {self.limits} limit{'' if self.limits == 1 else 's'}")

    def as_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "archive_gap_s": round(self.archive_gap_s(), 1), "line": self.line()}


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fresh(record: Optional[Record], now: datetime) -> List[Record]:
    return [m for m in (record or {}).get("measures") or []
            if (_parse(m.get("at")) or now) >= now - MEASURE_MAX_AGE
            and int(m.get("requests") or 0) >= 1 and float(m.get("window_s") or 0) > 0]


def _budget(host: str, record: Optional[Record], now: datetime) -> Optional[LearnedBudget]:
    """What the record's fresh measures give, or None: the fewest requests over the narrowest window when every
    refusal came before every recovery (one window, bracketed); else the slowest measure (the host changed)."""
    measures = _fresh(record, now)
    if not measures:
        return None
    fewest = min(int(m["requests"]) for m in measures)
    same = [m for m in measures if int(m["requests"]) == fewest]
    narrowest = min(float(m["window_s"]) for m in same)
    if max(float(m.get("refused_s") or 0) for m in same) < narrowest:
        return LearnedBudget(host, fewest, narrowest, len(measures))
    slowest = min(measures, key=lambda m: int(m["requests"]) / float(m["window_s"]))
    return LearnedBudget(host, int(slowest["requests"]), float(slowest["window_s"]), len(measures))


class HostBudgets:
    """Per host: the measuring stretch (persisted at each limit and recovery) and this process's count."""

    def __init__(self, store: Optional[HostBudgetStore] = None, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.store = store if store is not None else MemoryHostBudgetStore()
        self.clock = clock
        self._records: Dict[str, Record] = {}
        # [stretch, requests through since it began, their times (the last TIMES_KEPT)]: the stretch this
        # process saw begin
        self._counts: Dict[str, List[Any]] = {}
        self._archives: Dict[str, int] = {}   # archives running on the host in this process

    async def _save(self, host: str, record: Record) -> None:
        self._records[host] = record
        await asyncio.to_thread(self.store.save, host, dict(record))

    async def archive_started(self, host: str) -> None:
        """An archive begins on the host: re-read what other processes learned, and start a
        stretch unless the host is in a limit (its recovery starts it) or one is being measured."""
        record = await asyncio.to_thread(self.store.load, host) or {}
        self._records[host] = record
        self._archives[host] = self._archives.get(host, 0) + 1
        if record.get("limited_at") or host in self._counts:
            return
        stretch = uuid.uuid4().hex[:12]
        self._counts[host] = [stretch, 0, []]
        await self._save(host, {**record, "stretch": stretch, "recovered_at": _iso(self.clock()), "budget": None,
                                "window_started": None, "refused_at": None})

    def archive_stopped(self, host: str) -> None:
        self._archives[host] = max(0, self._archives.get(host, 0) - 1)
        if not self._archives[host]:
            self._counts.pop(host, None)

    def counted(self, host: str) -> None:
        """A live request to the host went through: it spends the stretch being measured, if any."""
        if host in self._counts:
            count = self._counts[host]
            count[1] += 1
            count[2] = (count[2] + [self.clock()])[-TIMES_KEPT:]

    async def succeeded(self, host: str) -> Optional[LearnedBudget]:
        """An archive's request went through. After a limit this is the recovery: it measures the
        limit and returns what is known now (whatever the number of limits); else None."""
        record = self._records.get(host) or {}
        if not record.get("limited_at"):
            self.counted(host)
            return None
        now = self.clock()
        measures = list(record.get("measures") or [])
        # from the start of the window the limit hit (the stretch's recovery unless one window was known)
        started = _parse(record.get("window_started")) or _parse(record.get("recovered_at"))
        refused, budget = _parse(record.get("refused_at")), record.get("budget")
        measured = started is not None and isinstance(budget, int) and budget >= 1
        if measured:
            measures.append({"requests": budget, "window_s": round((now - started).total_seconds(), 1),
                             **({"refused_s": round((refused - started).total_seconds(), 1)} if refused else {}),
                             "at": _iso(now)})
        stretch = uuid.uuid4().hex[:12]
        record = {**record, "stretch": stretch, "recovered_at": _iso(now), "limited_at": None, "budget": None,
                  "window_started": None, "refused_at": None, "measures": measures[-MEASURES_KEPT:]}
        self._counts[host] = [stretch, 1, [now]]
        await self._save(host, record)
        return _budget(host, record, now) if measured else None

    async def limited(self, host: str) -> None:
        """An archive's request was refused (429). The first refusal of a stretch ends it with the
        requests counted; another before a success is the same limit. The count is the stretch's
        budget only when this process saw that stretch begin (another process may have begun a
        newer one meanwhile)."""
        record = await asyncio.to_thread(self.store.load, host) or {}
        self._records[host] = record
        count = self._counts.pop(host, None)
        now = self.clock()
        if record.get("limited_at"):
            await self._save(host, {**record, "refused_at": _iso(now)})   # this limit's latest refusal
            return
        ours = count is not None and count[0] == record.get("stretch")
        budget, started = (count[1], record.get("recovered_at")) if ours else (None, None)
        known = _budget(host, record, now)
        if ours and known is not None and len(count[2]) >= known.requests:
            # the window it hit began with the request its budget's count back
            budget, started = known.requests, _iso(count[2][-known.requests])
        await self._save(host, {**record, "limited_at": _iso(now), "budget": budget, "window_started": started,
                                "refused_at": _iso(now)})

    def refill_wait(self, host: str) -> Optional[float]:
        """Seconds until the refill of the window a limit hit, once one window is measured: PROBE_S past the latest
        refusal known, at most the narrowest window measured, at least MIN_WAIT_S. None for an unmeasured host, an
        unseen window start, or a refusal past the measured window (the caller's wait ladder then)."""
        record = self._records.get(host) or {}
        now = self.clock()
        known = _budget(host, record, now)
        started, refused = _parse(record.get("window_started")), _parse(record.get("refused_at"))
        if known is None or started is None or not record.get("limited_at"):
            return None
        latest = max([float(m.get("refused_s") or 0) for m in _fresh(record, now)]
                     + [(refused - started).total_seconds() if refused else 0.0])
        if latest >= known.window_s:
            return None
        aim = started + timedelta(seconds=min(known.window_s, latest + PROBE_S))
        return max(float(MIN_WAIT_S), (aim - now).total_seconds())

    def learned(self, host: str) -> Optional[LearnedBudget]:
        """The budget an archive paces to: known once LEARN_AFTER limits are measured."""
        budget = _budget(host, self._records.get(host), self.clock())
        return budget if budget is not None and budget.limits >= LEARN_AFTER else None

    def learned_all(self) -> List[LearnedBudget]:
        """Every host's budget as known now (any number of limits), for health; reads the store."""
        now = self.clock()
        budgets = [_budget(host, record, now) for host, record in sorted(self.store.load_all().items())]
        return [budget for budget in budgets if budget is not None]
