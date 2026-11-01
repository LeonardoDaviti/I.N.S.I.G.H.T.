#!/usr/bin/env bash
set -euo pipefail

# One API worker, always (issue 0071). With two, each worker's start closes the other's running
# manual jobs; archives and the Telegram sign-in's pending code live in one worker's memory, so
# the next request can reach a worker that never saw them; each worker runs the start's search
# refill and story job and keeps its own host pacing and Discover cache.
if [ "${API_WORKERS:-1}" != "1" ]; then
  echo "API_WORKERS=${API_WORKERS} refused: the API runs as one worker (see docker/start-backend.sh). Remove API_WORKERS from .env." >&2
  exit 1
fi

python insight_core/db/migrate.py
# A missing or broken sources.json, or a bad entry, is logged and never stops the start (issue 0071).
python insight_core/scripts/sync_sources_json.py json-to-db --once || echo "sources.json import: see the lines above; starting anyway" >&2

# --workers 1 even when WEB_CONCURRENCY is set, which uvicorn would otherwise read.
# NOTE: do not add --limit-max-requests here. With --workers 1 uvicorn runs
# in-process with no supervisor (uvicorn/main.py: `elif config.workers > 1:
# Multiprocess(...)` / `else: server.run()`), so hitting the limit terminates
# PID 1 and restarts the whole container. The 30s healthcheck alone is ~2880
# requests/day, which would trip a 2000 limit in ~17h with nobody using the app.
exec uvicorn main:app --host 0.0.0.0 --port "${API_PORT:-8000}" --workers 1
