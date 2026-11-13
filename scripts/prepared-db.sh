#!/usr/bin/env bash
# Prepared copies (v10.17 workflow): named databases of the real-data snapshots, already migrated and backfilled, that
# an agent clones in seconds instead of copying a stale snapshot and re-running migrations and backfills each time.
#
#   scripts/prepared-db.sh list                         the prepared copies and their stamps
#   scripts/prepared-db.sh clone <set> <newdb>          a scratch copy of prep_<set> (CREATE DATABASE ... TEMPLATE)
#   scripts/prepared-db.sh drop <db>                    drop a scratch copy (or a prepared copy: --force)
#   scripts/prepared-db.sh refresh <set> [--ref REF]    only the NEW migrations and backfills, on a copy then swapped in
#   scripts/prepared-db.sh build <set> [--ref REF] [--rebuild|--remirror]   build prep_<set> (an existing one is
#                                                       refreshed unless --rebuild; --remirror copies the original again)
#   scripts/prepared-db.sh stamp <db>                   the stamp a copy (or a clone of one) carries
#   scripts/prepared-db.sh adopt <set> <db>             make prep_<set> a copy of <db> on insight-db (its stamp kept)
#
# Everything here lives on the scratch Postgres (insight-scratch-db, scripts/scratch-db.sh, started when not running):
# the prepared copies, their clones, and src_<original>, each original copied over once (pg_dump | pg_restore) and
# made again only by `build <set> --remirror`. insight-db, which holds the originals, is only read, by that pg_dump.
#
# Sets: lab (insight_lab: 41.6k posts to 30 Oct), server1105 (insight_server_1105: 49.4k posts to 5 Nov),
# mxreal (insight_server_1105_mxreal: the same with real Mark X answers), scale (server-sized: prep_mxreal
# inflated by scripts/prep/scale.py to ~148k posts, ~1M tasks and calls, ~830k mentions, ~130k vectors).
#
# REF: a commit, branch or tag whose backend's migrations and backfills are applied; default the working tree of
# this checkout. The originals (insight_lab, insight_server_1105* on insight-db) are only ever read (pg_dump).
# A prepared copy refuses connections (ALLOW_CONNECTIONS false): nobody can hold it open, so a clone never waits.
# Its stamp: the database's comment (one JSON line, `list`) and the table prep.stamp inside it (and every clone).
#
# Env: ENV_FILE (the .env the backend runs with; default ./.env or the main checkout's), PGCONTAINER (the scratch
# server's container, insight-scratch-db), SRC_CONTAINER (insight-db, where the originals are), NETWORK
# (insight_insight-network), STRATEGY (the copy strategy, FILE_COPY: on the scratch server its checkpoint never waits
# for the disk; on insight-db a FILE_COPY waited 90 s and more behind other writers, WAL_LOG 22 s, for prep_lab).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NETWORK="${NETWORK:-insight_insight-network}"
PGCONTAINER="${PGCONTAINER:-${SCRATCH_CONTAINER:-insight-scratch-db}}"
SRC_CONTAINER="${SRC_CONTAINER:-insight-db}"
PG_SRC="postgresql://insight:insight@postgres:5432"
STRATEGY="${STRATEGY:-FILE_COPY}"
APP=prepared-db
STATE="${XDG_CACHE_HOME:-$HOME/.cache}/insight-prep"   # lock files and a run's temporary trees (never /tmp)
mkdir -p "$STATE"

