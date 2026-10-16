# Backend Development Guide

## Architecture Overview

The INSIGHT backend follows a layered architecture:

```
┌─────────────────────────────────────┐
│   API Layer (main.py)               │  FastAPI endpoints, one error handler
├─────────────────────────────────────┤
│   Service Layer (services/)         │  Business operations
├─────────────────────────────────────┤
│   Repository Layer (db/repo_*.py)   │  Database operations
└─────────────────────────────────────┘
```

## How to Implement New Features

### Step-by-Step Process

#### 1. **Repository Layer** (`backend/insight_core/db/repo_*.py`)
   - This is the **lowest layer** that directly interacts with the database
   - Contains raw SQL queries and cursor operations
   - Returns Python dictionaries or basic types

**Pattern:**
```python
def get_something(self, cur: Cursor, param: str) -> List[Dict[str, Any]]:
    """
    Docstring explaining what this does.
    
    Args:
        cur: Database cursor
        param: Description of parameter
        
    Returns:
        List of dictionaries with data
    """
    query = """
        SELECT field1, field2, field3
        FROM table_name
        WHERE condition = %s
        ORDER BY field1
    """
    cur.execute(query, (param,))
    rows = cur.fetchall()
    
    # Transform rows to dictionaries
    results = []
    for row in rows:
        results.append({
            'field1': row[0],
            'field2': row[1],
            'field3': str(row[2])  # Convert UUIDs to strings
        })
    
    self.logger.info(f"Retrieved {len(results)} items")
    return results
```

**Key Points:**
- Always use parameterized queries (`%s`) to prevent SQL injection
- Convert UUIDs to strings when returning
- Add appropriate logging
- Handle errors gracefully

---

#### 2. **Service Layer** (`backend/insight_core/services/*_service.py`)
   - Orchestrates business logic
   - Manages database connections and transactions
   - Calls repository methods

**Pattern:**
```python
from insight_core.db import database as db

def get_something(self, param: str) -> List[Dict[str, Any]]:
    """Get something from database."""
    with db.connection(self.db_url) as conn, conn.cursor() as cur:
        return self.repo.get_something(cur, param)

def save_something(self, param: str) -> None:
    with db.transaction(self.db_url) as cur:   # commits, or rolls back if it raises
        self.repo.save_something(cur, param)
```

**Key Points:**
- Every connection comes from `insight_core/db/database.py`: a small pool per process,
  a statement timeout (5 minutes by default) and the transaction scope. Never call
  `psycopg.connect` yourself (the migration runner is the exception).
- A connection commits when its block ends cleanly and rolls back when it raises
- Do not hold a connection across a network fetch
- Keep business logic here, not in repositories
- Services use repositories, never direct SQL

---

#### 3. **API Layer** (`backend/main.py`)
   - Defines HTTP endpoints and request models
   - Calls the services directly, through `services()` from `insight_core/services/registry.py`
   - Lets errors rise: one handler answers them (see Error Handling)

**Pattern:**
```python
@app.get("/api/something/{param}")
@error_detail("load something")
async def get_something(param: str):
    """Get something by parameter."""
    items = services().something.get_something(param)
    return {"success": True, "data": items, "total": len(items)}
```

**Key Points:**
- No try/except for service errors in a route. A `ValueError` is a 400 with its message, a
  not-found `LookupError` a 404, anything else a 500 "Could not load something". Bad stored
  data (`json.JSONDecodeError`, `UnicodeDecodeError`) is a 500 too. A path id
  (`post_id`, `folder_id`, `source_id`, `job_id`) that is not a uuid is a 404 before the
  route runs. Every 4xx is logged as a warning.
- `@error_detail(what)` names the "what" in that message. Every route answers its errors
  the same way: a real status code and `{"detail": ...}`.
- The registry builds the services once. Tests swap them with `registry.use(...)`.

---

## Database Schema Reference

### Sources Table
```sql
sources (
    id UUID PRIMARY KEY,
    platform TEXT NOT NULL,
    handle_or_url TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    settings JSONB DEFAULT '{}'::jsonb,  -- Optional source-specific settings
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    UNIQUE(platform, handle_or_url)
)
```

