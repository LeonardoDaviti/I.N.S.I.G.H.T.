/**
 * The Sources page as one list (pure, so it is testable): every source is one
 * health row; the toolbar filters it (search + status) and groups it (by track
 * or platform; flat by default), the column headers sort inside each group. The
 * view lives in the URL:
 *
 *   ?q=simon&status=error&group=track&sort=added&dir=asc
 *
 * The old Health tab URL (`?tab=health`) is the flat list, keeping its
 * `?status=` filter, so bookmarks and the command palette still land right.
 * Retired or unknown values (`sort=success`, `group=status`) fall back to the
 * defaults. A track deep link (`?track=<id>`, issue 0003) groups by track so
 * its group is there to scroll to; the first change to the view consumes it.
 */
import type { Folder, HealthStatus, SourceHealthRow } from '../../services/api';
import type { Status } from '../ui/styles';
import { HEALTH_STATUS_ORDER, backoffLabel, filterHealthRows, statusRank } from '../../lib/sourceSchedule';
import { formatRelativeTime } from '../../lib/dates';
import { getPlatformLabel, sourceLabel } from '../../lib/sourceLabel';
import { matchesSource, queryWords } from '../../lib/sourceSearch';

export type GroupBy = 'none' | 'track' | 'kind';
export const GROUP_BY: readonly GroupBy[] = ['none', 'track', 'kind'];
export const GROUP_BY_LABELS: Record<GroupBy, string> = {
  none: 'No grouping',
  track: 'Track',
  kind: 'Kind',
};

/** The sortable columns, in on-screen order. */
export type SortBy = 'name' | 'kind' | 'posts' | 'lastPost' | 'added' | 'status';
export const SORT_BY: readonly SortBy[] = ['name', 'kind', 'posts', 'lastPost', 'added', 'status'];
export const SORT_BY_LABELS: Record<SortBy, string> = {
  name: 'Name',
  kind: 'Kind',
  posts: 'Posts',
  lastPost: 'Last post',
  added: 'Added',
  status: 'Status',
};

export type SortDir = 'asc' | 'desc';
export const DIR_WORDS: Record<SortDir, string> = { asc: 'ascending', desc: 'descending' };
export const DIR_ARROWS: Record<SortDir, string> = { asc: '↑', desc: '↓' };
/** A column's first click: text A to Z, numbers and dates biggest/newest first, status worst first. */
export const DEFAULT_DIR: Record<SortBy, SortDir> = {
  name: 'asc',
  kind: 'asc',
  posts: 'desc',
  lastPost: 'desc',
  added: 'desc',
  status: 'desc',
};

/** A status chip: one health status, or `enabled` (every source that is on). */
export type StatusFilter = HealthStatus | 'enabled';
const STATUS_FILTER_VALUES: readonly string[] = ['enabled', ...HEALTH_STATUS_ORDER];

export interface SourcesView {
  q: string;
  status: StatusFilter | null;
  group: GroupBy;
  sort: SortBy;
  dir: SortDir;
}

export const UNASSIGNED_KEY = 'track:none';

export interface SourceGroup {
  key: string;
  label: string;
  /** Listed without a header (the flat list; untracked sources after the tracks, below a divider). */
  headless?: boolean;
  /** Set for a real track (links to it, carries its menu). */
  folderId?: string;
  rows: SourceHealthRow[];
}

export function readSourcesView(params: URLSearchParams): SourcesView {
  // ?status=backoff is now part of Failing; ?group=platform is the old name of Group by Kind.
  const status = params.get('status') === 'backoff' ? 'error' : params.get('status');
  const group = params.get('group') === 'platform' ? 'kind' : params.get('group');
  const sort = SORT_BY.includes(params.get('sort') as SortBy) ? (params.get('sort') as SortBy) : 'status';
  const dir = params.get('dir');
  return {
    q: params.get('q') ?? '',
    status: STATUS_FILTER_VALUES.includes(status ?? '') ? (status as StatusFilter) : null,
    group: GROUP_BY.includes(group as GroupBy) ? (group as GroupBy) : params.has('track') ? 'track' : 'none',
    sort,
    dir: dir === 'asc' || dir === 'desc' ? dir : DEFAULT_DIR[sort],
  };
}

/**
 * The URL for a view; no grouping, the `status` sort, a column's own direction
 * and empty values stay out of it. The legacy tab and a consumed track deep
 * link go; other params (`data`, `source`) survive.
 */
