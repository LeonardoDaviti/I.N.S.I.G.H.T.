#!/usr/bin/env bash
# The real-data check before a merge (issue 0075 E): the judged cases, the invariants against main's
# baseline, the story job's identity, and the diff of everything the code derives, on copies of real data.
#
#   scripts/realdata-check.sh [options] <db>
#
#   <db>               the copy to check (insight_lab, a fresh dump's copy). Only read: pg_dump'ed once.
#   --base <ref>       the code to compare against (default: main)
#   --head <ref>       the code to check (default: this checkout's working tree)
#   --image <tag>      a local backend image to run the code in (default: the newest insight-backend:lab-*);
#                      the code is mounted over it, nothing is built or pulled
#   --identity <m:f>   the incremental job's identity check (default insight_core.scripts.story_identity:check;
#                      a version without it reports "not measured")
#   --allow name=why   an invariant rise the spec names (repeatable)
#   --now <ISO>        the clock the services read (default: the copy's last fetch)
#   --titles-only      no story job: snapshot titles, text starts and link titles of both versions over one
#                      read-only copy (a replay of a title change), no cases or invariants
#   --keep             keep the scratch copies
#   --no-cache         run the base side again even when its cached outputs match (and cache the new ones)
#   --in-place <zip>   one database only, never copied (owner 2026-11-19): <db> is made on the scratch Postgres from the
#                      export <zip> (db/import_export.py, at the export's migrations; each side migrates) and changed
#                      by the run. The base side runs only when the cache lacks it: restore, base side, restore again,
#                      head side; else one restore, the head side. <db> is dropped at the end (--keep keeps it).
#
# Env: CASES (plan/research/lab/cases.json), JOURNEYS (plan/research/lab/journeys.json, 0250), OUT (plan/research/lab/checks), PG_SRC (where <db> is), PG (the scratch
# server; default scripts/scratch-db.sh's), SCRATCH_DB=0 (copies on PG_SRC), SCRATCH_A / SCRATCH_B (the
# scratch copies' names: <db>_check_<pid>_a / _b, one pair per run),
# NETWORK (insight_insight-network), RESOURCE_BUDGETS (JSON: the jobs' budgets for this run, checks/resources.py),
# CACHE_KEEP (the cache entries kept, newest first: 8).
#
# Each version's code runs over its own scratch copy (one pg_restore of the dump, then a template copy of it), in a
# container of its own, both at once: first what a deploy's first start runs (the incremental job to the end, a
# rule change's rebuild when the copy's rows are of other rules: issue 0110), then the full job. Nothing is fetched or downloaded. The report (it names the owner's
# posts) goes to $OUT/<head>-<date>.md, private; its path goes in the merge notes. Exit 1: don't merge.
#
# The sides' cache (v10.17; one cache for both modes, 0253): a side's outputs (job, snapshot, invariants, cases, job
# checks) are kept in $OUT/base-cache/<key>, the key what they depend on: the code that ran (the side's backend tree
# as it ran, with this checkout's checks package and scripts over it: the content of its files, hashed), the data
# (the dump restored as SQL, hashed; or the export zip's sha256), the cases and journeys files, the image, --now and
# how the copy is prepared. The base side is looked up; when cached, only the head side runs (one copy, one
# restore). A side that ended and failed no step is kept: the base's, and the head's too (with no --identity), so the
# next release, whose base is this head merged, runs only its head over the same export. --no-cache runs the base
# again and replaces the entry. Not used with --titles-only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE=main; HEAD=""; IMAGE=""; IDENTITY=""; NOW=""; KEEP=0; TITLES_ONLY=0; NO_CACHE=0; ALLOW=(); IN_PLACE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="$2"; shift 2;;
    --head) HEAD="$2"; shift 2;;
    --image) IMAGE="$2"; shift 2;;
    --identity) IDENTITY="$2"; shift 2;;
    --allow) ALLOW+=("$2"); shift 2;;
    --now) NOW="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    --no-cache) NO_CACHE=1; shift;;
    --in-place) IN_PLACE="$2"; shift 2;;
    --titles-only) TITLES_ONLY=1; shift;;
    -h|--help) sed -n '2,43p' "$0"; exit 0;;
    -*) echo "unknown option $1" >&2; exit 2;;
    *) DB="$1"; shift;;
  esac
