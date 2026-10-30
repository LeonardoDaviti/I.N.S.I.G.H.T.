/**
 * The search page's URL (issue 0040): `/search?q=&scope=&filter=&days=&order=`, so a
 * search survives a reload and Back. No `scope` searches every post; the scope you searched
 * from (the Main feed `all`, a track, a source) is the first chip and can be taken off.
 * Later, Kept, News and Classics (one at a time), and the last week, month or year, are the
 * other chips.
 */
import type { SearchFilter, SearchOrder } from '../services/api';
import { isValidScope } from './feedContext.ts';

export interface SearchState {
  q: string;
  scope: string | null;
  filter: SearchFilter;
  days: number | null;
  order: SearchOrder;
}

/** The date chips; none pressed is any time. */
export const SEARCH_DAYS: ReadonlyArray<{ days: number; label: string }> = [
  { days: 7, label: 'Last week' },
  { days: 30, label: 'Last month' },
  { days: 365, label: 'Last year' },
];

/** The search in a URL's query; anything unknown falls back to its default. */
export function parseSearch(params: URLSearchParams): SearchState {
  const scope = params.get('scope');
  const filter = params.get('filter');
  const days = Number(params.get('days'));
  return {
    q: params.get('q') ?? '',
    scope: scope && isValidScope(scope) ? scope : null,
    // The lists to search, one at a time: Later, Kept, News and Classics (issue 0056).
    filter: /^(later|starred|news|classics)$/.test(filter ?? '') ? filter as SearchFilter : 'all',
    days: SEARCH_DAYS.some((choice) => choice.days === days) ? days : null,
    order: params.get('order') === 'best' ? 'best' : 'newest',
  };
}

/** `/search` with only what differs from the defaults. */
export function searchHref(state: Partial<SearchState>): string {
  const qs = new URLSearchParams();
  const q = state.q?.trim();
  if (q) qs.set('q', q);
  if (state.scope) qs.set('scope', state.scope);
  if (state.filter && state.filter !== 'all') qs.set('filter', state.filter);
  if (state.days) qs.set('days', String(state.days));
  if (state.order === 'best') qs.set('order', 'best');
  const text = qs.toString();
  return text ? `/search?${text}` : '/search';
}

/** True when a chip narrows the search (a scope, Later or Kept, a date). */
export function isNarrowed(state: SearchState): boolean {
  return Boolean(state.scope || state.filter !== 'all' || state.days);
}
