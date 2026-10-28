import { useMemo } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { FeedItem, FeedPage } from '../services/api';
import type { ContextEntry } from '../lib/feedContext';
import type { SearchState } from '../lib/search';
import { FEED_ROOT_KEY } from './useFeed';

/** Each row's matching line is read from its text, so a page is smaller than the feed's. */
export const SEARCH_PAGE_SIZE = 20;

/** Under the feed's root key: read, Later and Keep patch the results like any cached feed. */
export function searchKey(state: SearchState) {
  return [...FEED_ROOT_KEY, 'search', state.q.trim(), state.scope ?? '', state.filter, state.days ?? 0, state.order];
}

/**
 * Search results (issue 0040) as the reader's list reads them: pages of feed rows, each with
 * its matching line. Nothing is fetched while the query is empty. A search shown again
 * within 30 seconds comes from the cache; later it asks again.
 */
export function useSearch(state: SearchState) {
  const api = useApi();
  const query = useInfiniteQuery({
    queryKey: searchKey(state),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }): Promise<FeedPage> => api.searchPosts({
      q: state.q.trim(), scope: state.scope, filter: state.filter, days: state.days, order: state.order,
      cursor: pageParam, limit: SEARCH_PAGE_SIZE, signal,
    }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(state.q.trim()),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const derived = useMemo(() => {
    const items: FeedItem[] = [];
    const entries: ContextEntry[] = [];
    const data = query.data;
    data?.pages.forEach((page, index) => {
      const pageCursor = (data.pageParams[index] as string | null | undefined) ?? null;
      for (const item of page.items) {
        items.push(item);
        entries.push({ id: item.id, pageCursor });
      }
    });
    return { items, groups: [], entries };
  }, [query.data]);

  return { ...query, ...derived };
}
