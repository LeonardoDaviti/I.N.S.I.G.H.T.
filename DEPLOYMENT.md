# INSIGHT deployment guide (Mark IX)

INSIGHT runs as four Docker Compose services from `docker-compose.yml`. The README has the
feature overview; this file covers deploying, updating and troubleshooting.

| Service | Container | What it does |
| --- | --- | --- |
| `postgres` | `insight-db` | PostgreSQL 15 with pgvector. Internal to the Docker network only. |
| `backend` | `insight-api` | FastAPI on port 8000 (`BACKEND_PORT` on the host). Runs migrations and `sources.json -> DB` on start. |
| `ingestion` | `insight-ingestion` | The scheduler (`scripts/run_scheduler.py`): an ingestion tick every `ingest_tick_minutes`, daily work every `interval_hours`. |
| `frontend` | `insight-frontend` | The built React app behind Nginx (`FRONTEND_PORT`), proxying `/api` to the backend. |

## Networking

- All four services share one bridge network, `insight-network`. The API and the scheduler
  reach the database as `postgres:5432`. PostgreSQL has no host port.
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
`http://<host>:${BACKEND_PORT}/docs`.

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

## Updating

```bash
git pull
docker exec insight-db pg_dump -U insight insight > /tmp/insight_pre_update.sql   # back up first
docker compose build --pull
docker compose up -d --remove-orphans
```

`./update` does the same without the dump: `git pull`, `docker compose down`, build, `up -d`.
If only environment variables changed: `docker compose up -d --force-recreate`.

An older `.env` may still hold `INSIGHT_ANALYSIS`, `VITE_INSIGHT_ANALYSIS`, `GEMINI_*`,
`GOOGLE_API_KEY` or `INSIGHT_GENERATE_*_BRIEFING` from the analysis version. Nothing reads them
any more, so they are harmless; delete them when convenient. A Gemini key saved in Connections
stays in the `credentials` table and is no longer shown.

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
```

It makes real requests to the sites (2s apart per site). See
`backend/insight_core/scripts/README.md`, "Full text".

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

- Backend: `./run-tests.sh [module]` builds the image and runs the suite inside it, against the
  scratch database `insight_test` by default (never the live `insight`). Override with
  `TEST_DATABASE_URL`. `MIGRATE=1` migrates that database first.
- Frontend: `cd frontend && npm run typecheck && npm test && npm run build`.

## Troubleshooting

- **Feed is stale ("last fetch N days ago").** Check that the scheduler runs:
  `docker compose ps ingestion` and `docker compose logs --tail=100 ingestion`. The
  ingestion tab (`/settings/sources?tab=ingestion`) shows the scheduler status and the last run report.
- **A source shows failing.** Open `/settings/sources?tab=health&status=error`. The row shows the
  last error and when the next retry is. `Fetch now` retries it immediately.
- **Run reports `skipped_busy`.** Another all-sources run holds the run lock. It finishes on its
  own; folder and single-source fetches are not blocked by it.
- **The frontend shows network errors.** Check `docker compose logs backend` and that
  `http://<host>:${BACKEND_PORT}/health` answers. Leave `VITE_API_URL` empty in Docker so the UI
  uses same-origin `/api` through Nginx.
