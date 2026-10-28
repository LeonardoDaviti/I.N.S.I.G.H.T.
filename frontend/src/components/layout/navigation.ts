import { folderReadPath } from '../../lib/feedContext';

/**
 * The information architecture (design docs system/information-architecture.md): the nav words in the top bar,
 * and the destinations the ⌘K quick switcher can jump to. Navigation only:
 * search over posts stays deferred (spec §F.2).
 *
 * The app has three places, feed / sources / post (reading-finish R3 and
 * Decision 2). The top bar is `feed / sources / blog`; tracks are read from the
 * reader rail and reached in ⌘K one entry per track.
 */
export type NavKey = 'feed' | 'sources' | 'blog';

export interface NavItem {
  key: NavKey;
  label: string;
  to: string;
}

/** The top bar's words. */
export const NAV_ITEMS: readonly NavItem[] = [
  { key: 'feed', label: 'feed', to: '/' },
  { key: 'sources', label: 'sources', to: '/settings/sources' },
  { key: 'blog', label: 'blog', to: '/blog' },
];

/** Which nav word is current for a pathname; null when none is (an unknown route).
 *  A track page belongs to the feed: tracks live in the reader rail. */
export function activeNavKey(pathname: string): NavKey | null {
  const path = pathname.replace(/\/+$/, '') || '/';
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}/`);
  if (path === '/' || under('/read') || under('/posts') || under('/tracks')) return 'feed';
  if (under('/settings')) return 'sources';
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

/** The fixed switcher entries; the tracks go in after the feed ones. Ingestion is a tab under sources (reading-finish R3). */
export const DESTINATIONS: readonly Destination[] = [
  { id: 'feed-main', label: 'Main feed', group: 'feed', to: '/', keywords: 'home reader feed inbox new unread all posts' },
  { id: 'feed-later', label: 'Later', group: 'feed', to: '/?filter=later', keywords: 'read later saved bookmarks queue' },
  { id: 'feed-by-source', label: 'By source', group: 'feed', to: '/?view=by_source', keywords: 'grouped sources view' },
  { id: 'sources', label: 'Sources', group: 'sources', to: '/settings/sources', keywords: 'settings feeds add source health cadence backoff failing due schedule' },
  { id: 'ingestion', label: 'Ingestion', group: 'sources', to: '/settings/sources?tab=ingestion', keywords: 'run cycle fetch jobs report' },
  { id: 'blog', label: 'Blog', group: 'blog', to: '/blog', keywords: 'posts articles engineering learning' },
];

/**
 * The Design Studio (design docs, specimens, prototypes): reached only from
 * ⌘K, never from the top bar (Design Studio D8).
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

export interface TrackRef {
  id: string;
  name: string;
}

/**
 * What ⌘K can jump to: the feed entries, then one entry per track (to
 * `/read/folder/:id`, the reader scoped to it) in the order given, then the rest.
 * The design studio comes last, unless `studio` is false (⌘K inside one of the
 * studio's own frames).
 */
export function destinations(
  tracks: readonly TrackRef[] = [],
  { studio = true }: { studio?: boolean } = {},
): Destination[] {
  const last = studio ? [DESIGN_STUDIO] : [];
  const trackItems = tracks.map((track): Destination => ({
    id: `track-${track.id}`,
    label: track.name,
    group: 'tracks',
    to: folderReadPath(track.id),
    keywords: 'track folder',
  }));
  const at = DESTINATIONS.findIndex((item) => item.group !== 'feed');
  return [...DESTINATIONS.slice(0, at), ...trackItems, ...DESTINATIONS.slice(at), ...last];
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