export function writeSourcesView(params: URLSearchParams, view: SourcesView): URLSearchParams {
  const next = new URLSearchParams(params);
  next.delete('tab');
  next.delete('track');
  const set = (key: string, value: string | null) => (value ? next.set(key, value) : next.delete(key));
  set('q', view.q.trim() ? view.q : null);
  set('status', view.status);
  set('group', view.group === 'none' ? null : view.group);
  set('sort', view.sort === 'status' ? null : view.sort);
  set('dir', view.dir === DEFAULT_DIR[view.sort] ? null : view.dir);
  return next;
}

/** A column header click: a new column starts in its own direction, the active one reverses. */
export function nextSort<V extends Pick<SourcesView, 'sort' | 'dir'>>(view: V, sort: SortBy): V {
  const dir = sort !== view.sort ? DEFAULT_DIR[sort] : view.dir === 'asc' ? 'desc' : 'asc';
  return { ...view, sort, dir };
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

/** Each column's ascending order (status has its own: worst first). */
const ASCENDING: Record<Exclude<SortBy, 'status'>, (a: SourceHealthRow, b: SourceHealthRow) => number> = {
  name: byName,
  kind: (a, b) => kindLabel(a).localeCompare(kindLabel(b)),
  posts: (a, b) => a.stored_posts - b.stored_posts,
  lastPost: (a, b) => time(a.last_post_at) - time(b.last_post_at),
  added: (a, b) => time(a.created_at) - time(b.created_at),
};

/**
 * The order inside a group, by one column in a direction (default: the
 * column's own, DEFAULT_DIR). Status descending is worst first; ascending is the
 * status order reversed. A source without posts counts as the oldest. Ties fall
 * back to the name, A to Z, in every column: within a status too, never by the next
 * fetch (a just-fetched source sank to the end of Scheduled).
 */
export function sortSources(rows: readonly SourceHealthRow[], sort: SortBy, dir: SortDir = DEFAULT_DIR[sort]): SourceHealthRow[] {
  if (sort === 'status') {
    const sign = dir === 'desc' ? 1 : -1;
    return [...rows].sort((a, b) => sign * (statusRank(a.status) - statusRank(b.status)) || byName(a, b));
  }
  const sign = dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => sign * ASCENDING[sort](a, b) || byName(a, b));
}

/**
 * Groups in display order. None: one flat list without a header. Track: every
 * track in the folder order (empty ones too, unless a search or filter is on),
 * then the sources in no track, without a header; a source in two tracks shows
 * in both. Kind (as the list's Kind column names it): A to Z. Inside a group, `sort` in `dir` (default: worst
 * status first).
 */
export function groupSources(
  rows: readonly SourceHealthRow[],
  group: GroupBy,
  folders: readonly Pick<Folder, 'id' | 'name'>[] = [],
  { keepEmpty = true, sort = 'status', dir }: { keepEmpty?: boolean; sort?: SortBy; dir?: SortDir } = {},
): SourceGroup[] {
  const sorted = sortSources(rows, sort, dir);
  if (group === 'none') return [{ key: 'all', label: 'All sources', headless: true, rows: sorted }];
  if (group === 'kind') {
    const map = new Map<string, SourceHealthRow[]>();
    sorted.forEach((row) => { const label = kindLabel(row); map.set(label, [...(map.get(label) ?? []), row]); });
    return [...map.entries()]
      .map(([label, list]) => ({ key: `kind:${label}`, label, rows: list }))
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
  const all = [...groups, { key: UNASSIGNED_KEY, label: 'Other sources', headless: true, rows: unassigned }];
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
  if (row.kind === 'saved') return 'pages you save';
  if (row.status === 'unavailable') return 'unavailable';
  const backoff = backoffLabel(row, now);
  if (backoff) return backoff;
  if (row.status === 'error') return 'failed';
  if (!row.last_success_at) return 'never fetched';
  return `fetched ${formatRelativeTime(row.last_success_at, now)}`;
}

/**
 * Status chips. The primary ones always show (after All): enabled, disabled and
 * failing (error + backoff, like the "N source errors" chip, so backoff has no chip of its own). The
 * secondary ones narrow further and show only when they have sources.
 */
export const STATUS_FILTERS: { value: StatusFilter; label: string; secondary?: boolean }[] = [
  { value: 'enabled', label: 'Enabled' },
  { value: 'disabled', label: 'Disabled' },
  { value: 'error', label: 'Failing' },
  { value: 'unavailable', label: 'Unavailable', secondary: true },
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
  saved: 'Saved pages',
};

export function kindLabel(row: Pick<SourceHealthRow, 'kind' | 'platform'>): string {
  return KIND_LABELS[row.kind] ?? getPlatformLabel(row.platform);
}
