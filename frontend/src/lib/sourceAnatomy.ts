/**
 * Source anatomy (issue 0054): the words and the order of Sources → ingestion → sources, one
 * row per source, how it is read and what it gives. Pure; `now` is injected. Imported only by
 * the view's lazy chunk.
 */
import type { AnatomyKind, SourceAnatomyRow, SourceGives } from '../services/api';
import { compactAge, formatLocalDateTime } from './dates.ts';
import { formatHours } from './duration.ts';
import { formatCount } from './format.ts';
import { formatDue } from './sourceSchedule.ts';
import { sourceLabel } from './sourceLabel.ts';

export type AnatomySort =
  | 'name' | 'kind' | 'fullText' | 'watch' | 'conditional' | 'schedule' | 'lastFetch'
  | keyof SourceGives;
export type AnatomyDir = 'asc' | 'desc';

/** What each column gives, in on-screen order. */
export const GIVES_COLUMNS: readonly (keyof SourceGives)[] = ['posts', 'read', 'stories', 'first', 'classics', 'links'];

export const ANATOMY_LABELS: Record<AnatomySort, string> = {
  name: 'Source',
  kind: 'Kind',
  fullText: 'Full text',
  watch: 'Watch',
  conditional: 'If changed',
  schedule: 'Every',
  lastFetch: 'Last fetch',
  posts: 'Posts',
  read: 'Read',
  stories: 'Stories',
  first: 'First',
  classics: 'Classics',
  links: 'Links',
};

/** What a column's header says on hover. */
export const ANATOMY_HINTS: Partial<Record<AnatomySort, string>> = {
  fullText: 'Whether it reads each post’s page for the whole text',
  watch: 'Whether its pages are re-read for changes',
  conditional: 'Whether an unchanged feed is skipped (it answers 304 and costs nothing)',
  read: 'Posts you opened',
  stories: 'Stories its posts are in',
  first: 'Stories it reported first',
  classics: 'Classics it cited',
  links: 'Outside links it gave',
};

/** Words first A to Z; the schedule most often first; the last fetch and every count biggest first. */
export const ANATOMY_DEFAULT_DIR: Record<AnatomySort, AnatomyDir> = {
  name: 'asc', kind: 'asc', fullText: 'asc', watch: 'asc', conditional: 'asc', schedule: 'asc',
  lastFetch: 'desc', posts: 'desc', read: 'desc', stories: 'desc', first: 'desc', classics: 'desc', links: 'desc',
};

export const DEFAULT_ANATOMY_SORT: { sort: AnatomySort; dir: AnatomyDir } = { sort: 'posts', dir: 'desc' };

/** The same column again reverses; another column starts in its own direction. */
export function nextAnatomySort(current: { sort: AnatomySort; dir: AnatomyDir }, sort: AnatomySort): { sort: AnatomySort; dir: AnatomyDir } {
  if (sort !== current.sort) return { sort, dir: ANATOMY_DEFAULT_DIR[sort] };
  return { sort, dir: current.dir === 'asc' ? 'desc' : 'asc' };
}

const KIND_LABELS: Record<AnatomyKind, string> = {
  feed: 'Feed',
  page_watch: 'Page watching',
  site_reader: 'Site reader',
  telegram: 'Telegram',
  x: 'X',
  reddit: 'Reddit',
  youtube: 'YouTube',
  saved: 'Saved',
};

export function anatomyName(row: Pick<SourceAnatomyRow, 'display_name' | 'address'>): string {
  return sourceLabel(row.display_name, row.address);
}

export function anatomyKindLabel(row: Pick<SourceAnatomyRow, 'kind'>): string {
  return KIND_LABELS[row.kind] ?? row.kind;
}

/** A short word and what it means. */
export interface Cell { text: string; title: string }

export function fullTextCell(row: Pick<SourceAnatomyRow, 'full_text'> & Partial<Pick<SourceAnatomyRow, 'feed_misses'>>): Cell {
  const cell = row.full_text === 'on' ? { text: 'on', title: 'Reads each post’s page for the whole text' }
    : row.full_text === 'off' ? { text: 'off', title: 'Full text is off: only what the feed carries' }
      : { text: 'in feed', title: 'The feed carries the whole post' };
  // 0138 F2: pages of it other posts linked that its feed never carried (each read once as its post).
  const missed = row.feed_misses ?? 0;
  if (!missed) return cell;
  return { text: `${cell.text} · partial`,
    title: `${cell.title}. Its feed missed ${formatCount(missed)} linked ${missed === 1 ? 'page' : 'pages'}; INSIGHT read ${missed === 1 ? 'it' : 'them'} once` };
}

