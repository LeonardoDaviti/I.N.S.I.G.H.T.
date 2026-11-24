// The INSIGHT API client: one method per endpoint a screen calls, all through `request`.
import { JobFailedError, pollJob } from '../lib/jobPolling';
import { request, settle, type Envelope } from '../lib/request';
import { asRunReport } from '../lib/runReport';
import type { Byline } from '../lib/byline';
import type { MarkxFlag, MarkxNews, MarkxOverview, MarkxPostPanel, MarkxRelated, MarkxSettings } from './markx';
import type { MarkxEntityAnswer, MarkxEntityLimits, MarkxEntityList, MarkxEntityPage, MarkxEntityQueue, MarkxQueueView } from './markx';
import type { MarkxFactAnswer, MarkxPerspectiveAccuracy, MarkxPerspectiveAnswer, MarkxStoryView } from './markx';
import type { MarkxFold, MarkxFoldAnswer } from './markx';

export type { Envelope };

export interface SourceSettings {
  display_name?: string;
  fetch_delay_seconds?: number;
  /** Re-read its stored pages now and then for changes; off by default. */
  watch_changes?: boolean;
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

/** GET /api/sources: every source with its settings and post count; `settings.archive` without its `history`. */
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
  // Original HTML when the connector has it (RSS); else render `content` (plain text)
  content_html?: string;
  // Some connectors omit the date
  date?: string | null;
  source: string;
  platform: string;
  url?: string;
  feed_title?: string;
  media_urls?: string[];
  published_at?: string | null;
  /** How precise published_at is (posts.published_precision): "month" shows as "Feb 2026". */
  published_precision?: string | null;
  fetched_at?: string | null;
  categories?: string[];
  metadata?: Record<string, unknown>;
  handle_or_url?: string;
  source_display_name?: string;
  background?: BackgroundClassic[];
  story?: FeedStory | null;
  /** Each link of its text that is a stored post: href as written -> that post's id. */
  internal_links?: Record<string, string>;
  repost?: Repost | null;
  byline?: Byline | null;
  counts?: Counts | null;
  link?: { url: string; title: string | null; post_id: string | null; kind?: 'page' | 'picture' | 'video' } | null;
  news?: { id: string; title: string; voices: number; lead_id: string; scope: string } | null;
  /** Why it shows its feed's summary only; null when read in full. */
  teaser_reason?: string | null;
}
export interface Repost { by: string[]; author: string; }
export type { Byline };
export interface Counts { points: number; comments: number; }

export interface BackgroundClassic {
  url: string; post_id: string | null; title: string | null;
  voices: number;
}

export interface ReaderState {
  post_id?: string;
  is_favorited?: boolean;
  open_count?: number;
  first_opened_at?: string | null;
  last_opened_at?: string | null;
  total_read_seconds?: number;
  read_at?: string | null;
  starred_at?: string | null;
  resume_block?: number | null;
  resume_blocks?: number | null;
  later_at?: string | null;
}

// ---- Reader: GET /api/feed (every post list), PUT /api/feed/read (read state) ----

/** `starred` is Keep ("Kept"); `updated`: a watched source's changed pages; `history`: opened or read, last first. */
export type FeedFilter = 'all' | 'unread' | 'later' | 'starred' | 'updated' | 'history';
export type FeedView = 'stream' | 'by_source';
export type ReaderView = FeedView | 'news' | 'classics' | 'topic';  // topic: a track as a topic (Mark X)

export interface FeedItem {
  id: string; title: string; excerpt: string; url: string;   // title already falls back to the excerpt
  source_id: string; source_display_name: string; platform: string;
  sort_at: string; published_at: string | null; read_at: string | null; starred_at: string | null;
  /** How precise published_at is: "month" shows as "Feb 2026" (no day). */
  published_precision?: string | null;
  reading_minutes: number | null; duration_seconds: number | null;
  media_thumb: string | null;
  resume_block?: number | null; resume_blocks?: number | null;
  later_at?: string | null;
  /** History only: your last open or reading session, also its `sort_at`. */
  opened_at?: string | null;
  /** Search results only: the matching line, words marked; null when only the title or source name matched. */
  snippet?: SnippetPart[] | null;
  /** `markx` when only Mark X's English layer matched (the snippet is then its English headline). */
  snippet_from?: 'markx' | 'meaning' | null;
  update?: PageUpdate | null;
  /** The story this row leads, its other posts folded under it; null when in no story (or every post is shown). */
  story?: FeedStory | null;
  news?: NewsScore | null;
  repost?: Repost | null;
  byline?: Byline | null;
  counts?: Counts | null;
  saved_by_you?: boolean;
}
export interface NewsScore {
  /** recent: begun in the last 48 hours; earlier: earlier this week. */
  part: 'recent' | 'earlier';
  first_at: string;
  reports: number; shares: number; mentions: number;
  score: number;
  rank?: NewsRank | null;
  notable?: boolean;
  analysis?: { id: string; title: string; source: string; author: string }[];
  unread?: number;
  /** v10.42: the reader's interest in it (its things, kind, source): its factor, why, and what can be taught. */
  personal?: NewsPersonal | null;
}
/** v10.42: what a tap teaches: one thing (an entity), one kind of news, one source. */
export type InterestDim = 'thing' | 'kind' | 'source';
/** "more" / "less"; "none": not a reason; "undo": back to what INSIGHT learned from your reads. */
export type InterestAnswer = 'more' | 'less' | 'none' | 'undo';
export interface InterestReason {
  dim: InterestDim; key: string; name: string; amount: number; words: string;
  by: 'reader' | 'seed' | 'learned'; beaten: boolean;
}
/** v10.42: what a row (or a post) offers to teach, each with the reader's tap on it (null: none). */
export interface InterestTeach {
  things: { id: string; name: string; type: string | null; answer: InterestAnswer | null }[];
  kind: { key: string; words: string; answer: InterestAnswer | null } | null;
  source: { id: string; name: string | null; answer: InterestAnswer | null } | null;
}
export interface NewsPersonal {
  p: number; factor: number; why: string | null; reasons: InterestReason[]; teach: InterestTeach;
}
export interface PostInterest extends InterestTeach { post: string; row: string | null; }
export interface Classic {
  url: string;
  post_id: string | null;
  /** The stored post's title, else the link's most common words; null: show its address. */
  title: string | null;
  voices: number;
  days: number;
  first_at: string; last_at: string;
  cited_again: boolean;
  /** Each voice once, at its first citation; on one source's page its own voices first; a Reddit author with `place`. */
  citers: { name: string; at: string; place?: string | null }[];
  read_at: string | null; later_at: string | null;
}
export interface ClassicsResponse { success: true; classics: Classic[]; next_cursor?: string | null; }
export interface StoryVoice { id: string; name: string; place?: string | null; with?: { id: string; name: string }[]; }
export interface FeedStory {
  id: string;
  voices: number;
  /** Its origin post (before the tree is drawn: its first report, else first share); null for an outside origin. */
  first?: string | null;
  /** Its voices, one row each (`voices` is these and "+N"); `with`: the voice's other sources. A one-voice story
   *  lists that voice's sources instead ("also shared by"). */
  sources: StoryVoice[];
  posts: StoryPost[];
  origin?: StoryOrigin | null;
  parent_id?: string | null;
  parent_reason?: StoryParentReason | null;
  thread?: boolean;
  reposted_by?: string[] | null;
  roundups?: StoryRoundup[];
}
export interface StoryRoundup { id: string; title: string; source_display_name: string; }
export type StoryParentReason = 'address' | 'repost' | 'thread' | 'quote' | 'citation' | 'copy' | 'time' | 'none';
export interface StoryOrigin {
  url: string; title: string | null; linked_by: number;
  /** The address to open: its first post's link as written (a gift link kept); else `url`. */
  href?: string;
}
export interface StoryPost {
  id: string; title: string; url: string; source_id: string; source_display_name: string; platform: string;
  sort_at: string; published_at: string | null; read_at: string | null;
  /** report: its own writing; share: a copy, a forward or a link post. */
  role: 'report' | 'share';
  /** Its parent in the tree: a post of the story, else (with a reason) the outside `origin`; neither: it is the
   *  origin. Absent: no tree (News). */
  parent_id?: string | null;
  parent_reason?: StoryParentReason | null;
  text?: string | null;
  html?: string | null;
  internal_links?: Record<string, string>;
  /** A thread's reply that quotes a tweet of its story: no card, "↩ quotes the post above". */
  quotes_above?: boolean;
  reposted_by?: string[] | null;
  repost?: Repost | null;
  byline?: Byline | null;
}
export interface SnippetPart { text: string; mark: boolean; }
export interface PageUpdate {
  at: string; words: number; words_added: number; words_removed: number;
  sections_added: number; sections_removed: number;
}
export interface FeedPage { success: true; items: FeedItem[]; next_cursor: string | null; }
/** GET /api/news: whose rows (`mark`), and whether the main News fell back to the older one (`fallback`, `note`). */
export interface NewsPage extends FeedPage {
  mark?: 'x' | 'ix'; fallback?: boolean; note?: string | null;
  order?: NewsOrder;
  rows?: number;
  unread_rows?: number;
}
export interface SinceRow extends FeedItem {
  since?: { voices: string[]; lines: Array<{ id: string; title: string | null; source: string }> };
}
export interface SinceTrack {
  id: string; name: string; since: string; new: number; also: number;
  lines: Array<{ text: string; kind: string | null; sources: number; post: string | null }>;
}
export interface SinceLooked {
  look: string; first: boolean;
  news: { counts: { new: number; changed: number }; new: SinceRow[]; changed: SinceRow[] };
  tracks: SinceTrack[];
}
export type NewsMark = 'main' | 'ix';
/** v10.42: personal (global x your interest, the default), ranked (global only), coverage (the score). */
export type NewsOrder = 'personal' | 'ranked' | 'coverage';
/** A Mark X News row's kept rank: significance (the worker's answer), coverage and fit, each 0..1. */
export interface NewsRank {
  significance: number | null; coverage: number; fit: number; score: number;
  event?: string | null; effect?: number | null; usable?: string | null; why?: string | null;
}
export interface SearchEntity {
  id: string; name: string; type: string | null; maker: string | null; posts: number; voices: number;
  what?: string | null;
  senses?: { id: string; what: string | null; posts: number }[];
}
export interface SearchPage extends FeedPage { entities?: SearchEntity[]; }
export interface FeedGroup {
  source_id: string; source_display_name: string; platform: string;
  newest_sort_at: string; count: number; items: FeedItem[];   // items <= 3
}
export interface FeedGroupsPage { success: true; groups: FeedGroup[]; next_cursor: string | null; }
export interface ReadStateResult { success: true; updated: number; ids: string[]; }
export interface UnreadCounts {
  total: number; by_source: Record<string, number>; by_folder: Record<string, number>;
  newest_unread?: Record<string, string | null>;
  later?: { count: number; minutes: number };
}

