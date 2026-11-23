/**
 * The search page's URL, `/search?q=&scope=&filter=&days=&order=`, so a search survives a reload and Back. No
 * `scope` searches every post; no `order` is best match for 2+ words, newest for one.
 */
import type { SearchFilter, SearchOrder } from '../services/api';
import { isValidScope } from './feedContext.ts';

export interface SearchState {
  q: string;
  scope: string | null;
  filter: SearchFilter;
  days: number | null;
  /** null: by the words (searchOrder); else the order chosen, kept in the URL. */
  order: SearchOrder | null;
}

/** As the backend's default_order: 2+ words (not `or`, not an excluded -word) order by best match. */
export function defaultOrder(q: string): SearchOrder {
  const words = q.split(/\s+/).filter((w) => w && w.toLowerCase() !== 'or' && !w.startsWith('-') && /[\p{L}\p{N}]/u.test(w));
  return words.length >= 2 ? 'best' : 'newest';
}

/** The order the results are in: the one chosen, else the words'. */
export function searchOrder(state: Pick<SearchState, 'q' | 'order'>): SearchOrder {
  return state.order ?? defaultOrder(state.q);
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
  const order = params.get('order');
  return {
    q: params.get('q') ?? '',
    scope: scope && isValidScope(scope) ? scope : null,
    // The lists to search, one at a time.
    filter: /^(later|starred|history|news|classics)$/.test(filter ?? '') ? filter as SearchFilter : 'all',
    days: SEARCH_DAYS.some((choice) => choice.days === days) ? days : null,
    order: order === 'best' || order === 'newest' ? order : null,
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
  if (state.order) qs.set('order', state.order);
  const text = qs.toString();
  return text ? `/search?${text}` : '/search';
}

/** True when a chip narrows the search (a scope, Later or Kept, a date). */
export function isNarrowed(state: SearchState): boolean {
  return Boolean(state.scope || state.filter !== 'all' || state.days);
}
