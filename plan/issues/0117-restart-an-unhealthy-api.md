# 0117 — An API that stops answering is restarted by itself

Status: **spec** (2026-11-05, the owner). Not built. Deployment (`docker-compose.yml`, DEPLOYMENT.md); no change to the reader's features.

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
