# Quick start

The shortest path from a clone to reading your sources. `DEPLOYMENT.md` has the details.

## With Docker (recommended)

```bash
cp .env.example .env          # set DB_*, BACKEND_PORT, FRONTEND_PORT; GEMINI_API_KEY is optional
docker compose up -d --build
docker compose ps             # postgres, backend, ingestion and frontend should be up
```

Open `http://localhost:${FRONTEND_PORT}`.

## Without Docker (development)

PostgreSQL must be running and `DATABASE_URL` in `.env` must point at it.

```bash
# Terminal 1: API on :8000
pip install -r backend/requirements.txt
python backend/insight_core/db/migrate.py
python backend/start_api.py

# Terminal 2: UI on :5173 (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`. Run the scheduler too (`python backend/insight_core/scripts/run_scheduler.py`)
if you want sources fetched on their cadence.

## First steps in the app

1. **Add sources.** `sources` in the top bar (`/settings/sources`), or edit
   `backend/insight_core/config/sources.json` before the first start.
2. **Fetch.** New sources are due on the next ingestion tick. To fetch now, use `Fetch now` on a
   row of the health tab (`/settings/sources?tab=health`), or `Run due sources` on `/ingestion`.
3. **Read.** `/` is the unread feed for the main digest. `j`/`k` move, `o` opens, `m` toggles
   read, `s` stars, `?` lists every shortcut. Tracks (folders of sources) filter the feed from the
   rail.

## When nothing shows up

- **The feed is empty.** Switch the filter to `all`. If it is still empty, nothing has been
  fetched yet: run a cycle on `/ingestion` and watch its run report.
- **"Network error".** The API is not reachable. Check `http://localhost:8000/health` and the
  backend logs (`docker compose logs backend`, or the API terminal).
- **A source never fetches.** Its row in the health tab says why: not due yet (with the next due
  time), backing off after errors, or unavailable (for example no Telegram session or yt-dlp off).
- **The database does not exist.** `python backend/insight_core/db/ensure_db.py`, then
  `python backend/insight_core/db/migrate.py`.