export interface FeedParams {
  scope: string;
  filter: FeedFilter;
  cursor?: string | null;
  limit?: number;
  days?: number;
  allSources?: boolean;
  signal?: AbortSignal;
}

// ---- Search: GET /api/search ----

/** Search narrows to Later, Kept or History, never to read state; or searches News or Classics (`classics`
 *  answers ClassicsResponse with `next_cursor`, not a FeedPage). */
export type SearchFilter = 'all' | 'later' | 'starred' | 'history' | 'news' | 'classics';
export type SearchOrder = 'newest' | 'best';
export interface SearchParams {
  q: string;
  scope?: string | null;
  filter?: SearchFilter;
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
  if (params.order) qs.set('order', params.order);  // none: the backend's order, by the words
  if (params.cursor) qs.set('cursor', params.cursor);
  if (params.limit) qs.set('limit', String(params.limit));
  return `/api/search?${qs.toString()}`;
}

/** What a kind's available_posts means (backend kinds/base.py AvailableBasis). */
export type AvailableBasis = 'exact' | 'upper_bound' | 'estimate' | 'listing_cap' | 'feed_window' | 'unknown';

export interface BuildVersion { version: string | null; commit: string | null; commit_date: string | null; }

export interface ArchiveSupport {
  kind: string;
  available_basis: AvailableBasis;
  archivable: boolean;
  reason: string | null;
  unavailable: boolean;
  live_fetch_limit: number;
}

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
    paused?: boolean;
    paused_reason?: string;
    linked?: boolean;
    waiting_until?: string;
    waiting_host?: string;
    waiting_reason?: string;
  };
}

export interface ArchiveRateLimit {
  page_delay_seconds?: number;
  batch_size?: number;
  batch_cooldown_seconds?: number;
}

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
  coverage?: import('./smartArchive').ArchiveCoverage | null;
}

export interface ArchiveStatusResponse extends Envelope {
  archive?: ArchiveState;
  support?: ArchiveSupport | null;
  latest_job?: ArchiveJobSummary | null;
}

/** GET /api/archive/{id}/linked: the source's own pages your posts link that are not stored. `readable`: one
 *  fetch can read them; `archive_holds`: the source's archive reaches them (offered first until `archive_ran`). */
export interface LinkedPagesSummary {
  count: number;
  readable: boolean;
  estimated_seconds: number | null;
  archive_holds: boolean;
  archive_ran: boolean;
  pages: Array<{ url: string; posts: number; first_linked_at: string | null }>;
}

export interface ArchivePlan {
  available_posts: number | null;
  available_basis?: AvailableBasis;
  /** available - stored, or null when the source reports no size (the archive still runs to its end). */
  older_posts: number | null;
  estimated_pages: number | null;
  estimated_seconds: number | null;
  current_stored_posts?: number;
  oldest_published_at?: string | null;
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
  kind?: string;
  stored_posts: number;
  available_posts?: number | null;
  /** max(available - stored, 0), or null when the available count is unknown. */
  backlog_posts?: number | null;
  estimated_seconds?: number | null;
  last_inspected_at?: string | null;
  archive_status?: string | null;
  resume_ready?: boolean;
  source_type?: string | null;
  last_archived_at?: string | null;
  last_live_fetch_at?: string | null;
  checkpoint?: Record<string, unknown> | null;
  rate_limit?: Record<string, unknown>;
  waiting?: ArchiveWaiting | null;
  coverage?: import('./smartArchive').ArchiveCoverage | null;
}

export interface ArchiveWaiting {
  host: string;
  until: string;
  /** "limit" (HTTP 429) or "timeout" (no answer in time). */
  reason?: string | null;
}

export interface HostLimit {
  host: string;
  requests: number;
  window_s: number;
  /** How many limits it was learned from; an archive paces to it from 2. */
  limits: number;
  archive_gap_s: number;
  line: string;
}

export interface ArchiveCatalogResponse extends Envelope {
  sources?: ArchiveCatalogEntry[];
  total?: number;
}

/** An archive request's pacing overrides (the backend's `ArchiveRequest` names); a key left out keeps the saved value. */
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
  interval_hours?: number;
  ingest_tick_minutes?: number;
  /** Collect a News story's missing original, one page, within the shared budget. On unless switched off. */
  collect_originals?: boolean;
  /** Look up unlinked originals by title (arXiv, Crossref) within the same budget. Off unless switched on. */
  lookup_originals?: boolean;
  /** Store every Classic INSIGHT lacks once, under its own allowance (100 pages a day). On unless switched off. */
  store_classics?: boolean;
  updated_at?: string | null;
  state?: SchedulerState;
}

