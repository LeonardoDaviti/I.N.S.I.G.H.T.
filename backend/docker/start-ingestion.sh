#!/usr/bin/env bash
set -euo pipefail

python insight_core/db/migrate.py
python insight_core/scripts/sync_sources_json.py json-to-db

exec python insight_core/scripts/run_scheduler.py
