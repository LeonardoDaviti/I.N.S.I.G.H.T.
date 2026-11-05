#!/usr/bin/env bash
set -euo pipefail

# Two API processes (issue 0112 Decided 11): one stuck request, or one process hung on its CPU, can't freeze the
# reader. uvicorn's supervisor pings each process and replaces one that stops answering. What assumed one process
# is shared now: a Telegram sign-in's waiting code (the database), an export's progress (a file per token), a
# Mark X worker's last contact (mx_workers), an archive's start (one lock). The work done once per container start
# (closing the jobs a restart ended, the search refill, the start's story job) is the supervisor's
# (insight_core/scripts/api_supervisor.py), never each process's. Mark X's jobs run in insight-ingestion.
WORKERS="${API_WORKERS:-2}"
case "$WORKERS" in
  ''|*[!0-9]*|0) echo "API_WORKERS=${WORKERS} refused: a number of API processes, 1 or more." >&2; exit 1;;
esac

python insight_core/db/migrate.py
# A missing or broken sources.json, or a bad entry, is logged and never stops the start (issue 0071).
python insight_core/scripts/sync_sources_json.py json-to-db --once || echo "sources.json import: see the lines above; starting anyway" >&2

# --workers given, so WEB_CONCURRENCY (which uvicorn would otherwise read) never decides it.
# NOTE: do not add --limit-max-requests here: the 30 s healthcheck alone is ~2880 requests a day, and each
# process would be replaced every few hours with nobody using the app.
exec python -m insight_core.scripts.api_supervisor \
  uvicorn main:app --host 0.0.0.0 --port "${API_PORT:-8000}" --workers "$WORKERS"
