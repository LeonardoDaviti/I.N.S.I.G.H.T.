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
  "page_watch": {"prefix": "/news/"}     // Follow a page without a feed (issue 0028)
}
```

**Defaults** depend on the platform (`SourcesRepository._platform_defaults` in `db/repo_sources.py`).
For `rss`: `fetch_delay_seconds` 1, `priority` 999, `max_posts_per_fetch` 20. The posts per
fetch is the platform default only: the API does not accept it, and migration 0029 removed the
values stored before (issue 0029).

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
    "max_posts_per_fetch": 20          # from defaults
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
  requests to that source's host. The host's learned gap (below) still applies.
- `max_posts_per_fetch` (the platform default) feeds the cadence rules in `ingestion/schedule.py`, which decide each
  fetch's post limit.
- Each source's posts are saved as soon as its fetch finishes, so they reach the reader during
  the run; while it runs, the `ingestion_run` job's payload carries `sources: {done, total}`
  and `new_posts`.
- A run's phases are `decided`, one `source` per fetched source (with a `slowed` before it
  when a host limited us), then `saved`, which is 100 %: nothing runs after the last save.
  Each fetched source records the cheap half of `settings.archive` (kind, stored count, last
  live fetch); a run never measures a source's size. Only planning an archive does
  (`last_inspected_at`).

### Archives continue below the stored posts

`SourceFetchService.plan_archive` measures the source (`kind.inspect`) and picks the start:
a resumable checkpoint (one without `completed_at`) when resuming, else
`kind.start_checkpoint(source, stored)`, which jumps below the oldest stored post (by
position, or by date for Nitter's search RSS) one page early, else the newest post. The plan
reports `continues_from`, `older_posts` (available - stored, or null when the source reports
no size) and the estimate for them. An archive runs until the source ends, and reuses its
plan's measurement.

### Pacing: a gap per host that learns

`HostLimiter` in `ingestion/gates.py` spaces request starts to one host key (`reddit.com`,
`platform:reddit`, `substack.com`, the Telegram and Nitter bridges) by that host's gap. The
gap starts at the host's floor (`HOST_FLOORS`, else 0) and is kept for the life of the
process, so it carries from one hourly run to the next; a restart starts fresh. Each process
keeps its own pace: the scheduler's hourly runs and the API's manual runs and archives do not
share one (accepted; nothing is stored).

- `KindHttp` only classifies failures: each is an `HttpError` (a `ValueError`) with
  `status`, `retry_after` and `timed_out`. The Telegram bridge's JSON "Too many requests"
  answer is raised as a 429.
- On a 429 or a timeout the runner, still inside the source's slot, waits what the site asks
  (Retry-After, else 60 s; at most 120 s), doubles the host's gap (at least 5 s, at most
  120 s), adds a `slowed` event to the job ("reddit.com: too many requests, slowing to
  16 s") and fetches once more. A second failure fails the source (backoff applies).
- 20 successes in a row take a quarter off the gap, never below the floor.
- An archive takes the same `FetchGates.slot` for every page, so a run and an archive on one
  host are spaced together. The kind's pause after a page (its page delay, or the batch
  cooldown on a batch boundary) is the slot's minimum interval, so two pages are
  max(host gap, pause) apart, never the sum; kinds do not sleep between archive pages. The
  plan's time estimate uses the same rule with the host's floor. On a 429 or a timeout it waits, then asks again from the last
  recorded checkpoint; twice in a row it pauses: the job succeeds with `paused: true` and
  `paused_reason` ("reddit.com is limiting us"), and the checkpoint stays resumable.

### Reading an article page

One reader turns an article page into a post body: `parsing.read_article_page(html,
base_url)` / `extract_article_html` in `ingestion/kinds/parsing.py`, used by full text
(`full_text.read_article`), page watch (`page_watch.post_from`) and five site adapters. It
drops chrome (named elements and class names, never an element holding most of the page's
paragraph text), picks the article (`<article>`, `<main>`, a content class, else the block
holding most paragraphs) and keeps its text blocks, code, captions and images in page order;
the rules are commented in place.

It is heuristics, so it is tested on real pages: `tests/fixtures/pages/` holds ~25 saved
article pages and `expectations.json` (title, first and last sentence, image count, chrome
words that must not appear, known gaps with their reasons), checked by `test_page_corpus`
(issue 0032). A reader change must keep every page passing; a fix for one site that breaks
another fails the suite. `scripts/refresh_page_corpus.py` re-reads the pages when a site
redesigns (owner-run, see `scripts/README.md`).

Every page read records how well it went, in the post's `metadata.page_read`
(`repo_posts.PAGE_READ_KEY`; page watch and full text, kept when a later feed fetch keeps the
body): `{page_images, kept_images, text_chars, short_opening}` (`parsing.read_fidelity`).
`page_images` is an estimate from the article block the reader chose (related cards and
sidebars it dropped never count): images with an address, no pixel, icon or avatar;
`kept_images` the ones kept; `short_opening` a first block after the title under 25
characters ("Share:"), a hint of chrome left in. It shows in two places:
- source health: the row's `reading_notice`, from the source's 8 newest page reads, when at
  least 3 of them and half lost most of their images (3 or more, under half kept): "Pages from
  this source lose most of their images (5 of the last 8)"; or when at least 4 and three
  quarters opened short. The source sheet shows it as a quiet line. None otherwise.
- the run's job events: a source's line adds "· 2 of 3 pages lost most of their images", and
  the ingestion log says the same.

### A broken source finds its replacement (the source doctor)

`ingestion/source_doctor.py` (issue 0036): the runner shows it every failed fetch, with the
exception and the fetch state that failure wrote (`SourceDoctor.after_failure`, outside the
save lock; it never raises).

- **When:** an RSS (`generic_rss`) or page-watch source, never one a kind or site adapter
  reads directly; at 3 failures in a row, or at once on HTTP 404/410 or an answer that does
  not parse as a feed. At most once a day per source (`source_fetch_state.doctor_checked_at`,
  migration 0032), and not again in a streak whose finding was dismissed.
- **First:** the old address is read again; a feed that parses (a followed page that still
  lists articles) was a temporary error: recorded as `working_again` ("temporary error, working
  again"), nothing suggested, no finding on the health row, nothing else looked at.
- **Look:** the feed finder on the address (it reads the section and home page itself) and
  on a deeper section (`/a/b/rss` -> `/a/b/`), skipping the address itself; a feed on the
  source's site must stay within its section (`/oldnewthing/` for `/oldnewthing/feed`; a source
  at the root takes any). No feed: the page-watch preview of the section (for a root source the
  address itself), which must read at least one article.
- **Act:** a feed on the same site (`www.` ignored) while the old address is gone (404/410)
  is switched to, with a `doctor` job event ("Arena: feed moved, now following
  arena.ai/blog/feed.xml"). Anything else is stored in `doctor_finding`
  (`{replacement: {kind, url, title, found, prefix} | null, dismissed}`) and read by the
  health row as `doctor_looked_at` and `replacement`. A fetch that works clears it.
- **Switch** (`SourceConfigSyncService.switch_source`, used by the doctor and the route): the
  new `handle_or_url` and `settings.page_watch` (set or removed) and a clean fetch state, in
  one transaction; the id, name, tracks, read state and posts stay. Then sources.json is
  rewritten; when it cannot be, the switch is undone, because a file still naming the old
  address would make the next sync re-add it and mirror-delete the switched source. Nothing
  is re-fetched: posts match by URL, and an archive brings the older ones.
- `KindRegistry` caches by platform, address and whether `settings.page_watch` is set, so an
  address once asked about as a feed resolves as page_watch once a source follows it.

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
| GET | `/api/feed` | Every post list, newest first (Later: oldest saved first), one page | `scope=all\|source:<id>\|folder:<id>`, `filter=all\|unread\|later\|starred` (starred is Keep, "Kept"; later on `all` holds every source), `view=stream\|by_source`, `cursor`, `limit` (1-100), `days=N` or `date=YYYY-MM-DD` (UTC) |
| GET | `/api/feed/unread-counts` | Unread posts: total, per source, per folder; `later: {count, minutes}` | |
| PUT | `/api/feed/read` | Read state, answers `{updated, ids}`; marking read by ids also takes the posts out of Later | `{ids, read, keep_later?}` (1-500 ids; `keep_later`: the read is only an open), or `{scope, through_cursor, newest_cursor}` to mark read through a cursor |
| GET | `/api/media` | One image of one post, through the 24-hour cache | `post`, `url` |
| GET | `/api/posts/item/{post_id}` | One post with its reader state | |
| POST | `/api/posts/item/{post_id}/opened` | Record an open (marks it read; it stays in Later) | `{metadata?}` |
| POST | `/api/posts/item/{post_id}/reading-session` | Record time spent reading | `{durationSeconds, metadata?}` |
| PUT | `/api/feed/later` | Read later (issue 0022): put posts in Later or take them out, answers `{updated, ids}` | `{ids, later}` (1-500 ids) |
| POST | `/api/posts/item/{post_id}/favorite` | Star (Keep) or unstar | `{favorited}` |
| PUT | `/api/posts/item/{post_id}/position` | Where a long post was left (issue 0030); `block: null` clears it. Marking a post read clears it too | `{block, blocks}` (`0 <= block < blocks`) |
| GET | `/api/sources` | Every source with settings, `post_count`, `in_main_digest`; `total_posts` | |
| POST | `/api/sources` | Add a source | `{platform="rss", handle_or_url, display_name?, fetch_delay_seconds?, priority?, state="enabled", page_watch?}` (`page_watch: {prefix?}` follows a page without a feed, stored as `settings.page_watch`) |
| GET | `/api/sources/export.opml` | Every source as OPML 2.0 (`text/x-opml`, a download `insight-sources.opml`, issue 0035): one outline per track in track order, each source under its first track (`category` names all its tracks), then the sources in none (the built-in Saved source, issue 0031, is left out). A source outline: `text`/`title` (name or address), `xmlUrl` (its address), and the `insight:` attributes (namespace `https://insight.local/opml`) `displayName`, `pageWatchPrefix` (followed pages, with `htmlUrl`; empty: the path is inferred) and `platform` (when not rss) | |
| POST | `/api/sources/find-feed` | The feeds for any page address (`ingestion/feed_finder.py`, under 10 s): `{status: feed\|found\|direct\|none, feeds: [{url, title}], homepage, pages}`; for a site's home page with no feed (issue 0041) `homepage: true` and `pages`, its own blog or news pages that can be followed instead, each with its page-watch preview `{url, prefix, found, sitemap, items}`, the most articles first (previewed at once, within 15 s more) | `{url}` (no scheme: https) |
| POST | `/api/sources/page-watch/preview` | Following a page without a feed (`ingestion/kinds/page_watch.py`, issue 0028): `{prefix, found, sitemap, items: [{url, title, published_at}]}`, `found` the article URLs under the prefix (listing links and sitemap), `items` the first 5 read; no items: its articles need a browser. 400 when the page cannot be read (its status only, never the site's answer) | `{url, prefix?}` (no scheme: https; only http and https; prefix inferred from the page's path) |
| POST | `/api/saved` | Save any page (`services/saved_service.py`, issue 0031) as an unread post of the Saved source (platform `saved`, created by the first save and written to sources.json at once); every save puts the post in Later at the save time (issue 0022), and a new saved post is dated by it (`published_at`; the page's own date in `metadata.article_published_at`), so it sorts by when it was saved. A page already stored goes to Later with its date unchanged. `{status: saved, post_id, title, source_id, readable, reason, feed}`: `readable` false when the page could not be read as an article (saved with its title and address; `reason` its status or "no article on the page", never the site's answer); `feed` a feed of the site that is not a source yet (`{url, title}`) or null. A page already stored (its URL or where it redirects, normalised): `{status: already, post_id, title}`. 400 for an empty or non-http(s) address. Under ~10 s (the feed finder runs meanwhile) | `{url, title?}` (no scheme: https; `title` the bookmarklet's) |
| PUT | `/api/sources/{source_id}/settings` | Edit settings | any of `{display_name, fetch_delay_seconds, priority, page_watch}` |
| PUT | `/api/sources/{source_id}/enabled` | Enable or disable | `{enabled}` |
| PUT | `/api/sources/{source_id}/main-digest` | In or out of the "all" feed | `{in_main_digest}` |
| PUT | `/api/sources/{source_id}/cadence` | Set or clear the fetch interval override | `{override_hours}` (1-2160, or null) |
| DELETE | `/api/sources/{source_id}` | Delete a source and its posts | |
| POST | `/api/sources/{source_id}/switch` | Point a source at its replacement (issue 0036): name, tracks and posts kept, failures cleared, sources.json rewritten (the switch undone when it cannot be): `{handle_or_url, previous}`. 400: bad address or already a source | `{url, page_watch?}` (`page_watch: {prefix?}` follows the page) |
| POST | `/api/sources/{source_id}/replacement/dismiss` | Hide the source doctor's finding until the next failure streak: `{row}`. 404 without a finding | |
| GET | `/api/sources/{source_id}/folders` | The folder ids a source is in | |
| GET | `/api/sources/health` | Every source's schedule and fetch health, plus a summary; a row carries the source doctor's `doctor_looked_at` and `replacement` (`{kind: feed\|page_watch, url, title, found, prefix}`, null: none found) | |
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
| POST | `/api/archive/{source_id}/plan` | Measure the source; where the archive continues from and how much is older | `{resume?, pageDelaySeconds?, batchSize?, batchCooldownSeconds?}` |
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
| GET | `/api/youtube/progress/{video_id}` | Watch progress of a video | |
| PUT | `/api/youtube/progress/{video_id}` | Save watch progress | `{videoUrl, title, progressSeconds, durationSeconds?, sourceId?, notesMarkdown?, completed?}` |
