"""An API that stops answering is restarted by itself (issue 0117, the owner's option A: in insight-ingestion).

Docker restarts nothing for being unhealthy (`restart: unless-stopped` acts only when the process exits). On 5 Nov
the API answered nothing for over 20 minutes until the owner looked.

Two halves, because insight-ingestion can't restart another container without the Docker socket, and mounting the
socket gives a container root on the host (so it isn't done):
  - **The judge, in insight-ingestion** (`Watchdog`, a thread beside the scheduler): every 30 s it asks the API's
    /api/version over the compose network, 5 s at most. After 4 failures in a row (2 minutes) it asks for a restart:
    it writes a request file in the logs volume both containers mount (INSIGHT_LOG_DIR, /app/logs), and records the
    restart as an `api_restart` job (the operations page lists it with the failures): the time, the failing check,
    the last 50 log lines. Then it waits 5 minutes before judging again. An API that isn't there (the connection
    refused, the name unknown: stopped, or starting) is no hang and counts nothing (0124).
  - **The door, in the API container** (`RestartDoor`, run by scripts/api_supervisor.py, a process of its own, so a
    hung API process can't block it): it sees the request within a second or two, saves the evidence first (SIGUSR1
    to each API process: main.py registers `faulthandler` on it, which writes every thread's stack to
    api-stacks.log even while Python is stuck), hands the dump back (a done file the judge attaches to the job), then
    stops uvicorn, and the container exits: Docker's restart policy starts it again. A request written before its
    API started, or over a minute old, is set aside and the judge's record says "Not restarted" (0124).
  - Only the API is restarted: the database, ingestion and the frontend never are.
  - **No restart loop:** at most 3 restarts an hour. After that it stops restarting, logs "the API keeps failing",
    and records it once as an `api_restart` job (the operations overview's alerts show it).
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger("api_watchdog")

REQUEST = "api-restart-request.json"
DONE = "api-restart-done.json"
STACKS = "api-stacks.log"
APP_LOG = os.path.join("core", "application.log")
JOB_TYPE = "api_restart"
URL = "http://backend:8000/api/version"

INTERVAL = 30.0          # seconds between two checks
TIMEOUT = 5.0            # an answer slower than this is a failure
FAILURES = 4             # in a row: 2 minutes
COOLDOWN = 300.0         # after a restart, no judging for 5 minutes
CAP = 3                  # restarts an hour at most
WINDOW = 3600.0
TAIL = 50                # log lines kept with a restart
MAX_DUMP = 200_000       # bytes of stack dump kept
MAX_AGE = 60.0           # a restart request older than this (2 checks) is stale: the door looks every second


def shared_dir() -> str:
    """The logs volume both containers mount (INSIGHT_LOG_DIR; the processes' own `logs` when unset)."""
    return os.getenv("INSIGHT_LOG_DIR") or "logs"


def enabled() -> bool:
    return os.getenv("INSIGHT_API_WATCHDOG", "off").strip().lower() in ("on", "1", "true", "yes")


def tail(path: str, lines: int = TAIL) -> List[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 64_000))
            return fh.read().decode("utf-8", "replace").splitlines()[-lines:]
    except OSError:
        return []


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(data, fh, default=str)
    os.replace(path + ".tmp", path)


ABSENT = "absent"        # nothing listens (refused) or the name doesn't resolve: stopped or starting, not hung


def classify(exc: BaseException) -> Any:
    """A failed check's kind (0124): ABSENT when no API is there to answer (the connection refused: nothing listens,
    as while the container starts or its migrations run; the name unknown: compose's DNS drops a stopped container),
    else False, a failure that counts (a timeout, an error answer). A hung event loop still has its listening socket:
    the kernel takes the connection and nobody answers, so a hang is a timeout, never a refusal; a full listen queue
    drops the handshake, which is a timeout too."""
    reason = getattr(exc, "reason", exc) if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (ConnectionRefusedError, socket.gaierror)):
        return ABSENT
    return False


