# INSIGHT Mark IX — Ingestion, Information Reading, UI/UX

Status: **accepted (2026-10-09)**; the product-owner decisions are recorded in §8. Mark IX is not deployed yet, so breaking internal changes and new migrations are allowed.
Written: 2026-10-08
Stack (unchanged): FastAPI + psycopg 3 + Postgres 15/pgvector, React 19/TS/Vite/Tailwind, Docker Compose.
Supersedes: `plan/INSIGHT_adaptive_fetch_cadence_plan.md`. Section C implements that plan, and the deviations are recorded there.

---

## 0. Goals and non-goals

### Goals
1. **One ingestion module.** The scheduler, the manual "run cycle", track/folder fetch, single-source fetch-now and the CLI all go through one entry point: `run_ingestion(FetchRequest) -> RunReport`.
2. **Every path applies the same policy:**
   - the yt-dlp switch
   - backoff (read *and* write)
   - politeness gates
   - status recording
   - save isolation
   - enrichment

   The current bypasses in P3, P4 and P5 (the legacy ingest, fetch-now and folder fetch paths) go away.
3. **One save path that owns its transaction.** `PostsRepository.save_batch` handles savepoints, the commit cadence and recovery from a poisoned transaction. The live paths and archive pages all use it.
4. **Adaptive fetch cadence.** A pure decision function picks the fetch interval from each source's publishing rate, with a backlog guard, an override, probation and an error-backoff ladder.
   - Staleness is measured from the last *successful fetch* of the source, not from `MAX(posts.fetched_at)`.
5. **Source kinds behind one seam.** Each kind is one adapter that owns live fetch, inspect, archive pages and a declarative politeness profile. This replaces the strategy-string `if/elif` ladders in `source_fetch_service.py`.
6. **Reader first.** `/` becomes a unified feed with:
   - unread/read and starred state
   - keyboard navigation
   - cursor pagination
   - a readable reading view
   - prev/next on the post page
7. **Operations are legible:**
   - a typed run report instead of raw JSON
   - one "Run cycle" button, with an explicit "force" option
   - a full source health table in Settings → Sources: tier, interval, next due, backoff, last success, last error, skip reason, a per-source override and a per-source Fetch now
8. **Consistent states.** Loading, empty and error states look the same on the new surfaces (feed, track, source health, run report).
   - Toasts are used for async job outcomes.
   - API error messages no longer leak `| url=`.