done
[ -n "${DB:-}" ] || { echo "usage: scripts/realdata-check.sh [options] <db>" >&2; exit 2; }

# <db> is read on insight-db (PG_SRC); the scratch copies are made and checked on the scratch Postgres (PG, v10.17:
# scripts/scratch-db.sh, started when not running), where a CREATE/DROP DATABASE never waits on the durable server's
# checkpoints. SCRATCH_DB=0: the copies on insight-db, as before.
PG_SRC="${PG_SRC:-postgresql://insight:insight@postgres:5432}"
if [ "${SCRATCH_DB:-1}" = "1" ] && [ -z "${PG:-}" ]; then
  PG="$("$ROOT/scripts/scratch-db.sh" up)"; PGCONTAINER="${PGCONTAINER:-${SCRATCH_CONTAINER:-insight-scratch-db}}"
fi
PG="${PG:-$PG_SRC}"
NETWORK="${NETWORK:-insight_insight-network}"
# plan/research/ is private and lives in the main checkout only (a worktree has none): read it there.
MAIN_ROOT="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")"
CASES="${CASES:-$MAIN_ROOT/plan/research/lab/cases.json}"
JOURNEYS="${JOURNEYS:-$MAIN_ROOT/plan/research/lab/journeys.json}"   # 0250: the journeys' hard set (private)
OUT="${OUT:-$MAIN_ROOT/plan/research/lab/checks}"
# Each run has its own copies (its process id), so runs at the same time never share or drop each other's.
SCRATCH_A="${SCRATCH_A:-${DB}_check_$$_a}"
SCRATCH_B="${SCRATCH_B:-${DB}_check_$$_b}"
for name in "$SCRATCH_A" "$SCRATCH_B"; do
  if [[ ! "$name" =~ _(check_[ab]|check_[0-9]+_[ab]|[0-9]{4}[ab]|test)$ ]] || [ "$name" = "$DB" ]; then
    echo "refusing scratch name $name: it must end in _check_a/_check_b, _check_<pid>_a/b, _<nnnn>a/b or _test" >&2; exit 2
  fi
done
if [ -z "$IMAGE" ]; then
  IMAGE="$(docker images --format '{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}' | grep -P '\tinsight-backend:lab-' | sort -r | head -1 | cut -f2)"
fi
[ -n "$IMAGE" ] || { echo "no local insight-backend:lab-* image; pass --image" >&2; exit 2; }

HEAD_LABEL="${HEAD:-$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)}"
STAMP="$(date +%Y-%m-%d)"
umask 077
WORK="$(mktemp -d /tmp/realdata-check.XXXXXX)"
mkdir -p "$OUT" "$WORK/base" "$WORK/head" "$WORK/trees/base" "$WORK/trees/head"
REPORT="$OUT/${HEAD_LABEL//\//-}-$STAMP.md"
RUN_ID="rdc-$$"
started=$(date +%s)
say() { echo "==> $(date +%H:%M:%S) $*"; }
# psql in the database container (docker exec, 0.1 s) when it is there; a container of the image (16 s a call on a busy disk) else
if docker exec "${PGCONTAINER:-insight-db}" true >/dev/null 2>&1; then
  psql_admin() { docker exec -i "${PGCONTAINER:-insight-db}" psql -q -At -U insight -d postgres -c "$1"; }
else
  psql_admin() { docker run --rm --network "$NETWORK" "$IMAGE" psql -q -At "$PG/postgres" -c "$1"; }
fi

