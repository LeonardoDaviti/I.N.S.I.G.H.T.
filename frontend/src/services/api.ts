// API service for INSIGHT backend communication
// Use relative base by default (Vite dev proxy will forward /api to backend). Override with VITE_API_URL in production.
const API_BASE_URL = (import.meta as any).env?.VITE_API_URL || '';
import type { SourceConfig } from '../types';

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


export interface BriefingRequest {
  date: string; // Format: "YYYY-MM-DD"
}

export interface BriefingHighlight {
  id?: string;
  post_id?: string;
  highlight_text?: string;
  highlight_kind?: string;
  start_char?: number | null;
  end_char?: number | null;
  language_code?: string | null;
  importance_score?: number;
  commentary?: string | null;
  extractor_name?: string | null;
  extractor_version?: string | null;
  created_at?: string | null;
}

export interface BriefingReference {
  id?: string;
  artifact_type?: string;
  artifact_id?: string;
  post_id?: string;
  highlight_id?: string | null;
  reference_role?: string;
  display_label?: string | null;
  order_index?: number;
  created_at?: string | null;
  post?: Post | null;
  highlight?: BriefingHighlight | null;
}

export interface BriefingResponse {
  success: boolean;
  briefing?: string; // AI-generated briefing content
  date?: string;
  posts_processed?: number;
  total_posts_fetched?: number;
  posts?: Post[]; // Array of individual source posts
  format?: string;
  saved_briefing_id?: string | null;
  cached?: boolean;
  estimated_tokens?: number;
  one_sentence_takeaway?: string | null;
  references?: BriefingReference[];
  error?: string;
}

export interface WeeklyBriefingResponse {
  success: boolean;
  briefing?: string;
  format?: string;
  saved_briefing_id?: string | null;
  cached?: boolean;
  date?: string;
  week_start?: string | null;
  week_end?: string | null;
  subject_key?: string | null;
  daily_briefings_used?: number;
  days_covered?: string[];
  estimated_tokens?: number;
  one_sentence_takeaway?: string | null;
  topics?: Topic[];
  posts?: Record<string, Post>;
  references?: BriefingReference[];
  variant?: string;
  error?: string;
}

export interface WeeklyTopicTimelineEntry {
  date?: string | null;
  summary?: string | null;
  source_topics?: string[];
  post_ids?: string[];
}

export interface Topic {
  id: string;
  title: string;
  summary: string | null;
  post_ids?: string[]; // For AI-generated topics (legacy)
  posts?: Post[]; // For database topics
  timeline?: WeeklyTopicTimelineEntry[];
  is_outlier?: boolean;
  created_at?: string;
  post_count?: number;
}

export interface BriefingTopicsResponse {
  success: boolean;
  briefing?: string;
  date?: string;
  posts_processed?: number;
  total_posts_fetched?: number;
  enhanced?: boolean;
  cached?: boolean;
  topics?: Topic[];
  // posts map keyed by database post UUID
  posts?: Record<string, Post>;
  // list of database post UUIDs not referenced by any named topic
  unreferenced_posts?: string[];
  one_sentence_takeaway?: string | null;
  references?: BriefingReference[];
  error?: string;
}

export interface TopicsResponse {
  success: boolean;
  topics: Topic[];
  date: string;
  total: number;
  message?: string;
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
  topics?: Array<{ id: string; title: string; date?: string | null }>;
}

export interface PostHighlight {
  id?: string;
  post_id?: string;
  highlight_text: string;
  highlight_kind?: string;
  start_char?: number | null;
  end_char?: number | null;
  language_code?: string | null;
  importance_score?: number;
  commentary?: string | null;
  extractor_name?: string | null;
  extractor_version?: string | null;
  created_at?: string | null;
}

export interface ReaderState {
  post_id?: string;
  is_favorited?: boolean;
  open_count?: number;
  first_opened_at?: string | null;
  last_opened_at?: string | null;
  total_read_seconds?: number;
}

export interface SourceStats {
  success: boolean;
  data?: Record<string, any>;
  error?: string;
}

export interface ArchiveResponse {
  success?: boolean;
  error?: string;
  [key: string]: any;
}

