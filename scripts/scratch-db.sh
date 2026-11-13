#!/usr/bin/env bash
# The scratch Postgres (v10.17): a second, disposable server for everything that is copied, migrated, tested and
# thrown away - the test runs' databases, the real-data check's scratch copies, the prepared copies - so that none of
# it competes with the durable server (insight-db, which keeps only the owner's originals: insight, insight_lab,
# insight_server_1105*, insight_preview...).
#
#   scripts/scratch-db.sh up        start it (made the first time; idempotent; prints its DSN)
#   scripts/scratch-db.sh status    is it up, its settings, its databases and their sizes
#   scripts/scratch-db.sh psql [db] a psql inside it
#   scripts/scratch-db.sh recreate  remove it and its volume, then start it empty (everything on it is rebuildable)
#
# Tuned for throwaway data: fsync, synchronous_commit and full_page_writes off (a crash can corrupt it: rebuild),
# 8 GB of shared buffers, checkpoints every 30 min or 16 GB of WAL (a CREATE/DROP DATABASE's forced checkpoint only
# writes buffers to the OS, never waits for the disk), 400 connections, parallel workers for the 32 cores, a large
# /dev/shm for parallel builds. Same image as insight-db (pgvector/pgvector:pg15), on the compose network as
# insight-scratch-db:5432, its data in the docker volume insight-scratch-db-data (survives a restart, not a crash).
#
# Env: SCRATCH_CONTAINER (insight-scratch-db), NETWORK (insight_insight-network), SCRATCH_VOLUME (insight-scratch-db-data).
set -euo pipefail
NAME="${SCRATCH_CONTAINER:-insight-scratch-db}"
NETWORK="${NETWORK:-insight_insight-network}"
VOLUME="${SCRATCH_VOLUME:-insight-scratch-db-data}"
IMAGE="pgvector/pgvector:pg15"
DSN="postgresql://insight:insight@${NAME}:5432"

running() { [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = true ]; }
ready() {   # the real server (pid 1), not the first start's init server
  docker exec "$NAME" pg_isready -q -U insight -d postgres 2>/dev/null \
    && [ "$(docker exec "$NAME" head -1 /var/lib/postgresql/data/postmaster.pid 2>/dev/null)" = 1 ]
}

up() {
  if ! running; then
    if docker inspect "$NAME" >/dev/null 2>&1; then
      docker start "$NAME" >/dev/null
    else
      echo "==> making $NAME (volume $VOLUME, network $NETWORK)" >&2
      docker run -d --name "$NAME" --restart unless-stopped --network "$NETWORK" \
        --shm-size 8g -v "$VOLUME:/var/lib/postgresql/data" \
        -e POSTGRES_USER=insight -e POSTGRES_PASSWORD=insight -e POSTGRES_DB=postgres \
        --label insight.scratch=1 "$IMAGE" postgres \
        -c fsync=off -c synchronous_commit=off -c full_page_writes=off \
        -c shared_buffers=8GB -c effective_cache_size=48GB -c work_mem=32MB -c maintenance_work_mem=2GB \
        -c max_wal_size=16GB -c min_wal_size=2GB -c checkpoint_timeout=30min -c wal_level=minimal -c max_wal_senders=0 \
        -c max_connections=400 -c max_worker_processes=32 -c max_parallel_workers=24 \
        -c max_parallel_workers_per_gather=4 -c max_parallel_maintenance_workers=8 \
        -c random_page_cost=1.1 -c effective_io_concurrency=200 -c autovacuum_max_workers=6 >/dev/null
    fi
  fi
  for _ in $(seq 1 60); do ready && break; sleep 1; done
  ready || { echo "scratch-db: $NAME did not become ready" >&2; docker logs --tail 20 "$NAME" >&2; exit 1; }
  docker exec "$NAME" psql -X -q -U insight -d postgres -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null 2>&1 || true
  echo "$DSN"
}

case "${1:-up}" in
  up) up;;
  status)
    if running; then
      echo "$NAME: up ($DSN)"
      docker exec "$NAME" psql -X -At -U insight -d postgres -c "SELECT name || '=' || setting FROM pg_settings
        WHERE name IN ('fsync','synchronous_commit','full_page_writes','shared_buffers','max_wal_size','checkpoint_timeout','max_connections')"
      docker exec "$NAME" psql -X -At -U insight -d postgres -c "SELECT datname || E'\t' || pg_size_pretty(pg_database_size(datname))
        FROM pg_database WHERE NOT datistemplate ORDER BY 1"
    else echo "$NAME: not running (scripts/scratch-db.sh up)"; fi;;
  psql) shift; up >/dev/null; docker exec -it "$NAME" psql -U insight -d "${1:-postgres}";;
  recreate)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME" >/dev/null 2>&1 || true
    up;;
  *) sed -n '2,18p' "$0"; exit 2;;
esac
