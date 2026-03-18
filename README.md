# I.N.S.I.G.H.T.

I.N.S.I.G.H.T. is a source-ingestion and briefing system for controlled information flow. It collects posts from selected sources, stores them in PostgreSQL, builds daily briefings, and now supports one-time archive backfills plus ongoing live ingestion.

## What It Does

- Stores sources, posts, archive status, and briefings in PostgreSQL.
- Supports Telegram RSS, Nitter RSS, Reddit, and YouTube channels.
- Uses the same post storage path for archive and live ingestion.
- Generates daily briefings from already-ingested posts.
- Persists briefings in the database as markdown.
- Keeps `backend/insight_core/config/sources.json` and the database source registry in sync.

## Data Model

The runtime source of truth is the database pointed to by `DATABASE_URL`.

Important tables:

- `sources`: configured sources and per-source settings.
- `posts`: all archived and live-ingested posts.
- `briefings`: saved markdown briefing outputs.
- `youtube_watch_progress`: saved YouTube watch state.

Briefings are not saved as `.md` files on disk. They are saved in PostgreSQL in the `briefings` table:

- `render_format`: currently `markdown`
- `content`: markdown body
- `payload`: structured metadata for the briefing

This means the frontend should treat briefing responses as markdown strings and render them accordingly.

## Source Sync

`sources.json` and the database stay synchronized in both directions:

- On backend start: `sources.json -> DB`
- On scheduler cycle: `sources.json -> DB`
- On API source changes: `DB -> sources.json`

File path:

- `backend/insight_core/config/sources.json`
- Override with `INSIGHT_SOURCES_JSON_PATH`

This lets you keep editing `sources.json` manually without losing DB-backed behavior.

## Supported Source Types

- Telegram RSS via `https://telegram.local/rss/{username}/{page}`
- Nitter RSS via `https://nitter.local/{username}/rss`
- Reddit via `r/{subreddit}` or Reddit subreddit URLs
- YouTube via channel ID, `@handle`, `/channel/...`, or feed URL

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
- `ingestion`: long-running scheduler for safe ingestion and daily briefing generation

Scheduler defaults:

- ingestion every `20` hours
- `safe-ingest` skips sources fetched within the last `20` hours
- daily briefing generation enabled by default
- topic briefing generation disabled by default
- archive is never run automatically; archive remains a manual API action only

## Quick Start

1. Copy env file:

```bash
cp .env.example .env
```

2. Edit `.env` for your server.

Important values:

- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `POSTGRES_PORT`
- `BACKEND_PORT`
- `FRONTEND_PORT`
- `GEMINI_API_KEY` or `GOOGLE_API_KEY` if you want Gemini output
- `INSIGHT_SOURCES_JSON_PATH`

3. Optional: edit `backend/insight_core/config/sources.json` before first boot if you want some sources preloaded without using the frontend.

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
- backend runs migrations, syncs `sources.json -> DB`, and starts the API
- ingestion runs migrations, syncs `sources.json -> DB`, performs a scheduler cycle immediately, then sleeps until the next 20-hour cycle
- daily briefings are generated automatically after ingestion when enabled
- source changes made in the API are exported back into `sources.json`

## Ports

These are configurable in `.env`:

- `POSTGRES_PORT`: host port for PostgreSQL
- `BACKEND_PORT`: host port for backend API
- `FRONTEND_PORT`: host port for frontend

The backend CORS config follows `FRONTEND_PUBLIC_URL` and can be overridden with `CORS_ALLOW_ORIGINS`.
For the frontend, the recommended default is to leave `VITE_API_URL` empty so the built UI uses same-origin `/api` through Nginx. That is the safest option for homelab access from other devices.

## Normal Local Run Without Docker

If you want to run the project without Docker, you still need PostgreSQL running first.

Recommended database for normal local development:

- use the database from `DATABASE_URL`
- default local value from `.env.example` is `postgresql://insight:insight@localhost:5432/insight`

1. Install backend dependencies:

```bash
pip install -r requirements.txt
```

2. Apply migrations:

```bash
python backend/insight_core/db/migrate.py
```

3. Start the backend:

```bash
python backend/start_api.py
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

If you inspect another database, you will not see your sources/posts/briefings. The runtime database is always the one from `DATABASE_URL`.

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

If only environment variables changed:

```bash
docker compose up -d --force-recreate
```

## Daily Briefing Behavior

Daily briefings run on already-ingested posts for a specific day.

Current flow:

1. Ingestion stores posts in `posts`
2. `/api/daily` loads posts for the requested date from PostgreSQL
3. Gemini is attempted using the configured primary model
4. If a model is missing, rate-limited, quota-exhausted, or another configured failure occurs, the processor tries fallback Gemini models
5. If generation still fails, or Gemini is not configured at all, a deterministic markdown fallback briefing is generated
6. The final result is persisted to `briefings`

Returned API fields include:

- `briefing`
- `format`
- `saved_briefing_id`
- `posts_processed`

## Useful API Endpoints

- `POST /api/ingest-posts`
- `POST /api/safe-ingest-posts`
- `POST /api/daily`
- `POST /api/daily/topics`
- `GET /api/archive/{source_id}/status`
- `POST /api/archive/{source_id}/plan`
- `POST /api/archive/{source_id}/run`
- `POST /api/sources/sync/json-to-db`
- `POST /api/sources/sync/db-to-json`
- `POST /api/youtube/channel/videos`
- `POST /api/youtube/channel/roadmap`
- `POST /api/youtube/channel/playlists`
- `POST /api/youtube/video/evaluate`
- `POST /api/youtube/video/chat`
- `GET /api/youtube/progress/{video_id}`
- `PUT /api/youtube/progress/{video_id}`

## External Source Infrastructure

For self-hosted sources you still need upstream services:

- Telegram RSS: `telegram.local`
- Nitter: `nitter.local`

References:

- `https://github.com/xtrime-ru/TelegramRSS`
- `https://github.com/sekai-soft/guide-nitter-self-hosting`

## Notes

- Archive and live ingestion store posts in the same format.
- Archive status is informational and does not block re-archiving.
- YouTube roadmap and video tooling are backend-only right now.
- The migration runner now uses a PostgreSQL advisory lock so backend and ingestion can start safely at the same time.
