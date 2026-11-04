# INSIGHT deployment guide (Mark IX)

INSIGHT runs as four Docker Compose services from `docker-compose.yml`. The README has the
feature overview; this file covers deploying, updating and troubleshooting.

| Service | Container | What it does |
| --- | --- | --- |
| `postgres` | `insight-db` | PostgreSQL 15 with pgvector. Internal to the Docker network only. |
| `backend` | `insight-api` | FastAPI on port 8000 (`BACKEND_PORT` on the host, `127.0.0.1` only). Runs migrations on start, and imports `sources.json` once per database (add-only). |
| `ingestion` | `insight-ingestion` | The scheduler (`scripts/run_scheduler.py`): an ingestion tick every `ingest_tick_minutes`, daily work every `interval_hours`. |
| `frontend` | `insight-frontend` | The built React app behind Nginx (`FRONTEND_PORT`), proxying `/api` to the backend. |

The API runs as one uvicorn worker. Its start refuses `API_WORKERS` other than 1, with a line in
`docker compose logs backend` saying why (issue 0071): two workers would close each other's jobs,
lose an archive's or a Telegram sign-in's state between requests, and repeat the start's work.

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
- `.local` HTTPS hosts are fetched without TLS verification. Add other internal hosts to
  `RSS_SKIP_TLS_VERIFY_HOSTS`.
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
docker exec insight-db pg_dump -U insight insight > /tmp/insight_pre_update.sql   # back up first
docker compose build
docker compose up -d --remove-orphans
```

`./update` does the same without the dump: `git pull`, build, then `up -d`. Between the build
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
version tested, except `yt-dlp`, which a rebuild of that layer brings fresh; the first update to
v9.13 rebuilds it once, since the file changed.
If only environment variables changed: `docker compose up -d --force-recreate`.

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
~23 min and peaked at ~210 MB on a busy machine (the lab's own first start, 2026-11-04: 1,670 s, about 28 min; plan for 25–30 min). **The first start after v9.15's migration 0059 is
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
copy of the lab (41,637 posts, machine load 8–12 on 32 cores, two runs back to back): 260–261 s, a peak
of 145–159 MB in that process, 90–130 MB of WAL, and a 29.6 MB table (5.6% of `posts`). The API process
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
  `INSIGHT_ALLOW_BULK_SOURCE_DELETE` (nothing deletes sources in bulk). `API_WORKERS` is not read
  either, except that a value other than 1 stops the API's start.
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
