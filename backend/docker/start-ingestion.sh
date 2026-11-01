#!/usr/bin/env bash
set -euo pipefail

python insight_core/db/migrate.py
# A missing or broken sources.json, or a bad entry, is logged and never stops the start (issue 0071).
python insight_core/scripts/sync_sources_json.py json-to-db --once || echo "sources.json import: see the lines above; starting anyway" >&2

exec python insight_core/scripts/run_scheduler.py
