// API service for INSIGHT backend communication
import { apiErrorFromResponse, errorMessage, isAbortError, toApiError } from '../lib/apiError';
import { JobFailedError, pollJob } from '../lib/jobPolling';
import { asRunReport } from '../lib/runReport';

// Use relative base by default (Vite dev proxy will forward /api to backend). Override with VITE_API_URL in production.
const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || '';

export interface PostsResponse {
  success: boolean;
  posts: Post[];
  date: string;
  total: number;
  source: string;  // "database"
  error?: string;
}

export interface PostsBySourceResponse {
  success: boolean;
  posts: Post[];
  source_id: string;
  total: number;
  returned?: number;
  offset?: number;
  limit?: number | null;
  has_more?: boolean;
  error?: string;
}

export interface SourceWithCount {
  id: string;
  handle_or_url: string;
  display_name: string;  // Display name from settings, fallback to handle_or_url
  enabled: boolean;
  post_count: number;
  priority: number;  // Priority for sorting
}

export interface PlatformData {
  sources: SourceWithCount[];
  total_count: number;
}

export interface SourcesWithCountsResponse {
  success: boolean;
  platforms: Record<string, PlatformData>;  // e.g., { "rss": {...}, "telegram": {...} }
  total_posts: number;
  error?: string;
}

export interface SourceSettings {
  display_name?: string;
  fetch_delay_seconds?: number;
  priority?: number;
  max_posts_per_fetch?: number;
  archive?: Record<string, any>;
}

export interface SourceWithSettings {
  id: string;
  platform: string;
  handle_or_url: string;
  enabled: boolean;
  post_count: number;
  settings: SourceSettings;
  created_at?: string;
  updated_at?: string;
}

export interface SourceSettingsResponse {
  success: boolean;
  source_id: string;
  settings: SourceSettings;
  source?: SourceWithSettings;
  error?: string;
}

export interface SourcesWithSettingsResponse {
  success: boolean;
  sources: SourceWithSettings[];
  total: number;
  error?: string;
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
  metadata?: Record<string, any>;
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
}

// ---- Reader (Mark IX, B7: /api/feed*) ----

export type FeedFilter = 'all' | 'unread' | 'starred';
export type FeedView = 'stream' | 'by_source';

export interface FeedItem {
  id: string; title: string; excerpt: string; url: string;   // title already falls back to the excerpt
  source_id: string; source_display_name: string; platform: string;
  sort_at: string; published_at: string | null; read_at: string | null; starred_at: string | null;
  reading_minutes: number | null; duration_seconds: number | null;
  media_thumb: string | null;
}
export interface FeedPage { success: true; items: FeedItem[]; next_cursor: string | null; }
export interface FeedGroup {
  source_id: string; source_display_name: string; platform: string;
  newest_sort_at: string; count: number; items: FeedItem[];   // items <= 3
}
export interface FeedGroupsPage { success: true; groups: FeedGroup[]; next_cursor: string | null; }
export interface MarkReadResult { success: true; updated: number; ids: string[]; }
export interface UnreadCounts { total: number; by_source: Record<string, number>; by_folder: Record<string, number>; }

export interface FeedParams {
  /** `all`, `folder:<uuid>` or `source:<uuid>`. */
  scope: string;
  filter: FeedFilter;
  cursor?: string | null;
  limit?: number;
  days?: number;
  signal?: AbortSignal;
}

export interface ArchiveResponse {
  success?: boolean;
  error?: string;
  [key: string]: any;
}

/** What a kind's available_posts means (backend kinds/base.py AvailableBasis). */
export type AvailableBasis = 'exact' | 'upper_bound' | 'estimate' | 'listing_cap' | 'feed_window' | 'unknown';

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
    desired_posts?: number;
    error?: string;
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

export interface ArchiveStatusResponse {
  success?: boolean;
  error?: string;
  archive?: ArchiveState;
  /** Missing from a backend older than the source sheet's archive section. */
  support?: ArchiveSupport | null;
  latest_job?: ArchiveJobSummary | null;
}

/** POST /api/archive/{id}/plan `archive`: one inspection of the source plus the estimate. */
export interface ArchivePlan {
  available_posts: number | null;
  available_basis?: AvailableBasis;
  desired_posts: number;
  remaining_posts: number;
  estimated_pages: number;
  estimated_seconds: number;
  current_stored_posts?: number;
  resume: boolean;
  resume_available: boolean;
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
  /** The archive plan's requested target still to fetch (not the backlog). */
  remaining_posts?: number | null;
  /** The archive plan's time estimate for `remaining_posts`, in seconds. */
  estimated_seconds?: number | null;
  archive_status?: string | null;
  resume_ready?: boolean;
  source_type?: string | null;
  last_archived_at?: string | null;
  last_live_fetch_at?: string | null;
  checkpoint?: Record<string, any> | null;
  rate_limit?: Record<string, any>;
}