### Non-goals (Mark IX)
- Analysis and briefings: `briefing_service.py`, `gemini_processor`, topic modeling, experts and stories. These are only touched where the ingestion run report replaces the old result dict inside `run_scheduler.run_cycle`. The briefing/expert calls in that file are not modified.
- A thin HTTP bridge rewrite (prior candidate #6). Bridge methods only get *smaller*, because ingestion logic moves out.
- Cross-process host politeness, where the API and ingestion containers would share host slots. Mark IX adds a run-level advisory lock so two full cycles cannot overlap. Per-host coordination stays per-process, as documented in §A.6.
- Rewriting all of `DailyBriefing.tsx`. Mark IX adds a new reader route. DailyBriefing stays at `/briefing` as the briefing surface, and its "all posts" mode is removed in favour of the reader.
- Fixing the whole lint backlog (93 problems). Only files Mark IX touches must be lint-clean. Type errors are fixed in full (slice F1), because a typecheck gate is a precondition for safe UI work.
- Mark IX does not remove the `engines/mark_i_foundation_engine.py` / `insight_bridge.py` legacy pair. They are dead, but outside the ingestion seam; this is noted for Mark X.

---

## 1. Glossary (domain language; use these words in code, UI and commits)

| Term | Meaning | Code name |
|---|---|---|
| **Source** | A row in `sources`: one feed, channel, subreddit or site we read from. It has a platform, a `handle_or_url`, `enabled`, `in_main_digest` and settings. | `Source` (dataclass view), `sources` table |
| **Platform** | The user-facing family stored in `sources.platform`: `rss`, `reddit`, `youtube` or `telegram`. It drives avatars, presets and per-platform logs. It is **not** the fetch strategy. | `source.platform` |
| **Source kind** | The fetch strategy resolved from platform + URL, such as `generic_rss`, `telegram_rss`, `youtube_channel` or `lesswrong_graphql`. Exactly one adapter exists per kind. Replaces the Mark VIII "strategy string" / `classify_source`. | `SourceKind` protocol, `KindRegistry` |
| **Politeness profile** | The declarative per-kind rules that control how hard we may hit a source: concurrency pool, page delay, batch cooldown, cadence floor, minimum posts per fetch, requirements, and whether the kind does blocking I/O. It holds nothing host-keyed. | `PolitenessProfile` |
| **Host floor** | The minimum spacing between request starts to one *host key* (for example `tg.i-c-a.su`, `nitter.net`, `reddit.com`, `platform:reddit`). It is keyed by host, not by kind, because many kinds share a host (the `.rss` reddit sources resolve to `generic_rss`). | `HOST_FLOORS` in `gates.py` |
| **Fetch gates** | The process-wide object that enforces politeness profiles and host floors: a global semaphore, a yt-dlp pool and start spacer, and per-host limiters. | `FetchGates` |
| **Run lock** | The Postgres advisory lock that stops two full (`all`) fetch runs from overlapping. | `RunLock` port, `PgAdvisoryRunLock` |
| **Progress sink** | Where a fetch run reports phase events. The API path appends them to the job; tests and the CLI use a null or recording sink. | `ProgressSink` port |
| **Post** | A row in `posts`, deduplicated by `url` (global) and by `(source_id, external_id)`. | `posts` table; `PostDraft` before save |
| **Folder / Track** | A user-made group of sources (`folders` + `source_folders`). The UI calls a folder a **Track** when it has a page (`/tracks/:id`). The two are the same thing in the backend. | `folder_id` |
| **Source selector** | Which sources a fetch request targets: all enabled sources, one folder (enabled members only), or one source. | `SourceSelector` |
| **Trigger** | Who asked for the run: `scheduler`, `manual` or `cli`. Recorded on the job and on each fetch outcome. | `Trigger` enum |
| **Force** | A request flag that ignores *cadence* and *backoff*. It never ignores *unavailability*: a disabled yt-dlp stays disabled, and a Telegram MTProto source with no credentials or no authorised session stays unavailable. Fetch-now and track fetch are always forced. (Interim, B1–B3 only: `ignore_backoff`, which skips backoff but still honours cadence, keeps the Mark VIII manual-cycle behaviour until `force` exists.) | `FetchRequest.force` |
| **Fetch run** | One execution of `run_ingestion`: a job of type `ingestion_run`, the decisions, the fetches, the save, the enrichment and the inspection refresh. | `IngestionRunner.run` |
| **Run report** | The typed result of a fetch run: totals, counts per decision kind, failures and duration. Stored compact in `job_runs.payload` and rendered in the UI. | `RunReport` / TS `RunReport` |
| **Fetch decision** | The pure result of asking "should this source be fetched now?": whether to fetch, a reason kind, the post limit, the next due time and the next retry time. | `FetchDecision`, `DecisionKind` |
| **Fetch outcome** | What actually happened when a source was fetched: `healthy` (≥1 post), `empty` (0 posts, success), `error` or `unavailable`. | `FetchOutcome`, `OutcomeStatus` |
| **Fetch state** | The persisted per-source scheduling memory: last attempt, last success, last outcome and error, consecutive failures, next retry, last decision. It lives in its own table and is no longer stored in `settings` JSONB. | `source_fetch_state` table, `FetchStateRepository` |
| **Cadence tier** | A label derived from a source's mean gap between posts: `fast` < 12h, `medium` 12h–7d, `slow` > 7d, `unknown` < 3 dated posts. | `CadenceTier` enum, `sources.cadence_tier` |
| **Mean gap** | The mean time between a source's latest 20 dated posts. Recomputed at most once a day. | `sources.mean_gap_seconds` |
| **Fetch interval** | How long a successfully fetched source waits before it is due again. | `FetchDecision.interval` |
| **Probation** | The 24h interval used for `unknown` sources until they have at least 3 dated posts. | `DecisionKind`/tier `unknown` |
| **Backlog guard** | A cap so that `interval ≤ mean_gap × max_posts_per_fetch`. A feed that exposes N items is polled before it can push out unseen posts. | `_apply_backlog_guard` |
| **Override** | `sources.fetch_interval_hours_override`. When set, it replaces the tier interval entirely. | — |
| **Backoff** | The extra wait after consecutive *error* outcomes: 1h · 2^(n−1), capped at 24h (dormant cap 7d), jittered. It resets on the first non-error outcome. | `backoff_delay()` |
| **Unavailable** | The source's kind needs something the process does not have: yt-dlp is switched off, or (`telegram_mtproto`) the Telegram API credentials or the authorised session file are missing, the session is not authorised, the session is held by another run, or the account is in a flood wait. Each case carries its own reason. The source is skipped with its own reason, is never counted as backoff, and backoff is not advanced. | `DecisionKind.SKIP_UNAVAILABLE` |
| **Save batch** | One call to `PostsRepository.save_batch`. It upserts many post drafts with per-post isolation, commits every N posts, and recovers when the transaction is poisoned. | `SaveBatchResult` |
| **Enrichment** | The follow-on step after a save batch: entity memory and event memory over the *inserted* post ids, in chunks, off the event loop. | `Enricher` |
| **Inspection** | A per-source, archive-oriented probe: available posts, page size and first post date. It is refreshed on one global interval (`ARCHIVE_INSPECT_INTERVAL_HOURS`) by `DbInspectionRefresher`. | `Inspection` |
| **Archive / backfill** | Paging historical posts for one source. Each page goes through a save batch. | `archive_pages()` |
| **Read state** | Per-post reader projection: `read_at` and `starred_at`. | `post_reader_state` table |
| **Feed** | A keyset-paginated, newest-first list of posts for a scope (all main-digest, folder or source), filtered by unread, starred or all. Shown as a flat *stream* or grouped *by source*. | `GET /api/feed` |
| **Feed view** | How the feed is laid out: `stream` (one chronological list) or `by_source` (one group per source, newest first, so a high-volume source cannot bury a low-volume one). | `FeedView` |

---

## 2. Target package layout (backend)

```
backend/insight_core/ingestion/            NEW package (the deep module)
  __init__.py          public surface: run_ingestion, FetchRequest, SourceSelector, Trigger, RunReport
  types.py             request/report/outcome dataclasses + enums
  runner.py            IngestionRunner (orchestration only; ports injected)
  schedule.py          pure: decide_fetch, fetch_interval, tier_for, backoff_delay, cadence_stats (the only
                       CadenceStats constructor), CadenceStats, FetchDecision, Availability
  gates.py             FetchGates, HostLimiter, StartSpacer, HOST_FLOORS (moved from safe_ingest.py)
  enrichment.py        Enricher (chunked, to_thread), EnrichmentReport, StepReport
  inspection.py        DbInspectionRefresher: due check + kind.inspect + ArchiveMetadataWriter, under gates.slot
  archive_metadata.py  ArchiveMetadataWriter (moved from SourceFetchService._record_archive_metadata_sync)
  ports.py             Protocols: SourceCatalog, FetchStateStore, PostSaver, InspectionRefresher, RunLock,
                       ProgressSink, Clock (+ the Db*/PgAdvisory*/Null* real adapters)
  http.py              KindHttp: get_text / post_json / get_json / sleep with UA + TLS-skip policy (moved from SourceFetchService)
  kinds/
    __init__.py        KindRegistry (classify once, cached)
    base.py            SourceKind protocol, PolitenessProfile, RateLimit, Inspection, ArchivePage, KindUnavailable
    parsing.py         pure helpers moved off SourceFetchService: strip_html, isoformat, parse_datetime_value,
                       local_name, child_text, extract_article_html, extract_html_image_urls
    generic_rss.py     (feed parse + optional full-content expansion)
    telegram_rss.py
    nitter_rss.py
    reddit.py          reddit_subreddit: live via /new/.rss, archive via JSON (best-effort)
    youtube.py         wraps services/youtube_service.py, blocking_io=True
    telegram_mtproto.py bare Telegram handles over MTProto (B8): TelegramKind + TelegramSession (session
                       lifecycle), message->post synthesis moved from connectors/telegram_connector.py,
                       flood-wait handling; Telethon is imported lazily, only inside the real client factory
  telegram_session.py  TelegramClientPort protocol, TelethonClientFactory (the only telethon import),
                       TelegramFloodWait / TelegramChannelError (translated telethon errors), session path + lock
backend/insight_core/adapters/base_adapter.py BaseSourceAdapter implements SourceKind directly (no wrapper)
backend/insight_core/db/repo_fetch_state.py NEW  FetchStateRepository (+ cadence refresh SQL)
backend/insight_core/db/repo_reader.py      NEW  ReaderRepository (feed keyset query, read/star)
backend/insight_core/db/repo_posts.py       save_batch() added; upsert_posts_batch() removed
backend/insight_core/services/source_fetch_service.py  shrinks to archive planning/run (the metadata writer moves to ingestion/)
backend/insight_core/scripts/safe_ingest.py   becomes a ~40-line CLI shim over run_ingestion
backend/insight_core/scripts/ingest.py        DELETED
backend/insight_core/scripts/run_scheduler.py ingestion tick + daily-work gate (briefing calls untouched)
backend/insight_core/scripts/telegram_login.py NEW (B8) the ONLY interactive Telegram auth (operator CLI)
backend/insight_core/connectors/              DELETED by the end of B8 (B5 removes all but telegram; B8 moves
                                              telegram_connector.py's logic into ingestion/kinds and deletes it)
```

Dependency rule:
- `ingestion/` may import `db/`, `adapters/` and `services/youtube_service.py`. It must **not** import `services/source_fetch_service.py`. Everything the runner needs from it (the archive metadata writer, the inspection due rule, the parsing helpers) moves into `ingestion/`.
- `services/source_fetch_service.py` may import `ingestion/kinds`, `ingestion/archive_metadata`, `ingestion/enrichment` and `db/`, but not `ingestion/runner.py` or `ingestion/__init__`'s `run_ingestion`.
- The only callers of `run_ingestion` are `insight_api_bridge.py`, `run_scheduler.py` and the `safe_ingest` CLI shim.
- This means `ingestion/__init__` can wire the default runner without an import cycle.
- `adapters/*.py` import `ingestion.kinds.base` and `ingestion.kinds.parsing`, and importing those runs `ingestion/__init__` and `ingestion/kinds/__init__` first. So both `__init__` files must stay import-light: `KindRegistry.default()` imports `adapters` inside the function, and `run_ingestion` imports `runner`/`ports` inside the function. `test_importing_ingestion_does_not_import_connectors_or_telethon` also asserts `import insight_core.adapters` succeeds in a fresh interpreter.

---

## A. Ingestion module (deep module)

### A.1 Interface

```python
# ingestion/types.py
class Trigger(str, Enum):
    SCHEDULER = "scheduler"
    MANUAL = "manual"
    CLI = "cli"

@dataclass(frozen=True)
class SourceSelector:
    kind: Literal["all", "folder", "source"]
    id: str | None = None
    @staticmethod
    def all() -> "SourceSelector": ...
    @staticmethod
    def folder(folder_id: str) -> "SourceSelector": ...
    @staticmethod
    def source(source_id: str) -> "SourceSelector": ...

@dataclass(frozen=True)
class FetchRequest:
    selector: SourceSelector
    trigger: Trigger
    force: bool = False              # ignore cadence + backoff (never unavailability)
    limit: int | None = None         # per-source post limit override (still floored by profile.min_posts_per_fetch)
    # No job_id and no refresh_inspection: job tracking is a ProgressSink (below), and the
    # inspection refresh is always on (its env kill switch INSIGHT_REFRESH_ARCHIVE_METADATA=0
    # is read by DbInspectionRefresher, renamed from SAFE_INGEST_REFRESH_ARCHIVE_METADATA).

class OutcomeStatus(str, Enum):
    HEALTHY = "healthy"; EMPTY = "empty"; ERROR = "error"; UNAVAILABLE = "unavailable"

@dataclass(frozen=True)
class FetchOutcome:
    source_id: str
    status: OutcomeStatus
    fetched: int
    error: str | None
    duration_s: float

@dataclass(frozen=True)
class SourceFailure:
    source_id: str
    display_name: str
    stage: Literal["fetch", "save", "connector"]
    error: str

@dataclass(frozen=True)
class InsertedBySource:
    source_id: str
    display_name: str
    inserted: int

@dataclass
class RunReport:
    run_id: str | None
    trigger: Trigger
    selector: SourceSelector
    force: bool
    status: Literal["success", "partial", "failed", "skipped_busy", "nothing_due"]
    started_at: datetime
    finished_at: datetime
    sources_considered: int
    sources_fetched: int              # attempted
    sources_failed: int
    decisions: dict[str, int]         # DecisionKind.value -> count  (replaces sources_backoff_skipped)
    posts_fetched: int
    posts_inserted: int               # THE "new posts" number (one name everywhere)
    posts_updated: int
    posts_failed: int
    failures: list[SourceFailure]           # <= 20
    post_failures: list[PostSaveFailure]    # <= 20 (§B.1)
    enrichment: EnrichmentReport            # (§B.2) entity/event StepReport(posts, chunks, failed_chunks)
    inserted_by_source: list[InsertedBySource]  # <= 20, desc by inserted
    def to_payload(self) -> dict: ...       # every list <= 20, so OperationsService._compact_payload is a no-op
    def summary_line(self) -> str: ...      # "12 due, 63 deferred, 1 failed; 48 new posts" (pinned by a unit test)
```

```python
# ingestion/__init__.py
async def run_ingestion(request: FetchRequest, *, progress: ProgressSink | None = None,
                        runner: IngestionRunner | None = None) -> RunReport

# ingestion/runner.py
class IngestionRunner:
    def __init__(self, *, catalog: SourceCatalog, state: FetchStateStore, saver: PostSaver,
                 enricher: Enricher, inspections: InspectionRefresher, registry: KindRegistry,
                 gates: FetchGates, run_lock: RunLock, availability: Callable[[], Availability],
                 clock: Clock, rand: Callable[[], float] = random.random): ...
    async def run(self, request: FetchRequest, *, progress: ProgressSink = NULL_PROGRESS) -> RunReport

# ingestion/ports.py (the ones not obvious from the names)
class RunLock(Protocol):
    def try_acquire(self) -> AbstractAsyncContextManager[bool]   # yields False when another run holds it
class ProgressSink(Protocol):
    def event(self, phase: str, data: dict) -> None
class InspectionRefresher(Protocol):
    async def refresh(self, source: Source, kind: SourceKind, fetched_posts: int) -> None  # owns the due check
```
`run_ingestion` builds the default runner from `DATABASE_URL`, using the real ports, `PgAdvisoryRunLock`, `availability_from_env` and the process-wide `FetchGates.shared()`. Tests construct `IngestionRunner(...)` with fakes for every keyword, including `rand=lambda: 1.0` so backoff is deterministic. The API path passes a `JobProgressSink(operations_service, job_id)` that calls `append_job_event`; the runner never imports `OperationsService`.

### A.2 What the runner does (one algorithm for every caller)

1. **Run lock.** When `selector.kind == "all"`, enter `run_lock.try_acquire()`. The real `PgAdvisoryRunLock` takes `pg_try_advisory_lock(hashtext('insight.ingestion_run'))` on a dedicated connection held for the run. If the lock is not acquired, the run returns `status="skipped_busy"` immediately. Folder and source runs do not take the lock: they are small, and the per-process gates protect hosts.
2. **Load the sources.** `SourceCatalog.load(selector) -> list[Source]` makes one query and returns `post_count`, the settings merged with defaults, the cadence columns and the override. It replaces the N+1 query in `get_all_sources_with_settings`.
   - `all` and `folder` return **enabled** sources only.
   - `source` returns the source even when it is disabled. Fetch-now on a disabled source is allowed because it is explicit.
3. **Load the fetch state.** `FetchStateStore.load(source_ids) -> dict[id, FetchStateRow]` is one query.
4. **Decide per source.** `decide_fetch(cadence_stats(source, state_row), kind.profile, now, force=request.force, availability=self.availability(), requested_limit=request.limit)` (§C). Both calls are pure; `cadence_stats` is the only place a `CadenceStats` is built.
5. **Record the skip decisions.** Every decision is written to `source_fetch_state` as `last_decision_kind` and `last_decision_at`, so the UI can show "skipped: not due (next 2026-10-10 14:00)". This is one batched UPSERT.
6. **Fetch.** Due sources are interleaved by host and gathered concurrently under the gates. There are two **concurrency pools** (`host-lock`, `ytdlp`); there is no shared-session pool in Mark IX.
   - Each fetch is `async with gates.slot(kind.profile, kind.host_key(source)): posts = await kind.fetch_latest(source, limit)`.
   - `KindUnavailable` raised by a kind becomes `FetchOutcome(UNAVAILABLE)`; any other exception becomes `FetchOutcome(ERROR)`. The fetch never raises out of the runner.
7. **Record outcomes.** `FetchStateStore.record_outcomes(outcomes, trigger=..., now=..., backoff=lambda n: backoff_delay(n, rand=self.rand))` writes all outcomes in one connection and transaction. Per row it is one atomic UPSERT that computes the new `consecutive_failures` in SQL (`RETURNING`), and the store then applies `backoff(new_count)` to set `next_retry_at` (§C.3). A healthy or empty outcome resets `consecutive_failures` and sets `last_success_at = now`. This is what fixes staleness (§C).
8. **Save.** All fetched posts go through `PostSaver.save(drafts)` → `SaveBatchResult` (§B), via `asyncio.to_thread`. There is one save batch per run. Each draft carries its `source_id`.
   - A source whose posts *all* failed to save gets a `SourceFailure(stage="save")`. Its fetch outcome stays as it was: the fetch itself worked.
9. **Enrich.** `Enricher.run(result.inserted_ids)` is chunked and runs in `to_thread`. Failing chunks are counted, not raised.
10. **Refresh inspections.** For each source with ≥ 1 fetched post the runner calls `inspections.refresh(source, kind, fetched_posts)`. `DbInspectionRefresher` owns the whole step: the Mark VIII due rule (global `ARCHIVE_INSPECT_INTERVAL_HOURS`, not kind-specific), `kind.inspect` under the same `gates.slot` (the duplicate gate code goes away), and `ArchiveMetadataWriter.record(source_id, kind, data, mode="live")`. Failures are logged and counted, never raised.
11. **Build the report.** The `RunReport` is built. `progress.event(phase, data)` is called at each phase (`decided`, `fetched`, `saved`, `enriched`, `inspected`); the caller finishes the job with `report.to_payload()`.

### A.3 Callers after Mark IX

| Caller | Before | After |
|---|---|---|
| Scheduler `run_scheduler.run_cycle` | `safe_ingest_posts(trigger="scheduler")` plus a message built by hand | `run_ingestion(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER))`. The job is finished in a `try/finally`, so a raise marks `ingestion_run` failed instead of leaving it "running". |
| Manual cycle | `POST /api/safe-ingest-posts` (synchronous, inside the request) | `POST /api/ingestion/run {force?: bool}` → 202 + job, run in the background |
| Legacy full ingest | `POST /api/ingest-posts` → `scripts/ingest.py` | **Deleted** (route, bridge method, script and `api.ts ingestPosts`) |
| Folder / track fetch | `bridge.ingest_folder_now`: a sequential loop over `ingest_source_now` | `POST /api/folders/{id}/ingest` → `FetchRequest(SourceSelector.folder(id), MANUAL, force=True)` |
| Single source | `SourceFetchService.ingest_source_now` | `POST /api/sources/{id}/fetch-now` → `FetchRequest(SourceSelector.source(id), MANUAL, force=True, limit=body.limit)` |
| CLI | `python safe_ingest.py`, `python ingest.py` | `python -m insight_core.scripts.safe_ingest [--force] [--folder ID] [--source ID]` prints the report as JSON |

`SourceFetchService.ingest_source_now`, `_persist_posts`, `bridge.ingest_posts`, `bridge.safe_ingest_posts` and the fetch loop in `bridge.ingest_folder_now` are deleted. `bridge.fetch_source_now` and `bridge.ingest_folder_now` become thin wrappers of about 10 lines each that call `run_ingestion` and return `report.to_payload()`.

### A.4 Scheduler change (ingestion tick vs daily work)
Cadence tiers and a 1h backoff ladder mean nothing if the scheduler wakes every 20h. So:
- **Ingestion tick:** `run_scheduler.main` runs an *ingestion tick* every `scheduler_config.ingest_tick_minutes`. This is a new config field, default 60, with a 15-minute floor.
  - The tick calls `run_ingestion(all, SCHEDULER)`. Because of cadence, a tick touches only the sources that are due.
- **Daily work** keeps its existing order and code:
  - prune job_runs
  - sync sources.json
  - experts
  - the daily and topic briefings

  It runs when `now - last_daily_work_at >= interval_hours`. `last_daily_work_at` is persisted in `system_settings['scheduler_state']`, so the briefing call sites run exactly as often as today. *The briefing code itself is not modified.*
  - **First tick after deploy.** When `scheduler_state.last_daily_work_at` is missing, it is seeded from the latest `job_runs.finished_at` of a successful `scheduler_cycle` job (the Mark VIII daily cycle). Daily work runs immediately only when no such row exists. This stops every fresh deploy from producing an extra briefing.
- **Testable tick.** `run_scheduler.py` extracts `async def tick(now, state: SchedulerState, config, *, ingest, daily_work, ops) -> SchedulerState`. `ingest` is `run_ingestion`, `daily_work` is the existing prune/sync/experts/briefing sequence, and `ops` is the operations service (start/finish job, read/write scheduler state). `main` only bootstraps, installs signal handlers, loops, calls `tick` and sleeps. Tests call `tick` directly with fakes passed as arguments, not patched module attributes.
- **Scheduler state.** The scheduler writes `system_settings['scheduler_state'] = {last_tick_at, next_tick_at, last_daily_work_at, next_daily_work_at}` after each tick. `GET /api/operations/scheduler` returns it, which replaces the client-side countdown guess.
- **Cadence refresh.** Once per daily work, `FetchStateRepository.refresh_cadence()` runs (§C.3).

### A.5 Async API path
All three manual endpoints are async-only (`asyncMode` is removed from the request bodies):
1. `_start_job_safe("ingestion_run", trigger="manual", source_id=..., payload={"selector":..., "force":...})`
2. `background_tasks.add_task(...)` schedules `run_ingestion(..., progress=JobProgressSink(ops, job_id))` followed by `finish_job(status, message=report.summary_line(), payload=report.to_payload(), compact=True)` in a `try/finally` (a raise finishes the job as failed).
3. The endpoint returns `JSONResponse(status_code=202, content={success: true, job_id, job_type: "ingestion_run", status: "running"})`. The status code is in the returned response object, not the route decorator, so the route tests can assert it when they call the coroutine directly.

If `start_job` fails, the endpoint returns `JSONResponse(status_code=503, content={success:false, error:"job tracking unavailable"})` and does **not** run synchronously.

Job types `safe_ingest`, `ingest_all`, `fetch_source_now` and `folder_ingest` are replaced by one `ingestion_run`. The selector is in the payload. `operations_service.py` and `frontend/src/lib/operationsOverview.ts` get updated label maps; old rows are still displayed through a legacy label map.

### A.6 Known limitation (documented, not fixed)
The API container and the ingestion container each have their own `FetchGates`. A forced track fetch in the API can overlap a scheduler tick on the same host. Two things mitigate this:
- the run lock prevents two *full* cycles from overlapping
- a forced fetch is user-initiated and bounded

A shared limiter (Postgres advisory locks keyed by host) is a Mark X candidate.

---

## B. Save batch (posts repository owns its transaction)

### B.1 Interface

```python
# db/repo_posts.py
@dataclass(frozen=True)
class PostDraft:
    source_id: str
    post: dict            # the existing normalized post dict (url, title, content, date, ...)

@dataclass(frozen=True)
class PostSaveFailure:
    url: str | None
    source_id: str
    stage: Literal["upsert", "discarded"]   # discarded = lost to a poisoned-txn rollback
    error: str

@dataclass
class SaveBatchResult:
    inserted_ids: list[str]
    updated_ids: list[str]
    failures: list[PostSaveFailure]
    by_source: dict[str, dict[str, int]]    # source_id -> {inserted, updated, failed}
    @property
    def inserted(self) -> int: ...
    @property
    def updated(self) -> int: ...
    @property
    def failed(self) -> int: ...

class PostsRepository:
    def save_batch(self, conn: psycopg.Connection, drafts: Sequence[PostDraft], *, commit_every: int = 20) -> SaveBatchResult
```

How `save_batch` works:
1. **Precondition.** The connection must not be in autocommit mode, and the caller passes it in idle state. `save_batch` **owns the transaction boundaries** on it: it commits every `commit_every` attempted drafts and once at the end.
2. **Per-draft isolation.** Each draft runs `upsert_post(cur, post, source_id)`, which keeps its own retry + savepoint logic, inside a `try`.
   - An exception becomes `PostSaveFailure(stage="upsert")`.
   - Then `_transaction_is_poisoned(conn)` is checked (moved from safe_ingest, using the `_PQ_INERROR` guard). If the transaction is poisoned:
     1. `conn.rollback()`
     2. every id and draft since the last commit watermark is moved into `failures` as `"discarded"`
     3. the batch continues
3. **Return value.** Ids are returned as strings. `commit_every` defaults to `INSIGHT_SAVE_COMMIT_BATCH` (env, default 20). This is renamed from `SAFE_INGEST_SAVE_COMMIT_BATCH`, and the old name is still read as a fallback for one version. The 20 keeps the subtransactions in a batch under Postgres's 64-subxact cache.
4. **Removed:** `upsert_posts_batch` (it has no callers).

`PostSaver` (the ingestion port) is a 10-line adapter that does `with psycopg.connect(db_url) as conn: return repo.save_batch(conn, drafts)`.

**Callers:**
- the ingestion runner (§A)
- archive page persistence in `source_fetch_service.archive_source` (it replaces `_persist_posts`)

### B.2 Enrichment as a follow-on step

```python
# ingestion/enrichment.py
@dataclass(frozen=True)
class StepReport:
    posts: int
    chunks: int
    failed_chunks: int

@dataclass(frozen=True)
class EnrichmentReport:
    entity: StepReport
    event: StepReport

class Enricher:
    def __init__(self, entity: EntityProcessor, event: EventProcessor, chunk_size: int = 100): ...
    async def run(self, post_ids: Sequence[str]) -> EnrichmentReport   # to_thread per chunk
```
- **Input:** enrichment runs on **inserted** ids only.
- **Behaviour change:** Mark VIII re-enriched every duplicate it re-fetched. Re-enriching updated rows is deferred to the analysis version, where it can key off a content-hash change.
- **Processors:** the real processors are `EntityMemoryService.process_posts` and `EventMemoryService.process_posts`.
- **Shared with archive:** archive runs use the same `Enricher` per page.

### B.3 Other repo changes
- `PostsRepository.get_source_post_stats` stays the only implementation. The 2-tuple copy in `safe_ingest.py` is deleted.
- Stale comments: `safe_ingest.py:125`, `:875` and `:949` go away with the file body. Any comment that moves into `save_batch` must describe the current behaviour: the collision lookup *is* inside the `insight_upsert_lookup` savepoint (`repo_posts.py:272`).

---

## C. Fetch-schedule module (pure decision + outcome recording)

### C.1 Data migration `0019_fetch_schedule.sql`

```sql
ALTER TABLE sources
  ADD COLUMN IF NOT EXISTS mean_gap_seconds DOUBLE PRECISION NULL,
  ADD COLUMN IF NOT EXISTS cadence_sample_size INT NULL,
  ADD COLUMN IF NOT EXISTS cadence_tier TEXT NOT NULL DEFAULT 'unknown'
      CHECK (cadence_tier IN ('fast','medium','slow','unknown')),
  ADD COLUMN IF NOT EXISTS cadence_computed_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS fetch_interval_hours_override DOUBLE PRECISION NULL
      CHECK (fetch_interval_hours_override IS NULL OR fetch_interval_hours_override > 0);

CREATE TABLE IF NOT EXISTS source_fetch_state (
  source_id            UUID PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  last_attempt_at      TIMESTAMPTZ NULL,
  last_success_at      TIMESTAMPTZ NULL,   -- healthy OR empty: the fetch worked
  last_outcome         TEXT NULL CHECK (last_outcome IN ('healthy','empty','error','unavailable')),
  last_trigger         TEXT NULL,
  last_fetched_posts   INT NULL,
  last_error           TEXT NULL,
  last_error_at        TIMESTAMPTZ NULL,
  consecutive_failures INT NOT NULL DEFAULT 0,
  next_retry_at        TIMESTAMPTZ NULL,
  last_decision_kind   TEXT NULL,
  last_decision_at     TIMESTAMPTZ NULL,
  next_due_at          TIMESTAMPTZ NULL,   -- denormalised from the last decision, for sorting in the UI
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS source_fetch_state_next_due_idx ON source_fetch_state (next_due_at);

-- Safe casts: the JSONB was written by Python and can be malformed (safe_ingest.py already
-- guards next_retry_at against ValueError; tests use "not-a-date"). A raw ::timestamptz would
-- abort migrate.py, and both start scripts run it under `set -euo pipefail`, so both
-- containers would crash-loop. pg_temp functions vanish with the session.
CREATE OR REPLACE FUNCTION pg_temp.try_ts(v text) RETURNS timestamptz LANGUAGE plpgsql AS $$
BEGIN RETURN NULLIF(v,'')::timestamptz; EXCEPTION WHEN others THEN RETURN NULL; END $$;
CREATE OR REPLACE FUNCTION pg_temp.try_int(v text) RETURNS int LANGUAGE plpgsql AS $$
BEGIN RETURN NULLIF(v,'')::int; EXCEPTION WHEN others THEN RETURN NULL; END $$;

-- Backfill from Mark VIII JSONB (settings.ops + settings.ingest_backoff), else from posts.
INSERT INTO source_fetch_state (source_id, last_attempt_at, last_success_at, last_outcome, last_trigger,
                                last_fetched_posts, last_error, last_error_at, consecutive_failures, next_retry_at)
SELECT s.id,
       pg_temp.try_ts(s.settings #>> '{ops,last_checked_at}'),
       -- Mark VIII only advanced ops.last_success_at on 'healthy'; Mark IX counts 'empty' as a
       -- success too, so an empty last check is the newer success.
       COALESCE(GREATEST(pg_temp.try_ts(s.settings #>> '{ops,last_success_at}'),
                         CASE WHEN s.settings #>> '{ops,last_status}' = 'empty'
                              THEN pg_temp.try_ts(s.settings #>> '{ops,last_checked_at}') END),
                (SELECT MAX(p.fetched_at) FROM posts p WHERE p.source_id = s.id)),
       -- Normalised here, not in a later UPDATE: the CHECK constraint is enforced during the
       -- INSERT, so an out-of-set value ('running', 'unknown', ...) must never reach it.
       CASE WHEN s.settings #>> '{ops,last_status}' IN ('healthy','empty','error','unavailable')
            THEN s.settings #>> '{ops,last_status}' END,
       NULLIF(s.settings #>> '{ops,last_trigger}',''),
       pg_temp.try_int(s.settings #>> '{ops,last_fetched_posts}'),
       CASE WHEN s.settings #>> '{ops,last_status}' = 'error' THEN s.settings #>> '{ops,last_message}' END,
       pg_temp.try_ts(s.settings #>> '{ops,last_error_at}'),
       GREATEST(COALESCE(pg_temp.try_int(s.settings #>> '{ingest_backoff,consecutive_failures}'), 0), 0),
       pg_temp.try_ts(s.settings #>> '{ingest_backoff,next_retry_at}')
FROM sources s
ON CONFLICT (source_id) DO NOTHING;

UPDATE sources SET settings = settings - 'ingest_backoff' - 'ops'
WHERE settings ? 'ingest_backoff' OR settings ? 'ops';
```
- The migration must be idempotent, and it runs inside the single transaction that `migrate.py` uses.
- `migrate.py` gets a real lock in B1: `acquire_migration_lock` runs `SELECT pg_advisory_xact_lock(hashtext('insight.migrate'))` as the first statement of that transaction, before `ensure_schema_migrations` and `applied_versions`. The backend and ingestion containers both run `migrate.py` at start, and a `CREATE TABLE IF NOT EXISTS` (0020) can fail with a duplicate `pg_type` key under two concurrent transactions. The "psycopg shim" comment no longer applies, because the image deletes the stubs (`backend/Dockerfile:22`). `release_migration_lock` stays a no-op, because the xact lock is released at commit or rollback.
- Cadence columns start out empty and are filled by the first `refresh_cadence()`. The migration also runs that SQL once at the end (C.3) so the UI is not blank.
- After this migration, nothing writes `settings.ops` or `settings.ingest_backoff`. `OperationsService.record_source_status` is **deleted**. Its only callers were the ingest paths (`safe_ingest.py:508,553` and `scripts/ingest.py:110,131`), and B1 switches all four to `record_outcome`.
- Anything that reads `settings.ops` must read `source_fetch_state` instead: `operations_service.py:340` (deleted) and `:440` (`get_source_health`, rewritten in §F.4).

### C.2 Pure decision function

```python
# ingestion/schedule.py
class DecisionKind(str, Enum):
    FETCH_NEW_SOURCE   = "fetch_new_source"    # no last_success_at and no posts
    FETCH_DUE          = "fetch_due"           # interval elapsed since last_success_at
    FETCH_RETRY        = "fetch_retry"         # in error state and next_retry_at elapsed
    FETCH_FORCED       = "fetch_forced"        # request.force
    SKIP_NOT_DUE       = "skip_not_due"
    SKIP_BACKOFF       = "skip_backoff"
    SKIP_UNAVAILABLE   = "skip_unavailable"    # yt-dlp off / no Telegram credentials or session (telegram_mtproto)
    SKIP_DISABLED      = "skip_disabled"       # only reachable for selector 'all'/'folder' defensive path
    @property
    def fetches(self) -> bool: ...

class CadenceTier(str, Enum):
    FAST = "fast"; MEDIUM = "medium"; SLOW = "slow"; UNKNOWN = "unknown"

@dataclass(frozen=True)
class CadenceStats:                 # read model, from sources + source_fetch_state + post_count
    post_count: int
    mean_gap: timedelta | None
    sample_size: int
    tier: CadenceTier
    override_hours: float | None
    max_posts_per_fetch: int
    last_success_at: datetime | None
    last_outcome: OutcomeStatus | None
    consecutive_failures: int
    next_retry_at: datetime | None

@dataclass(frozen=True)
class Availability:
    ytdlp_enabled: bool
    telegram_credentials: bool       # B1-B7: always False. B8: TELEGRAM_API_ID + TELEGRAM_API_HASH set
                                     # and the session file exists (whether it is *authorised* is only
                                     # known when the session opens; see §D.2 telegram_mtproto)
    telegram_reason: str | None = None   # B8: why telegram_credentials is False (shown as the skip reason)

def availability_from_env() -> Availability   # reads INSIGHT_YTDLP_ENABLED (B8: + TELEGRAM_API_ID/HASH and the
                                              # session file); injected into the runner as a callable

@dataclass(frozen=True)
class FetchDecision:
    kind: DecisionKind
    fetch: bool
    post_limit: int
    interval: timedelta              # the cadence interval in force (for display)
    interval_basis: Literal["override", "tier", "probation", "backlog_guard", "profile_floor"]
    next_due_at: datetime | None     # when it would next be fetched (None if unavailable)
    next_retry_at: datetime | None   # backoff deadline if in error state
    detail: str                      # human text for logs/UI, never parsed

def cadence_stats(source: Source, state: FetchStateRow | None) -> CadenceStats   # the ONLY constructor:
    # used by the runner, the B1 should_fetch_source shim and get_source_health, so they cannot drift
def decide_fetch(stats: CadenceStats, profile: PolitenessProfile, now: datetime, *,
                 force: bool, availability: Availability, requested_limit: int | None = None,
                 ignore_backoff: bool = False) -> FetchDecision
def fetch_interval(stats: CadenceStats, profile: PolitenessProfile) -> tuple[timedelta, str]
def tier_for(mean_gap: timedelta | None, sample_size: int) -> CadenceTier
def backoff_delay(consecutive_failures: int, *, rand: Callable[[], float] = random.random) -> timedelta
```

**Rules, in order:**
1. **Unavailable.** If `profile.requires == "ytdlp" and not availability.ytdlp_enabled`, or `profile.requires == "telegram_creds"` and not `availability.telegram_credentials` (always the case before B8; after B8, when the API credentials or the session file are missing) → `SKIP_UNAVAILABLE`, `fetch=False`. This applies even when `force` is set, and it never counts as backoff.
2. **Force.** `force` → `FETCH_FORCED`.
3. **Error state.** `consecutive_failures > 0 and next_retry_at`:
   - if `now < next_retry_at` → `SKIP_BACKOFF`
   - otherwise → `FETCH_RETRY`

   The error ladder applies *regardless of tier*, as the cadence spec requires. `ignore_backoff=True` skips this rule only, so rules 4 and 5 still apply. It exists for B1–B3, where the manual cycle keeps its Mark VIII behaviour (skip backoff, respect freshness: `safe_ingest.py:344-361`). B4 drops the argument from every caller because `force` supersedes it; the parameter is then deleted.
4. **New source.** No `last_success_at` and `post_count == 0` → `FETCH_NEW_SOURCE`.
5. **Due check.** `due = (last_success_at or epoch) + interval`. `now >= due` → `FETCH_DUE`, otherwise `SKIP_NOT_DUE`.

**`fetch_interval`:**
1. If an override is set → `override_hours`, with basis `"override"`. The override skips everything below, including the guard ("manual override wins").
2. If the tier is `unknown` → 24h, basis `"probation"`.
3. Otherwise: `base = clamp(mean_gap * 0.5, 24h, 21d)`, basis `"tier"`.
4. Profile floor: `base = max(base, profile.cadence_floor)`, basis `"profile_floor"` if it raised the value. For yt-dlp, `cadence_floor` = 168h. This keeps the Mark VIII weekly YouTube cadence, because yt-dlp is the expensive kind.
5. **Backlog guard (applied last, may go below the floor):** `cap = mean_gap * max(stats.max_posts_per_fetch, profile.min_posts_per_fetch)`. If `base > cap`, then `base = max(cap, 1h)` with basis `"backlog_guard"`.

   The guard only binds for fast sources, where the 24h floor or a yt-dlp week would let the feed overflow. Example: a mean gap of 30 minutes with `max_posts=20` caps the interval at 10h.

**Tier boundaries** (`tier_for`):
- `unknown` if `sample_size < 3`
- `fast` if `mean_gap < 12h`
- `medium` if `mean_gap ≤ 7d`
- `slow` otherwise

The tier is a *label*. The interval comes from the formula. This is a documented deviation from the cadence plan's table: the plan's "medium 3–5 d" and "slow 21 d" are approximations of the formula, and the formula wins.

**Post limit.** `post_limit = max(requested_limit or stats.max_posts_per_fetch, profile.min_posts_per_fetch)`. For YouTube the minimum is 15, which keeps the Mark VIII backlog guard.

**Backoff ladder decision: 1h base (spec), not 15m (Mark VIII code).**
- **Formula:** `backoff_delay(n) = min(1h · 2^(n−1), cap) · U(0.85, 1.0)`. With `cap = 24h`, the ladder is 1h, 2h, 4h, 8h, 16h, 24h, 24h, …
- **Dormant cap.** When `n ≥ INSIGHT_BACKOFF_DORMANT_AFTER` (default 10, roughly a week of daily failures), the cap rises to 7d. The UI labels such a source "dormant".
- **Why 1h:**
  1. The scheduler now ticks every 60 minutes (§A.4), so any delay under 1h rounds up to the next tick anyway. A 15m base would make steps 1–3 (15m, 30m, 60m) all mean "next tick", which looks like three retries but behaves like one.
  2. With 1h, every step of the ladder is observable and distinct at the tick resolution.
  3. It matches `INSIGHT_adaptive_fetch_cadence_plan.md`.
  4. The dormant cap is the Mark IX addition. It targets the case the plan names, where 32 dead YouTube channels each cost a yt-dlp timeout per cycle. At a 24h cap they still cost one timeout a day each.
- **Env vars:** `INSIGHT_BACKOFF_BASE_MINUTES` (default 60), `INSIGHT_BACKOFF_MAX_HOURS` (24), `INSIGHT_BACKOFF_DORMANT_AFTER` (10), `INSIGHT_BACKOFF_DORMANT_MAX_HOURS` (168). The `SAFE_INGEST_*` names are removed, and `.env.example`/README are updated if they mention them.

**Fixes that fall out of this design:**
- **🚫 miscount.** The report counts `decisions["skip_backoff"]` from an enum, so yt-dlp-disabled sources show up only under `skip_unavailable`.
- **Manual fetch applies freshness.** A forced fetch (fetch-now, track fetch, "force" cycle) ignores cadence and backoff but still honours unavailability. The non-forced "Run cycle" button respects cadence, which is the intended "run what's due" behaviour.
- **Staleness from `MAX(posts.fetched_at)`.** The interval counts from `last_success_at`, which empty fetches also advance. `posts.fetched_at` is no longer read by the scheduler.
- **Two YouTube checks disagree.** The rules use only `profile.requires` and `profile.cadence_floor`, both of which come from the resolved **kind**. A `/feeds/videos.xml` URL stored as `rss` therefore gets the yt-dlp rules consistently.

### C.3 Outcome recording and cadence refresh

```python
# db/repo_fetch_state.py
@dataclass(frozen=True)
class FetchStateRow: ...  # mirrors table columns

class FetchStateRepository:
    def load(self, cur, source_ids: Sequence[str]) -> dict[str, FetchStateRow]
    def record_decisions(self, cur, decisions: Sequence[tuple[str, FetchDecision]], now: datetime) -> None
    def record_outcome(self, cur, outcome: FetchOutcome, *, trigger: Trigger, now: datetime,
                       backoff: Callable[[int], timedelta]) -> FetchStateRow
    def record_outcomes(self, cur, outcomes: Sequence[FetchOutcome], *, trigger: Trigger, now: datetime,
                        backoff: Callable[[int], timedelta]) -> list[FetchStateRow]   # loop of record_outcome
    def refresh_cadence(self, cur, *, window: int = 20, min_samples: int = 3) -> int   # rows updated
    def load_schedule_view(self, cur) -> list[dict]   # for GET /api/sources/health (joins sources, counts, folders)
```

**`record_outcome`** is a single `INSERT … ON CONFLICT (source_id) DO UPDATE` that computes `consecutive_failures` in SQL. It is atomic and has no read-modify-write:
- `error` → `consecutive_failures + 1` and sets `last_error`/`last_error_at`. The UPSERT does `RETURNING consecutive_failures`; the repo then calls `backoff(new_count)` and sets `next_retry_at = now + delay` with a second `UPDATE … WHERE source_id = %s` in the same transaction. The delay is computed from the count the database returned, so two concurrent runs cannot both write a delay for a stale count. The in-memory fake applies the same callable to its own counter, so it mirrors the real store exactly.
- `healthy` or `empty` → resets the counter, clears `next_retry_at`, sets `last_success_at`.
- `unavailable` → touches only `last_attempt_at`, `last_outcome` and `last_error`. The counter is unchanged.

**`refresh_cadence`** runs the SQL from the cadence plan:
- It works on the latest 20 `published_at` per source and requires `HAVING count ≥ 3`.
- It writes `mean_gap_seconds`, `cadence_sample_size`, `cadence_tier` (with the tier CASE in SQL kept identical to `tier_for`) and `cadence_computed_at`.
- Sources below the threshold get `tier='unknown'`, `mean_gap=NULL`.
- A test asserts that the SQL tier and `tier_for` agree, using the boundary cases.

`FetchStateStore` (the ingestion port) wraps this repo. It opens one connection per *method call*, so the runner makes exactly three store calls per run (`load`, `record_decisions`, `record_outcomes`), each through `to_thread`.

**Schedule preview.** `GET /api/sources/health` builds each row with `cadence_stats(source, state_row)` and then `decide_fetch(..., force=False)` to compute `next_due_at` and `would_fetch_now`. Because the runner, the health API and the B1 shim all go through the same two functions, the UI and the runner cannot disagree.

---

## D. Source-kind adapters (one seam)

### D.1 Interface

```python
# ingestion/kinds/base.py
@dataclass(frozen=True)
class RateLimit:                         # the effective archive pacing for one run
    page_delay_s: float
    batch_size: int                      # 0 = no batch cooldown
    batch_cooldown_s: float

@dataclass(frozen=True)
class PolitenessProfile:
    concurrency_pool: Literal["host-lock", "ytdlp"]
    page_delay_s: float = 0.0
    batch_size: int = 0                  # 0 = no batch cooldown
    batch_cooldown_s: float = 0.0
    live_pages_rate_limited: bool = False
    cadence_floor: timedelta = timedelta(0)
    min_posts_per_fetch: int = 0
    requires: Literal["none", "ytdlp", "telegram_creds"] = "none"
    blocking_io: bool = False            # run fetch/inspect in a thread
    # No host floor here: host spacing is keyed by host (HOST_FLOORS, §D.3), not by kind.
    def rate_limit(self, overrides: Mapping[str, Any] | None = None) -> RateLimit: ...
        # profile defaults <- persisted settings.archive.rate_limit <- request overrides
        # (pageDelaySeconds / batchSize / batchCooldownSeconds from /api/archive/{id}/plan and /run).
        # Replaces SourceFetchService._resolve_rate_limit (source_fetch_service.py:1442-1501).
    def estimate_seconds(self, pages: int, rate: RateLimit) -> int: ...   # generic, replaces the _estimate_seconds ladder

@dataclass(frozen=True)
class Inspection:
    available_posts: int | None
    page_size: int | None
    first_post_date: str | None
    raw: dict                            # kind-specific extras persisted into settings.archive

@dataclass(frozen=True)
class ArchivePage:
    posts: list[dict]
    checkpoint: dict | None              # None = finished

class SourceKind(Protocol):
    name: str                            # strategy string, persisted as settings.archive.source_type
    profile: PolitenessProfile
    def matches(self, source: Source) -> bool
    def host_key(self, source: Source) -> str
    async def fetch_latest(self, source: Source, limit: int) -> list[dict]
    async def inspect(self, source: Source) -> Inspection
    def archive_pages(self, source: Source, target: int, checkpoint: dict | None,
                      rate: RateLimit) -> AsyncIterator[ArchivePage]
    def checkpoint_resumable(self, checkpoint: Any) -> bool
    def estimate_pages(self, remaining: int, page_size: int | None) -> int

class KindUnavailable(Exception): ...   # e.g. telegram not authorised -> outcome UNAVAILABLE

# Added in B8. Every kind has a session; all but telegram_mtproto use NullKindSession (a no-op).
class KindSession(Protocol):
    async def open(self) -> None         # may raise KindUnavailable(reason); never prompts
    async def close(self) -> None        # idempotent; called in a finally
#   SourceKind gains:  def session(self) -> KindSession

class KindRegistry:
    def __init__(self, kinds: Sequence[SourceKind]): ...   # ordered by priority
    def resolve(self, source: Source) -> SourceKind          # cached by (platform, handle_or_url)
    @staticmethod
    def default(http: KindHttp, youtube: YouTubeService) -> "KindRegistry"
```

**Resolution priority:**
1. the 6 site adapters (host plus path match)
2. `reddit_subreddit` (platform reddit, or a `/r/` URL not ending in `.rss`/`.xml`)
3. `youtube_channel` (platform youtube, or a `/feeds/videos.xml` URL)
4. `telegram_rss`
5. `nitter_rss`
6. `telegram_mtproto` (platform telegram **and** a bare handle, no `://`)
7. `generic_rss`, which is the fallback

For every source *except* platform-telegram bare handles, this matches Mark VIII `classify_source` (`source_fetch_service.py:494-532`), and a table test pins it. **Deliberate deviation:** `classify_source` has no MTProto branch, so today a bare handle such as `ai_newz` (platform telegram) falls through to `generic_rss` and fails as an RSS URL. (Mark VIII `safe_ingest` did reach these through `TelegramConnector`, which prompts on stdin when the session is not authorised.) In Mark IX they resolve to `telegram_mtproto`. B3 ships the kind's resolution and profile; until B8 lands, `Availability.telegram_credentials` is False, so they are `skip_unavailable`. B8 makes them fetchable when an authorised session exists. All 12 such sources are currently disabled. The table test carries this as an explicit, labelled row.

### D.2 Kinds and profiles

| Kind | Real implementation (moved from) | Profile |
|---|---|---|
| `generic_rss` | `_fetch_text` + `_parse_feed_posts` + `_maybe_enrich_generic_rss_posts` | host-lock; floor 0 |
| `telegram_rss` | `_collect_telegram_posts`, `_inspect_telegram_source`, `_find_last_telegram_page` | host-lock (its hosts carry a 5s host floor in `HOST_FLOORS`); page 5s; batch 10 / 30s; **`live_pages_rate_limited=True`** (fixes the FLOOD_WAIT 429s); live fetch honours `?limit=` in the URL and fetches only the pages needed for `limit` |
| `nitter_rss` | `_collect_nitter_posts`, `_inspect_nitter_source` | host-lock; page 10s; batch 10 / 30s; live rate-limited |
| `reddit_subreddit` | live: **new** `/r/{sub}/new/.rss` through the generic RSS parser (the JSON endpoint returns 403 on every cycle; the 10 `.rss` reddit sources are platform `rss` and already resolve to `generic_rss`); archive: `_collect_reddit_posts` JSON (best-effort, failures surface as archive errors) | host-lock; page 2s. The 8s reddit spacing is a **host floor** (`reddit.com` and `platform:reddit` in `HOST_FLOORS`, §D.3), so it also covers the `generic_rss` reddit feeds |
| `youtube_channel` | `youtube_service.fetch_live_posts` / `inspect_channel` / `archive_channel_posts` | **ytdlp** pool (sem 2, 3s spacer); `requires="ytdlp"`; `blocking_io=True` (fixes the archive call that blocked the event loop); `cadence_floor=168h`; `min_posts_per_fetch=15`; page 2s (one constant) |
| `telegram_mtproto` | **Real in Mark IX (B8)**, built from `connectors/telegram_connector.py`: `_synthesize_messages` (album grouping) becomes the pure `synthesize_posts(messages, handle)`, the `get_entity` error mapping and the chunked `get_messages(offset_id=…)` loop become `fetch_latest` / `archive_pages`, and the `request_counter` throttle becomes the profile. **Session lifecycle:** one `TelegramSession` per run (`kind.session()`), opened lazily by the runner before the first due telegram source and closed in a `finally`. `open()` takes a Postgres advisory lock (`hashtext('insight.telegram_session')`; Telethon's SQLite session file cannot be shared by two processes), connects, and checks `is_user_authorized()`. It **never** calls `client.start()`, `send_code_request` or `input()`: a missing or unauthorised session raises `KindUnavailable("Telegram session not authorised; run scripts/telegram_login")`, and a held lock raises `KindUnavailable("Telegram session in use by another run")`. Authorisation happens only in the operator CLI `scripts/telegram_login.py`. **Flood wait:** the client is built with `flood_sleep_threshold=0`, so every `FloodWaitError` reaches the kind (translated to `TelegramFloodWait(seconds)`). A wait ≤ `MAX_INLINE_FLOOD_WAIT_S` (60) is slept through the injected sleeper and the request retried once. A longer wait fails that source (outcome `error`, normal backoff, message "flood wait Ns") and marks the session `flooded_until = now + seconds`; every later telegram source in the run raises `KindUnavailable("Telegram flood wait until …")`, which is not backoff. **Inspect:** `get_entity` + `get_messages(limit=1)` (`.total` → `available_posts`) + the oldest message's date. **Archive:** `archive_pages` yields one `ArchivePage` per 100-message chunk with checkpoint `{"offset_id": <last id>}`, and `None` when a chunk comes back empty. Host key is the constant `platform:telegram` for every MTProto source, so the host lock serialises all of them onto the one client | host-lock (`platform:telegram`, 2s host floor); page 1s; batch 10 / 18s (the connector's 10-request / 18s throttle); `live_pages_rate_limited=True`; `requires="telegram_creds"` |
| 6 sites (`lesswrong_graphql`, `gwern_site`, `dario_site`, `deeplearning_batch_site`, `philschmid_cloud_attention`, `zerotomastery_ml_monthly`) | `adapters/*.py`. **`BaseSourceAdapter` implements `SourceKind` directly; there is no `SiteKind` wrapper.** The constructor takes `http: KindHttp` instead of `service`. Every `self.service.*` call moves: `_fetch_text`/`_post_json` → `self.http`; `_strip_html`, `_isoformat`, `_parse_datetime_value`, `_local_name`, `_child_text`, `_extract_article_html`, `_extract_html_image_urls` → `kinds/parsing.py`. `inspect_source` → `inspect` (returns `Inspection`). `fetch_live_posts` → `fetch_latest`. `checkpoint_is_resumable` → `checkpoint_resumable`. `archive_posts(..., progress_callback, page_callback, rate_limit)` becomes `archive_pages(source, target, checkpoint, rate)`: each place that called `self.service._emit_page(page_callback, posts, checkpoint, ...)` now `yield ArchivePage(posts, checkpoint)`, and the `_emit_progress` calls are dropped (the archive loop reports progress per page). `default_rate_limit()` becomes the class `profile` | host-lock; page delay = the adapter's `PAGE_DELAY_SECONDS` (1s) |

**`archive_pages`.** Single-shot kinds (`generic_rss`, `youtube_channel`) yield one page with `checkpoint=None`. This removes the "persist once at the end" special case at `source_fetch_service.py:296`. `archive_source` becomes one loop:

```
async for page in kind.archive_pages(...):
    save_batch → enrich → record checkpoint → progress
```

The page delays are enforced *inside* the kind using the `rate` it was given (`await self.http.sleep(rate.page_delay_s)`), so tests inject a recording sleeper through `KindHttp`.

### D.3 `FetchGates` (fixes the data clump and the duplicated acquisition)

```python
# ingestion/gates.py
# Host-keyed floors (seconds between request starts). Keys are HostLimiter.host_key values:
# extract_url_host output (www. stripped, HOST_ALIASES applied) or "platform:<p>" for bare handles.
HOST_FLOORS: Mapping[str, float] = {
    **{h: 5.0 for h in TELEGRAM_RSS_HOSTS},     # was SourceFetchService.TELEGRAM_HOSTS / TELEGRAM_PAGE_DELAY_SECONDS
    **{h: 10.0 for h in NITTER_HOSTS},          # was NITTER_HOSTS / NITTER_PAGE_DELAY_SECONDS
    "reddit.com": 8.0,                          # the 10 .rss reddit feeds (kind generic_rss)
    "platform:reddit": 8.0,                     # bare r/<sub> handles (kind reddit_subreddit)
    "platform:telegram": 2.0,                   # B8: every telegram_mtproto source (one shared client)
}

class FetchGates:
    def __init__(self, *, max_concurrency: int = 8, ytdlp_concurrency: int = 2, ytdlp_min_start_interval_s: float = 3.0,
                 host_floors: Mapping[str, float] = HOST_FLOORS): ...
    @classmethod
    def shared(cls) -> "FetchGates"          # process-wide singleton, env-configured
    @asynccontextmanager
    async def slot(self, profile: PolitenessProfile, host_key: str, *, per_source_delay_s: float = 0.0): ...
```
`slot` is the **only** place that turns a profile into acquisitions:
- `ytdlp` → yt-dlp semaphore + spacer + global semaphore
- `host-lock` → host limiter (with `max(host_floors.get(host_key, 0), per_source_delay_s)`) + global semaphore

The host floor table is owned by `FetchGates` (it replaces `HOST_MIN_INTERVAL_OVERRIDES`, which was applied inside `_HostLimiter.slot`, `safe_ingest.py:99-104,165`). `TELEGRAM_RSS_HOSTS` and `NITTER_HOSTS` move from `SourceFetchService` into `ingestion/kinds/telegram_rss.py` and `nitter_rss.py`, and `gates.py` imports them from there.

Fetch and inspection refresh both call it, which removes the `safe_ingest.py:457` / `:978` duplication.

Environment variables are renamed to `INSIGHT_FETCH_MAX_CONCURRENCY`, `INSIGHT_YTDLP_CONCURRENCY` and `INSIGHT_YTDLP_MIN_INTERVAL`. `INSIGHT_YTDLP_ENABLED` is kept and read into `Availability`. `HostLimiter`, `StartSpacer` and `interleave_by_host` move unchanged from `safe_ingest.py`, together with their existing tests.

### D.4 What `source_fetch_service.py` keeps
- `plan_archive`, `archive_source` (now a loop over `kind.archive_pages`) and `get_archive_status`. Both still accept the `pageDelaySeconds`/`batchSize`/`batchCooldownSeconds` overrides from `/api/archive/{id}/plan` and `/run` (`main.py:1484-1488,1503-1507`) and turn them into a `RateLimit` with `kind.profile.rate_limit(overrides)`, which is passed to `archive_pages` and `estimate_seconds` and persisted as `settings.archive.rate_limit`.
- `get_archive_catalog`
- the archive metadata writer **moves out** to `ingestion/archive_metadata.py` as `ArchiveMetadataWriter.record(source_id: str, kind: SourceKind, data: dict, mode: Literal["plan","archive","archive_progress","live"])`, together with `_derive_archive_status`, `_prepare_checkpoint` and `_archive_history_event`. Today `_record_archive_metadata_sync` reaches back into `_estimate_pages`/`_estimate_seconds` (`:1387-1388`) and `_checkpoint_is_resumable` (`:1424`); after the move it calls `kind.estimate_pages`, `kind.profile.estimate_seconds(pages, kind.profile.rate_limit(data.get("rate_limit")))` and `kind.checkpoint_resumable`, so the dependency on the kind is explicit in the signature. `record_live_fetch` is deleted (the runner's `DbInspectionRefresher` calls the writer).
- `fetch_reddit_comments_for_post`, used by post_detail. It delegates to `KindHttp` + the reddit JSON helper.

**Removed** (moved into kinds, or gone):
- `classify_source`, `fetch_live_posts`, `inspect_source`
- `_estimate_seconds`, `_estimate_pages`, `_resolve_rate_limit`, `_checkpoint_is_resumable`, `_record_archive_metadata_sync`, `record_live_fetch`
- all `_collect_*`, `_inspect_*` and `_parse_*` helpers
- `ingest_source_now`, `_persist_posts`
- the `TELEGRAM_HOSTS`/`NITTER_HOSTS`/`*_PAGE_DELAY_SECONDS` constants

The target size is under 500 lines, down from 1727.

### D.5 Dead code removal (proven dead by the source-kinds map §5)

**Deleted:**
- `connectors/rss_connector.py`, `reddit_connector.py`, `youtube_connector.py`, `tool_registry.py`
- `discover_connectors`, `AVAILABLE_CONNECTORS`, `setup_connectors`, `get_available_connector_types`, `list_discovered_connectors` and `create_connector` from `connectors/__init__.py`. The file is reduced to re-exporting `TelegramConnector` and `BaseConnector`, if `base_connector.py` exists and Telegram uses it.
- In B8: `connectors/telegram_connector.py`, once its logic has moved into `ingestion/kinds/telegram_mtproto.py`, and with it `base_connector.py` and `connectors/__init__.py` if nothing else imports them (the legacy `engines/mark_i_foundation_engine.py` still calls `create_connector`; B5 must already have dealt with that call, see the §D.5 grep).
- The undiscovered ad-hoc scripts `tests/connector_test.py`, `tests/upsert_test.py`, `tests/upsert_multiple_test.py` and `tests/read_posts.py`
- Every file under `tests/old tests/` that imports a deleted module. Verify with `grep -l "rss_connector\|reddit_connector\|youtube_connector\|tool_registry" -r "backend/insight_core/tests/old tests"`.

**Verification before deleting:**

```
grep -rn "rss_connector\|reddit_connector\|youtube_connector\|tool_registry\|discover_connectors\|AVAILABLE_CONNECTORS\|create_connector" backend --include=*.py
```

After the deletion, the command must return only the lines being deleted.

**Not deleted:** the 6 site adapters (tested, cheap), nitter (cheap, tested by unit tests) and reddit JSON, which comments still use.

---

## E. Targeted fixes

| # | Fix | Where it lands |
|---|---|---|
| E1 | **`backlog_posts` edge case** (`source_fetch_service.py:1375`: `derived_remaining = remaining_posts = data.get("remaining_posts")`). When `available_posts` is not an int, `backlog_posts` silently takes the *plan's* `remaining_posts`, which describes a requested archive target and is not the backlog. Rule: `backlog_posts = max(available − stored, 0)` when `available_posts` is a known int, otherwise `None` (UI shows "unknown"). `remaining_posts` stays the plan field and is never aliased. | Slice 3; `ArchiveBacklogEstimateTests` gains the "available unknown → backlog None" case |
| E2 | Stale comments: `safe_ingest.py:125`, `:875`, `:949`; `api.ts:2361`; unused `MilestoneNode` type at `api.ts:2488` | The safe_ingest comments go with the file (slice 4). api.ts is fixed in F1. |
| E3 | `FetchGates` data clump (`_fetch_source(..., semaphore, ytdlp_semaphore, spacer, host_limiter)`) | Slice 3 (`gates.py`) |
| E4 | Duplicated gate acquisition, `safe_ingest.py:457` vs `:978` | Slice 4: the runner uses `gates.slot` for both |
| E5 | `safe_ingest` job left "running" when an exception is raised | Slice 4: `try/finally` in `run_cycle` |
| E6 | `classify_source` builds 6 adapters per call | Slice 3: the `KindRegistry` cache |
| E7 | YouTube archive blocks the loop; the archive ignores `INSIGHT_YTDLP_ENABLED` | Slice 3 (`blocking_io`) and slice 4: `archive_source` checks `Availability` before planning and returns a 409 `{error:"yt-dlp disabled"}` |
| E8 | `merge_source_settings` last-writer-wins | Mitigated: `ops` and `backoff` leave JSONB (C.1). `repo_sources.merge_source_settings` also reads through its own `SELECT settings FROM sources WHERE id = %s FOR UPDATE` inside its transaction, instead of `get_source_by_id` (`repo_sources.py:228`). `get_source_by_id` has 8 non-test callers and stays lock-free (slice 1; a small change plus a test). |
| E9 | `pollOperationPayload` gives up on the first transient error and never cancels | F1 |

---

## F. Information reading + UI/UX

### F.1 Selection (what is in, and why)
The ranking is user value ÷ (risk + cost):
1. **Reader-first feed at `/`** with cursor pagination. This replaces the N+1 "all posts" load. *In.*
2. **Unread/read + starred state** in lists, with mark read on open, mark all read up to here, and the Unread/Starred/All filters. *In.* It needs a projection table, because a list query cannot aggregate `post_interactions` per row cheaply.
3. **Keyboard navigation**: j/k, o/Enter, m, s, u/Esc, `?`, plus prev/next on the post page, with an on/off switch (WCAG 2.1.4). *In.* A pure reducer makes it testable. Search (`/`) is **deferred**: no search endpoint exists.
3a. **By-source view and compact density.** In the latest 30-day window, four arXiv feeds produce 47% of the 2,721 posts (cs.CL 340, cs.LG 340, physics.optics 335, cs.AI 260) and `r/EvenRealities` another 200, so a flat stream buries the low-volume blogs. The feed gets `view=stream|by_source` and a title-only "compact" density toggle. *In.*
4. **Reading view typography and speed**: a ~68ch column at 18px with line-height 1.7, `@tailwindcss/typography` installed, original content first, and the AI summary collapsible. The post load moves to react-query so the next post can be prefetched. *In.*
5. **Source health table** in Settings → Sources: tier, interval and basis, next due, backoff, last success, last error, skip reason, override, Fetch now. *In.*
6. **Run report display**, plus one "Run cycle" button with a force checkbox, a track fetch button and toasts. *In.*
7. **Consistent states.** Shared `<LoadingState/>`, `<EmptyState/>` and `<ErrorState/>` components, an app-level error boundary, and an `ApiError` type with clean messages. Used on all *new and touched* surfaces. *In.*
8. **Persistent nav rail** on the reader only. The other pages keep their own "Back". Below the `md` breakpoint the rail becomes a drawer opened from `FeedToolbar`. *In (reader only).*
9. **Out:** splitting DailyBriefing, mobile work beyond the reader (the reader itself must work at 375px, §F.6), the slate dark-mode remap on IngestionControl (except the new components, which use tokens only), and moving every page to react-query.

### F.2 Backend for reading — migration `0020_reader_state.sql`

```sql
CREATE TABLE IF NOT EXISTS post_reader_state (
  post_id    UUID PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  read_at    TIMESTAMPTZ NULL,
  starred_at TIMESTAMPTZ NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_reader_state_starred_idx ON post_reader_state (starred_at) WHERE starred_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS posts_feed_order_idx ON posts ((COALESCE(published_at, fetched_at)) DESC, id DESC);
CREATE INDEX IF NOT EXISTS posts_source_feed_order_idx ON posts (source_id, (COALESCE(published_at, fetched_at)) DESC, id DESC);

-- Backfill from the interaction log
INSERT INTO post_reader_state (post_id, read_at, starred_at)
SELECT post_id,
       MIN(created_at) FILTER (WHERE interaction_type = 'opened'),
       (SELECT CASE WHEN i2.interaction_type = 'favorited' THEN i2.created_at END
          FROM post_interactions i2
         WHERE i2.post_id = i.post_id AND i2.interaction_type IN ('favorited','unfavorited')
         ORDER BY i2.created_at DESC LIMIT 1)
FROM post_interactions i
GROUP BY post_id
ON CONFLICT (post_id) DO NOTHING;
```
- `post_interactions` stays the audit log.
- Live data today has only `opened` (5) and `reading_session` (5) rows and no `favorited` rows, so the backfill sets `read_at` for the opened posts and `starred_at` stays empty until the first star toggle. That is expected, not a bug.
- B7 acceptance query: `SELECT count(*) FROM post_reader_state WHERE read_at IS NOT NULL` equals `SELECT count(DISTINCT post_id) FROM post_interactions WHERE interaction_type = 'opened'`.
- `PostDetailService.record_post_open` also sets `read_at` (`COALESCE(read_at, now())`).
- The favorite endpoint also sets or clears `starred_at`.
- `get_post_reader_state` reads `is_favorited` from the projection.

```python
# db/repo_reader.py
@dataclass(frozen=True)
class FeedScope:
    kind: Literal["all", "folder", "source"]   # 'all' honours sources.in_main_digest; starred is a filter, not a scope
    id: str | None = None

FeedView = Literal["stream", "by_source"]

@dataclass(frozen=True)
class FeedCursor:
    sort_at: datetime
    post_id: str
    def encode(self) -> str: ...   # urlsafe base64 of "iso|uuid"
    @staticmethod
    def decode(s: str) -> "FeedCursor": ...

class ReaderRepository:
    def feed(self, cur, scope: FeedScope, *, filter: Literal["all", "unread", "starred"], cursor: FeedCursor | None,
             limit: int = 30, since: datetime | None = None) -> tuple[list[dict], FeedCursor | None]
    def feed_by_source(self, cur, scope: FeedScope, *, filter: Literal["all", "unread", "starred"],
                       per_source: int = 3, group_cursor: FeedCursor | None = None, groups: int = 20
                       ) -> tuple[list[dict], FeedCursor | None]
        # one group per source: {source_id, source_display_name, platform, newest_sort_at, count, items[<=3]},
        # ordered by newest_sort_at desc; keyset on (newest_sort_at, source_id); count honours the filter + window
    def set_read(self, cur, post_ids: Sequence[str], read: bool) -> int
    def set_starred(self, cur, post_id: str, starred: bool) -> None
    def mark_read_through(self, cur, scope: FeedScope, through: FeedCursor, *, newest: FeedCursor,
                          now: datetime) -> list[str]
        # see the bound below; returns the ids it marked so the UI can undo
    def unread_counts(self, cur) -> dict   # {total, by_source: {id: n}, by_folder: {id: n}}
```
- **`mark_read_through` is bounded.** It marks posts in `scope` whose sort key is between `through` and `newest` inclusive (`newest` is the first item the client loaded, so posts that arrived after the page was rendered stay unread), **and** within the unread window (`sort_at >= now - INSIGHT_UNREAD_WINDOW_DAYS`), **and** with `read_at IS NULL`. So scope `all` writes at most the window's unread rows, never one row per archive post. The route returns `{success, updated: n, ids}`; the UI toast offers a 5-second Undo that calls `set_read(ids, false)`.
- **Feed query:** keyset `WHERE (COALESCE(p.published_at,p.fetched_at), p.id) < (%s, %s)`, ordered descending.
- **Each item carries:**
  - `id`, `title` (never empty: falls back to the first 80 characters of the excerpt; 9 posts have an empty title today), `excerpt` (first 280 characters of content with tags stripped)
  - `url`, `source_id`, `source_display_name`, `platform`, `sort_at`, `published_at`
  - `read_at`, `starred_at`
  - `reading_minutes` (`ceil(length(content) / 1100)`, about 200 words a minute; NULL for YouTube) and `duration_seconds` (`metadata->>'duration_seconds'` for YouTube, else NULL)
  - `media_thumb` (first media url)
- **Search is deferred.** There is no search endpoint today and `/api/feed` gets no `q=` in Mark IX; it is an analysis-version candidate (trigram index on title).
- **"Unread" window:** "unread" means `read_at IS NULL`. `unread_counts` only counts the last 30 days (`INSIGHT_UNREAD_WINDOW_DAYS`), so a 50k-post archive backfill does not show "48,213 unread". The feed's unread filter and `mark_read_through` apply the same window.

### F.3 Frontend architecture for the new surfaces

**New files:**

```
frontend/tsconfig.json, tsconfig.node.json      F1
frontend/src/lib/apiError.ts (+ .test.ts)       ApiError {status, message, detail}; clean message (no "| url=")
frontend/src/lib/jobPolling.ts (+ .test.ts)     pollJob(fetchJob, {signal, intervalMs, timeoutMs, maxConsecutiveErrors=3})
frontend/src/lib/runReport.ts (+ .test.ts)      summarizeRunReport(report) -> {headline, lines[], tone}; DECISION_LABELS
frontend/src/lib/sourceSchedule.ts (+ .test.ts) formatDue(nextDueAt, now), backoffLabel(row), tierLabel, sortHealthRows
frontend/src/lib/feedNavigation.ts (+ .test.ts) pure reducer: (state, action) -> state for j/k/o/m/s/u + load-more trigger
frontend/src/lib/feedContext.ts (+ .test.ts)    encode/decode the ?ctx=<scope>:<filter>:<cursor> query param for prev/next
frontend/src/lib/dates.ts (+ .test.ts)          localDateISO(), formatRelativeTime() (one shared helper)
frontend/src/services/ApiContext.tsx            ApiProvider + useApi(); defaults to the apiService singleton.
                                                New components call useApi(), never import apiService directly
frontend/src/hooks/useFeed.ts                   react-query useInfiniteQuery(['feed', scope, filter, view]),
                                                staleTime: Infinity, refetchOnWindowFocus: false (see "Live data" below)
frontend/src/hooks/usePost.ts                   useQuery(['post', id]) + prefetchPost(id) for the selected and next item
frontend/src/hooks/useReaderMutations.ts        optimistic setRead/setStarred/markReadThrough + invalidate counts
frontend/src/hooks/useIngestionRun.ts           start run -> poll job -> toast -> invalidate ['unread-counts'], ['sources-health']
                                                (never ['feed']: the feed shows a "N new posts" pill instead)
frontend/src/hooks/useShortcutPreference.ts     keyboard shortcuts on/off, persisted in localStorage
frontend/src/hooks/useKeyboardShortcuts.ts      binds keys -> feedNavigation actions; ignores inputs/textareas
frontend/src/components/states/{LoadingState,EmptyState,ErrorState}.tsx
frontend/src/components/AppErrorBoundary.tsx
frontend/src/components/reader/{ReaderNavRail,FeedList,FeedItem,FeedToolbar,ShortcutHelp}.tsx
frontend/src/components/ops/{RunReportSummary,RunCycleButton,SourceHealthTable,CadenceOverrideEditor}.tsx
frontend/src/pages/ReaderPage.tsx               route "/" and "/read/:scopeKind/:scopeId?"
```

**Changed files:**
- `App.tsx`: the routes `/` → `ReaderPage` and `/hub` → `Index` (renamed "All tools"), plus `AppErrorBoundary` around `<Routes>` and `ApiProvider`. The global fixed `ThemeToggle` (`App.tsx:26-27`, `fixed bottom-4 right-4 z-50`) is not rendered on reader routes; `ReaderNavRail`/`FeedToolbar` host it there, so it cannot cover "Load more" or row buttons.
- `PostDetailPage.tsx`:
  - the post load (`:549-606`, `useState`/`useEffect`) moves to `usePost(id)` (`useQuery(['post', id])`), so the reader can prefetch it
  - the timeline (`getPostTimeline`, `:609-611`) loads only when its panel is expanded; the YouTube progress call (`:613-621`) runs only for YouTube posts
  - prev/next from `?ctx=` (`feedContext`), with keyboard j/k/u. At the last loaded id it calls `getFeed` with the context's cursor to fetch the next page. With no `ctx`, j/k are disabled and a visible "Back to feed" link is shown
  - the reading column (`max-w-[68ch] text-[18px] leading-[1.7] prose`)
  - original content before the summary, with the summary in a collapsible `<details>`
  - the action bar wraps (`flex-wrap`)
  - the "inspired by youtube2webpage" copy is removed
- `TrackPage.tsx`: a "Fetch this track" button (`useIngestionRun`), `returnTo` + feedContext on "Read", read state on cards, and the empty state offers a fetch
- `SourcesConfig.tsx`: a new "Health & cadence" tab hosting `SourceHealthTable`, and confirmation dialogs on delete
- `SourceSettingsEditor.tsx`: the cadence override field and the main-digest toggle; the `parseInt(...)||0` bug becomes validation
- `IngestionControl.tsx`: "Run Full Ingestion"/"Ingest Now"/"Run Safe Ingestion" are replaced by `RunCycleButton` (Run due sources, plus a "Force all (ignore cadence & backoff)" checkbox with a confirm); Recent Responses renders `RunReportSummary` with a raw-JSON disclosure kept below it; the 8-row health list links to Settings → Sources → Health
- `DailyBriefing.tsx`:
  - the `ingestPosts`/`safeIngestPosts` buttons are removed, along with the "All posts" mode
  - the "Open reader" link remains
  - the "N source errors" chip links to `/settings/sources?tab=health&status=error`
  - "Fetch Posts" is relabelled "Load posts"
  - the success message moves from the error banner to a toast
- `services/api.ts`: see the API table in §4

**Key TS types (in `api.ts`):**

```ts
export type DecisionKind = 'fetch_new_source'|'fetch_due'|'fetch_retry'|'fetch_forced'
  |'skip_not_due'|'skip_backoff'|'skip_unavailable'|'skip_disabled';
export type CadenceTier = 'fast'|'medium'|'slow'|'unknown';
export type OutcomeStatus = 'healthy'|'empty'|'error'|'unavailable';
export type SourceSelector = {kind:'all'} | {kind:'folder'; id:string} | {kind:'source'; id:string};

export interface RunReport {
  run_id: string|null; trigger: 'scheduler'|'manual'|'cli'; selector: SourceSelector; force: boolean;
  status: 'success'|'partial'|'failed'|'skipped_busy'|'nothing_due';
  started_at: string; finished_at: string;
  sources_considered: number; sources_fetched: number; sources_failed: number;
  decisions: Partial<Record<DecisionKind, number>>;
  posts_fetched: number; posts_inserted: number; posts_updated: number; posts_failed: number;
  failures: {source_id:string; display_name:string; stage:'fetch'|'save'|'connector'; error:string}[];
  post_failures: {url:string|null; source_id:string; stage:'upsert'|'discarded'; error:string}[];
  inserted_by_source: {source_id:string; display_name:string; inserted:number}[];
  enrichment: Record<string, {posts:number; chunks:number; failed_chunks:number}>;
}

export interface SourceHealthRow {             // replaces the Mark VIII shape
  source_id: string; display_name: string; platform: string; kind: string; enabled: boolean;
  in_main_digest: boolean; folders: {id:string; name:string}[];
  stored_posts: number; backlog_posts: number|null;
  tier: CadenceTier; mean_gap_hours: number|null; interval_hours: number;
  interval_basis: 'override'|'tier'|'probation'|'backlog_guard'|'profile_floor';
  override_hours: number|null;
  next_due_at: string|null; would_fetch_now: boolean; decision: DecisionKind;
  last_attempt_at: string|null; last_success_at: string|null;
  last_outcome: OutcomeStatus|null; last_fetched_posts: number|null;
  last_error: string|null; last_error_at: string|null;
  consecutive_failures: number; next_retry_at: string|null; dormant: boolean;
}
export interface SourcesHealthResponse {
  success: true; generated_at: string; rows: SourceHealthRow[];
  summary: {due_now: number; deferred: number; backoff: number; unavailable: number; errors: number};
}

export interface FeedItem {
  id: string; title: string; excerpt: string; url: string;   // title already falls back to the excerpt
  source_id: string; source_display_name: string; platform: string;
  sort_at: string; published_at: string|null; read_at: string|null; starred_at: string|null;
  reading_minutes: number|null; duration_seconds: number|null;
  media_thumb: string|null;
}
export interface FeedPage { success: true; items: FeedItem[]; next_cursor: string|null; }
export interface FeedGroup {
  source_id: string; source_display_name: string; platform: string;
  newest_sort_at: string; count: number; items: FeedItem[];   // items <= 3
}
export interface FeedGroupsPage { success: true; groups: FeedGroup[]; next_cursor: string|null; }
export interface MarkReadResult { success: true; updated: number; ids: string[]; }
export interface UnreadCounts { total: number; by_source: Record<string,number>; by_folder: Record<string,number>; }
export interface JobAccepted { success: true; job_id: string; job_type: string; status: 'running'; }
```

**Live data in the reader.** The global `QueryClient` uses defaults (`App.tsx:8`), so `useInfiniteQuery` would refetch every loaded page on window focus and after each ingestion, and new posts would land on top and shift the j/k index and the scroll position mid-read. Rules:
- `['feed', …]` uses `staleTime: Infinity` and `refetchOnWindowFocus: false`.
- After an ingestion run, only `['unread-counts']` is invalidated. When the count for the current scope grows, the toolbar shows a "N new posts, show" pill; clicking it resets the feed query and scrolls to the top.
- Selection is held by post id, not by index, so appending or prepending pages never moves it.

### F.4 Source health API (backend)
`GET /api/sources/health` → `SourcesHealthResponse`.
- Built by `OperationsService.get_source_health()`, rewritten on top of `FetchStateRepository.load_schedule_view()`, `KindRegistry.resolve`, `availability_from_env()`, and, for every row, `cadence_stats(source, state_row)` followed by `decide_fetch(..., force=False)`.
- `operations/overview.source_health` becomes `summary` plus the 8 worst rows, built by the same function.

`PUT /api/sources/{id}/cadence {override_hours: number|null}` → `{success, row: SourceHealthRow}`.
- Validation: `null`, or a value in [1, 2160].
- It writes `sources.fetch_interval_hours_override`.

### F.5 Keyboard map (one table, shown by `?`)
| Key | Feed | Post page |
|---|---|---|
| j / k | next / previous item, scrolls it into view; at the end it loads more | next / previous post in the feed context |
| o / Enter | open the selected post (marks it read) | — |
| u / Esc | — | back to the feed, restoring scroll and selection |
| m | toggle read | toggle read |
| s | toggle star | toggle star |
| Shift+A | mark all read up to the selected item (confirm) | — |
| f | fetch the current scope (source or track; on "all" this runs a non-forced cycle) | fetch this post's source |
| ? | shortcut help | shortcut help |

`/` (search) is not bound in Mark IX: search is deferred (§F.2).

Shortcuts are ignored while focus is in an `input`, `textarea`, `select` or `[contenteditable]`, and while any modifier other than Shift is held. Single-character shortcuts can be switched off (WCAG 2.1.4): `ShortcutHelp` has a "Keyboard shortcuts on/off" toggle, persisted in localStorage by `useShortcutPreference`. When off, only `?` stays bound.

### F.6 Accessibility and state rules (acceptance for every new component)
- A feed item is an `<article>` with exactly one primary link (the title). The secondary actions are sibling `<button>`s with `aria-label`s. There are no nested interactive elements.
- Selection uses a roving `tabIndex`: the selected `<article>` has `tabIndex=0` (all others `-1`), receives `.focus()` when j/k moves, carries `aria-current="true"`, and shows a visible focus ring. Moving DOM focus is what makes screen readers announce it.
- Results of read, star, mark-through and undo are announced in one `aria-live="polite"` region owned by `ReaderPage`.
- Touch: row star/read buttons have a 44×44px minimum hit area. Below `md`, `ReaderNavRail` is a drawer opened from a `FeedToolbar` button. The reader must be usable at 375px width (no horizontal scroll, no overlapping fixed elements).
- Thumbnails sit in a fixed aspect-ratio box (`aspect-video`, fixed width) with `loading="lazy"` and `decoding="async"`, so there is no layout shift.
- Every data fetch renders exactly one of the following:
  - `LoadingState`, a skeleton with `aria-busy`
  - `EmptyState`, with copy and a primary action ("Fetch this track", "Show all", "Add a source")
  - `ErrorState`, showing `ApiError.message` and a Retry button
- Async job outcomes are shown as a sonner toast, plus a link to the job.
- Colours use tokens only (`bg-[var(--background-primary)]` or the shadcn HSL classes). New components use no `slate-*`/`gray-*` utilities.
- Dates are shown with local-date helpers. `toISOString().split('T')[0]` is not allowed in new code.

---

### F.7 Design language (product-owner directive, 2026-10-09)

Every frontend slice (F1 where it sets tokens, F3, F2, and the final polish pass) is built against three project skills in `.claude/skills/`. Load them with the Skill tool before writing UI code: `apple-design`, `emil-design-eng`, `break-ui`. The concrete rules for INSIGHT:

- **Motion budget by frequency.** j/k, keyboard navigation, mark-read and list hovers get **no animation**; they happen hundreds of times a day. Toasts, sheets, popovers and the shortcut-help dialog get short, interruptible transitions: under 300ms, strong ease-out `cubic-bezier(0.23, 1, 0.32, 1)`, `transform`/`opacity` only, never `transition: all`, never `scale(0)`. Popovers scale from their trigger; modals stay centered. Use springs (critically damped by default) only for anything draggable.
- **Response.** Every pressable control gives instant `:active` feedback (`scale(0.97)`, 100–160ms). Optimistic UI for mark-read/unread with rollback on error. No artificial delays on the input path. Hover effects only under `@media (hover: hover) and (pointer: fine)`.
- **Materials and hierarchy.** Sticky reader toolbar and nav rail use a translucent material (`backdrop-filter` blur + semi-transparent bg) with content scrolling under it, and a scroll-edge fade instead of a hard 1px divider. Never stack translucent on translucent.
- **Reading typography.** System font stack with optical sizing. Body measure 60–75ch, line-height ~1.5–1.6. Headings use tighter leading and negative tracking (≈ −0.02em at display sizes). `tabular-nums` for counts, timestamps and health-table numbers. Spacing in rem so 200% zoom and a raised root font size don't break layout.
- **Accessibility signals.** Honour `prefers-reduced-motion` (cross-fades instead of slides), `prefers-reduced-transparency` (solid surfaces, no blur) and `prefers-contrast: more`. Dark mode must hold.
- **Feedback kinds.** Status (run in progress), completion (run report), warning (backoff, kind unavailable), error. Each has one consistent component from F1's `components/states/*`.
- **Worst-case data is an acceptance gate.** Every new list or row component (FeedItem, FeedGroup, SourceHealthTable row, RunReportSummary) ships with a worst-case fixture from `.claude/skills/break-ui/CATALOG.md`: long and missing titles, unbreakable URLs, non-Latin, RTL and emoji text, 0/1/12,847 counts, null dates, future dates, sources in backoff, kind unavailable. Fixtures live next to the component's tests, and a dev-only `?data=worst|empty|one|huge` switch is exposed on the reader and health-table routes. Long text: titles wrap (clamped at 2–3 lines in lists), URLs and handles middle-truncate with a `title` attribute, and numbers and dates are never truncated. Use `Intl.PluralRules` and `Intl.NumberFormat`.

## 3. Seams and adapters (real vs test)

| Seam (interface) | Real adapter | Test adapter |
|---|---|---|
| `IngestionRunner` ports: `SourceCatalog` | `DbSourceCatalog` (single SQL) | `InMemorySourceCatalog(list[Source])` |
| `FetchStateStore` | `DbFetchStateStore` → `FetchStateRepository` | `InMemoryFetchStateStore` (dict; records calls) |
| `PostSaver` | `DbPostSaver` → `PostsRepository.save_batch` | `InMemoryPostSaver` (url-dedupe; configurable failing urls) |
| `Enricher` processors | `EntityMemoryService.process_posts`, `EventMemoryService.process_posts` | `RecordingProcessor(fail_on_chunk=…)` |
| `InspectionRefresher` | `DbInspectionRefresher` (`ingestion/inspection.py`: due rule + `kind.inspect` under `gates.slot` + `ArchiveMetadataWriter`) | `RecordingInspectionRefresher` |
| `RunLock` | `PgAdvisoryRunLock` (dedicated connection, `pg_try_advisory_lock`) | `FakeRunLock(held: bool)` |
| `ProgressSink` | `JobProgressSink(operations_service, job_id)` → `append_job_event` | `NULL_PROGRESS`, `RecordingProgressSink` |
| `availability` | `availability_from_env` (reads `INSIGHT_YTDLP_ENABLED`; B8 adds `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` and the session file) | `lambda: Availability(ytdlp_enabled=False, telegram_credentials=False)` |
| Telegram client (B8) | `TelethonClientFactory` (`kinds/telegram_session.py`; the only module that imports telethon, lazily, and translates its errors) | `FakeTelegramClient` (scripted `is_user_authorized`, entities, message pages, `TelegramFloodWait`/`TelegramChannelError` raises; records connect/disconnect/calls) |
| Telegram session lock (B8) | `PgAdvisorySessionLock('insight.telegram_session')` | `FakeRunLock(held: bool)` (same shape as the run lock) |
| `rand` (backoff jitter) | `random.random` | `lambda: 1.0` |
| `Clock` | `lambda: datetime.now(UTC)` | `FixedClock(t)` |
| `KindRegistry` / `SourceKind` | real kinds (§D.2) | `FakeKind(name, profile, behaviour)` returning posts, raising, `KindUnavailable`, or sleeping |
| `KindHttp` | httpx/requests implementation moved from `SourceFetchService`; `sleep = asyncio.sleep` | `FakeHttp({url: text \| exception}, sleep=RecordingSleeper())`, used by the kind parsing tests |
| `FetchGates` | real (`asyncio`) | real with 0 delays (as today), or `SpyFetchGates` (a subclass recording `slot` calls) |
| `PostsRepository.save_batch` | real DB | real DB (scratch sources); fault injection by subclassing `PostsRepository.upsert_post` |
| `FetchStateRepository` | real DB | real DB (rollback pattern; `refresh_cadence` in a rolled-back transaction) |
| `ReaderRepository` | real DB | real DB (rollback pattern) |
| HTTP routes | `main.py` + `InsightApiBridge` | FakeBridge, with the route coroutine called directly (existing pattern) and a real `BackgroundTasks()` passed in |
| Scheduler | `run_scheduler.main` loop | `tick(...)` called with fake `ingest`, `daily_work` and `ops` arguments |
| Frontend `api` | `ApiService` via `ApiProvider` (`src/services/ApiContext.tsx`) | pure `lib/*` functions with hand-made objects (node --test); components with vitest + jsdom + Testing Library inside `<ApiProvider value={fakeApi}>` |

---

## 4. API changes (old → new) and `api.ts` impact

| Old | New | `api.ts` |
|---|---|---|
| `POST /api/ingest-posts` | **removed** | delete `ingestPosts` |
| `POST /api/safe-ingest-posts` (sync) | `POST /api/ingestion/run {force?: boolean}` → 202 `JobAccepted`; job payload `RunReport` | `runIngestionCycle({force}) : Promise<RunReport>` (tracked; uses `pollJob`); delete `safeIngestPosts` |
| `POST /api/sources/{id}/fetch-now {limit, asyncMode}` → `LiveFetchResponse` | same URL, body `{limit?}` → 202; payload `RunReport` (selector source, force) | `fetchSourceNow(id, {limit}) : Promise<RunReport>`; delete `LiveFetchResponse` |
| `POST /api/folders/{id}/ingest {limit, delaySeconds, asyncMode}` (no client) | same URL, body `{limit?}` → 202; payload `RunReport`. `delaySeconds` is removed (the profiles own politeness) | new `fetchFolderNow(id) : Promise<RunReport>` |
| `GET /api/operations/overview` `source_health: SourceHealthRow[]` (old shape) | `source_health: {summary, rows (worst 8)}` using the new `SourceHealthRow` | update `OperationsOverview` type and `lib/operationsOverview.ts` |
| — | `GET /api/sources/health` → `SourcesHealthResponse` | `getSourcesHealth()` |
| — | `PUT /api/sources/{id}/cadence {override_hours}` | `setCadenceOverride(id, hours\|null)` |
| `GET /api/operations/scheduler` → config | config plus `ingest_tick_minutes` and `state {last_tick_at, next_tick_at, last_daily_work_at, next_daily_work_at}` | extend `SchedulerConfig`; `IngestionControl` countdown reads `state.next_tick_at` |
| `PUT /api/operations/scheduler` | accepts `ingest_tick_minutes` (≥ 15) | — |
| — | `GET /api/feed?scope=all\|folder:<id>\|source:<id>&filter=all\|unread\|starred&view=stream\|by_source&cursor=&limit=30&days=` → `FeedPage` (stream) or `FeedGroupsPage` (by_source) | `getFeed(params)`, `getFeedGroups(params)` |
| — | `GET /api/feed/unread-counts` → `UnreadCounts` | `getUnreadCounts()` |
| — | `PUT /api/posts/item/{id}/read {read: boolean}` | `setPostRead(id, read)` |
| `POST /api/posts/item/{id}/favorite` | unchanged URL; also writes `starred_at` | unchanged |
| — | `POST /api/feed/mark-read {scope, through_cursor, newest_cursor}` → `MarkReadResult {success, updated, ids}` (bounded by the unread window, §F.2) | `markReadThrough(scope, through, newest)`; undo = `setPostsRead(ids, false)` |
| — | `PUT /api/feed/read {ids: string[], read: boolean}` → `{success, updated}` (batch, used by undo) | `setPostsRead(ids, read)` |
| `GET /api/posts/item/{id}/reader-state` | unchanged shape; also includes `read_at` | add `read_at` to `ReaderState` |
| `POST /api/archive/{id}/run` | unchanged; 409 when the kind is unavailable | handle the 409 message |
| `GET /api/archive/catalog` | entries add `backlog_posts: number\|null`, `remaining_posts`, `estimated_seconds`, `kind` | extend `ArchiveCatalogEntry` |

**Error contract for new endpoints:**
- Non-2xx with `{"detail": "<human message>"}`.
- `makeRequest` throws `ApiError`. New methods do **not** wrap the error in `{success:false}`: react-query and the error components handle it.
- Old methods keep their wrapping, which avoids churning about 100 methods.

---

## 5. Test plan per module (pre-agreed TDD seams)

Conventions:
- **Backend:** stdlib `unittest`; `IsolatedAsyncioTestCase` for async code; hand-written fakes (no `unittest.mock` unless patching an env-read constant). DB tests use either the **rollback pattern** (`test_repo_posts_upsert.py`) or, when a commit is needed, the **scratch-source pattern**:
  - sources with `https://test.invalid/mark-ix/<uuid4>` handles, created with `enabled=false` and `in_main_digest=false` (a tick or the feed must never pick them up, even by accident), unless the test is about those flags
  - a `tearDown` that deletes them (posts and fetch state cascade), and a `setUp` that also deletes any leftovers matching `https://test.invalid/mark-ix/%`
  - **every committing test class** is decorated with `@requires_test_db`, a helper in `tests/_db.py` that is `skipUnless` the DSN's database name ends in `_test`. `run-tests.sh` defaults to the live `insight` DB (`run-tests.sh:33`), so without `TEST_DATABASE_URL` these classes are skipped, never run against live data. Rollback-pattern tests may run on either database, but must scope every assertion to their own scratch rows (never count all posts).
- **Frontend:** pure logic is tested in `src/lib/*.test.ts` with `node --test`. Component behaviour is tested in `src/**/*.test.tsx` with vitest + jsdom.

### 5.1 Fetch schedule — `tests/test_fetch_schedule.py` (pure, no DB)
Everything goes through `decide_fetch`, `fetch_interval`, `tier_for` and `backoff_delay`, using a `stats()` builder and `FixedClock` times.

`decide_fetch` cases:
- New source (no success, 0 posts) → `FETCH_NEW_SOURCE`.
- Unknown tier, success 23h ago → `SKIP_NOT_DUE`; success 24h ago → `FETCH_DUE` (probation 24h).
- Fast source (gap 2h) → interval 24h (floor).
- Medium (gap 3d) → 36h.
- Slow (gap 60d) → 21d (ceiling).
- Backlog guard: gap 30m, max_posts 20 → 10h with basis `backlog_guard`. Also with a YouTube profile: gap 2h, max 15 → 30h, which beats the 168h floor.
- Override 6h beats tier, guard and floor.
- YouTube profile with gap 3d → 168h (`profile_floor`).
- Error state: `next_retry_at` in the future → `SKIP_BACKOFF`; in the past → `FETCH_RETRY`, even when the tier interval has not elapsed.
- `force=True` with active backoff → `FETCH_FORCED`.
- `ignore_backoff=True` with active backoff and success 2h ago (24h interval) → `SKIP_NOT_DUE`; with success 25h ago → `FETCH_DUE`. It skips rule 3 only.
- `cadence_stats(source, None)` (no state row) gives `consecutive_failures=0`, `last_success_at=None`; with a state row, every field is copied from the row and the cadence columns.
- `force=True` with yt-dlp off → `SKIP_UNAVAILABLE`. Regression for the bypass bug.
- yt-dlp off, not forced → `SKIP_UNAVAILABLE`, *not* `SKIP_BACKOFF`. Regression for the 🚫 miscount.
- An RSS-platform source whose kind is `youtube_channel` gets the yt-dlp rules.
- Post limit: YouTube `max_posts=5` → 15; requested limit 3 with the YouTube profile → 15; RSS requested 50 → 50.
- `next_due_at` equals `last_success_at + interval` in every SKIP_NOT_DUE case.

Other functions:
- `tier_for` boundaries: 11h59m → fast, 12h → medium, 7d → medium, 7d+1s → slow, sample 2 → unknown.
- `backoff_delay` with `rand=lambda: 0.0` and `rand=lambda: 1.0`:
  - n=1 → [51m, 60m]
  - n=5 → 16h band
  - n=6 → 24h band
  - n=10 → 7d band (dormant)
  - n=0 → 0

### 5.2 Fetch state repo — `tests/test_repo_fetch_state.py` (DB, rollback pattern)
- `record_outcome`:
  - error → error → the counter is 2 and `last_error` is set
  - then empty → the counter resets, `last_success_at` is set, `next_retry_at` is NULL
  - `unavailable` leaves the counter alone
- `load` returns rows for the requested ids only.
- `refresh_cadence`: the scratch source has posts with published dates spaced 6h apart (25 posts) → `mean_gap ≈ 6h` from the latest 20, tier `fast`. A source with 2 posts → `unknown`.
- SQL tier vs `tier_for` parity, over boundary fixtures.
- `load_schedule_view` includes the override and the cadence columns.
- `record_outcomes` writes several rows in one call; with `backoff=lambda n: timedelta(hours=n)`, two errors give `next_retry_at = now + 2h`.
- Migration check: after `migrate`, the `source_fetch_state` and `sources.cadence_tier` columns exist (`information_schema` query). This goes in `test_migrate_runner.py` as a new test method.
- `test_0019_backfill` (in `test_migrate_runner.py`, `@requires_test_db`, rolled back): create scratch sources with `settings.ops` / `settings.ingest_backoff` covering a healthy row, an `empty` last status (expect `last_success_at = last_checked_at`), a `running` status (expect `last_outcome IS NULL`), a `"not-a-date"` `next_retry_at` and a `"x"` failure count (expect NULL / 0, no exception). Delete their `source_fetch_state` rows, execute the 0019 SQL file, assert the fields and that `ops`/`ingest_backoff` are gone from settings, then execute it a second time and assert nothing changed (idempotence).
- `test_migration_lock_is_taken`: `acquire_migration_lock` issues `pg_advisory_xact_lock` (a second connection's `pg_try_advisory_xact_lock(hashtext('insight.migrate'))` returns false while the first transaction is open).

### 5.3 Save batch — `tests/test_repo_posts_save_batch.py` (DB, scratch-source pattern, commits)
- 45 new drafts with `commit_every=20` → `inserted=45`, all ids present. A fresh connection sees all 45 rows (proves the commits).
- Re-saving the same 45 → `updated=45`, `inserted=0`.
- Per-post isolation: a `PostsRepository` subclass whose `upsert_post` raises `ValueError` for url #7 → `failed=1` with stage `upsert`, and the other 44 are saved.
- Poisoned transaction: the subclass executes `SELECT 1/0` *outside* a savepoint for url #25, so the transaction is aborted. The drafts committed in the first batch (1–20) survive. Drafts 21–24 are reported `discarded`. Drafts 26–45 are saved after the rollback. Counts add up: `inserted + failed == 45`.
- The external-id collision path through `save_batch` returns `updated` and leaves no `UniqueViolation` (smoke test reusing the existing fixtures).
- `by_source` splits correctly across 2 sources.

`test_repo_posts_upsert.py` is unchanged and must still pass.

### 5.4 Enricher — inside `tests/test_ingestion_runner.py`, class `EnricherTests`
- Chunking: 250 ids with chunk size 100 → 3 calls.
- A failing chunk is counted and does not stop the run.
- An empty input makes no calls.

### 5.5 Kinds — `tests/test_source_kinds.py` (no network; `FakeHttp`)
- Registry resolution table (platform, url) → kind name, covering all 12 kinds and the fallback. Rows with `platform='telegram'` and a bare handle are **excluded** from the parity check against Mark VIII `classify_source`; the table instead has an explicit row `('telegram', 'ai_newz') → telegram_mtproto`, labelled "intentional divergence: Mark VIII returned generic_rss". Every other row is identical to the Mark VIII results (written first against the current `classify_source`). The existing classify tests in `test_source_fetch_service.py` are moved here and pointed at `KindRegistry.resolve`.
- The cache resolves each (platform, url) pair only once (a counting `matches`).
- `generic_rss.fetch_latest` parses a fixture feed (moved parse tests).
- `reddit_subreddit.fetch_latest` requests `/r/x/new/.rss` and does not request `.json`.
- `telegram_rss.fetch_latest(limit=20)` with page size 20 fetches 1 page. With limit 45 it fetches 3 pages and sleeps `page_delay_s` between them (recording sleeper injected via `KindHttp(sleep=...)`).
- `profile.rate_limit({"page_delay_seconds": 9})` overrides the page delay and keeps the profile's batch values; `archive_pages(..., rate)` sleeps the overridden delay; `estimate_seconds(pages, rate)` uses it.
- `youtube_channel` has `blocking_io=True` and `requires == "ytdlp"`.
- `archive_pages` for single-shot kinds yields exactly one page with `checkpoint=None`.
- `telegram_mtproto` has `requires == "telegram_creds"`; with `Availability(telegram_credentials=False)` `decide_fetch` gives `SKIP_UNAVAILABLE` even with `force=True`; and Telethon is not imported (checked with `"telethon" not in sys.modules` after resolve + profile access). The B8 behaviour tests live in `tests/test_telegram_kind.py` (§B8).
- Site adapters satisfy `SourceKind` directly (`isinstance` against a `runtime_checkable` protocol). A site adapter's `archive_pages` yields one `ArchivePage` per page that the old `page_callback` received, with the same checkpoints. The existing `test_source_adapters.py` keeps passing after the adapters move to `KindHttp` + `kinds/parsing.py`.
- `PolitenessProfile.estimate_seconds` matches the old `_estimate_seconds` values for telegram, nitter and site kinds, using fixtures copied from the current outputs.

### 5.6 Gates — `tests/test_fetch_gates.py`
These tests are moved from `test_safe_ingest.py`: HostLimiter, StartSpacer, interleave and host overrides. New tests:
- `slot(ytdlp_profile)` holds the yt-dlp semaphore: a third concurrent entry waits while two are held.
- `slot(host_lock_profile, "a")` serialises the same host but not different hosts.
- Host floors are keyed by host, not kind: a `generic_rss` source on `https://www.reddit.com/r/x/.rss` and a `reddit_subreddit` source `r/x` (host key `platform:reddit`) both get the 8s floor; a telegram RSS host gets 5s; an unlisted host gets 0 (floors measured with a fake monotonic clock).

### 5.7 Ingestion runner — `tests/test_ingestion_runner.py` (all fakes, `IsolatedAsyncioTestCase`)
All of these go through `await IngestionRunner(...).run(FetchRequest, progress=RecordingProgressSink())`. The runner is assembled with the §A.1 keyword constructor from `InMemorySourceCatalog`, `InMemoryFetchStateStore`, `InMemoryPostSaver`, an `Enricher` over `RecordingProcessor`s, `RecordingInspectionRefresher`, a `KindRegistry` of `FakeKind`s, real `FetchGates(…0 delays)` (or `SpyFetchGates`), `FakeRunLock(held=False)`, a fixed `availability` lambda, `FixedClock` and `rand=lambda: 1.0`.
- Selector `all` excludes disabled sources. Selector `source` includes a disabled source.
- Scheduled run: due sources are fetched and not-due ones skipped. `report.decisions` counts per kind, and the store records the decisions.
- yt-dlp off: YouTube fake kind is never called; `decisions["skip_unavailable"]==n`, `decisions.get("skip_backoff",0)==0`.
- Folder selector + force + yt-dlp off: YouTube is still skipped. Regression for the P5 bypass.
- A kind raising → outcome error. The in-memory store's row has `consecutive_failures == 1` and `next_retry_at == now + backoff_delay(1, rand=lambda: 1.0)` (deterministic). The other sources are unaffected, `status == "partial"`.
- A kind returning 0 posts → outcome `EMPTY` and `last_success_at` advances. Next run with the clock +2h → `SKIP_NOT_DUE`. Regression for staleness.
- `KindUnavailable` raised by a kind's `fetch_latest` → that source's outcome is `UNAVAILABLE` and no backoff is written.
- Saver failing some urls → `posts_failed`, `post_failures` ≤ 20, and the source's fetch outcome is still healthy.
- Enrichment receives exactly `inserted_ids` (not updated ids).
- `inspections.refresh` is called exactly for sources with ≥ 1 fetched post, with the resolved kind and the fetched count. A separate `DbInspectionRefresherTests` class (fake kind, fake writer, `SpyFetchGates`, fixed clock) checks the due rule (inspected 2h ago → skipped; never inspected → inspected) and that `kind.inspect` runs inside `gates.slot`.
- Progress: the recording sink receives the phases `decided`, `fetched`, `saved`, `enriched`, `inspected` in order.
- Run lock: `FakeRunLock(held=True)` → `status == "skipped_busy"` and no kind is called. A folder selector does not touch the lock.
- Nothing due → `status == "nothing_due"`, and the saver is not called.
- `to_payload()`: every list is ≤ 20, the payload is JSON-serialisable, and `OperationsService._compact_payload(payload) == payload`.
- `summary_line()` format is pinned: a report with 12 due, 63 not due, 1 failed and 48 inserted renders exactly `"12 due, 63 deferred, 1 failed; 48 new posts"` (the B4 "N due, M deferred" acceptance check is this test, not a log read).

### 5.8 Routes and scheduler — `tests/test_ingestion_routes.py`, `tests/test_run_scheduler.py`
- Routes, using the FakeBridge pattern, each called with a real `tasks = BackgroundTasks()`:
  - `POST /api/ingestion/run {force:true}` starts an `ingestion_run` job with `{selector:{kind:"all"}, force:true}`; the returned `JSONResponse` has `status_code == 202`; `len(tasks.tasks) == 1`; and the fake bridge's `run_ingestion` has **not** been awaited when the route returns (it runs only when the test awaits the task).
  - `fetch-now` uses a source selector with force.
  - folder ingest uses a folder selector with force.
  - When job start fails → `status_code == 503` and `len(tasks.tasks) == 0`.
  - `/api/ingest-posts` and `/api/safe-ingest-posts` no longer exist (`not hasattr(main, "ingest_posts")`, and the route path is not in `[r.path for r in main.app.routes]`).
- Scheduler, calling `tick(now, state, config, ingest=fake_ingest, daily_work=fake_daily, ops=FakeOps())` directly (no module patching):
  - a tick runs ingestion every time
  - daily work runs only when `interval_hours` has elapsed since `state.last_daily_work_at`
  - first tick with no `last_daily_work_at`: seeded from `ops`' latest successful `scheduler_cycle` finish time (so no daily work if it was 2h ago); runs daily work only when there is no such job
  - an exception in ingestion still finishes the job as failed (E5)
  - the returned state has `next_tick_at = now + ingest_tick_minutes`, and `ops` received it

### 5.9 Source health API — `tests/test_source_health.py`
- `OperationsService.get_source_health` with a fake schedule view + `FakeKind` registry + `FixedClock`:
  - the row fields are computed by `decide_fetch`
  - the summary counts are correct
  - sorting puts errors first, then backoff, unavailable, due and deferred
- Route `PUT /api/sources/{id}/cadence` validates the range (0 → 400, 3000 → 400, null → OK).

### 5.10 Reader — `tests/test_repo_reader.py` (DB, rollback) + `tests/test_post_detail_reader.py` (DB, `@requires_test_db`, commits) + `tests/test_feed_routes.py` (FakeBridge)
Every rollback-pattern query is scoped to the test's own scratch rows so live posts cannot leak into counts:
- Feed keyset pagination over 70 scratch posts with `FeedScope("source", scratch_id)` and limit 30 → 30/30/10 items, no duplicates, strictly descending.
- Ties on `sort_at` are broken by id, with no item skipped across a page boundary.
- `scope=folder` (a scratch folder) returns only member sources. `scope=all` with a scratch `in_main_digest=false` source: none of its post ids appear in the first page (asserted on ids, not counts).
- `filter=unread` hides read posts. `filter=starred` shows starred ones (source scope).
- `mark_read_through(through=item 10, newest=item 1)` in source scope marks items 1–10 only and returns their ids. A scratch post newer than `newest` stays unread. A scratch post older than the unread window is not marked, so the rowcount is bounded by the window.
- `feed_by_source`: two scratch sources (one with 40 posts, one with 2) → two groups, each with ≤ 3 items and the right `count`, ordered by newest post.
- Item shape: an empty-title post gets the excerpt-prefix title; a YouTube post with `metadata.duration_seconds` returns it.
- `set_starred` toggles.
- `unread_counts`: assert `by_source[scratch_id]` only; a post older than 30 days is not counted.
- `FeedCursor.encode/decode` round-trip. A malformed cursor → 400 at the route.
- `test_post_detail_reader.py`: `record_post_open` → `explainability_service.record_post_interaction` opens and commits its own connection (`explainability_service.py:71-74`), so it cannot see an uncommitted post. This test uses the scratch-source pattern: commit a scratch post, open it twice, assert `read_at` is set once and unchanged by the second open.

### 5.11 Frontend
- **`node --test`** (pure, the existing runner):
  - `apiError`: message stripping, status mapping
  - `jobPolling`:
    - 2 transient errors then success → resolves
    - 3 consecutive → rejects
    - abort → rejects with `AbortError`
    - timeout
  - `runReport`: headline for success / partial / nothing_due / skipped_busy; the decision labels cover every `DecisionKind`
  - `sourceSchedule`:
    - `formatDue` (overdue, in 3h, in 5d)
    - backoff label with dormant
    - tier label
    - sort order matching the backend
  - `feedNavigation` reducer:
    - j at the last item emits `loadMore`
    - k at 0 stays at 0
    - m/s produce mutation intents
    - selection is held by post id: it survives a page append *and* a page prepend (new posts on top) without moving to another item
  - `feedContext`: `?ctx=` encode/decode round-trip; prev/next at the boundaries; at the last loaded id it returns a "load next page with cursor X" intent; a missing or malformed `ctx` gives "no context" (j/k disabled)
  - `dates`: `localDateISO` near midnight in a non-UTC offset (inject `Date` and the offset)
- Frontend tests run **on the host only**, with Node ≥ 22.18 (unflagged TypeScript type stripping for `node --test src/lib/*.test.ts`). `package.json` declares `"engines": {"node": ">=22.18"}`. The Docker image only builds; it does not run tests.
- **vitest + jsdom + @testing-library/react** (added in F1); components get a fake API through `<ApiProvider value={fakeApi}>`:
  - `FeedList.test.tsx`:
    - renders `article`s with one link each
    - j/k moves `aria-current`, the roving `tabIndex`, and `document.activeElement` to the selected `<article>`
    - `o` calls navigate with `?ctx=`
    - `m` calls `setPostRead` optimistically, rolls back on error, and announces the result in the `aria-live` region
    - with shortcuts switched off, `j` does nothing and `?` still opens help
    - an item with no title renders the excerpt-prefix title; thumbnails have `loading="lazy"`
    - the empty state shows the action
  - `ReaderPage.test.tsx`: after a fake ingestion raises the unread count, the "N new posts" pill appears and the loaded list is unchanged until it is clicked; the mark-through toast's Undo calls `setPostsRead(ids, false)`
  - `SourceHealthTable.test.tsx`:
    - renders a backoff row with "retry in 3h"
    - the Fetch now button calls `fetchSourceNow`
    - the override editor validates
  - `RunReportSummary.test.tsx`: renders counts and failures; the raw JSON sits behind a disclosure
  - `RunCycleButton.test.tsx`: force needs a confirmation

---

## 6. Implementation slices

Rules:
- **Backend slices B1→B7, then B8, are strictly sequential.** Each one leaves the suite green and the app deployable.
- **Migrations:** 0019 belongs to B1, 0020 and 0021 to B7.
- **Frontend slices** list their backend dependency.
- **"Parallel-safe with"** means the two slices touch disjoint files.

**Test commands** (from the repo root `/home/normie/Documents/Projects/I.N.S.I.G.H.T.`):
- **One-time setup (required):** `docker exec insight-db createdb -U insight insight_test`. Committing test classes are skipped unless the DSN's database ends in `_test` (§5 conventions).
- **Migrations before tests.** B1 adds `MIGRATE=1` to `run-tests.sh`: when set, it runs `python -m insight_core.db.migrate` with `DATABASE_URL=$DB_URL` in the same image before the test command. A slice that adds a migration (B1: 0019, B7: 0020) runs its tests with `MIGRATE=1`, so the tests never run against an unmigrated schema. (Migrating the live `insight` DB this way is what the container start does anyway; take the §7 `pg_dump` backup first.)
- `T=postgresql://insight:insight@postgres:5432/insight_test` below.
- one backend module: `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.<module>`
  - Add `SKIP_BUILD=1` only when re-running without code changes.
- full backend suite: `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`
- verbose backend suite: `TEST_DATABASE_URL=$T ./run-tests.sh discover -v -s insight_core/tests -p 'test_*.py'`
- frontend (host, Node ≥ 22.18): `cd frontend && node --test src/lib/*.test.ts`. After F1: `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`.

---

### B1. Fetch schedule: pure decision, fetch state table, cadence columns
**Goal:** one `decide_fetch`. Backoff and staleness move off JSONB and `posts.fetched_at`. The 🚫 miscount is fixed. The existing `safe_ingest_posts` keeps working, rewired to the new decision. Every ingest path (including the legacy `scripts/ingest.py`, deleted only in B4) keeps working after this slice.

**Files:**
- new: `backend/insight_core/ingestion/__init__.py` (empty surface for now), `ingestion/types.py` (`Trigger`, `OutcomeStatus`, `FetchOutcome`), `ingestion/schedule.py` (incl. `cadence_stats`, `availability_from_env`), `db/repo_fetch_state.py`, `db/migrations/0019_fetch_schedule.sql`, `tests/_db.py` (`requires_test_db`)
- edit: `db/migrate.py`: `acquire_migration_lock` → `pg_advisory_xact_lock(hashtext('insight.migrate'))`, called first in the transaction (§C.1)
- edit: `run-tests.sh`: `MIGRATE=1` runs the migrator against `$DB_URL` before the tests
- edit: `scripts/safe_ingest.py`
  - `should_fetch_source` becomes a ~15-line adapter: `cadence_stats(source, state_row)` from `FetchStateRepository.load` + source, then `decide_fetch(..., ignore_backoff=(trigger == "manual"))`; it returns `(decision.fetch, decision.detail)` and exposes `decision.kind`
  - the manual trigger keeps its Mark VIII semantics through `ignore_backoff=True` (skips backoff, still respects freshness). `force` arrives in B4
  - the backoff count uses `kind == SKIP_BACKOFF`
  - `_record_backoff` and both `record_source_status` calls (`:508`, `:553`) → `FetchStateRepository.record_outcome`
  - `FetchStateRepository.refresh_cadence()` is called once at the start of `safe_ingest_posts`, so new sources leave probation and gaps update through B1–B3 (B4 moves it to daily work)
  - its duplicate `get_source_post_stats` is deleted
  - interim profile: YouTube is decided by `classify_source(...) == "youtube_channel"`
- edit: `scripts/ingest.py`: its two `record_source_status` calls (`:110`, `:131`) → `FetchStateRepository.record_outcome`, so `/api/ingest-posts` keeps working until B4 deletes it
- edit: `services/operations_service.py`: `record_source_status` is deleted; `get_source_health` reads `source_fetch_state` (old row shape kept for now)
- edit: `db/repo_sources.py`: `merge_source_settings` reads through a dedicated `SELECT settings FROM sources WHERE id=%s FOR UPDATE` (E8); `get_source_by_id` is unchanged
- edit: `tests/test_safe_ingest.py`: the backoff-JSONB and `_FakeCursor` tests are deleted; `ShouldFetchSourceTests` and `YouTubeCadenceTests` (`:307`, `:360`) are rewritten against the adapter with a fake fetch-state repo rather than deleted; `FetchSourceNeverRaisesTests` stays
- edit: `tests/test_operations_service.py` fixtures

**Tests first:**
- `test_fetch_schedule.py` (§5.1)
- `test_repo_fetch_state.py` (§5.2)
- the migrate check, `test_0019_backfill` and `test_migration_lock_is_taken` in `test_migrate_runner.py`
- `test_source_settings.py`: a concurrent-merge test (`@requires_test_db`; two connections, the second blocks until the first commits — use `lock_timeout` to assert blocking)
- in `test_safe_ingest.py`:
  - `test_ytdlp_off_counts_unavailable_not_backoff`: `safe_ingest_posts` with `INSIGHT_YTDLP_ENABLED=0`, a YouTube source and a fake fetch-state repo → the 🚫 backoff counter is 0 and the source is reported unavailable
  - `test_manual_trigger_ignores_backoff_but_respects_freshness`: manual + active backoff + fresh success → skipped not-due; manual + active backoff + stale → fetched

**Acceptance:**
- the full backend suite is green (with `MIGRATE=1`)
- `SELECT count(*) FROM source_fetch_state` equals the number of sources after migrating
- no code path writes `settings.ops` or `settings.ingest_backoff` (`grep -rn "ingest_backoff\|\"ops\"" backend/insight_core --include=*.py` matches only migration-related comments and tests)
- `grep -rn "record_source_status" backend --include=*.py` returns nothing
- `test_ytdlp_off_counts_unavailable_not_backoff` passes

**Commands:**
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_fetch_schedule`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_repo_fetch_state`
- `SKIP_BUILD=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_migrate_runner`
- `SKIP_BUILD=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_safe_ingest`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

**As built (2026-10-09) — deviations from the text above, all keeping its intent:**
- **Created early:** `ingestion/kinds/base.py` holds only `PolitenessProfile` (fields as in §D.1, no `rate_limit`/`estimate_seconds` yet), because `decide_fetch` takes a profile; B3 adds the rest. `ingestion/ports.py` holds only `DbFetchStateStore` (one connection per call, clock + `backoff_delay` injected), which `safe_ingest.py`, `ingest.py` and the bridge share; B4 adds the protocols and other adapters. The interim profiles are `YTDLP_PROFILE` / `HOST_LOCK_PROFILE` in `safe_ingest.py`, picked by `interim_profile()` (`classify_source(...) == "youtube_channel"`).
- **Profile floor applies to probation too.** `fetch_interval` step 4 runs after step 2, so an `unknown` YouTube channel waits 168h, not 24h (yt-dlp is the expensive kind either way). The backlog guard needs a mean gap, so it never applies to probation.
- **`cadence_sample_size` counts distinct publication timestamps** in the 20-post window, not posts. On 2026-10-09, 4 live sources stamped whole batches with one time; their mean gap was 0, and the guard would have polled them hourly. With one distinct timestamp they stay `unknown` (24h probation). `tier_for` is unchanged; the SQL tier CASE is pinned to it by a parity test.
- **`refresh_cadence(..., source_ids=None)`** gained an optional scope so the rollback-pattern tests touch only their scratch rows.
- **The bridge also called `record_source_status`** (`fetch_source_now` and `run_archive`, via `_record_source_status_safe`); the spec listed only the ingest scripts. `fetch_source_now` now records a normal outcome (`_record_fetch_outcome_safe`). An archive run no longer writes fetch state at all: paging old posts must neither delay the next live fetch nor reset its backoff, and the archive keeps its own status in `settings.archive`.
- **A connector outage** (`_record_connector_outage`, telegram) is recorded as `unavailable`, which keeps the Mark VIII rule that a shared connector fault does not advance any source's backoff.
- **`safe_ingest_posts`** gained keyword seams (`sources_service`, `fetch_service`, `fetch_state`, `availability`, `clock`) for the decision-phase tests, records the decisions once per cycle, and its result adds `sources_unavailable_skipped` and `decisions` (`{kind: count}`). `should_fetch_source(source, state_row, trigger, *, profile, now, availability)` returns a `ShouldFetch` that unpacks as `(fetch, reason)` and exposes `.kind` / `.decision`.
- `SourcesRepository.get_sources_with_post_counts` also returns the four cadence columns `cadence_stats` reads. `OperationsService.get_source_health` reads fetch state through `_load_fetch_states` (a seam for its unit test). `SAFE_INGEST_SKIP_THRESHOLD_HOURS` is gone from `docker-compose.yml` and `.env.example`.

### B2. Save batch owns its transaction; enrichment as a follow-on step
**Files:**
- edit: `db/repo_posts.py`
  - add `PostDraft`, `PostSaveFailure`, `SaveBatchResult`, `save_batch`, and `_transaction_is_poisoned` (moved)
  - delete `upsert_posts_batch`
- new: `ingestion/enrichment.py`
- edit: `scripts/safe_ingest.py`: the save loop (:831–946) is replaced by `await asyncio.to_thread(DbPostSaver.save, drafts)` + `Enricher`
- edit: `services/source_fetch_service.py`: `_persist_posts` becomes a wrapper around `save_batch` + `Enricher`, kept until B4 for `ingest_source_now` and the archive pages, and run via `to_thread`
- edit: `scripts/ingest.py`: switched to `save_batch` too, so B2 leaves no unsafe path even though the file is deleted in B4
- edit: `tests/test_source_fetch_service.py`: `test_persist_posts_enriches_with_persisted_ids` is updated to the new seam

**Tests first:**
- `test_repo_posts_save_batch.py` (§5.3)
- `EnricherTests` (§5.4)

**Acceptance:**
- all three save paths call `save_batch`: `grep -n "upsert_post(" backend/insight_core --include=*.py -r` shows calls only inside `repo_posts.py`
- the suite is green
- an injected poison in a test drops exactly the uncommitted window

**Commands:**
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_repo_posts_save_batch`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_source_fetch_service`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

**As built (2026-10-09, landed after B3, immediately before B4). Deviations, all keeping the intent:**
- **`Enricher.run` takes the inserted posts, not bare ids.** The real processors (`EntityMemoryService.process_posts`, `EventMemoryService.process_posts`) read post bodies (title, content, url) to extract mentions and events, so ids alone would force a reload of every post. `SaveBatchResult` therefore also carries `inserted_posts` (`{**post, id, source_id}`, the inserted rows only, pruned with the ids when a poisoned window is discarded). Enrichment still runs on inserted posts only; the runner tests assert on their ids.
- **`commit_every`** defaults to `None`, meaning `INSIGHT_SAVE_COMMIT_BATCH` (fallback `SAFE_INGEST_SAVE_COMMIT_BATCH`, default 20). `INSIGHT_ENRICH_CHUNK_SIZE` (fallback `SAFE_INGEST_ENRICH_CHUNK_SIZE`, default 100) sets the enrichment chunk.
- `_persist_posts` was deleted rather than kept as a wrapper: the archive loop and `ingest_source_now` call `SourceFetchService._save_and_enrich` (`save_batch` in a thread, then `Enricher`). B4 deletes `ingest_source_now`, `scripts/ingest.py` and the safe_ingest body, so this keeps only the B4 end state. `test_persist_posts_enriches_with_persisted_ids` became the archive-loop assertion that each page's inserted posts (and only those) are enriched.

### B3. Source kinds, politeness profiles and FetchGates
**Files:**
- new: `ingestion/gates.py` (incl. `HOST_FLOORS`), `ingestion/http.py` (incl. `sleep`), `ingestion/archive_metadata.py`, `ingestion/kinds/{__init__,base,parsing,generic_rss,telegram_rss,nitter_rss,reddit,youtube,telegram_mtproto}.py`. In B3 `telegram_mtproto.py` carries only `matches`, `host_key` and the §D.2 profile (`requires="telegram_creds"`); its fetch/inspect/archive raise `KindUnavailable`, and they are never reached because `Availability.telegram_credentials` is False until B8 builds the real kind from `connectors/telegram_connector.py`
- edit: `adapters/base_adapter.py`: `BaseSourceAdapter` implements `SourceKind` directly (`fetch_latest`, `inspect`, `archive_pages(source, target, checkpoint, rate)`, `checkpoint_resumable`, `estimate_pages`, `profile`)
- edit: `adapters/*.py`: take `http: KindHttp` instead of `service`; helpers come from `kinds/parsing.py`; `archive_posts` with callbacks becomes the `archive_pages` generator (§D.2); `adapters/__init__.py` exposes `ADAPTER_CLASSES` only
- edit: `services/source_fetch_service.py`
  - `fetch_live_posts`, `inspect_source` and `classify_source` delegate to `KindRegistry`; the ladders are deleted
  - `archive_source` loops `kind.archive_pages`, passing `kind.profile.rate_limit(overrides)` from the `/plan` and `/run` request fields
  - `_record_archive_metadata_sync` and its helpers move to `ingestion/archive_metadata.py` (`ArchiveMetadataWriter.record(source_id, kind, data, mode)`); `record_live_fetch` delegates to it until B4 deletes it
  - the E1 `backlog_posts` fix
  - YouTube archive runs through `blocking_io`
- edit: `scripts/safe_ingest.py`
  - uses `FetchGates.shared().slot(kind.profile, kind.host_key(source))` for fetch *and* refresh (E3, E4)
  - the profile replaces `classify_source == "youtube_channel"`; `HOST_MIN_INTERVAL_OVERRIDES` is deleted in favour of `gates.HOST_FLOORS`
  - grouping by `profile.concurrency_pool` (`host-lock`, `ytdlp`)
- edit: `services/youtube_service.py`: the duplicate `page_delay 2` constant is removed (it reads the profile)
- move tests: the HostLimiter, spacer and interleave tests go from `test_safe_ingest.py` to `test_fetch_gates.py`; the classify, parse and rate-limit tests go from `test_source_fetch_service.py` to `test_source_kinds.py`
- edit: `test_source_adapters.py` (inject `FakeHttp`)

**Tests first:**
- `test_source_kinds.py` (§5.5): start with the resolution parity table (telegram bare handles excluded, plus the labelled divergence row), run against *current* `classify_source` outputs before moving the code
- an `ArchiveMetadataWriterTests` case: recording `mode="live"` with a fake kind uses `kind.estimate_pages` and `kind.checkpoint_resumable`
- a rate-override case: `plan_archive` with `pageDelaySeconds=9` persists `rate_limit.page_delay_seconds == 9` and a matching `estimated_seconds`
- `test_fetch_gates.py` (§5.6)
- `ArchiveBacklogEstimateTests.test_unknown_available_gives_none_backlog`

**Acceptance:**
- `grep -n "== \"telegram_rss\"\|== \"youtube_channel\"\|== \"nitter_rss\"\|== \"generic_rss\"" backend/insight_core/services/source_fetch_service.py backend/insight_core/scripts/safe_ingest.py` returns nothing
- `source_fetch_service.py` is under 800 lines; it reaches under 500 after B4
- importing `insight_core.ingestion.kinds` does not import telethon
- the suite is green

**Commands:**
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_source_kinds`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_fetch_gates`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_source_adapters`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_source_fetch_service`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

**As built (2026-10-09). Deviations from the text above, all keeping its intent:**
- **B2 had not landed** when B3 was built (no `save_batch`, no `Enricher`). The `archive_source` loop therefore saves each `ArchivePage` through the existing `_persist_posts`, now run in a thread, instead of `save_batch → enrich`. B2 swaps that call; nothing else in the loop changes.
- **safe_ingest drops its connector path** (`create_connector`, the sequential telegram group and `_record_connector_outage`). Every source now fetches through its kind. Bare telegram handles resolve to `telegram_mtproto`, are `skip_unavailable` until B8, and so never reach a fetch. A platform-telegram source with an RSS-bridge URL now goes through `telegram_rss` instead of the connector. `ingest_source_now` and `scripts/ingest.py` keep the connector until B4/B8; its import is now lazy.
- **`PolitenessProfile.rate_limit(*layers)`** takes the persisted rate limit and the request overrides as separate layers, applied in order. Batch keys are ignored for kinds with no batch cooldown, as Mark VIII did. `RateLimit.as_settings()` writes the Mark VIII `settings.archive.rate_limit` keys, and `RateLimit.delay_after(n)` is the one place where page-delay and batch-cooldown pacing is decided (used by the kinds and by `estimate_seconds`).
- **`ArchivePage.checkpoint=None` is used only by the single-shot kinds** (`generic_rss`, `youtube_channel`). Paged kinds yield a checkpoint for every page and finish when the generator is exhausted. For a single-shot page, `archive_source` builds a `{mode: <kind>, pages_fetched, collected_posts}` checkpoint so the archive history keeps one. Progress events are emitted per page by `archive_source`; the kinds no longer emit any.
- **`telegram_rss` keeps the source URL's query on every page URL** (`/rss/<chan>/<n>?limit=50`), for live and archive alike. That is how "honours `?limit=`" is met: the bridge's page size follows the source's setting.
- **`reddit_subreddit` live posts** take `external_id` from the Atom `<id>` minus its `t3_` prefix, so they dedupe against posts saved by the JSON archive. They also keep `platform: reddit` and `source: r/<sub>`.
- **`FetchGates.shared()` is one instance per running event loop.** asyncio primitives bind to their first loop, so this gives one set of gates in the API process and a fresh set per CLI run or test. `HostLimiter` and `StartSpacer` accept an injected clock and sleep, which the host-floor tests use. `safe_ingest_posts` gained `kinds=` and `gates=` seams.
- **Kept as delegates until B4:** `classify_source`, `fetch_live_posts`, `inspect_source` and `record_live_fetch` (all over `KindRegistry` / `ArchiveMetadataWriter`), plus `ingest_source_now`. `source_fetch_service.py` went from 1727 lines to 396. Test fakes (`FakeHttp`, `RecordingSleeper`, `FakeKind`) live in `tests/_kind_fakes.py`. `KindRegistry.by_name()` was added for the writer tests and the archive-metadata fallback.
- The old `test_safe_ingest` test for the connector outage became `test_a_kind_that_is_unavailable_records_unavailable_not_error`: `KindUnavailable` raised by a kind is recorded as `unavailable` and never advances backoff.

### B4. The ingestion module: one entry point; legacy paths deleted
**Files:**
- new: `ingestion/runner.py` (keyword constructor, §A.1), `ingestion/ports.py` (all ports + `PgAdvisoryRunLock`, `JobProgressSink`, `NULL_PROGRESS`, `Db*` adapters), `ingestion/inspection.py` (`DbInspectionRefresher`), and the `run_ingestion` public surface in `ingestion/__init__.py`
- the `ignore_backoff` argument is removed from `decide_fetch` and its callers (`force` supersedes it)
- rewrite: `scripts/safe_ingest.py` as a CLI shim of about 40 lines (`--force`, `--folder`, `--source`)
- delete: `scripts/ingest.py`
- edit: `main.py`
  - delete the `/api/ingest-posts` and `/api/safe-ingest-posts` routes
  - add `POST /api/ingestion/run`
  - rewrite the `fetch-now` and `folders/{id}/ingest` bodies (async-only; each takes `background_tasks: BackgroundTasks` and returns `JSONResponse` 202, or 503 on job failure)
  - remove `LiveFetchRequest.asyncMode`
  - add a 409 on the archive when unavailable
- edit: `insight_api_bridge.py`
  - delete `ingest_posts` and `safe_ingest_posts`
  - `fetch_source_now` and `ingest_folder_now` become `run_ingestion` wrappers
  - new `run_ingestion_cycle`
- edit: `services/source_fetch_service.py`: delete `ingest_source_now`, `_persist_posts` and `record_live_fetch`; archive pages call `save_batch` + `Enricher` directly
- edit: `scripts/run_scheduler.py`: extract `tick(...)` (§A.4); ingestion tick + daily-work gate (seeded from the last successful `scheduler_cycle` on first run) + `scheduler_state` + `try/finally` + daily `refresh_cadence` (the B1 call at the start of `safe_ingest_posts` goes away with that function)
- edit: `services/operations_service.py`
  - scheduler config `ingest_tick_minutes`
  - `get_scheduler_state`
  - job label for `ingestion_run`
- edit: `tests/test_safe_ingest.py`: reduced to CLI argument parsing, or deleted if empty
- docs: `backend/insight_core/scripts/README.md`, ingestion section

**Tests first:**
- `test_ingestion_runner.py` (§5.7)
- `test_ingestion_routes.py` and `test_run_scheduler.py` (§5.8)

**Acceptance:**
- `grep -rn "safe_ingest_posts\|ingest_source_now\|ingest_posts\b\|_persist_posts" backend --include=*.py` finds only the CLI shim's `run_ingestion` import, or nothing
- a manual `POST /api/sources/{yt-id}/fetch-now` with `INSIGHT_YTDLP_ENABLED=0` returns a report with `decisions.skip_unavailable == 1`
- a forced RSS fetch-now writes a `source_fetch_state` row with `last_trigger='manual'`
- the `summary_line()` format test passes (it is what the scheduler logs per tick)
- after the first deploy of B4, no extra `daily_briefing` job appears unless `interval_hours` had elapsed since the last `scheduler_cycle`
- the suite is green

**Manual smoke:**
- `docker compose up -d --build backend ingestion`
- `curl -XPOST localhost:8000/api/ingestion/run -H 'content-type: application/json' -d '{}'`
- then poll `/api/operations/jobs/<id>`

**Commands:**
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_ingestion_runner`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_ingestion_routes`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_run_scheduler`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

### B5. Dead-code removal (connectors)
**Files:**
- delete:
  - `connectors/rss_connector.py`, `connectors/reddit_connector.py`, `connectors/youtube_connector.py`, `connectors/tool_registry.py`
  - `tests/connector_test.py`, `tests/upsert_test.py`, `tests/upsert_multiple_test.py`, `tests/read_posts.py`
  - the `tests/old tests/*` files found by the grep in §D.5
- edit: `connectors/__init__.py` (re-exports only). `connectors/telegram_connector.py` is kept for now: it is the basis for B8, which moves its synthesis, error mapping and throttle into `ingestion/kinds/telegram_mtproto.py`, replaces its interactive `input()` login with the non-interactive session check, and then deletes it. No ingestion path uses it after B4
- edit: `config/` or `config_manager.py`, only if it references the deleted connectors (check with the grep)

**Tests first:** in `test_source_kinds.py`:
- `test_importing_ingestion_does_not_import_connectors_or_telethon`

**Acceptance:**
- the grep from §D.5 returns nothing
- `docker compose build backend` succeeds
- the suite is green

**Command:** `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

### B6. Source health and cadence API
**Files:**
- edit: `services/operations_service.py`: `get_source_health()` is rewritten (new row shape + summary), and `overview.source_health` becomes `{summary, rows}`
- edit: `db/repo_fetch_state.py`: `load_schedule_view`
- edit: `main.py`: `GET /api/sources/health`, `PUT /api/sources/{id}/cadence`; `get_archive_catalog` entries gain `kind`, `backlog_posts`, `remaining_posts` and `estimated_seconds`
- edit: `insight_api_bridge.py`: the two pass-through methods
- edit: `tests/test_operations_service.py`

**Tests first:**
- `test_source_health.py` (§5.9)
- the `load_schedule_view` case in `test_repo_fetch_state.py`

**Acceptance:**
- `curl localhost:8000/api/sources/health | jq '.summary'` shows counts that add up to the number of enabled sources
- an override PUT is reflected in `interval_basis: "override"`

**Commands:**
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_source_health`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_operations_service`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

### B7. Reader backend: read state, feed and unread counts
**Files:**
- new: `db/migrations/0020_reader_state.sql`, `db/repo_reader.py` (`feed`, `feed_by_source`, bounded `mark_read_through`), `services/reader_service.py`
- new: `db/migrations/0021_arxiv_out_of_main_digest.sql` (§8 decision 2): `UPDATE sources SET in_main_digest = false WHERE handle_or_url IN ('https://rss.arxiv.org/rss/cs.AI', 'https://rss.arxiv.org/rss/cs.CL', 'https://rss.arxiv.org/rss/cs.LG', 'https://rss.arxiv.org/rss/physics.optics')`. It runs once (the migrator records it), so a later re-enable in the UI sticks. The two `export.arxiv.org` query feeds are not in the decision and are left alone. The sources stay `enabled` and readable through their track/folder and `scope=source:<id>`
- edit: `config/sources.json`: the four entries gain `"in_main_digest": false`; `services/source_config_sync_service.py` reads that optional key when it *creates* a source (default true; an existing row's flag is never overwritten by a sync) and writes it on export, so a fresh install gets the same default
- edit: `main.py`: `/api/feed` (incl. `view=`), `/api/feed/unread-counts`, `/api/feed/mark-read`, `PUT /api/feed/read`, `PUT /api/posts/item/{id}/read`
- edit: `services/post_detail_service.py`: `record_post_open` sets `read_at`; the favorite path sets `starred_at`
- edit: `db/repo_explainability.py`: `get_post_reader_state` reads the projection and adds `read_at`
- edit: `insight_api_bridge.py`

**Tests first:**
- `test_repo_reader.py`, `test_post_detail_reader.py` and `test_feed_routes.py` (§5.10)
- `test_migrate_runner.py`: `test_0021_arxiv_main_digest` (`@requires_test_db`, rolled back): scratch sources with the four arXiv URLs (or the existing rows) and one other source; after the 0021 SQL the four are `in_main_digest=false` and still `enabled`, the other is unchanged
- `test_source_sync_and_youtube_service.py`: a JSON entry with `"in_main_digest": false` creates the source with the flag off; a sync over an existing row does not change its flag; export round-trips the key

**Acceptance:**
- `EXPLAIN` of a feed page on the live DB uses `posts_feed_order_idx` (Index Scan, no Sort), recorded in the PR description
- latency: run `EXPLAIN (ANALYZE, BUFFERS)` 20 times each for `scope=all&filter=unread`, `scope=all&filter=all` and `view=by_source` on the live corpus; the p95 of the reported execution time is under 50ms for a 30-item page (`feed_by_source`: under 100ms); the 20 timings are recorded in the PR description
- the §F.2 backfill query: `count(*) FROM post_reader_state WHERE read_at IS NOT NULL` equals the number of distinct opened posts
- after migrating, `SELECT handle_or_url, enabled, in_main_digest FROM sources WHERE handle_or_url LIKE 'https://rss.arxiv.org/rss/%'` shows four rows, all `enabled=true, in_main_digest=false`, and `GET /api/feed?scope=all` returns none of their posts
- the suite is green

**Commands:**
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_repo_reader`
- `SKIP_BUILD=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_post_detail_reader`
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_feed_routes`
- `SKIP_BUILD=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_migrate_runner`
- `SKIP_BUILD=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_source_sync_and_youtube_service`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

**Implementation notes (B7 as built, 2026-10-09):**
- **Unread is an anti-join.** The unread predicate is `NOT EXISTS (SELECT 1 FROM post_reader_state r WHERE r.post_id = p.id AND r.read_at IS NOT NULL)`, not `rs.read_at IS NULL` on the LEFT JOIN. With the LEFT JOIN form the planner estimated ~1 row, dropped the LIMIT shortcut, and chose Seq Scan + Sort for `filter=unread`; the anti-join keeps the `posts_feed_order_idx` Index Scan. Same predicate in `feed`, `feed_by_source`, `mark_read_through` and `unread_counts`.
- **By-source window.** `feed_by_source` bounds `filter=all` and `filter=unread` by the unread window (so groups and `count` stay cheap on an archive); `filter=starred` is unbounded (a star never ages out). The group page size is `min(limit, 50)`; the group cursor is a `FeedCursor` whose `post_id` carries the source id.
- **Route details.** `/api/feed` defaults to `filter=all`, `view=stream`; `limit` must be 1–100 and `days` ≥ 1 (400 otherwise). `PUT /api/feed/read` takes at most 500 ids. Scope ids and post ids must be UUIDs (400). A 500 carries a generic "Could not … Check the backend logs." detail; the exception is logged, never echoed. `PUT /api/posts/item/{id}/read` returns `{success, post_id, updated}`.
- **Read state writes.** `set_read(…, True)` keeps the first `read_at` (re-reading does not move it); `record_post_open` and the favorite toggle write the interaction log and the projection in one transaction. `get_post_reader_state` also returns `starred_at`.
- **`sources.json`.** Export writes `"in_main_digest": false` only for sources that are off, so the default stays implicit and the file diff stays small. `get_all_sources` now also returns `in_main_digest`.
- **Acceptance evidence (live corpus, 7,102 posts).** The live `insight` DB is not migrated by this slice (it has not had 0019 either; container start migrates it on deploy). The EXPLAIN, latency, backfill and arXiv checks ran on the live DB inside one transaction that applied 0020 + 0021 and was rolled back. Results: both stream queries `Limit > Nested Loop > … Index Scan using posts_feed_order_idx`, no Sort; p95 of 20 `EXPLAIN (ANALYZE, BUFFERS)` runs: `scope=all&filter=unread` 1.15ms, `scope=all&filter=all` 1.71ms, `view=by_source` (unread) 5.79ms and (all) 5.40ms, summed over the group query and its per-group item queries (uses `posts_source_feed_order_idx`); backfill `read_at` rows 4 = distinct opened posts 4; the four arXiv RSS rows are `enabled=true, in_main_digest=false`, and none of the first 200 `scope=all` items come from them.

### B8. Telegram MTProto source kind
**Goal:** the 12 bare-handle Telegram sources become fetchable (live, inspect, archive) whenever an authorised Telethon session exists, through the same runner, gates, fetch state and save path as every other kind. The server never prompts: with no valid session the kind is reported unavailable with a clear reason. Sequential, after B4 (it needs the runner) and after B6 so the health table shows the new skip reasons; it does not touch B7's files.

**Basis:** `connectors/telegram_connector.py` (489 lines), read first. What moves and what changes:
- `_synthesize_messages` (album grouping by `grouped_id`, text-only posts, `https://t.me/<handle>/<id>` urls, `?single` media urls) → pure `synthesize_posts(messages, handle) -> list[dict]` in `kinds/telegram_mtproto.py`, producing the same post dict shape the other kinds return (`platform="telegram"`, `source="@<handle>"`)
- the `get_entity` error ladder (`ChannelInvalid`, `ChannelPrivate`, `UsernameInvalid`, `UsernameNotOccupied`, `RPCError`) → `TelethonClientFactory` translates them to `TelegramChannelError(reason)`; the kind turns that into a source error (backoff applies: the channel is the problem, not the account)
- the chunked `get_messages(entity, limit, offset_id)` loop (chunk 100, max 20 chunks) → `fetch_latest(limit)` (stops as soon as `limit` posts are synthesized; sleeps `page_delay_s` between chunks through `KindHttp.sleep`) and `archive_pages` (one `ArchivePage` per chunk, checkpoint `{"offset_id": id}`)
- `request_counter` / `REQUEST_THRESHOLD=10` / `COOLDOWN_SECONDS=18` → the profile's `batch_size=10`, `batch_cooldown_s=18`
- `connect()`'s `input()` login → **removed**; replaced by `TelegramSession.open()` (non-interactive) and the operator CLI `scripts/telegram_login.py`
- the in-loop `FloodWaitError` → `asyncio.sleep(e.seconds)` (unbounded) → the bounded flood-wait rule in §D.2
- `session_file = backend/insight_session` (inside the image, lost on rebuild) → `TELEGRAM_SESSION_PATH`, default `/app/insight_core/config/telegram/insight.session`; `config/` is bind-mounted into both containers, so the session survives rebuilds and is shared, which is why `open()` takes the advisory lock

**Files:**
- new: `ingestion/kinds/telegram_session.py` (`TelegramClientPort` protocol, `TelethonClientFactory`, `TelegramFloodWait`, `TelegramChannelError`, `telegram_session_path()`, `PgAdvisorySessionLock`)
- rewrite: `ingestion/kinds/telegram_mtproto.py` (B3 placeholder → `TelegramKind`, `TelegramSession`, `synthesize_posts`, `MAX_INLINE_FLOOD_WAIT_S`)
- edit: `ingestion/kinds/base.py`: `KindSession` protocol, `NullKindSession`, and `session()` on `SourceKind`; `adapters/base_adapter.py` and the other kinds return `NullKindSession()`
- edit: `ingestion/runner.py`: per run, open each kind's session lazily before its first due source (inside `gates.slot`), close every opened session in a `finally`; `KindUnavailable` from `open()` marks every due source of that kind `UNAVAILABLE` with the reason (no backoff), and the session is not retried within the run
- edit: `ingestion/schedule.py`: `availability_from_env` sets `telegram_credentials` from `TELEGRAM_API_ID` (an int), `TELEGRAM_API_HASH` and the session file's existence, with `telegram_reason` naming what is missing
- edit: `ingestion/gates.py`: `"platform:telegram": 2.0` in `HOST_FLOORS`
- new: `scripts/telegram_login.py`: the only interactive path (phone, code, 2FA password via `getpass`), writes the session to `telegram_session_path()`; run with `docker compose run --rm -it backend python -m insight_core.scripts.telegram_login` (an operator step, not part of any test)
- edit: `services/source_fetch_service.py`: the `create_connector(platform)` branch of the fetch path (`:344-359` today, if B4 has not already removed it) is deleted; archive plan/run for telegram sources goes through the kind like every other source, and returns the B4 409 when the kind is unavailable
- delete: `connectors/telegram_connector.py`, and `connectors/base_connector.py` + `connectors/__init__.py` when the acceptance grep shows no other importers (otherwise `connectors/__init__.py` just stops exporting Telegram)
- edit: `.gitignore`: `backend/insight_core/config/telegram/`
- edit: `.env.example`: `TELEGRAM_SESSION_PATH` (commented, with the default)
- docs: `backend/insight_core/scripts/README.md`: "Telegram session" (login once, where the file lives, what the unavailable reasons mean)

**Tests first** (`tests/test_telegram_kind.py`, all fakes, no network, no telethon session, `IsolatedAsyncioTestCase`; the kind is built with a `FakeTelegramClient` factory, a `FakeRunLock` session lock, `FakeHttp(sleep=RecordingSleeper())` and a `FixedClock`):
- `synthesize_posts`: an album of 3 messages with one caption becomes one post with 3 media urls and the caption's message id in the url; a media-only group is dropped; output matches a fixture captured from the current `_synthesize_messages`
- session lifecycle: two due telegram sources in one runner run → `connect` once, `disconnect` once, after both fetches; a fetch raising still disconnects; a run with no due telegram source never constructs a client; non-telegram kinds' `NullKindSession` is a no-op
- non-interactive auth failure → unavailable: `is_user_authorized() == False` → both due sources get outcome `UNAVAILABLE` with "not authorised" in the reason, `consecutive_failures` stays 0, `client.start`/`send_code_request` are never called, and `builtins.input` (patched to raise) is never called
- availability: no `TELEGRAM_API_ID` → `SKIP_UNAVAILABLE` with the reason naming the variable, even with `force=True`; credentials set but no session file → `SKIP_UNAVAILABLE` "no Telegram session"
- session lock held → every telegram source `UNAVAILABLE` "in use by another run", no `connect`
- flood wait: a 5s `TelegramFloodWait` on a page → the recording sleeper sees 5s, the page is retried once and the source is healthy; a 600s wait → that source `error` (backoff written, message "flood wait 600s") and the next telegram source in the run is `UNAVAILABLE` "flood wait until …" without a client call; the RSS sources in the same run are unaffected
- `TelegramChannelError` on `get_entity` → that source `error` with the reason, the next telegram source still fetched on the same client
- `fetch_latest(limit=20)` with 100-message chunks fetches 1 chunk; `limit=150` fetches 2 and sleeps `page_delay_s` between them
- `archive_pages` from checkpoint `{"offset_id": 500}` requests `offset_id=500`, yields a page per chunk with the last id as checkpoint, and ends with `checkpoint=None` on an empty chunk; `checkpoint_resumable` accepts `{"offset_id": int}` only
- `inspect` returns `available_posts` from the fake's `.total` and the oldest message's date
- `host_key` is `platform:telegram` for every MTProto source, and `FetchGates` gives it the 2s floor
- the existing `test_importing_ingestion_does_not_import_connectors_or_telethon` still passes: importing `ingestion`, `ingestion.kinds` and `ingestion.kinds.telegram_mtproto` leaves `telethon` out of `sys.modules`; only `TelethonClientFactory.create()` imports it
- `TelethonClientFactory` translation (the one test that imports telethon, skipped if it is not installed): a constructed `telethon.errors.FloodWaitError` becomes `TelegramFloodWait(seconds)`, and `ChannelPrivateError` becomes `TelegramChannelError`

**Acceptance:**
- `grep -rn "input(" backend/insight_core --include=*.py | grep -v tests` matches only `scripts/telegram_login.py`
- `grep -rn "telethon" backend/insight_core --include=*.py | grep -v tests` matches only `ingestion/kinds/telegram_session.py` and `scripts/telegram_login.py`
- `grep -rn "telegram_connector\|TelegramConnector" backend --include=*.py` returns nothing (any `tests/old tests/` file still importing it is deleted in this slice). `connectors/__init__.py` and `base_connector.py` are deleted only if `grep -rn "insight_core.connectors\|\.\.connectors" backend --include=*.py` shows no other importer; the legacy `engines/mark_i_foundation_engine.py` pair is a Mark IX non-goal, so if it still imports the package, the package stays with Telegram removed from it
- with no session file, `GET /api/sources/health` shows the 12 telegram sources as unavailable with the "no Telegram session" reason, not as errors or backoff
- manual (operator, after `telegram_login`): enabling one telegram source and running `POST /api/sources/{id}/fetch-now` yields a `RunReport` with that source `healthy` and its posts saved; this is recorded in the PR description, never run by the test suite
- the suite is green

**Commands:**
- `TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_telegram_kind`
- `SKIP_BUILD=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_source_kinds`
- `SKIP_BUILD=1 TEST_DATABASE_URL=$T ./run-tests.sh insight_core.tests.test_ingestion_runner`
- `MIGRATE=1 TEST_DATABASE_URL=$T ./run-tests.sh`

---

### F1. Frontend foundations: typecheck, tests, error and polling primitives
**Parallel-safe with B1, B2, B3, B5, B6, B7.** It touches only `frontend/`.
- It also touches nothing in `api.ts` that B4 removes. The removal of `ingestPosts`/`safeIngestPosts` is F2's job.
- `pollJob` is generic.

**Files:**
- new:
  - `frontend/tsconfig.json`: strict, `moduleResolution: bundler`, `jsx: react-jsx`, `paths @/*`, `types: ["vite/client", "node"]`, `allowImportingTsExtensions`, `noEmit`
  - `tsconfig.node.json`
  - `vitest.config.ts`: jsdom, `include src/**/*.test.tsx`
  - `src/test/setup.ts`
  - `src/lib/apiError.ts`, `src/lib/jobPolling.ts`, `src/lib/dates.ts` and their tests
  - `src/services/ApiContext.tsx` (`ApiProvider`, `useApi()`; the default value is the existing `apiService` singleton, so the 16 files that import it directly keep working unchanged; every *new* component uses `useApi()`)
  - `src/components/states/*`, `src/components/AppErrorBoundary.tsx`
- edit: `package.json`
  - `"engines": {"node": ">=22.18"}` (host-only frontend tests rely on unflagged TS type stripping in `node --test`)
  - scripts: `"typecheck": "tsc --noEmit -p ."`, `"test": "node --test src/lib/*.test.ts && vitest run"`, `"build": "tsc --noEmit -p . && vite build"`
  - devDeps: `@types/node`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `@tailwindcss/typography`
- edit: `tailwind.config.js` (typography plugin)
- edit: `frontend/Dockerfile`: builder `node:18-alpine` → `node:22-alpine` (Vite 7 needs Node ≥ 20.19; the image only builds, it runs no tests)
- edit: `src/services/api.ts`
  - `makeRequest` throws `ApiError`
  - `makeTrackedRequest` uses `pollJob` with tolerance for transient errors and an `AbortSignal`
  - the `api.ts:2361` stale comment and the unused `MilestoneNode` type are fixed
- edit: `src/App.tsx` (error boundary, `ApiProvider`)
- fix the about 101 existing type errors:
  - `PostIntelligenceInspector.tsx`: type the `mention` records
  - `DailyBriefing.tsx`: lines 1358, 1451, 1470 (wrap handlers) and 2185
  - `PostDetailPage.tsx`: 593 and 1715
  - `StoriesExplorerPage.tsx`: 181 and 461 (extend the types)
- delete the dead files: `pages/TopicsBriefing.tsx`, `components/NavigationPanel.tsx`, `DailyBriefingHeader.tsx`, `BriefingViewer.tsx`, `ui/IntelligenceCard.tsx`, `App.css`. Confirm first with `grep -rn` that nothing imports them.
- `index.html`: load IBM Plex Sans/Mono, or remove them from `index.css`. Decision: drop them and use the system stack, so there is no network font dependency.

**Tests first:** `apiError.test.ts`, `jobPolling.test.ts`, `dates.test.ts`, plus a single smoke `states.test.tsx` that proves vitest + jsdom work and that a component rendered inside `<ApiProvider value={fakeApi}>` calls the fake.

**Acceptance:**
- `npm run typecheck` exits 0
- `npm test` is green on the host (Node ≥ 22.18), and the existing 16 tests still pass
- `npm run build` is green, and `docker compose build frontend` succeeds on `node:22-alpine`
- `npx eslint src/lib src/components/states src/components/AppErrorBoundary.tsx` is clean

**Commands:** `cd frontend && npm install && npm run typecheck && npm test && npm run build`

**As built (F1, 2026-10-09), deviations from the text above:**
- The root `.gitignore` ignores `*.json`, which silently dropped the new tsconfig files. It now un-ignores `frontend/tsconfig.json` and `frontend/tsconfig.node.json`. `package-lock.json` stays untracked as before, so the Dockerfile keeps `npm ci || npm install`.
- `index.html` never loaded IBM Plex; only `index.css` named it. The decision stands: `index.css` now uses the system sans and mono stacks.
- The typography plugin restyles the `prose` blocks that already exist in DailyBriefing, StoriesExplorer and PostIntelligenceInspector. Those were no-ops before. To keep this safe, `tailwind.config.js` maps the `--tw-prose-*` colours to the theme tokens, so `prose` follows dark mode.
- 91 of the 101 type errors came from one untyped `asArray()` in `PostIntelligenceInspector.tsx`. Typed overloads fix them, along with a stray `loadEvidence(true)` argument. The DailyBriefing handlers are wrapped as `() => void handler()`. Before this, the click event was passed in as `options`.
- `src/lib/operationsOverview.ts` had 7 `no-explicit-any` lint errors, and the acceptance requires `eslint src/lib` to be clean. They became `unknown`, a type-only change.
- `api.ts` gains a public `waitForJob<T>(jobId, {signal, timeoutMs, intervalMs})` that throws (`JobFailedError` with the payload in `.value`, `JobTimeoutError`, `AbortError`, `ApiError`). It is the polling primitive for the Mark IX tracked methods in F2. `makeTrackedRequest` wraps it and keeps the Mark VIII `{success:false, error}` contract for the existing callers. It also exports `type Api` and `TrackedRequestOptions`.
- The test helper `src/test/fakeApi.ts` adds `makeFakeApi(methods)`, a Proxy that throws and names any method the test did not provide.
- `AppErrorBoundary` takes a `resetKey`. App passes the pathname, so navigating away from a crashed page recovers.
- F1 meets the parts of §F.7 that it owns, which are the tokens and the state components:
  - `components/states/` adds `Notice` (tone `status|completion|warning|error`: the four feedback kinds, as `role=status` or `role=alert`) and the shared `PRESS_FEEDBACK` (`active:scale-[0.97]`, 120ms, transform only) and `FOCUS_RING` classes.
  - The skeleton pulses only under `motion-safe`.
  - Tailwind's `future.hoverOnlyWhenSupported` puts every `hover:` style behind `(hover: hover) and (pointer: fine)`.
  - The body font gets `font-optical-sizing: auto`.

### F2. Ingestion operations UI: run report, Run cycle, health table, fetch buttons

> **Design gate:** before you write UI code, load the `apple-design`, `emil-design-eng` and `break-ui` skills with the Skill tool and meet §F.7. Acceptance includes worst-case fixtures and the dev-only `?data=` switch for every new list or row component.
**Depends on B4 (for API shapes) and B6.** Priority: **after F3** (reader value first). When F2 and F3 are both in flight, F3 lands first and F2 rebases.
- The components and pure libs can be written in parallel with B4–B6 against fixture JSON, because they touch disjoint frontend files.
- The `api.ts` method changes ship after B6 is merged.
- Parallel-safe with B7, except that both edit `api.ts`. Merge B7's api.ts lines only through F3.
- New components use `useApi()` (F1), so their tests inject a fake API through `ApiProvider`.

**Files:**
- new:
  - `src/lib/runReport.ts`, `src/lib/sourceSchedule.ts` and their tests
  - `src/hooks/useIngestionRun.ts`
  - `src/components/ops/{RunReportSummary,RunCycleButton,SourceHealthTable,CadenceOverrideEditor}.tsx` and their tests
- edit: `src/services/api.ts`
  - delete `ingestPosts`, `safeIngestPosts` and `LiveFetchResponse`
  - add `runIngestionCycle`, `fetchSourceNow` (returns `RunReport`), `fetchFolderNow`, `getSourcesHealth`, `setCadenceOverride`
  - new `SourceHealthRow`/`RunReport`/`SchedulerConfig.state` types and `ArchiveCatalogEntry` fields
- edit: `src/pages/IngestionControl.tsx`
  - the three buttons become `RunCycleButton`
  - the countdown comes from `state.next_tick_at`
  - recent responses → `RunReportSummary`
  - the archive panel shows `backlog_posts` and the ETA
  - polling pauses while the tab is hidden (`document.visibilityState`)
- edit: `src/pages/SourcesConfig.tsx` (Health & cadence tab, delete confirmations)
- edit: `src/components/SourceSettingsEditor.tsx`
- edit: `src/pages/TrackPage.tsx` (Fetch this track button, fetch in the empty state)
- edit: `src/pages/DailyBriefing.tsx`: remove the ingest buttons; the error chip becomes a link
- edit: `src/lib/operationsOverview.ts` (+ test), for the new `source_health` shape and the `ingestion_run` label

**Tests first:**
- `runReport.test.ts`, `sourceSchedule.test.ts`
- `RunReportSummary.test.tsx`, `SourceHealthTable.test.tsx`, `RunCycleButton.test.tsx`
- `useIngestionRun`: on success it invalidates `['unread-counts']` and `['sources-health']` and **not** `['feed']`
- the updated `operationsOverview.test.ts`

**Acceptance:**
- No `JSON.stringify` of an ingestion result is shown by default.
- Settings → Sources → Health shows every source, with tier, interval and basis, next due, backoff, last success, last error and a Fetch now button. It can be sorted by status and filtered by `?status=error`.
- Fetch now shows a toast with "N new posts" and refreshes the table.
- Track fetch works.
- typecheck, test, lint (touched files) and build are green.

**Commands:** `cd frontend && npm run typecheck && npm test && npx eslint src/components/ops src/lib src/pages/SourcesConfig.tsx src/pages/TrackPage.tsx && npm run build`

### F3. Reader-first home: feed, unread, keyboard, reading view, prev/next

> **Design gate:** before you write UI code, load the `apple-design`, `emil-design-eng` and `break-ui` skills with the Skill tool and meet §F.7. Acceptance includes worst-case fixtures and the dev-only `?data=` switch for every new list or row component.
**Depends on B7.** Priority: right after F1; it lands before F2.
- The pure libs (`feedNavigation`, `feedContext`) and the components can be built in parallel with B4–B7 against fixtures.
- Wiring them to `api.ts` waits for B7.
- Parallel-safe with F2 except for `api.ts` and `TrackPage.tsx`: F3 lands first and F2 rebases.

**Files:**
- new:
  - `src/lib/feedNavigation.ts`, `src/lib/feedContext.ts` and their tests
  - `src/hooks/{useFeed,usePost,useReaderMutations,useKeyboardShortcuts,useShortcutPreference}.ts`
  - `src/components/reader/{ReaderNavRail,FeedList,FeedItem,FeedGroup,FeedToolbar,ShortcutHelp,NewPostsPill}.tsx` and their tests
  - `src/pages/ReaderPage.tsx`
- edit:
  - `src/App.tsx`: `/` → ReaderPage, `/read/:scopeKind/:scopeId?`, `/hub` → Index; the global `ThemeToggle` is hidden on reader routes (the rail/toolbar hosts it)
  - `src/pages/Index.tsx`: retitled "All tools", the brochure copy and the duplicate card removed
  - `src/services/api.ts`: `getFeed`, `getFeedGroups`, `getUnreadCounts`, `setPostRead`, `setPostsRead`, `markReadThrough`, plus the `FeedItem`/`FeedPage`/`FeedGroup`/`FeedGroupsPage`/`MarkReadResult`/`UnreadCounts` types and `ReaderState.read_at`
  - `src/pages/PostDetailPage.tsx`: load via `usePost` (react-query); timeline lazy on expand; prev/next from `?ctx=` with next-page fetch at the end and a "Back to feed" fallback without context; shortcuts; reading column + typography; original content first; the summary collapsible; the action bar wraps; the marketing copy removed
  - `src/pages/TrackPage.tsx`: read state on cards; "Read" passes `?ctx=`
  - `src/pages/DailyBriefing.tsx`: remove the "All posts" mode and its N+1 loader (`:740-812`); add an "Open in reader" link
- Infinite scroll uses `IntersectionObserver` on a sentinel. There is also a visible "Load more" button as the accessible fallback.
- `FeedToolbar` has: the filter (Unread/Starred/All), the view switch (Stream / By source), the density switch (Comfortable / Compact title-only, persisted in localStorage), the scope fetch button, and (below `md`) the nav-drawer button.
- The selected item and the next one are prefetched with `prefetchPost(id)`, so `o` opens from cache.

**Tests first:**
- `feedNavigation.test.ts`, `feedContext.test.ts`
- `FeedList.test.tsx` and `ReaderPage.test.tsx` (§5.11), `ReaderNavRail.test.tsx` (unread badges render from counts; the active scope has `aria-current="page"`; below `md` it renders as a drawer toggled from the toolbar)
- `FeedGroup.test.tsx`: renders ≤ 3 items plus "N more from <source>", which links to the source scope

**Acceptance:**
- `/` opens straight into the unread feed for the main digest.
- j/k/o/m/s/u/?/f all work as in §F.5, and the shortcut toggle in `?` switches the single-key shortcuts off.
- By-source view shows one group per source; Compact density shows title-only rows.
- Refocusing the window or finishing an ingestion run never reorders the loaded list; a "N new posts" pill appears instead.
- Opening a post from the feed shows its content without a loading skeleton when it was prefetched.
- Reload on a post page opened from the feed keeps prev/next (context in `?ctx=`).
- Mark all read up to here shows a toast with the count and a working 5-second Undo.
- At 375px width: the nav rail is a drawer, row buttons are ≥ 44px, and nothing fixed overlaps the list or "Load more" (manual check in devtools, screenshot in the PR).
- Opening a post marks it read: the badge decrements without a reload.
- Prev/next on the post page follows the feed order.
- Starred filter works.
- Mark all read up to here works, with a confirmation.
- Reading view: original content in a column of 75ch or less at 18px.
- Lighthouse a11y ≥ 95 on `/`, in a manual check.
- typecheck, test, lint (touched files) and build are green.

**Commands:** `cd frontend && npm run typecheck && npm test && npx eslint src/components/reader src/hooks src/pages/ReaderPage.tsx src/pages/PostDetailPage.tsx && npm run build`

---

### Slice order and parallelism summary

| Order | Slice | Depends on | Can run in parallel with |
|---|---|---|---|
| 1 | B1 fetch schedule | — | F1 |
| 2 | B2 save batch | B1 | F1 |
| 3 | B3 kinds + gates | B2 | F1 |
| 4 | B4 ingestion module | B3 | F1 (fully); F2 component/lib work against fixtures |
| 5 | B5 dead code | B4 | F1, F2, F3 (lib/components) |
| 6 | B6 health API | B4 (B5 optional) | F1, F2 lib/components, F3 lib/components |
| 7 | B7 reader backend (+ arXiv `in_main_digest=false`, 0021) | B1 (migration numbering only; logically independent). May be pulled forward to run right after B1 so F3 can wire up sooner; it is **not** parallel-safe with B4/B6 (all three edit `main.py` and `insight_api_bridge.py`) | F1, F2 |
| 8 | B8 Telegram MTProto kind | B4 (runner), B6 (health reasons), B5 (connector cleanup) | F1, F2, F3 (it touches no frontend files and none of B7's) |
| — | F1 foundations | — | all backend slices |
| — | F3 reader (frontend priority 2) | F1, B7 (for api.ts wiring) | B4–B6, F2 lib/components |
| — | F2 ops UI (frontend priority 3) | F1, B4, B6 (for api.ts wiring); rebases on F3 | B5, B7, F3 lib/components |

That makes 11 slices in total (B1–B8 and F1–F3). Every slice ends with the full backend suite green. Frontend slices also end with `npm run typecheck && npm test && npm run build` green.

---

## 7. Risks and mitigations

- **Migration 0019 drops `settings.ops` / `settings.ingest_backoff`.**
  - Mitigation: the backfill runs in the same transaction, the `INSERT … SELECT` is idempotent, malformed JSONB values are cast through `pg_temp.try_ts`/`try_int` instead of aborting, out-of-set statuses are normalised to NULL inside the SELECT, and `test_0019_backfill` covers all of this on the test DB.
  - Both containers run `migrate.py` at start; the B1 advisory xact lock serialises them.
  - Before running it, back up with `docker exec insight-db pg_dump -U insight -t sources insight > /tmp/sources_pre_0019.sql`. The B1 PR description records this.
- **The hourly tick changes how often the scheduler acts.**
  - Mitigation: briefings stay gated on `interval_hours`, and only due sources are fetched.
  - The first run after deploy fetches every source whose `last_success_at` is older than its interval. That is about the same as a Mark VIII cycle.
  - Daily work does not fire on the first tick: `last_daily_work_at` is seeded from the last successful `scheduler_cycle` job (§A.4).
- **Reddit platform sources switch to the RSS URL form.** The one live `r/LocalLLaMA` source starts working. The 8s host floor on `reddit.com` and `platform:reddit` covers it and the 10 `.rss` reddit feeds (which are `generic_rss`), because floors are keyed by host, not kind.
- **Telegram MTProto touches a real account.** A flood wait or an over-eager archive can get the account limited. Mitigation: one shared client per run under the host lock (`platform:telegram`, 2s floor), the 10-request / 18s batch cooldown carried over from the connector, `flood_sleep_threshold=0` with a 60s inline cap, and a long flood wait stops all telegram fetching for the rest of the run instead of retrying. Until an operator runs `telegram_login`, the 12 sources are reported unavailable ("no Telegram session") rather than as errors.
- **Shared session file.** Both containers mount `config/`, and Telethon's SQLite session cannot be opened by two processes at once. Mitigation: the `insight.telegram_session` advisory lock around every session open; the loser reports "in use by another run".
- **Enrichment on inserted posts only.** Posts updated in place, such as those where RSS full-content expansion arrived later, are not re-enriched. This is accepted and deferred to the analysis version, which is where content-hash change detection belongs.
- **Type-error cleanup in F1 touches large files** (DailyBriefing, PostDetailPage). Mitigation: type-level edits only (annotations, narrowing, handler wrappers), with no behaviour changes, and each one reviewed in the diff.

---

## 8. Decisions (product owner, 2026-10-09)

1. **Scope of F2: keep the full F2.** F2 ships the full Source health table and the `CadenceOverrideEditor` (goal 7), as written. The frontend priority stays F1 → F3 → F2.
2. **Default feed view on `/`: `stream`.** `/` stays `stream` by default, with `by_source` as a toggle. The four arXiv RSS feeds (`cs.AI`, `cs.CL`, `cs.LG`, `physics.optics`) default to `in_main_digest=false`, so they leave the main feed but stay enabled and readable through their track. This lands in B7 as migration `0021_arxiv_out_of_main_digest.sql` plus the `sources.json` key.
3. **Telegram MTProto is in Mark IX.** Not a stub: a real `telegram_mtproto` kind with a session lifecycle on the `SourceKind` seam (opened and closed around a run), non-interactive authorisation (the server never prompts on stdin; with no valid session the kind is unavailable with a clear reason), a politeness profile with flood-wait handling, live fetch and archive pages. The 12 bare-handle Telegram sources become fetchable once a session exists. This is slice B8, built from `connectors/telegram_connector.py`.
4. **Feed search is deferred** to the analysis version. `/` stays unbound and `/api/feed` gets no `q=`.
