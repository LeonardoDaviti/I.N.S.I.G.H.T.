# INSIGHT deployment guide (Mark IX)

INSIGHT runs as four Docker Compose services from `docker-compose.yml`. The README has the
feature overview; this file covers deploying, updating and troubleshooting.

| Service | Container | What it does |
| --- | --- | --- |
| `postgres` | `insight-db` | PostgreSQL 15 with pgvector. Internal to the Docker network only. |
| `backend` | `insight-api` | FastAPI on port 8000 (`BACKEND_PORT` on the host, `127.0.0.1` only). Runs migrations on start, and imports `sources.json` once per database (add-only). |
| `ingestion` | `insight-ingestion` | The scheduler (`scripts/run_scheduler.py`): an ingestion tick every `ingest_tick_minutes`, daily work every `interval_hours`; Mark X's jobs when it is on; the API watchdog. |
| `frontend` | `insight-frontend` | The built React app behind Nginx (`FRONTEND_PORT`), proxying `/api` to the backend. |

The API runs as two uvicorn processes (`API_WORKERS`, default 2; issue 0112 Decided 11), so one stuck
request or one process hung on its CPU can't freeze the reader: uvicorn replaces a process that stops
answering its ping. They run under a small supervisor (`scripts/api_supervisor.py`) that does the start's
work once per container: it closes the jobs a restart ended before any process serves, then runs the
search refill and the start's story job in a child process. What one process used to keep in memory is
shared: a Telegram sign-in's waiting code (encrypted, in the database), an export's progress (a file per
token), a Mark X worker's last contact (`mx_workers`), an archive's start (one lock). `API_WORKERS=1`
runs one process; anything that isn't a number of 1 or more stops the start with a line saying why.

## Networking

- All four services share one bridge network, `insight-network`. The API and the scheduler
  reach the database as `postgres:5432`. PostgreSQL has no host port.
- The API's port is published on `127.0.0.1` only (issue 0071): it has no login and can delete
  sources, so only the machine it runs on reaches it. The app reaches it through the frontend's
  nginx (`/api` on `FRONTEND_PORT`), which proxies to `backend:8000` on the compose network.
  Leave `VITE_API_URL` empty: a build that points the browser at `http://<host>:8000` can't reach it.
  From another machine, use a tunnel: `ssh -L 8000:localhost:8000 <host>`.
- The Telegram RSS bridge and Nitter are self-hosted outside this compose file. Sources reach
  them as `https://telegram.local/...` and `https://nitter.local/...`, so those names must
  resolve from inside the `backend` and `ingestion` containers.
- Outgoing requests (feeds, Add source, page watch, saved pages, Discover, research, `/api/media`) go
  only to hosts that resolve to public addresses (issue 0187): a private, loopback, link-local
  (169.254.169.254), CGNAT/Tailscale (100.64/10) or Docker-network address is refused, on every
  redirect too, so a pasted address can't reach the database, the API or the LAN. The exceptions
  are the bridges: `telegram.local`, `nitter.local`, and every host named in `NITTER_HOSTS`,
  `TELEGRAM_RSS_HOSTS`, `INSIGHT_MEDIA_PRIVATE_HOSTS` or `RSS_SKIP_TLS_VERIFY_HOSTS`. A feed on another
  LAN host (an RSSHub, a FreshRSS) needs its host in `INSIGHT_MEDIA_PRIVATE_HOSTS`. No `HTTP_PROXY` is
  used for them.
- A bridge on a LAN address is fetched without TLS verification (self-signed certificates); other
  `.local` hosts are no longer skipped automatically. Add any other host to `RSS_SKIP_TLS_VERIFY_HOSTS`.
- A fetched body is read up to 10 MB, unpacked or not; a larger one fails that fetch.
- Never use `localhost` in a source URL: inside a container it is the container itself.

## Prerequisites

- Docker with the Compose plugin.
- For development without Docker: Python 3.12, PostgreSQL 15, Node.js 20.19+ (or 22.12+) and npm 10.

## First deploy

```bash
cp .env.example .env        # then edit it: DB_*, ports, CORS, intervals (no API keys)
docker compose up -d --build
docker compose ps
docker compose logs -f backend ingestion
```

On start, both `backend` and `ingestion` run `insight_core/db/migrate.py`. The migration runner
takes a PostgreSQL advisory lock, so the two containers can start together safely. Applied
migrations are recorded and never re-run.

Open `http://<host>:${FRONTEND_PORT}`. `/` is the reader. API docs are at
`http://localhost:${BACKEND_PORT}/docs` on the host (or through an SSH tunnel, see Networking).

### API keys and sessions: Sources → Connections

No API key is read from `.env`. Add them in the app under **Sources → Connections**; they are
stored encrypted in the `credentials` table with the key in the `insight_secrets` volume (or
`INSIGHT_SECRET_KEY`). Back that volume up with the database.

- **Telegram** (bare-handle channels over MTProto, optional): the API ID and hash from
  https://my.telegram.org, then sign in there with your phone number. The session is saved
  encrypted; until then those sources show as unavailable in the health table, not as failing.
- **Substack** (paid posts in full, optional): the `substack.sid` cookie.

Upgrading from a `.env` that still has `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` or `SUBSTACK_SID`?
Copy them into the store once, then delete those lines from `.env`:

```bash
docker compose exec backend python -m insight_core.scripts.import_env_secrets
```

It prints only the names it stored or skipped (empty values, template placeholders, values
already stored), never a value. An older Telegram session file is not imported: sign in again.

## Your sources: the database is the truth

Your sources live in the database. `backend/insight_core/config/sources.json` is their export,
rewritten after each change in the app (to a temporary file, then renamed over it). Nothing
deletes a source because a file lacks it: a source is removed only by Remove in the app.