cleanup() {
  docker rm -f "$RUN_ID-base" "$RUN_ID-head" "$RUN_ID-dump" "$RUN_ID-report" "$RUN_ID-restore" "$RUN_ID-hash" "$RUN_ID-analyze" >/dev/null 2>&1 || true   # by name only
  if [ "$KEEP" != "1" ] && [ "$TITLES_ONLY" != "1" ] && [ -z "$IN_PLACE" ]; then
    # detached when it can be: a DROP DATABASE waits for a checkpoint (minutes on a busy disk), and nothing waits on it
    docker exec -d "${PGCONTAINER:-insight-db}" psql -q -U insight -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH_A WITH (FORCE)" \
        -c "DROP DATABASE IF EXISTS $SCRATCH_B WITH (FORCE)" >/dev/null 2>&1 \
      || { psql_admin "DROP DATABASE IF EXISTS $SCRATCH_A" >/dev/null 2>&1; psql_admin "DROP DATABASE IF EXISTS $SCRATCH_B" >/dev/null 2>&1; } || true
  fi
  if [ -n "$IN_PLACE" ] && [ "$KEEP" != "1" ]; then   # the one copy, made from the export: dropped when the run ends
    docker exec -d "${PGCONTAINER:-insight-db}" psql -q -U insight -d postgres -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK" || echo "left $WORK (remove it by hand)" >&2
}
trap cleanup EXIT

# ---- the two versions' code, each with this checkout's checks package ----------------------------
say "code: $BASE against ${HEAD:-the working tree}, in $IMAGE"
git -C "$ROOT" archive "$BASE" backend | tar -x -C "$WORK/trees/base"
if [ -n "$HEAD" ]; then
  git -C "$ROOT" archive "$HEAD" backend | tar -x -C "$WORK/trees/head"
else
  tar -C "$ROOT" --exclude='__pycache__' --exclude='backend/logs' --exclude='backend/insight_core/logs/*.log' -cf - backend \
    | tar -x -C "$WORK/trees/head"
fi
for side in base head; do   # the checks run on any version: the newest copy of the package and its scripts
  rm -rf "$WORK/trees/$side/backend/insight_core/checks"
  cp -r "$ROOT/backend/insight_core/checks" "$WORK/trees/$side/backend/insight_core/checks"
  cp "$ROOT/backend/insight_core/scripts/check_cases.py" "$ROOT/backend/insight_core/scripts/check_invariants.py" \
     "$WORK/trees/$side/backend/insight_core/scripts/"
done
if [ -f "$CASES" ]; then cp "$CASES" "$WORK/cases.json"; fi
if [ -f "$JOURNEYS" ]; then cp "$JOURNEYS" "$WORK/journeys-set.json"; fi

run_side() {   # run_side <side> <db> [env…]
  local side="$1" db="$2"; shift 2
  docker run --rm --name "$RUN_ID-$side" --network "$NETWORK" -v "$WORK/trees/$side/backend:/app:ro" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" \
    -w "/work/$side" -e PYTHONPATH=/app -e PYTHONDONTWRITEBYTECODE=1 -e CASES=/work/cases.json -e JOURNEYS=/work/journeys-set.json "$@" \
    "$IMAGE" sh /app/insight_core/checks/side.sh "$PG/$db" "$side" "$NOW"
}