export interface ArchiveCatalogEntry {
  source_id: string;
  display_name: string;
  platform: string;
  enabled: boolean;
  stored_posts: number;
  available_posts?: number | null;
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

export interface LiveFetchResponse {
  success?: boolean;
  error?: string;
  source_id?: string;
  source?: {
    display_name?: string;
    platform?: string;
    handle_or_url?: string;
  };
  fetched_limit?: number;
  posts_fetched?: number;
  posts_inserted?: number;
  posts_updated?: number;
  stored_posts?: number;
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

export interface SchedulerConfig {
  interval_hours: number;
  sync_sources_each_cycle: boolean;
  generate_daily_briefing: boolean;
  generate_topic_briefing: boolean;
  updated_at?: string | null;
}

export interface JobRun {
  id: string;
  job_type: string;
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

export interface SourceHealthRow {
  source_id: string;
  display_name: string;
  platform: string;
  enabled: boolean;
  stored_posts: number;
  archive_status?: string | null;
  status: string;
  last_checked_at?: string | null;
  last_success_at?: string | null;
  last_error_at?: string | null;
  last_message?: string | null;
}

export interface OperationsOverviewResponse {
  success?: boolean;
  error?: string;
  scheduler?: SchedulerConfig;
  jobs?: JobRun[];
  source_health?: SourceHealthRow[];
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

interface AcceptedJobResponse {
  success?: boolean;
  accepted?: boolean;
  job_id?: string;
  job_type?: string;
  status?: string;
  message?: string;
}

export interface PostNotesPayload {
  post_id: string;
  notes_markdown: string;
  updated_at?: string | null;
}

export interface PostDetailResponse {
  success?: boolean;
  error?: string;
  post?: Post | null;
  notes?: PostNotesPayload;
  summary?: PostSummaryResponse | null;
  summary_references?: BriefingReference[];
  highlights?: PostHighlight[];
  reader_state?: ReaderState | null;
}

export interface PostSummaryResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
  summary_markdown?: string;
  model?: string;
  updated_at?: string | null;
  cached?: boolean;
  categories?: string[];
  estimated_tokens?: number;
  one_sentence_takeaway?: string | null;
  highlights?: PostHighlight[];
  references?: BriefingReference[];
}

export interface PostHighlightsResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
  highlights?: PostHighlight[];
  one_sentence_takeaway?: string | null;
  cached?: boolean;
  model?: string | null;
}

export interface PostReaderStateResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
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

export interface PostChatResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
  answer?: string;
  source?: string;
  estimated_tokens?: number;
  context?: Record<string, any>;
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

export interface RedditCommentsBriefingResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
  summary_markdown?: string;
  model?: string | null;
  signals?: string[];
  updated_at?: string | null;
  comment_count?: number;
  cached?: boolean;
  estimated_tokens?: number;
}

export interface EvidenceArtifact {
  id: string;
  artifact_type: string;
  canonical_url: string;
  normalized_url: string;
  url_host?: string | null;
  display_title?: string | null;
  status?: string;
  metadata?: Record<string, any>;
  relation_type?: string;
  confidence?: number;
  is_primary?: boolean;
  link_metadata?: Record<string, any>;
  created_at?: string | null;
}

export interface EvidenceRelation {
  from_post_id?: string;
  to_post_id?: string;
  relation_type: string;
  method?: string;
  confidence?: number;
  metadata?: Record<string, any>;
  created_at?: string | null;
}

export interface EvidenceDebug {
  post?: Record<string, any>;
  artifacts?: EvidenceArtifact[];
  relations?: {
    outgoing?: EvidenceRelation[];
    incoming?: EvidenceRelation[];
  };
}

export interface MemoryMentionCandidate {
  mention_id: string;
  entity_id: string;
  candidate_method: string;
  score: number;
  selected: boolean;
  resolver_version: string;
  created_at?: string | null;
  mention_text?: string | null;
  normalized_mention?: string | null;
  entity_type?: string | null;
  canonical_name?: string | null;
  normalized_name?: string | null;
}

export interface MemoryMention {
  id: string;
  post_id: string;
  mention_text: string;
  normalized_mention: string;
  language_code?: string | null;
  entity_type_predicted: string;
  role?: string | null;
  char_start?: number | null;
  char_end?: number | null;
  extractor_confidence?: number;
  extractor_name?: string | null;
  extractor_version?: string | null;
  metadata?: Record<string, any>;
  created_at?: string | null;
  candidates?: MemoryMentionCandidate[];
}

export interface MemoryEntity {
  post_id: string;
  entity_id: string;
  mention_id: string;
  resolution_status: string;
  confidence: number;
  role?: string | null;
  metadata?: Record<string, any>;
  created_at?: string | null;
  entity: {
    id: string;
    entity_type: string;
    canonical_name: string;
    canonical_name_pivot?: string | null;
    normalized_name: string;
    description?: string | null;
    status?: string;
    review_state?: string;
    first_seen_at?: string | null;
    last_seen_at?: string | null;
  };
  mention: {
    id: string;
    mention_text: string;
    normalized_mention: string;
    entity_type_predicted: string;
  };
}

export interface MemorySourceProfile {
  source_id: string;
  language_code?: string | null;
  publisher_type?: string | null;
  country_code?: string | null;
  is_primary_reporter?: boolean;
  reliability_notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MemoryDebug {
  post?: Record<string, any>;
  source_profile?: MemorySourceProfile;
  mentions?: MemoryMention[];
  entities?: MemoryEntity[];
  candidates?: MemoryMentionCandidate[];
}

export interface EventEvidence {
  event_id: string;
  event: {
    id: string;
    event_type: string;
    title: string;
    normalized_event_key?: string | null;
    status?: string;
    confidence?: number;
    occurred_at?: string | null;
    first_seen_at?: string | null;
    last_seen_at?: string | null;
  };
  stance: string;
  evidence_snippet?: string | null;
  confidence?: number;
  extractor_version?: string | null;
  created_at?: string | null;
}

export interface EventEntityLink {
  event_id: string;
  entity_id: string;
  role?: string | null;
  created_at?: string | null;
  event: {
    id: string;
    event_type: string;
    title: string;
    normalized_event_key?: string | null;
  };
  entity: {
    id: string;
    entity_type: string;
    canonical_name: string;
    normalized_name: string;
    review_state?: string;
  };
}

export interface EventDebug {
  post?: Record<string, any>;
  events?: Array<EventEvidence["event"] & { evidence?: EventEvidence[]; entities?: EventEntityLink[] }>;
  evidence?: EventEvidence[];
  entities?: EventEntityLink[];
}

export interface StoryAnchorPost {
  id: string;
  url?: string | null;
  title?: string | null;
  published_at?: string | null;
  source_id?: string | null;
  platform?: string | null;
  handle_or_url?: string | null;
  normalized_url?: string | null;
  canonical_url?: string | null;
  url_host?: string | null;
}

export interface StoryCard {
  id: string;
  canonical_title: string;
  canonical_summary?: string | null;
  story_kind?: string;
  status?: string;
  anchor_post_id?: string | null;
  anchor_confidence?: number;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  created_by_method?: string | null;
  resolution_version?: string | null;
  metadata?: Record<string, any>;
  created_at?: string | null;
  updated_at?: string | null;
  post_count?: number;
  update_count?: number;
  anchor_post?: StoryAnchorPost | null;
  role?: string;
  relevance_score?: number;
  anchor_score?: number;
  is_anchor_candidate?: boolean;
  evidence_weight?: number;
  added_by_method?: string | null;
  added_at?: string | null;
  story_post_metadata?: Record<string, any>;
}

export interface StoryPostEntry {
  story_id: string;
  post_id: string;
  role?: string | null;
  relevance_score?: number;
  anchor_score?: number;
  is_anchor_candidate?: boolean;
  evidence_weight?: number;
  added_by_method?: string | null;
  added_at?: string | null;
  metadata?: Record<string, any>;
  post: Post;
}

export interface StoryUpdatePostEntry {
  story_update_id: string;
  post_id: string;
  role?: string | null;
  created_at?: string | null;
  post: Post;
}

export interface StoryUpdateEntry {
  id: string;
  story_id: string;
  update_date?: string | null;
  title: string;
  summary: string;
  importance_score?: number;
  created_by_method?: string | null;
  metadata?: Record<string, any>;
  created_at?: string | null;
  updated_at?: string | null;
  post_count?: number;
  posts?: StoryUpdatePostEntry[];
}

export interface StoryDetail extends StoryCard {
  posts?: StoryPostEntry[];
  posts_by_role?: Record<string, StoryPostEntry[]>;
  updates?: StoryUpdateEntry[];
  timeline?: StoryUpdateEntry[];
}

export interface StoryTimelineResponse {
  story_id: string;
  story?: StoryCard;
  timeline?: StoryUpdateEntry[];
}

export interface StoryCandidateLink {
  id: string;
  source_post_id: string;
  candidate_post_id: string;
  candidate_story_id?: string | null;
  retrieval_method: string;
  retrieval_score: number;
  decision_status: string;
  decision_reason?: string | null;
  metadata?: Record<string, any>;
  created_at?: string | null;
  updated_at?: string | null;
  candidate_post?: Post | null;
  candidate_story?: Pick<StoryCard, 'id' | 'canonical_title' | 'story_kind' | 'status'> | null;
}

export interface PostTimelineView {
  grouped_dates?: string[];
  current_update?: StoryUpdateEntry | null;
  earlier_updates?: StoryUpdateEntry[];
  later_updates?: StoryUpdateEntry[];
  total_updates?: number;
}

export interface PostTimelineResponse {
  success?: boolean;
  error?: string;
  post_id?: string;
  post?: Post | null;
  has_story?: boolean;
  primary_story?: StoryCard | null;
  story?: StoryDetail | null;
  timeline?: PostTimelineView | null;
  related_candidates?: StoryCandidateLink[];
  refreshed?: boolean;
}

export interface InboxBatch {
  id: string;
  scope_type: string;
  scope_value?: string | null;
  generated_for_date?: string | null;
  status?: string;
  item_count?: number;
  metadata?: Record<string, any>;
  created_at?: string | null;
  updated_at?: string | null;
  pending_count?: number;
  acted_count?: number;
}

export interface InboxItem {
  id: string;
  batch_id: string;
  batch_scope_type?: string;
  batch_scope_value?: string | null;
  batch_generated_for_date?: string | null;
  batch_status?: string;
  batch_item_count?: number;
  batch_metadata?: Record<string, any>;
  batch_created_at?: string | null;
  batch_updated_at?: string | null;
  target_type: string;
  target_id: string;
  status: string;
  priority_score?: number;
  novelty_score?: number;
  evidence_score?: number;
  duplication_penalty?: number;
  source_priority_score?: number;
  reason_summary?: string | null;
  reasons?: Array<Record<string, any>>;
  surfaced_at?: string | null;
  acted_at?: string | null;
  metadata?: Record<string, any>;
  item_created_at?: string | null;
  item_updated_at?: string | null;
  target_preview?: Record<string, any> | null;
}

export interface InboxAction {
  id: string;
  inbox_item_id?: string | null;
  target_type: string;
  target_id: string;
  action_type: string;
  actor_id?: string | null;
  created_by?: string | null;
  payload?: Record<string, any>;
  created_at?: string | null;
  item_status?: string | null;
  batch_id?: string | null;
  scope_type?: string | null;
  scope_value?: string | null;
  generated_for_date?: string | null;
}

export interface InboxItemDetail {
  success?: boolean;
  error?: string;
  item?: InboxItem | null;
  target?: Record<string, any> | null;
  actions?: InboxAction[];
}

export interface InboxBatchResponse {
  success?: boolean;
  error?: string;
  batch?: InboxBatch | null;
  items?: InboxItem[];
  total?: number;
}

export interface InboxBatchesResponse {
  success?: boolean;
  error?: string;
  batches?: InboxBatch[];
  total?: number;
}

export interface InboxItemsResponse {
  success?: boolean;
  error?: string;
  items?: InboxItem[];
  total?: number;
}

export interface InboxActionsResponse {
  success?: boolean;
  error?: string;
  actions?: InboxAction[];
  total?: number;
}

export interface InboxActionResponse {
  success?: boolean;
  error?: string;
  action?: InboxAction | null;
  item?: InboxItem | null;
  side_effects?: Array<Record<string, any>>;
}

export interface VerticalBriefingTrack {
  id: string;
  title: string;
  summary?: string;
  track_kind?: string;
  post_ids?: string[];
  timeline?: Array<{
    date?: string | null;
    summary?: string | null;
    post_ids?: string[];
  }>;
  story_titles?: string[];
  entity_hints?: string[];
  evidence_cluster_count?: number;
  raw_post_count?: number;
  unique_post_count?: number;
}

export interface VerticalBriefingResponse {
  success?: boolean;
  error?: string;
  briefing?: string;
  vertical_briefing?: string;
  format?: string;
  saved_briefing_id?: string | null;
  cached?: boolean;
  scope_type?: string;
  scope_id?: string;
  source_id?: string;
  source_label?: string;
  start_date?: string;
  end_date?: string;
  subject_key?: string;
  posts_processed?: number;
  total_posts_fetched?: number;
  estimated_tokens?: number;
  tracks?: VerticalBriefingTrack[];
  posts?: Record<string, Post>;
  variant?: string;
}

export interface RebuildResponse {
  success?: boolean;
  error?: string;
  job_id?: string | null;
  result?: Record<string, any>;
  [key: string]: any;
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

export interface YouTubeVideoChapter {
  title: string;
  start_seconds: number;
  end_seconds?: number;
}

export interface YouTubeVideoEvaluationResponse {
  success?: boolean;
  error?: string;
  summary_markdown?: string;
  chapters?: YouTubeVideoChapter[];
  depth?: string;
  novelty?: string;
  worth_watching?: string;
  reasoning?: string;
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

function normalizeErrorText(text: string, contentType: string): string | null {
  const raw = text.trim();
  if (!raw) {
    return null;
  }

  if (contentType.includes('text/html')) {
    const titleMatch = raw.match(/<title>(.*?)<\/title>/is);
    const headingMatch = raw.match(/<h1[^>]*>(.*?)<\/h1>/is);
    const bestHtmlSnippet = titleMatch?.[1] || headingMatch?.[1] || raw;
    const stripped = bestHtmlSnippet.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    return stripped.slice(0, 180) || 'HTML error response';
  }

  return raw.replace(/\s+/g, ' ').trim().slice(0, 240);
}

class ApiService {
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

