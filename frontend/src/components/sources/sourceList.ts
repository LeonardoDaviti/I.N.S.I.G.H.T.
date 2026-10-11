/**
 * The Sources page as one list (pure, so it is testable): every source is one
 * health row; the toolbar filters it (search + status), groups it (by track,
 * status, platform, or not at all) and sorts inside each group. The view lives
 * in the URL:
 *
 *   ?q=simon&status=error&group=status&sort=posts
 *
 * The old Health tab URL (`?tab=health`) maps to `group=status`, keeping its
 * `?status=` filter, so bookmarks and the command palette still land right.
 */
import type { Folder, HealthStatus, SourceHealthRow } from '../../services/api';
import type { Status } from '../ui/styles';
import { HEALTH_STATUS_LABELS, HEALTH_STATUS_ORDER, backoffLabel, filterHealthRows, sortHealthRows } from '../../lib/sourceSchedule';
import { formatRelativeTime } from '../../lib/dates';
import { getPlatformLabel, sourceLabel } from '../../lib/sourceLabel';
import { matchesSource, queryWords } from '../../lib/sourceSearch';

export type GroupBy = 'track' | 'status' | 'platform' | 'none';
export const GROUP_BY: readonly GroupBy[] = ['track', 'status', 'platform', 'none'];
export const GROUP_BY_LABELS: Record<GroupBy, string> = {
  track: 'Track',
  status: 'Status',
  platform: 'Platform',
  none: 'No grouping',
};

export type SortBy = 'status' | 'name' | 'success' | 'posts';
export const SORT_BY: readonly SortBy[] = ['status', 'name', 'success', 'posts'];
export const SORT_BY_LABELS: Record<SortBy, string> = {
  status: 'Status',
  name: 'Name',
  success: 'Last success',
  posts: 'Posts',
};

/** A status chip: one health status, or `enabled` (every source that is on). */
export type StatusFilter = HealthStatus | 'enabled';
const STATUS_FILTER_VALUES: readonly string[] = ['enabled', ...HEALTH_STATUS_ORDER];

export interface SourcesView {
  q: string;
  status: StatusFilter | null;
  group: GroupBy;
  sort: SortBy;
}

export const UNASSIGNED_KEY = 'track:none';

export interface SourceGroup {
  key: string;
  label: string;
  /** Set for a real track (links to it, carries its menu). */
  folderId?: string;
  rows: SourceHealthRow[];
}

export function readSourcesView(params: URLSearchParams): SourcesView {
  const status = params.get('status');
  const group = params.get('group');
  const sort = params.get('sort');
  const legacyHealth = params.get('tab') === 'health';
  return {
    q: params.get('q') ?? '',
    status: STATUS_FILTER_VALUES.includes(status ?? '') ? (status as StatusFilter) : null,
    group: GROUP_BY.includes(group as GroupBy) ? (group as GroupBy) : legacyHealth ? 'status' : 'track',
    sort: SORT_BY.includes(sort as SortBy) ? (sort as SortBy) : 'status',
  };
}

/** The URL for a view; `track` grouping, `status` sort and empty values stay out of it. Other params (`data`) survive. */
export function writeSourcesView(params: URLSearchParams, view: SourcesView): URLSearchParams {
  const next = new URLSearchParams(params);
  next.delete('tab');
  const set = (key: string, value: string | null) => (value ? next.set(key, value) : next.delete(key));
  set('q', view.q.trim() ? view.q : null);
  set('status', view.status);
  set('group', view.group === 'track' ? null : view.group);
  set('sort', view.sort === 'status' ? null : view.sort);
  return next;
}

export function rowName(row: Pick<SourceHealthRow, 'display_name' | 'source_id'>): string {
  return sourceLabel(String(row.display_name || row.source_id));
}

/** The rows a status chip keeps: `enabled` is every source that is on, the rest as filterHealthRows. */
export function filterByStatus(rows: readonly SourceHealthRow[], status: StatusFilter | null): SourceHealthRow[] {
  if (status === 'enabled') return rows.filter((row) => row.enabled);
  return filterHealthRows(rows, status);
}

export function filterSources(rows: readonly SourceHealthRow[], view: Pick<SourcesView, 'q' | 'status'>): SourceHealthRow[] {
  const words = queryWords(view.q);
  return filterByStatus(rows, view.status).filter((row) => matchesSource({
    name: String(row.display_name ?? ''),
    label: rowName(row),
    kind: row.kind,
    platform: row.platform,
    url: row.folders.map((folder) => folder.name).join(' '),
  }, words));
}

const byName = (a: SourceHealthRow, b: SourceHealthRow) =>
  rowName(a).localeCompare(rowName(b), undefined, { sensitivity: 'base' });

const time = (iso: string | null | undefined) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? -Infinity : t;
};

/**
 * The order inside a group. Status: worst first, then name. Name: A to Z.
 * Last success: the stalest first (never fetched at the top), so the ones that
 * stopped working surface. Posts: the most first. Ties fall back to the name.
 */
export function sortSources(rows: readonly SourceHealthRow[], sort: SortBy): SourceHealthRow[] {
  const named = [...rows].sort(byName);
  if (sort === 'status') return sortHealthRows(named);
  if (sort === 'name') return named;
  if (sort === 'posts') return named.sort((a, b) => b.stored_posts - a.stored_posts);
  return named.sort((a, b) => time(a.last_success_at) - time(b.last_success_at));
}

/**
 * Groups in display order. Track: every track in the folder order (empty ones
 * too, unless a search or filter is on), then "Not in a track"; a source in two
 * tracks shows in both. Status: worst first. Inside a group, `sort` (default:
 * worst status first, then name).
 */