### Posts Table
```sql
posts (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    url TEXT NOT NULL UNIQUE,
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT now(),
    title TEXT,
    content TEXT,
    content_html TEXT,
    media_urls JSONB DEFAULT '[]',
    categories JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
```

---

## Source Settings System

### Settings Schema

Each source can have optional settings stored in the `settings` JSONB field:

```json
{
  "display_name": "Friendly Name",       // null = use handle_or_url
  "fetch_delay_seconds": 5,              // Minimum seconds between requests to this source's host
  "priority": 1,                         // Lower = fetch first (default: 999)
  "max_posts_per_fetch": 50              // Upper bound for one live fetch
}
```

**Defaults** depend on the platform (`SourcesRepository._platform_defaults` in `db/repo_sources.py`).
For `rss`: `fetch_delay_seconds` 1, `priority` 999, `max_posts_per_fetch` 20.

### How Settings Work

1. **Hardcoded defaults** apply to all sources (simple and consistent)
2. **Source settings** in database override defaults (only store what's different)
3. **Merged settings** = Defaults + Source overrides

**Example:**
```python
# Source has only display_name and priority set in database
{
    "display_name": "TechCrunch",
    "priority": 1
}

# Merged result (defaults + overrides)
{
    "display_name": "TechCrunch",       # from database (override)
    "fetch_delay_seconds": 1,           # from defaults
    "priority": 1,                      # from database (override)
    "max_posts_per_fetch": 50          # from defaults
}
```

### Accessing Settings in Code

**Repository Layer:**
```python
# Get settings for a source (defaults + overrides)
settings = repo.get_source_settings(cur, source_id)
# Returns: {"display_name": "...", "fetch_delay_seconds": 1, "priority": 999, ...}

# Update source settings (only stores overrides)
repo.update_source_settings(cur, source_id, {
    "display_name": "New Name",
    "priority": 5
})
```

**Service Layer:**
```python
# Get source with settings
source = service.get_source_with_settings(source_id)
# Returns: {...source fields..., "settings": {...merged settings...}}

# Get all sources with settings
sources = service.get_all_sources_with_settings()

# Update settings (with validation)
service.update_source_settings(source_id, {
    "display_name": "New Name",
    "fetch_delay_seconds": "10"  # Validated and converted to int
})
```

**API Usage:**
```bash
# Every source with its merged settings and post count
GET /api/sources

# Update source settings
PUT /api/sources/{source_id}/settings
Body: {"display_name": "New Name", "priority": 5}
```

### Settings in ingestion

The ingestion runner (`insight_core/ingestion/runner.py`) reads the merged settings:

- Due sources are fetched in `priority` order, then interleaved by host.
- `fetch_delay_seconds` is passed to `FetchGates.slot` and sets the minimum gap between
  requests to that source's host. The host floors in `ingestion/gates.py` still apply.
- `max_posts_per_fetch` feeds the cadence rules in `ingestion/schedule.py`, which decide each
  fetch's post limit.
- Each source's posts are saved as soon as its fetch finishes, so they reach the reader during
  the run; while it runs, the `ingestion_run` job's payload carries `sources: {done, total}`
  and `new_posts`.

How sources are fetched at all is described in
`backend/insight_core/docs/CONNECTOR_DEVELOPMENT_GUIDE.md` (source kinds).

---

## Common Patterns

### Listing Posts
Every post list goes through `ReaderRepository.list_posts(cur, FeedQuery(...), now=...)`
(`db/repo_reader.py`): scope, read-state filter, time bound, cursor and view in one query.
Add a filter there rather than writing a second listing query.

### Joining Posts with Sources
```sql
FROM posts p
JOIN sources s ON p.source_id = s.id
```

### Counting Posts
```sql
SELECT COUNT(*) FROM posts WHERE source_id = %s
```

---

## Testing Your Feature

Every backend feature needs tests in `backend/insight_core/tests/`. They are plain
`unittest` modules (`test_*.py`).

- Test through the module's interface: a route's status and JSON, saved rows, a `RunReport`.
- Prior art: `test_feed_routes` (routes over ASGI with `tests/_asgi.py`, a swapped service,
  the error handler), `test_feed_listing_routes` (real services), `test_repo_reader` and
  `test_ingestion_db` (a real database through the test database helpers),
  `test_ingestion_runner` and `test_source_kinds` (fakes, no network).

Run them inside the backend image, never on the host:

```bash
./run-tests.sh                                        # whole suite
./run-tests.sh insight_core.tests.test_feed_routes    # one module
MIGRATE=1 ./run-tests.sh                              # migrate the test database first
```

It uses the scratch database `insight_test`, never the live `insight`.

### Manual API Testing

```bash
# Start the API (or use docker compose)
cd backend
uvicorn main:app --reload --port 8000 --env-file ../.env

# In another terminal
curl "http://localhost:8000/api/feed?scope=source:{source_id}"
```

---

## Logging

Use the component logger:
```python
from insight_core.logs.core.logger_config import get_component_logger

self.logger = get_component_logger("component_name")
self.logger.info("Something happened")
self.logger.error("Something went wrong")
self.logger.debug("Detailed info")
```

---

## Error Handling

1. **Repository and service layers:** let errors propagate. Raise `ValueError` (bad input) or
   `LookupError` (not found) with a message a person can act on.
2. **API layer:** one handler, `service_error_response` in `main.py`, turns an error into a
   safe `{"detail": ...}` answer with a real status code. Other exceptions are logged with their traceback
   and answered "Could not ...": a driver message can carry a DSN or SQL, so it never reaches
   the response.
3. **Job tracking:** `OperationsService.try_start_job` / `try_append_job_event` /
   `try_finish_job` log a failed `job_runs` write and let the work go on.

---

## Example: Complete Feature Implementation

See the post listing for a complete example:
- Repository: `repo_reader.py::ReaderRepository.list_posts()` with a `FeedQuery`
- Service: `reader_service.py::ReaderService.list_posts()`
- API: `main.py::@app.get("/api/feed")`
- Tests: `test_repo_reader`, `test_feed_routes`, `test_feed_listing_routes`

---

## HTTP API

Every route in `main.py`. Errors are a non-2xx status with `{"detail": "<message>"}`: 400 bad
input, 404 not found, 409 conflict, 429 throttled, 500 "Could not ...", 503 job tracking down.
Ingestion and archive runs answer `202 {job_id}`; `GET /api/operations/jobs/{job_id}` carries
the result when the job finishes.

| Method | Path | Purpose | Body or query |
|---|---|---|---|
| GET | `/` | Liveness text | |
| GET | `/health` | Container health check | |
| GET | `/api/status` | System state for an agent: corpus, scheduler, folders, recent jobs | |
| GET | `/api/feed` | Every post list, newest first, one page | `scope=all\|source:<id>\|folder:<id>`, `filter=all\|unread\|starred`, `view=stream\|by_source`, `cursor`, `limit` (1-100), `days=N` or `date=YYYY-MM-DD` (UTC) |
| GET | `/api/feed/unread-counts` | Unread posts: total, per source, per folder | |
| PUT | `/api/feed/read` | Read state, answers `{updated, ids}` | `{ids, read}` (1-500 ids), or `{scope, through_cursor, newest_cursor}` to mark read through a cursor |
| GET | `/api/media` | One image of one post, through the 24-hour cache | `post`, `url` |
| GET | `/api/posts/item/{post_id}` | One post with its reader state | |
| POST | `/api/posts/item/{post_id}/opened` | Record an open (marks it read) | `{metadata?}` |
| POST | `/api/posts/item/{post_id}/reading-session` | Record time spent reading | `{durationSeconds, metadata?}` |
| POST | `/api/posts/item/{post_id}/favorite` | Star or unstar | `{favorited}` |
| POST | `/api/posts/item/{post_id}/reddit-comments` | Fetch a Reddit post's comments | `{limit?, refresh?, asyncMode?}` |
| GET | `/api/sources` | Every source with settings, `post_count`, `in_main_digest`; `total_posts` | |
| POST | `/api/sources` | Add a source | `{platform="rss", handle_or_url, display_name?, fetch_delay_seconds?, priority?, max_posts_per_fetch?, state="enabled"}` |
| PUT | `/api/sources/{source_id}/settings` | Edit settings | any of `{display_name, fetch_delay_seconds, priority, max_posts_per_fetch}` |
| PUT | `/api/sources/{source_id}/enabled` | Enable or disable | `{enabled}` |
| PUT | `/api/sources/{source_id}/main-digest` | In or out of the "all" feed | `{in_main_digest}` |
| PUT | `/api/sources/{source_id}/cadence` | Set or clear the fetch interval override | `{override_hours}` (1-2160, or null) |
| DELETE | `/api/sources/{source_id}` | Delete a source and its posts | |
| GET | `/api/sources/{source_id}/folders` | The folder ids a source is in | |
| GET | `/api/sources/health` | Every source's schedule and fetch health, plus a summary | |
| POST | `/api/sources/{source_id}/fetch-now` | Fetch one source now (202 job) | `{limit?}` |
| GET | `/api/folders` | Folders and tracks with counts | |
| POST | `/api/folders` | Create a folder or track | `{name, kind?="folder"\|"track", description?, sort_order?, exclude_from_main_digest?, match_keywords?}` |
| PUT | `/api/folders/{folder_id}` | Edit a folder | any of the create fields |
| DELETE | `/api/folders/{folder_id}` | Delete a folder (its sources stay) | |
| POST | `/api/folders/{folder_id}/sources` | Add a source to a folder | `{source_id}` |
| DELETE | `/api/folders/{folder_id}/sources/{source_id}` | Remove a source from a folder | |
| PUT | `/api/folders/{folder_id}/main-digest` | Every source of a folder in or out of the "all" feed | `{in_main_digest}` |
| POST | `/api/folders/{folder_id}/ingest` | Fetch a folder's enabled sources now (202 job) | `{limit?}` |
| GET | `/api/archive/catalog` | Enabled sources with their archive state | |
| GET | `/api/archive/{source_id}/status` | One source's archive state and newest archive job | |
| POST | `/api/archive/{source_id}/plan` | Estimate an archive run | `{desiredPosts, resume?, pageDelaySeconds?, batchSize?, batchCooldownSeconds?}` |
| POST | `/api/archive/{source_id}/run` | Run an archive (202 job with `background: true`) | as plan, plus `{background?}` |
| POST | `/api/ingestion/run` | Run the ingestion cycle now (202 job) | `{force?}` |
| GET | `/api/ingestion/logs` | Tail of a log file | `log`, `lines` (1-1000) |
| GET | `/api/operations/overview` | Recent jobs, source health, alerts | |
| GET | `/api/operations/jobs/{job_id}` | One job with its result | |
| GET | `/api/operations/scheduler` | Scheduler settings and state | |
| PUT | `/api/operations/scheduler` | Edit scheduler settings | `{intervalHours?, syncSourcesEachCycle?, ingestTickMinutes?}` (tick >= 15) |
| GET | `/api/credentials` | Every connection, without its values | |
| PUT | `/api/credentials/{provider}/{key}` | Save one secret | `{value}` |
| DELETE | `/api/credentials/{provider}/{key}` | Remove one secret | |
| POST | `/api/credentials/{provider}/test` | Test a connection | |
| POST | `/api/credentials/telegram/login/start` | Telegram sign-in: send the code | `{phone}` |
| POST | `/api/credentials/telegram/login/code` | Telegram sign-in: the code | `{code}` |
| POST | `/api/credentials/telegram/login/password` | Telegram sign-in: two-step password | `{password}` |
| POST | `/api/credentials/telegram/login/cancel` | Cancel the sign-in | |
| POST | `/api/youtube/channel/videos` | List a channel's newest videos | `{source, limit?}` |
| GET | `/api/youtube/progress/{video_id}` | Watch progress of a video | |
| PUT | `/api/youtube/progress/{video_id}` | Save watch progress | `{videoUrl, title, progressSeconds, durationSeconds?, sourceId?, notesMarkdown?, completed?}` |