def probe(url: str, timeout: float) -> Any:
    """True when the API answers 2xx in time; ABSENT when no API is there; False otherwise."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read(2048)
            return 200 <= r.status < 300
    except Exception as exc:  # noqa: BLE001 - any failure is a failed check
        return classify(exc)


_get = probe


class Watchdog:
    """The judge (insight-ingestion). `ops` is the OperationsService (its job rows); `check` and `clock` are seams."""

    def __init__(self, ops: Any, *, url: str = URL, directory: Optional[str] = None,
                 check: Optional[Callable[[], bool]] = None, clock: Callable[[], float] = time.time,
                 failures: int = FAILURES, cooldown: float = COOLDOWN, cap: int = CAP, window: float = WINDOW,
                 timeout: float = TIMEOUT) -> None:
        self.ops, self.url = ops, url
        self.directory = directory or shared_dir()
        self.check = check or (lambda: _get(self.url, timeout))
        self.clock = clock
        self.failures_needed, self.cooldown, self.cap, self.window = failures, cooldown, cap, window
        self.failures = 0
        self.failing_since: Optional[float] = None
        self.quiet_until = 0.0
        self.restarts: List[float] = self._recent_restarts()
        self.gave_up_at: Optional[float] = None
        self.absent = False
        self.stop = threading.Event()

    def _path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def _recent_restarts(self) -> List[float]:
        """The restarts of the last hour, from the job rows (so a restart of ingestion doesn't reset the cap)."""
        try:
            return [t for t in self.ops.recent_job_times(JOB_TYPE, self.window, kind="restart")]
        except Exception:  # noqa: BLE001
            logger.exception("API watchdog: could not read the last hour's restarts")
            return []

    def tick(self) -> str:
        """One look: ok, failing, cooling, restart, or gave_up."""
        now = self.clock()
        self.collect_dump()
        if now < self.quiet_until:
            return "cooling"
        answer = self.check()
        if answer == ABSENT:
            # 0124: no API to answer (stopped by hand, or starting: its migrations, uvicorn not listening yet) is no
            # hang, and a restart can't help it: the count starts again from the API's first timeout.
            if not self.absent:
                logger.info("API watchdog: the API is not running (stopped or starting): not a hang, no restart")
            self.absent = True
            self.failures, self.failing_since = 0, None
            return "absent"
        self.absent = False
        if answer:
            if self.failures:
                logger.info("API watchdog: the API answers again")
            self.failures, self.failing_since = 0, None   # gave_up_at stays: "keeps failing" is said once an hour
            return "ok"
        self.failures += 1
        if self.failing_since is None:
            self.failing_since = now
        if self.failures < self.failures_needed:
            logger.warning("API watchdog: %s did not answer (%d of %d)", self.url, self.failures, self.failures_needed)
            return "failing"
        failing_for = now - self.failing_since
        self.restarts = [t for t in self.restarts if now - t < self.window]
        if len(self.restarts) >= self.cap:
            if self.gave_up_at is None:
                self.gave_up_at = now
                until = min(self.restarts) + self.window
                # No clock time in the message (0124): the container's zone is UTC, the reader's isn't. The times
                # are ISO UTC in the payload ("at", "until"), and the page writes them in the reader's zone.
                message = (f"The API keeps failing: {len(self.restarts)} restarts in the last hour, so no more for "
                           f"{max(0.0, until - now) / 60:.0f} min; it has not answered for {failing_for / 60:.0f} min")
                logger.error("API watchdog: %s (until %s)", message, _iso(until))
                self._record("gave_up", message, failing_for, at=now, until=until, restarts=len(self.restarts))
            return "gave_up"
        self.gave_up_at = None   # under the cap again
        message = f"The API was restarted after {failing_for / 60:.0f} min of no answer"
        logger.error("API watchdog: %s (%s)", message, self.url)
        job_id = self._record("restart", message, failing_for, at=now)
        try:
            _write_json(self._path(REQUEST), {"at": _iso(now), "reason": f"{self.url} did not answer {self.failures} times",
                                              "failing_seconds": round(failing_for), "job_id": job_id})
        except OSError:
            logger.exception("API watchdog: could not ask the API container for a restart")
        self.restarts.append(now)
        self.failures, self.failing_since = 0, None
        self.quiet_until = now + self.cooldown
        return "restart"

    def _record(self, kind: str, message: str, failing_for: float, *, at: float, until: Optional[float] = None,
                restarts: Optional[int] = None) -> Optional[str]:
        payload: Dict[str, Any] = {"kind": kind, "check": self.url, "failing_seconds": round(failing_for), "at": _iso(at),
                                   "log_tail": tail(self._path(APP_LOG))}
        if until is not None:
            payload["until"] = _iso(until)
        if restarts is not None:
            payload["restarts"] = restarts
        try:
            job_id = self.ops.start_job(JOB_TYPE, trigger="watchdog", message=message, payload=payload)
            self.ops.finish_job(job_id, status="failed", message=message, payload=payload)
            return job_id
        except Exception:  # noqa: BLE001 - the log line above stays
            logger.exception("API watchdog: could not record the %s", kind)
            return None

    def collect_dump(self) -> Optional[Dict[str, Any]]:
        """The door's done file: the stack dump goes into the ingestion log and onto its restart's job."""
        path = self._path(DONE)
        try:
            with open(path, encoding="utf-8") as fh:
                done = json.load(fh)
            os.remove(path)
        except (OSError, ValueError):
            return None
        if done.get("stale"):   # 0124: the door found the request too old to honour; its record says so
            logger.warning("API watchdog: the API did not restart: %s", done["stale"])
            job_id = (done.get("request") or {}).get("job_id")
            if job_id:
                try:
                    self.ops.append_job_event(job_id, message=f"Not restarted: {done['stale']}", level="warning")
                except Exception:  # noqa: BLE001
                    logger.exception("API watchdog: could not note job %s", job_id)
            return done
        stacks = done.get("stacks") or ""
        logger.error("API watchdog: the stuck API's threads, before its restart:\n%s", stacks)
        job_id = (done.get("request") or {}).get("job_id")
        if job_id:
            try:
                self.ops.append_job_event(job_id, message="Stack dump before the restart", level="error",
                                          fields={"stacks": stacks[:MAX_DUMP]})
            except Exception:  # noqa: BLE001
                logger.exception("API watchdog: could not attach the stack dump to job %s", job_id)
        return done

    def start(self, interval: float = INTERVAL) -> threading.Thread:
        def loop() -> None:   # every `interval` seconds, however long a check took (a failed one takes TIMEOUT)
            spent = 0.0
            while not self.stop.wait(max(0.0, interval - spent)):
                began = time.monotonic()
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - never stops ingestion
                    logger.exception("API watchdog: the check failed")
                spent = time.monotonic() - began
        thread = threading.Thread(target=loop, name="api-watchdog", daemon=True)
        thread.start()
        logger.info("API watchdog: checking %s every %.0f s", self.url, interval)
        return thread


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


# ---- the door, in the API container ------------------------------------------------------------------------

def children(pid: int, proc: str = "/proc", match: Optional[str] = None) -> List[int]:
    """The processes whose parent is `pid`, from /proc; with `match`, only those whose command line holds it."""
    out = []
    try:
        names = os.listdir(proc)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(proc, name, "stat"), encoding="utf-8") as fh:
                stat = fh.read()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid != pid:
            continue
        if match is not None:
            try:
                with open(os.path.join(proc, name, "cmdline"), "rb") as fh:
                    if match.encode() not in fh.read():
                        continue
            except OSError:
                continue
        out.append(int(name))
    return sorted(out)


