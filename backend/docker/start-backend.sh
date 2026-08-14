#!/usr/bin/env bash
set -euo pipefail

python insight_core/db/migrate.py
python insight_core/scripts/sync_sources_json.py json-to-db

# NOTE: do not add --limit-max-requests here. With --workers 1 uvicorn runs
# in-process with no supervisor (uvicorn/main.py: `elif config.workers > 1:
# Multiprocess(...)` / `else: server.run()`), so hitting the limit terminates
# PID 1 and restarts the whole container. The 30s healthcheck alone is ~2880
# requests/day, which would trip a 2000 limit in ~17h with nobody using the app.
exec uvicorn main:app --host 0.0.0.0 --port "${API_PORT:-8000}" \
  --workers "${API_WORKERS:-1}"