- **A new install** starts with no sources, or with your file: copy
  `backend/insight_core/config/sources.example.json` to `sources.json` beside it and edit it before
  the first start. The first start of a database imports the file once, add-only: it adds the
  sources the database lacks, each on or off as the file says. Later starts don't read it.
- **An import only adds** (v9.14): it never changes the on/off of a source the database has, and
  never adds back a source removed in the app (or an address a source was switched away from): the
  database remembers those (`removed_sources`). Adding the source again in the app forgets it.
  Sources removed before v9.14 left no trace, so an old file can still add them back.
- **Importing a file by hand**, add-only, any time:
  `docker compose exec backend python insight_core/scripts/sync_sources_json.py json-to-db`.
  It never deletes. It exits 1 when the file can't be read or an entry was skipped, and the log
  names each skipped entry.
- **A missing, empty or broken file** changes nothing and never stops a start.
- The file is not in git (it was until v9.13). Copy it with your backups if you keep any.

### Pulling v9.13 on a server whose sources.json was in git (once)

Until v9.13 `sources.json` was tracked, and the app rewrote it on the server, so the server's
copy has local changes. The pull that untracks it would refuse to run over them, and the old
code still running reads the file. So: move the file out of the way (the old code refuses to
mirror a missing file, so nothing is deleted meanwhile), pull, put it back, then update. In the
server's checkout, and change no source in the app until the update is done:

```bash
grep -c '^VITE_API_URL=.' .env      # 0: the app calls /api through nginx (v9.13 closes the API port to other machines)
F=backend/insight_core/config/sources.json
sudo docker exec insight-db psql -U insight -d insight -Atc 'SELECT count(*) FROM sources'   # note the number
mv "$F" ~/sources.json.keep          # the running code refuses to mirror a missing file
git pull --ff-only                   # removes the tracked file; nothing of yours is overwritten
cp ~/sources.json.keep "$F"          # put it back: untracked and ignored from now on
git status --short "$F"              # prints nothing
bash ./update
sudo docker compose logs backend ingestion | grep -E "sources.json|Imported"
sudo docker exec insight-db psql -U insight -d insight -Atc 'SELECT count(*) FROM sources'   # the same number
```

- The first start reads the file once as an add-only import. The log says
  `Imported sources.json: added=0 updated=0 skipped=0` when the file was in step with the
  database, as the app's own export is. The other container's start then says it was imported
  before.
- If the first line prints more than 0, the app's build calls the API's port directly, which v9.13
  closes to other machines: stop and empty `VITE_API_URL` first (the app then uses `/api`).
- If `git pull` refuses anyway, put the file back (`mv ~/sources.json.keep "$F"`) and stop:
  nothing has changed.
- Use your `DB_USER` and `DB_NAME` if they are not `insight`. Keep `~/sources.json.keep` until
  you have checked the count.

## Updating

```bash
git pull
./scripts/backup              # optional: the database (-Fc), the secrets volume and .env into ./backups/<time>/
docker compose build
docker compose up -d --remove-orphans
```

`./update` does the same without the backup, unless you ask for it (`INSIGHT_BACKUP_ON_UPDATE=1` in `.env`, see
"Backups and rollback" below): `git pull`, build, then `up -d`. Between the build
and `up -d` it lists the migrations the new code will run at its start, each with its header's
first line (`migrate.py --pending`, read-only), so one that rewrites rows is seen before it runs. The build runs
while the old containers keep serving; `up -d` then recreates only the containers whose image
or config changed, so the site is down only while those containers restart, not for the build.
The frontend starts again as soon as the API's healthcheck passes, which is checked every second
while the API starts (`start_interval`, Docker Engine 25+ and Compose 2.20.2+), so the downtime
is the API's own start: about 4 s on the build machine with the lab's data (it was 32 s while
the first check waited 30 s). Migrations run inside that start, so a long one makes it longer.
It reuses the cached base images and dependency installs, so a code-only update rebuilds only
the code layers; npm packages are reinstalled only when `package.json` or `package-lock.json`
changes (the build stamp comes after `npm ci`). `./update --refresh` (or `docker compose build --pull`) also pulls
fresh base images (python, node, nginx), which rebuilds the pip and npm installs: do it now
and then for security patches, and after changing `requirements.txt` or `package.json`
(those rebuild their install layer anyway). `backend/requirements.txt` pins every package to the
version tested, `yt-dlp` too (since v10.16.2): when YouTube breaks it, bump its pin and update.
If only environment variables changed: `docker compose up -d --force-recreate`.

### Backups and rollback (issue 0188)

**A backup:** `./scripts/backup` writes `backups/<UTC time>/` next to `docker-compose.yml`:
- `insight.dump`: the database, `pg_dump -Fc` (compressed; checked with `pg_restore --list` before it counts);
- `secrets.tar`: the `insight_secrets` volume, the key that decrypts Connections (API keys, sessions);
- `env`: a copy of `.env`.

**`secrets.tar` and `env` hold secrets.** The directory is made 700 and its files 600. Copy a backup off the
machine only to a place as private as the machine. The newest `INSIGHT_BACKUPS_KEEP` (default 5) backups are kept;
older ones are removed by the next backup. `backups/` is never committed.

**On a schedule** (nothing runs one by default): `contrib/systemd/insight-backup.service` and `.timer` (nightly at
03:30, a missed night runs at the next boot; the install steps are in the service file), or root's crontab:
`30 3 * * * cd /path/to/checkout && ./scripts/backup >> backups/backup.log 2>&1`.