say() { echo "==> $(date +%H:%M:%S) $*" >&2; }
case "${1:-}" in -h|--help|help|"") ;; *) PG="$("$ROOT/scripts/scratch-db.sh" up)";; esac
die() { echo "prepared-db: $*" >&2; exit 2; }
# psql as the admin role inside the database container (no container to start: ~0.1 s a call)
sql() { local db="$1"; shift; docker exec -i -e PGAPPNAME="$APP" -e PGOPTIONS="-c client_min_messages=warning" "$PGCONTAINER" psql -X -q -At -v ON_ERROR_STOP=1 -U insight -d "$db" "$@"; }
admin() { sql postgres -c "$1"; }
exists() { [ "$(admin "SELECT 1 FROM pg_database WHERE datname = '$1'")" = 1 ]; }
valid_name() { [[ "$1" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || die "bad database name: $1"; }

source_of() {   # the original a set is made from (on insight-db); for scale, the prepared copy it inflates
  case "$1" in
    lab) echo insight_lab;; server1105) echo insight_server_1105;; mxreal) echo insight_server_1105_mxreal;;
    scale) echo prep_mxreal;;
    *) die "unknown set $1 (lab, server1105, mxreal, scale)";;
  esac
}

# copy_over <db on insight-db> <new db on the scratch server>: one pg_dump (read-only) and a parallel pg_restore
copy_over() {
  local src="$1" dst="$2" work
  work="$(mktemp -d "$STATE/copy.XXXXXX")"
  IMAGE="$(deps_image)"
  admin "CREATE DATABASE $dst"
  docker run --rm --network "$NETWORK" --user "$(id -u):$(id -g)" -e HOME=/tmp -e PGAPPNAME="$APP" -v "$work:/work" "$IMAGE" \
    sh -c "pg_dump -Fc -Z1 -f /work/copy.dump '$PG_SRC/$src' && pg_restore -j 8 --no-owner --no-privileges -d '$PG/$dst' /work/copy.dump" \
    2> "$work/restore.log" || true
  if [ ! -s "$work/copy.dump" ] || grep -v -e transaction_timeout -e "errors ignored" -e "^Command was" "$work/restore.log" | grep -qi error; then
    cat "$work/restore.log" >&2; rm -rf "$work"; die "copying $src over failed"
  fi
  rm -rf "$work"
}

# The scratch server's copy of an original (src_<original>), made once (--remirror: again).
mirror() {   # mirror <original> [--remirror]
  local src="$1" m="src_$1"
  if exists "$m" && [ "${2:-}" != --remirror ]; then echo "$m"; return; fi
  docker exec "$SRC_CONTAINER" true 2>/dev/null || die "$SRC_CONTAINER (where $src is) is not running"
  exists "$m" && admin "DROP DATABASE $m WITH (FORCE)" >/dev/null
  exists "${m}__copying" && admin "DROP DATABASE ${m}__copying WITH (FORCE)" >/dev/null
  local t0; t0=$(date +%s)
  say "copying $src over from $SRC_CONTAINER (pg_dump | pg_restore, once)"
  copy_over "$src" "${m}__copying"
  admin "ALTER DATABASE ${m}__copying RENAME TO $m"
  admin "COMMENT ON DATABASE $m IS \$j\$$(P_SRC="$src" python3 -c 'import json, os, datetime; print(json.dumps({"mirror_of": os.environ["P_SRC"], "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}))')\$j\$"
  admin "ALTER DATABASE $m ALLOW_CONNECTIONS false"
  say "$m: copied over in $(( $(date +%s) - t0 )) s"
  echo "$m"
}

env_file() {
  if [ -n "${ENV_FILE:-}" ]; then echo "$ENV_FILE"; elif [ -f "$ROOT/.env" ]; then echo "$ROOT/.env"
  else echo "$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")/.env"; fi
}

# The image the copies' code runs in: the dependencies only (requirements.txt and the Dockerfile; the code is
# mounted over /app), built once per change of either.
deps_image() {
  local h; h="$(cat "$ROOT/backend/requirements.txt" "$ROOT/backend/Dockerfile" | sha256sum | cut -c1-12)"
  local tag="insight-backend:deps-$h"
  if ! docker image inspect "$tag" >/dev/null 2>&1; then
    say "building $tag (dependencies changed)"; docker build -q -t "$tag" "$ROOT/backend" >/dev/null
  fi
  echo "$tag"
}

