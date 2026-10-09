import { useMemo } from 'react';
import { useInfiniteQuery, useQuery, type InfiniteData } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { FeedFilter, FeedGroup, FeedGroupsPage, FeedItem, FeedPage, FeedView, UnreadCounts } from '../services/api';
import type { ContextEntry } from '../lib/feedContext';

export const FEED_PAGE_SIZE = 30;
export const UNREAD_COUNTS_KEY = ['unread-counts'] as const;

export type AnyFeedPage = FeedPage | FeedGroupsPage;
export type FeedData = InfiniteData<AnyFeedPage, string | null>;

/** Dev-only `?data=` fixtures replace the API at the data boundary (break-ui). */
export interface FeedFixture {
  name: string;
  /** Pages in order; page `n` is served for cursor `fixture:<n>`. */
  stream: FeedPage[];
  groups: FeedGroupsPage[];
  counts: UnreadCounts;
}

export function feedKey(scope: string, filter: FeedFilter, view: FeedView, fixtureName?: string) {
  return fixtureName ? ['feed', scope, filter, view, 'fixture', fixtureName] : ['feed', scope, filter, view];
}

function fixturePage(fixture: FeedFixture, view: FeedView, cursor: string | null): AnyFeedPage {
  const pages = view === 'by_source' ? fixture.groups : fixture.stream;
  const index = cursor ? Number(cursor.replace('fixture:', '')) : 0;
  const page = pages[index] ?? pages[pages.length - 1];
  return { ...page, next_cursor: index + 1 < pages.length ? `fixture:${index + 1}` : null } as AnyFeedPage;
}

/**
 * The reader feed (spec §F.3): `useInfiniteQuery(['feed', scope, filter, view])`
 * with `staleTime: Infinity` and no refetch on focus, so nothing reorders the list
 * while it is being read. New posts surface through the unread counts instead.
 */
export function useFeed({ scope, filter, view, fixture }: {
  scope: string; filter: FeedFilter; view: FeedView; fixture?: FeedFixture | null;
}) {
  const api = useApi();
  const query = useInfiniteQuery({
    queryKey: feedKey(scope, filter, view, fixture?.name),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }): Promise<AnyFeedPage> => {
      if (fixture) return Promise.resolve(fixturePage(fixture, view, pageParam));
      const params = { scope, filter, cursor: pageParam, limit: view === 'by_source' ? 20 : FEED_PAGE_SIZE, signal };
      return view === 'by_source' ? api.getFeedGroups(params) : api.getFeed(params);
    },
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const derived = useMemo(() => {
    const items: FeedItem[] = [];
    const groups: FeedGroup[] = [];
    const entries: ContextEntry[] = [];
    const data = query.data;
    data?.pages.forEach((page, index) => {
      const pageCursor = (data.pageParams[index] as string | null | undefined) ?? null;
      if ('groups' in page) {
        for (const group of page.groups) {
          groups.push(group);
          for (const item of group.items) {
            items.push(item);
            entries.push({ id: item.id, pageCursor });
          }
        }
      } else {
        for (const item of page.items) {
          items.push(item);
          entries.push({ id: item.id, pageCursor });
        }
      }
    });
    const lastPage = data?.pages[data.pages.length - 1];
    return { items, groups, entries, nextCursor: lastPage?.next_cursor ?? null };
  }, [query.data]);

  return { ...query, ...derived };
}

/** Unread counts for the rail badges and the "N new posts" pill. */
export function useUnreadCounts(fixture?: FeedFixture | null) {
  const api = useApi();
  return useQuery({
    queryKey: fixture ? [...UNREAD_COUNTS_KEY, 'fixture', fixture.name] : [...UNREAD_COUNTS_KEY],
    queryFn: fixture ? async () => fixture.counts : () => api.getUnreadCounts(),
    staleTime: 30_000,
  });
}

/** The unread count of one scope: total, a folder's or a source's. */
export function scopeUnreadCount(counts: UnreadCounts | undefined, scope: string): number | null {
  if (!counts) return null;
  if (scope === 'all') return counts.total;
  const [kind, id] = scope.split(':');
  const table = kind === 'folder' ? counts.by_folder : counts.by_source;
  return table?.[id] ?? 0;
}
