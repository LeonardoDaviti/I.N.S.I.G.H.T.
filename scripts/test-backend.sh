#!/usr/bin/env bash
# Run the backend tests from any checkout or worktree, the way the scale-v1014 work ran them:
# build this checkout's backend into an image of its own tag (never insight-backend:latest, which the
# running services use), then ./run-tests.sh creates a fresh *_test database, migrates it, runs the
# tests in the image on the compose network, and drops the database on exit.
#
# Usage:
#   scripts/test-backend.sh                                        # the whole suite
#   scripts/test-backend.sh insight_core.tests.test_markx_scale    # modules / classes / tests (unittest names)
#   REPEAT=10 scripts/test-backend.sh insight_core.tests.test_markx_scale.PlannerMarks.test_x   # n runs, one image
#
# Environment:
#   ENV_FILE    the .env to run with (default: ./.env, else the main checkout's .env for a worktree)
#   TEST_IMAGE  the image tag (default: insight-backend:test-<branch>)
#   REPEAT      run the same tests this many times (each run its own fresh database)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${ENV_FILE:-}" ]; then
  if [ -f .env ]; then ENV_FILE=.env
  else ENV_FILE="$(git rev-parse --path-format=absolute --git-common-dir)/../.env"; fi
fi
[ -f "$ENV_FILE" ] || { echo "error: no .env (set ENV_FILE)" >&2; exit 1; }

branch="$(git rev-parse --abbrev-ref HEAD | tr -c 'a-zA-Z0-9_.-' '-')"
export TEST_IMAGE="${TEST_IMAGE:-insight-backend:test-${branch}}"

# run-tests.sh reads .env next to it; link one in for this run when the checkout has none (removed after)
linked=0
if [ ! -e .env ]; then ln -s "$(realpath "$ENV_FILE")" .env; linked=1; fi
cleanup() { if [ "$linked" = 1 ]; then rm -f .env; fi; }   # an if, never a failing && as the trap's last status
trap cleanup EXIT

echo "==> building ${TEST_IMAGE}"
docker build -q -t "$TEST_IMAGE" backend >/dev/null

status=0
for n in $(seq 1 "${REPEAT:-1}"); do
  [ "${REPEAT:-1}" -gt 1 ] && echo "==> run $n of ${REPEAT}"
  SKIP_BUILD=1 ./run-tests.sh "$@" || status=1
done
exit $status
