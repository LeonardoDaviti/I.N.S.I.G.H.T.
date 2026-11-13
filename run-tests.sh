#!/usr/bin/env bash
# Run the backend test suite the only way it is meaningful: inside the image.
#
# The image holds the real packages from requirements.txt and reaches the database on the
# compose network. The host has neither, so host results are not a signal.
#
# Usage:
#   ./run-tests.sh                                   # whole suite
#   ./run-tests.sh insight_core.tests.test_ingestion_runner   # one module
#   JOBS=4 ./run-tests.sh                            # the whole suite in 4 shards at once, each its own database
#
# Environment:
#   TEST_DATABASE_URL   test against this database instead of a fresh one (MIGRATE=1 migrates it)
#   TEST_IMAGE          build and run this image tag instead of insight-backend:latest
#   SKIP_BUILD=1        run the image as it is
#   JOBS=n              the whole suite (no arguments) split by module into n shards run at once (default 1)
#   NO_TEMPLATE=1       create and migrate the run's database from nothing (the template's check)
#   DISCOVER=1          the whole suite as one `unittest discover` (every module imported at the start), as before v10.17
set -euo pipefail

cd "$(dirname "$0")"

# the .env to run with: ENV_FILE, else the one next to this script (scripts/test-backend.sh passes ENV_FILE, so runs
# at once in one checkout never link or remove a shared .env)
ENV_FILE="${ENV_FILE:-.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE not found (a .env next to run-tests.sh, or ENV_FILE)" >&2
  exit 1
fi
ENV_FILE="$(realpath "$ENV_FILE")"

IMAGE="${TEST_IMAGE:-insight-backend:latest}"
NETWORK=insight_insight-network
JOBS="${JOBS:-1}"

# Build every run. The image bakes the source in (no volume is mounted), so a stale image
# silently tests code that is no longer on disk - a green run that proves nothing.
# Layer caching makes a no-change rebuild cost about a second. SKIP_BUILD=1 opts out.
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  echo "==> building ${IMAGE}"
  if [ -n "${TEST_IMAGE:-}" ]; then docker build -q -t "$IMAGE" backend >/dev/null; else docker compose build backend; fi
fi

# The runs' databases live on the scratch Postgres (v10.17, scripts/scratch-db.sh: started here when it is not
# running), a disposable server tuned for throwaway data, never on insight-db, which keeps the owner's originals:
# there every CREATE/DROP DATABASE waited for a checkpoint behind every other agent's writes. SCRATCH_DB=0 runs on
# insight-db as before.
if [ "${SCRATCH_DB:-1}" = "1" ]; then
  SERVER="$(scripts/scratch-db.sh up)"
  PGCONTAINER="${SCRATCH_CONTAINER:-insight-scratch-db}"
else
  SERVER=postgresql://insight:insight@postgres:5432
  PGCONTAINER="${PGCONTAINER:-insight-db}"
fi
DBHOST="${SERVER#*@}"; DBHOST="${DBHOST%%:*}"
# psql in the database's own container (docker exec: 0.1 s), not a container of the image started for each statement
# (docker run: 16 s each on a busy disk, measured); the image's psql when that container is not there.
if docker exec "$PGCONTAINER" true >/dev/null 2>&1; then
  admin() { docker exec -i "$PGCONTAINER" psql -X -q -At -U insight -d postgres -c "$1"; }
  admin_many() { docker exec -i "$PGCONTAINER" psql -X -q -At -U insight -d postgres "$@"; }
  admin_bg() { docker exec -d "$PGCONTAINER" psql -X -q -At -U insight -d postgres "$@"; }
else
  admin() { docker run --rm --network "$NETWORK" "$IMAGE" psql -X -q -At "$SERVER/postgres" -c "$1"; }
  admin_many() { docker run --rm --network "$NETWORK" "$IMAGE" psql -X -q -At "$SERVER/postgres" "$@"; }
  admin_bg() { docker run -d --rm --network "$NETWORK" "$IMAGE" psql -X -q -At "$SERVER/postgres" "$@"; }
fi

