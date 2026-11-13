# I.N.S.I.G.H.T.

I.N.S.I.G.H.T. is a single place for all your sources and one calm reading flow. It collects posts from selected sources on a per-source cadence, stores them in PostgreSQL, and gives you one reader over all of them. It also supports one-time archive backfills.

Mark IX is a **reader**. The top bar reads `feed / sources / blog`:

- **feed** (`/`, `/read/...`): every source in one reading flow. The rail holds tracks (folders)
  and sources. Its views: **Stream**, **By source**, **News** (the stories several of your voices
  cover now) and **Classics** (pages your voices keep linking over time). A post that several
  sources cover is one row, a story, with its other posts under it as a tree.
- **post** (`/posts/:postId`): the content only, with open original (↗), star (☆) and copy (⧉),
  and the story it belongs to, as a tree from its origin.
- **search** (`/search`): every post, by title, source name and text.
- **save** (`/save`): save any page as a post (the bookmarklet's and ⌘K's).
- **sources** (`/settings/sources`): tabs `sources / discover / connections / ingestion`. Discover
  suggests the sites and accounts your sources keep linking that you don't follow.
- **blog** (`/blog`); the Design Studio (`/design`) is reached from ⌘K.

Stories came back as a reading feature (issues 0050, 0051, 0064): the story job groups the posts
that cover one thing (by address, text, title, links, reposts, threads and quotes), draws each
story as a tree, and derives News, Classics and Discover from the same links. The old analysis
layer (entity and event memory, experts, briefings, the inbox, Gemini) was retired in issue 0005;
the tag `mark-ix-analysis-archive` holds it.

## What It Does

- Stores sources, posts and archive status in PostgreSQL.
- Supports RSS/Atom feeds, Telegram RSS, Telegram channels over MTProto, Nitter RSS, Reddit, and YouTube channels.
- Fetches every source through one ingestion entry point, on a per-source cadence with backoff for failing sources.
- Gives you one reader over all sources (`/`): unread, starred and read state, tracks (folders) as filters.
- Uses the same post storage path for archive and live ingestion.
- Keeps your sources in the database, and writes them to `backend/insight_core/config/sources.json` as an export after each change.

## Data Model

The runtime source of truth is the database pointed to by `DATABASE_URL`.

Important tables:

- `sources`: configured sources and per-source settings.
- `source_fetch_state`: per-source fetch schedule state (last attempt and outcome, failures, next retry).
- `posts`: all archived and live-ingested posts.
- `post_reader_state`: read and starred state per post.
- `youtube_watch_progress`: saved YouTube watch state.

The full schema is in `backend/insight_core/docs/DB.md`.

## Sources and sources.json

The database is the truth for your sources (issue 0071). `sources.json` is their export:

- Adding, editing and removing a source in the app write the database, then rewrite the file
  (to a temporary file, then renamed over it, so a crash never leaves it cut short).
- A source is removed only by Remove in the app. Nothing deletes a source because a file lacks it.
- The first start of a database imports the file once: it adds the sources the database lacks, and
  never deletes. Later starts don't read it.
- An import only adds: it never changes a source's on/off and never brings back a source you
  removed (the database remembers it; adding it again in the app forgets that).
- To import a file by hand (add-only):
  `docker compose exec backend python insight_core/scripts/sync_sources_json.py json-to-db`.
- A missing, empty or broken file changes nothing; a bad entry is skipped with a line in the log.
- The file is not in git. `backend/insight_core/config/sources.example.json` is a starting point.

File path: `backend/insight_core/config/sources.json`; override with `INSIGHT_SOURCES_JSON_PATH`.

## Supported Source Types

- Telegram RSS via `https://telegram.local/rss/{username}/{page}`
- Telegram channels by bare handle, over MTProto (needs a session, see below)
- Nitter RSS via `https://nitter.local/{username}/rss`
- Reddit via `r/{subreddit}` or Reddit subreddit URLs
- YouTube via channel ID, `@handle`, `/channel/...`, or feed URL

Notes:

- RSS-based Telegram sources do not require Telegram API credentials.
- Bare-handle Telegram sources need the Telegram API ID and hash and a signed-in session, all added under Sources → Connections → Telegram (see `backend/insight_core/scripts/README.md`). Until then those sources show as unavailable, not failing.
- Reddit is read through its public RSS/JSON feeds and needs no account or API key.
- Self-hosted `.local` HTTPS feeds are fetched with TLS verification disabled automatically. You can also set `RSS_SKIP_TLS_VERIFY_HOSTS` for additional internal hosts.

Archive behavior:

- Telegram: 5s per page, then 30s cooldown after each 10 pages
- Nitter: 10s per page, then 30s cooldown after each 10 pages
- Reddit: archive uses top 250 all-time, live uses newest posts
- YouTube: archive/live fetches videos into the same post pipeline

## Docker Topology

The recommended production layout is the included `docker-compose.yml`:

- `postgres`: PostgreSQL 15 (`pgvector/pgvector:pg15`)
- `backend`: FastAPI API server
- `frontend`: built static frontend behind Nginx
- `ingestion`: long-running scheduler (`scripts/run_scheduler.py`)