export function watchCell(row: Pick<SourceAnatomyRow, 'watch_changes' | 'watched_pages'>): Cell {
  if (row.watch_changes === null) return { text: '—', title: 'Its kind cannot watch pages for changes' };
  if (!row.watch_changes) return { text: 'off', title: 'Its pages are not re-read for changes' };
  return { text: 'on', title: `Watches ${formatCount(row.watched_pages)} ${row.watched_pages === 1 ? 'page' : 'pages'} for changes` };
}

export function conditionalCell(row: Pick<SourceAnatomyRow, 'validators'>): Cell {
  if (row.validators === null) return { text: '—', title: 'Its kind reads in full every time' };
  if (row.validators) return { text: 'yes', title: 'An unchanged feed answers 304 and costs nothing' };
  return { text: 'no', title: 'Nothing stored to ask with yet: it reads in full until its feed sends validators' };
}

/** "6h", its next fetch on hover; "—" for a source that is off or never fetches. */
export function scheduleCell(row: Pick<SourceAnatomyRow, 'kind' | 'enabled' | 'interval_hours' | 'next_due_at'>, now: Date): Cell {
  if (row.kind === 'saved') return { text: '—', title: 'Saved pages come by hand; it is never fetched' };
  if (!row.enabled) return { text: 'off', title: 'Disabled: not fetched' };
  return { text: formatHours(row.interval_hours), title: `Fetched every ${formatHours(row.interval_hours)}; next ${formatDue(row.next_due_at, now)}` };
}

export function lastFetchFailed(row: Pick<SourceAnatomyRow, 'last_outcome'>): boolean {
  return row.last_outcome === 'error' || row.last_outcome === 'unavailable';
}

/** "3h", "failed 3h: HTTP 404" (the error in full on hover), "—" never. */
export function lastFetchCell(row: Pick<SourceAnatomyRow, 'last_attempt_at' | 'last_outcome' | 'last_error'>, now: Date): Cell {
  if (!row.last_attempt_at) return { text: '—', title: 'Never fetched' };
  const age = compactAge(row.last_attempt_at, now);
  const when = formatLocalDateTime(row.last_attempt_at) ?? '';
  if (!lastFetchFailed(row)) return { text: age, title: `Last fetched ${when}` };
  const error = row.last_error?.trim();
  return { text: error ? `failed ${age}: ${error}` : `failed ${age}`, title: `Failed ${when}${error ? `: ${error}` : ''}` };
}

const byName = (a: SourceAnatomyRow, b: SourceAnatomyRow) =>
  anatomyName(a).localeCompare(anatomyName(b), undefined, { sensitivity: 'base' });
const time = (iso: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? -Infinity : t;
};
const rank = (value: boolean | null) => (value === null ? 2 : value ? 0 : 1);
const FULL_TEXT_RANK = { on: 0, feed: 1, off: 2 } as const;
/** A source that is never fetched sorts after every interval. */
const interval = (row: SourceAnatomyRow) => (row.kind === 'saved' || !row.enabled ? Infinity : row.interval_hours);

const ASCENDING: Record<AnatomySort, (a: SourceAnatomyRow, b: SourceAnatomyRow) => number> = {
  name: byName,
  kind: (a, b) => anatomyKindLabel(a).localeCompare(anatomyKindLabel(b)),
  fullText: (a, b) => FULL_TEXT_RANK[a.full_text] - FULL_TEXT_RANK[b.full_text],
  watch: (a, b) => rank(a.watch_changes) - rank(b.watch_changes),
  conditional: (a, b) => rank(a.validators) - rank(b.validators),
  schedule: (a, b) => (interval(a) === interval(b) ? 0 : interval(a) < interval(b) ? -1 : 1),
  lastFetch: (a, b) => time(a.last_attempt_at) - time(b.last_attempt_at),
  ...Object.fromEntries(GIVES_COLUMNS.map((key) => [key, (a: SourceAnatomyRow, b: SourceAnatomyRow) => (a.recent[key] - b.recent[key]) || (a.all[key] - b.all[key])])) as Record<keyof SourceGives, (a: SourceAnatomyRow, b: SourceAnatomyRow) => number>,
};

/** The rows by one column in a direction; ties A to Z by name in every column. */
export function sortAnatomy(rows: readonly SourceAnatomyRow[], sort: AnatomySort, dir: AnatomyDir): SourceAnatomyRow[] {
  const sign = dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => sign * ASCENDING[sort](a, b) || byName(a, b));
}