# The migrated template (v10.17): every migration applied once into insight_tmpl_<hash>_test, keyed by the hash of
# the migrations directory (and migrate.py), and each run's database a CREATE DATABASE ... TEMPLATE of it (about a second) instead of
# a database migrated from nothing. Built by the first run that needs it (under a name of its own, then renamed, so
# two runs building at once never see half of one); it refuses connections, so a copy never waits for a reader.
# The newest few templates are kept (other branches' migrations), older ones dropped.
template_db() {
  local hash name building
  hash="$( (cd backend/insight_core/db && { ls migrations/*.sql | LC_ALL=C sort; cat $(ls migrations/*.sql | LC_ALL=C sort) migrate.py; } | sha256sum) | cut -c1-12)"
  name="insight_tmpl_${hash}_test"
  if [ "$(admin "SELECT 1 FROM pg_database WHERE datname = '$name'")" != 1 ]; then
    building="insight_tmplbuild_$$_test"
    echo "==> building the test template ${name} (the migrations changed)" >&2
    admin "DROP DATABASE IF EXISTS $building" >/dev/null 2>&1
    admin_many -c "CREATE DATABASE $building" -c "COMMENT ON DATABASE $building IS '$RUN_TAG'" >/dev/null
    local out
    if ! out="$(docker run --rm --network "$NETWORK" --env-file "$ENV_FILE" -e DATABASE_URL="$SERVER/$building" -w /app "$IMAGE" \
                python -m insight_core.db.migrate 2>&1)"; then
      echo "$out" | tail -30 >&2
      admin "DROP DATABASE IF EXISTS $building" >/dev/null || true
      echo "error: migrating the test template failed" >&2; return 1
    fi
    admin_many -c "ALTER DATABASE $building ALLOW_CONNECTIONS false" -c "COMMENT ON DATABASE $building IS NULL" >/dev/null
    if ! admin "ALTER DATABASE $building RENAME TO $name" >/dev/null 2>&1; then
      admin "DROP DATABASE IF EXISTS $building" >/dev/null   # another run made it first
    fi
    # keep the 6 newest templates
    admin "SELECT datname FROM pg_database WHERE datname ~ '^insight_tmpl_[0-9a-f]{12}_test$' AND datname <> '$name'
             ORDER BY oid DESC OFFSET 5" | while read -r old; do
      [ -n "$old" ] && admin "DROP DATABASE IF EXISTS $old" >/dev/null 2>&1 || true
    done
  fi
  echo "$name"
}

# This run's identity (stamped on its databases and containers; see clean_orphans below)
BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown)"
pid_start() { awk '{print $22}' "/proc/$1/stat" 2>/dev/null; }
RUN_TAG="run-tests:${BOOT_ID}:$$:$(pid_start $$)"

# Several suites INSERT and commit rows, so each run (each shard) gets a database of its own (issue 0071): created
# here, and dropped when the run ends, so two runs at once never share rows. Its name ends in _test, which the
# committing suites require. Never the live `insight`. The drop runs in a detached container: a DROP DATABASE waits
# for a checkpoint, minutes while other copies write (measured 3 min for a 15-test module), and nothing waits on it.
CREATED=()
drop_all() {
  # this run's test containers first (a run stopped by Ctrl-C or a kill left them running against the database)
  docker ps -q --filter "label=insight.test-run=$RUN_TAG" | xargs -r docker rm -f >/dev/null 2>&1 || true
  [ "${#CREATED[@]}" -gt 0 ] || return 0
  local args=() db
  for db in "${CREATED[@]}"; do args+=(-c "DROP DATABASE IF EXISTS $db WITH (FORCE)"); done
  admin_bg "${args[@]}" >/dev/null 2>&1 \
    || for db in "${CREATED[@]}"; do admin "DROP DATABASE IF EXISTS $db WITH (FORCE)" >/dev/null 2>&1 || true; done
}
trap drop_all EXIT