# CREATE DATABASE <new> TEMPLATE <src>. Postgres refuses while anyone is connected to <src>: wait (up to WAIT s),
# ending only connections this script opened (application_name prepared-db); never another's.
create_from() {
  local src="$1" new="$2" wait="${WAIT:-300}" t0 out
  t0=$(date +%s)
  while :; do
    if out="$(admin "CREATE DATABASE $new TEMPLATE $src STRATEGY $STRATEGY" 2>&1)"; then return 0; fi
    case "$out" in
      *"is being accessed by other users"*)
        admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$src' AND application_name = '$APP' AND pid <> pg_backend_pid()" >/dev/null
        if [ $(( $(date +%s) - t0 )) -ge "$wait" ]; then
          echo "$out" >&2
          admin "SELECT 'in use by: ' || coalesce(application_name, '?') || ' ' || coalesce(client_addr::text, 'local') FROM pg_stat_activity WHERE datname = '$src'" >&2
          die "$src stayed in use for ${wait} s"
        fi
        sleep 2;;
      *) echo "$out" >&2; die "could not create $new from $src";;
    esac
  done
}

lock() {   # one build/refresh of a set at a time
  exec 9>"$STATE/$1.lock"
  flock -n 9 || { say "waiting for another build or refresh of $1"; flock 9; }
}

# The ref's backend into a fresh directory: git archive of REF, or this checkout's working tree.
export_tree() {
  local ref="$1" dir="$2"
  if [ -n "$ref" ]; then git -C "$ROOT" archive "$ref" backend | tar -x -C "$dir"
  else tar -C "$ROOT" --exclude='__pycache__' --exclude='backend/logs' --exclude='*.log' -cf - backend | tar -x -C "$dir"; fi
}
ref_label() {
  local ref="$1"
  if [ -n "$ref" ]; then git -C "$ROOT" rev-parse --short=12 "$ref^{commit}"
  else
    local c; c="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
    if [ -n "$(git -C "$ROOT" status --porcelain -- backend)" ]; then echo "$c+dirty"; else echo "$c"; fi
  fi
}

in_image() {   # in_image <db> <workdir> cmd...: the exported backend at /app (read-only), /prep, the work dir writable
  local db="$1" work="$2"; shift 2
  docker run --rm --network "$NETWORK" --env-file "$(env_file)" --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -e DATABASE_URL="$PG/$db" -e PGAPPNAME="$APP" -e INSIGHT_MARKX=1 -e PYTHONHASHSEED=0 -e PYTHONPATH=/app \
    -e PYTHONDONTWRITEBYTECODE=1 -v "$work/backend:/app:ro" -v "$ROOT/scripts/prep:/prep:ro" -v "$work:/work" -w /work \
    "$IMAGE" "$@"
}