export interface JobRun {
  id: string;
  job_type: string;
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

// ---- Ingestion types ----

export type DecisionKind = 'fetch_new_source' | 'fetch_due' | 'fetch_retry' | 'fetch_forced' | 'fetch_linked'
  | 'skip_not_due' | 'skip_backoff' | 'skip_unavailable' | 'skip_disabled';
export type OutcomeStatus = 'healthy' | 'empty' | 'error' | 'unavailable';
export type HealthStatus = 'error' | 'backoff' | 'unavailable' | 'due' | 'deferred' | 'disabled';
export type IntervalBasis = 'override' | 'tier' | 'probation' | 'backlog_guard' | 'profile_floor';
export type RunStatus = 'success' | 'partial' | 'failed' | 'skipped_busy' | 'nothing_due';

export interface RunReport {
  run_id: string | null;
  status: RunStatus;
  duration_s?: number;
  sources_considered: number;
  sources_fetched: number;
  sources_failed: number;
  sources_with_new?: number;
  /** THE "new posts" number. */
  posts_inserted: number;
  posts_failed: number;
  failures: { source_id: string; display_name: string; stage: 'fetch' | 'save' | 'connector'; error: string }[];
  inserted_by_source: { source_id: string; display_name: string; inserted: number }[];
}

// ---- Connections: write-only secrets. No call returns a stored value. ----

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

export interface MarkxTokenView {
  set: boolean;
  last4: string | null;
  updated_at: string | null;
}

/** POST /api/markx/token: the new token, the only time it is shown. */
export interface MarkxTokenCreated extends MarkxTokenView {
  token: string;
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
  last_post_at: string | null;
  created_at: string;
  backlog_posts: number | null;
  mean_gap_hours: number | null;
  interval_hours: number;
  interval_basis: IntervalBasis;
  override_hours: number | null;
  next_due_at: string | null;
  would_fetch_now: boolean;
  decision: DecisionKind;
  decision_detail?: string | null;
  unavailable_reason?: string | null;
  credential_notice?: string | null;
  reading_notice?: string | null;
  watchable?: boolean;
  watch_changes?: boolean;
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
  doctor_looked_at?: string | null;
  replacement?: SourceReplacement | null;
  server_error?: { status: number | null; site?: string } | null;
  /** Fetches work but nothing new for 30 days and over 3x its usual gap; never on a broken, disabled or kept source. */
  quiet?: boolean;
  /** 20+ posts, added 30+ days ago, none opened, put in Later or kept. */
  never_opened?: boolean;
  opened_posts?: number;
  /** When the owner last kept it from Tidy up; the marks hide for 90 days from then. */
  tidy_kept_at?: string | null;
  moved_to?: { host: string; followed: boolean } | null;
  /** Silent beyond max(5x its usual gap, 14 days), and where the doctor found it went; null when not, or marked stopped. */
  silent?: SourceSilence | null;
  /** Stopped unseen: its last success (else added) older than max(3 days, 5x interval), or 5+ failures in a row. */
  stalled?: SourceStalled | null;
  /** The doctor marked its host dead (no answer for 14+ days). Nothing is switched off by itself. */
  dead?: SourceDeadHost | null;
}

export interface SourceStalled {
  since: string | null;
  days: number | null;
  failures: number;
  posts?: number;
  reason?: string | null;
}

export interface SourceDeadHost {
  host: string;
  since: string | null;
  reason: string;
  checked_at: string | null;
}

export interface SourceSilence {
  days: number;
  usual_gap_hours: number;
  last_post_at: string | null;
  looked_at: string | null;
  moved: { via: string; from: string; to: string }[];
  /** A live feed found where it went (never switched by itself). */
  replacement: SilentReplacement | null;
}

export interface SilentReplacement {
  kind: 'feed';
  url: string;
  title: string;
  latest?: string[];
  newest?: string | null;
  via: string;
}

export interface SourceReplacement {
  kind: 'feed' | 'page_watch';
  url: string;
  title: string;
  found: number | null;
  prefix: string | null;
  shared?: number;
  latest?: string[];
}

export interface SourceHealthSummary {
  due_now: number;
  deferred: number;
  backoff: number;
  unavailable: number;
  errors: number;
  silent?: number;
  stalled?: number;
}

export interface SourcesHealthResponse {
  success: true;
  generated_at: string;
  rows: SourceHealthRow[];
  summary: SourceHealthSummary;
  host_limits?: HostLimit[];
}

export interface JobAccepted {
  success: true;
  accepted?: boolean;
  job_id: string;
  job_type: string;
  status: 'running';
  message?: string;
}

export interface RunRequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  intervalMs?: number;
  onAccepted?: (job: JobAccepted) => void;
}

export interface StoriesRunSummary {
  computed_at: string;
  seconds?: number | null;
  full?: boolean | null;
  posts?: number | null;
  stories?: number | null;
  news?: number | null;
  classics?: number | null;
  links_filled?: number | null;
  rebuild?: { done: number; total: number } | null;
}

export interface BackgroundProgress {
  total: number;
  pending: number;
}

export interface BackgroundWorkResponse extends Envelope {
  stories: { running: boolean; last_run: StoriesRunSummary | null };
  search: BackgroundProgress;
  links: BackgroundProgress;
}

export interface RunningJobsResponse extends Envelope {
  jobs?: JobRun[];
}

export interface OperationsOverviewResponse extends Envelope {
  scheduler?: SchedulerConfig;
  jobs?: JobRun[];
  source_health?: { summary: SourceHealthSummary; rows: SourceHealthRow[]; host_limits?: HostLimit[] };
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
  page_watch?: { prefix: string };
}

export interface AddSourceResponse extends Envelope {
  source_id?: string;
  warning?: string;
}

export interface FoundFeed {
  url: string;
  title: string;
  holds?: number;
  moved_to?: string;
}

export type FollowLabel = 'feed' | 'page' | 'headlines' | 'blocked' | 'other_feed';

export interface SuggestedSource {
  /** A site (`openai.com`) or an account on a platform (`x.com/nn_teacher`). */
  key: string;
  url: string;
  voices: number;
  voice_names: string[];
  article_count: number;
  link_count: number;
  articles: { url: string; title: string | null; linked_by: string[] }[];
  follow_test?: { label: FollowLabel; at: string };
  places?: string[];
  section?: 'unfollowable';
  classics?: number;
  origins?: number;
  origin_stories?: OriginStory[];
  follows?: string[];
  originals?: number;
  originals_reason?: string;
  cited_by_longreads?: number;
  account?: { url: string; label: string } | null;
}
export interface OriginStory { url: string; title: string | null; voices: number; stored: boolean; }
export interface MissingOrigins {
  source_id: string;
  name: string;
  places: string[];
  origins: number;
  since: string | null;
  older: number;
  origin_stories: OriginStory[];
  archive?: { state: 'running' | 'paused' | 'finished' | null; found: number; pages_fetched?: number };
  /** `origins`: pages it still lacks; `stored`: stored since; `stopped`: its newest post when its feed stopped;
   *  `watches`: the prefix it watches and the sections outside it; `archivable`: missing pages an archive can reach. */
  stored?: number;
  stopped?: string;
  watches?: { prefix: string; not: string[] };
  archivable?: number;
}
export interface SuggestedSourcesResponse {
  success: true;
  suggestions: SuggestedSource[];
  also?: (SuggestedSource & { of: string; source_id: string })[];
  total?: number;
  more?: boolean;
  references?: { key: string; voices: number }[];
  archives?: MissingOrigins[];
  unnamed?: { place: string; origins: number }[];
  pages?: DiscoverPage[];
  supplied?: { key: string; source_id: string; name: string; followed_at: string; originals_first: number }[];
  worlds?: { entity: { id: string; name: string }; sites: number; not_followed: number; works_not_stored: number }[];
  built_at?: string | null;
  refreshing?: boolean;
}

export type MainSourceKind = 'missing' | 'wrong_section' | 'disabled';
export interface MainSourceTest {
  label: FollowLabel;
  holds?: number | null;
  of?: number;
  feeds?: { url: string; title?: string | null; holds?: number | null }[];
  pages?: { url: string; prefix?: string | null; found?: number | null; holds?: number | null }[];
  preview?: { prefix?: string | null; found?: number | null; items: { url: string; title?: string | null }[] };
  at: string;
}
export interface MainSourceEvent {
  story: string;
  headline: string;
  event_type: string;
  voices: number;
  first_at: string | null;
  /** The actor's own page: held (a member's own address), linked (2+ members, or an X post), main_link (a short
   *  link post's), source_page (the page members link when none is the original). */
  own_page: { url: string; how: 'held' | 'linked' | 'main_link' | 'source_page'; held_by: string[] } | null;
  posts: { id: string; title: string; source: string; source_id: string; url: string | null; at: string | null }[];
}
export interface MainSourceRow {
  /** `main:<channel key>`: Not interested hides it (POST /api/sources/suggested/hide). */
  key: string;
  kind: MainSourceKind;
  channel: { key: string; kind: 'account' | 'site' | 'source'; platform: string; url: string; prefix: string | null };
  actor: { id: string; name: string };
  source: { id: string; name: string; enabled: boolean; watch: string | null } | null;
  events: MainSourceEvent[];
  latest: string | null;
  test: MainSourceTest | null;
}
export interface PeopleEvidence {
  post_id: string;
  title: string;
  url: string;
  where: string;            // "track:<name>" | "news"
  how: string;              // quote | repost | mention | link | maker
  at: string | null;
}

export interface PeopleRow {
  key: string;
  kind: 'author' | 'maker';
  platform: string;
  name: string;
  posts: number;
  sources: number;
  accounts: string[];
  tracks: string[];
  news: number;
  how: Record<string, number>;
  why: string;
  evidence: PeopleEvidence[];
  follow: { address?: string; via: string; feed?: string | null; ready: boolean } | null;
  channels?: { key: string | null; kind: string | null; state: string | null; address: string | null; source_id: string | null }[];
}

export interface PeopleResponse {
  window_days: number;
  posts: number;
  authors: PeopleRow[];
  makers: PeopleRow[];
  built_at: string | null;
  refreshing: boolean;
}

