// The INSIGHT API client: one method per endpoint a screen calls, all through `request`.
import { JobFailedError, pollJob } from '../lib/jobPolling';
import { request, settle, type Envelope } from '../lib/request';
import { asRunReport } from '../lib/runReport';

export type { Envelope };

export interface SourceSettings {
  display_name?: string;
  fetch_delay_seconds?: number;
  archive?: Record<string, unknown>;
}

export interface SourceWithSettings {
  id: string;
  platform: string;
  handle_or_url: string;
  enabled: boolean;
  in_main_digest?: boolean;
  post_count: number;
  settings: SourceSettings;
  created_at?: string;
  updated_at?: string;
}

export interface SourceSettingsResponse extends Envelope {
  source_id: string;
  settings: SourceSettings;
  source?: SourceWithSettings;
}

/** GET /api/sources: every source with its settings and post count. */
export interface SourcesResponse extends Envelope {
  sources: SourceWithSettings[];
  total: number;
  total_posts?: number;
}

export interface Post {
  id?: string;
  source_id?: string;
  external_id?: string | null;
  title?: string;
  content: string;
  // When available (e.g., RSS), original HTML content of the post
  // Prefer this for richer rendering; fall back to `content` (plain text)
  content_html?: string;
  // Some connectors may omit or fail to serialize a date; treat as optional
  date?: string | null;
  source: string;
  platform: string;
  url?: string;
  feed_title?: string;
  media_urls?: string[];
  published_at?: string | null;
  fetched_at?: string | null;
  categories?: string[];
  metadata?: Record<string, unknown>;
  handle_or_url?: string;
  source_display_name?: string;
}

export interface ReaderState {
  post_id?: string;
  is_favorited?: boolean;
  open_count?: number;
  first_opened_at?: string | null;
  last_opened_at?: string | null;
  total_read_seconds?: number;
  /** Mark IX projection (post_reader_state): set on first open or mark read. */
  read_at?: string | null;
  starred_at?: string | null;
  /** Where a long post was left (issue 0030): the top text block in view, of the body's blocks. */
  resume_block?: number | null;
  resume_blocks?: number | null;
  /** In Later since (issue 0022); null when not in Later. */
  later_at?: string | null;
}

// ---- Reader: GET /api/feed (every post list), PUT /api/feed/read (read state) ----

/** `starred` is Keep, shown as "Kept" (issue 0022). */
export type FeedFilter = 'all' | 'unread' | 'later' | 'starred';
export type FeedView = 'stream' | 'by_source';

export interface FeedItem {
  id: string; title: string; excerpt: string; url: string;   // title already falls back to the excerpt
  source_id: string; source_display_name: string; platform: string;
  sort_at: string; published_at: string | null; read_at: string | null; starred_at: string | null;
  reading_minutes: number | null; duration_seconds: number | null;
  media_thumb: string | null;
  /** Where the post was left (issue 0030), as on the post's reader state. */
  resume_block?: number | null; resume_blocks?: number | null;
  /** In Later since (issue 0022); null or absent when not in Later. */
  later_at?: string | null;
  /** Search results only (issue 0040): the matching line, its words marked; null when the
   *  words matched only the title or the source's name. */
  snippet?: SnippetPart[] | null;
}
export interface SnippetPart { text: string; mark: boolean; }
export interface FeedPage { success: true; items: FeedItem[]; next_cursor: string | null; }
export interface FeedGroup {
  source_id: string; source_display_name: string; platform: string;
  newest_sort_at: string; count: number; items: FeedItem[];   // items <= 3
}
export interface FeedGroupsPage { success: true; groups: FeedGroup[]; next_cursor: string | null; }
/** PUT /api/feed/read: `ids` are the posts whose read state changed. */
export interface ReadStateResult { success: true; updated: number; ids: string[]; }
export interface UnreadCounts {
  total: number; by_source: Record<string, number>; by_folder: Record<string, number>;
  /** Every post in Later and its reading time in minutes (issue 0022). */
  later?: { count: number; minutes: number };
}

export interface FeedParams {
  /** `all`, `folder:<uuid>` or `source:<uuid>`. */
  scope: string;
  filter: FeedFilter;
  cursor?: string | null;
  limit?: number;
  days?: number;
  signal?: AbortSignal;
}

// ---- Search: GET /api/search (issue 0040) ----