# What earlier runs left behind (v10.17: one module took 79, 378, then 781 s on three runs in a row while leftovers
# piled up): the containers and databases of runs that ENDED, and only those this runner can prove ended. Every run
# stamps what it makes with its identity, RUN_TAG = run-tests:<boot id>:<pid>:<the pid's start time> (a database's
# comment, a container's label insight.test-run). A run is proven ended when the machine has rebooted since (another
# boot id), or its pid is not running, or the pid now running started at another time (a reused pid). Anything without
# such a stamp - another tool's database, a run made before v10.17, an unlabelled container - is never touched, however
# old; neither is a database someone is connected to. Only on the server this run uses (the scratch one by default).
# CLEAN_ORPHANS=0 skips this; CLEAN_ORPHANS=dry lists what it would remove.
ended() {   # ended <tag>: true only when the tagged run is proven over
  local boot pid start
  IFS=: read -r _ boot pid start <<<"$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [ "$boot" != "$BOOT_ID" ] && [ "$BOOT_ID" != unknown ] && return 0
  [ -d "/proc/$pid" ] || return 0
  [ -n "$start" ] && [ "$(pid_start "$pid")" != "$start" ]
}
clean_orphans() {
  [ "${CLEAN_ORPHANS:-1}" = "0" ] && return 0
  local dry=0 cid tag db
  local -a dbs args
  [ "${CLEAN_ORPHANS:-1}" = "dry" ] && dry=1
  while read -r cid tag; do
    [ -n "$cid" ] && [[ "$tag" == run-tests:* ]] && ended "$tag" || continue
    if [ "$dry" = 1 ]; then echo "==> would remove container $cid (its run ended: $tag)" >&2
    else docker rm -f "$cid" >/dev/null 2>&1 || true; fi
  done < <(docker ps -a --filter "label=insight.test-run" --format '{{.ID}} {{.Label "insight.test-run"}}')
  docker exec "$PGCONTAINER" true >/dev/null 2>&1 || return 0
  dbs=()
  while IFS=$'\t' read -r db tag; do
    [ -n "$db" ] && [[ "$tag" == run-tests:* ]] && ended "$tag" && dbs+=("$db")
  done < <(docker exec -i "$PGCONTAINER" psql -X -q -At -F $'\t' -U insight -d postgres -c "SELECT d.datname,
             shobj_description(d.oid, 'pg_database') FROM pg_database d
            WHERE shobj_description(d.oid, 'pg_database') LIKE 'run-tests:%'
              AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname)")   # none in use now
  [ "${#dbs[@]}" -gt 0 ] || return 0
  if [ "$dry" = 1 ]; then printf "==> would drop %s (its run ended)\n" "${dbs[@]}" >&2; return 0; fi
  echo "==> dropping ${#dbs[@]} database(s) that runs which ended left behind" >&2
  args=()
  for db in "${dbs[@]}"; do args+=(-c "DROP DATABASE IF EXISTS $db WITH (FORCE)"); done
  admin_bg "${args[@]}" >/dev/null 2>&1 || true
}
clean_orphans

new_db() {   # new_db <name>: a fresh database for a run, migrated (from the template unless NO_TEMPLATE=1)
  local name="$1"
  CREATED+=("$name")
  if [ "${NO_TEMPLATE:-0}" = "1" ]; then
    admin_many -c "CREATE DATABASE $name" -c "COMMENT ON DATABASE $name IS '$RUN_TAG'" >/dev/null
    echo "==> migrating ${name}" >&2
    docker run --rm --network "$NETWORK" --env-file "$ENV_FILE" -e DATABASE_URL="$SERVER/$name" -w /app "$IMAGE" python -m insight_core.db.migrate >&2
  else
    # synchronous_commit off for the run's database (a setting of the database, not copied from the template): the
    # suites commit often, and each commit waited for its WAL flush on a disk other copies keep busy
    admin_many -c "CREATE DATABASE $name TEMPLATE $TEMPLATE" -c "COMMENT ON DATABASE $name IS '$RUN_TAG'" \
      -c "ALTER DATABASE $name SET synchronous_commit = off" >/dev/null
  fi
}

in_image() {   # in_image <db url> cmd...
  local url="$1"; shift
  docker run --rm --network "$NETWORK" --label "insight.test-run=$RUN_TAG" \
    --env-file "$ENV_FILE" -e DATABASE_URL="$url" -e ADMIN_DATABASE_URL="$SERVER/postgres" -e DB_HOST="$DBHOST" \
    -w /app "$IMAGE" "$@"
}

if [ -z "${TEST_DATABASE_URL:-}" ] && [ "${NO_TEMPLATE:-0}" != "1" ]; then TEMPLATE="$(template_db)"; fi

