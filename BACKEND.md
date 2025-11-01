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

## Testing Your Feature (REQUIRED!)

**IMPORTANT:** Every backend feature MUST be tested before integration. Write tests in `backend/insight_core/tests/`.

### Test File Structure

Create a test file following this pattern:

```python
# test_your_feature.py
import sys
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

# Setup
setup_logging(debug_mode=True)
logger = get_component_logger("test_your_feature")

# Connect to DB
db_url = ensure_database()

class YourFeatureTest:
    def __init__(self, db_url: str):
        self.db_url = db_url
        # Initialize repos/services you need
    
    def test_repository_layer(self):
        """Test repository method directly"""
        # Your test code here
        pass
    
    def test_service_layer(self):
        """Test service layer"""
        # Your test code here
        pass

# Run tests
if __name__ == "__main__":
    test = YourFeatureTest(db_url)
    test.test_repository_layer()
    test.test_service_layer()
    logger.info("✅ All tests passed!")
```

### Testing Checklist

For each new feature, you MUST test:

1. ✅ **Repository Layer** - Test SQL queries return correct data
2. ✅ **Service Layer** - Test business logic works correctly
3. ✅ **API Layer** - Test HTTP endpoints (manual with curl/Postman)

### Example: Testing Posts by Source

```python
# test_posts_by_source.py
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.repo_posts import PostsRepository
from insight_core.services.posts_service import PostsService
from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

setup_logging(debug_mode=True)
logger = get_component_logger("test_posts_by_source")
db_url = ensure_database()

class PostsBySourceTest:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = PostsRepository(db_url)
        self.service = PostsService(db_url)

    def test_repo(self, source_id: str):
        """Test repository layer"""
        logger.info(f"Testing repo.get_posts_by_source({source_id})")
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                posts = self.repo.get_posts_by_source(cur, source_id)
                logger.info(f"Retrieved {len(posts)} posts")
                if posts:
                    logger.info(f"Sample post: {posts[0].get('title', 'No title')}")
                return posts
    
    def test_service(self, source_id: str):
        """Test service layer"""
        logger.info(f"Testing service.get_posts_by_source({source_id})")
        posts = self.service.get_posts_by_source(source_id)
        logger.info(f"Retrieved {len(posts)} posts")
        return posts

# Run test
if __name__ == "__main__":
    test = PostsBySourceTest(db_url)
    
    # Replace with actual source_id from your database
    test_source_id = "YOUR-SOURCE-UUID-HERE"
    
    # Test repository
    posts = test.test_repo(test_source_id)
    
    # Test service
    posts = test.test_service(test_source_id)
    
    logger.info("✅ All tests passed!")
```

### Running Tests

```bash
# Navigate to tests directory
cd backend/insight_core/tests/

# Run your test
python test_posts_by_source.py
```

### Manual API Testing

After backend tests pass, test the API endpoint:

```bash
# Start backend server
cd backend
python start_api.py

# In another terminal, test endpoint
curl http://localhost:8000/api/posts/source/{source_id}

# Or use httpie (prettier output)
http GET http://localhost:8000/api/posts/source/{source_id}
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