/** Search narrows to Later or Kept, never to read state. */
export type SearchFilter = 'all' | 'later' | 'starred';
export type SearchOrder = 'newest' | 'best';
export interface SearchParams {
  q: string;
  /** No scope searches every post; `all` is the Main feed, `folder:<uuid>`, `source:<uuid>`. */
  scope?: string | null;
  filter?: SearchFilter;
  /** The last N days. */
  days?: number | null;
  order?: SearchOrder;
  cursor?: string | null;
  limit?: number;
  signal?: AbortSignal;
}

function searchPath(params: SearchParams): string {
  const qs = new URLSearchParams({ q: params.q });
  if (params.scope) qs.set('scope', params.scope);
  if (params.filter && params.filter !== 'all') qs.set('filter', params.filter);
  if (params.days) qs.set('days', String(params.days));
  if (params.order && params.order !== 'newest') qs.set('order', params.order);
  if (params.cursor) qs.set('cursor', params.cursor);
  if (params.limit) qs.set('limit', String(params.limit));
  return `/api/search?${qs.toString()}`;
}

/** What a kind's available_posts means (backend kinds/base.py AvailableBasis). */
export type AvailableBasis = 'exact' | 'upper_bound' | 'estimate' | 'listing_cap' | 'feed_window' | 'unknown';

/** GET /api/version: the build an image was stamped with (issue 0020); null when unset. */
export interface BuildVersion { version: string | null; commit: string | null; commit_date: string | null; }

/** GET /api/archive/{id}/status `support`: can this source archive (no network involved). */
export interface ArchiveSupport {
  kind: string;
  available_basis: AvailableBasis;
  archivable: boolean;
  /** Why it cannot archive (kind unavailable, a feed with nothing older), or null. */
  reason: string | null;
  unavailable: boolean;
  live_fetch_limit: number;
}

/** The newest archive_source job for a source, summarised. */
export interface ArchiveJobSummary {
  id: string;
  status: string;
  message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  progress?: number | null;
  result?: {
    posts_fetched?: number;
    posts_inserted?: number;
    posts_updated?: number;
    pages_fetched?: number;
    stored_posts?: number;
    error?: string;
    /** Issue 0016: the archive paused (a site limiting us); Resume continues from its checkpoint. */
    paused?: boolean;
    paused_reason?: string;
  };
}

export interface ArchiveRateLimit {
  page_delay_seconds?: number;
  batch_size?: number;
  batch_cooldown_seconds?: number;
}

/** settings.archive plus live storage stats, as GET /api/archive/{id}/status returns it. */
export interface ArchiveState {
  status?: string;
  stored_posts?: number;
  available_posts?: number | null;
  last_inspected_at?: string | null;
  last_archived_at?: string | null;
  resume_ready?: boolean;
  checkpoint?: { collected_posts?: number; pages_fetched?: number; completed?: boolean } | null;
  rate_limit?: ArchiveRateLimit | null;
  oldest_published_at?: string | null;
}

export interface ArchiveStatusResponse extends Envelope {
  archive?: ArchiveState;
  /** Missing from a backend older than the source sheet's archive section. */
  support?: ArchiveSupport | null;
  latest_job?: ArchiveJobSummary | null;
}

/** POST /api/archive/{id}/plan `archive`: one measurement of the source, where the archive starts, and the estimate. */
export interface ArchivePlan {
  available_posts: number | null;
  available_basis?: AvailableBasis;
  /** available - stored, or null when the source reports no size (the archive still runs to its end). */
  older_posts: number | null;
  /** The estimate for `older_posts`; null when that is unknown. */
  estimated_pages: number | null;
  estimated_seconds: number | null;
  current_stored_posts?: number;
  oldest_published_at?: string | null;
  /** The oldest stored post's date when the archive jumps below the stored posts, else null. */
  continues_from?: string | null;
  resume: boolean;
  resume_available: boolean;
  checkpoint?: { collected_posts?: number } | null;
  rate_limit?: ArchiveRateLimit;
  first_post_date?: string | null;
}

export interface ArchiveCatalogEntry {
  source_id: string;
  display_name: string;
  platform: string;
  enabled: boolean;
  /** Source kind (Mark IX §D), e.g. `generic_rss`, `telegram_mtproto`. */
  kind?: string;
  stored_posts: number;
  available_posts?: number | null;
  /** max(available - stored, 0), or null when the available count is unknown (E1). */
  backlog_posts?: number | null;
  /** The time estimate for `backlog_posts`, in seconds. */
  estimated_seconds?: number | null;
  /** When planning last measured the source; null when it never was. */
  last_inspected_at?: string | null;
  archive_status?: string | null;
  resume_ready?: boolean;
  source_type?: string | null;
  last_archived_at?: string | null;
  last_live_fetch_at?: string | null;
  checkpoint?: Record<string, unknown> | null;
  rate_limit?: Record<string, unknown>;
}