The scheduler has two clocks:

- the ingestion tick, every `ingest_tick_minutes` (default `60`, floor `15`, env `INSIGHT_INGEST_TICK_MINUTES`). Each tick is one ingestion run over all enabled sources, and each source's cadence decides whether it is due, so a tick fetches only the sources whose interval has passed or whose backoff has expired. A failing source retries on a backoff ladder (`INSIGHT_BACKOFF_*` in `.env.example`).
- daily work, once `interval_hours` (default `20`) have passed since it last ran: prune old `job_runs` and refresh source cadence.

Archive is never run automatically; it is a manual action only. Backend and ingestion share a persistent `insight_logs` volume, so the Ingestion tab can show recent runtime logs.

## Quick Start

1. Copy env file:

```bash
cp .env.example .env
```

2. Edit `.env` for your server. It holds infrastructure only (database, ports, CORS, intervals); API keys are added in the app under **Sources → Connections** and stored encrypted.

Important values:

- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `BACKEND_PORT`
- `FRONTEND_PORT`
- `INSIGHT_SOURCES_JSON_PATH`

3. Optional: to start with some sources without using the app, copy
   `backend/insight_core/config/sources.example.json` to `sources.json` beside it and edit it before
   the first start. The first start imports it once.

4. Start the stack:

```bash
docker compose up -d --build
```

5. Check services:

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f ingestion
```

Default URLs:

- Frontend: `http://localhost:${FRONTEND_PORT}`
- Backend API: `http://localhost:${BACKEND_PORT}`
- API docs: `http://localhost:${BACKEND_PORT}/docs`

What happens automatically on startup:

- PostgreSQL starts and persists data in `postgres_data`
- backend runs migrations, imports `sources.json` if this database never imported one (add-only), and starts the API
- ingestion runs migrations, the same import, runs its first tick immediately, then ticks every `ingest_tick_minutes`
- daily work runs when `interval_hours` have passed since it last ran; the first tick after a deploy does not run it again
- source changes made in the app are written to the database, then exported to `sources.json`

Frontend pages. Every page sits under one top bar with the slash nav and a Cmd/Ctrl+K switcher. The top bar reads `feed / sources / blog`:

