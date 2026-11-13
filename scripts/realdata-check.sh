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
#
# Env: CASES (plan/research/lab/cases.json), OUT (plan/research/lab/checks), PG_SRC (where <db> is), PG (the scratch
# server; default scripts/scratch-db.sh's), SCRATCH_DB=0 (copies on PG_SRC), SCRATCH_A / SCRATCH_B (the
# scratch copies' names: <db>_check_<pid>_a / _b, one pair per run),
# NETWORK (insight_insight-network).
#
# Each version's code runs over its own scratch copy (one pg_restore of the dump, then a template copy of it), in a
# container of its own, both at once: first what a deploy's first start runs (the incremental job to the end, a
# rule change's rebuild when the copy's rows are of other rules: issue 0110), then the full job. Nothing is fetched or downloaded. The report (it names the owner's
# posts) goes to $OUT/<head>-<date>.md, private; its path goes in the merge notes. Exit 1: don't merge.
#
# The base side's cache (v10.17): the base side's outputs (job, snapshot, invariants, cases, job checks) are kept in
# $OUT/base-cache/<key>, the key the base's backend tree, the copy's content (its dump restored as SQL, hashed),
# the checks' code (the checks package, check_cases.py, check_invariants.py, side.sh: what runs inside the side), the cases file,
# the image and --now. A run whose key is cached runs only the head side (one scratch copy); --no-cache runs the
# base again and replaces the entry. A base side that failed is never cached. Not used with --titles-only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE=main; HEAD=""; IMAGE=""; IDENTITY=""; NOW=""; KEEP=0; TITLES_ONLY=0; NO_CACHE=0; ALLOW=()
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
    --titles-only) TITLES_ONLY=1; shift;;
    -h|--help) sed -n '2,30p' "$0"; exit 0;;
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
  docker rm -f "$RUN_ID-base" "$RUN_ID-head" "$RUN_ID-dump" "$RUN_ID-report" "$RUN_ID-restore" "$RUN_ID-hash" >/dev/null 2>&1 || true   # by name only
  if [ "$KEEP" != "1" ] && [ "$TITLES_ONLY" != "1" ]; then
    # detached when it can be: a DROP DATABASE waits for a checkpoint (minutes on a busy disk), and nothing waits on it
    docker exec -d "${PGCONTAINER:-insight-db}" psql -q -U insight -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH_A WITH (FORCE)" \
        -c "DROP DATABASE IF EXISTS $SCRATCH_B WITH (FORCE)" >/dev/null 2>&1 \
      || { psql_admin "DROP DATABASE IF EXISTS $SCRATCH_A" >/dev/null 2>&1; psql_admin "DROP DATABASE IF EXISTS $SCRATCH_B" >/dev/null 2>&1; } || true
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

run_side() {   # run_side <side> <db> [env…]
  local side="$1" db="$2"; shift 2
  docker run --rm --name "$RUN_ID-$side" --network "$NETWORK" -v "$WORK/trees/$side/backend:/app:ro" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" \
    -w "/work/$side" -e PYTHONPATH=/app -e PYTHONDONTWRITEBYTECODE=1 -e CASES=/work/cases.json "$@" \
    "$IMAGE" sh /app/insight_core/checks/side.sh "$PG/$db" "$side" "$NOW"
}

if [ "$TITLES_ONLY" = "1" ]; then
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
  rm -f "$WORK/copy.dump"

  # the base side's cache key: what its outputs depend on
  CACHE_DIR="$OUT/base-cache"
  BASE_TREE="$(git -C "$ROOT" rev-parse "$BASE^{commit}:backend")"
  CHECKS_SHA="$( (cd "$ROOT" && tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --exclude='__pycache__' -cf - \
                   backend/insight_core/checks backend/insight_core/scripts/check_cases.py \
                   backend/insight_core/scripts/check_invariants.py) | sha256sum | cut -c1-64)"
  CASES_SHA="$( [ -f "$WORK/cases.json" ] && sha256sum < "$WORK/cases.json" | cut -c1-64 || echo none)"
  IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE")"
  KEY_TEXT="base_tree=$BASE_TREE dump=$(cat "$WORK/dump.sha") checks=$CHECKS_SHA cases=$CASES_SHA image=$IMAGE_ID now=$NOW"
  KEY="$(echo "$KEY_TEXT" | sha256sum | cut -c1-24)"
  CACHED=""
  if [ "$NO_CACHE" != "1" ] && [ -f "$CACHE_DIR/$KEY/key.txt" ] && [ -d "$CACHE_DIR/$KEY/base" ]; then CACHED="$CACHE_DIR/$KEY"; fi

  if [ -n "$CACHED" ]; then
    say "base side cached ($KEY, from $(cat "$CACHED/at.txt")): only the head side runs"
    cp -r "$CACHED/base/." "$WORK/base/"
    cp "$CACHED/base.log" "$WORK/base.log"
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
    # a base side that ended and failed no step is cached (its outputs, its log)
    if [ "$base_ok" = 1 ] && ! grep -q "FAILED" "$WORK/base.log" && grep -q "\] .* done$" "$WORK/base.log"; then
      mkdir -p "$CACHE_DIR"
      tmp="$(mktemp -d "$CACHE_DIR/.new.XXXXXX")"
      cp -r "$WORK/base" "$tmp/base"; cp "$WORK/base.log" "$tmp/base.log"
      echo "$KEY_TEXT" > "$tmp/key.txt"; date -u +%Y-%m-%dT%H:%M:%SZ > "$tmp/at.txt"; echo "$BASE" > "$tmp/base-ref.txt"
      rm -rf "$CACHE_DIR/$KEY"; mv "$tmp" "$CACHE_DIR/$KEY"
      say "base side cached as $KEY"
    fi
  fi
fi

say "report"
ALLOW_ARGS=(); [ ${#ALLOW[@]} -gt 0 ] && ALLOW_ARGS=(--allow "${ALLOW[@]}")
set +e
docker run --rm --name "$RUN_ID-report" --network "$NETWORK" -v "$WORK/trees/head/backend:/app:ro" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" -w /work -e PYTHONPATH=/app \
  -e PYTHONDONTWRITEBYTECODE=1 "$IMAGE" python -m insight_core.checks.report --work /work --out /work/report.md \
  --label-base "$BASE" --label-head "$HEAD_LABEL" --copy "$DB" "${ALLOW_ARGS[@]}"
verdict=$?
set -e
elapsed=$(( $(date +%s) - started ))
cache_note=""
[ -n "${CACHED:-}" ] && cache_note=" The base side's outputs came from the cache ($KEY, made $(cat "$CACHED/at.txt"))."
{ cat "$WORK/report.md"; echo; echo "Took ${elapsed} s ($(( elapsed / 60 )) min $(( elapsed % 60 )) s), image $IMAGE.$cache_note"; } > "$REPORT"
mkdir -p "${REPORT%.md}"
for side in base head; do
  for f in deploy.json invariants.json jobs.json cases.json job.json; do
    [ -f "$WORK/$side/$f" ] && cp "$WORK/$side/$f" "${REPORT%.md}/$side-$f"
  done
done
[ -f "$WORK/diff-counts.json" ] && cp "$WORK/diff-counts.json" "${REPORT%.md}/"
say "took ${elapsed} s; report: $REPORT"
exit $verdict