# The whole suite (no arguments) in JOBS shards at once (default 1): the modules dealt out, the slowest first (by the
# last run's times when known), each shard its own database and container; a shard's output is printed when it
# failed. A shard imports its modules first and runs them in name order, as `unittest discover` did: tests mix the
# module-level clocks of several modules (NOW = datetime.now() at import; test_markx_later failed when each module was
# imported just before it ran), and some read what earlier modules left. A shard is short, so its clocks are fresh.
if [ "$#" -eq 0 ] && [ -z "${TEST_DATABASE_URL:-}" ] && [ "${DISCOVER:-0}" != "1" ]; then
  TIMES="${XDG_CACHE_HOME:-$HOME/.cache}/insight-prep/test-times.tsv"
  mkdir -p "$(dirname "$TIMES")"; touch "$TIMES"
  OUTDIR="$(dirname "$TIMES")/shards/$$"   # this run's shard logs, kept for reading , not /tmp
  mkdir -p "$OUTDIR"   # the shard logs of runs that ended go, but the newest 5
  for d in $(ls -dt "$(dirname "$OUTDIR")"/*/ 2>/dev/null | tail -n +6); do kill -0 "$(basename "$d")" 2>/dev/null || rm -rf "$d"; done
  # modules by last time (unknown ones by file size), dealt to the shard with the least so far
  mapfile -t shards < <(for f in backend/insight_core/tests/test_*.py; do
      m="$(basename "$f" .py)"; t="$(awk -F'\t' -v m="$m" '$1==m {print $2}' "$TIMES" | tail -1)"
      echo -e "$m\t${t:-$(( $(stat -c %s "$f") / 2000 ))}"
    done | sort -t$'\t' -k2,2nr | awk -F'\t' -v n="$JOBS" '
      { best = 0; for (i = 1; i < n; i++) if (load[i] < load[best]) best = i
        load[best] += $2; list[best] = list[best] " insight_core.tests." $1 }
      END { for (i = 0; i < n; i++) print list[i] }')
  # each shard's modules in name order, as `unittest discover` ran them: some tests read what earlier modules left in the
  # database or the process (the HNSW neighbours of test_markx_storage, the children test_api_watchdog lists, the tied
  # rows of test_markx_event_types) and failed when the slowest modules ran first in one shard (measured)
  for i in "${!shards[@]}"; do shards[$i]="$(tr ' ' '\n' <<<"${shards[$i]}" | grep . | LC_ALL=C sort | paste -sd ' ' - || true)"; done
  mapfile -t shards < <(printf '%s\n' "${shards[@]}" | grep . || true)   # no empty shard (more JOBS than modules)
  echo "==> ${#shards[@]} shards from template ${TEMPLATE:-none}"
  # one process a shard, its modules one after another; a line for each module: tests, seconds, result
  SHARD_PY='
import sys, time, unittest
failed = 0
suites = [(m, unittest.defaultTestLoader.loadTestsFromName(m)) for m in sys.argv[1:]]   # all imported first, as discover
for m, suite in suites:
    t = time.monotonic()
    r = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
    bad = len(r.failures) + len(r.errors) + len(r.unexpectedSuccesses)
    failed += bad
    print("MODULE %s %d %.1f %s" % (m, r.testsRun, time.monotonic() - t, "FAILED" if bad else "OK"), flush=True)
sys.exit(1 if failed else 0)'
  pids=()
  for i in "${!shards[@]}"; do
    db="insight_run_$(date +%s)_$$_s${i}_test"
    new_db "$db"
    # shellcheck disable=SC2086
    in_image "$SERVER/$db" python -c "$SHARD_PY" ${shards[$i]} > "$OUTDIR/shard$i.log" 2>&1 &
    pids+=($!)
  done
  status=0
  for p in "${pids[@]}"; do wait "$p" || status=1; done
  for i in "${!shards[@]}"; do   # a shard that failed or ended early: its output, less the dots
    if grep -q ' FAILED$' "$OUTDIR/shard$i.log" || ! tail -1 "$OUTDIR/shard$i.log" | grep -q '^MODULE '; then
      echo "==> shard $i ($OUTDIR/shard$i.log):"
      grep -vE '^(MODULE .* OK|[.sxEF]*|-+|Ran [0-9]+ tests? in .*|OK.*)$' "$OUTDIR/shard$i.log" | grep -vE '^(INFO|WARNING|DEBUG) ' | tail -120 || true
    fi
  done
  total=$(cat "$OUTDIR"/shard*.log | awk '/^MODULE / {s += $3} END {print s + 0}')
  modules=$(cat "$OUTDIR"/shard*.log | grep -c '^MODULE ' || true)
  expected=$(ls backend/insight_core/tests/test_*.py | wc -l)
  [ "$modules" -eq "$expected" ] || { echo "error: $modules of $expected modules reported" >&2; status=1; }
  cat "$OUTDIR"/shard*.log | awk '/^MODULE / {sub(/^insight_core\.tests\./, "", $2); print $2 "\t" int($4 + 0.5)}' > "$TIMES.new" \
    && mv "$TIMES.new" "$TIMES"
  if [ "$status" = 0 ]; then echo "==> $JOBS shards, $modules modules, $total tests: OK"; else echo "==> $JOBS shards, $total tests: FAILED (above)"; fi
  exit $status
fi

if [ -n "${TEST_DATABASE_URL:-}" ]; then
  DB_URL="$TEST_DATABASE_URL"
else
  DB_NAME="insight_run_$(date +%s)_$$_test"
  echo "==> creating ${DB_NAME}${TEMPLATE:+ from ${TEMPLATE}}"
  new_db "$DB_NAME"
  DB_URL="$SERVER/$DB_NAME"
fi

if [ "$#" -eq 0 ]; then
  set -- discover -s insight_core/tests -p 'test_*.py'
fi

# MIGRATE=1 applies pending migrations to $DB_URL first, in the same image, so a slice that
# adds a migration never runs its tests against an unmigrated schema.
if [ "${MIGRATE:-0}" = "1" ]; then
  echo "==> migrating ${DB_URL##*/}"
  in_image "$DB_URL" python -m insight_core.db.migrate
fi

in_image "$DB_URL" python -m unittest "$@"
