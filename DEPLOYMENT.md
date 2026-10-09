# INSIGHT deployment guide (Mark IX)

INSIGHT runs as four Docker Compose services from `docker-compose.yml`. The README has the
feature overview; this file covers deploying, updating and troubleshooting.

| Service | Container | What it does |
| --- | --- | --- |
| `postgres` | `insight-db` | PostgreSQL 15 with pgvector. Internal to the Docker network only. |
| `backend` | `insight-api` | FastAPI on port 8000 (`BACKEND_PORT` on the host). Runs migrations and `sources.json -> DB` on start. |
| `ingestion` | `insight-ingestion` | The scheduler (`scripts/run_scheduler.py`): an ingestion tick every `ingest_tick_minutes`, daily work every `interval_hours`. |
| `frontend` | `insight-frontend` | The built React app behind Nginx (`FRONTEND_PORT`), proxying `/api` to the backend. |

## Prerequisites

- Docker with the Compose plugin.
- For development without Docker: Python 3.12, PostgreSQL 15, Node.js 20.19+ (or 22.12+) and npm 10.

## First deploy

```bash
cp .env.example .env        # then edit it: DB_*, ports, GEMINI_API_KEY, TELEGRAM_* if used
docker compose up -d --build
docker compose ps
docker compose logs -f backend ingestion
```

On start, both `backend` and `ingestion` run `insight_core/db/migrate.py`. The migration runner
takes a PostgreSQL advisory lock, so the two containers can start together safely. Applied
migrations are recorded and never re-run.

Open `http://<host>:${FRONTEND_PORT}`. `/` is the reader. API docs are at
`http://<host>:${BACKEND_PORT}/docs`.

### Telegram channels over MTProto (optional)

Bare-handle Telegram sources need `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and a session file.
Create the session once, interactively:

```bash
docker compose exec ingestion python -m insight_core.scripts.telegram_login
docker compose exec ingestion python -m insight_core.scripts.telegram_login --check
```

The session is written to `TELEGRAM_SESSION_PATH` (default
`/app/insight_core/config/telegram/insight.session`, inside the bind-mounted `config/`, so it
survives rebuilds). A path without the `.session` suffix gets it added, as Telethon does. Until a
session exists those sources show as unavailable in the health table, not as failing.

## Updating

```bash
git pull
docker exec insight-db pg_dump -U insight insight > /tmp/insight_pre_update.sql   # back up first
docker compose build --pull
docker compose up -d --remove-orphans
```

If only environment variables changed: `docker compose up -d --force-recreate`.

## Development mode

```bash
# backend (needs PostgreSQL and DATABASE_URL in .env)
pip install -r requirements.txt
python backend/insight_core/db/migrate.py
python backend/start_api.py

# scheduler, in another shell (optional)
python backend/insight_core/scripts/run_scheduler.py

# frontend, in another shell
cd frontend && npm install && npm run dev
```

Vite serves on `http://localhost:5173` (bound to all interfaces) and proxies `/api` to
`http://localhost:8000`. To point the dev UI at another backend, set `VITE_API_URL` and restart Vite.

## Tests

- Backend: `./run-tests.sh [module]` builds the image and runs the suite inside it, against the
  scratch database `insight_test` by default (never the live `insight`). Override with
  `TEST_DATABASE_URL`. `MIGRATE=1` migrates that database first.
- Frontend: `cd frontend && npm run typecheck && npm test && npm run build`.

## Troubleshooting

- **Feed is stale ("last fetch N days ago").** Check that the scheduler runs:
  `docker compose ps ingestion` and `docker compose logs --tail=100 ingestion`. The
  `/ingestion` page shows the next tick and the last run report.
- **A source shows failing.** Open `/settings/sources?tab=health&status=error`. The row shows the
  last error and when the next retry is. `Fetch now` retries it immediately.
- **Run reports `skipped_busy`.** Another all-sources run holds the run lock. It finishes on its
  own; folder and single-source fetches are not blocked by it.
- **The frontend shows network errors.** Check `docker compose logs backend` and that
  `http://<host>:${BACKEND_PORT}/health` answers. Leave `VITE_API_URL` empty in Docker so the UI
  uses same-origin `/api` through Nginx.
