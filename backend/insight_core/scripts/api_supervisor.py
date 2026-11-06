#!/usr/bin/env python3
"""The API container's first process under tini (docker/start-backend.sh): runs uvicorn's processes and the work that
must happen once per container start, not once per API process (issue 0112 Decided 11).

    python -m insight_core.scripts.api_supervisor uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2

- **Before uvicorn serves:** the API's jobs a restart ended are marked interrupted (issue 0070). Done here, once: in
  each API process's start it would also close the other process's running jobs whenever uvicorn replaces a hung one.
- **Then uvicorn**, as a child, with INSIGHT_API_SUPERVISED=1 so main.py's lifespan leaves the start work to this.
- **The start work, once, in a child process of its own:** the search refill and the start's story job (then Mark
  X's first decision run is asked for), as main.py's lifespan ran them in one process.
- SIGTERM and SIGINT go to uvicorn; this exits with uvicorn's exit code.
- **The watchdog's door (issue 0117):** every second it looks for a restart request from the watchdog in
  insight-ingestion (services/api_watchdog.py). Asked, it saves every API process's thread stacks, stops uvicorn and
  exits with RESTART_EXIT, so Docker's restart policy starts the container again. Being a process of its own, a hung
  API process can't block it. A request written before this process started, or over a minute old, is set aside,
  never honoured (0124: one left from a stop or a deploy killed the fresh API 4 s into its start).
- **Open files (0124):** it raises its soft open-files limit (65,536, as compose sets) before uvicorn starts, so
  every API process inherits it; and every 5 s it counts each API process's open files: one held at 90% of its limit
  at 3 looks in a row is ended (SIGKILL), and uvicorn starts another in its place.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

logger = logging.getLogger("api_supervisor")

SUPERVISED = "INSIGHT_API_SUPERVISED"
RESTART_EXIT = 75          # asked to restart by the watchdog (EX_TEMPFAIL): Docker starts the container again
STOP_GRACE = 15.0          # seconds uvicorn gets to stop before it is killed


OPEN_FILES = 65536         # the soft open-files limit asked for (compose sets the same, issue 0124)
GUARD_SHARE = 0.9          # an API process holding this share of its limit ...
GUARD_LOOKS = 3            # ... at this many looks in a row (GUARD_EVERY apart) is ended: uvicorn starts another
GUARD_EVERY = 5.0


def raise_open_files(get: Optional[Callable[[], tuple]] = None, set_: Optional[Callable[[int, int], None]] = None,
                     want: int = OPEN_FILES) -> int:
    """The soft open-files limit raised to `want` (never past the hard one), inherited by uvicorn's processes: the
    container's default soft limit is 1,024, and after a long hang one process accepted the queued connections past
    it (0124, the v10.0.2 review's W4). Returns the soft limit now. Never raises."""
    import resource
    get = get or (lambda: resource.getrlimit(resource.RLIMIT_NOFILE))
    set_ = set_ or (lambda soft, hard: resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard)))
    try:
        soft, hard = get()
        target = want if hard == resource.RLIM_INFINITY else min(want, hard)
        if soft >= target:
            return soft
        set_(target, hard)
        return target
    except (OSError, ValueError):
        logger.exception("Could not raise the open-files limit")
        return -1


def open_files(pid: int, proc: str = "/proc") -> Optional[int]:
    """How many files (sockets included) a process holds, or None when it is gone."""
    try:
        return len(os.listdir(os.path.join(proc, str(pid), "fd")))
    except OSError:
        return None