export interface MainSourceResponse {
  success: true;
  rows: MainSourceRow[];
  total: number;
  checked: number;
  events: number;
  within_days: number;
}

export type OfficialKind = 'x' | 'telegram' | 'youtube' | 'section' | 'releases';
export type OfficialState = 'candidate' | 'proven' | 'would_add' | 'added' | 'undone' | 'refused' | 'covered';
export type OfficialFrom = 'own_page' | 'site_section' | 'code_address' | 'handle' | 'web_search' | 'web_announcement';
export interface OfficialProof {
  via: string;
  address: string;
  items: number;
  dated: number;
  holds: number;
  linked: number;
  newest_days: number | null;
  announces?: 'path' | 'stream' | null;
  retry?: boolean;
}
export interface OfficialJudge {
  verdict: 'follow' | 'maybe' | 'skip' | null;
  fits: boolean | null;
  original: string | null;
  reasons: string[];
}
export interface OfficialFilter {
  kind: string;
  hide: { field: string; regex: string; why: string }[];
}
export interface OfficialRow {
  id: string;
  /** `acme.example/blog/`, `x.com/acme`, `github.com/acme/widget`. */
  key: string;
  kind: OfficialKind;
  state: OfficialState;
  why: string;
  actor: { id: string | null; name: string | null };
  follow: string | null;
  from: OfficialFrom | null;
  owned: string | null;
  proof: OfficialProof | null;
  judge: OfficialJudge | null;
  filter: OfficialFilter | null;
  source_id: string | null;
  hidden_items: number;
  events: { story: string; headline: string; voices: number; first_at: string | null }[];
  decided_at: string | null;
  created_at: string | null;
}
export interface OfficialResponse {
  success: true;
  mode: 'off' | 'shadow' | 'on';
  cap: number;
  added_today: number;
  counts: Record<string, number>;
  events: Record<string, number>;
  rows: OfficialRow[];
  total?: number;
  offset?: number;
  limit?: number;
  states?: OfficialState[] | null;
}
export interface OfficialPage {
  offset?: number;
  limit?: number;
  states?: OfficialState[];
}
export interface ItemFilterResponse {
  success: true;
  rule: OfficialFilter | null;
  by: string | null;
  hidden: number;
}

export interface DiscoverPage {
  url: string;
  title: string | null;
  site: string;
  hide_key: string;
  /** A tweet: not saved here (the save path reads x.com's app shell); Collect originals keeps it from the quote. */
  tweet?: boolean;
  video: boolean;
  first_linked_at: string;
  voices: number;
  readable: boolean;
  stories: OriginStory[];
  entity?: { id: string; name: string };
  voice_names?: string[];
  follow_url?: string | null;
}

export interface SourceGives { posts: number; read: number; stories: number; first: number; classics: number; links: number; }
export type AnatomyKind = 'feed' | 'page_watch' | 'site_reader' | 'telegram' | 'x' | 'reddit' | 'youtube' | 'saved';

export interface SourceAnatomyRow {
  source_id: string;
  display_name: string | null;
  address: string;
  platform: string;
  enabled: boolean;
  kind: AnatomyKind;
  full_text: 'on' | 'off' | 'feed';
  /** Its posts left as the feed's summary, by their last page read's outcome → count. Absent from an older API. */
  teasers?: Record<string, number>;
  watch_changes: boolean | null;
  watched_pages: number;
  feed_misses?: number;
  validators: boolean | null;
  status: HealthStatus;
  interval_hours: number;
  interval_basis: IntervalBasis;
  next_due_at: string | null;
  last_attempt_at: string | null;
  last_outcome: OutcomeStatus | null;
  last_error: string | null;
  last_error_at: string | null;
  recent: SourceGives;
  all: SourceGives;
}
export interface SourceAnatomyResponse { success: true; window_days: number; generated_at: string; rows: SourceAnatomyRow[]; }

export interface FeedFinding extends Envelope {
  status?: 'feed' | 'found' | 'direct' | 'none';
  feeds?: FoundFeed[];
  homepage?: boolean;
  pages?: PageOffer[];
  linked?: number;
  start?: string | null;
}

export interface PageWatchPreview extends Envelope {
  prefix?: string;
  found?: number;
  sitemap?: boolean;
  items?: { url: string; title: string; published_at: string | null }[];
}

export interface PageOffer {
  url: string;
  prefix: string;
  found: number;
  sitemap: boolean;
  items: { url: string; title: string; published_at: string | null }[];
  holds?: number;
}

export interface PageSource { id: string; name: string; }

/** POST /api/saved: a page saved, or one already stored. A page of a followed source is looked for under it first:
 *  `fetching` while that source is fetched (`savePage` waits and asks again), then `already` or `saved`. */
export interface SavedPage extends Envelope {
  status?: 'saved' | 'already' | 'fetching';
  post_id?: string;
  title?: string;
  source_id?: string;
  source?: PageSource | null;
  job_id?: string;
  fetched?: boolean;
  readable?: boolean;
  reason?: string | null;
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

/** Wait for an operation job and resolve with its payload. Throws `JobFailedError` (payload in `.value`),
 *  `JobTimeoutError`, an `AbortError`, or the `ApiError` that ended polling. */
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

/** Start an ingestion_run job and resolve with its run report, even when some sources failed (`partial`). */
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
  if (params.allSources) qs.set('all_sources', '1');
  return `/api/feed?${qs.toString()}`;
}

/**
 * The client. Methods throw `ApiError` on any failure, except those wrapped in `settle`, which resolve
 * `{success: false, error}`. Components reach it through `useApi()`, so a test can hand them a fake.
 */
