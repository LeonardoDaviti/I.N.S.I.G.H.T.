import { folderReadPath } from '../../lib/feedContext';

/**
 * The information architecture: the top bar's nav words (`feed / sources / blog`) and the destinations the ⌘K
 * quick switcher jumps to, plus its "Search posts…". Tracks are read from the reader rail and reached in ⌘K.
 */
export type NavKey = 'feed' | 'sources' | 'blog' | 'markx';

export interface NavItem {
  key: NavKey;
  label: string;
  to: string;
}

/** The blog and the Design Studio are dev-only pages (never in the production bundle), so their nav word and ⌘K
 *  entries are too. */
export const DEV_PAGES: boolean = import.meta.env.DEV;

/** The top bar's words. */
export const NAV_ITEMS: readonly NavItem[] = [
  { key: 'feed', label: 'feed', to: '/' },
  { key: 'sources', label: 'sources', to: '/settings/sources' },
  ...(DEV_PAGES ? [{ key: 'blog', label: 'blog', to: '/blog' } as const] : []),
];

/** Mark X's page: one more word, only while INSIGHT_MARKX is on. */
export const MARKX_NAV: NavItem = { key: 'markx', label: 'mark x', to: '/markx' };

/** The top bar's words, with Mark X's when it is on. */
export function navItems(markx: boolean): readonly NavItem[] {
  return markx ? [...NAV_ITEMS, MARKX_NAV] : NAV_ITEMS;
}

/** Which nav word is current for a pathname; null for an unknown route. A track page and search belong to the
 *  feed. */
export function activeNavKey(pathname: string): NavKey | null {
  const path = pathname.replace(/\/+$/, '') || '/';
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}/`);
  if (path === '/' || under('/read') || under('/reading') || under('/posts') || under('/tracks') || under('/search')) return 'feed';
  if (under('/settings')) return 'sources';
  if (under('/blog')) return 'blog';
  if (under('/markx')) return 'markx';
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

/** The fixed switcher entries; the tracks go in after the feed ones. */
export const DESTINATIONS: readonly Destination[] = [
  { id: 'feed-main', label: 'Main feed', group: 'feed', to: '/', keywords: 'home reader feed inbox new unread all posts' },
  { id: 'feed-later', label: 'Later', group: 'feed', to: '/?filter=later', keywords: 'read later saved bookmarks queue' },
  { id: 'feed-by-source', label: 'By source', group: 'feed', to: '/?view=by_source', keywords: 'grouped sources view' },
  { id: 'reading', label: 'Your reading', group: 'feed', to: '/reading', keywords: 'history opened read time stats seen usage depth' },
  { id: 'sources', label: 'Sources', group: 'sources', to: '/settings/sources', keywords: 'settings feeds add source health cadence backoff failing due schedule' },
  { id: 'ingestion', label: 'Ingestion', group: 'sources', to: '/settings/sources?tab=ingestion', keywords: 'run cycle fetch jobs report' },
  { id: 'data', label: 'Export data', group: 'sources', to: '/settings/sources?tab=data', keywords: 'export backup dump download database zip csv sources.json' },
  ...(DEV_PAGES ? [{ id: 'blog', label: 'Blog', group: 'blog', to: '/blog', keywords: 'posts articles engineering learning' }] : []),
  { id: 'save-page', label: 'Save a page…', group: 'save', to: '/save', keywords: 'save page url link bookmark bookmarklet keep saved paste' },
];

/** The Design Studio: reached only from ⌘K, never from the top bar. */
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
 * What ⌘K can jump to: the feed entries, one entry per track (in the order given), then the rest; the design
 * studio last, unless `studio` is false (inside a studio frame) or the build is a production one.
 */
/** Mark X's page in ⌘K, only while it is on. */
export const MARKX_DESTINATION: Destination = {
  id: 'markx', label: 'Mark X', group: 'mark x', to: '/markx', keywords: 'shadow haiku stories news judge worker briefing entities',
};

export function destinations(
  tracks: readonly TrackRef[] = [],
  { studio = true, markx = false }: { studio?: boolean; markx?: boolean } = {},
): Destination[] {
  const last = [...(markx ? [MARKX_DESTINATION] : []), ...(studio && DEV_PAGES ? [DESIGN_STUDIO] : [])];
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
