# Quick start

The shortest path from a clone to reading your sources. `DEPLOYMENT.md` has the details.

## With Docker (recommended)

```bash
cp .env.example .env          # set DB_*, BACKEND_PORT, FRONTEND_PORT; leave INSIGHT_ANALYSIS=off
docker compose up -d --build
docker compose ps             # postgres, backend, ingestion and frontend should be up
```

Open `http://localhost:${FRONTEND_PORT}`. API keys never go in `.env`: add them in the app under
**Sources → Connections** (Telegram, Substack; with analysis on, Gemini). They are
stored encrypted in the database. Coming from an older `.env` that still holds keys? Run
`docker compose exec backend python -m insight_core.scripts.import_env_secrets` once, then delete those lines.

## Without Docker (development)

PostgreSQL must be running and `DATABASE_URL` in `.env` must point at it.

```bash
# Terminal 1: API on :8000
pip install -r backend/requirements.txt
python backend/insight_core/db/migrate.py
(cd backend && uvicorn main:app --reload --port 8000 --env-file ../.env)

# Terminal 2: UI on :5173 (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`. Run the scheduler too (`python backend/insight_core/scripts/run_scheduler.py`)
if you want sources fetched on their cadence.

## The app: three places

The top bar reads `feed / sources`.

- **feed** (`/`): every source in one reading flow. The rail holds tracks and sources.
- **post** (`/posts/:id`): the content only, with open original, star and copy.
- **sources** (`/settings/sources`): tabs `sources / connections / ingestion`. The `ingestion`
  tab holds the run report, `Run due sources`, the scheduler status and the job history.

That is the reading-only app, and it is the default. Briefings, stories, the inbox and experts sit
behind one switch, `INSIGHT_ANALYSIS`. To bring them back, set `INSIGHT_ANALYSIS=on` and
`VITE_INSIGHT_ANALYSIS=on` in `.env`, then run `docker compose up -d --build`. They also need
a Gemini API key, added in Sources → Connections → Gemini. The README's "Analysis switch" section has the details. Nothing is deleted
either way.

## First steps in the app

1. **Add sources.** `sources` in the top bar (`/settings/sources`), or edit
   `backend/insight_core/config/sources.json` before the first start.
2. **Fetch.** New sources are due on the next ingestion tick. To fetch now, use `Fetch now` on a
   source's row, or `Run due sources` in the ingestion tab (`/settings/sources?tab=ingestion`).
3. **Read.** `/` is the unread feed for the main digest. `j`/`k` move, `o` opens, `m` toggles
   read, `s` stars, `?` lists every shortcut. Tracks (folders of sources) filter the feed from the
   rail, and ⌘K jumps to any track.

## When nothing shows up

- **The feed is empty.** Switch the filter to `all`. If it is still empty, nothing has been
  fetched yet: use `Run due sources` in the ingestion tab and watch its run report.
- **The ingestion tab says the scheduler is not running.** Start the `ingestion` container
  (`docker compose up -d ingestion`), or `run_scheduler.py` without Docker.
- **"Network error".** The API is not reachable. Check `http://localhost:8000/health` and the
  backend logs (`docker compose logs backend`, or the API terminal).
- **A source never fetches.** Its row in the sources list says why: not due yet (with the next due
  time), backing off after errors, or unavailable (for example no Telegram session or yt-dlp off).
- **The database does not exist.** `python backend/insight_core/db/ensure_db.py`, then
  `python backend/insight_core/db/migrate.py`.