export function createApi() {
  return {
    // ---- Reader ----

    getFeed: (params: FeedParams) => request<FeedPage>(feedPath(params, 'stream'), { signal: params.signal }),
    getFeedGroups: (params: FeedParams) => request<FeedGroupsPage>(feedPath(params, 'by_source'), { signal: params.signal }),
    searchPosts: (params: SearchParams) => request<SearchPage>(searchPath(params), { signal: params.signal }),
    getUnreadCounts: () => request<UnreadCounts>('/api/feed/unread-counts'),
    /** Mark posts (at most 500) read or unread. Marking read takes them out of Later unless `keepLater`. */
    setPostsRead: (ids: string[], read: boolean, { keepLater = false }: { keepLater?: boolean } = {}) =>
      request<ReadStateResult>('/api/feed/read', { method: 'PUT', body: keepLater ? { ids, read, keep_later: true } : { ids, read } }),
    setPostsLater: (ids: string[], later: boolean) =>
      request<ReadStateResult>('/api/feed/later', { method: 'PUT', body: { ids, later } }),
    /** Mark read every unread post in `scope` from `newest` down to `through` (feed cursors), as its list shows them. */
    markReadThrough: (scope: string, through: string, newest: string, allSources = false) =>
      request<ReadStateResult>('/api/feed/read', {
        method: 'PUT',
        body: allSources ? { scope, through_cursor: through, newest_cursor: newest, all_sources: true } : { scope, through_cursor: through, newest_cursor: newest },
      }),
    /** Unlike `togglePostFavorite`, this throws on failure. */
    setPostStarred: (postId: string, starred: boolean) =>
      request<PostInteractionResponse>(`/api/posts/item/${enc(postId)}/favorite`, { method: 'POST', body: { favorited: starred } }),

    // ---- The post page ----

    getPostDetail: (postId: string) => request<PostDetailResponse>(`/api/posts/item/${postId}`),
    getPostConnected: (postId: string, all = false) =>
      request<PostConnected>(`/api/posts/item/${enc(postId)}/connected${all ? '?all=true' : ''}`),
    recordPostOpen: (postId: string, metadata?: Record<string, unknown>) =>
      settle(request<PostInteractionResponse>(`/api/posts/item/${postId}/opened`, { method: 'POST', body: { metadata } })),
    recordPostReadingSession: (postId: string, durationSeconds: number, metadata?: Record<string, unknown>) =>
      settle(request<PostInteractionResponse>(`/api/posts/item/${postId}/reading-session`, { method: 'POST', body: { durationSeconds, metadata } })),
    togglePostFavorite: (postId: string, favorited: boolean) =>
      settle(request<PostInteractionResponse>(`/api/posts/item/${postId}/favorite`, { method: 'POST', body: { favorited } })),
    /** Where a long post was left; `null` clears it (the post was finished). */
    savePostPosition: (postId: string, block: number | null, blocks: number | null) =>
      settle(request<Envelope>(`/api/posts/item/${enc(postId)}/position`, { method: 'PUT', body: { block, blocks } })),
    getYouTubeWatchProgress: (videoId: string) =>
      settle(request<YouTubeWatchProgressResponse>(`/api/youtube/progress/${videoId}`)),
    saveYouTubeWatchProgress: (videoId: string, payload: YouTubeProgressInput) =>
      settle(request<YouTubeWatchProgressResponse>(`/api/youtube/progress/${videoId}`, { method: 'PUT', body: payload })),

    // ---- Sources ----

    getSources: () => request<SourcesResponse>('/api/sources'),
    getSourcesHealth: () => request<SourcesHealthResponse>('/api/sources/health'),
    addSource: (payload: NewSource) => settle(request<AddSourceResponse>('/api/sources', { method: 'POST', body: payload })),
    findFeed: (url: string) => settle(request<FeedFinding>('/api/sources/find-feed', { method: 'POST', body: { url } })),
    /** Save any page. A page of a followed source is looked for there first: that source is fetched
     *  (`onFetching` says which), then the page is its post, or saved as one. */
    savePage: (url: string, title?: string, { onFetching }: { onFetching?: (source: PageSource) => void } = {}) =>
      settle((async () => {
        const body = { url, ...(title ? { title } : {}) };
        const first = await request<SavedPage>('/api/saved', { method: 'POST', body });
        if (first.status !== 'fetching' || !first.job_id) return first;
        if (first.source) onFetching?.(first.source);
        // The fetch's outcome doesn't matter here: found or not, the second answer says.
        await waitForJob<unknown>(first.job_id).catch(() => undefined);
        const after = await request<SavedPage>('/api/saved', { method: 'POST', body: { ...body, after_fetch: true } });
        return { ...after, fetched: true };
      })()),
    pageSource: (url: string) =>
      request<{ success: true; source: PageSource | null }>(`/api/saved/source?url=${enc(url)}`).then((r) => r.source),
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
    /** Point a broken source at its replacement (a feed, or with `pageWatch` a page). Its name, tracks and posts stay. */
    switchSource: (sourceId: string, url: string, pageWatch?: { prefix?: string }) =>
      request<{ success: true; source_id: string; handle_or_url: string; previous: string }>(
        `/api/sources/${enc(sourceId)}/switch`, { method: 'POST', body: { url, ...(pageWatch ? { page_watch: pageWatch } : {}) } },
      ),
    dismissReplacement: (sourceId: string) =>
      request<{ success: true; row: SourceHealthRow }>(`/api/sources/${enc(sourceId)}/replacement/dismiss`, { method: 'POST' }),
    keepSource: (sourceId: string) =>
      request<{ success: true; row: SourceHealthRow }>(`/api/sources/${enc(sourceId)}/tidy/keep`, { method: 'POST' }),
    markSourceStopped: (sourceId: string) =>
      request<{ success: true; row: SourceHealthRow }>(`/api/sources/${enc(sourceId)}/silence/stopped`, { method: 'POST' }),
    getSourceAnatomy: () => request<SourceAnatomyResponse>('/api/sources/anatomy'),
    getSuggestedSources: (page = '', signal?: AbortSignal) =>
      request<SuggestedSourcesResponse>(`/api/sources/suggested${page}`, { signal }),
    getMainSourceMissing: (signal?: AbortSignal) =>
      request<MainSourceResponse>('/api/discover/main-source', { signal }),
    getDiscoverPeople: (signal?: AbortSignal) =>
      request<PeopleResponse>('/api/discover/people', { signal }),
    getOfficial: (signal?: AbortSignal, page: OfficialPage = {}) => {
      const qs = new URLSearchParams();
      if (page.offset) qs.set('offset', String(page.offset));
      if (page.limit) qs.set('limit', String(page.limit));
      if (page.states?.length) qs.set('state', page.states.join(','));
      const query = qs.toString();
      return request<OfficialResponse>(`/api/official${query ? `?${query}` : ''}`, { signal });
    },
    undoOfficial: (id: string) =>
      request<{ success: true; id: string; state: 'undone'; source_id: string | null }>(
        `/api/official/${enc(id)}/undo`, { method: 'POST' }),
    getItemFilter: (sourceId: string, signal?: AbortSignal) =>
      request<ItemFilterResponse>(`/api/sources/${enc(sourceId)}/item-filter`, { signal }),
    setItemFilter: (sourceId: string, rule: OfficialFilter | null) =>
      request<ItemFilterResponse>(`/api/sources/${enc(sourceId)}/item-filter`, { method: 'PUT', body: { rule } }),
    hideSuggestedSource: (key: string) =>
      request<Envelope>('/api/sources/suggested/hide', { method: 'POST', body: { key } }),
    getNews: ({ scope, cursor, signal, mark = 'main', order, unread = false }: { scope: string; cursor?: string | null; signal?: AbortSignal; mark?: NewsMark; order?: NewsOrder; unread?: boolean }) =>
      request<NewsPage>(`/api/news?scope=${enc(scope)}${cursor ? `&cursor=${enc(cursor)}` : ''}${mark === 'ix' ? '&mark=ix' : ''}${order ? `&order=${order}` : ''}${unread ? '&unread=true' : ''}`, { signal }),
    /** Mark every post of every News row of the scope read (Later kept). Its ids undo it. */
    markAllNewsRead: (scope: string, mark: NewsMark = 'main') =>
      request<ReadStateResult>('/api/feed/read', { method: 'PUT', body: mark === 'ix' ? { scope, news: true, mark } : { scope, news: true } }),
    getSince: (signal?: AbortSignal) => request<SinceLooked>('/api/news/since', { signal }),
    lookSince: () => request<{ before: string | null; now: string }>('/api/news/since/look', { method: 'POST' }),
    getClassics: ({ scope, cursor, signal }: { scope: string; cursor?: string | null; signal?: AbortSignal }) =>
      request<ClassicsResponse>(`/api/classics?scope=${enc(scope)}${cursor ? `&cursor=${enc(cursor)}` : ''}`, { signal }),
    hideClassic: (url: string) => request<Envelope>('/api/classics/hide', { method: 'POST', body: { url } }),
    setSourceMainDigest: (sourceId: string, inMainDigest: boolean) =>
      request<{ success: true; source_id: string; in_main_digest: boolean }>(
        `/api/sources/${enc(sourceId)}/main-digest`, { method: 'PUT', body: { in_main_digest: inMainDigest } },
      ),

    // ---- Tracks (folders) ----

    getFolders: () => settle(request<FoldersResponse>('/api/folders')),
    createFolder: (payload: { name: string; description?: string; sort_order?: number }) =>
      settle(request<FolderResponse>('/api/folders', { method: 'POST', body: payload })),
    renameTrack: (folderId: string, name: string) => request<Envelope>(`/api/folders/${enc(folderId)}`, { method: 'PUT', body: { name } }),
    deleteFolder: (folderId: string) => settle(request<Envelope>(`/api/folders/${folderId}`, { method: 'DELETE' })),
    setTrackMainDigest: (folderId: string, inMainDigest: boolean) =>
      request<Envelope>(`/api/folders/${enc(folderId)}/main-digest`, { method: 'PUT', body: { in_main_digest: inMainDigest } }),
    getSourceFolders: (sourceId: string) => settle(request<SourceFoldersResponse>(`/api/sources/${sourceId}/folders`)),
    addSourceToFolder: (folderId: string, sourceId: string) =>
      settle(request<Envelope>(`/api/folders/${folderId}/sources`, { method: 'POST', body: { source_id: sourceId } })),
    removeSourceFromFolder: (folderId: string, sourceId: string) =>
      settle(request<Envelope>(`/api/folders/${folderId}/sources/${sourceId}`, { method: 'DELETE' })),

    // ---- Ingestion ----

    runIngestionCycle: ({ force = false, ...opts }: { force?: boolean } & RunRequestOptions = {}) =>
      runIngestionJob('/api/ingestion/run', { force }, opts),
    fetchSourceNow: (sourceId: string, { limit, ...opts }: { limit?: number } & RunRequestOptions = {}) =>
      runIngestionJob(`/api/sources/${enc(sourceId)}/fetch-now`, limit ? { limit } : {}, opts),
    fetchFolderNow: (folderId: string, { limit, ...opts }: { limit?: number } & RunRequestOptions = {}) =>
      runIngestionJob(`/api/folders/${enc(folderId)}/ingest`, limit ? { limit } : {}, opts),
    getOperationsOverview: () => request<OperationsOverviewResponse>('/api/operations/overview'),
    getRunningJobs: () => request<RunningJobsResponse>('/api/operations/running'),
    getBackgroundWork: () => request<BackgroundWorkResponse>('/api/operations/background'),
    getOperationJob: (jobId: string) => request<OperationJobResponse>(`/api/operations/jobs/${jobId}`),
    getSchedulerConfig: () => request<SchedulerResponse>('/api/operations/scheduler'),
    updateSchedulerConfig: (config: Partial<SchedulerConfig>) => settle(request<SchedulerResponse>('/api/operations/scheduler', {
      method: 'PUT',
      body: {
        intervalHours: config.interval_hours,
        ingestTickMinutes: config.ingest_tick_minutes,
        collectOriginals: config.collect_originals,
        lookupOriginals: config.lookup_originals,
        storeClassics: config.store_classics,
      },
    })),
    getVersion: () => request<BuildVersion>('/api/version'),
    getIngestionLogs: (log = 'application', lines = 200) =>
      request<LogTailResponse>(`/api/ingestion/logs?${new URLSearchParams({ log, lines: String(lines) }).toString()}`),

    // ---- Archive (the source sheet's section and the Ingestion tab) ----

    getArchiveCatalog: () => request<ArchiveCatalogResponse>('/api/archive/catalog'),
    getSourceArchive: (sourceId: string) => request<ArchiveStatusResponse>(`/api/archive/${enc(sourceId)}/status`),
    /** Ask the source how many posts it has and estimate the run. Touches the source, never the posts. */
    planSourceArchive: async (sourceId: string, resume: boolean, pacing?: ArchivePacing): Promise<ArchivePlan> => {
      const response = await request<{ archive?: ArchivePlan }>(
        `/api/archive/${enc(sourceId)}/plan`, { method: 'POST', body: { resume, ...pacing } },
      );
      if (!response.archive) throw new Error('Could not plan the archive');
      return response.archive;
    },
    startSourceArchive: async (sourceId: string, resume: boolean, pacing?: ArchivePacing): Promise<{ job_id: string }> => {
      const response = await request<{ job_id?: string }>(
        `/api/archive/${enc(sourceId)}/run`, { method: 'POST', body: { resume, background: true, ...pacing } },
      );
      if (!response.job_id) throw new Error('Could not start the archive');
      return { job_id: response.job_id };
    },

    getLinkedPages: async (sourceId: string): Promise<LinkedPagesSummary> => {
      const response = await request<{ linked?: LinkedPagesSummary }>(`/api/archive/${enc(sourceId)}/linked`);
      if (!response.linked) throw new Error('Could not count the linked pages');
      return response.linked;
    },
    fetchLinkedPages: async (sourceId: string): Promise<{ job_id: string }> => {
      const response = await request<{ job_id?: string }>(`/api/archive/${enc(sourceId)}/linked`, { method: 'POST' });
      if (!response.job_id) throw new Error('Could not fetch the linked pages');
      return { job_id: response.job_id };
    },

    // ---- Connections: write-only secrets. No call returns a stored value. ----

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
    getMarkxToken: () => request<MarkxTokenView>('/api/markx/token'),
    createMarkxToken: () => request<MarkxTokenCreated>('/api/markx/token', { method: 'POST' }),
    getMarkxOn: () => request<{ on: boolean }>('/api/markx/on'),
    getMarkxNews: (all = false) => request<MarkxNews>(`/api/markx/news?all=${all ? 1 : 0}`),
    getMarkxPost: (postId: string) => request<MarkxPostPanel>(`/api/markx/posts/${enc(postId)}`),
    /** Related reading, on request (~1.5 s: a scan of every stored vector). */
    getMarkxRelated: (postId: string) => request<MarkxRelated>(`/api/markx/posts/${enc(postId)}/related`),
    // v10.42: the reader's interest: one tap (kept; News orders by it at once), and a post page's teach panel
    teachInterest: (body: { dim: InterestDim; key: string; answer: InterestAnswer; name?: string | null; row?: string | null; post?: string | null }) =>
      request<{ id: string; dim: InterestDim; key: string; answer: InterestAnswer }>('/api/markx/interests', { method: 'POST', body }),
    getPostInterest: (postId: string) => request<PostInterest>(`/api/markx/posts/${enc(postId)}/interest`),
    getMarkxOverview: () => request<MarkxOverview>('/api/markx/overview'),
    runMarkxDecisions: () => request<Record<string, unknown>>('/api/markx/decide', { method: 'POST' }),
    /** The reading window: days, or null for every post; counts from the next planner run. */
    setMarkxReadingWindow: (days: number | null) =>
      request<MarkxSettings>('/api/markx/settings/reading-window', { method: 'POST', body: { days } }),
    flagMarkxMember: (post: string, story: string, answer: MarkxFlag) =>
      request<{ id: string; post: string; story: string; answer: MarkxFlag }>('/api/markx/labels/news',
        { method: 'POST', body: { post, story, answer } }),
    answerMarkxFold: (story: string, post: string, answer: MarkxFoldAnswer) =>
      request<{ story: string; post: string } & Partial<MarkxFold>>('/api/markx/folds/answer',
        { method: 'POST', body: { story, post, answer } }),
    // entities and the review queue: each answer applied at once and stored as a label
    getMarkxEntities: () => request<MarkxEntityList>('/api/markx/entities'),
    /** `byLimit`: by posts listed loose; `replies`: replies to its handles too; `limits`: stories and loose posts
     *  listed; `whole`: every post, citing work and timeline event. */
    getMarkxEntity: (id: string, byLimit?: number, replies?: boolean, limits?: MarkxEntityLimits, whole?: boolean) => {
      const q = [byLimit !== undefined ? `by_limit=${byLimit}` : '', replies ? 'replies=true' : '',
        limits?.stories !== undefined ? `stories_limit=${limits.stories}` : '',
        limits?.loose !== undefined ? `loose_limit=${limits.loose}` : '',
        whole ? 'all=true' : ''].filter(Boolean).join('&');
      return request<MarkxEntityPage>(`/api/markx/entities/${enc(id)}${q ? `?${q}` : ''}`);
    },
    /** The first `limit` open items; next_offset says more are open. `view`: flagged (default) or all. */
    getMarkxEntityQueue: (limit?: number, view?: MarkxQueueView) => {
      const q = [limit !== undefined ? `limit=${limit}` : '', view ? `view=${view}` : ''].filter(Boolean).join('&');
      return request<MarkxEntityQueue>(`/api/markx/entities/queue${q ? `?${q}` : ''}`);
    },
    answerMarkxEntity: (item: string, answer: MarkxEntityAnswer) =>
      request<Record<string, unknown>>(`/api/markx/entities/queue/${enc(item)}`, { method: 'POST', body: { answer } }),
    undoMarkxMerge: (redirect: string) =>
      request<Record<string, unknown>>(`/api/markx/entities/merges/${enc(redirect)}/undo`, { method: 'POST', body: {} }),
    getMarkxStory: (id: string) => request<MarkxStoryView>(`/api/markx/stories/${enc(id)}`),
    labelMarkxPerspective: (story: string, post: string, answer: MarkxPerspectiveAnswer) =>
      request<{ id: string; answer: MarkxPerspectiveAnswer; shown: string }>('/api/markx/labels/perspective',
        { method: 'POST', body: { story, post, answer } }),
    labelMarkxFact: (story: string, post: string, index: number, answer: MarkxFactAnswer) =>
      request<{ id: string; answer: MarkxFactAnswer }>('/api/markx/labels/fact',
        { method: 'POST', body: { story, post, index, answer } }),
    getMarkxPerspectiveAccuracy: () => request<MarkxPerspectiveAccuracy>('/api/markx/labels/perspectives'),

    // ---- Data: the export downloads as a link; these read around it ----

    getExportInfo: () => request<ExportInfo>('/api/export'),
    getExportProgress: (token: string) => request<ExportProgress>(`/api/export/progress/${enc(token)}`),
  };
}

