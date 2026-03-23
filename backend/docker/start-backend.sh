#!/usr/bin/env bash
set -euo pipefail

python insight_core/db/migrate.py
python insight_core/scripts/sync_sources_json.py json-to-db

exec uvicorn main:app --host 0.0.0.0 --port "${API_PORT:-8000}" --workers "${API_WORKERS:-2}"
