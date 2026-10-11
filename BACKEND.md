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
  a statement timeout (60 s by default) and the transaction scope. Never call
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
  not-found `LookupError` a 404, anything else a 500 "Could not load something".
- `@error_detail(what)` answers errors as HTTP errors with `{"detail": ...}` (Mark IX
  routes). `@error_envelope(what, **fields)` answers them as HTTP 200
  `{"success": false, "error": ..., **fields}`, for the older routes whose callers expect it.
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
# Get source settings
GET /api/sources/{source_id}/settings

# Update source settings
PUT /api/sources/{source_id}/settings
Body: {"display_name": "New Name", "priority": 5}

# Get all sources with settings
GET /api/sources/with-settings
```

### Settings in ingestion

The ingestion runner (`insight_core/ingestion/runner.py`) reads the merged settings:

- Due sources are fetched in `priority` order, then interleaved by host.
- `fetch_delay_seconds` is passed to `FetchGates.slot` and sets the minimum gap between
  requests to that source's host. The host floors in `ingestion/gates.py` still apply.
- `max_posts_per_fetch` feeds the cadence rules in `ingestion/schedule.py`, which decide each
  fetch's post limit.

How sources are fetched at all is described in
`backend/insight_core/docs/CONNECTOR_DEVELOPMENT_GUIDE.md` (source kinds).

---

## Common Patterns

### Filtering Posts by Date
```sql
WHERE DATE(COALESCE(p.published_at, p.fetched_at)) = %s
```

### Filtering Posts by Source
```sql
WHERE p.source_id = %s
```

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
  the error handler), `test_posts_by_source_routes` (real services), `test_repo_reader` and
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
curl http://localhost:8000/api/posts/source/{source_id}
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
   safe JSON answer in the route's shape. Other exceptions are logged with their traceback
   and answered "Could not ...": a driver message can carry a DSN or SQL, so it never reaches
   the response.
3. **Job tracking:** `OperationsService.try_start_job` / `try_append_job_event` /
   `try_finish_job` log a failed `job_runs` write and let the work go on.

---

## Example: Complete Feature Implementation

See the `get_posts_by_date` feature for a complete example:
- Repository: `repo_posts.py::get_posts_by_date()`
- Service: `posts_service.py::get_posts_by_date()`
- API: `main.py::@app.get("/api/posts/{date}")`