export interface ArchiveCatalogResponse {
  success?: boolean;
  error?: string;
  sources?: ArchiveCatalogEntry[];
  total?: number;
}

/** An archive request's pacing overrides, in the names the backend's `ArchiveRequest` takes; a key left out keeps the saved or default value. */
export interface ArchivePacing {
  pageDelaySeconds?: number;
  batchSize?: number;
  batchCooldownSeconds?: number;
}

export interface LogTailResponse {
  success?: boolean;
  error?: string;
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
  payload?: Record<string, any>;
  progress?: number;
  event_count?: number;
  started_at?: string | null;
  finished_at?: string | null;
}

// ---- Mark IX ingestion types (spec §F.3) ----

export type DecisionKind = 'fetch_new_source' | 'fetch_due' | 'fetch_retry' | 'fetch_forced'
  | 'skip_not_due' | 'skip_backoff' | 'skip_unavailable' | 'skip_disabled';
export type CadenceTier = 'fast' | 'medium' | 'slow' | 'unknown';
export type OutcomeStatus = 'healthy' | 'empty' | 'error' | 'unavailable';
export type SourceSelector = { kind: 'all' } | { kind: 'folder'; id: string } | { kind: 'source'; id: string };
/** One status per health row (B6): the summary buckets plus `disabled`. */
export type HealthStatus = 'error' | 'backoff' | 'unavailable' | 'due' | 'deferred' | 'disabled';
export type IntervalBasis = 'override' | 'tier' | 'probation' | 'backlog_guard' | 'profile_floor';
export type RunStatus = 'success' | 'partial' | 'failed' | 'skipped_busy' | 'nothing_due';

export interface RunReport {
  run_id: string | null;
  trigger: 'scheduler' | 'manual' | 'cli';
  selector: SourceSelector;
  force: boolean;
  status: RunStatus;
  /** The backend's one-line summary ("12 due, 63 deferred, 1 failed; 48 new posts"). */
  summary?: string;
  started_at: string;
  finished_at: string;
  duration_s?: number;
  sources_considered: number;
  sources_fetched: number;
  sources_failed: number;
  decisions: Partial<Record<DecisionKind, number>>;
  posts_fetched: number;
  /** THE "new posts" number. */
  posts_inserted: number;
  posts_updated: number;
  posts_failed: number;
  failures: { source_id: string; display_name: string; stage: 'fetch' | 'save' | 'connector'; error: string }[];
  post_failures: { url: string | null; source_id: string; stage: 'upsert' | 'discarded'; error: string }[];
  inserted_by_source: { source_id: string; display_name: string; inserted: number }[];
}

// ---- Connections (Mark IX §10.1): write-only secrets. No call returns a stored value. ----

export type CredentialProviderId = 'substack' | 'telegram' | 'reddit' | 'youtube' | (string & {});

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
  needed: boolean;
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
  backlog_posts: number | null;
  tier: CadenceTier;
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

export interface OperationsOverviewResponse {
  success?: boolean;
  error?: string;
  scheduler?: SchedulerConfig;
  jobs?: JobRun[];
  /** Summary plus the 8 worst rows (Mark IX); use lib/operationsOverview.normalizeSourceHealth. */
  source_health?: { summary: SourceHealthSummary; rows: SourceHealthRow[] };
  alerts?: Array<{
    id: string;
    severity: string;
    title: string;
    message: string;
    started_at?: string | null;
    source_id?: string | null;
  }>;
  stats?: Record<string, any>;
}

export interface OperationJobResponse {
  success?: boolean;
  error?: string;
  job?: JobRun | null;
}

export interface SystemCorpusStatus {
  total_posts: number;
  enabled_sources: number;
  total_sources: number;
  latest_post_at?: string | null;
  oldest_post_at?: string | null;
  latest_fetch_at?: string | null;
  posts_last_24h: number;
}

export interface SystemFolderStatus {
  id: string;
  name: string;
  source_count: number;
  post_count: number;
}

export interface SystemJobStatus {
  id: string;
  job_type: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  message?: string | null;
}

export interface SystemStatusResponse {
  success: boolean;
  healthy?: boolean;
  generated_at?: string;
  corpus?: SystemCorpusStatus;
  scheduler?: Partial<SchedulerConfig>;
  folders?: SystemFolderStatus[];
  recent_jobs?: SystemJobStatus[];
  source_health_summary?: { monitored?: number; errors?: number };
  error?: string;
}

/** Polling knobs for a request that may come back as a job (202 + job_id). */
export interface TrackedRequestOptions {
  timeoutMs?: number;
  intervalMs?: number;
  signal?: AbortSignal;
}

interface AcceptedJobResponse {
  success?: boolean;
  accepted?: boolean;
  job_id?: string;
  job_type?: string;
  status?: string;
  message?: string;
}

export interface PostDetailResponse {
  success?: boolean;
  error?: string;
  post?: Post | null;
  reader_state?: ReaderState | null;
}