# migrate + backfills (+ the scale inflation the first time) over <db>, with REF's code; writes the stamp
update_db() {   # update_db <set> <db> <ref> <fresh:0|1> <previous stamp json or {}>
  local set="$1" db="$2" ref="$3" fresh="$4" prev="$5"
  local work; work="$(mktemp -d "$STATE/work.XXXXXX")"
  trap 'rm -rf "'"$work"'"' RETURN
  export_tree "$ref" "$work"
  local label; label="$(ref_label "$ref")"
  IMAGE="$(deps_image)"
  local before after t0 t_mig t_bf t_inf=0
  before="$(sql "$db" -c "SELECT CASE WHEN to_regclass('schema_migrations') IS NULL THEN '' ELSE (SELECT string_agg(version, ',' ORDER BY version) FROM schema_migrations) END")"
  local snap='{}'   # what the source snapshot held: read on the fresh copy (the original is never connected to)
  if [ "$set" != scale ]; then snap="$(snapshot_of "$db")"; fi   # used when the stamp has none yet
  t0=$(date +%s)
  say "$db: migrate to $label"
  in_image "$db" "$work" python -m insight_core.db.migrate > "$work/migrate.log" 2>&1 || { tail -20 "$work/migrate.log" >&2; die "migrate failed on $db"; }
  t_mig=$(( $(date +%s) - t0 ))
  after="$(sql "$db" -c "SELECT string_agg(version, ',' ORDER BY version) FROM schema_migrations")"
  local applied; applied="$(comm -13 <(tr ',' '\n' <<<"$before" | sort) <(tr ',' '\n' <<<"$after" | sort) | paste -sd, -)"
  local extra; extra="$(comm -23 <(tr ',' '\n' <<<"$after" | sort) <(ls "$work/backend/insight_core/db/migrations" | grep '\.sql$' | sort) | paste -sd, -)"
  [ -n "$extra" ] && say "note: $db has migrations $label does not know: $extra"
  say "$db: $( [ -n "$applied" ] && echo "applied $(tr ',' '\n' <<<"$applied" | wc -l) migration(s)" || echo "no new migration") in ${t_mig} s"

  if [ "$set" = scale ] && [ "$fresh" = 1 ]; then
    t0=$(date +%s)
    say "$db: inflating to server scale (scripts/prep/scale.py)"
    in_image "$db" "$work" python /prep/scale.py ${SCALE_ARGS:-} > "$work/scale.out" 2> >(tee "$work/scale.log" >&2) \
      || { tail -30 "$work/scale.log" >&2; die "the scale inflation failed on $db"; }
    say "$db: $(tail -1 "$work/scale.out")"
    t_inf=$(( $(date +%s) - t0 ))
  fi

  t0=$(date +%s)
  say "$db: backfills ($label's code)"
  in_image "$db" "$work" python /prep/backfills.py > "$work/backfills.out" 2> "$work/backfills.log" \
    || { tail -30 "$work/backfills.log" >&2; die "a backfill failed on $db (above): left as it is, the prepared copy unchanged"; }
  t_bf=$(( $(date +%s) - t0 ))
  local bf; bf="$(tail -1 "$work/backfills.out")"
  [ -n "$bf" ] || bf='{}'
  say "$db: backfills in ${t_bf} s: $bf"

  local src; src="$(source_of "$set")"
  local stamp
  stamp="$(P_PREV="$prev" P_SNAP="$snap" P_SET="$set" P_SRC="$src" P_REF="${ref:-working tree}" P_COMMIT="$label" \
           P_AFTER="$after" P_APPLIED="$applied" P_BF="$bf" P_SEC="{\"migrate\": $t_mig, \"backfills\": $t_bf, \"inflate\": $t_inf}" \
           python3 "$ROOT/scripts/prep/stamp.py")"
  sql "$db" -c "CREATE SCHEMA IF NOT EXISTS prep" -c "CREATE TABLE IF NOT EXISTS prep.stamp (at timestamptz PRIMARY KEY DEFAULT now(), stamp jsonb NOT NULL)" \
            -c "INSERT INTO prep.stamp (stamp) VALUES (\$j\$${stamp}\$j\$::jsonb)" -c "ANALYZE"
  STAMP_JSON="$stamp"
}

snapshot_of() {   # what a snapshot holds (read on its fresh copy)
  local src="$1"
  sql "$src" -c "SELECT json_build_object('posts', (SELECT count(*) FROM posts),
      'last_fetched', (SELECT max(fetched_at) FROM posts), 'migrations', (SELECT count(*) FROM schema_migrations),
      'last_migration', (SELECT max(version) FROM schema_migrations))" 2>/dev/null || echo '{}'
}

stamp_of() { admin "SELECT coalesce(shobj_description(oid, 'pg_database'), '') FROM pg_database WHERE datname = '$1'"; }

seal() {   # seal <building db> <prep db>: refuse connections, stamp as the comment, swap in
  local building="$1" target="$2" stamp="$3"
  admin "COMMENT ON DATABASE $building IS \$j\$${stamp}\$j\$"
  admin "ALTER DATABASE $building ALLOW_CONNECTIONS false"
  admin "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$building' AND application_name = '$APP'" >/dev/null
  if exists "$target"; then
    admin "ALTER DATABASE $target RENAME TO ${target}__old_$$"
    admin "ALTER DATABASE $building RENAME TO $target"
    # the old copy dropped in the background: a DROP DATABASE waits for a checkpoint (minutes on a busy disk)
    docker exec -d -e PGAPPNAME="$APP" "$PGCONTAINER" psql -X -q -U insight -d postgres -c "DROP DATABASE IF EXISTS ${target}__old_$$ WITH (FORCE)"
  else
    admin "ALTER DATABASE $building RENAME TO $target"
  fi
}

