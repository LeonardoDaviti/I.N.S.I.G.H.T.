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

## Module layout: the rules

Stories, trees, News, Classics and Discover are made by pure rule modules in `insight_core/utils/`
(plain data in, plain data out, no database). The services load what they read and write what they
return; the repositories hold the SQL. One job each:

| Module | Its job |
|---|---|
| `addresses.py` | what an address says, one definition each: its **host** (`host_of`), **site** (`site_of`, `same_site`; the feed finder's narrower `blog_site`), **publication** (`publication_of`), whether it is a **tweet** and whose (`is_tweet`, `tweet_author`, `x_account`), the account it is under on a platform (`account_key`) |
| `post_links.py` | the outside links in a post's HTML, and the small facts the story rules read of an address (home page, article, section, reference page) |
| `post_fields.py` | the fields computed on save, and the read-time rules of a post's title and body: `post_title(title, content, html)` (the text's first 4,000 and the HTML's first 2,000 characters) is the one title every place shows a stored post by (issue 0072 D1); `reading_text`, `quote_only`, `link_post_target`, `hnrss_counts` its body, quote and footer. Only the parser calls them (below) |
| `post_parser.py`, `post_parts.py` | **a post is read once, when it is saved** (issue 0076): `post_parser.parse` runs those rules once per post and the result is its `post_parts` row (migration 0060), which every page and the story job read (`db/repo_post_parts.py`: `shown_title()`, `body()`): the title, a row's lead, the post page's text and HTML as cut points into the raw columns (`post_parts.Body`: kept spans, read after decoding HTML codes, joined by line breaks; a copy only where no cut says it), the quote and whether the post only quotes (and folds into its own account's tweet), the footer's counts and link, the reply, Reddit's poster, the words, a short reaction's quoted subject (News's lead), and `warnings` where a rule guessed. Written in `upsert_post`'s savepoint; a change to the raw columns drops the row (a trigger) and the next save or the catch-up writes it again; the catch-up (`catch_up`, first in the story job's process) parses the posts with none, newest first, and every post again when `parse_stamp()` changes, writing only rows whose digest changed. `tests/test_post_parts.py` fails if a service, a repository or the API imports the read-time rules |
| `titles.py` | what a title is when two are compared (`title_key`: entities, NFKC, case, quotes, spaces; `comparable` keeps the case for names), as SQL's `post_title_key` |
| `story_rules.py` | the **story**: `StoryPost` (what the rules read of a post), `group` / `grouping` (joins by address, text, title, link, citation, thread, quote, each an `Edge`), roles, voices, a story's times (`story_times`: a date alone counts as that day's first timed post) and id (its post stored first), and the keys a post joins by (`keys`) |
| `tree_rules.py` | the **tree**: each post's parent and why, the origin, an outside origin's title (`origin_title`) |
| `discover_rules.py` | **Discover**: an address's key, site and article (`discover_address`), suggestions (the reference `repo_discover` counts in SQL), where stories start; `ADDRESS_RULES` |
| `news_rules.py` | **names** in titles and their surges, and **News** stories and their score |
| `classic_rules.py` | **Classics**: pages your sources keep citing |
| `stamps.py` | the fixed sample every stamp is computed from (below) |

**Stamps (issue 0071).** Derived data says which rules made it by a stamp computed at start, never
a number bumped by hand: a fingerprint of what the rules make of the sample in `utils/stamps.py`.
A rule change that changes the output there makes the data again by itself; a rename or a move
doesn't. `StoriesService.rules_stamp` (stories, trees, News, their edges and keys: every post regrouped, in batches), `post_parser.parse_stamp` (the stored parts, issue 0076: every post parsed again), `ADDRESS_RULES`
(Discover's `discover_addresses` rows), `stored_bodies_stamp` (the stored-body repair), and in SQL
`search_vector_version()` (migration 0055: the search vectors). Discover's kept counts are stamped by
their query's text. **A new rule adds its case to the sample**, and a tuned value has a case at its
edge (`tests/test_stamps.py` checks the sample still uses every join and parent reason and every
way an origin is titled).

## The incremental story job (issue 0072 A)

The story job (`services/stories_service.py`) regroups only what new or changed posts touch, and a
full rebuild (`recompute(full=True)`, `regroup`) over the same posts makes the same rows: the oracle,
checked by `scripts/story_identity.py` (`check(db_url)`; on a scratch copy only).
- **What a run reads first:** migration 0059's triggers queue each post saved, changed or removed
  (`story_queue`: `post:`, `gone:` with what it was). A batch takes up to `STORY_BATCH` of them.
- **What it stores between runs:** `story_keys`, each post's keys (`story_rules.keys`: its text `h:`,
  title `t:`, address and the pages it links `u:`, their page keys `g:`; its address's page key `a:`;
  the names in its title `n:`), and `post_edges`, every connection the rules made (`story_rules.Edge`:
  a join with the key it went through, a thread reply, a roundup's mention). Stories are the groups
  the edges make; a thread's edges are kept by its timeline (`_threads`: the posts within a day of
  a change, read from that source's posts within two).
- **What a batch regroups (`_neighbourhood`):** the seeds, the posts linking an address a seed is or
  was at (its own page may have moved), and the stories they are in. Then, until nothing is added:
  the rules group the scope with every post holding one of its keys and the posts at the addresses
  those link (the context a full run would read for them), and the scope takes in every group that
  holds a post of it, every post near it whose connection through such a key differs from the stored
  one (a chain of copies, a page's first linker), the stories a roundup of it lists, a platform
  roundup that lists one of its stories, with each of their old stories. A join merges groups; a
  split falls out of regrouping the whole old story. Only rows that differ are written.
- **A story's id** is its post stored first (`posts.created_at`), so a post that joins later keeps it,
  however early it was posted; a merge keeps the earlier stored one's.
- **News** keeps the stories begun in the last 30 days (`NEWS_KEEP`) and the posts of no story posted
  in them. A batch judges again only the names its titles say (`news_surges` keeps each name's
  surges: `news_rules.name_surges`), then regroups the News stories of the posts it regrouped, of the
  surges that changed, and of what crossed the window since the last run.
- **Classics** are recounted for the pages the batch's posts link or are at; **Discover** for the keys
  of those addresses (`DiscoverRepository.counts(keys=...)`), the rest of its kept counts kept.
- **A rule change** (another `rules_stamp`) regroups every post in steps, each its own transaction:
  every post's keys, each X source's threads, every name's surges, then every post queued (`redo:`)
  and worked off in batches. The rows of the old rules are served until each batch replaces them;
  Background work shows how far it is (`rebuild`).
- **Every field the job reads of a post** comes from `StoriesService._story_post` (the row
  `load_posts` reads, and its source's facts).

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
- **A server error** (HTTP 5xx, a timeout; issue 0072) is no move: recorded at once as
  `{server_error: true, status}` ("server error, not moved"), nothing looked at, nothing offered;
  the health row carries `server_error: {status}` and the sheet says the server is failing and
  INSIGHT keeps retrying (0072 D3). Migration 0058 rewrote what was stored before: an error text
  that was a proxy's page as its status line ("HTTP 502 while fetching …: Bad Gateway"), and an
  offer never checked against the source's items as that finding (on a 5xx) or nothing.
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
  one transaction; the id, name, tracks, read state and posts stay. Then sources.json, the
  export, is rewritten; when it cannot be, the log says so and the switch stands (the database
  is the truth, issue 0071). Nothing is re-fetched: posts match by URL, and an archive brings
  the older ones.
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
TEST_DATABASE_URL=postgresql://insight:insight@postgres:5432/mine_test MIGRATE=1 ./run-tests.sh   # a database of yours
```

By default each run creates its own database (`insight_run_<time>_<pid>_test`), migrates it and
drops it at the end, never the live `insight`. The posts and sources tests make come from one
factory, `insight_core/tests/_stories.py`.

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
| GET | `/health` | Container health check: one quick database query through the pool; 503 `{status: "unhealthy", database: false}` when the database doesn't answer (issue 0071) | |
| GET | `/api/version` | The build stamp (issue 0020): `{version, commit, commit_date}`, each null in a dev build | |
| GET | `/api/status` | System state for an agent: corpus, scheduler, folders, recent jobs | |
| GET | `/api/feed` | Every post list, newest first (Later: oldest saved first), one page | `scope=all\|source:<id>\|folder:<id>`, `filter=all\|unread\|later\|starred` (starred is Keep, "Kept"; later on `all` holds every source), `view=stream\|by_source`, `cursor`, `limit` (1-100), `days=N` or `date=YYYY-MM-DD` (UTC) |
| GET | `/api/feed/unread-counts` | Unread posts: total, per source, per folder; `later: {count, minutes}` | |
| GET | `/api/search` | Search every post (issue 0040): title, source name and full text, word forms in English and Russian, `"phrases"`, `-word`; feed rows plus `snippet` (the matching line as `[{text, mark}]`, null when only the title or source matched) | `q` (1-500 chars), `scope` (none: every post; `all` is the Main feed, `source:<id>`, `folder:<id>`), `filter=all\|later\|starred`, `days=N`, `order=newest\|best` (best ranks the newest 5,000 matches), `cursor` (the page's `next_cursor`), `limit` (1-100) |
| PUT | `/api/feed/read` | Read state, answers `{updated, ids}`; marking read by ids also takes the posts out of Later | `{ids, read, keep_later?}` (1-500 ids; `keep_later`: the read is only an open), or `{scope, through_cursor, newest_cursor}` to mark read through a cursor |
| GET | `/api/media` | One image of one post, through the 24-hour cache | `post`, `url` |
| GET | `/api/posts/item/{post_id}` | One post with its reader state | |
| POST | `/api/posts/item/{post_id}/opened` | Record an open (marks it read; it stays in Later) | `{metadata?}` |
| POST | `/api/posts/item/{post_id}/reading-session` | Record time spent reading | `{durationSeconds, metadata?}` |
| PUT | `/api/feed/later` | Read later (issue 0022): put posts in Later or take them out, answers `{updated, ids}` | `{ids, later}` (1-500 ids) |
| POST | `/api/posts/item/{post_id}/favorite` | Star (Keep) or unstar | `{favorited}` |
| GET | `/api/news` | News (issue 0051): the stories 2+ of your voices covered whose first post is in the last 7 days, with a post from the scope's sources. A FeedPage (no next page): each item a story's lead with its `story` and `news` `{part: recent \| earlier, first_at, reports, shares, mentions, score}`; recent (48 hours) first, then by score, then the newest | `scope` (`all` \| `folder:<uuid>`) |
| GET | `/api/classics` | Classics (issue 0051): pages 2+ of your voices linked 30+ days apart, a source of the scope among them, not hidden: `{classics: [{url, post_id, title, voices, days, first_at, last_at, cited_again, citers [{name, at}], read_at, later_at}]}`, cited again this week first, then most voices, then cited longest. Nothing is fetched | `scope` |
| POST | `/api/classics/hide` | Hide a classic for good ("I know it" and "not for me" in one) | `{url}` |
| PUT | `/api/posts/item/{post_id}/position` | Where a long post was left (issue 0030); `block: null` clears it. Marking a post read clears it too | `{block, blocks}` (`0 <= block < blocks`) |
| GET | `/api/sources` | Every source with settings, `post_count`, `in_main_digest`; `total_posts`. The archive's `history` is left out (issue 0105: 1.57 of the 1.81 MB on the lab); it stays in the row, and `GET /api/archive/{id}/status` and the source's own settings carry it | |
| POST | `/api/sources` | Add a source | `{platform="rss", handle_or_url, display_name?, fetch_delay_seconds?, priority?, state="enabled", page_watch?}` (`page_watch: {prefix?}` follows a page without a feed, stored as `settings.page_watch`) |
| GET | `/api/sources/export.opml` | Every source as OPML 2.0 (`text/x-opml`, a download `insight-sources.opml`, issue 0035): one outline per track in track order, each source under its first track (`category` names all its tracks), then the sources in none (the built-in Saved source, issue 0031, is left out). A source outline: `text`/`title` (name or address), `xmlUrl` (its address), and the `insight:` attributes (namespace `https://insight.local/opml`) `displayName`, `pageWatchPrefix` (followed pages, with `htmlUrl`; empty: the path is inferred) and `platform` (when not rss) | |
| GET | `/api/export` | Settings → Data, before the click (issue 0079): `{database_bytes, estimate_bytes, estimate_seconds, estimate_basis, last_export, tables, login_tables, logins_include}`: the estimate from the last whole export's real size and time, grown with the live rows since (`estimate_basis: last_export`, `last_export: {bytes, seconds, at, logins_included}`, kept in `system_settings.last_export`), else from the live rows' stored bytes (`live_rows`; issue 0105, `services/export_service.py`) | |
| GET | `/api/export/everything` | The whole database as one zip, streamed (`insight-YYYY-MM-DD-HHMM.zip`, issue 0079): a CSV per table (`COPY … TO STDOUT (FORMAT csv, HEADER)`, one repeatable-read snapshot), `schema.sql`, `manifest.json`, `README.txt`; the `credentials` CSV empty unless `logins=true`. Restored by `insight_core/db/import_export.py` (DEPLOYMENT.md) | `?logins=true&token=` (8-64 letters, digits, `-`, `_`: follow it with the next route) |
| GET | `/api/export/progress/{token}` | `{file_name, bytes, done, error}` of the export started with that token (the last 20 kept in the API's memory); 404 for another | |
| GET | `/api/export/sources.json` | The sources in the shape `sources.json` imports (`{metadata, platforms: {<platform>: {enabled, sources: [{id, state, in_main_digest?}]}}}`), a download `sources.json` | |
| POST | `/api/sources/find-feed` | The feeds for any page address (`ingestion/feed_finder.py`, under 10 s): `{status: feed\|found\|direct\|none, feeds: [{url, title}], homepage, pages}`; for a site's home page with no feed (issue 0041) `homepage: true` and `pages`, its own blog or news pages that can be followed instead, each with its page-watch preview `{url, prefix, found, sitemap, items}`, the most articles first (previewed at once, within 15 s more); when it names none (issue 0047), its own menu links (header and navigation, then footer, at most 12) are previewed instead and only one that reads as an article list (3 posts dated within a year) is offered; when your sources linked the site's articles (issue 0060, `ingestion/where_linked.py`), `linked` is how many and every feed and page carries `holds`, how many of them it holds, the most first (a tie to the narrower path); a home page whose links are 60%+ under one section that is not a date or a number starts there (`start`, else null), the home page's own feeds beside the section's, and one linked article is fetched to see where a moved section went | `{url}` (no scheme: https) |
| POST | `/api/sources/page-watch/preview` | Following a page without a feed (`ingestion/kinds/page_watch.py`, issue 0028): `{prefix, found, sitemap, items: [{url, title, published_at}]}`, `found` the article URLs under the prefix (listing links and sitemap), `items` the first 5 read; no items: its articles need a browser. 400 when the page cannot be read (its status only, never the site's answer) | `{url, prefix?}` (no scheme: https; only http and https; prefix inferred from the page's path) |
| POST | `/api/saved` | Save any page (`services/saved_service.py`, issue 0031) as an unread post of the Saved source (platform `saved`, created by the first save, then sources.json rewritten); every save puts the post in Later at the save time (issue 0022), and a new saved post is dated by it (`published_at`; the page's own date in `metadata.article_published_at`), so it sorts by when it was saved. A page already stored goes to Later with its date unchanged. `{status: saved, post_id, title, source_id, readable, reason, feed}`: `readable` false when the page could not be read as an article (saved with its title and address; `reason` its status or "no article on the page", never the site's answer); `feed` a feed of the site that is not a source yet (`{url, title}`) or null. A page already stored (its URL or where it redirects, normalised): `{status: already, post_id, title}`. 400 for an empty or non-http(s) address. Under ~10 s (the feed finder runs meanwhile) | `{url, title?}` (no scheme: https; `title` the bookmarklet's) |
| PUT | `/api/sources/{source_id}/settings` | Edit settings | any of `{display_name, fetch_delay_seconds, priority, page_watch}` |
| PUT | `/api/sources/{source_id}/enabled` | Enable or disable | `{enabled}` |
| PUT | `/api/sources/{source_id}/main-digest` | In or out of the "all" feed | `{in_main_digest}` |
| PUT | `/api/sources/{source_id}/cadence` | Set or clear the fetch interval override | `{override_hours}` (1-2160, or null) |
| DELETE | `/api/sources/{source_id}` | Delete a source and its posts | |
| POST | `/api/sources/{source_id}/switch` | Point a source at its replacement (issue 0036): name, tracks and posts kept, failures cleared, sources.json rewritten (when it cannot be, the switch stands): `{handle_or_url, previous}`. 400: bad address or already a source | `{url, page_watch?}` (`page_watch: {prefix?}` follows the page) |
| POST | `/api/sources/{source_id}/replacement/dismiss` | Hide the source doctor's finding until the next failure streak: `{row}`. 404 without a finding | |
| POST | `/api/sources/{source_id}/tidy/keep` | Keep a source marked quiet or never opened (issue 0046): its marks hide for 90 days and come back only if still true; the fresh health row. 404 for no such source | |
| GET | `/api/sources/suggested` | Discover (issue 0050): the sites and accounts 3+ of your sources link in article-like pages that you don't follow, each `{key, url, voices, voice_names, article_count, link_count, articles, origins, origin_stories, follows?}`, the most stories started there first (issue 0065), then most voices; `archives` (followed sources whose own pages started stories they don't hold) and `unnamed`. Nothing is fetched | |
| POST | `/api/sources/suggested/hide` | Not interested: the key is never suggested again | `{key}` |
| GET | `/api/sources/anatomy` | Source anatomy (issue 0054): every source, how it is read and what it gives: `{window_days, generated_at, rows: [{source_id, display_name, address, platform, enabled, kind, full_text, watch_changes, watched_pages, validators, status, interval_hours, next_due_at, last_outcome, last_error, recent, all}]}`, most posts in the window first. Nothing is fetched | |
| GET | `/api/sources/{source_id}/folders` | The folder ids a source is in | |
| GET | `/api/sources/health` | Every source's schedule and fetch health, plus a summary; a row carries the source doctor's `doctor_looked_at` and `replacement` (`{kind: feed\|page_watch, url, title, found, prefix}`, null: none found), and `server_error` (`{status}` when it read a server error, issue 0072) | |
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
| GET | `/api/operations/background` | What runs on its own (issue 0062): stories, the search index, link reading, each with its progress. Read only | |
| GET | `/api/operations/scheduler` | Scheduler settings and state | |
| PUT | `/api/operations/scheduler` | Edit scheduler settings | `{intervalHours?, ingestTickMinutes?}` (tick >= 15) |
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