**Before an update, if you want it:** `INSIGHT_BACKUP_ON_UPDATE=1` in `.env` (or the shell) makes `./update` run
`scripts/backup` after the build and before the new code starts and migrates; a backup that fails stops the update
there, with the old version still serving. Off by default.

**Rollback:** every `./update` tags the images it built with the version (`VERSION`'s `vX.Y.Z`) and the commit,
beside `:latest`; the newest `INSIGHT_IMAGES_KEEP` (default 3) builds keep their tags. `./update --images` lists them.
```bash
./update --rollback v10.16          # no pull, no build: those images become :latest and start
./scripts/backup --restore backups/2026-11-13T033000Z   # only if the older code needs the database as it was
```
- `--rollback` refuses, changing nothing, when that version's images are not kept. The first update with this
  (v10.17) is the first tagged one: a rollback needs two tagged updates.
- The database keeps what the newer code migrated. Most migrations only add, and older code runs on them; when it
  doesn't, restore the backup taken before the update: `--restore` asks you to type the database's name, stops the
  API and ingestion, empties the database (`dropdb`/`createdb`), `pg_restore`s the dump and starts them again.
  Everything written since that backup is lost. It leaves `.env` and the secrets volume alone and prints how to put
  those back from the same backup.
- Roll back first, then restore: restoring under the newer code would migrate the database again at its start.
- The checkout stays at the pulled code; the next `./update` builds it again.

After the restart the API catches up in the background while the reader already works: it
re-indexes search when the search rule changed, reads the links of posts never read, and runs
the story job (stories, News, Classics). Sources → Ingestion → Background work shows each. They
finish by themselves, without a restart: the search refill and the link reading wait for each
other's rows rather than stopping early. After each fetch run the story job regroups only what the
new posts touch (issue 0072 A: on a copy of the lab, 30 new posts take about 1 s of CPU and ~75 MB).
When an update changes what the story rules make (their stamp, worked out at start from a fixed
sample: `utils/stamps.py`), the story job regroups every post in batches in the background, old
stories too, while the reader shows the stories of the old rules until each batch replaces them;
Background work says "regrouping every post by new rules, X of Y". On the lab's data that took
~23 min and peaked at ~210 MB on a busy machine (the lab's own first starts, 2026-11-04: 28 min for 0059 alone; 45 min for 0058–0065 together on a machine at load 27–58; plan for 30–45 min). **The first start after v9.15's migration 0059 is
such a rebuild**, and three things change once with it: story ids (a story keeps the id of its post
stored first), a date alone counts as that day's first timed post of its story, and News keeps the
last 30 days even after a full run. A full rebuild at once is still there by hand:
`docker compose exec backend python -m insight_core.services.stories_service full` (~30 s CPU,
~520 MB). The start's story work runs in a process of its own (issue 0072): on a copy of the lab a
first start peaks at ~540 MB, and the API holds ~45 MB once it is done (it held 530-550 MB before). Discover's addresses, the stored bodies and
the search index are stamped the same way, and each is made again by itself when its rules change.

**The first start after v9.16's migrations 0060–0063 (issue 0076, a post is read once) parses every
stored post once**, before the story job, in the job's own process: each post's title, lead, shown
body (as cut points), quote and footer go into `post_parts`, which every page reads from then on. On a
copy of the lab (41,637 posts, machine load 8–27 on 32 cores, three runs): 246–261 s, a peak of
145–164 MB in that process, 90–165 MB of WAL, and a 33 MB table (6.2% of `posts`). The API process
itself stays at ~70 MB (56 MB the container, after the job). Until a post is parsed the pages show its
stored title and text (the newest posts are parsed first). Then the story job regroups every post in
batches, as after 0059 (the stories now read the title the pages show, so the rules' stamp changed):
plan for the parse's ~5 min on top of that rebuild. Later starts parse only what has no parts (a save
parses its post at once), and every post again only when the parser's own stamp changes, writing only
the rows that changed. No posts row is rewritten (`published_precision` stays empty on stored posts,
read as before).

### Version

The repo-root `VERSION` file holds the running version in the Mark scheme, e.g.
`Mark IX v9.1` (Mark = major, vN.x = its release). Bump it by hand in each release's commit.
`./update` exports it with the commit as build args, `INSIGHT_VERSION` (VERSION's contents),
`INSIGHT_COMMIT` (short SHA) and `INSIGHT_COMMIT_DATE` (YYYY-MM-DD); compose passes them to
the backend, ingestion and frontend images. The API answers them at `GET /api/version`, the
web app has them inlined by Vite, and the Ingestion tab's last line shows both, saying "out of
step" when they differ. A plain `docker compose build` leaves them empty: `dev build`. To stamp
one by hand, export the three as `./update` does before building.

### `.env` keys that are safe to remove

Nothing in the code, compose file or scripts reads these any more (checked by name, v9.13), so
an older `.env` that still holds them works the same without them:

- from the analysis version: `INSIGHT_ANALYSIS`, `VITE_INSIGHT_ANALYSIS`, `GOOGLE_API_KEY`,
  `GEMINI_MODEL`, `GEMINI_MODEL_FALLBACKS` (any `GEMINI_*`), `INSIGHT_GENERATE_DAILY_BRIEFING`,
  `INSIGHT_GENERATE_TOPIC_BRIEFING`;
- older settings: `API_HOST`, `SAFE_INGEST_SKIP_THRESHOLD_HOURS`;
- gone in v9.13 (issue 0071): `INSIGHT_SYNC_SOURCES_EACH_CYCLE` (no file sync runs) and
  `INSIGHT_ALLOW_BULK_SOURCE_DELETE` (nothing deletes sources in bulk). `API_WORKERS` is read again
  since v10.0.2 (the number of API processes, default 2): remove it unless you want another number.
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and `SUBSTACK_SID` are read only by `import_env_secrets`
  (above): remove them once they are in Connections.

A Gemini key saved in Connections stays in the `credentials` table and is no longer shown.

## Retiring analysis (migration 0027)

Migration `0027_drop_analysis.sql` removes the analysis data for good. It runs by itself on
the next start of the `backend` or `ingestion` container after the pull, so pull it only on
the owner's go, and back up the database first.

1. Back up, before `git pull`:

   ```bash
   docker exec insight-db pg_dump -U insight -Fc insight > ~/insight_pre_0027_$(date +%F).dump
   ls -lh ~/insight_pre_0027_*.dump    # check it is not empty
   ```

   (Use your `DB_USER` and `DB_NAME` if they are not `insight`.) To restore it into a fresh
   database: `docker exec -i insight-db pg_restore -U insight -d insight --clean < <file>`.

2. Pull and roll the containers as in "Updating". The migration runs at start.

What it drops:

- 30 tables: `topics`, `topic_posts`, `topic_connections`, `briefings`, `post_ai_cache`,
  `post_highlights`, `artifacts`, `artifact_post_references`, `post_artifacts`,
  `post_relations`, `source_profiles`, `entities`, `entity_aliases`, `entity_mentions`,
  `mention_entity_candidates`, `post_entities`, `events`, `event_entities`, `event_evidence`,
  `analyst_actions`, `stories`, `story_posts`, `story_updates`, `story_update_posts`,
  `story_candidate_links`, `inbox_batches`, `inbox_items`, `experts`, `milestone_lanes`,
  `milestone_overrides`.
- 9 `posts` columns: `title_original`, `body_original`, `title_pivot`, `summary_pivot`,
  `title_pivot_version`, `summary_pivot_version`, `title_hash`, `normalization_version`,
  `enriched_at`.
- 1 `folders` column: `use_global_milestone_lanes`.

It keeps every reading table, `post_notes` included, and the post columns reading uses
(content hash, normalised and canonical URL, URL host, language). The migration is
idempotent: running it again changes nothing.

## Repairing teaser posts (once)

Posts stored before full text was kept (Substack and many news feeds stored only their
summary) are re-read by hand, once, after the deploy that brings it:

```bash
docker compose exec backend python -m insight_core.scripts.repair_full_text --dry-run
docker compose exec backend python -m insight_core.scripts.repair_full_text
docker compose exec backend python -m insight_core.scripts.repair_full_text --entities --dry-run
docker compose exec backend python -m insight_core.scripts.repair_full_text --entities
```

The first two make real requests to the sites (2s apart per site). `--entities` makes
none: it decodes the HTML codes ("That&#39;s") stored in older posts' text. See
`backend/insight_core/scripts/README.md`, "Full text".

**When it is safe to run:** once the server runs Mark IX v9.14 (issue 0072) or later, and not
before. A post the repair reads keeps what the server's reader makes of its page, and is not
read again. The reader before 0053 kept Hugging Face's upvoter avatars (6 to 22 full-width
pictures before the words) and the post's title as a heading. The reader since then drops them,
as the page corpus's Hugging Face page shows (0072 C2). On a copy of the server's data
(2026-11-01), `--dry-run` lists 5,588 posts on 319 sites, 245 of them the Hugging Face blog's
empty posts (`--source <its id>`: 245, all to read, none skipped). Run `--dry-run` first and
check that its count is close to that. The 7 Hugging Face posts stored with a body keep their
avatars: the repair reads only short bodies.

## Exporting and restoring the database (issue 0079)

**Export:** Sources → data → Export everything. The browser downloads one zip,
`insight-YYYY-MM-DD-HHMM.zip` (written as it streams; nothing is kept on the server):
a CSV per table, `schema.sql` (the migrations it was made at), `manifest.json` (version,
migrations, each table's rows) and `README.txt`. Stored logins (the `credentials` table:
the Substack cookie, the Telegram API id, hash and session) are an empty CSV unless
"Include stored logins" is ticked; even then they are ciphertext that reads only with this
server's secret key (`INSIGHT_SECRET_KEY` or the `insight_secrets` volume). Export sources
(same tab) downloads the sources list as `sources.json`.

**Restore** (into a new database: the restore refuses one with any table, and never
replaces data). Copy the zip to the server, into the INSIGHT folder, then from that folder:

```bash
docker compose run --rm -v "$PWD/insight-2026-11-05-1200.zip:/tmp/insight-2026-11-05-1200.zip:ro" backend \
  python insight_core/db/import_export.py /tmp/insight-2026-11-05-1200.zip --into insight_restored
```

It creates `insight_restored` on the same server, runs the export's migrations, loads every
CSV in the order the foreign keys need (the tables' own triggers off, the plain indexes built
after the load), checks each table's rows against the manifest, all in one transaction (a
failure leaves the database empty), then migrates up to the running version. An export from a
newer INSIGHT is refused: update first. To read it:

```bash
# in .env
DB_NAME=insight_restored
docker compose up -d
```

The old database stays as it was until you drop it. Logins left out of the export are entered
again in Sources → Connections. On the lab's copy (41,637 posts) the zip is 243 MB, about the
size of `pg_dump -Fc`, and the restore takes about 41 s, as `pg_restore` does.

**Explored on its own:** the README in the zip says how (DuckDB, pandas, SQLite, or
`psql -f schema.sql` into any Postgres with pgvector, then `\copy` each CSV).

## Mark X Shadow (issue 0086): off by default
Mark X reads every post beside Mark IX and writes only its own `mx_*` tables (migration 0068). Mark IX's feed, stories, News, Classics and Discover don't change because of it. It ships **off**: no Mark X job runs and `/api/markx/*` answers 404.

**Turning it on:**
1. Add `INSIGHT_MARKX=on` to the server's `.env`, then `./update`.
2. Settings → Sources → Connections → **Mark X worker token**: generate it and copy it once to the device that runs the worker, as `~/.config/insight/markx-token` (mode 600).
3. The menu shows **mark x** (`/markx`): Mark X News beside Mark IX's, the briefing, entities, the worker's queue and the labels.

**What runs on the server when it's on: in `insight-ingestion`, never in the API** (issue 0112 Decided 10, v10.0.2). On 5 Nov a decision run inside the API's one process sat at 101% CPU and every `/api/*` request timed out.
- The API only marks that work arrived (`mx_jobs`; new vectors' posts in `mx_candidate_posts`): a valid answer, new vectors, **run the decisions now** on `/markx` (`POST /api/markx/decide` only asks), the start's story job.
- Ingestion's scheduler looks every 30 s and runs the job due, each in a child process of its own (killed after 15 minutes):
  - the candidate finder, when vectors arrived;
  - a decision run (the candidate finder first, with the posts whose entities arrived), 60 s after work arrived and at least hourly, **at most one every 5 minutes** however the uploads stream in (Decided 12).
- One at a time: one process runs them, and the decision run holds a database lock (a second one is skipped and asked again).
- **A decision run has a 120-second limit** (Decided 12). Past it, it stops before its next stage, writes nothing (its one transaction rolls back), logs which stage, and runs again at the next look. Its logs: `Mark X decision run started`, each stage with its duration (`candidates`, `load`, `questions and decisions`, `write`, `connections`, `headlines`, `news`), `Mark X decision run finished in N s` (`docker compose logs ingestion`). Measured on the server's 5 Nov copy: 62 s for the first run after a day's entities (59 s of it the candidate finder over 5,031 posts), 3 s after.
- `/markx` → Worker shows a running run's stage and start, a run asked for, or how the last one stopped (`/api/markx/status` → `jobs`).
- Nothing calls a model from the server.

**Updating to v10.0.1 (issue 0112): update the worker on the device with the server.**
- The fix for refused readings lives in `scripts/markx-worker`: it sends each guide's answer schema with the guide, so Haiku writes the field names the server checks. A v10.0 worker against a v10.0.1 server keeps failing about 45% of reading items (`answer.mentions[i]: name missing`). Pull the same commit on the device (or copy `scripts/markx-worker`) when you `./update` the server, and restart its loops.
- Migration 0069 runs at the server's start, once:
  - it reopens the read tasks that failed only from that error (their failed answers stay recorded); the next worker cycle reads them;
  - it closes, as failed with the reason, the checks v10.0 queued against an empty story: v10.0.1 never asks them.
- **The reading window** (issue 0112 Decided 9): `/markx` → Worker → **Reading window**: 30 days (the default, when never set), 120 days, everything, or a number of days. It is how far back the worker reads, finds entities and embeds (embeddings followed every post before; now the window too); a change counts from the next lease, with no restart. Nothing sets it on deploy: set 120 days on the page after the update. The decisions keep to the last 30 days whatever it says. To read another range from the device at any time, whatever the page says: `scripts/markx-worker cycle … --kinds read,entities --days 120` (or `--days all`): each lease then plans that window first, newest first.
- **Parallel calls:** start the worker at `--parallel 10` at most and raise it in steps while watching it. About 100 `claude -p` calls at once made the device's Tailscale DNS stop resolving, twice (5 Nov), and the calls failed with "Can't reach the API server".
- The first decision run after the start (once the story job is done) re-decides v10.0's removals: a post removed on an empty-story check, or a near-copy of another member, is a member again; the empty-story check is asked again with the story shown, and a near-copy is never checked. Run the worker's `check` and `merge` kinds again from then on.

**Updating to the second ask and incremental runs (issues 0112 Decided 8, 0116): update the worker on the device with the server.**
- **The worker asks each merge alone:** `scripts/markx-worker --per-call`, default `merge=1`. The lease still takes `--batch` tasks; other kinds keep 20 a call. Pull the same commit on the device (or copy `scripts/markx-worker`) when you `./update` the server, and restart its loops. An older worker still works, but it batches merges 20 a call.
- **Expect about 470 questions reopened by the first decision run** (measured on the 5 Nov server copy: 165 joins, 301 pairs, 6 merges).
  - A join, pair or merge that changes a story now counts only once a second answer agrees, so every story-changing answer v10.0.1 had is asked again.
  - Until the worker answers them, those joins and pairs are out of Mark X's stories: `/markx` shows fewer of them. Mark IX's stories and News are unaffected.
  - Run the worker's `join,pair,merge` kinds after the update. About 1 in 5 then needs a third ask (about 90 more).
- **Incremental runs need nothing:** the first run after a start is full and the next ones read only what changed. A full run happens each night after 04:00 server time and checks the incremental runs. `/api/markx/status`'s last run shows `counts.run` (kind, dirty tasks, closure, seconds), and `counts.check` after a nightly run. A difference there is logged as "Mark X incremental-run bug".

**The worker** runs on your device (`scripts/markx-worker`, standard library only):
```
# embeddings, with a local llama-server running BGE-M3 (llama-server --embedding -m bge-m3-q8_0.gguf --port 8091)
scripts/markx-worker cycle --server http://<server>:5173 --token-file ~/.config/insight/markx-token \
    --kinds embed --embedder http://127.0.0.1:8091
# readings and entities through Claude Code's Haiku (your Claude account)
scripts/markx-worker cycle --server http://<server>:5173 --token-file ~/.config/insight/markx-token \
    --kinds read,entities --batch 20 --batches 1 --parallel 3
```
Start with `--batches 1`, read what was refused (`markx-worker status`), then the last 30 days. It stops cleanly at a usage limit (exit 4) or a sign-in error (exit 5) and hands its tasks back.

**What the worker costs** (issue 0191, v10.17; Haiku 5.5 at list price, $0.10 / M input and $0.50 / M output; on a Claude subscription the same tokens count toward its limits). Measured on one week of the owner's logs (84,820 calls), each kind's answers per new post priced at its cost per answer:

| kind | answers per new post | $ per 1,000 new posts, v10.16 | v10.17 |
|---|---|---|---|
| entities | 1.42 | 1.248 | 0.862 |
| alias | 2.01 | 0.388 | 0.244 |
| read | 1.00 | 0.352 | 0.293 |
| cite | 0.29 | 0.347 | 0.231 |
| relate | 0.77 | 0.128 | 0.116 |
| track | 0.49 | 0.107 | 0.070 |
| back | 0.21 | 0.063 | 0.040 |
| collide | 0.18 | 0.060 | 0.029 |
| pair | 0.24 | 0.056 | 0.036 |
| read3 | 0.07 | 0.048 | 0.048 |
| perspective | 0.01 | 0.038 | 0.033 |
| connect | 0.12 | 0.038 | 0.023 |
| join | 0.10 | 0.028 | 0.017 |
| merge | 0.06 | 0.027 | 0.018 |
| other kinds (each under $3 a week) | | 0.039 | 0.027 |
| **total** | | **2.97** | **2.09** |

Run the worker from INSIGHT's checkout (it imports the server's answer checks from `backend/insight_core/markx/validate.py`, so an answer the server would refuse is asked again in the same cycle). Its cost settings, each measured per kind on the lab's labelled sets and overridable: `--effort` (Claude Code's thinking effort; default `entities=medium,cite=low,alias=low,alias2=low`), `--prompt-cache` (off for most kinds: Claude Code's 1-hour cache bills every prompt at 2x and calls of distinct items never read it back; the 5-minute cache for the one-item-a-call kinds, whose first call of a cycle goes alone so the others read its guide; Claude Code's default for relate, back, read3 and websearch), `--no-server-rules` (the schema alone). A post the API's classifier refuses is isolated at once and asked alone from then on (`refused.json` beside the spool).

