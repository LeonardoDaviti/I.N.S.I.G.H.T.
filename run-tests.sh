#!/usr/bin/env bash
# Run the backend test suite the only way it is meaningful: inside the image.
#
# The image holds the real packages from requirements.txt and reaches the database on the
# compose network. The host has neither, so host results are not a signal.
#
# Usage:
#   ./run-tests.sh                                   # whole suite
#   ./run-tests.sh insight_core.tests.test_ingestion_runner   # one module
#
# Environment:
#   TEST_DATABASE_URL   test against this database instead of a fresh one (MIGRATE=1 migrates it)
#   TEST_IMAGE          build and run this image tag instead of insight-backend:latest
#   SKIP_BUILD=1        run the image as it is
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "error: .env not found next to run-tests.sh" >&2
  exit 1
fi

IMAGE="${TEST_IMAGE:-insight-backend:latest}"
NETWORK=insight_insight-network

# Build every run. The image bakes the source in (no volume is mounted), so a stale image
# silently tests code that is no longer on disk - a green run that proves nothing.
# Layer caching makes a no-change rebuild cost about a second. SKIP_BUILD=1 opts out.
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "==> building ${IMAGE}"
  if [ -n "${TEST_IMAGE:-}" ]; then docker build -q -t "$IMAGE" backend >/dev/null; else docker compose build backend; fi
fi

in_image() {
  docker run --rm --network "$NETWORK" --env-file .env -e DATABASE_URL="$DB_URL" -w /app "$IMAGE" "$@"
}

# Several suites INSERT and commit rows, so each run gets a database of its own (issue 0071):
# created here, migrated, and dropped when the run ends, so two runs at once never share rows.
# Its name ends in _test, which the committing suites require. Never the live `insight` one.
SERVER=postgresql://insight:insight@postgres:5432
if [ -n "${TEST_DATABASE_URL:-}" ]; then
  DB_URL="$TEST_DATABASE_URL"
else
  DB_NAME="insight_run_$(date +%s)_$$_test"
  DB_URL="$SERVER/$DB_NAME"
  drop() { docker run --rm --network "$NETWORK" "$IMAGE" psql -q "$SERVER/postgres" -c "DROP DATABASE IF EXISTS $DB_NAME" >/dev/null || true; }
  trap drop EXIT
  echo "==> creating ${DB_NAME}"
  docker run --rm --network "$NETWORK" "$IMAGE" psql -q "$SERVER/postgres" -c "CREATE DATABASE $DB_NAME" >/dev/null
  MIGRATE=1
fi

if [ "$#" -eq 0 ]; then
  set -- discover -s insight_core/tests -p 'test_*.py'
fi

# MIGRATE=1 applies pending migrations to $DB_URL first, in the same image, so a slice that
# adds a migration never runs its tests against an unmigrated schema.
if [ "${MIGRATE:-0}" = "1" ]; then
  echo "==> migrating ${DB_URL##*/}"
  in_image python -m insight_core.db.migrate
fi

in_image python -m unittest "$@"
