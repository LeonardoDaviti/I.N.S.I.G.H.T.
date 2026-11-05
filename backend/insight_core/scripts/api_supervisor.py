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

    def forward(self, signum: int, _frame=None) -> None:
        self.stopping = True
        if self.child is not None and self.child.poll() is None:
            self.child.send_signal(signum)

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
        return code


def main(argv: Optional[List[str]] = None) -> int:
    from insight_core.logs.core.logger_config import setup_logging
    setup_logging(debug_mode=False)
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        print("usage: api_supervisor <uvicorn command…>", file=sys.stderr)
        return 2
    supervisor = Supervisor(command)
    signal.signal(signal.SIGTERM, supervisor.forward)
    signal.signal(signal.SIGINT, supervisor.forward)
    supervisor.start()
    return supervisor.wait()


if __name__ == "__main__":
    sys.exit(main())