**Workers that survive a reboot (issue 0188), only if you want them on a schedule.** The worker is run by hand
by default; `contrib/systemd/` has *user* units for the device that runs it:
- `markx-worker.service`: one cycle, with the arguments in `~/.config/insight/markx-worker.env`
  (`contrib/systemd/markx-worker.env.example`). Exit 3 (server unreachable) and 4 (usage limit) count as normal stops.
- `markx-worker.timer`: a cycle every hour, `Persistent=true` (a run missed while the device was off runs at the
  next boot); never two cycles at once. **Ships disabled**: enable it only if you want the worker to run by itself.
- `llama-server.service`: the embedder for the `embed` kind (BGE-M3), `Restart=on-failure`, with its binary, GGUF
  and port in `~/.config/insight/llama-server.env` (the steps are in the file). It holds the model in memory while
  it runs: enable it only when you embed.
```bash
mkdir -p ~/.config/systemd/user ~/.config/insight
cp contrib/systemd/markx-worker.{service,timer} contrib/systemd/llama-server.service ~/.config/systemd/user/
cp contrib/systemd/markx-worker.env.example ~/.config/insight/markx-worker.env    # edit: paths, server, kinds
systemctl --user daemon-reload
systemctl --user start markx-worker.service            # one cycle now; journalctl --user -u markx-worker
systemctl --user enable --now markx-worker.timer       # only for the schedule
sudo loginctl enable-linger "$USER"                    # user units run at boot, before (and without) a login
```
The worker's state (its JSON-lines log, the spool of answers not yet delivered, the GGUF hash memo) lives in
`~/.local/state/insight/markx-worker/`, never `/tmp`, so a reboot loses nothing. `log.jsonl` rotates past 10 MB and
keeps 4 old files (`log.jsonl.1` ... `.4`); two worker processes can share it.

