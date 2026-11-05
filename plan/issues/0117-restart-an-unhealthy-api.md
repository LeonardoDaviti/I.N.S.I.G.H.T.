# 0117 — An API that stops answering is restarted by itself

Status: **built** on branch `issue-0112-jobs-out-of-api` (2026-11-05), option A (the default). Not merged, not deployed. Deployment (`docker-compose.yml`, DEPLOYMENT.md, the API container's supervisor); no change to the reader's features.

**The owner (2026-11-05):** "Docker restarts nothing on unhealthy by itself: add an autoheal, or a watchdog that restarts the API if /api/version fails for 2 minutes."

**Constraints:**
- download nothing on the development machine; the server's images are built as `./update` builds them, and a third-party autoheal image is pulled only if the owner chooses it;
- no restart loops;
- every restart is logged and visible;
- the database, ingestion and the frontend are never restarted by it;
- keep everything.

## Why (live, 5 Nov 22:43 local time)
- `insight-api` stopped answering for over 20 minutes: one thread at 101% CPU (0112, wrong today 5).
- Docker marked it **unhealthy**, and that's all. Compose doesn't restart a container for being unhealthy; `restart: unless-stopped` acts only when the process exits.
- The reader was down until the owner looked.
- **The container's health check also passes when it shouldn't:** `/health` runs one quick database query through the pool, but it answered while every `/api/*` request hung.

## What it does
1. **A health check that tests what the reader needs:** `/api/version` must answer within 5 s. Docker's `healthcheck` checks it every 30 s; 4 failures in a row (2 minutes) mean unhealthy. `/health` stays as the database check.
2. **A watchdog restarts an unhealthy API.** One of these, the owner's pick (default A):
   - **A. In the ingestion container** (no new image): a small loop, beside the scheduler, calls the API's `/api/version` over the compose network every 30 s.
     - After 2 minutes of failures it restarts the API through the Docker socket (mounted read-only to that container) or a compose-level restart command.
     - Then it waits 5 minutes before judging again.
   - **B. An autoheal container:** a small, widely used open-source image that restarts containers labelled `autoheal=true` when unhealthy. It needs the Docker socket and one image pulled on the server.
   - **C. On the host:** a systemd timer that runs `curl` and `docker compose restart backend`. Nothing in compose changes, but it's set up once outside the repo.
3. **No restart loop:**
   - at most 3 restarts an hour;
   - after that it stops restarting, and shows "the API keeps failing" in the operations overview (the frontend already polls it) and in the logs.
4. **Every restart is recorded:** time, the failing check and the last 50 log lines before it. Kept in the ingestion logs and, for option A, in a small table the operations page lists. "The API was restarted at 22:45 after 2 min of no answer."
5. **Before restarting, it saves the evidence:** a Python stack dump of the stuck process (`faulthandler` on a signal the API registers at start) goes into the log, so the next hang names its function. On 5 Nov that needed a database dump and a profile.

## Measure before building
- On a local copy, make the API spin, for example with a test endpoint behind a debug flag that busy-loops a thread for 5 minutes:
  - the watchdog restarts it within 2–3 minutes;
  - the stack dump names the loop;
  - the reader answers again;
  - nothing else restarts.
- The restart cap: a spin that returns after each restart stops after 3 restarts, and the overview shows it.
- 7 days on the server: no restart when nothing is wrong, and the check's own cost is under 0.1% CPU.

## Open, for the owner
- **Watchdog A, B or C?** Default A: no new image, and it already runs beside the scheduler.

## Built (option A, branch `issue-0112-jobs-out-of-api`, 2026-11-05)

**How ingestion restarts the API without the Docker socket:**
- Ingestion can't restart another container without the socket, and the socket gives a container root on the host. So the socket is not mounted, and the work is split in two:
  - **The judge, in insight-ingestion** (`services/api_watchdog.py`, a thread beside the scheduler; `INSIGHT_API_WATCHDOG=on` in compose).
    - It asks `http://backend:8000/api/version` every 30 s, with 5 s at most for an answer.
    - After 4 failures in a row it writes a request file in the logs volume both containers already mount (`/app/logs/api-restart-request.json`).
    - It records the restart as an `api_restart` job: the message, the check, the seconds failing, the last 50 lines of `core/application.log`.
    - Then it judges nothing for 5 minutes.
  - **The door, in the API container** (`scripts/api_supervisor.py`: tini's child, uvicorn's parent).
    - It is a process of its own, so a hung API process can't block it.
    - It sees the request within a second and takes it once (renamed).
    - It sends SIGUSR1 to each API process (uvicorn's spawned processes, never its resource tracker). `main.py` registers `faulthandler` on it, which writes every thread's stack to `api-stacks.log`.
    - It hands the dump back to the judge in a done file. The judge prints it in the ingestion log and attaches it to the job.
    - Then it stops uvicorn (killed after 15 s) and exits 75. Docker's `restart: unless-stopped` starts the container again.
  - Only the API container restarts.
- **Option C stays possible** (a host systemd timer and service). The exact units are in DEPLOYMENT.md; set `INSIGHT_API_WATCHDOG=off` if you use them. `docker kill -s USR1 insight-api` reaches the supervisor, which passes it on, so the dump works there too.

**The health check** asks `/api/version` (`curl -fsS -m 5`) every 30 s; 4 failures make it unhealthy. `/health` stays the database check.

**No restart loop:**
- At most 3 restarts an hour, counted from the `api_restart` job rows, so restarting ingestion doesn't reset the cap.
- After that it records "The API keeps failing: 3 restarts in the last hour, so no more until HH:MM" once while the cap holds, and logs it.
- The overview's alerts list it with every restart, since they are failed jobs.

**Measured on a scratch copy** (the head code; both API processes made to spin with `POST /api/debug/spin`, behind `INSIGHT_DEBUG_SPIN=on`; a watchdog container at the default timings; one shared logs volume):
- The hang began 23:48:12. The watchdog failed its checks from 23:48:37 on and asked for the restart on the 4th failure. The container restarted at 23:50:48, **2 min 36 s** after the hang (the check timing then made the gap 35 s, not 30 s; it is fixed-rate now).
- **The dump named the loop** in both API processes: `File "/app/main.py", line 1404 in debug_spin`, under "Current thread", 12,552 bytes on the job.
- The reader answered again **2.1 s** after the restart.
- Nothing else restarted: the watchdog container and the database weren't touched, and the API's restart count was 1.
- **The cap**, at short test timings (checks every 3 s, 2 failures, 10 s of quiet):
  - The copy already held one restart from the run above, and two more followed. Then it gave up: "The API keeps failing: 3 restarts in the last hour".
  - That run found two things, both fixed and tested:
    - The give-up was recorded twice when the API answered once between two hangs.
    - With quiet shorter than the API's start (about 15 s), a second restart can come during the start. At the default 5 minutes it can't.
- **Not measured:** 7 days on the server (no restart when nothing is wrong; the check's cost under 0.1% CPU).

**Tests:** `test_api_watchdog`, which covers:
- the 2 minutes;
- an answer resetting the count;
- the cap and its record once;
- the cap surviving a restart of ingestion;
- the dump attached;
- the door honouring a request once, with the stacks first;
- only API processes signalled;
- the supervisor's exit for a restart;
- a real SIGUSR1 naming a busy loop's function;
- the spin route off by default.

Plus `test_api_supervisor`.
