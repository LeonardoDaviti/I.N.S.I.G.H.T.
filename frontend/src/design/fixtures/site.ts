/**
 * A whole INSIGHT backend as data (Design Studio D4): the feed, the tracks, the
 * sources and their health, the connections, the ingestion jobs and the posts.
 * `siteRoutes` turns one into the fixture transport's routes, so a frame can
 * open any page (and, in walk mode, move between them) on the same sample data.
 * The feed honours scope, filter, view and paging like the backend does.
 */
import type {
  ArchiveCatalogEntry, ArchiveStatusResponse, CredentialsResponse, FeedGroup, FeedItem, Folder, JobRun, PostDetailResponse,
  SchedulerConfig, SourceHealthRow, SourceWithSettings, UnreadCounts,
} from '../../services/api';
import { healthResponse } from '../../components/ops/fixtures';
import type { FixtureRequest, FixtureRoute } from '../frame/transport';

export interface Site {
  /** The whole feed, newest first. */
  items: FeedItem[];
  folders: Folder[];
  /** Every source; its `folders` say which tracks it is in. */
  health: SourceHealthRow[];
  credentials: CredentialsResponse;
  /** Newest first; an ingestion run's payload is its run report. */
  jobs: JobRun[];
  scheduler: SchedulerConfig;
  /** Posts with a hand-written detail; any other feed item opens as a post made from its row. */
  posts?: Record<string, PostDetailResponse>;
}

const PAGE_SIZE = 30;

function inScope(site: Site, scope: string): (item: FeedItem) => boolean {
  if (scope === 'all') return () => true;
  const [kind, id] = scope.split(':');
  if (kind === 'source') return (item) => item.source_id === id;
  const members = new Set(site.health.filter((row) => row.folders.some((folder) => folder.id === id)).map((row) => row.source_id));
  return (item) => members.has(item.source_id);
}

function passes(filter: string | null): (item: FeedItem) => boolean {
  if (filter === 'starred') return (item) => item.starred_at !== null;
  if (filter === 'all') return () => true;
  return (item) => item.read_at === null;
}

function feedItems(site: Site, query: URLSearchParams): FeedItem[] {
  return site.items.filter(inScope(site, query.get('scope') ?? 'all')).filter(passes(query.get('filter')));
}

/** One page of a list, with the offset as the cursor. */
function page<T>(list: T[], query: URLSearchParams): { slice: T[]; next_cursor: string | null } {
  const start = Number(query.get('cursor') ?? 0) || 0;
  const limit = Number(query.get('limit') ?? PAGE_SIZE) || PAGE_SIZE;
  const end = start + limit;
  return { slice: list.slice(start, end), next_cursor: end < list.length ? String(end) : null };
}

function groups(items: FeedItem[]): FeedGroup[] {
  const bySource = new Map<string, FeedItem[]>();
  for (const item of items) bySource.set(item.source_id, [...(bySource.get(item.source_id) ?? []), item]);
  return [...bySource.values()].map((list) => ({
    source_id: list[0].source_id,
    source_display_name: list[0].source_display_name,
    platform: list[0].platform,
    newest_sort_at: list[0].sort_at,
    count: list.length,
    items: list.slice(0, 3),
  }));
}

function feed({ query }: FixtureRequest, site: Site) {
  const items = feedItems(site, query);
  if (query.get('view') === 'by_source') {
    const { slice, next_cursor } = page(groups(items), query);
    return { success: true, groups: slice, next_cursor };
  }
  const { slice, next_cursor } = page(items, query);
  return { success: true, items: slice, next_cursor };
}

export function unreadCounts(site: Site): UnreadCounts {
  const counts: UnreadCounts = { total: 0, by_source: {}, by_folder: {} };
  const foldersOf = new Map(site.health.map((row) => [row.source_id, row.folders.map((folder) => folder.id)]));
  for (const item of site.items) {
    if (item.read_at !== null) continue;
    counts.total += 1;
    counts.by_source[item.source_id] = (counts.by_source[item.source_id] ?? 0) + 1;
    for (const id of foldersOf.get(item.source_id) ?? []) counts.by_folder[id] = (counts.by_folder[id] ?? 0) + 1;
  }
  return counts;
}

function paragraphs(item: FeedItem): string {
  const lead = item.excerpt || item.title;
  return [
    lead,
    'The change is small on paper and large in practice: the same request now costs a fraction of what it did, and the latency of the first token drops with it.',
    'What follows is a walk through the details, the numbers we measured on our own workloads, and the two places where the behaviour still surprises people.',
  ].map((text) => `<p>${text}</p>`).join('\n');
}

/** A feed row opened as a post: its title, source and an article-length body. */
export function postFromItem(item: FeedItem): PostDetailResponse {
  const html = paragraphs(item);
  return {
    success: true,
    post: {
      id: item.id,
      source_id: item.source_id,
      title: item.title,
      content: html.replace(/<[^>]+>/g, ''),
      content_html: html,
      source: item.url,
      source_display_name: item.source_display_name,
      platform: item.platform,
      url: item.url,
      published_at: item.published_at,
    },
    reader_state: { post_id: item.id, is_favorited: item.starred_at !== null, open_count: 0 },
  };
}

function postDetail({ params }: FixtureRequest, site: Site) {
  const known = site.posts?.[params.postId];
  if (known) return known;
  const item = site.items.find((candidate) => candidate.id === params.postId);
  if (item) return postFromItem(item);
  return new Response(JSON.stringify({ detail: 'Post not found' }), { status: 404 });
}