export interface ArchiveCatalogResponse extends Envelope {
  sources?: ArchiveCatalogEntry[];
  total?: number;
}

/** An archive request's pacing overrides, in the names the backend's `ArchiveRequest` takes; a key left out keeps the saved or default value. */
export interface ArchivePacing {
  pageDelaySeconds?: number;
  batchSize?: number;
  batchCooldownSeconds?: number;
}

export interface LogTailResponse extends Envelope {
  log?: string;
  available_logs?: string[];
  path?: string;
  exists?: boolean;
  updated_at?: number | null;
  lines?: string[];
}

/** When the scheduler last acted and will act next (ISO strings; empty before the first tick). */
export interface SchedulerState {
  last_tick_at?: string | null;
  next_tick_at?: string | null;
  last_daily_work_at?: string | null;
  next_daily_work_at?: string | null;
}

export interface SchedulerConfig {
  /** The daily upkeep interval (pruning, cadence, the sources.json sync). Not edited here; sent back as read. */
  interval_hours?: number;
  sync_sources_each_cycle: boolean;
  /** How often the ingestion tick looks for due sources (>= 15). */
  ingest_tick_minutes?: number;
  updated_at?: string | null;
  /** Only on GET /api/operations/scheduler. */
  state?: SchedulerState;
}

export interface JobRun {
  id: string;
  job_type: string;
  /** Human label from the backend (`ingestion_run` -> "Ingestion run"). */
  job_label?: string;
  status: string;
  trigger: string;
  source_id?: string | null;
  source_display_name?: string | null;
  source_platform?: string | null;
  message?: string | null;
  payload?: Record<string, unknown>;
  progress?: number;
  event_count?: number;
  started_at?: string | null;
  finished_at?: string | null;
}

// ---- Mark IX ingestion types (spec §F.3) ----

export type DecisionKind = 'fetch_new_source' | 'fetch_due' | 'fetch_retry' | 'fetch_forced'
  | 'skip_not_due' | 'skip_backoff' | 'skip_unavailable' | 'skip_disabled';
export type OutcomeStatus = 'healthy' | 'empty' | 'error' | 'unavailable';
/** One status per health row (B6): the summary buckets plus `disabled`. */
export type HealthStatus = 'error' | 'backoff' | 'unavailable' | 'due' | 'deferred' | 'disabled';
export type IntervalBasis = 'override' | 'tier' | 'probation' | 'backlog_guard' | 'profile_floor';
export type RunStatus = 'success' | 'partial' | 'failed' | 'skipped_busy' | 'nothing_due';

/** The parts of a run report a reader sees (issue 0021); the payload carries more. */
export interface RunReport {
  run_id: string | null;
  status: RunStatus;
  duration_s?: number;
  sources_considered: number;
  sources_fetched: number;
  sources_failed: number;
  /** Sources with at least one new post; absent from reports stored before issue 0021. */
  sources_with_new?: number;
  /** THE "new posts" number. */
  posts_inserted: number;
  /** Posts that could not be saved. */
  posts_failed: number;
  failures: { source_id: string; display_name: string; stage: 'fetch' | 'save' | 'connector'; error: string }[];
  /** At most 20, most new posts first. */
  inserted_by_source: { source_id: string; display_name: string; inserted: number }[];
}

// ---- Connections (Mark IX §10.1): write-only secrets. No call returns a stored value. ----

export type CredentialProviderId = 'substack' | 'telegram' | (string & {});

export interface CredentialField {
  key: string;
  label: string;
  hint: string;
  /** False: set only by a flow (the Telegram session). */
  writable: boolean;
  set: boolean;
  /** The last 4 characters of the saved value (null for the session). Never the value. */
  last4: string | null;
  updated_at: string | null;
  /** 'db' when stored in Connections (the only place secrets live), else 'none'. */
  source: 'db' | 'none';
  error: string | null;
}

export interface CredentialTest {
  ok: boolean;
  message: string;
  tested_at: string | null;
}

export type TelegramLoginStage = 'code' | 'password' | 'done';

export interface CredentialProviderView {
  provider: CredentialProviderId;
  label: string;
  description: string;
  testable: boolean;
  sign_in: boolean;
  configured: boolean;
  fields: CredentialField[];
  test: CredentialTest | null;
  login: { stage: TelegramLoginStage } | null;
}

export interface CredentialsResponse {
  providers: CredentialProviderView[];
}

export type TelegramLoginStep = { stage: 'code' } | { stage: 'password' } | { stage: 'done'; account: string };