- `/`, `/read/:scopeKind/:scopeId`: the reader. Unread / starred / all, stream or by source, keyboard shortcuts (`?` lists them). The rail lists tracks and sources.
- `/posts/:postId`: the reading view of one post, with prev/next in feed order. Content only, with ↗ ☆ ⧉.
- `/tracks/:trackId`: one track's reading view. ⌘K has one "Tracks…" entry per track. Fetch, rename, main digest and delete are in the track group's ⋯ menu on the sources list.
- `/search`: search every post. `/save`: save any page. `/blog`: the engineering blog.
- News and Classics are views of the reader (the toolbar's view menu), of the Main feed or a track.
- `/settings/sources`: four tabs, `sources / discover / connections / ingestion`.
  - `sources`: the list, add/edit, tracks, health and cadence. The old `?tab=health` URL still works and opens the list with its status filter.
  - `discover` (`?tab=discover`): the sites and accounts 3+ of your sources link that you don't follow, and the stories they started.
  - `connections` (`?tab=connections`): provider credentials, one row per provider, stored encrypted. The only place API keys live: Telegram and Substack. To move keys from an older `.env`, run `docker compose exec backend python -m insight_core.scripts.import_env_secrets` once.
  - `ingestion` (`?tab=ingestion`): the run report, `Run due sources`, the scheduler interval and status, and the job history (`&sub=jobs`; `&job=<id>` opens one job).

The old analysis paths `/briefing*`, `/stories`, `/inbox`, `/experts` and the `/tracks` list redirect to `/` (stories today live in the feed, not at `/stories`). `/ingestion` and `/ingestion/:tab` redirect to `/settings/sources?tab=ingestion` and carry the tab across as `sub`, so `/ingestion/jobs` opens `?tab=ingestion&sub=jobs`. Every redirect replaces the history entry.

The UI is monochrome, dark by default, with a theme toggle in the top bar. The design rules live in `frontend/src/design/docs` (shown at `/design`).

## Ports

These are configurable in `.env`:

- `BACKEND_PORT`: host port for backend API, published on `127.0.0.1` only (the app reaches the API through the frontend's `/api`)
- `FRONTEND_PORT`: host port for frontend

The backend CORS config follows `FRONTEND_PUBLIC_URL` and can be overridden with `CORS_ALLOW_ORIGINS`.
For the frontend, the recommended default is to leave `VITE_API_URL` empty so the built UI uses same-origin `/api` through Nginx. That is the safest option for homelab access from other devices.

PostgreSQL is intentionally internal-only in Docker Compose. The backend and ingestion containers reach it over the Docker network as `postgres:5432`, so there is no host port conflict and no public DB exposure by default.

Logs are stored in the shared Docker volume mounted at `/app/logs` inside the backend and ingestion containers. The frontend reads those logs through the backend API, so you can inspect recent scheduler/fetch activity without shelling into the server.

## Normal Local Run Without Docker

If you want to run the project without Docker, you still need PostgreSQL running first.

Recommended database for normal local development:

- use the database from `DATABASE_URL`
- default local value from `.env.example` is `postgresql://insight:insight@localhost:5432/insight`

1. Install backend dependencies:

```bash
pip install -r backend/requirements.txt
```

2. Apply migrations:

```bash
python backend/insight_core/db/migrate.py
```

3. Start the backend:

```bash
(cd backend && uvicorn main:app --reload --port 8000 --env-file ../.env)
```

4. Start the ingestion scheduler in another shell:

```bash
python backend/insight_core/scripts/run_scheduler.py
```

5. Start the frontend in another shell if needed:

```bash
cd frontend
npm install
npm run dev
```

If you inspect another database, you will not see your sources and posts. The runtime database is always the one from `DATABASE_URL`.

Local logs are written under `./logs` when you run the project from the repo root.

## Manual Operations

A new source is due on the next tick (at most `ingest_tick_minutes` away). To fetch it now:

1. Open `/settings/sources` and add the source.
2. Use `Fetch now` on its row in the list, or in its detail sheet.
3. If you want a backfill, use the archive view in the Ingestion tab, or call `POST /api/archive/{source_id}/plan` and `POST /api/archive/{source_id}/run`.

The `ingestion` tab under sources (`/settings/sources?tab=ingestion`) has:

- `Run due sources`: one ingestion run over all enabled sources that fetches only the due ones, exactly as the next tick would. Ticking `Force all` ignores cadence and backoff and fetches every source, after a confirmation.
- the latest run report, and the scheduler status and settings: tick minutes and the daily-work interval. When the scheduler is not running, the tab says so.
- the job history, with a readable run report per job.

From the command line: `docker compose exec ingestion python -m insight_core.scripts.safe_ingest [--force] [--folder ID] [--source ID]` runs the same ingestion and prints the run report as JSON.

## Updating On Server

Because backend and frontend images are built from this repo, the normal update flow is:

```bash
git pull
docker compose build --pull
docker compose up -d --remove-orphans
```

Notes:

- `git pull` updates your local repo
- `docker compose build --pull` rebuilds local images and refreshes base images
- `docker compose up -d --remove-orphans` rolls the updated containers

If you changed backend/frontend code and want a clean rebuild:

```bash
docker compose build --no-cache backend ingestion frontend
docker compose up -d --remove-orphans
```

If only environment variables changed:

```bash
docker compose up -d --force-recreate
```

## Useful API Endpoints

Every route, with its body, is in the "HTTP API" table in `BACKEND.md`. The ones used most:

Ingestion runs are background jobs: these return `202` with a `job_id`, and `GET /api/operations/jobs/{job_id}` carries the run report when the job finishes.

- `POST /api/ingestion/run` (`{"force": false}`)
- `POST /api/sources/{source_id}/fetch-now` (`{"limit": N}`)
- `POST /api/folders/{folder_id}/ingest`

Reader and sources:

- `GET /api/feed` (`scope=all|source:<id>|folder:<id>`, `filter=unread|starred|all`, `view=stream|by_source`, `cursor`, `days` or `date`)
- `GET /api/feed/unread-counts`
- `GET /api/search` (`q`; `scope` none for every post, or `all|source:<id>|folder:<id>`; `filter=later|starred`, `days`, `order=newest|best`, `cursor`)
- `PUT /api/feed/read` (`{ids, read}`, or `{scope, through_cursor, newest_cursor}`)
- `GET /api/sources`, `POST /api/sources`
- `GET /api/sources/health`
- `PUT /api/sources/{source_id}/cadence`
- `GET /api/operations/scheduler`, `PUT /api/operations/scheduler`

Archive:

- `GET /api/archive/{source_id}/status`
- `POST /api/archive/{source_id}/plan`
- `POST /api/archive/{source_id}/run`

## External Source Infrastructure

For self-hosted sources you still need upstream services:

- Telegram RSS: `telegram.local`
- Nitter: `nitter.local`

References:

- `https://github.com/xtrime-ru/TelegramRSS`
- `https://github.com/sekai-soft/guide-nitter-self-hosting`

## Tests

Run the backend suite inside the image with `./run-tests.sh` (or `./run-tests.sh insight_core.tests.test_ingestion_runner` for one module). Several suites write rows, so each run creates a database of its own (`insight_run_<time>_<pid>_test`, a copy of a migrated template), and drops it when the run ends, so two runs at once never share rows; never the live `insight`. `JOBS=n` runs the whole suite in n shards at once. Prepared real-data copies, the real-data check's cache and when to run what: [WORKFLOW.md](WORKFLOW.md). `TEST_DATABASE_URL` uses a database of your own instead, and `MIGRATE=1` applies pending migrations to it first. The frontend: `cd frontend && npm run typecheck && npm test && npm run build`.

## Notes

- Archive and live ingestion store posts in the same format.
- Archive status is informational and does not block re-archiving.
- The migration runner now uses a PostgreSQL advisory lock so backend and ingestion can start safely at the same time.