cmd_build() {
  local set="$1"; shift; local ref="" rebuild=0 remirror=""
  while [ $# -gt 0 ]; do
    case "$1" in --ref) ref="$2"; shift 2;; --rebuild) rebuild=1; shift;; --remirror) remirror=--remirror; rebuild=1; shift;;
                 *) die "unknown option $1";; esac
  done
  source_of "$set" >/dev/null
  local target="prep_$set"
  if exists "$target" && [ "$rebuild" = 0 ]; then cmd_refresh "$set" ${ref:+--ref "$ref"}; return; fi
  lock "$set"
  local src; src="$(source_of "$set")"
  [ "$set" = scale ] && ! exists prep_mxreal && { say "scale is built from prep_mxreal: building it first"; cmd_build mxreal ${ref:+--ref "$ref"}; }
  [ "$set" = scale ] || src="$(mirror "$src" $remirror)"
  exists "$src" || die "no source database $src"
  local building="${target}__building" t0; t0=$(date +%s)
  exists "$building" && admin "DROP DATABASE $building WITH (FORCE)"
  say "copy $src to $building"
  create_from "$src" "$building"
  admin "ALTER DATABASE $building ALLOW_CONNECTIONS true" >/dev/null
  local prev='{}'
  # scale's source is a prepared copy: its own stamp is kept as where it came from
  [ "$set" = scale ] && prev="$(python3 -c 'import json,sys; s=json.loads(sys.argv[1] or "{}"); print(json.dumps({"source":"prep_mxreal","source_snapshot":{"from":s.get("source_snapshot"),"prep_mxreal_commit":s.get("commit")}}))' "$(stamp_of prep_mxreal)")"
  update_db "$set" "$building" "$ref" 1 "$prev"
  seal "$building" "$target" "$STAMP_JSON"
  say "built $target in $(( $(date +%s) - t0 )) s"
}

cmd_refresh() {
  local set="$1"; shift; local ref=""
  while [ $# -gt 0 ]; do case "$1" in --ref) ref="$2"; shift 2;; *) die "unknown option $1";; esac; done
  source_of "$set" >/dev/null
  local target="prep_$set"
  exists "$target" || die "$target does not exist: build it (scripts/prepared-db.sh build $set)"
  lock "$set"
  local building="${target}__building" t0; t0=$(date +%s)
  exists "$building" && admin "DROP DATABASE $building WITH (FORCE)"
  create_from "$target" "$building"
  admin "ALTER DATABASE $building ALLOW_CONNECTIONS true" >/dev/null
  update_db "$set" "$building" "$ref" 0 "$(stamp_of "$target")"
  seal "$building" "$target" "$STAMP_JSON"
  say "refreshed $target in $(( $(date +%s) - t0 )) s"
}

cmd_clone() {
  local set="$1" new="$2"; valid_name "$new"
  local src="prep_$set"; [[ "$set" == prep_* ]] && src="$set"
  exists "$src" || die "$src does not exist (scripts/prepared-db.sh build ${set#prep_})"
  [[ "$new" == prep_* || "$new" == insight || "$new" == insight_lab || "$new" == insight_server_1105* ]] && die "refusing to create $new"
  exists "$new" && die "$new exists already (scripts/prepared-db.sh drop $new)"
  local t0; t0=$(date +%s%N)
  create_from "$src" "$new"
  admin "COMMENT ON DATABASE $new IS \$j\$$(python3 -c 'import json,sys; s=json.loads(sys.argv[1] or "{}"); print(json.dumps({"clone_of": sys.argv[2], "commit": s.get("commit"), "last_migration": s.get("last_migration")}))' "$(stamp_of "$src")" "$src")\$j\$"
  say "$new: a copy of $src in $(( ($(date +%s%N) - t0) / 1000000 )) ms"
  echo "$PG/$new"
}

cmd_drop() {
  local db="$1" force="${2:-}"; valid_name "$db"
  case "$db" in
    insight|insight_lab|insight_server_1105|insight_server_1105_mxreal|postgres|template0|template1) die "refusing to drop $db";;
    prep_*) [ "$force" = --force ] || die "$db is a prepared copy: pass --force to drop it";;
  esac
  exists "$db" || { say "$db does not exist"; return 0; }
  if [ "${WAIT_DROP:-0}" = 1 ] || [[ "$db" == prep_* ]]; then
    admin "DROP DATABASE $db WITH (FORCE)"; say "dropped $db"
  else   # detached: a DROP DATABASE waits for a checkpoint, minutes on a busy disk (WAIT_DROP=1 waits)
    docker exec -d -e PGAPPNAME="$APP" "$PGCONTAINER" psql -X -q -U insight -d postgres -c "DROP DATABASE IF EXISTS $db WITH (FORCE)"
    say "dropping $db (in the background)"
  fi
}

