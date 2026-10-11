# Backend Development Guide

## Architecture Overview

The INSIGHT backend follows a layered architecture:

```
┌─────────────────────────────────────┐
│   API Layer (main.py)               │  FastAPI endpoints
├─────────────────────────────────────┤
│   Bridge Layer (insight_api_bridge) │  Business logic coordination
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
def get_something(self, param: str) -> List[Dict[str, Any]]:
    """Get something from database."""
    with psycopg.connect(self.db_url) as conn:
        with conn.cursor() as cur:
            return self.repo.get_something(cur, param)
```

**Key Points:**
- Use context managers for connections/cursors (automatic cleanup)
- Call `conn.commit()` after write operations
- Keep business logic here, not in repositories
- Services use repositories, never direct SQL

---

#### 3. **Bridge Layer** (`backend/insight_api_bridge.py`)
   - Coordinates between API and services
   - Transforms data for frontend consumption
   - Handles data validation and error formatting

**Pattern:**
```python
def get_something_by_param(self, param_str: str) -> Dict[str, Any]:
    """
    Get something for frontend display.
    
    Args:
        param_str: String parameter from frontend
        
    Returns:
        Dict with success, data, and metadata
    """
    try:
        # Parse/validate input
        parsed_param = self._parse_param(param_str)
        
        # Get data from service
        items = self.service.get_something(parsed_param)
        
        return {
            "success": True,
            "data": items,
            "total": len(items),
            "param": param_str
        }
        
    except ValueError as e:
        return {
            "success": False,
            "error": f"Invalid parameter: {param_str}",
            "data": []
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "data": []
        }
```

**Key Points:**
- Always return consistent response format
- Include success/error status
- Handle all exceptions
- Transform data for frontend needs

---

#### 4. **API Layer** (`backend/main.py`)
   - Defines HTTP endpoints
   - Validates request models
   - Returns JSON responses

**Pattern:**
```python
@app.get("/api/something/{param}")
async def get_something(param: str):
    """Get something by parameter."""
    try:
        logger.info(f"📋 Fetching something for: {param}")
        
        result = api_bridge.get_something_by_param(param)
        
        if result.get("success"):
            logger.info(f"✅ Retrieved {result.get('total', 0)} items")
        
        return result
        
    except Exception as e:
        logger.exception("Failed to get something")
        return {"success": False, "error": str(e)}
```

**Key Points:**
- Use FastAPI route decorators (`@app.get`, `@app.post`, etc.)
- Add logging at API level
- Let bridge layer handle business errors
- Return JSON directly

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

- Test through the module's interface: a route function's JSON, saved rows, a `RunReport`.
- Prior art: `test_feed_routes` (route functions, error redaction), `test_repo_reader` and
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

## Error Handling Best Practices

1. **Repository Layer:** Let errors propagate (database errors are important)
2. **Service Layer:** Catch specific errors and add context
3. **Bridge Layer:** Catch all errors and format for frontend
4. **API Layer:** Log errors and return consistent error responses

---

## Example: Complete Feature Implementation

See the `get_posts_by_date` feature for a complete example:
- Repository: `repo_posts.py::get_posts_by_date()`
- Service: `posts_service.py::get_posts_by_date()`
- Bridge: `insight_api_bridge.py::get_posts_by_date()`
- API: `main.py::@app.get("/api/posts/{date}")`

