#!/bin/sh
# One version's checks over its own scratch copy (issue 0075; called by scripts/realdata-check.sh inside a
# container: the version's code at /app, its outputs in the current directory).
#   side.sh <scratch dsn> <name> [now]     env: IDENTITY, CASES, NO_JOB, PARTS, PARTS_ONLY
# Writes job.json, snapshot.json, invariants.json, jobs.json, cases.json and their logs; never prints a DSN.
set -u
DSN="$1"; NAME="$2"; NOW="${3:-}"
NOWARG=""; [ -n "$NOW" ] && NOWARG="--now $NOW"
step() { echo "[$NAME] $(date +%H:%M:%S) $*"; }

if [ "${NO_JOB:-0}" != "1" ]; then
  step "migrate"
  DATABASE_URL="$DSN" python -m insight_core.db.migrate > migrate.log 2>&1 || { step "migrate FAILED (migrate.log)"; exit 2; }
  step "story job (full)"
  python -m insight_core.checks.job --db "$DSN" $NOWARG > job.json 2> job.log || { step "job FAILED (job.log)"; exit 2; }
fi
step "snapshot"
python -m insight_core.checks.snapshot --db "$DSN" --out snapshot.json --parts "${PARTS:-posts,links,stories,news,classics,discover}" $NOWARG > snapshot.log 2>&1 \
  || step "snapshot FAILED (snapshot.log)"
[ "${PARTS_ONLY:-0}" = "1" ] && exit 0
step "invariants"
python -m insight_core.scripts.check_invariants --db "$DSN" --json invariants.json $NOWARG > invariants.log 2>&1 \
  || step "invariants FAILED (invariants.log)"
if [ -n "${CASES:-}" ] && [ -f "$CASES" ]; then
  step "cases"
  python -m insight_core.scripts.check_cases --db "$DSN" --cases "$CASES" --json cases.json $NOWARG > cases.log 2>&1
  echo $? > cases.exit
fi
if [ "${NO_JOB:-0}" != "1" ]; then
  step "job checks (a second rebuild; ${IDENTITY:-the incremental job's identity check})"
  python -m insight_core.checks.job_checks --db "$DSN" ${IDENTITY:+--identity "$IDENTITY"} --json jobs.json $NOWARG > jobs.log 2>&1 \
    || step "job checks FAILED (jobs.log)"
fi
step "done"
