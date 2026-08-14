#!/usr/bin/env bash
# Run the backend test suite the only way it is meaningful: inside the image.
#
# Running `python -m unittest` on the host imports the vendored stubs in backend/
# (fastapi/, pydantic/, psycopg/, dotenv), which the Dockerfile deletes at build time
# in favour of the real packages. The host also has no `psql` binary, which several
# DB-backed tests shell out to. Both produce failures that do not exist in the
# deployed image, so host results are not a signal.
#
# Usage:
#   ./run-tests.sh                                   # whole suite
#   ./run-tests.sh insight_core.tests.test_inbox_service   # one module
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "error: .env not found next to run-tests.sh" >&2
  exit 1
fi

# Build only if the image is missing; pass REBUILD=1 to force.
if [ "${REBUILD:-0}" = "1" ] || ! docker image inspect insight-backend:latest >/dev/null 2>&1; then
  echo "==> building insight-backend:latest"
  docker compose build backend
fi

# NOTE: several suites connect to DATABASE_URL and INSERT rows. Point TEST_DATABASE_URL
# at a scratch database if you do not want them touching live data.
DB_URL="${TEST_DATABASE_URL:-postgresql://insight:insight@postgres:5432/insight}"

exec docker run --rm \
  --network insight_insight-network \
  --env-file .env \
  -e DATABASE_URL="$DB_URL" \
  -e LANGFUSE_ENABLED=false \
  -w /app insight-backend:latest \
  python -m unittest "${@:-discover -s insight_core/tests -p test_*.py}"