cmd_adopt() {   # adopt <set> <db on insight-db>: a database made there (before v10.17) copied over as prep_<set>
  local set="$1" src="$2"; valid_name "$src"; source_of "$set" >/dev/null
  local target="prep_$set" building="prep_${set}__building"
  [ "$(docker exec "$SRC_CONTAINER" psql -X -At -U insight -d postgres -c "SELECT datallowconn FROM pg_database WHERE datname = '$src'")" = t ] \
    || die "$src on $SRC_CONTAINER does not exist or refuses connections (ALTER DATABASE $src ALLOW_CONNECTIONS true, if it is yours)"
  lock "$set"
  exists "$building" && admin "DROP DATABASE $building WITH (FORCE)"
  local t0; t0=$(date +%s)
  say "copying $src over as $target"
  copy_over "$src" "$building"
  local stamp; stamp="$(sql "$building" -c "SELECT stamp FROM prep.stamp ORDER BY at DESC LIMIT 1" 2>/dev/null || true)"
  [ -n "$stamp" ] || stamp="{\"set\": \"$set\", \"adopted_from\": \"$src\"}"
  seal "$building" "$target" "$stamp"
  say "adopted $src as $target in $(( $(date +%s) - t0 )) s"
}

cmd_list() {
  admin "SELECT datname || E'\t' || pg_size_pretty(pg_database_size(datname)) || E'\t' || coalesce(shobj_description(oid, 'pg_database'), '')
           FROM pg_database WHERE datname LIKE 'prep\\_%' ORDER BY 1" | python3 "$ROOT/scripts/prep/list.py"
}

cmd_stamp() {
  local db="$1"
  local c; c="$(stamp_of "$db")"; [ -n "$c" ] && echo "$c"
  if [ "$(admin "SELECT datallowconn FROM pg_database WHERE datname = '$db'")" = t ]; then
    sql "$db" -c "SELECT stamp FROM prep.stamp ORDER BY at DESC LIMIT 1" 2>/dev/null || true
  fi
}

case "${1:-}" in
  list) cmd_list;;
  build) shift; [ $# -ge 1 ] || die "build <set>"; cmd_build "$@";;
  refresh) shift; [ $# -ge 1 ] || die "refresh <set>"; cmd_refresh "$@";;
  clone) shift; [ $# -eq 2 ] || die "clone <set> <newdb>"; cmd_clone "$@";;
  drop) shift; [ $# -ge 1 ] || die "drop <db>"; cmd_drop "$@";;
  stamp) shift; [ $# -eq 1 ] || die "stamp <db>"; cmd_stamp "$1";;
  adopt) shift; [ $# -eq 2 ] || die "adopt <set> <db>"; cmd_adopt "$@";;
  -h|--help|help|"") sed -n '2,31p' "$0";;
  *) die "unknown command $1";;
esac
