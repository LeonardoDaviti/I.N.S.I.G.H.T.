import { folderReadPath } from '../../lib/feedContext';

/**
 * The information architecture (design docs system/information-architecture.md): the nav words in the top bar,
 * and the destinations the ⌘K quick switcher can jump to. Navigation only:
 * search over posts stays deferred (spec §F.2).
 *
 * Reading-only (analysis off, reading-finish R3 and Decision 2): the app has
 * three places, feed / sources / post. The top bar is `feed / sources`; tracks
 * are read from the reader rail and reached in ⌘K one entry per track. With
 * analysis on, the five words and the full switcher list stay as they were.
 */
export type NavKey = 'feed' | 'tracks' | 'briefings' | 'sources' | 'ingestion' | 'blog';

export interface NavItem {
  key: NavKey;
  label: string;
  to: string;
}

/** The analysis-on top bar: five words, then the blog. */
export const NAV_ITEMS: readonly NavItem[] = [
  { key: 'feed', label: 'feed', to: '/' },
  { key: 'tracks', label: 'tracks', to: '/tracks' },
  { key: 'briefings', label: 'briefings', to: '/briefing' },
  { key: 'sources', label: 'sources', to: '/settings/sources' },
  { key: 'ingestion', label: 'ingestion', to: '/ingestion' },
  { key: 'blog', label: 'blog', to: '/blog' },
];

const READING_KEYS: ReadonlySet<NavKey> = new Set(['feed', 'sources', 'blog']);

/** The top bar's words: six with analysis on, `feed / sources / blog` without it. */
export function navItems(analysisEnabled: boolean): readonly NavItem[] {
  return analysisEnabled ? NAV_ITEMS : NAV_ITEMS.filter((item) => READING_KEYS.has(item.key));
}

/** Which nav word is current for a pathname; null when none is (an unknown route).
 *  Reading-only, a track page belongs to the feed: tracks live in the reader rail. */
export function activeNavKey(pathname: string, analysisEnabled = true): NavKey | null {
  const path = pathname.replace(/\/+$/, '') || '/';
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}/`);
  if (path === '/' || under('/read') || under('/posts')) return 'feed';
  if (under('/tracks') || under('/experts')) return analysisEnabled ? 'tracks' : 'feed';
  if (under('/briefing') || under('/stories') || under('/inbox')) return 'briefings';
  if (under('/settings')) return 'sources';
  if (under('/ingestion')) return 'ingestion';
  if (under('/blog')) return 'blog';
  return null;
}

export interface Destination {
  id: string;
  label: string;
  /** Where it lives, shown muted on the right ("feed", "sources"). */
  group: string;
  to: string;
  /** Extra words the filter matches ("health", "cadence"). */
  keywords?: string;
}

/** The analysis-on switcher list. */
export const DESTINATIONS: readonly Destination[] = [
  { id: 'feed-unread', label: 'Unread', group: 'feed', to: '/', keywords: 'home reader feed inbox new' },
  { id: 'feed-starred', label: 'Starred', group: 'feed', to: '/?filter=starred', keywords: 'saved favourites star' },
  { id: 'feed-all', label: 'All posts', group: 'feed', to: '/?filter=all', keywords: 'everything posts' },
  { id: 'feed-by-source', label: 'By source', group: 'feed', to: '/?view=by_source', keywords: 'grouped sources view' },
  { id: 'tracks', label: 'Tracks', group: 'tracks', to: '/tracks', keywords: 'folders experts topics' },
  { id: 'briefing', label: 'Daily briefing', group: 'briefings', to: '/briefing', keywords: 'digest today summary' },
  { id: 'briefing-topics', label: 'Topic briefing', group: 'briefings', to: '/briefing/topics', keywords: 'topics clusters' },
  { id: 'briefing-vertical', label: 'Vertical briefing', group: 'briefings', to: '/briefing/vertical', keywords: 'source timeline' },
  { id: 'stories', label: 'Stories', group: 'briefings', to: '/stories', keywords: 'threads narrative timeline' },
  { id: 'inbox', label: 'Analyst inbox', group: 'briefings', to: '/inbox', keywords: 'triage candidates review' },
  { id: 'sources', label: 'Sources', group: 'sources', to: '/settings/sources', keywords: 'settings feeds add source' },
  { id: 'sources-health', label: 'Source health', group: 'sources', to: '/settings/sources?tab=health', keywords: 'cadence backoff failing due schedule' },
  { id: 'ingestion', label: 'Ingestion', group: 'ingestion', to: '/ingestion', keywords: 'run cycle fetch jobs report' },
  { id: 'blog', label: 'Blog', group: 'blog', to: '/blog', keywords: 'posts articles engineering learning' },
];

/**
 * The Design Studio (design docs, specimens, prototypes): reached only from
 * ⌘K, never from the top bar, with analysis on or off (Design Studio D8).
 */
export const DESIGN_STUDIO: Destination = {
  id: 'design-studio',
  label: 'Design studio',
  group: 'design',
  to: '/design',
  keywords: 'principles system tokens components specimens prototypes decisions',
};

/** True inside a Design Studio frame (`/design/frame/…`), whose page runs in a memory router. */
export function insideDesignFrame(): boolean {
  return typeof window !== 'undefined' && window.location.pathname.startsWith('/design/frame/');
}

/** Switcher ids that belong to analysis (briefings, stories, inbox) or to the
 *  tracks list page, which reading-only drops (Decision 2). */
const ANALYSIS_DESTINATION_IDS: ReadonlySet<string> = new Set([
  'tracks', 'briefing', 'briefing-topics', 'briefing-vertical', 'stories', 'inbox',
]);

export interface TrackRef {
  id: string;
  name: string;
}

/**
 * What ⌘K can jump to. With analysis on, the list above unchanged. Reading-only:
 * the feed and sources entries, then one entry per track (to `/read/folder/:id`,
 * the reader scoped to it) in the order given. Either way the design studio
 * comes last, unless `studio` is false (⌘K inside one of the studio's own frames).
 */
export function destinations(
  analysisEnabled: boolean,
  tracks: readonly TrackRef[] = [],
  { studio = true }: { studio?: boolean } = {},
): Destination[] {
  const last = studio ? [DESIGN_STUDIO] : [];
  if (analysisEnabled) return [...DESTINATIONS, ...last];
  // Reading-only, ingestion is a tab under sources (reading-finish R3).
  const reading = DESTINATIONS
    .filter((item) => !ANALYSIS_DESTINATION_IDS.has(item.id))
    .map((item) => (item.id === 'ingestion' ? { ...item, group: 'sources', to: '/settings/sources?tab=ingestion' } : item));
  const trackItems = tracks.map((track): Destination => ({
    id: `track-${track.id}`,
    label: track.name,
    group: 'tracks',
    to: folderReadPath(track.id),
    keywords: 'track folder',
  }));
  // Tracks go after the feed entries; with none after the feed, at the end.
  const afterFeed = reading.findIndex((item) => item.group !== 'feed');
  const at = afterFeed === -1 ? reading.length : afterFeed;
  return [...reading.slice(0, at), ...trackItems, ...reading.slice(at), ...last];
}

/** Case-insensitive, every word must match label, group or keywords. Order is kept. */
export function filterDestinations(query: string, items: readonly Destination[] = DESTINATIONS): Destination[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [...items];
  return items.filter((item) => {
    const haystack = `${item.label} ${item.group} ${item.keywords ?? ''}`.toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/** ⌘K / Ctrl+K anywhere (also from inputs: it carries a modifier). */
export function isQuickSwitcherShortcut(event: KeyboardEvent): boolean {
  return (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'k';
}