    const response = await fetch(url, { ...defaultOptions, ...options });
    
    if (!response.ok) {
      // Try to surface server error details when available
      let detail = `${response.status} ${response.statusText}`;
      try {
        const data = await response.clone().json();
        const serverMsg = (data && (data.detail || data.error || data.message));
        if (serverMsg) detail = `${response.status} ${serverMsg}`;
      } catch {
        try {
          const text = await response.text();
          const contentType = response.headers.get('content-type') || 'unknown';
          const normalizedText = normalizeErrorText(text, contentType);
          if (normalizedText) detail = `${response.status} ${normalizedText}`;
        } catch {}
      }
      throw new Error(`API request failed: ${detail} | url=${url}`);
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

  private async pollOperationPayload<T extends { success?: boolean; error?: string }>(
    jobId: string,
    opts?: { timeoutMs?: number; intervalMs?: number },
  ): Promise<T> {
    const timeoutMs = Math.max(10_000, opts?.timeoutMs ?? 600_000);
    const intervalMs = Math.max(500, opts?.intervalMs ?? 1_500);
    const startedAt = Date.now();

    while (Date.now() - startedAt < timeoutMs) {
      const jobResponse = await this.getOperationJob(jobId);
      if (!jobResponse.success || !jobResponse.job) {
        return {
          success: false,
          error: jobResponse.error || `Operation job ${jobId} not found`,
        } as T;
      }

      const job = jobResponse.job;
      if (job.status === 'success') {
        return {
          success: true,
          ...(job.payload || {}),
        } as T;
      }

      if (job.status === 'failed') {
        const payloadError = typeof job.payload?.error === 'string' ? job.payload.error : null;
        return {
          success: false,
          error: payloadError || job.message || `Operation ${job.job_type} failed`,
          ...(job.payload || {}),
        } as T;
      }

      await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
    }

    return {
      success: false,
      error: `Operation timed out while waiting for job ${jobId}`,
    } as T;
  }

  private async makeTrackedRequest<T extends { success?: boolean; error?: string }>(
    url: string,
    options: RequestInit,
    opts?: { timeoutMs?: number; intervalMs?: number },
  ): Promise<T> {
    const response = await this.makeRequest<T | AcceptedJobResponse>(url, options);
    if (!this.isAcceptedJobResponse(response)) {
      return response as T;
    }
    return this.pollOperationPayload<T>(response.job_id!, opts);
  }

  async generateBriefing(date: string): Promise<BriefingResponse> {
    try {
      const response = await this.makeTrackedRequest<BriefingResponse>('/api/daily', {
        method: 'POST',
        body: JSON.stringify({ date, asyncMode: true }),
      });
      
      return response;
    } catch (error) {
      console.error('Failed to generate briefing:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async generateWeeklyBriefing(date: string, refresh = false, includeTopics = false): Promise<WeeklyBriefingResponse> {
    try {
      return await this.makeTrackedRequest<WeeklyBriefingResponse>('/api/weekly', {
        method: 'POST',
        body: JSON.stringify({ date, refresh, includeTopics, asyncMode: true }),
      });
    } catch (error) {
      console.error('Failed to generate weekly briefing:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
  }

  async generateBriefingWithTopics(
    date: string,
    opts?: { includeUnreferenced?: boolean; refresh?: boolean }
  ): Promise<BriefingTopicsResponse> {
    try {
      const endpoint = `/api/daily/topics`;
      const response = await this.makeTrackedRequest<BriefingTopicsResponse>(endpoint, {
        method: 'POST',
        body: JSON.stringify({
          date,
          includeUnreferenced: opts?.includeUnreferenced ?? true,
          refresh: opts?.refresh ?? false,
          asyncMode: true,
        })
      });
      return response;
    } catch (error) {
      console.error('Failed to generate briefing with topics:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      } as BriefingTopicsResponse;
    }
  }

  async getEnabledSources(): Promise<SourceStats> {
    try {
      const response = await this.makeRequest<SourceStats>('/api/enabled-sources');
      return response;
    } catch (error) {
      console.error('Failed to get enabled sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to fetch sources'
      };
    }
  }

  async getSources(): Promise<SourceStats> {
    try {
      const response = await this.makeRequest<SourceStats>('/api/sources');
      return response;
    } catch (error) {
      console.error('Failed to get sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to fetch sources'
      };
    }
  }

  async updateSources(config: SourceConfig): Promise<SourceStats> {
    try {
      const response = await this.makeRequest<SourceStats>('/api/sources', {
        method: 'POST',
        body: JSON.stringify(config),
      });
      return response;
    } catch (error) {
      console.error('Failed to update sources:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Failed to update sources'
      };
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

  async getPostHighlights(postId: string, refresh = false): Promise<PostHighlightsResponse> {
    try {
      return await this.makeRequest<PostHighlightsResponse>(`/api/posts/item/${postId}/highlights`, {
        method: 'POST',
        body: JSON.stringify({ refresh }),
      });
    } catch (error) {
      console.error('Failed to get post highlights:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
        highlights: [],
      };
    }
  }

  async getPostReaderState(postId: string): Promise<PostReaderStateResponse> {
    try {
      return await this.makeRequest<PostReaderStateResponse>(`/api/posts/item/${postId}/reader-state`);
    } catch (error) {
      console.error('Failed to get post reader state:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
        reader_state: null,
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

  async getPostNotes(postId: string): Promise<PostNotesPayload & { success?: boolean; error?: string }> {
    try {
      return await this.makeRequest<PostNotesPayload & { success?: boolean; error?: string }>(`/api/posts/item/${postId}/notes`);
    } catch (error) {
      console.error('Failed to get post notes:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
        notes_markdown: '',
      };
    }
  }

  async savePostNotes(postId: string, notesMarkdown: string): Promise<PostNotesPayload & { success?: boolean; error?: string }> {
    try {
      return await this.makeRequest<PostNotesPayload & { success?: boolean; error?: string }>(`/api/posts/item/${postId}/notes`, {
        method: 'PUT',
        body: JSON.stringify({ notesMarkdown }),
      });
    } catch (error) {
      console.error('Failed to save post notes:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
        notes_markdown: notesMarkdown,
      };
    }
  }

  async getPostSummary(postId: string, refresh = false): Promise<PostSummaryResponse> {
    try {
      return await this.makeTrackedRequest<PostSummaryResponse>(`/api/posts/item/${postId}/summary`, {
        method: 'POST',
        body: JSON.stringify({ refresh, asyncMode: true }),
      });
    } catch (error) {
      console.error('Failed to get post summary:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
      };
    }
  }

  async chatAboutPost(postId: string, question: string): Promise<PostChatResponse> {
    try {
      return await this.makeTrackedRequest<PostChatResponse>(`/api/posts/item/${postId}/chat`, {
        method: 'POST',
        body: JSON.stringify({ question, asyncMode: true }),
      });
    } catch (error) {
      console.error('Failed to chat about post:', error);
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

  async generateRedditCommentsBriefing(postId: string, opts?: { limit?: number; refresh?: boolean }): Promise<RedditCommentsBriefingResponse> {
    try {
      return await this.makeTrackedRequest<RedditCommentsBriefingResponse>(`/api/posts/item/${postId}/reddit-comments/briefing`, {
        method: 'POST',
        body: JSON.stringify({
          limit: opts?.limit ?? 80,
          refresh: opts?.refresh ?? false,
          asyncMode: true,
        }),
      });
    } catch (error) {
      console.error('Failed to generate Reddit comments briefing:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
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

  async ingestPosts(): Promise<{ success: boolean; error?: string; message?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; error?: string; message?: string }>('/api/ingest-posts', {
        method: 'POST',
      });
      return response;
    } catch (error) {
      console.error('Failed to ingest posts:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async safeIngestPosts(): Promise<{ success: boolean; error?: string; message?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; error?: string; message?: string }>('/api/safe-ingest-posts', {
        method: 'POST',
      });
      return response;
    } catch (error) {
      console.error('Failed to safe ingest posts:', error);
      return {
        success: false,
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

  async fetchSourceNow(sourceId: string, limit?: number): Promise<LiveFetchResponse> {
    try {
      return await this.makeTrackedRequest<LiveFetchResponse>(`/api/sources/${sourceId}/fetch-now`, {
        method: 'POST',
        body: JSON.stringify({ limit, asyncMode: true }),
      });
    } catch (error) {
      console.error('Failed to fetch source now:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
      };
    }
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
        source_health: [],
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
          generateDailyBriefing: config.generate_daily_briefing,
          generateTopicBriefing: config.generate_topic_briefing,
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

  async evaluateYouTubeVideo(source: string, video: string): Promise<YouTubeVideoEvaluationResponse> {
    try {
      return await this.makeRequest<YouTubeVideoEvaluationResponse>('/api/youtube/video/evaluate', {
        method: 'POST',
        body: JSON.stringify({ source, video }),
      });
    } catch (error) {
      console.error('Failed to evaluate YouTube video:', error);
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

  async getPostEvidence(postId: string): Promise<{ success?: boolean; error?: string; evidence?: EvidenceDebug | null }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; evidence?: EvidenceDebug | null }>(`/api/posts/item/${postId}/evidence`);
    } catch (error) {
      console.error('Failed to get post evidence:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', evidence: null };
    }
  }

  async getPostMemory(postId: string): Promise<{ success?: boolean; error?: string; memory?: MemoryDebug | null }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; memory?: MemoryDebug | null }>(`/api/posts/item/${postId}/memory`);
    } catch (error) {
      console.error('Failed to get post memory:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', memory: null };
    }
  }

  async getPostEvents(postId: string): Promise<{ success?: boolean; error?: string; events?: EventDebug | null }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; events?: EventDebug | null }>(`/api/posts/item/${postId}/events`);
    } catch (error) {
      console.error('Failed to get post events:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', events: null };
    }
  }

  async getPostStory(postId: string): Promise<{ success?: boolean; error?: string; post_id?: string; stories?: StoryCard[]; primary_story?: StoryCard | null }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; post_id?: string; stories?: StoryCard[]; primary_story?: StoryCard | null }>(`/api/posts/item/${postId}/story`);
    } catch (error) {
      console.error('Failed to get post story:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', post_id: postId, stories: [], primary_story: null };
    }
  }

  async rebuildEvidenceForPost(postId: string): Promise<RebuildResponse> {
    try {
      return await this.makeRequest<RebuildResponse>('/api/evidence/rebuild-for-post', {
        method: 'POST',
        body: JSON.stringify({ postId }),
      });
    } catch (error) {
      console.error('Failed to rebuild evidence for post:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
    }
  }

  async rebuildEvidenceForDate(date: string, limit?: number): Promise<RebuildResponse> {
    try {
      return await this.makeRequest<RebuildResponse>('/api/evidence/rebuild-for-date', {
        method: 'POST',
        body: JSON.stringify({ date, limit }),
      });
    } catch (error) {
      console.error('Failed to rebuild evidence for date:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
    }
  }

  async rebuildMemoryForPost(postId: string): Promise<RebuildResponse> {
    try {
      return await this.makeRequest<RebuildResponse>('/api/memory/rebuild-for-post', {
        method: 'POST',
        body: JSON.stringify({ postId }),
      });
    } catch (error) {
      console.error('Failed to rebuild memory for post:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
    }
  }

  async rebuildMemoryForDate(date: string, limit?: number): Promise<RebuildResponse> {
    try {
      return await this.makeRequest<RebuildResponse>('/api/memory/rebuild-for-date', {
        method: 'POST',
        body: JSON.stringify({ date, limit }),
      });
    } catch (error) {
      console.error('Failed to rebuild memory for date:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
    }
  }

  async rebuildEventsForPost(postId: string): Promise<RebuildResponse> {
    try {
      return await this.makeRequest<RebuildResponse>('/api/events/rebuild-for-post', {
        method: 'POST',
        body: JSON.stringify({ postId }),
      });
    } catch (error) {
      console.error('Failed to rebuild events for post:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
    }
  }

  async rebuildEventsForDate(date: string, limit?: number): Promise<RebuildResponse> {
    try {
      return await this.makeRequest<RebuildResponse>('/api/events/rebuild-for-date', {
        method: 'POST',
        body: JSON.stringify({ date, limit }),
      });
    } catch (error) {
      console.error('Failed to rebuild events for date:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred' };
    }
  }

  async getStories(filters?: { status?: string; storyKind?: string; limit?: number; offset?: number }): Promise<{ success?: boolean; error?: string; stories?: StoryCard[]; total?: number }> {
    try {
      const params = new URLSearchParams();
      if (filters?.status) params.set('status', filters.status);
      if (filters?.storyKind) params.set('storyKind', filters.storyKind);
      if (filters?.limit != null) params.set('limit', String(filters.limit));
      if (filters?.offset != null) params.set('offset', String(filters.offset));
      const endpoint = params.toString() ? `/api/stories?${params.toString()}` : '/api/stories';
      return await this.makeRequest<{ success?: boolean; error?: string; stories?: StoryCard[]; total?: number }>(endpoint);
    } catch (error) {
      console.error('Failed to get stories:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', stories: [], total: 0 };
    }
  }

  async getStory(storyId: string): Promise<{ success?: boolean; error?: string; story?: StoryDetail | null }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; story?: StoryDetail | null }>(`/api/stories/${storyId}`);
    } catch (error) {
      console.error('Failed to get story:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', story: null };
    }
  }

  async getStoryTimeline(storyId: string): Promise<StoryTimelineResponse & { success?: boolean; error?: string }> {
    try {
      return await this.makeRequest<StoryTimelineResponse & { success?: boolean; error?: string }>(`/api/stories/${storyId}/timeline`);
    } catch (error) {
      console.error('Failed to get story timeline:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', story_id: storyId, timeline: [] };
    }
  }

  async getPostTimeline(postId: string, refresh = false): Promise<PostTimelineResponse> {
    try {
      if (refresh) {
        return await this.makeRequest<PostTimelineResponse>(`/api/posts/item/${postId}/timeline/refresh`, {
          method: 'POST',
          body: JSON.stringify({ refresh: true }),
        });
      }
      return await this.makeRequest<PostTimelineResponse>(`/api/posts/item/${postId}/timeline`);
    } catch (error) {
      console.error('Failed to get post timeline:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred',
        post_id: postId,
        timeline: null,
        related_candidates: [],
      };
    }
  }

  async acceptStoryCandidate(candidateId: string): Promise<{ success?: boolean; error?: string; candidate?: StoryCandidateLink | null; timeline?: PostTimelineResponse | null }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; candidate?: StoryCandidateLink | null; timeline?: PostTimelineResponse | null }>(`/api/story-candidates/${candidateId}/accept`, {
        method: 'POST',
      });
    } catch (error) {
      console.error('Failed to accept story candidate:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', candidate: null, timeline: null };
    }
  }

  async rejectStoryCandidate(candidateId: string): Promise<{ success?: boolean; error?: string; candidate?: StoryCandidateLink | null; timeline?: PostTimelineResponse | null }> {
    try {
      return await this.makeRequest<{ success?: boolean; error?: string; candidate?: StoryCandidateLink | null; timeline?: PostTimelineResponse | null }>(`/api/story-candidates/${candidateId}/reject`, {
        method: 'POST',
      });
    } catch (error) {
      console.error('Failed to reject story candidate:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', candidate: null, timeline: null };
    }
  }

  async getInbox(batchId?: string, limit = 20): Promise<InboxBatchResponse> {
    try {
      const params = new URLSearchParams();
      if (batchId) params.set('batchId', batchId);
      params.set('limit', String(limit));
      const endpoint = `/api/inbox${params.toString() ? `?${params.toString()}` : ''}`;
      return await this.makeRequest<InboxBatchResponse>(endpoint);
    } catch (error) {
      console.error('Failed to get inbox:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', batch: null, items: [], total: 0 };
    }
  }

  async getInboxBatches(limit = 50, offset = 0): Promise<InboxBatchesResponse> {
    try {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      return await this.makeRequest<InboxBatchesResponse>(`/api/inbox/batches?${params.toString()}`);
    } catch (error) {
      console.error('Failed to get inbox batches:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', batches: [], total: 0 };
    }
  }

  async getInboxItems(filters?: { batchId?: string; status?: string; targetType?: string; sourceId?: string; generatedForDate?: string; limit?: number; offset?: number }): Promise<InboxItemsResponse> {
    try {
      const params = new URLSearchParams();
      if (filters?.batchId) params.set('batchId', filters.batchId);
      if (filters?.status) params.set('status', filters.status);
      if (filters?.targetType) params.set('targetType', filters.targetType);
      if (filters?.sourceId) params.set('sourceId', filters.sourceId);
      if (filters?.generatedForDate) params.set('generatedForDate', filters.generatedForDate);
      params.set('limit', String(filters?.limit ?? 100));
      params.set('offset', String(filters?.offset ?? 0));
      return await this.makeRequest<InboxItemsResponse>(`/api/inbox/items?${params.toString()}`);
    } catch (error) {
      console.error('Failed to get inbox items:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', items: [], total: 0 };
    }
  }

  async getInboxItem(itemId: string): Promise<InboxItemDetail> {
    try {
      return await this.makeRequest<InboxItemDetail>(`/api/inbox/items/${itemId}`);
    } catch (error) {
      console.error('Failed to get inbox item:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', item: null, target: null, actions: [] };
    }
  }

  async rebuildInbox(payload?: { generatedForDate?: string; scopeType?: string; scopeValue?: string; limit?: number; actorId?: string }): Promise<InboxBatchResponse> {
    try {
      return await this.makeRequest<InboxBatchResponse>('/api/inbox/rebuild', {
        method: 'POST',
        body: JSON.stringify(payload || {}),
      });
    } catch (error) {
      console.error('Failed to rebuild inbox:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', batch: null, items: [], total: 0 };
    }
  }

  async recordInboxAction(itemId: string, payload: { actionType: string; actorId?: string; payload?: Record<string, any> }): Promise<InboxActionResponse> {
    try {
      return await this.makeRequest<InboxActionResponse>(`/api/inbox/items/${itemId}/actions`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    } catch (error) {
      console.error('Failed to record inbox action:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', action: null, item: null, side_effects: [] };
    }
  }

  async getInboxActions(filters?: { limit?: number; offset?: number; targetType?: string; targetId?: string; inboxItemId?: string }): Promise<InboxActionsResponse> {
    try {
      const params = new URLSearchParams();
      params.set('limit', String(filters?.limit ?? 100));
      params.set('offset', String(filters?.offset ?? 0));
      if (filters?.targetType) params.set('targetType', filters.targetType);
      if (filters?.targetId) params.set('targetId', filters.targetId);
      if (filters?.inboxItemId) params.set('inboxItemId', filters.inboxItemId);
      return await this.makeRequest<InboxActionsResponse>(`/api/inbox/actions?${params.toString()}`);
    } catch (error) {
      console.error('Failed to get inbox actions:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', actions: [], total: 0 };
    }
  }

  async getVerticalBriefing(sourceId: string, start?: string | null, end?: string | null): Promise<VerticalBriefingResponse> {
    try {
      const params = new URLSearchParams({ asyncMode: 'true' });
      if (start) params.set('start', start);
      if (end) params.set('end', end);
      return await this.makeTrackedRequest<VerticalBriefingResponse>(`/api/briefings/vertical/source/${sourceId}?${params.toString()}`, {
        method: 'GET',
      });
    } catch (error) {
      console.error('Failed to get vertical briefing:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', tracks: [], posts: {} };
    }
  }

  async refreshVerticalBriefing(sourceId: string, start?: string | null, end?: string | null): Promise<VerticalBriefingResponse> {
    try {
      const params = new URLSearchParams({ asyncMode: 'true' });
      if (start) params.set('start', start);
      if (end) params.set('end', end);
      return await this.makeTrackedRequest<VerticalBriefingResponse>(`/api/briefings/vertical/source/${sourceId}/refresh?${params.toString()}`, {
        method: 'POST',
      });
    } catch (error) {
      console.error('Failed to refresh vertical briefing:', error);
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error occurred', tracks: [], posts: {} };
    }
  }

  // ============= TOPICS METHODS =============

  async getTopicsByDate(date: string): Promise<TopicsResponse> {
    try {
      const response = await this.makeRequest<TopicsResponse>(`/api/topics/${date}`);
      return response;
    } catch (error) {
      console.error('Failed to get topics:', error);
      return {
        success: false,
        topics: [],
        date,
        total: 0,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async checkTopicsExist(date: string): Promise<{ success: boolean; exists: boolean; date: string; error?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; exists: boolean; date: string; error?: string }>(`/api/topics/check/${date}`);
      return response;
    } catch (error) {
      console.error('Failed to check topics:', error);
      return {
        success: false,
        exists: false,
        date,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async updateTopicTitle(topicId: string, newTitle: string): Promise<{ success: boolean; topic_id?: string; title?: string; error?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; topic_id?: string; title?: string; error?: string }>(`/api/topics/${topicId}/title`, {
        method: 'PUT',
        body: JSON.stringify({ title: newTitle }),
      });
      return response;
    } catch (error) {
      console.error('Failed to update topic title:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }

  async movePostToOutlier(topicId: string, postId: string, date: string): Promise<{ success: boolean; post_id?: string; source_topic_id?: string; outlier_topic_id?: string; message?: string; error?: string }> {
    try {
      const response = await this.makeRequest<{ success: boolean; post_id?: string; source_topic_id?: string; outlier_topic_id?: string; message?: string; error?: string }>(`/api/topics/${topicId}/posts/${postId}/move-to-outlier`, {
        method: 'POST',
        body: JSON.stringify({ date }),
      });
      return response;
    } catch (error) {
      console.error('Failed to move post to outlier:', error);
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error occurred'
      };
    }
  }
}

// Export singleton instance
export const apiService = new ApiService();
export default apiService; 
