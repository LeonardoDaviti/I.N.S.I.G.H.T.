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
#
# Env: CASES (plan/research/lab/cases.json), OUT (plan/research/lab/checks), SCRATCH_A / SCRATCH_B (the
# scratch copies' names: <db>_check_<pid>_a / _b, one pair per run), PG (postgresql://insight:insight@postgres:5432),
# NETWORK (insight_insight-network).
#
# Each version's code runs over its own scratch copy (one pg_restore of the dump, then a file copy of it), in a
# container of its own, both at once: first what a deploy's first start runs (the incremental job to the end, a
# rule change's rebuild when the copy's rows are of other rules: issue 0110), then the full job. Nothing is fetched or downloaded. The report (it names the owner's
# posts) goes to $OUT/<head>-<date>.md, private; its path goes in the merge notes. Exit 1: don't merge.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE=main; HEAD=""; IMAGE=""; IDENTITY=""; NOW=""; KEEP=0; TITLES_ONLY=0; ALLOW=()
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="$2"; shift 2;;
    --head) HEAD="$2"; shift 2;;
    --image) IMAGE="$2"; shift 2;;
    --identity) IDENTITY="$2"; shift 2;;
    --allow) ALLOW+=("$2"); shift 2;;
    --now) NOW="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    --titles-only) TITLES_ONLY=1; shift;;
    -h|--help) sed -n '2,30p' "$0"; exit 0;;
    -*) echo "unknown option $1" >&2; exit 2;;
    *) DB="$1"; shift;;
  esac
done
[ -n "${DB:-}" ] || { echo "usage: scripts/realdata-check.sh [options] <db>" >&2; exit 2; }

PG="${PG:-postgresql://insight:insight@postgres:5432}"
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
psql_admin() { docker run --rm --network "$NETWORK" "$IMAGE" psql -q -At "$PG/postgres" -c "$1"; }

cleanup() {
  docker rm -f "$RUN_ID-base" "$RUN_ID-head" "$RUN_ID-dump" "$RUN_ID-report" "$RUN_ID-restore" >/dev/null 2>&1 || true   # by name only
  if [ "$KEEP" != "1" ] && [ "$TITLES_ONLY" != "1" ]; then
    psql_admin "DROP DATABASE IF EXISTS $SCRATCH_A" >/dev/null 2>&1 || true
    psql_admin "DROP DATABASE IF EXISTS $SCRATCH_B" >/dev/null 2>&1 || true
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
  run_side base "$DB" -e NO_JOB=1 -e PARTS=posts,links -e PARTS_ONLY=1 &
  run_side head "$DB" -e NO_JOB=1 -e PARTS=posts,links -e PARTS_ONLY=1 &
  wait
else
  # ---- scratch copies: one dump, one restore, one template copy --------------------------------
  say "dump $DB (read-only)"
  docker run --rm --name "$RUN_ID-dump" --network "$NETWORK" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" "$IMAGE" pg_dump -Fc -Z1 -f /work/copy.dump "$PG/$DB"
  # One restore (its index builds are most of the time), then a file copy of it: no second WAL-logged load.
  say "restore into $SCRATCH_A"
  psql_admin "DROP DATABASE IF EXISTS $SCRATCH_A" ; psql_admin "DROP DATABASE IF EXISTS $SCRATCH_B"
  psql_admin "CREATE DATABASE $SCRATCH_A"
  docker run --rm --name "$RUN_ID-restore" --network "$NETWORK" --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$WORK:/work" "$IMAGE" \
    pg_restore -j 8 --no-owner --no-privileges -d "$PG/$SCRATCH_A" /work/copy.dump 2> "$WORK/restore.log" || true
  grep -v -e transaction_timeout -e "errors ignored" -e "^Command was" "$WORK/restore.log" | grep -i error \
    && { echo "restore failed" >&2; exit 2; } || true
  say "copy $SCRATCH_A to $SCRATCH_B (file copy)"
  psql_admin "CREATE DATABASE $SCRATCH_B TEMPLATE $SCRATCH_A STRATEGY FILE_COPY"
  rm -f "$WORK/copy.dump"

  say "both versions at once: migrate, full story job, snapshot, invariants, cases, job checks"
  run_side base "$SCRATCH_A" > "$WORK/base.log" 2>&1 &
  pid_base=$!
  run_side head "$SCRATCH_B" ${IDENTITY:+-e IDENTITY="$IDENTITY"} > "$WORK/head.log" 2>&1 &
  pid_head=$!
  wait $pid_base || true
  wait $pid_head || true
  cat "$WORK/base.log" "$WORK/head.log"
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
{ cat "$WORK/report.md"; echo; echo "Took ${elapsed} s ($(( elapsed / 60 )) min $(( elapsed % 60 )) s), image $IMAGE."; } > "$REPORT"
mkdir -p "${REPORT%.md}"
for side in base head; do
  for f in deploy.json invariants.json jobs.json cases.json job.json; do
    [ -f "$WORK/$side/$f" ] && cp "$WORK/$side/$f" "${REPORT%.md}/$side-$f"
  done
done
[ -f "$WORK/diff-counts.json" ] && cp "$WORK/diff-counts.json" "${REPORT%.md}/"
say "took ${elapsed} s; report: $REPORT"
exit $verdict
