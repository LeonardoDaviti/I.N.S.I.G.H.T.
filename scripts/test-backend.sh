#!/usr/bin/env bash
# Run the backend tests from any checkout or worktree, the way the scale-v1014 work ran them:
# build this checkout's backend into an image of its own tag (never insight-backend:latest, which the
# running services use; tagged by the tree's content, so an unchanged tree is not built again), then
# ./run-tests.sh copies the migrated test template into a fresh *_test database, runs the tests in the
# image on the compose network, and drops the database on exit.
#
# Usage:
#   scripts/test-backend.sh                                        # the whole suite
#   JOBS=6 scripts/test-backend.sh                                 # the whole suite in 6 shards at once
#   scripts/test-backend.sh insight_core.tests.test_markx_scale    # modules / classes / tests (unittest names)
#   REPEAT=10 scripts/test-backend.sh insight_core.tests.test_markx_scale.PlannerMarks.test_x   # n runs, one image
#
# Environment:
#   ENV_FILE    the .env to run with (default: ./.env, else the main checkout's .env for a worktree)
#   TEST_IMAGE  the image tag (default: insight-backend:test-c<the backend tree's content hash>)
#   JOBS        the whole suite in this many shards at once, each its own database (run-tests.sh)
#   REPEAT      run the same tests this many times (each run its own fresh database)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${ENV_FILE:-}" ]; then
  if [ -f .env ]; then ENV_FILE=.env
  else ENV_FILE="$(git rev-parse --path-format=absolute --git-common-dir)/../.env"; fi
fi
[ -f "$ENV_FILE" ] || { echo "error: no .env (set ENV_FILE)" >&2; exit 1; }

# The image is tagged by the content of the backend tree (v10.17): a tree already built is not built again, and
# two checkouts with the same tree share one image. A changed tree (any file, committed or not) is a new tag.
if [ -z "${TEST_IMAGE:-}" ]; then
  tree="$(tar -C backend --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
            --exclude='__pycache__' --exclude='*.pyc' --exclude='./logs' --exclude='insight_core/logs/*/*.log' -cf - . | sha256sum | cut -c1-16)"
  export TEST_IMAGE="insight-backend:test-c${tree}"
  if docker image inspect "$TEST_IMAGE" >/dev/null 2>&1; then built=1; else built=0; fi
else
  built=0
fi

# run-tests.sh reads ENV_FILE (v10.17: a .env linked into the checkout for the run and removed after raced between
# runs at once in one checkout: "ln: failed to create symbolic link '.env': File exists", and the first to end took
# the others' .env away)
export ENV_FILE="$(realpath "$ENV_FILE")"

if [ "$built" = 1 ]; then
  echo "==> ${TEST_IMAGE} (this tree, built already)"
else
  echo "==> building ${TEST_IMAGE}"
  docker build -q -t "$TEST_IMAGE" backend >/dev/null
  # keep the 12 newest content-tagged test images (an image a run is using is never removed: docker refuses)
  docker images --format '{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}' | grep -P '\tinsight-backend:test-c[0-9a-f]{16}$' \
    | sort -r | tail -n +13 | cut -f2 | xargs -r docker rmi >/dev/null 2>&1 || true
fi

status=0
for n in $(seq 1 "${REPEAT:-1}"); do
  [ "${REPEAT:-1}" -gt 1 ] && echo "==> run $n of ${REPEAT}"
  SKIP_BUILD=1 ./run-tests.sh "$@" || status=1
done
exit $status