export interface ExportInfo {
  database_bytes: number;
  estimate_bytes: number;
  estimate_seconds: number;
  tables: number;
  login_tables: string[];
  logins_include: string;
  estimate_basis?: 'last_export' | 'live_rows';
  last_export?: ExportRecord | null;
}

export interface ExportRecord {
  bytes: number;
  seconds: number;
  at: string;
  logins_included: boolean;
}

export interface ExportProgress {
  file_name: string;
  bytes: number;
  done: boolean;
  error: string | null;
}

export type Api = ReturnType<typeof createApi>;

// How a Mark X story is built: `built` on each Mark X News row and the story view; each News line has its role.
export type MarkxOriginalHow = 'links' | 'maker' | 'maker-page' | 'maker-link';
export interface MarkxBuiltLeak {
  post: string;
  hours: number;
  joins: boolean;
  own_coverage: boolean;
}
export interface MarkxBuiltLink {
  story: string;
  headline: string;
  hours: number;
  joins: boolean;
  via: 'connection' | 'subject';
}
export interface MarkxBuilt {
  code: string;
  event_type: string | null;
  read: { read: number; members: number };
  original: { post: string; how: MarkxOriginalHow } | null;
  source_page: string | null;
  order?: string[];
  release_at: string | null;
  leaks: MarkxBuiltLeak[];
  came_true: MarkxBuiltLink[];
  leaked_before: (MarkxBuiltLink & { posts: string[] })[];
  disputes?: MarkxDispute[];
}
export interface MarkxDispute {
  fact: string;
  kind: 'number' | 'date' | 'status' | 'cause' | 'attribution' | 'other';
  sides: { says: string; claimed: boolean; by: { post: string; source: string | null; quote: string; claim: boolean }[] }[];
}
export type MarkxBuiltLine =
  | { role: 'original'; how: MarkxOriginalHow }
  | { role: 'leak'; hours: number; joins: boolean; own_coverage: boolean };