export interface SourceHealthRow {
  source_id: string;
  display_name: string;
  platform: string;
  kind: string;
  enabled: boolean;
  in_main_digest: boolean;
  folders: { id: string; name: string }[];
  stored_posts: number;
  /** When its newest post was published (fetched, if undated); null without posts. */
  last_post_at: string | null;
  /** When the source was added. */
  created_at: string;
  backlog_posts: number | null;
  mean_gap_hours: number | null;
  interval_hours: number;
  interval_basis: IntervalBasis;
  override_hours: number | null;
  next_due_at: string | null;
  would_fetch_now: boolean;
  decision: DecisionKind;
  /** The decision's human text (for example the unavailable reason). */
  decision_detail?: string | null;
  /** Why the kind cannot fetch at all (no Telegram session, ...), or null. */
  unavailable_reason?: string | null;
  /** A kind that fetches less without a credential says so (Substack: teasers only). */
  credential_notice?: string | null;
  /** How its newest page reads went (issue 0032): "Pages from this source lose most of their images (5 of the last 8)", or null. */
  reading_notice?: string | null;
  status: HealthStatus;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_outcome: OutcomeStatus | null;
  last_fetched_posts: number | null;
  last_error: string | null;
  last_error_at: string | null;
  consecutive_failures: number;
  next_retry_at: string | null;
  dormant: boolean;
  /** When the source doctor last looked for this broken source's replacement (issue 0036);
   *  null when it has not in this failure streak, or the finding was dismissed. */
  doctor_looked_at?: string | null;
  /** What it found; null with doctor_looked_at set: nothing. */
  replacement?: SourceReplacement | null;
}

/** A broken source's replacement: a feed, or a page to follow (`found` articles under `prefix`). */
export interface SourceReplacement {
  kind: 'feed' | 'page_watch';
  url: string;
  title: string;
  found: number | null;
  prefix: string | null;
}

export interface SourceHealthSummary {
  due_now: number;
  deferred: number;
  backoff: number;
  unavailable: number;
  errors: number;
}

export interface SourcesHealthResponse {
  success: true;
  generated_at: string;
  rows: SourceHealthRow[];
  summary: SourceHealthSummary;
}

export interface JobAccepted {
  success: true;
  accepted?: boolean;
  job_id: string;
  job_type: string;
  status: 'running';
  message?: string;
}

/** Options for the Mark IX tracked ingestion methods. */
export interface RunRequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  intervalMs?: number;
  /** Called once the backend accepted the run (202), before polling: the job id is known. */
  onAccepted?: (job: JobAccepted) => void;
}

export interface OperationsOverviewResponse extends Envelope {
  scheduler?: SchedulerConfig;
  jobs?: JobRun[];
  /** Summary plus the 8 worst rows. */
  source_health?: { summary: SourceHealthSummary; rows: SourceHealthRow[] };
  alerts?: Array<{
    id: string;
    severity: string;
    title: string;
    message: string;
    started_at?: string | null;
    source_id?: string | null;
  }>;
  stats?: Record<string, unknown>;
}

export interface OperationJobResponse extends Envelope {
  job?: JobRun | null;
}

export interface PostDetailResponse extends Envelope {
  post?: Post | null;
  reader_state?: ReaderState | null;
}

export interface PostInteractionResponse extends Envelope {
  post_id?: string;
  event?: ({ created_at?: string } & Record<string, unknown>) | null;
  reader_state?: ReaderState | null;
  favorited?: boolean;
}

export interface RedditComment {
  id?: string;
  author?: string | null;
  body: string;
  score?: number | null;
  depth?: number | null;
  created_at?: string | null;
  permalink?: string | null;
}