**Turning it off:** `INSIGHT_MARKX=off` (or remove the line) and `./update`. Every Mark X job stops and the page hides; its tables stay as they are (keep everything).

**Updating to v10.0.2 (issue 0112 Decided 10-13):** `./update` rebuilds both images; migration 0070 adds `mx_jobs`, `mx_candidate_posts` and `mx_workers` (Mark X tables only). Mark X's jobs move to `insight-ingestion` by themselves; nothing to set. Remove `API_WORKERS=1` from `.env` if it is there, so the API runs its two processes.

## Health, timeouts, memory and logs (issue 0188)
- **`GET /api/status`'s `healthy` is computed**, with its `health.reasons` (what makes it false), `health.warnings`
  (shown, never false alone) and `health.checks` (the numbers read):
  - the newest successful ingestion run is older than the fetch interval plus two ticks, or the scheduler's next tick
    is two ticks overdue;
  - the scheduler's or Mark X's loop stopped beating (`/app/logs/runtime/heartbeat-*`, written every 30 s by the
    scheduler and after each Mark X look);
  - with Mark X on: a job failing (3 failed runs in a row), or no decision run finished in 2 hours;
  - warnings: failing sources; Mark X workers silent for over 3 days (also marked "stale" on the /markx page).
  `table_sizes` lists the 15 biggest tables (with indexes and TOAST). Nothing is pruned: everything is kept.