def open_files_limit(pid: int, proc: str = "/proc") -> Optional[int]:
    """A process's soft open-files limit, or None."""
    try:
        with open(os.path.join(proc, str(pid), "limits"), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("Max open files"):
                    value = line.split()[3]
                    return None if value == "unlimited" else int(value)
    except (OSError, ValueError, IndexError):
        return None
    return None


class OpenFilesGuard:
    """A process left at its open-files limit is ended (0124). At its limit it can't accept a connection (each
    accept fails: "Too many open files") nor open a database connection, so it answers a share of requests late or
    never, and nothing ends that state by itself: the review saw it 7 minutes on. uvicorn starts a new process when
    one exits (its supervisor checks each 0.5 s), so ending it is the recovery; with one process, `end` restarts the
    container. A burst that drains between two looks is left alone. `processes`, `count`, `limit`, `end` are seams."""

    def __init__(self, *, processes: Callable[[], List[int]], end: Callable[[int], None],
                 count: Callable[[int], Optional[int]] = open_files, limit: Callable[[int], Optional[int]] = open_files_limit,
                 share: float = GUARD_SHARE, looks: int = GUARD_LOOKS) -> None:
        self.processes, self.end, self.count, self.limit = processes, end, count, limit
        self.share, self.looks = share, looks
        self.full: dict = {}

    def tick(self) -> List[int]:
        ended = []
        seen = set()
        for pid in self.processes():
            seen.add(pid)
            n, cap = self.count(pid), self.limit(pid)
            if n is None or not cap or n < self.share * cap:
                self.full.pop(pid, None)
                continue
            self.full[pid] = self.full.get(pid, 0) + 1
            if self.full[pid] >= self.looks:
                logger.error("API process %s held %s of %s open files at %s looks in a row: ended, so uvicorn starts "
                             "another (it can't accept connections or reach the database at its limit)",
                             pid, n, cap, self.full[pid])
                self.full.pop(pid, None)
                try:
                    self.end(pid)
                    ended.append(pid)
                except OSError:
                    logger.exception("Could not end API process %s", pid)
        for pid in set(self.full) - seen:
            self.full.pop(pid, None)
        return ended


def close_interrupted_jobs() -> int:
    """The API's jobs a restart ended (issue 0070), before any API process serves: no request has started one yet."""
    from insight_core.services.registry import services
    try:
        closed = services().operations.close_interrupted_jobs("manual")
        if closed:
            logger.info("Jobs: %s left running by a restart marked interrupted", closed)
        return closed
    except Exception:  # noqa: BLE001 - the API starts anyway
        logger.exception("Jobs: could not close the jobs a restart interrupted")
        return 0


def start_work() -> None:
    """The start's background work, once per container (a child process; main.py's functions, as its lifespan ran
    them): the search refill and the story job side by side, then Mark X's first decision run is asked for."""
    logging.basicConfig(level=logging.INFO)
    import main
    threads = [threading.Thread(target=main.fill_search_vectors, name="search-fill"),
               threading.Thread(target=main.start_stories, name="stories")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


class Supervisor:
    """uvicorn as a child, the start work beside it. `spawn_work` and `popen` are the tests' seams."""

    def __init__(self, command: Sequence[str], *, popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 spawn_work: Optional[Callable[[], object]] = None, close_jobs: Callable[[], int] = close_interrupted_jobs) -> None:
        self.command = list(command)
        self.popen = popen
        self.spawn_work = spawn_work or self._spawn_work
        self.close_jobs = close_jobs
        self.child: Optional[subprocess.Popen] = None
        self.work: Optional[object] = None
        self.stopping = False
        self.restart_asked = False

    @staticmethod
    def _spawn_work():
        from insight_core.scripts.api_supervisor import start_work as target   # by its name, also when run as -m
        process = multiprocessing.get_context("spawn").Process(target=target, name="api-start-work")
        process.start()
        return process

    def start(self) -> subprocess.Popen:
        self.close_jobs()
        env = {**os.environ, SUPERVISED: "1"}
        self.child = self.popen(self.command, env=env)
        try:
            self.work = self.spawn_work()
        except Exception:  # noqa: BLE001 - the API serves without it; the next start runs it
            logger.exception("Could not start the API's start work")
        return self.child

    def dump_stacks(self, processes: Callable[[], List[int]], kill: Callable[[int, int], None] = os.kill) -> List[int]:
        """SIGUSR1 to each API process (`docker kill -s USR1 insight-api` reaches this one only): each writes its
        threads' stacks to api-stacks.log (main.py's faulthandler). Never raises."""
        sent = []
        for pid in processes():
            try:
                kill(pid, signal.SIGUSR1)
                sent.append(pid)
            except OSError:
                logger.exception("Could not ask API process %s for its stacks", pid)
        return sent

    def forward(self, signum: int, _frame=None) -> None:
        self.stopping = True
        if self.child is not None and self.child.poll() is None:
            self.child.send_signal(signum)

    def stop_for_restart(self, grace: float = STOP_GRACE) -> None:
        """The watchdog asked: uvicorn stops (killed after `grace` seconds), and this exits with RESTART_EXIT."""
        self.restart_asked = True
        child = self.child
        if child is None or child.poll() is not None:
            return
        child.send_signal(signal.SIGTERM)

        def kill_later() -> None:
            time.sleep(grace)
            if child.poll() is None:
                logger.error("uvicorn did not stop in %.0f s: killed", grace)
                child.kill()
        threading.Thread(target=kill_later, daemon=True).start()

    def wait(self, poll: float = 1.0, on_tick: Optional[Callable[[], None]] = None) -> int:
        """Until uvicorn exits: its exit code. `on_tick` runs every `poll` seconds meanwhile."""
        assert self.child is not None
        while True:
            code = self.child.poll()
            if code is not None:
                break
            if on_tick is not None:
                try:
                    on_tick()
                except Exception:  # noqa: BLE001 - never stops the API
                    logger.exception("The supervisor's tick failed")
            time.sleep(poll)
        work = self.work
        if work is not None and getattr(work, "is_alive", lambda: False)():
            work.terminate()   # type: ignore[attr-defined]
        return RESTART_EXIT if self.restart_asked else code


def main(argv: Optional[List[str]] = None) -> int:
    started = time.time()   # a restart request written before this is never honoured (0124: stopped, or a deploy)
    from insight_core.logs.core.logger_config import setup_logging
    setup_logging(debug_mode=False)
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        print("usage: api_supervisor <uvicorn command…>", file=sys.stderr)
        return 2
    limit = raise_open_files()
    logger.info("API processes: open files up to %s each", limit)
    supervisor = Supervisor(command)
    signal.signal(signal.SIGTERM, supervisor.forward)
    signal.signal(signal.SIGINT, supervisor.forward)
    child = supervisor.start()
    from insight_core.services.api_watchdog import RestartDoor, api_processes
    door = RestartDoor(processes=lambda: api_processes(child.pid), since=started)
    signal.signal(signal.SIGUSR1, lambda signum, frame: supervisor.dump_stacks(lambda: api_processes(child.pid)))

    def end(pid: int) -> None:
        if pid == child.pid:   # one process, uvicorn's own: the container restarts
            supervisor.stop_for_restart()
        else:                  # one of uvicorn's processes: uvicorn starts another
            os.kill(pid, signal.SIGKILL)
    guard = OpenFilesGuard(processes=lambda: api_processes(child.pid), end=end)
    next_guard = [time.monotonic() + GUARD_EVERY]

    def tick() -> None:
        if not supervisor.restart_asked and door.honour() is not None:
            logger.error("Restarting the API container, as the watchdog asked")
            supervisor.stop_for_restart()
        if not supervisor.restart_asked and time.monotonic() >= next_guard[0]:
            next_guard[0] = time.monotonic() + GUARD_EVERY
            guard.tick()
    return supervisor.wait(on_tick=tick)


if __name__ == "__main__":
    sys.exit(main())