/** One row of a post's Connected block: a stored post (Earlier, Later) or an outside page (no post_id; its host
 *  and link words as `title`). `reason`: the line the author gave for it. */
export interface ConnectedRow {
  post_id: string | null;
  url: string;
  address?: string;
  host?: string;
  source: string | null;
  byline?: Byline | null;
  source_id?: string;
  date: string | null;
  title: string | null;
  same_source: boolean;
  reason: string | null;
  reason_kind: 'quote' | 'sentence' | 'title' | 'link_words' | null;
}

export interface PostConnected extends Envelope {
  earlier: ConnectedRow[];
  later: ConnectedRow[];
  outside: ConnectedRow[];
  more: { earlier: number; later: number; outside: number };
}

// A post's translation (Mark X). Outside createApi: components read it through `markxTranslationApi(useApi())`, so
// a test's fake api can provide these methods.
export interface MarkxTranslationView {
  post_id: string;
  lang: string | null;
  foreign: boolean;
  task: { id: string; status: 'open' | 'leased' | 'answered' | 'failed'; guide: string; error: string | null } | null;
  translation: { title_en: string; text_en: string; guide: string; model: string; at: string } | null;
  label: 'right' | 'wrong' | null;
}
export type MarkxTranslationAnswer = 'right' | 'wrong' | 'undo';
const markxTranslationMethods = {
  getMarkxTranslation: (postId: string) =>
    request<MarkxTranslationView>(`/api/markx/posts/${enc(postId)}/translation`),
  askMarkxTranslation: (postId: string) =>
    request<{ task_id: string; new: boolean; view: MarkxTranslationView }>(`/api/markx/posts/${enc(postId)}/translate`,
      { method: 'POST' }),
  labelMarkxTranslation: (postId: string, answer: MarkxTranslationAnswer) =>
    request<MarkxTranslationView>(`/api/markx/posts/${enc(postId)}/translation/label`, { method: 'POST', body: { answer } }),
};
export type MarkxTranslationApi = typeof markxTranslationMethods;
/** These methods from `api` when it answers them (a test's fake), else the real client's. */
export function markxTranslationApi(api: object): MarkxTranslationApi {
  const own = api as Partial<MarkxTranslationApi>;
  const pick = <K extends keyof MarkxTranslationApi>(k: K): MarkxTranslationApi[K] => {
    const got = own[k];
    return typeof got === 'function' ? (got as MarkxTranslationApi[K]) : markxTranslationMethods[k];
  };
  return { getMarkxTranslation: pick('getMarkxTranslation'), askMarkxTranslation: pick('askMarkxTranslation'),
    labelMarkxTranslation: pick('labelMarkxTranslation') };
}

// Archives that work again, archives back to a date, and the archive queue.
export interface ArchiveUnreached {
  stored?: number;
  no_post?: number;
  unreadable?: number;
  updated?: number;
}
export interface ArchiveResultExtra {
  unreached?: ArchiveUnreached;
  until?: string;
  until_reached?: string;
  layout_changed?: boolean;
  queued_at?: string;
}
export interface ArchiveSupport {
  until?: boolean;
}
export interface ArchiveCatalogResponse {
  interrupted?: string[];
  queued?: Array<{ id: string; source_id: string; lane: string | null; queued_at: string | null }>;
}
export interface ArchiveStarted {
  job_id: string;
  status: 'running' | 'queued';
  message?: string;
}

const archivePath = (sourceId: string, what: string) => `/api/archive/${encodeURIComponent(sourceId)}/${what}`;

/** The archive queue's calls, beside createApi's: start (or queue) an archive back to a date, queue one, and
 *  resume every interrupted archive. */
export const archiveQueueApi = {
  startArchive: async (sourceId: string, resume: boolean, until?: string | null, pacing?: ArchivePacing): Promise<ArchiveStarted> => {
    const response = await request<{ job_id?: string; status?: string; message?: string }>(archivePath(sourceId, 'run'), {
      method: 'POST', body: { resume, background: true, ...(until ? { until } : {}), ...pacing },
    });
    if (!response.job_id) throw new Error('Could not start the archive');
    return { job_id: response.job_id, status: response.status === 'queued' ? 'queued' : 'running', message: response.message };
  },
  queueArchive: async (sourceId: string, resume: boolean, until?: string | null): Promise<ArchiveStarted> => {
    const response = await request<{ job_id?: string; message?: string }>(archivePath(sourceId, 'queue'), {
      method: 'POST', body: { resume, ...(until ? { until } : {}) },
    });
    if (!response.job_id) throw new Error('Could not queue the archive');
    return { job_id: response.job_id, status: 'queued', message: response.message };
  },
  stopArchive: async (sourceId: string): Promise<void> => {
    await request<{ stopping?: boolean }>(archivePath(sourceId, 'stop'), { method: 'POST', body: {} });
  },
  resumeInterrupted: async (): Promise<{ count: number }> => {
    const response = await request<{ count?: number }>('/api/archive/resume-interrupted', { method: 'POST', body: {} });
    return { count: response.count ?? 0 };
  },
};

// The owner's right / wrong on an edge of the Mark X post panel's Before list.
export type MarkxEdgeAnswer = 'right' | 'wrong' | 'undo';
export const markxGraphApi = {
  labelEdge: (newer: string, older: string, answer: MarkxEdgeAnswer) =>
    request<{ id: string; answer: MarkxEdgeAnswer; label: 'right' | 'wrong' | null; relation: string }>(
      '/api/markx/labels/edge', { method: 'POST', body: { newer, older, answer } }),
};

// The source analysis page (/markx/sources), outside createApi: read through `markxSourcesApi(useApi())` for test fakes.
export interface MarkxSourceCell {
  value: unknown;
  n: number;
  too_few: boolean;
}
export interface MarkxSourceRow {
  kind: 'source' | 'voice';
  id: string;
  name: string;
  platform: string;
  enabled: boolean;
  channels: number;
  stats: Partial<Record<string, MarkxSourceCell>>;
  switch_off?: MarkxSwitchOff | null;
}
export interface MarkxSwitchOff {
  line: string;
  noise: number;
  posts: number;
  opened: number | null;
  cited_by: number;
}
export interface MarkxSourcesList {
  rows: MarkxSourceRow[];
  columns: string[];
  formulas: Record<string, string>;
  computed_at: string | null;
  job: { ok?: boolean; seconds?: number; peak_mb?: number; rows?: number; at?: string; error?: string } | null;
}
export interface MarkxEvidencePost {
  id: string;
  title: string;
  at: string | null;
  source: string | null;
  [extra: string]: unknown;
}
export interface MarkxSourceSignal {
  signal: string;
  value: unknown;
  n: number;
  min: number;
  counts: string;
  too_few: boolean;
  formula: string;
  evidence: Record<string, unknown>;
}
export interface MarkxSourceCard {
  card: string;
  title: string;
  experimental: boolean;
  signals: MarkxSourceSignal[];
}
export interface MarkxSourceTab {
  kind: 'source' | 'voice';
  id: string;
  name: string;
  platform: string;
  computed: boolean;
  cards: MarkxSourceCard[];
  switch_off?: MarkxSwitchOff | null;
}
export interface MarkxSourcePage {
  subject: { kind: 'source' | 'voice'; id: string; name: string; voice: { id: string; name: string | null } | null };
  tabs: MarkxSourceTab[];
  computed_at: string | null;
}
export type MarkxStanceAnswer = 'right' | 'wrong' | 'undo';
const markxSourcesMethods = {
  getMarkxSources: () => request<MarkxSourcesList>('/api/markx/sources'),
  getMarkxSource: (id: string) => request<MarkxSourcePage>(`/api/markx/sources/${enc(id)}`),
  labelMarkxStance: (task: string, pattern: number, answer: MarkxStanceAnswer) =>
    request<{ labels: Record<string, 'right' | 'wrong'> }>('/api/markx/sources/stance/label',
      { method: 'POST', body: { task, pattern, answer } }),
};
export type MarkxSourcesApi = typeof markxSourcesMethods;
/** These methods from `api` when it answers them (a test's fake), else the real client's. */
export function markxSourcesApi(api: object): MarkxSourcesApi {
  const own = api as Partial<MarkxSourcesApi>;
  const pick = <K extends keyof MarkxSourcesApi>(k: K): MarkxSourcesApi[K] => {
    const got = own[k];
    return typeof got === 'function' ? (got as MarkxSourcesApi[K]) : markxSourcesMethods[k];
  };
  return { getMarkxSources: pick('getMarkxSources'), getMarkxSource: pick('getMarkxSource'),
    labelMarkxStance: pick('labelMarkxStance') };
}