export interface YouTubeWatchProgress {
  video_id?: string;
  source_id?: string | null;
  video_url?: string;
  title?: string;
  duration_seconds?: number | null;
  progress_seconds?: number | null;
  progress_percent?: number | null;
  notes_markdown?: string | null;
  watch_sessions?: number | null;
  completed?: boolean;
  last_watched_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface YouTubeWatchProgressResponse extends Envelope {
  progress?: YouTubeWatchProgress | null;
}

export interface Folder {
  id: string;
  name: string;
  description?: string | null;
  sort_order: number;
  /** "folder" = generic grouping, "track" = curated interest with its own reading view */
  kind?: 'folder' | 'track';
  /** Optional narrowing within the track's sources; empty = take everything */
  match_keywords?: string[];
  source_count?: number;
  post_count?: number;
}

export interface FoldersResponse extends Envelope {
  folders: Folder[];
}

export interface FolderResponse extends Envelope {
  folder?: Folder;
}

export interface SourceFoldersResponse extends Envelope {
  folder_ids: string[];
}

export interface SchedulerResponse extends Envelope {
  scheduler?: SchedulerConfig;
}

export interface NewSource {
  platform: string;
  handle_or_url: string;
  display_name?: string;
  fetch_delay_seconds?: number;
  /** Follow a page without a feed (issue 0028): stored as settings.page_watch. */
  page_watch?: { prefix: string };
}

export interface AddSourceResponse extends Envelope {
  source_id?: string;
}

export interface FoundFeed {
  url: string;
  title: string;
}

/** What the feed finder made of an address: a feed already, feeds found for it, a site INSIGHT reads itself, or nothing. */
export interface FeedFinding extends Envelope {
  status?: 'feed' | 'found' | 'direct' | 'none';
  feeds?: FoundFeed[];
  /** None, and the address is a site's home page (issue 0041): a poor page to follow. */
  homepage?: boolean;
  /** For a home page: the site's own blog or news pages to follow instead, the most articles first. */
  pages?: PageOffer[];
}

/** Following a page without a feed (issue 0028): the article URLs found under the path, the first few read. */
export interface PageWatchPreview extends Envelope {
  prefix?: string;
  found?: number;
  /** Some of the articles came from the site's sitemap. */
  sitemap?: boolean;
  items?: { url: string; title: string; published_at: string | null }[];
}

/** A site's blog or news page to follow instead of its home page, with its preview (issue 0041). */
export interface PageOffer {
  url: string;
  prefix: string;
  found: number;
  sitemap: boolean;
  items: { url: string; title: string; published_at: string | null }[];
}

/** POST /api/saved (issue 0031): a page saved into the Saved source, or one already stored. */
export interface SavedPage extends Envelope {
  status?: 'saved' | 'already';
  post_id?: string;
  title?: string;
  source_id?: string;
  /** False: the page could not be read as an article; its title and address were kept. */
  readable?: boolean;
  /** Why it could not be read ("HTTP 403", "no article on the page"). */
  reason?: string | null;
  /** A feed of the site that is not a source yet. */
  feed?: FoundFeed | null;
}

export interface YouTubeProgressInput {
  videoUrl: string;
  title: string;
  durationSeconds?: number | null;
  progressSeconds: number;
  sourceId?: string | null;
  notesMarkdown?: string | null;
  completed?: boolean;
}

const enc = encodeURIComponent;

/** Wait for an operation job and resolve with its payload. Throws `JobFailedError`
 *  (payload in `.value`) when the job fails, `JobTimeoutError`, an `AbortError`, or
 *  the `ApiError` that ended polling (pollJob tolerates two transient read errors). */
function waitForJob<T>(jobId: string, opts?: Pick<RunRequestOptions, 'signal' | 'timeoutMs' | 'intervalMs'>): Promise<T> {
  return pollJob<T>(
    async (signal) => {
      const { job } = await request<OperationJobResponse>(`/api/operations/jobs/${enc(jobId)}`, { signal });
      if (!job) return { state: 'failed', error: `Operation job ${jobId} not found` };
      if (job.status === 'success') return { state: 'done', value: (job.payload || {}) as T };
      if (job.status === 'failed') {
        const payloadError = typeof job.payload?.error === 'string' ? job.payload.error : null;
        return { state: 'failed', error: payloadError || job.message || `Operation ${job.job_type} failed`, value: (job.payload || {}) as T };
      }
      return { state: 'pending' };
    },
    {
      signal: opts?.signal,
      timeoutMs: Math.max(10_000, opts?.timeoutMs ?? 600_000),
      intervalMs: Math.max(500, opts?.intervalMs ?? 1_500),
    },
  );
}

/** Start an ingestion_run job, then wait for its run report. A finished run resolves
 *  with its report even when some sources failed (a `partial` run is a failed job). */
async function runIngestionJob(path: string, body: Record<string, unknown>, opts?: RunRequestOptions): Promise<RunReport> {
  const accepted = await request<JobAccepted>(path, { method: 'POST', body, signal: opts?.signal });
  if (!accepted || typeof accepted.job_id !== 'string') throw new Error('The backend did not start an ingestion run');
  opts?.onAccepted?.(accepted);
  try {
    const report = asRunReport(await waitForJob<unknown>(accepted.job_id, opts));
    if (!report) throw new Error('The ingestion run finished without a run report');
    return { ...report, run_id: report.run_id ?? accepted.job_id };
  } catch (error) {
    const report = error instanceof JobFailedError ? asRunReport(error.value) : null;
    if (report) return { ...report, run_id: report.run_id ?? accepted.job_id };
    throw error;
  }
}

function feedPath(params: FeedParams, view: FeedView): string {
  const qs = new URLSearchParams({ scope: params.scope, filter: params.filter, view });
  if (params.cursor) qs.set('cursor', params.cursor);
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.days) qs.set('days', String(params.days));
  return `/api/feed?${qs.toString()}`;
}

