#!/usr/bin/env bash
# Run the backend test suite the only way it is meaningful: inside the image.
#
# The image holds the real packages from requirements.txt and reaches the database on the
# compose network. The host has neither, so host results are not a signal.
#
# Usage:
#   ./run-tests.sh                                   # whole suite
#   ./run-tests.sh insight_core.tests.test_ingestion_runner   # one module
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "error: .env not found next to run-tests.sh" >&2
  exit 1
fi

# Build every run. The image bakes the source in (no volume is mounted), so a stale image
# silently tests code that is no longer on disk - a green run that proves nothing.
# Layer caching makes a no-change rebuild cost about a second. SKIP_BUILD=1 opts out.
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "==> building insight-backend:latest"
  docker compose build backend
fi

# Several suites connect to DATABASE_URL and INSERT rows, so the default is the scratch
# `insight_test` database, never the live `insight` one. Override with TEST_DATABASE_URL.
DB_URL="${TEST_DATABASE_URL:-postgresql://insight:insight@postgres:5432/insight_test}"

if [ "$#" -eq 0 ]; then
  set -- discover -s insight_core/tests -p 'test_*.py'
fi

# MIGRATE=1 applies pending migrations to $DB_URL first, in the same image, so a slice that
# adds a migration never runs its tests against an unmigrated schema.
if [ "${MIGRATE:-0}" = "1" ]; then
  echo "==> migrating ${DB_URL##*/}"
  docker run --rm \
    --network insight_insight-network \
    --env-file .env \
    -e DATABASE_URL="$DB_URL" \
    -w /app insight-backend:latest \
    python -m insight_core.db.migrate
fi

exec docker run --rm \
  --network insight_insight-network \
  --env-file .env \
  -e DATABASE_URL="$DB_URL" \
  -w /app insight-backend:latest \
  python -m unittest "$@"