def api_processes(uvicorn_pid: int) -> List[int]:
    """uvicorn's API processes (spawned: `spawn_main` in their command line; never its resource tracker, which a
    SIGUSR1 would end); uvicorn itself when it runs one process in its own."""
    return children(uvicorn_pid, match="spawn_main") or [uvicorn_pid]


class RestartDoor:
    """Run by the API supervisor every second or two: a restart request from the judge is honoured once. `kill` and
    `processes` are the tests' seams."""

    def __init__(self, directory: Optional[str] = None, *, processes: Callable[[], Iterable[int]] = lambda: [],
                 kill: Callable[[int, int], None] = os.kill, settle: float = 2.0, since: Optional[float] = None,
                 clock: Callable[[], float] = time.time, max_age: float = MAX_AGE) -> None:
        self.directory = directory or shared_dir()
        self.processes, self.kill, self.settle = processes, kill, settle
        self.since, self.clock, self.max_age = since, clock, max_age

    def _path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def stale(self, request: Dict[str, Any], written: float) -> Optional[str]:
        """Why a request is too old to honour, or None (0124): written before this API started (asked of an API that
        is gone: stopped, or replaced by a deploy), or more than `max_age` ago (the door looks every second, so a
        request it didn't see then had no door: no API was running)."""
        try:
            at = datetime.fromisoformat(str(request["at"])).timestamp()
        except (KeyError, ValueError, TypeError):
            at = written
        if self.since is not None and at < self.since:
            return f"the request was written {self.since - at:.0f} s before this API started"
        age = self.clock() - at
        if age > self.max_age:
            return f"the request is {age:.0f} s old (more than {self.max_age:.0f} s)"
        return None

    def requested(self) -> Optional[Dict[str, Any]]:
        """The request, taken (renamed, so it is honoured once), or None. A stale one is set aside (renamed .stale)
        and the judge told (the done file, `stale`), never honoured."""
        path = self._path(REQUEST)
        try:
            with open(path, encoding="utf-8") as fh:
                request = json.load(fh)
            written = os.path.getmtime(path)
        except (OSError, ValueError):
            return None
        why = self.stale(request, written)
        try:
            os.replace(path, path + (".stale" if why else ".taken"))
        except OSError:
            return None
        if why:
            logger.warning("API restart asked by the watchdog ignored: %s (before this API started, or no API ran "
                           "to see it)", why)
            try:
                _write_json(self._path(DONE), {"request": request, "stale": why,
                                               "at": datetime.now(timezone.utc).isoformat()})
            except OSError:
                logger.exception("Could not tell the watchdog the request was stale")
            return None
        return request

    def dump(self) -> str:
        """Every API process's threads (SIGUSR1: faulthandler in main.py writes them to api-stacks.log)."""
        path = self._path(STACKS)
        try:
            start = os.path.getsize(path)
        except OSError:
            start = 0
        for pid in self.processes():
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(f"\n=== API process {pid}, {datetime.now(timezone.utc).isoformat()} ===\n")
                self.kill(pid, signal.SIGUSR1)
            except OSError:
                logger.exception("Could not ask API process %s for its stacks", pid)
            time.sleep(self.settle / 4)
        time.sleep(self.settle)
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                return fh.read(MAX_DUMP).decode("utf-8", "replace")
        except OSError:
            return ""

    def honour(self) -> Optional[Dict[str, Any]]:
        """When asked: the dump, saved for the judge (the done file). The caller then stops uvicorn."""
        request = self.requested()
        if request is None:
            return None
        logger.error("API restart asked by the watchdog: %s; saving the stacks first", request.get("reason"))
        stacks = self.dump()
        try:
            _write_json(self._path(DONE), {"request": request, "stacks": stacks,
                                           "at": datetime.now(timezone.utc).isoformat()})
        except OSError:
            logger.exception("Could not save the stack dump for the watchdog")
        return request