/**
 * The client. Methods throw `ApiError` on any failure (lib/request), for react-query
 * and the `ErrorState` components, except the ones wrapped in `settle`: those resolve
 * `{success: false, error}` for the screens that read the envelope instead.
 * Components reach it through `useApi()` (ApiContext), so a test can hand them a fake.
 */
export function createApi() {
  return {
    // ---- Reader ----

    /** One newest-first page of the stream view. */
    getFeed: (params: FeedParams) => request<FeedPage>(feedPath(params, 'stream'), { signal: params.signal }),
    /** One page of the by-source view: one group per source, at most 3 items each. */
    getFeedGroups: (params: FeedParams) => request<FeedGroupsPage>(feedPath(params, 'by_source'), { signal: params.signal }),
    /** One page of search results (issue 0040): feed rows with their matching line. */
    searchPosts: (params: SearchParams) => request<FeedPage>(searchPath(params), { signal: params.signal }),
    /** Unread counts (all-time; INSIGHT_UNREAD_WINDOW_DAYS can narrow them): total, per source, per folder. */
    getUnreadCounts: () => request<UnreadCounts>('/api/feed/unread-counts'),
    /** Mark one post or many (at most 500) read or unread. Marking read takes them out of
     *  Later unless `keepLater` (the read is only an open, issue 0022). */
    setPostsRead: (ids: string[], read: boolean, { keepLater = false }: { keepLater?: boolean } = {}) =>
      request<ReadStateResult>('/api/feed/read', { method: 'PUT', body: keepLater ? { ids, read, keep_later: true } : { ids, read } }),
    /** Put posts in Later or take them out (issue 0022). */
    setPostsLater: (ids: string[], later: boolean) =>
      request<ReadStateResult>('/api/feed/later', { method: 'PUT', body: { ids, later } }),
    /** Mark read every unread post in `scope` from `newest` down to `through` (both feed cursors). */
    markReadThrough: (scope: string, through: string, newest: string) =>
      request<ReadStateResult>('/api/feed/read', { method: 'PUT', body: { scope, through_cursor: through, newest_cursor: newest } }),
    /** Star or unstar a post. Unlike `togglePostFavorite`, this throws on failure. */
    setPostStarred: (postId: string, starred: boolean) =>
      request<PostInteractionResponse>(`/api/posts/item/${enc(postId)}/favorite`, { method: 'POST', body: { favorited: starred } }),

    // ---- The post page ----

    getPostDetail: (postId: string) => request<PostDetailResponse>(`/api/posts/item/${postId}`),
    recordPostOpen: (postId: string, metadata?: Record<string, unknown>) =>
      settle(request<PostInteractionResponse>(`/api/posts/item/${postId}/opened`, { method: 'POST', body: { metadata } })),
    recordPostReadingSession: (postId: string, durationSeconds: number, metadata?: Record<string, unknown>) =>
      settle(request<PostInteractionResponse>(`/api/posts/item/${postId}/reading-session`, { method: 'POST', body: { durationSeconds, metadata } })),
    togglePostFavorite: (postId: string, favorited: boolean) =>
      settle(request<PostInteractionResponse>(`/api/posts/item/${postId}/favorite`, { method: 'POST', body: { favorited } })),
    /** Where a long post was left (issue 0030); `null` clears it (the post was finished). */
    savePostPosition: (postId: string, block: number | null, blocks: number | null) =>
      settle(request<Envelope>(`/api/posts/item/${enc(postId)}/position`, { method: 'PUT', body: { block, blocks } })),
    getYouTubeWatchProgress: (videoId: string) =>
      settle(request<YouTubeWatchProgressResponse>(`/api/youtube/progress/${videoId}`)),
    saveYouTubeWatchProgress: (videoId: string, payload: YouTubeProgressInput) =>
      settle(request<YouTubeWatchProgressResponse>(`/api/youtube/progress/${videoId}`, { method: 'PUT', body: payload })),

    // ---- Sources ----

    getSources: () => request<SourcesResponse>('/api/sources'),
    /** Every source's schedule-aware health row, worst first, plus the summary. */
    getSourcesHealth: () => request<SourcesHealthResponse>('/api/sources/health'),
    addSource: (payload: NewSource) => settle(request<AddSourceResponse>('/api/sources', { method: 'POST', body: payload })),
    /** The feeds for any page address (issue 0026); takes up to about 10 seconds. */
    findFeed: (url: string) => settle(request<FeedFinding>('/api/sources/find-feed', { method: 'POST', body: { url } })),
    /** What following a page without a feed would give (issue 0028); reads a few of its pages. */
    savePage: (url: string, title?: string) =>
      settle(request<SavedPage>('/api/saved', { method: 'POST', body: { url, ...(title ? { title } : {}) } })),
    previewPageWatch: (url: string, prefix?: string) =>
      settle(request<PageWatchPreview>('/api/sources/page-watch/preview', { method: 'POST', body: { url, ...(prefix ? { prefix } : {}) } })),
    updateSourceSettings: (sourceId: string, settings: SourceSettings) =>
      settle(request<SourceSettingsResponse>(`/api/sources/${sourceId}/settings`, { method: 'PUT', body: settings })),
    setSourceEnabled: (sourceId: string, enabled: boolean) =>
      settle(request<Envelope>(`/api/sources/${sourceId}/enabled`, { method: 'PUT', body: { enabled } })),
    deleteSource: (sourceId: string) => settle(request<Envelope>(`/api/sources/${sourceId}`, { method: 'DELETE' })),
    /** Set (hours in [1, 2160]) or clear (null) a source's fetch interval override. */
    setCadenceOverride: (sourceId: string, hours: number | null) =>
      request<{ success: true; row: SourceHealthRow }>(`/api/sources/${enc(sourceId)}/cadence`, { method: 'PUT', body: { override_hours: hours } }),
    /** Point a broken source at its replacement (issue 0036): a feed, or with `pageWatch` a page
     *  to follow. Its name, tracks and posts stay. */
    switchSource: (sourceId: string, url: string, pageWatch?: { prefix?: string }) =>
      request<{ success: true; source_id: string; handle_or_url: string; previous: string }>(
        `/api/sources/${enc(sourceId)}/switch`, { method: 'POST', body: { url, ...(pageWatch ? { page_watch: pageWatch } : {}) } },
      ),
    /** Hide the replacement notice until the source's next failure streak; the fresh row. */
    dismissReplacement: (sourceId: string) =>
      request<{ success: true; row: SourceHealthRow }>(`/api/sources/${enc(sourceId)}/replacement/dismiss`, { method: 'POST' }),
    /** Show one source in the Main feed (true) or leave it out (false). */
    setSourceMainDigest: (sourceId: string, inMainDigest: boolean) =>
      request<{ success: true; source_id: string; in_main_digest: boolean }>(
        `/api/sources/${enc(sourceId)}/main-digest`, { method: 'PUT', body: { in_main_digest: inMainDigest } },
      ),

    // ---- Tracks (folders) ----

    getFolders: () => settle(request<FoldersResponse>('/api/folders')),
    createFolder: (payload: { name: string; description?: string; sort_order?: number }) =>
      settle(request<FolderResponse>('/api/folders', { method: 'POST', body: payload })),
    /** Rename a track. */
    renameTrack: (folderId: string, name: string) => request<Envelope>(`/api/folders/${enc(folderId)}`, { method: 'PUT', body: { name } }),
    deleteFolder: (folderId: string) => settle(request<Envelope>(`/api/folders/${folderId}`, { method: 'DELETE' })),
    /** Every source in the track shown in (true) or left out of (false) the Main feed. */
    setTrackMainDigest: (folderId: string, inMainDigest: boolean) =>
      request<Envelope>(`/api/folders/${enc(folderId)}/main-digest`, { method: 'PUT', body: { in_main_digest: inMainDigest } }),
    getSourceFolders: (sourceId: string) => settle(request<SourceFoldersResponse>(`/api/sources/${sourceId}/folders`)),
    addSourceToFolder: (folderId: string, sourceId: string) =>
      settle(request<Envelope>(`/api/folders/${folderId}/sources`, { method: 'POST', body: { source_id: sourceId } })),
    removeSourceFromFolder: (folderId: string, sourceId: string) =>
      settle(request<Envelope>(`/api/folders/${folderId}/sources/${sourceId}`, { method: 'DELETE' })),

    // ---- Ingestion ----

    /** The manual "Run cycle": every enabled source; due ones only unless `force`. */
    runIngestionCycle: ({ force = false, ...opts }: { force?: boolean } & RunRequestOptions = {}) =>
      runIngestionJob('/api/ingestion/run', { force }, opts),
    /** Fetch one source now (forced, even when disabled). */
    fetchSourceNow: (sourceId: string, { limit, ...opts }: { limit?: number } & RunRequestOptions = {}) =>
      runIngestionJob(`/api/sources/${enc(sourceId)}/fetch-now`, limit ? { limit } : {}, opts),
    /** Fetch every enabled source of a folder/track now (forced). */
    fetchFolderNow: (folderId: string, { limit, ...opts }: { limit?: number } & RunRequestOptions = {}) =>
      runIngestionJob(`/api/folders/${enc(folderId)}/ingest`, limit ? { limit } : {}, opts),
    getOperationsOverview: () => request<OperationsOverviewResponse>('/api/operations/overview'),
    getOperationJob: (jobId: string) => request<OperationJobResponse>(`/api/operations/jobs/${jobId}`),
    getSchedulerConfig: () => request<SchedulerResponse>('/api/operations/scheduler'),
    updateSchedulerConfig: (config: Partial<SchedulerConfig>) => settle(request<SchedulerResponse>('/api/operations/scheduler', {
      method: 'PUT',
      body: {
        intervalHours: config.interval_hours,
        syncSourcesEachCycle: config.sync_sources_each_cycle,
        ingestTickMinutes: config.ingest_tick_minutes,
      },
    })),
    getVersion: () => request<BuildVersion>('/api/version'),
    getIngestionLogs: (log = 'application', lines = 200) =>
      request<LogTailResponse>(`/api/ingestion/logs?${new URLSearchParams({ log, lines: String(lines) }).toString()}`),

    // ---- Archive (the source sheet's section and the Ingestion tab) ----

    getArchiveCatalog: () => request<ArchiveCatalogResponse>('/api/archive/catalog'),
    getSourceArchive: (sourceId: string) => request<ArchiveStatusResponse>(`/api/archive/${enc(sourceId)}/status`),
    /** Ask the source how many posts it has and estimate the run. Touches the source, never the posts.
     *  `pacing` overrides the source's own for this plan. */
    planSourceArchive: async (sourceId: string, resume: boolean, pacing?: ArchivePacing): Promise<ArchivePlan> => {
      const response = await request<{ archive?: ArchivePlan }>(
        `/api/archive/${enc(sourceId)}/plan`, { method: 'POST', body: { resume, ...pacing } },
      );
      if (!response.archive) throw new Error('Could not plan the archive');
      return response.archive;
    },
    /** Start an archive_source job (202); poll it with getOperationJob. `pacing` as for the plan. */
    startSourceArchive: async (sourceId: string, resume: boolean, pacing?: ArchivePacing): Promise<{ job_id: string }> => {
      const response = await request<{ job_id?: string }>(
        `/api/archive/${enc(sourceId)}/run`, { method: 'POST', body: { resume, background: true, ...pacing } },
      );
      if (!response.job_id) throw new Error('Could not start the archive');
      return { job_id: response.job_id };
    },

    // ---- Connections (Mark IX §10.1): write-only secrets. No call returns a stored value. ----

    getCredentials: () => request<CredentialsResponse>('/api/credentials'),
    /** Save one secret. The response is the provider's view (set, last4), never the value. */
    putCredential: (provider: string, key: string, value: string) =>
      request<CredentialProviderView>(`/api/credentials/${enc(provider)}/${enc(key)}`, { method: 'PUT', body: { value } }),
    deleteCredential: (provider: string, key: string) =>
      request<CredentialProviderView>(`/api/credentials/${enc(provider)}/${enc(key)}`, { method: 'DELETE' }),
    testCredential: (provider: string) => request<CredentialProviderView>(`/api/credentials/${enc(provider)}/test`, { method: 'POST' }),
    telegramLoginStart: (phone: string) =>
      request<TelegramLoginStep>('/api/credentials/telegram/login/start', { method: 'POST', body: { phone } }),
    telegramLoginCode: (code: string) =>
      request<TelegramLoginStep>('/api/credentials/telegram/login/code', { method: 'POST', body: { code } }),
    telegramLoginPassword: (password: string) =>
      request<TelegramLoginStep>('/api/credentials/telegram/login/password', { method: 'POST', body: { password } }),
    telegramLoginCancel: () => request<{ stage: null }>('/api/credentials/telegram/login/cancel', { method: 'POST' }),
  };
}

/** The client's shape, shared by the real client and the test fake (test/fakeApi). */
export type Api = ReturnType<typeof createApi>;