function sourcesWithSettings(site: Site): { success: true; sources: SourceWithSettings[]; total: number } {
  const sources = site.health.map((row): SourceWithSettings => ({
    id: row.source_id,
    platform: row.platform,
    handle_or_url: row.display_name.startsWith('http') ? row.display_name : `https://feeds.example.org/${row.source_id}.xml`,
    enabled: row.enabled,
    post_count: row.stored_posts,
    settings: { display_name: row.display_name, fetch_delay_seconds: 0, priority: 0, max_posts_per_fetch: 50 },
  }));
  return { success: true, sources, total: sources.length };
}

/**
 * The archive catalog the ingestion tab lists, made from the health rows: a
 * feed holds all it lists, a channel has a backlog, Substack never says.
 */
export function archiveCatalog(site: Site): ArchiveCatalogEntry[] {
  return site.health.filter((row) => row.enabled).map((row, i) => {
    const stored = row.stored_posts;
    const available = row.platform === 'substack' ? null
      : row.platform === 'youtube' || row.platform === 'telegram' ? stored * 4 + 80
        : stored;
    return {
      source_id: row.source_id,
      display_name: row.display_name,
      platform: row.platform,
      enabled: row.enabled,
      kind: row.kind,
      stored_posts: stored,
      available_posts: available,
      backlog_posts: available === null ? null : Math.max(available - stored, 0),
      archive_status: available !== null && stored >= available ? 'archived' : stored > 0 ? 'partial' : 'not_archived',
      resume_ready: row.platform === 'youtube' && i % 2 === 0,
      rate_limit: { page_delay_seconds: 5, batch_size: 10, batch_cooldown_seconds: 30 },
    };
  });
}

function archiveStatus({ params }: FixtureRequest, site: Site): ArchiveStatusResponse {
  const entry = archiveCatalog(site).find((candidate) => candidate.source_id === params.sourceId);
  const stored = entry?.stored_posts ?? 120;
  return {
    success: true,
    archive: {
      status: 'idle',
      stored_posts: stored,
      available_posts: entry ? entry.available_posts : 480,
      resume_ready: entry?.resume_ready ?? false,
      checkpoint: entry?.resume_ready ? { collected_posts: Math.round(stored / 2), pages_fetched: 6 } : null,
      rate_limit: entry?.rate_limit ?? null,
    },
    support: {
      kind: entry?.kind ?? 'generic_rss',
      available_basis: entry && entry.available_posts === null ? 'unknown' : entry?.platform === 'rss' ? 'feed_window' : 'exact',
      archivable: true,
      reason: null,
      unavailable: false,
      live_fetch_limit: 50,
    },
    latest_job: null,
  };
}

/** The tail of a backend log: a few fetches around the last run. */
function logTail({ query }: FixtureRequest, site: Site) {
  const log = query.get('log') ?? 'application';
  const stamp = (site.jobs[0]?.started_at ?? '2026-10-11T08:00:00Z').replace('T', ' ').slice(0, 19);
  const names = site.health.slice(0, 8).map((row) => row.display_name);
  const lines = log === 'errors'
    ? [`${stamp},412 - insight.connectors - ERROR - ${names[1] ?? 'A source'}: HTTP 503 from the feed, retrying in 30 minutes`]
    : [
      `${stamp},004 - insight.scheduler - INFO - Tick: 12 due, 66 deferred`,
      ...names.map((name, i) => `${stamp},${String(120 + i * 61).padStart(3, '0')} - insight.ingestion - INFO - ${name}: ${i % 3} new posts`),
      `${stamp},998 - insight.ingestion - INFO - Run finished: 12 due, 66 deferred, 0 failed; 48 new posts`,
    ];
  return {
    success: true,
    log,
    available_logs: ['application', 'errors', 'rss', 'reddit', 'youtube', 'telegram', 'automated', 'interactive', 'recovery'],
    exists: true,
    updated_at: Date.parse(site.jobs[0]?.finished_at ?? site.jobs[0]?.started_at ?? '2026-10-11T08:00:00Z') / 1000,
    lines,
  };
}

/** The transport routes that serve one site. */
export function siteRoutes(site: Site): FixtureRoute[] {
  return [
    { path: '/api/feed', respond: (request) => feed(request, site) },
    { path: '/api/feed/unread-counts', respond: () => unreadCounts(site) },
    { path: '/api/folders', respond: () => ({ success: true, folders: site.folders }) },
    { path: '/api/sources/health', respond: () => healthResponse(site.health) },
    { path: '/api/sources', respond: () => sourcesWithSettings(site) },
    {
      path: '/api/sources/:sourceId/folders',
      respond: ({ params }) => ({
        success: true,
        folder_ids: site.health.find((row) => row.source_id === params.sourceId)?.folders.map((folder) => folder.id) ?? [],
      }),
    },
    { path: '/api/credentials', respond: () => site.credentials },
    { path: '/api/operations/overview', respond: () => ({ success: true, jobs: site.jobs, alerts: [], scheduler: site.scheduler }) },
    { path: '/api/operations/scheduler', respond: () => ({ success: true, scheduler: site.scheduler }) },
    { path: '/api/version', respond: () => ({ version: null, commit: null, commit_date: null }) },
    {
      path: '/api/operations/jobs/:jobId',
      respond: ({ params }) => ({ success: true, job: site.jobs.find((job) => job.id === params.jobId) ?? null }),
    },
    { path: '/api/posts/item/:postId', respond: (request) => postDetail(request, site) },
    { path: '/api/youtube/progress/:videoId', respond: () => ({ success: true, progress: null }) },
    // The archive: the ingestion tab's catalog, and each source's status (the sheet and the tab).
    { path: '/api/archive/catalog', respond: () => ({ success: true, sources: archiveCatalog(site), total: archiveCatalog(site).length }) },
    { path: '/api/archive/:sourceId/status', respond: (request) => archiveStatus(request, site) },
    { path: '/api/ingestion/logs', respond: (request) => logTail(request, site) },
  ];
}
