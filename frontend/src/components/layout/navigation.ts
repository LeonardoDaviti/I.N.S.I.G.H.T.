/**
 * The information architecture (design doc §9): five nav words in the top bar,
 * and the destinations the ⌘K quick switcher can jump to. Navigation only:
 * search over posts stays deferred (spec §F.2).
 */
export type NavKey = 'feed' | 'tracks' | 'briefings' | 'sources' | 'ingestion';

export interface NavItem {
  key: NavKey;
  label: string;
  to: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { key: 'feed', label: 'feed', to: '/' },
  { key: 'tracks', label: 'tracks', to: '/tracks' },
  { key: 'briefings', label: 'briefings', to: '/briefing' },
  { key: 'sources', label: 'sources', to: '/settings/sources' },
  { key: 'ingestion', label: 'ingestion', to: '/ingestion' },
];

/** Which nav word is current for a pathname; null when none is (an unknown route). */
export function activeNavKey(pathname: string): NavKey | null {
  const path = pathname.replace(/\/+$/, '') || '/';
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}/`);
  if (path === '/' || under('/read') || under('/posts')) return 'feed';
  if (under('/tracks') || under('/experts')) return 'tracks';
  if (under('/briefing') || under('/stories') || under('/inbox')) return 'briefings';
  if (under('/settings')) return 'sources';
  if (under('/ingestion')) return 'ingestion';
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
];

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