- **insight-ingestion's healthcheck** runs `python -I insight_core/utils/heartbeat.py`: unhealthy when the
  scheduler's heartbeat is over 3 minutes old (or Mark X's over 2000 s). Docker restarts nothing for that; it shows.
- **A Mark X job that fails backs off** (`mx_jobs.failures`, migration 0129): 10 minutes after the first failure,
  doubling, at most 6 hours apart, and keeps trying; from 3 in a row it is "failing" (/markx, `/api/status`).
  A decision run over its limit twice in a row in the same late stage (graph, back, later, entities, surges,
  perspectives) skips that stage once and is logged so; the run after tries it again.
- **Database timeouts** (`db/database.py`, by role): in insight-ingestion a statement ends after 14 minutes (under a
  job's 15-minute kill) and a transaction idle for 16 minutes is ended; in the API a request's statements end after
  30 s (`INSIGHT_DB_REQUEST_TIMEOUT_MS`, 0 turns it off; deleting a source is allowed the default 5 minutes), its
  background work keeps 5 minutes, an idle transaction ends after 2 minutes. Every connection checks its client
  every 10 s, so a killed job's statement ends and its locks are freed.
- **Logs:** each container's own log (`docker logs`) is capped at 5 x `INSIGHT_DOCKER_LOG_SIZE` (20m). The files in
  `/app/logs` (both containers, every process) rotate at 10 MB, 3 kept, by whichever process finds one full, under a
  lock, so no line is lost; the worker's `log.jsonl` rotates at 10 MB, 4 kept.
- **Memory** (`mem_limit`, each from `.env`): past its limit the kernel ends a process of that container only. In
  insight-ingestion that is a Mark X job's process (the largest), recorded as a failed run and backed off, never
  Postgres. The limits sit above the measured peaks, so a normal run is never ended:

  | container | limit | measured |
  |---|---|---|
  | insight-ingestion | 12g (`INSIGHT_INGESTION_MEM_LIMIT`) | 7.0-7.75 GiB spikes in decision runs on the server (0183); a decision run 1.2-1.6 GB on a 95k-entity copy (the server has ~250k) |
  | insight-api | 10g (`INSIGHT_API_MEM_LIMIT`) | 2.3 GB average, 3.2 GB at most on the server before 0186; an export's process peak 7.5 GB on the 0186 copy |
  | insight-db | 6g (`INSIGHT_DB_MEM_LIMIT`) | its page cache is reclaimed under the limit, never killed for |
  | insight-frontend | 256m | nginx serving files |

  If the server's corpus grows and a container is ended at its limit (`docker inspect insight-ingestion` shows
  `OOMKilled`, or a Mark X run "exited with code -9"), raise its limit in `.env` and `./update`.