export function groupSources(
  rows: readonly SourceHealthRow[],
  group: GroupBy,
  folders: readonly Pick<Folder, 'id' | 'name'>[] = [],
  { keepEmpty = true, sort = 'status' }: { keepEmpty?: boolean; sort?: SortBy } = {},
): SourceGroup[] {
  const sorted = sortSources(rows, sort);
  if (group === 'none') return [{ key: 'all', label: 'All sources', rows: sorted }];
  if (group === 'status') {
    return HEALTH_STATUS_ORDER
      .map((status) => ({ key: `status:${status}`, label: HEALTH_STATUS_LABELS[status], rows: sorted.filter((row) => row.status === status) }))
      .filter((g) => g.rows.length > 0);
  }
  if (group === 'platform') {
    const map = new Map<string, SourceHealthRow[]>();
    sorted.forEach((row) => map.set(row.platform, [...(map.get(row.platform) ?? []), row]));
    return [...map.entries()]
      .map(([platform, list]) => ({ key: `platform:${platform}`, label: getPlatformLabel(platform), rows: list }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }
  const known = new Set(folders.map((folder) => folder.id));
  const groups: SourceGroup[] = folders.map((folder) => ({
    key: `track:${folder.id}`,
    label: folder.name?.trim() || 'Untitled track',
    folderId: folder.id,
    rows: sorted.filter((row) => row.folders.some((f) => f.id === folder.id)),
  }));
  const unassigned = sorted.filter((row) => !row.folders.some((f) => known.has(f.id)));
  const all = [...groups, { key: UNASSIGNED_KEY, label: 'Not in a track', rows: unassigned }];
  return all.filter((g) => g.rows.length > 0 || (keepEmpty && g.folderId));
}

/** The rows j/k walk: visible (not collapsed) rows in order, one entry per (group, source). */
export function visibleRowKeys(groups: readonly SourceGroup[], collapsed: ReadonlySet<string>): { key: string; id: string }[] {
  return groups.flatMap((g) => (collapsed.has(g.key) ? [] : g.rows.map((row) => ({ key: `${g.key}/${row.source_id}`, id: row.source_id }))));
}

/** j/k: the next active key, clamped at the ends; from nothing, j starts at the top and k at the bottom. */
export function stepActive(keys: readonly string[], current: string | null, delta: 1 | -1): string | null {
  if (!keys.length) return null;
  const index = current ? keys.indexOf(current) : -1;
  if (index < 0) return delta === 1 ? keys[0] : keys[keys.length - 1];
  return keys[Math.min(keys.length - 1, Math.max(0, index + delta))];
}

/**
 * Shift-click: the source ids from the anchor row to the target row, both
 * included, in on-screen order (either direction). Without a visible anchor,
 * just the target.
 */
export function rangeIds(keys: readonly { key: string; id: string }[], anchor: string | null, target: string): string[] {
  const to = keys.findIndex((k) => k.key === target);
  if (to < 0) return [];
  const from = anchor ? keys.findIndex((k) => k.key === anchor) : -1;
  if (from < 0) return [keys[to].id];
  const [lo, hi] = from < to ? [from, to] : [to, from];
  return [...new Set(keys.slice(lo, hi + 1).map((k) => k.id))];
}

export function toggleInSet<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

/** Health status -> the monochrome status vocabulary (design docs system/status.md). */
export const STATUS_GLYPH: Record<HealthStatus, Status> = {
  error: 'failing',
  backoff: 'backoff',
  unavailable: 'unavailable',
  due: 'due',
  deferred: 'scheduled',
  disabled: 'disabled',
};

/** The one fact a row shows on the right: what happens next, or what went wrong. */
export function rowFact(row: SourceHealthRow, now: Date): string {
  if (!row.enabled) return 'off';
  if (row.status === 'unavailable') return 'unavailable';
  const backoff = backoffLabel(row, now);
  if (backoff) return backoff;
  if (row.status === 'error') return 'failed';
  if (!row.last_success_at) return 'never fetched';
  return `fetched ${formatRelativeTime(row.last_success_at, now)}`;
}

/**
 * Status chips. The primary ones always show (after All): enabled, disabled,
 * failing (error + backoff, like the "N source errors" chip), unavailable. The
 * secondary ones narrow further and show only when they have sources.
 */
export const STATUS_FILTERS: { value: StatusFilter; label: string; secondary?: boolean }[] = [
  { value: 'enabled', label: 'Enabled' },
  { value: 'disabled', label: 'Disabled' },
  { value: 'error', label: 'Failing' },
  { value: 'unavailable', label: 'Unavailable' },
  { value: 'backoff', label: 'Backoff', secondary: true },
  { value: 'due', label: 'Due', secondary: true },
  { value: 'deferred', label: 'Scheduled', secondary: true },
];

/** Readable names for the backend's source kinds; an unknown kind falls back to the platform. */
const KIND_LABELS: Record<string, string> = {
  generic_rss: 'RSS',
  youtube_channel: 'YouTube',
  telegram_mtproto: 'Telegram',
  telegram_rss: 'Telegram RSS',
  reddit_subreddit: 'Reddit',
  substack: 'Substack',
};

export function kindLabel(row: Pick<SourceHealthRow, 'kind' | 'platform'>): string {
  return KIND_LABELS[row.kind] ?? getPlatformLabel(row.platform);
}

/** When the source's newest post was published (the backend's `last_post_at`; older backends omit it). */
export function lastPostAt(row: SourceHealthRow): string | null {
  return (row as SourceHealthRow & { last_post_at?: string | null }).last_post_at ?? null;
}