export interface PostInteractionResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
  event?: Record<string, any> | null;
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

export interface RedditCommentsResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
  comments?: RedditComment[];
  comment_count?: number;
  cached?: boolean;
  fetched_at?: string | null;
}

export interface SyncSourcesResponse {
  success: boolean;
  error?: string;
  message?: string;
  [key: string]: any;
}

export interface YouTubeVideoPreview {
  video_id: string;
  url: string;
  title: string;
  description?: string;
  published_at?: string | null;
  channel_title?: string | null;
  channel_id?: string | null;
  source_handle: string;
}

export interface YouTubeChannelVideosResponse {
  success?: boolean;
  error?: string;
  channel?: Record<string, any>;
  total_videos?: number;
  videos?: YouTubeVideoPreview[];
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

export interface YouTubeWatchProgressResponse {
  success?: boolean;
  error?: string;
  progress?: YouTubeWatchProgress | null;
}

class ApiService {
  /** One HTTP call. Non-2xx throws `ApiError` (status + the server's clean `detail`);
   *  a network failure throws `ApiError` with status 0. Mark VIII methods catch this
   *  and wrap it in `{success: false, error}`; Mark IX methods let it propagate to
   *  react-query and the `ErrorState` components (§4 error contract). */
  private async makeRequest<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${API_BASE_URL}${endpoint}`;

    const defaultOptions: RequestInit = {
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    };

    let response: Response;
    try {
      response = await fetch(url, { ...defaultOptions, ...options });
    } catch (error) {
      if (isAbortError(error)) throw error;
      throw toApiError(error);
    }

    if (!response.ok) {
      throw await apiErrorFromResponse(response);
    }

    return response.json();
  }

  private isAcceptedJobResponse(value: unknown): value is AcceptedJobResponse {
    return Boolean(
      value
      && typeof value === 'object'
      && (value as AcceptedJobResponse).accepted
      && typeof (value as AcceptedJobResponse).job_id === 'string',
    );
  }

  /** Wait for an operation job and resolve with its payload. Throws: `JobFailedError`
   *  (payload in `.value`) when the job fails, `JobTimeoutError`, an `AbortError` when
   *  `signal` aborts, or the `ApiError` that ended polling. Up to two consecutive
   *  transient read errors (a backend restart, a 502 from nginx) are tolerated. */
  async waitForJob<T>(jobId: string, opts?: TrackedRequestOptions): Promise<T> {
    return pollJob<T>(
      async (signal) => {
        const response = await this.makeRequest<OperationJobResponse>(
          `/api/operations/jobs/${encodeURIComponent(jobId)}`,
          { signal },
        );
        const job = response.job;
        if (!job) {
          return { state: 'failed', error: response.error || `Operation job ${jobId} not found` };
        }
        if (job.status === 'success') {
          return { state: 'done', value: (job.payload || {}) as T };
        }
        if (job.status === 'failed') {
          const payloadError = typeof job.payload?.error === 'string' ? job.payload.error : null;
          return {
            state: 'failed',
            error: payloadError || job.message || `Operation ${job.job_type} failed`,
            value: (job.payload || {}) as T,
          };
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

  /** A request that may answer 202 with a job id; polls the job when it does.
   *  Keeps the Mark VIII contract for its callers: failures, timeouts and polling
   *  errors resolve as `{success: false, error}` (the failed job's payload is
   *  spread in, as before). Only an abort rejects. */
  private async makeTrackedRequest<T extends { success?: boolean; error?: string }>(
    url: string,
    options: RequestInit,
    opts?: TrackedRequestOptions,
  ): Promise<T> {
    const requestOptions = opts?.signal ? { ...options, signal: opts.signal } : options;
    const response = await this.makeRequest<T | AcceptedJobResponse>(url, requestOptions);
    if (!this.isAcceptedJobResponse(response)) {
      return response as T;
    }
    try {
      const payload = await this.waitForJob<Record<string, unknown>>(response.job_id!, opts);
      return { success: true, ...payload } as unknown as T;
    } catch (error) {
      if (isAbortError(error)) throw error;
      const payload = error instanceof JobFailedError && error.value && typeof error.value === 'object'
        ? error.value as Record<string, unknown>
        : {};
      return { ...payload, success: false, error: errorMessage(error) } as unknown as T;
    }
  }


  async syncSources(direction: 'json-to-db' | 'db-to-json'): Promise<SyncSourcesResponse> {
    try {
      return await this.makeRequest<SyncSourcesResponse>(`/api/sources/sync/${direction}`, {
        method: 'POST',
      });
    } catch (error) {
      console.error('Failed to sync sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to sync sources',
      };
    }
  }

  async getDailyPosts(date: string): Promise<PostsResponse> {
    try {
      const response = await this.makeRequest<PostsResponse>(`/api/posts/${date}`);
      return response;
    } catch (error) {
      console.error('Failed to get daily posts:', error);
      return {
        success: false,
        posts: [],
        date: date,
        total: 0,
        source: 'database',
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getPostsBySource(
    sourceId: string,
    options?: { limit?: number; offset?: number },
  ): Promise<PostsBySourceResponse> {
    try {
      const params = new URLSearchParams();
      if (options?.limit != null) params.set('limit', String(options.limit));
      if (options?.offset != null) params.set('offset', String(options.offset));
      const query = params.toString();
      const response = await this.makeRequest<PostsBySourceResponse>(
        `/api/posts/source/${sourceId}${query ? `?${query}` : ''}`,
      );
      return response;
    } catch (error) {
      console.error('Failed to get posts by source:', error);
      return {
        success: false,
        posts: [],
        source_id: sourceId,
        total: 0,
        returned: 0,
        offset: options?.offset || 0,
        limit: options?.limit ?? null,
        has_more: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getPostDetail(postId: string): Promise<PostDetailResponse> {
    try {
      return await this.makeRequest<PostDetailResponse>(`/api/posts/item/${postId}`);
    } catch (error) {
      console.error('Failed to get post detail:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post: null,
      };
    }
  }

  async recordPostOpen(postId: string, metadata?: Record<string, any>): Promise<PostInteractionResponse> {
    try {
      return await this.makeRequest<PostInteractionResponse>(`/api/posts/item/${postId}/opened`, {
        method: 'POST',
        body: JSON.stringify({ metadata }),
      });
    } catch (error) {
      console.error('Failed to record post open:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
      };
    }
  }

  async recordPostReadingSession(
    postId: string,
    durationSeconds: number,
    metadata?: Record<string, any>,
  ): Promise<PostInteractionResponse> {
    try {
      return await this.makeRequest<PostInteractionResponse>(`/api/posts/item/${postId}/reading-session`, {
        method: 'POST',
        body: JSON.stringify({ durationSeconds, metadata }),
      });
    } catch (error) {
      console.error('Failed to record post reading session:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
      };
    }
  }

  async togglePostFavorite(postId: string, favorited: boolean): Promise<PostInteractionResponse> {
    try {
      return await this.makeRequest<PostInteractionResponse>(`/api/posts/item/${postId}/favorite`, {
        method: 'POST',
        body: JSON.stringify({ favorited }),
      });
    } catch (error) {
      console.error('Failed to toggle post favorite:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
      };
    }
  }

  async fetchRedditComments(postId: string, opts?: { limit?: number; refresh?: boolean }): Promise<RedditCommentsResponse> {
    try {
      return await this.makeTrackedRequest<RedditCommentsResponse>(`/api/posts/item/${postId}/reddit-comments`, {
        method: 'POST',
        body: JSON.stringify({
          limit: opts?.limit ?? 80,
          refresh: opts?.refresh ?? false,
          asyncMode: true,
        }),
      });
    } catch (error) {
      console.error('Failed to fetch Reddit comments:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
        comments: [],
      };
    }
  }

  async getSourcesWithCounts(): Promise<SourcesWithCountsResponse> {
    try {
      const response = await this.makeRequest<SourcesWithCountsResponse>('/api/sources/with-counts');
      return response;
    } catch (error) {
      console.error('Failed to get sources with counts:', error);
      return {
        success: false,
        platforms: {},
        total_posts: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getSourceSettings(sourceId: string): Promise<SourceSettingsResponse> {
    try {
      const response = await this.makeRequest<SourceSettingsResponse>(`/api/sources/${sourceId}/settings`);
      return response;
    } catch (error) {
      console.error('Failed to get source settings:', error);
      return {
        success: false,
        source_id: sourceId,
        settings: {},
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async updateSourceSettings(sourceId: string, settings: SourceSettings): Promise<SourceSettingsResponse> {
    try {
      const response = await this.makeRequest<SourceSettingsResponse>(`/api/sources/${sourceId}/settings`, {
        method: 'PUT',
        body: JSON.stringify(settings),
      });
      return response;
    } catch (error) {
      console.error('Failed to update source settings:', error);
      return {
        success: false,
        source_id: sourceId,
        settings: {},
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getSourcesWithSettings(): Promise<SourcesWithSettingsResponse> {
    try {
      const response = await this.makeRequest<SourcesWithSettingsResponse>('/api/sources/with-settings');
      return response;
    } catch (error) {
      console.error('Failed to get sources with settings:', error);
      return {
        success: false,
        sources: [],
        total: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async getArchiveStatus(sourceId: string): Promise<ArchiveResponse> {
    try {
      return await this.makeRequest<ArchiveResponse>(`/api/archive/${sourceId}/status`);
    } catch (error) {
      console.error('Failed to get archive status:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async getArchiveCatalog(): Promise<ArchiveCatalogResponse> {
    try {
      return await this.makeRequest<ArchiveCatalogResponse>('/api/archive/catalog');
    } catch (error) {
      console.error('Failed to get archive catalog:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        sources: [],
        total: 0,
      };
    }
  }

  async planArchive(
    sourceId: string,
    desiredPosts?: number,
    options?: {
      resume?: boolean;
      pageDelaySeconds?: number;
      batchSize?: number;
      batchCooldownSeconds?: number;
    },
  ): Promise<ArchiveResponse> {
    try {
      return await this.makeRequest<ArchiveResponse>(`/api/archive/${sourceId}/plan`, {
        method: 'POST',
        body: JSON.stringify({
          desiredPosts,
          resume: options?.resume ?? true,
          pageDelaySeconds: options?.pageDelaySeconds,
          batchSize: options?.batchSize,
          batchCooldownSeconds: options?.batchCooldownSeconds,
        }),
      });
    } catch (error) {
      console.error('Failed to plan archive:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async runArchive(
    sourceId: string,
    desiredPosts?: number,
    options?: {
      resume?: boolean;
      pageDelaySeconds?: number;
      batchSize?: number;
      batchCooldownSeconds?: number;
    },
  ): Promise<ArchiveResponse> {
    try {
      return await this.makeRequest<ArchiveResponse>(`/api/archive/${sourceId}/run`, {
        method: 'POST',
        body: JSON.stringify({
          desiredPosts,
          resume: options?.resume ?? true,
          pageDelaySeconds: options?.pageDelaySeconds,
          batchSize: options?.batchSize,
          batchCooldownSeconds: options?.batchCooldownSeconds,
        }),
      });
    } catch (error) {
      console.error('Failed to run archive:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  // ---- The source sheet's archive section (Mark IX). These throw (ApiError) instead of
  // resolving {success:false}; a backend without `support` still answers the status.

  async getSourceArchive(sourceId: string): Promise<ArchiveStatusResponse> {
    const response = await this.makeRequest<ArchiveStatusResponse>(`/api/archive/${encodeURIComponent(sourceId)}/status`);
    if (response.success === false) throw new Error(response.error || 'Could not read the archive status');
    return response;
  }

  /**
   * Ask the source how many posts it has and estimate the run. Touches the source, never the posts.
   * `pacing` overrides the source's own for this plan.
   */
  async planSourceArchive(sourceId: string, desiredPosts: number, resume: boolean, pacing?: ArchivePacing): Promise<ArchivePlan> {
    const response = await this.makeRequest<{ success?: boolean; error?: string; archive?: ArchivePlan }>(
      `/api/archive/${encodeURIComponent(sourceId)}/plan`,
      { method: 'POST', body: JSON.stringify({ desiredPosts, resume, ...pacing }) },
    );
    if (!response.success || !response.archive) throw new Error(response.error || 'Could not plan the archive');
    return response.archive;
  }

  /** Start an archive_source job (202); poll it with getOperationJob. `pacing` as for the plan. */
  async startSourceArchive(sourceId: string, desiredPosts: number, resume: boolean, pacing?: ArchivePacing): Promise<{ job_id: string }> {
    const response = await this.makeRequest<{ success?: boolean; error?: string; job_id?: string }>(
      `/api/archive/${encodeURIComponent(sourceId)}/run`,
      { method: 'POST', body: JSON.stringify({ desiredPosts, resume, background: true, ...pacing }) },
    );
    if (!response.success || !response.job_id) throw new Error(response.error || 'Could not start the archive');
    return { job_id: response.job_id };
  }

  // ---- Mark IX ingestion (spec §4). These throw (ApiError, JobTimeoutError, AbortError)
  // instead of resolving {success:false}; a finished run resolves with its RunReport even
  // when some sources failed (a `partial` run is a failed job but still a report).

  /** Start an ingestion_run job, then wait for its run report. */
  private async runIngestionJob(endpoint: string, body: Record<string, unknown>, opts?: RunRequestOptions): Promise<RunReport> {
    const accepted = await this.makeRequest<JobAccepted>(endpoint, {
      method: 'POST',
      body: JSON.stringify(body),
      signal: opts?.signal,
    });
    if (!accepted || typeof accepted.job_id !== 'string') {
      throw new Error('The backend did not start an ingestion run');
    }
    opts?.onAccepted?.(accepted);
    try {
      const payload = await this.waitForJob<unknown>(accepted.job_id, opts);
      const report = asRunReport(payload);
      if (!report) throw new Error('The ingestion run finished without a run report');
      return { ...report, run_id: report.run_id ?? accepted.job_id };
    } catch (error) {
      if (error instanceof JobFailedError) {
        const report = asRunReport(error.value);
        if (report) return { ...report, run_id: report.run_id ?? accepted.job_id };
      }
      throw error;
    }
  }

  /** The manual "Run cycle": every enabled source; due ones only unless `force`. */
  async runIngestionCycle(options: { force?: boolean } & RunRequestOptions = {}): Promise<RunReport> {
    const { force = false, ...opts } = options;
    return this.runIngestionJob('/api/ingestion/run', { force }, opts);
  }

  /** Fetch one source now (forced, even when disabled). */
  async fetchSourceNow(sourceId: string, options: { limit?: number } & RunRequestOptions = {}): Promise<RunReport> {
    const { limit, ...opts } = options;
    return this.runIngestionJob(`/api/sources/${encodeURIComponent(sourceId)}/fetch-now`, limit ? { limit } : {}, opts);
  }

  /** Fetch every enabled source of a folder/track now (forced). */
  async fetchFolderNow(folderId: string, options: { limit?: number } & RunRequestOptions = {}): Promise<RunReport> {
    const { limit, ...opts } = options;
    return this.runIngestionJob(`/api/folders/${encodeURIComponent(folderId)}/ingest`, limit ? { limit } : {}, opts);
  }

  /** Every source's schedule-aware health row, worst first, plus the summary. */
  async getSourcesHealth(): Promise<SourcesHealthResponse> {
    return this.makeRequest<SourcesHealthResponse>('/api/sources/health');
  }

  /** Set (hours in [1, 2160]) or clear (null) a source's fetch interval override. */
  async setCadenceOverride(sourceId: string, hours: number | null): Promise<{ success: true; row: SourceHealthRow }> {
    return this.makeRequest<{ success: true; row: SourceHealthRow }>(`/api/sources/${encodeURIComponent(sourceId)}/cadence`, {
      method: 'PUT',
      body: JSON.stringify({ override_hours: hours }),
    });
  }

  /** Include/exclude one source from the main digest and the main feed. Throws on failure. */
  async setSourceMainDigest(sourceId: string, inMainDigest: boolean): Promise<{ success: true; source_id: string; in_main_digest: boolean }> {
    const response = await this.makeRequest<{ success: boolean; error?: string; source_id: string; in_main_digest: boolean }>(
      `/api/sources/${encodeURIComponent(sourceId)}/main-digest`,
      { method: 'PUT', body: JSON.stringify({ in_main_digest: inMainDigest }) },
    );
    if (!response.success) throw new Error(response.error || 'Failed to update the main-digest setting');
    return response as { success: true; source_id: string; in_main_digest: boolean };
  }

  // ---- Connections (Mark IX §10.1). Write-only; these throw ApiError on failure. ----

  async getCredentials(): Promise<CredentialsResponse> {
    return this.makeRequest<CredentialsResponse>('/api/credentials');
  }

  /** Save one secret. The response is the provider's view (set, last4), never the value. */
  async putCredential(provider: string, key: string, value: string): Promise<CredentialProviderView> {
    return this.makeRequest<CredentialProviderView>(`/api/credentials/${encodeURIComponent(provider)}/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    });
  }

  async deleteCredential(provider: string, key: string): Promise<CredentialProviderView> {
    return this.makeRequest<CredentialProviderView>(`/api/credentials/${encodeURIComponent(provider)}/${encodeURIComponent(key)}`, {
      method: 'DELETE',
    });
  }

  async testCredential(provider: string): Promise<CredentialProviderView> {
    return this.makeRequest<CredentialProviderView>(`/api/credentials/${encodeURIComponent(provider)}/test`, { method: 'POST' });
  }

  async telegramLoginStart(phone: string): Promise<TelegramLoginStep> {
    return this.makeRequest<TelegramLoginStep>('/api/credentials/telegram/login/start', { method: 'POST', body: JSON.stringify({ phone }) });
  }

  async telegramLoginCode(code: string): Promise<TelegramLoginStep> {
    return this.makeRequest<TelegramLoginStep>('/api/credentials/telegram/login/code', { method: 'POST', body: JSON.stringify({ code }) });
  }

  async telegramLoginPassword(password: string): Promise<TelegramLoginStep> {
    return this.makeRequest<TelegramLoginStep>('/api/credentials/telegram/login/password', { method: 'POST', body: JSON.stringify({ password }) });
  }

  async telegramLoginCancel(): Promise<{ stage: null }> {
    return this.makeRequest<{ stage: null }>('/api/credentials/telegram/login/cancel', { method: 'POST' });
  }

  // ---- Reader (Mark IX). These throw ApiError on failure (§4 error contract). ----

  private feedQuery(params: FeedParams, view: FeedView): string {
    const qs = new URLSearchParams({ scope: params.scope, filter: params.filter, view });
    if (params.cursor) qs.set('cursor', params.cursor);
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.days) qs.set('days', String(params.days));
    return `/api/feed?${qs.toString()}`;
  }

  /** One newest-first page of the stream view. */
  async getFeed(params: FeedParams): Promise<FeedPage> {
    return this.makeRequest<FeedPage>(this.feedQuery(params, 'stream'), { signal: params.signal });
  }

  /** One page of the by-source view: one group per source, at most 3 items each. */
  async getFeedGroups(params: FeedParams): Promise<FeedGroupsPage> {
    return this.makeRequest<FeedGroupsPage>(this.feedQuery(params, 'by_source'), { signal: params.signal });
  }

  /** Unread counts (all-time; INSIGHT_UNREAD_WINDOW_DAYS can narrow them): total, per source, per folder. */
  async getUnreadCounts(): Promise<UnreadCounts> {
    return this.makeRequest<UnreadCounts>('/api/feed/unread-counts');
  }

  async setPostRead(postId: string, read: boolean): Promise<{ success: true; post_id: string; updated: number }> {
    return this.makeRequest(`/api/posts/item/${encodeURIComponent(postId)}/read`, {
      method: 'PUT',
      body: JSON.stringify({ read }),
    });
  }

  /** Batch read/unread (at most 500 ids); the mark-through Undo uses it. */
  async setPostsRead(ids: string[], read: boolean): Promise<{ success: true; updated: number }> {
    return this.makeRequest('/api/feed/read', { method: 'PUT', body: JSON.stringify({ ids, read }) });
  }

  /** Mark read every unread post in `scope` from `newest` down to `through` (both feed cursors). */
  async markReadThrough(scope: string, through: string, newest: string): Promise<MarkReadResult> {
    return this.makeRequest<MarkReadResult>('/api/feed/mark-read', {
      method: 'POST',
      body: JSON.stringify({ scope, through_cursor: through, newest_cursor: newest }),
    });
  }

  /** Star or unstar a post. Unlike `togglePostFavorite`, this throws on failure. */
  async setPostStarred(postId: string, starred: boolean): Promise<PostInteractionResponse> {
    const response = await this.makeRequest<PostInteractionResponse>(`/api/posts/item/${encodeURIComponent(postId)}/favorite`, {
      method: 'POST',
      body: JSON.stringify({ favorited: starred }),
    });
    if (response && response.success === false) throw new Error(response.error || 'Could not update the star');
    return response;
  }

  async getIngestionLogs(log = 'application', lines = 200): Promise<LogTailResponse> {
    try {
      const params = new URLSearchParams({
        log,
        lines: String(lines),
      });
      return await this.makeRequest<LogTailResponse>(`/api/ingestion/logs?${params.toString()}`);
    } catch (error) {
      console.error('Failed to load ingestion logs:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        log,
        lines: [],
      };
    }
  }

  async getOperationsOverview(): Promise<OperationsOverviewResponse> {
    try {
      return await this.makeRequest<OperationsOverviewResponse>('/api/operations/overview');
    } catch (error) {
      console.error('Failed to load operations overview:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        jobs: [],
        source_health: { summary: { due_now: 0, deferred: 0, backoff: 0, unavailable: 0, errors: 0 }, rows: [] },
        alerts: [],
      };
    }
  }

  async getOperationJob(jobId: string): Promise<OperationJobResponse> {
    try {
      return await this.makeRequest<OperationJobResponse>(`/api/operations/jobs/${jobId}`);
    } catch (error) {
      console.error('Failed to load operation job detail:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        job: null,
      };
    }
  }

  async getStatus(): Promise<SystemStatusResponse> {
    try {
      return await this.makeRequest<SystemStatusResponse>('/api/status');
    } catch (error) {
      console.error('Failed to load system status:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async getSchedulerConfig(): Promise<{ success?: boolean; error?: string; scheduler?: SchedulerConfig }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; scheduler?: SchedulerConfig }>('/api/operations/scheduler');
    } catch (error) {
      console.error('Failed to load scheduler config:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async updateSchedulerConfig(config: Partial<SchedulerConfig>): Promise<{ success?: boolean; error?: string; scheduler?: SchedulerConfig }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; scheduler?: SchedulerConfig }>('/api/operations/scheduler', {
        method: 'PUT',
        body: JSON.stringify({
          intervalHours: config.interval_hours,
          syncSourcesEachCycle: config.sync_sources_each_cycle,
          ingestTickMinutes: config.ingest_tick_minutes,
        }),
      });
    } catch (error) {
      console.error('Failed to update scheduler config:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async listYouTubeChannelVideos(source: string, limit = 1): Promise<YouTubeChannelVideosResponse> {
    try {
      return await this.makeRequest<YouTubeChannelVideosResponse>('/api/youtube/channel/videos', {
        method: 'POST',
        body: JSON.stringify({ source, limit }),
      });
    } catch (error) {
      console.error('Failed to preview YouTube channel:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async getYouTubeWatchProgress(videoId: string): Promise<YouTubeWatchProgressResponse> {
    try {
      return await this.makeRequest<YouTubeWatchProgressResponse>(`/api/youtube/progress/${videoId}`);
    } catch (error) {
      console.error('Failed to get YouTube watch progress:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        progress: null,
      };
    }
  }

  async saveYouTubeWatchProgress(
    videoId: string,
    payload: {
      videoUrl: string;
      title: string;
      durationSeconds?: number | null;
      progressSeconds: number;
      sourceId?: string | null;
      notesMarkdown?: string | null;
      completed?: boolean;
    },
  ): Promise<YouTubeWatchProgressResponse> {
    try {
      return await this.makeRequest<YouTubeWatchProgressResponse>(`/api/youtube/progress/${videoId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    } catch (error) {
      console.error('Failed to save YouTube watch progress:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        progress: null,
      };
    }
  }

  // ===== Folders =====

  /** Reading feed for one folder/track: newest posts from its sources. */
  async getFolderPosts(
    folderId: string,
    opts?: { limit?: number; offset?: number; days?: number },
  ): Promise<{
    success: boolean;
    folder?: Folder;
    source_count?: number;
    posts: Post[];
    total?: number;
    returned?: number;
    has_more?: boolean;
    error?: string;
  }> {
    try {
      const params = new URLSearchParams();
      if (opts?.limit != null) params.set('limit', String(opts.limit));
      if (opts?.offset != null) params.set('offset', String(opts.offset));
      if (opts?.days != null) params.set('days', String(opts.days));
      const qs = params.toString();
      return await this.makeRequest(`/api/folders/${folderId}/posts${qs ? `?${qs}` : ''}`);
    } catch (error) {
      return { success: false, posts: [], error: error instanceof Error ? error.message : 'Failed to load track feed' };
    }
  }

  async getFolders(): Promise<{ success: boolean; folders: Folder[]; error?: string }> {
    try { return await this.makeRequest('/api/folders'); }
    catch (e) { return { success: false, folders: [], error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async createFolder(payload: { name: string; description?: string; sort_order?: number }): Promise<{ success: boolean; folder?: Folder; error?: string }> {
    try { return await this.makeRequest('/api/folders', { method: 'POST', body: JSON.stringify(payload) }); }
    catch (e) { return { success: false, error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async deleteFolder(folderId: string): Promise<{ success: boolean; error?: string }> {
    try { return await this.makeRequest(`/api/folders/${folderId}`, { method: 'DELETE' }); }
    catch (e) { return { success: false, error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async getSourceFolders(sourceId: string): Promise<{ success: boolean; folder_ids: string[]; error?: string }> {
    try { return await this.makeRequest(`/api/sources/${sourceId}/folders`); }
    catch (e) { return { success: false, folder_ids: [], error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async addSourceToFolder(folderId: string, sourceId: string): Promise<{ success: boolean; error?: string }> {
    try { return await this.makeRequest(`/api/folders/${folderId}/sources`, { method: 'POST', body: JSON.stringify({ source_id: sourceId }) }); }
    catch (e) { return { success: false, error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async removeSourceFromFolder(folderId: string, sourceId: string): Promise<{ success: boolean; error?: string }> {
    try { return await this.makeRequest(`/api/folders/${folderId}/sources/${sourceId}`, { method: 'DELETE' }); }
    catch (e) { return { success: false, error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async addSource(payload: { platform: string; handle_or_url: string; display_name?: string; fetch_delay_seconds?: number; priority?: number; max_posts_per_fetch?: number; state?: string }): Promise<{ success: boolean; source_id?: string; error?: string }> {
    try { return await this.makeRequest('/api/sources/add', { method: 'POST', body: JSON.stringify(payload) }); }
    catch (e) { return { success: false, error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async setSourceEnabled(sourceId: string, enabled: boolean): Promise<{ success: boolean; error?: string }> {
    try { return await this.makeRequest(`/api/sources/${sourceId}/enabled`, { method: 'PUT', body: JSON.stringify({ enabled }) }); }
    catch (e) { return { success: false, error: e instanceof Error ? e.message : 'Unknown error' }; }
  }

  async deleteSource(sourceId: string): Promise<{ success: boolean; error?: string }> {
    try { return await this.makeRequest(`/api/sources/${sourceId}`, { method: 'DELETE' }); }
    catch (e) { return { success: false, error: e instanceof Error ? e.message : 'Unknown error' }; }
  }
}

export interface Folder {
  id: string;
  name: string;
  description?: string | null;
  sort_order: number;
  /** "folder" = generic grouping, "track" = curated interest with its own reading view */
  kind?: 'folder' | 'track';
  /** Hide this track's sources from the main daily/weekly digests */
  exclude_from_main_digest?: boolean;
  /** Optional narrowing within the track's sources; empty = take everything */
  match_keywords?: string[];
  source_count?: number;
  post_count?: number;
}

// Export singleton instance
export const apiService = new ApiService();
export default apiService;

/** The API client's shape. Components get it from `useApi()` (ApiContext), so
 *  tests can hand them a fake through `<ApiProvider value={fakeApi}>`. */
export type Api = ApiService;