// Voices: one company, person or publication made of its channels (today's sources), joined only by you.

/** One line of a suggestion's evidence: which rule, what it saw, up to 3 example posts. */
export interface VoiceEvidence { rule: string; line: string; posts: string[]; }
export interface VoiceChannel {
  id: string; name: string; platform: string; kind: string; enabled: boolean; in_main_digest: boolean;
  priority: number; posts: number; last_post_at: string | null;
}
export interface Voice {
  id: string; name: string; kind: 'company' | 'person' | 'publication' | null; entity_id: string | null;
  created_at: string; confirmed_at: string | null; channels: VoiceChannel[];
  related: { id: string; name: string; evidence: VoiceEvidence[] }[];
  /** Any channel's: the voice shows the highest (priority: the lowest number). */
  in_main_digest: boolean; priority: number;
}
export interface VoiceSource { id: string; name: string; kind: string; posts: number; enabled: boolean; voice_id: string | null; }
export interface VoiceSuggestion {
  key: string; sources: VoiceSource[]; voice_ids: string[]; same_channel: boolean;
  edges: { a: string; b: string; verdict: 'same_channel' | 'join'; evidence: VoiceEvidence[] }[];
}
export interface VoicePair { a: VoiceSource; b: VoiceSource; evidence: VoiceEvidence[]; names?: string[]; }
export interface VoiceSuggestions {
  success: true; computed_at: string | null; computing: boolean;
  voices: VoiceSuggestion[]; possible: VoicePair[]; related: VoicePair[];
}
/** "Also on <channel>": the same voice's other channel's post, a line under the earliest (within 72 hours). */
export interface AlsoOnLine {
  id: string; source_id: string; source_display_name: string; platform: string; title: string | null; url: string | null;
  sort_at: string; why: 'links' | 'copy';
}
export interface FeedItem {
  /** One post on two channels of a voice shows once; the others are lines under it. */
  also_on?: AlsoOnLine[];
}
// The voices' calls are services/voices.ts (voicesApi): loaded only by the voice pages' own chunks.

/** A part of a post's series: a stored post, its number as its title writes it ("3", "32a"). */
export interface SeriesPart {
  post_id: string; number: string | null; position: number; title: string | null; date: string | null; current: boolean;
}
/** The post's Series line: "Part 3 of 4 in <name>" (a series) or "Issue #136 of <name>" (a column: previous and next only). */
export interface PostSeries {
  id: string; kind: 'series' | 'column'; name: string; number: string | null; position: number; count: number;
  total: number; parts: SeriesPart[]; prev: SeriesPart | null; next: SeriesPart | null;
}
/** Connected with the series line and the same-source links that are series navigation. Older servers send neither. */
export type PostConnectedSeries = PostConnected & {
  series?: PostSeries | null;
  navigation?: (ConnectedRow & { group: 'earlier' | 'later' })[];
};

// The finder's saved searches and refusals, and the Telegram bridge the Add-source dialog builds on.
export interface FoundFeed { /** It reads as a saved search ("Keyword search for query", ?q=): ranked last. */ saved_search?: boolean }
export interface FeedFinding { /** A feed was found whose items INSIGHT cannot read: never offered. */ refused?: string }
/** The bridge's origin ("https://telegram.local"), or null when none is set (TELEGRAM_RSS_HOSTS empty). */
export const telegramBridge = async (): Promise<string | null> =>
  (await request<{ bridge?: string | null }>('/api/sources/telegram-bridge')).bridge ?? null;

// Back in the news on /markx: the old stories judged back with a development, and the owner's label on each.
export type MarkxBackLabel = 'development' | 'retold' | 'related' | 'unrelated';
export interface MarkxBackPost {
  id: string; n: number; title: string | null; source: string | null; byline?: Byline | null; at: string | null; url: string | null;
  trig: string[]; verdict: MarkxBackLabel | null; about: string | null;
}
export interface MarkxBackRow {
  id: string; story: string; headline: string | null; first_at: string; window_at: string; days_later: number;
  trig: string[]; posts: MarkxBackPost[]; old_thing: string | null; what_new: string[]; runs: (string | null)[];
  label: MarkxBackLabel | null;
}
export interface MarkxBackPrecision { labelled: number; development: number; precision: number | null; }
export interface MarkxBack {
  /** Its feature's switch (markx/consumers.py `back`): off, nothing is shown. */
  on: boolean;
  items: MarkxBackRow[]; counts: Record<string, number>; precision: MarkxBackPrecision | null;
  measured: { precision: number; lo: number; hi: number; n: number; words: string };
}
export const markxBackApi = {
  list: () => request<MarkxBack>('/api/markx/back'),
  label: (row: string, answer: MarkxBackLabel | 'undo') =>
    request<{ id: string; answer: string; label: MarkxBackLabel | null; precision: MarkxBackPrecision }>(
      '/api/markx/labels/back', { method: 'POST', body: { row, answer } }),
};

// Own round-ups. A round-up's item is display only: never a voice, a member or a News count.
export interface MarkxRoundupItem {
  key: string; kind: 'mx_story' | 'ix_story' | 'post' | 'page' | 'unit'; ref: string | null; headline: string | null;
  curators: number; issues: number; only_roundups: boolean; at: string; posts: string[];
  units: { unit: number; post: string; n: number; item: string; source: string | null; title: string | null }[];
}
export interface MarkxRoundupIssue {
  id: number; span: 'day' | 'week'; from: string; until: string; version: number; built_at: string;
  roundups: number; units: number; count: number; items?: MarkxRoundupItem[];
  /** The items left out as no news ({type: n}, `continues`), still untyped, and over the per-source cap. */
  left_out?: Record<string, number>; untyped?: number; capped?: number;
}
export interface MarkxRoundupIssues {
  daily: MarkxRoundupIssue | null; weekly: MarkxRoundupIssue | null; past: MarkxRoundupIssue[]; tz_offset_minutes: number;
}
export const markxRoundupApi = {
  issues: () => request<MarkxRoundupIssues>('/api/markx/roundups/issues'),
  issue: (id: number) => request<MarkxRoundupIssue>(`/api/markx/roundups/issues/${id}`),
};

// Channel profiles and the channels you don't follow (declaration merging adds the suggestions' fields).
export interface NotFollowedChannel {
  key: string; url: string; label: string; platform: string; of: string[]; hosts?: number;
  why: { rule: 'profile' | 'own_links' | 'discover'; line: string; posts: string[] }[];
}
export interface NotFollowedGroup { subject: { kind: 'voice' | 'source'; id: string; name: string }; channels: NotFollowedChannel[] }
export interface VoiceSuggestions { not_followed?: NotFollowedGroup[]; profiles?: number }

// A full text's reference list (post_links kind 'reference'), shown folded in Connected. Older servers send none.
export interface ConnectedReference { url: string; address: string; host: string; title: string | null }
export type PostConnectedReferences = PostConnected & { references?: ConnectedReference[] };

// The finder says why none, when only a saved search was found, and which feeds are the site's, not this page's.
export interface FoundFeed { /** The site's feed, not this page's. */ not_this_page?: 'other_scope' | 'stale' }
export interface FeedFinding {
  /** Why none: blocked, rate-limited, needs login, gone, server error, empty feed, no bridge, none found. */
  reason?: string;
  note?: string;
  /** Every feed found is the site's, not this page's: the page itself to follow, with its preview. */
  watch?: PageOffer;
}