- **Minimum host**, from those numbers: 16 GB of RAM for a server-sized corpus (ingestion's peak ~8 GB, the API ~3 GB,
  Postgres and the page cache the rest); 4 cores (a decision run uses one; the API two processes; Postgres the
  rest). A small corpus runs in far less: the limits are ceilings, not reservations.

## When the API stops answering (issue 0117)
Docker restarts nothing for being unhealthy: `restart: unless-stopped` acts only when the process exits. On 5 Nov the API answered nothing for over 20 minutes until the owner looked.

- **The health check asks `/api/version`** (what the reader needs; `/health` answered on 5 Nov while every `/api/*` request hung), every 30 s, 5 s at most; 4 failures in a row (2 minutes) mark `insight-api` unhealthy. `/health` stays the database check.
- **A watchdog in `insight-ingestion`** (the owner's option A; `INSIGHT_API_WATCHDOG=on`, set in compose) asks `http://backend:8000/api/version` every 30 s. After 4 failures in a row (2 minutes) it asks the API container to restart, then judges nothing for 5 minutes. An API that isn't there (stopped with `docker compose stop backend`, or starting: nothing listens yet) is no hang and counts nothing; the API's supervisor never honours a request written before it started or over a minute old, so a stop or an `./update` never ends in a kill of the fresh API (issue 0124).
- **How, without the Docker socket:** a container that holds the socket can do anything on the host as root, so it is never mounted. Ingestion writes a request file in the logs volume both containers mount (`/app/logs/api-restart-request.json`). The API container's supervisor, a process of its own that a hung API process can't block, sees it within a second, saves the evidence, stops uvicorn and exits; Docker's restart policy starts the container again. Only the API restarts: never the database, ingestion or the frontend.
- **The evidence first:** each API process writes every thread's stack to `/app/logs/api-stacks.log` on SIGUSR1 (`faulthandler`, which works while Python is stuck). The supervisor sends it to each API process before the restart; the watchdog prints the dump in its log and attaches it to the restart's record. By hand, any time, without a restart: `docker kill -s USR1 insight-api` (the supervisor passes it to each API process), then read `/app/logs/api-stacks.log` (`docker compose exec backend tail -n 200 /app/logs/api-stacks.log`).
- **No restart loop:** at most 3 restarts an hour (counted from the records, so a restart of ingestion doesn't reset it). After that it stops restarting and records once that the API keeps failing.
- **Every restart is recorded** as an `API restart` job (Settings → Sources → Ingestion, and the overview's alerts): "The API was restarted at 22:45 after 2 min of no answer" (the time in your browser's zone: the record keeps it as UTC, issue 0124), the failing check, the last 50 log lines, and the stack dump.
- Measured on a copy (both API processes made to spin, `INSIGHT_DEBUG_SPIN=on`, `POST /api/debug/spin`): restarted 2 min 36 s after the hang began, the dump named the spinning function in both processes, the API answered again 2 s after the restart, nothing else restarted.
- **Option C, if you'd rather keep it outside the containers** (set `INSIGHT_API_WATCHDOG=off` in `.env` then): a systemd timer on the host. It has no cap of its own beyond `StartLimit`, and keeps no record in INSIGHT.
```
# /etc/systemd/system/insight-api-watchdog.service
[Unit]
Description=Restart insight-api when /api/version stops answering
StartLimitIntervalSec=3600
StartLimitBurst=3
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for i in 1 2 3 4; do curl -fsS -m 5 -o /dev/null http://127.0.0.1:8000/api/version && exit 0; sleep 30; done; docker kill -s USR1 insight-api; sleep 3; docker restart insight-api'
# /etc/systemd/system/insight-api-watchdog.timer
[Unit]
Description=Check insight-api every 5 minutes
[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
```
  `sudo systemctl enable --now insight-api-watchdog.timer`. Its `docker kill -s USR1` writes the stacks to `api-stacks.log` before the restart.

## Development mode

```bash
# backend (needs PostgreSQL and DATABASE_URL in .env)
pip install -r backend/requirements.txt
python backend/insight_core/db/migrate.py
(cd backend && uvicorn main:app --reload --port 8000 --env-file ../.env)

# scheduler, in another shell (optional)
python backend/insight_core/scripts/run_scheduler.py

# frontend, in another shell
cd frontend && npm install && npm run dev
```

Vite serves on `http://localhost:5173` (bound to all interfaces) and proxies `/api` to
`http://localhost:8000`. To point the dev UI at another backend, set `VITE_API_URL` and restart Vite.

## Tests

- Backend: `./run-tests.sh [module]` builds the image and runs the suite inside it. By default
  each run creates a database of its own (`insight_run_<time>_<pid>_test`), migrates it, and drops it when the run ends, so two runs at once never share rows (never the live `insight`). `TEST_DATABASE_URL` tests against a database
  of your own instead (its name must end in `_test` for the suites that commit rows), and `MIGRATE=1`
  migrates it first. `TEST_IMAGE=<tag>` builds and runs that tag instead of `insight-backend:latest`.
- Test data: `insight_core/tests/_stories.py` is the one factory for the posts and sources tests
  make (`story_post`, `insert_source`, `insert_post`).
- Frontend: `cd frontend && npm run typecheck && npm test && npm run build`.

## Before a merge: the real-data check (issue 0075)

Nothing merges into main unless this passes on the lab copy. It runs locally, never in CI: real data
can't leave the machine.

```bash
scripts/realdata-check.sh insight_lab                     # this checkout's working tree against main
scripts/realdata-check.sh --head <branch> insight_lab     # a committed branch instead
scripts/realdata-check.sh --titles-only --base <a> --head <b> <copy>   # two commits' titles over one copy, no story job
```

- **What it does:**
  - It `pg_dump`s the copy once (only reading it) and restores two scratch copies, `<db>_check_a` and `<db>_check_b`. You can set their names with `SCRATCH_A`/`SCRATCH_B`; a name must end in `_check_a/_b`, `_<nnnn>a/b` or `_test`.
  - Main's code runs on one copy and the branch's on the other, both at once. Each runs in a container from the newest local `insight-backend:lab-*` image (`--image` picks another) with its code mounted. Nothing is built, pulled or fetched.
- **Each side runs these steps:**
  1. the migrations;
  2. a full story job, on the copy's own clock (its last fetch; `--now` sets another);
  3. a snapshot of everything the code derives;
  4. the invariants;
  5. the judged cases;
  6. a second full rebuild, to check identity;
  7. the incremental job's own identity check (`--identity module:function`). A version without it reads "not measured".
- **The report** names the owner's posts, so it is private. It goes to `plan/research/lab/checks/<branch>-<date>.md`, with the JSON beside it. Put its path in the merge notes.
- **It fails (exit 1) when:**
  - a case marked `pass` fails;
  - an invariant's count rose above main's and no `--allow name=reason` names a reason the spec gives;
  - a step produced nothing.
- **The pieces run alone too:**
  - `python -m insight_core.scripts.check_cases --db <dsn> --cases <file>`;
  - `python -m insight_core.scripts.check_invariants --db <dsn> [--baseline main.json]`;
  - `python -m insight_core.checks.diff --before a.json --after b.json`;
  - `python -m insight_core.checks.table_rows --a <dsn> --b <dsn>`, the story tables of two copies row by row. A no-op move must show 0.

  The case format is `backend/insight_core/checks/case.schema.json`. The cases themselves are in `plan/research/lab/cases.json`, which is private.
- **Read-only:** the checks open every connection read-only. The story job only ever writes a scratch copy, and refuses any other name.
- **Cleanup:** the script removes only containers it named and the scratch copies it made (`--keep` keeps the copies).

## Troubleshooting

- **Feed is stale ("last fetch N days ago").** Check that the scheduler runs:
  `docker compose ps ingestion` and `docker compose logs --tail=100 ingestion`. The
  ingestion tab (`/settings/sources?tab=ingestion`) shows the scheduler status and the last run report.
- **A source shows failing.** Open `/settings/sources?tab=health&status=error`. The row shows the
  last error and when the next retry is. `Fetch now` retries it immediately.
- **Run reports `skipped_busy`.** Another all-sources run holds the run lock. It finishes on its
  own; folder and single-source fetches are not blocked by it.
- **The frontend shows network errors.** Check `docker compose logs backend` and that
  `curl -s localhost:${BACKEND_PORT}/health` on the host answers. It makes one database query:
  503 `{"status": "unhealthy"}` means the API runs but can't read the database. Leave `VITE_API_URL` empty in Docker so the UI
  uses same-origin `/api` through Nginx.