# ---- the sides' cache (one for both modes, 0253) -----------------------------------------------
CACHE_DIR="$OUT/base-cache"
CASES_SHA="$( [ -f "$WORK/cases.json" ] && sha256sum < "$WORK/cases.json" | cut -c1-64 || echo none)"
JOURNEYS_SHA="$( [ -f "$WORK/journeys-set.json" ] && sha256sum < "$WORK/journeys-set.json" | cut -c1-64 || echo none)"
IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE")"
DATA_SHA=""; COPY_PREP=""   # set by the mode: what the copy holds, and how it was prepared (a change there is a new key)
tree_sha() {   # tree_sha <side>: the content of the code the side runs (its files, the checks over them), hashed
  (cd "$WORK/trees/$1/backend" && find . -type f ! -path '*/__pycache__/*' ! -name '*.pyc' ! -path './logs/*' \
     ! -path './insight_core/logs/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) | sha256sum | cut -c1-64
}
key_text() {   # key_text <side>: what the side's outputs depend on
  echo "code=$(tree_sha "$1") data=$DATA_SHA cases=$CASES_SHA journeys=$JOURNEYS_SHA image=$IMAGE_ID now=$NOW copy=$COPY_PREP"
}
key_of() { echo "$1" | sha256sum | cut -c1-24; }
side_ok() {    # side_ok <side>: the side ended and failed no step
  grep -q "\] .* done$" "$WORK/$1.log" && ! grep -q "FAILED" "$WORK/$1.log"
}
cache_put() {  # cache_put <side> <ref>: the side's outputs kept under its key; the newest CACHE_KEEP entries kept
  local text key tmp
  text="$(key_text "$1")"; key="$(key_of "$text")"
  mkdir -p "$CACHE_DIR"
  tmp="$(mktemp -d "$CACHE_DIR/.new.XXXXXX")"
  cp -r "$WORK/$1" "$tmp/base"; cp "$WORK/$1.log" "$tmp/base.log"
  echo "$text" > "$tmp/key.txt"; date -u +%Y-%m-%dT%H:%M:%SZ > "$tmp/at.txt"; echo "$2" > "$tmp/base-ref.txt"; echo "$1" > "$tmp/side.txt"
  rm -rf "${CACHE_DIR:?}/$key"; mv "$tmp" "$CACHE_DIR/$key"
  say "the $1 side ($2) cached as $key"
  find "$CACHE_DIR" -mindepth 2 -maxdepth 2 -name key.txt -printf '%T@ %h\n' | sort -rn | tail -n +$(( ${CACHE_KEEP:-8} + 1 )) \
    | cut -d' ' -f2- | while read -r old; do rm -rf "$old"; done
}
cache_lookup() {   # sets KEY and CACHED (the base side's entry, or "")
  KEY_TEXT="$(key_text base)"; KEY="$(key_of "$KEY_TEXT")"; CACHED=""
  if [ "$NO_CACHE" != "1" ] && [ -f "$CACHE_DIR/$KEY/key.txt" ] && [ -d "$CACHE_DIR/$KEY/base" ]; then
    CACHED="$CACHE_DIR/$KEY"
    CACHED_FROM="the $(cat "$CACHED/side.txt" 2>/dev/null || echo base) side of $(cat "$CACHED/base-ref.txt"), made $(cat "$CACHED/at.txt")"
    say "base side cached ($KEY, $CACHED_FROM): only the head side runs"
    cp -r "$CACHED/base/." "$WORK/base/"; cp "$CACHED/base.log" "$WORK/base.log"
  fi
}
head_kept() {   # the head side kept for the next release (its base), unless a non-default identity check ran
  if [ -z "$IDENTITY" ] && side_ok head; then cache_put head "$HEAD_LABEL"; fi
}

if [ -n "$IN_PLACE" ]; then
  # ---- one database, no copy: <db> made from the export for each side that runs ------------------
  EXPORT="$IN_PLACE"
  [ -f "$EXPORT" ] || { echo "--in-place: no export $EXPORT" >&2; exit 2; }
  [ "${SCRATCH_DB:-1}" = "1" ] || { echo "--in-place: <db> is made on the scratch Postgres (not with SCRATCH_DB=0)" >&2; exit 2; }
  case "$DB" in insight|insight_lab|insight_preview|insight_server_copy|postgres|template*) echo "refusing to remake $DB" >&2; exit 2;; esac
  say "in place: $DB from $(basename "$EXPORT") (no copy); the export's sha256"
  DATA_SHA="export:$(sha256sum < "$EXPORT" | cut -c1-64)"; COPY_PREP="import_export-analyzed-v1"
  restore_in_place() {   # <db> made again from the export, at its migrations (each side migrates), then analyzed
    say "restore $DB from the export"
    psql_admin "DROP DATABASE IF EXISTS $DB WITH (FORCE)"; psql_admin "CREATE DATABASE $DB"
    docker run --rm --name "$RUN_ID-restore" --network "$NETWORK" -v "$WORK/trees/head/backend:/app:ro" \
      -v "$(realpath "$EXPORT"):/work-export.zip:ro" -w /tmp --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONPATH=/app \
      -e PYTHONDONTWRITEBYTECODE=1 "$IMAGE" python -c 'import sys, time; from insight_core.db.import_export import restore
t = time.monotonic(); n = restore(sys.argv[1], sys.argv[2]); print(f"restored {len(n)} tables, {sum(n.values())} rows in {time.monotonic() - t:.0f} s")' \
      /work-export.zip "$PG/$DB" > "$WORK/restore.log" 2>&1 || { tail -n 20 "$WORK/restore.log" >&2; echo "restore failed" >&2; exit 2; }
    tail -n 2 "$WORK/restore.log"
    say "analyze $DB"
    docker run --rm --name "$RUN_ID-analyze" --network "$NETWORK" "$IMAGE" vacuumdb --analyze-only -q -j 4 -d "$PG/$DB"
  }
  cache_lookup
  if [ -z "$CACHED" ]; then
    restore_in_place
    say "the base version on $DB: migrate, full story job, snapshot, invariants, cases, job checks"
    run_side base "$DB" > "$WORK/base.log" 2>&1 || true
    side_ok base || { cat "$WORK/base.log"; tail -n 40 "$WORK"/base/*.log >&2 2>/dev/null; echo "the base side failed: nothing kept" >&2; exit 2; }
    cache_put base "$BASE"
  fi
  restore_in_place
  say "the head version on $DB: migrate, full story job, snapshot, invariants, cases, job checks"
  run_side head "$DB" ${IDENTITY:+-e IDENTITY="$IDENTITY"} > "$WORK/head.log" 2>&1 || true
  cat "$WORK/base.log" "$WORK/head.log"
  head_kept
elif [ "$TITLES_ONLY" = "1" ]; then
  say "titles only: both versions read $DB (read-only), no story job"
  PG="$PG_SRC" run_side base "$DB" -e NO_JOB=1 -e PARTS=posts,links -e PARTS_ONLY=1 &
  PG="$PG_SRC" run_side head "$DB" -e NO_JOB=1 -e PARTS=posts,links -e PARTS_ONLY=1 &
  wait
else
  # ---- scratch copies: one dump, one restore, one template copy --------------------------------
  say "dump $DB (read-only)"
  docker run --rm --name "$RUN_ID-dump" --network "$NETWORK" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" "$IMAGE" pg_dump -Fc -Z1 -f /work/copy.dump "$PG_SRC/$DB"
  # One restore (its index builds are most of the time), then a template copy of it when the base side runs: no second
  # restore. The copy's content hash (the dump as SQL, less pg_dump's per-run \restrict key) beside it.
  say "restore into $SCRATCH_B; the copy's content hash"
  psql_admin "DROP DATABASE IF EXISTS $SCRATCH_A" ; psql_admin "DROP DATABASE IF EXISTS $SCRATCH_B"
  psql_admin "CREATE DATABASE $SCRATCH_B"
  docker run --rm --name "$RUN_ID-hash" --network "$NETWORK" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" "$IMAGE" \
    sh -c 'pg_restore -f - /work/copy.dump | grep -v -e "^\\\\restrict " -e "^\\\\unrestrict " | sha256sum | cut -c1-64' > "$WORK/dump.sha" &
  pid_hash=$!
  docker run --rm --name "$RUN_ID-restore" --network "$NETWORK" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" "$IMAGE" \
    pg_restore -j 8 --no-owner --no-privileges -d "$PG/$SCRATCH_B" /work/copy.dump 2> "$WORK/restore.log" || true
  wait $pid_hash || { echo "hashing the dump failed" >&2; exit 2; }
  grep -v -e transaction_timeout -e "errors ignored" -e "^Command was" "$WORK/restore.log" | grep -i error \
    && { echo "restore failed" >&2; exit 2; } || true
  # Planner statistics before any copy is taken or checked (v10.16.2, 9fcd09a): pg_restore writes none, and the
  # template copy takes the catalog but not the activity counters, so autovacuum analyzed one copy and never the
  # other's untouched tables (post_parts, sources): that side's API planned /api/feed blind, every request slow, and
  # markx.api_during_run / _rebuild were "not measured" or rose on it whatever its code. Analyzed once here, on the
  # scratch server, the head's copy has them on a cached run too, and the base's copy (a template copy of this one)
  # starts with the same ones.
  say "analyze $SCRATCH_B"
  docker run --rm --name "$RUN_ID-analyze" --network "$NETWORK" "$IMAGE" vacuumdb --analyze-only -q -j 4 -d "$PG/$SCRATCH_B"
  rm -f "$WORK/copy.dump"
  DATA_SHA="dump:$(cat "$WORK/dump.sha")"; COPY_PREP="analyzed-v1"
  cache_lookup

  if [ -n "$CACHED" ]; then
    say "the head version: migrate, full story job, snapshot, invariants, cases, job checks"
    run_side head "$SCRATCH_B" ${IDENTITY:+-e IDENTITY="$IDENTITY"} > "$WORK/head.log" 2>&1 || true
    cat "$WORK/base.log" "$WORK/head.log"
  else
    say "copy $SCRATCH_B to $SCRATCH_A (a template copy)"
    # WAL_LOG, not FILE_COPY (v10.17): a FILE_COPY waits for a checkpoint first, and with several agents writing a
    # checkpoint took over 20 minutes (measured 2026-11-13: this copy waited 23 min behind it)
    psql_admin "CREATE DATABASE $SCRATCH_A TEMPLATE $SCRATCH_B STRATEGY WAL_LOG"
    say "both versions at once: migrate, full story job, snapshot, invariants, cases, job checks"
    run_side base "$SCRATCH_A" > "$WORK/base.log" 2>&1 &
    pid_base=$!
    run_side head "$SCRATCH_B" ${IDENTITY:+-e IDENTITY="$IDENTITY"} > "$WORK/head.log" 2>&1 &
    pid_head=$!
    base_ok=1
    wait $pid_base || base_ok=0
    wait $pid_head || true
    cat "$WORK/base.log" "$WORK/head.log"
    if [ "$base_ok" = 1 ] && side_ok base; then cache_put base "$BASE"; fi
  fi
  head_kept
fi

say "report"
ALLOW_ARGS=(); [ ${#ALLOW[@]} -gt 0 ] && ALLOW_ARGS=(--allow "${ALLOW[@]}")
set +e
docker run --rm --name "$RUN_ID-report" --network "$NETWORK" -v "$WORK/trees/head/backend:/app:ro" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" -w /work -e PYTHONPATH=/app \
  -e PYTHONDONTWRITEBYTECODE=1 ${RESOURCE_BUDGETS:+-e RESOURCE_BUDGETS="$RESOURCE_BUDGETS"} "$IMAGE" python -m insight_core.checks.report --work /work --out /work/report.md \
  --label-base "$BASE" --label-head "$HEAD_LABEL" --copy "$DB" "${ALLOW_ARGS[@]}"
verdict=$?
set -e
elapsed=$(( $(date +%s) - started ))
cache_note=""
[ -n "${CACHED:-}" ] && cache_note=" The base side's outputs came from the cache ($KEY: $CACHED_FROM)."
{ cat "$WORK/report.md"; echo; echo "Took ${elapsed} s ($(( elapsed / 60 )) min $(( elapsed % 60 )) s), image $IMAGE.$cache_note"; } > "$REPORT"
mkdir -p "${REPORT%.md}"
for side in base head; do
  for f in deploy.json invariants.json jobs.json cases.json job.json resources.json; do
    [ -f "$WORK/$side/$f" ] && cp "$WORK/$side/$f" "${REPORT%.md}/$side-$f"
  done
done
[ -f "$WORK/diff-counts.json" ] && cp "$WORK/diff-counts.json" "${REPORT%.md}/"
say "took ${elapsed} s; report: $REPORT"
exit $verdict
