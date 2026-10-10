import { useQuery, useQueryClient } from '@tanstack/react-query';

import type { Api, FeedPage } from '../services/api';
import { FEED_PAGE_SIZE, feedKey, type FeedData } from './useFeed';
import { neighborsAt, type ContextEntry, type FeedContext, type SortedEntry } from '../lib/feedContext';

export interface PostNeighbors {
  prev: ContextEntry | null;
  next: ContextEntry | null;
  /** The context's feed page is still loading. */
  loading: boolean;
}

const NONE: PostNeighbors = { prev: null, next: null, loading: false };

/** The reader's cached stream for the context, when it holds the current post. */
function cachedEntries(data: FeedData | undefined, postId: string): { entries: SortedEntry[]; nextCursor: string | null } | null {
  if (!data?.pages.length) return null;
  const entries: SortedEntry[] = [];
  data.pages.forEach((page, index) => {
    if ('groups' in page) return;
    const pageCursor = (data.pageParams[index] as string | null | undefined) ?? null;
    for (const item of page.items) entries.push({ id: item.id, sortAt: item.sort_at, pageCursor });
  });
  if (!entries.some((entry) => entry.id === postId)) return null;
  return { entries, nextCursor: data.pages[data.pages.length - 1]?.next_cursor ?? null };
}

function pageEntries(page: FeedPage | undefined, pageCursor: string | null): SortedEntry[] {
  return (page?.items ?? []).map((item) => ({ id: item.id, sortAt: item.sort_at, pageCursor }));
}

/**
 * Prev/next on the post page (spec §F.3, §F.5), in the order of the feed the post
 * was opened from (`?ctx=`). The reader's cached feed answers when it holds the
 * post; otherwise (a reload) the context's page is fetched. At the end of the
 * loaded order the next page is fetched to find `next`.
 */
export function usePostNeighbors(
  api: Api,
  ctx: FeedContext | null,
  current: { id: string; sortAt: string | null } | null,
): PostNeighbors {
  const queryClient = useQueryClient();
  const cached = ctx && current
    ? cachedEntries(queryClient.getQueryData<FeedData>(feedKey(ctx.scope, ctx.filter, 'stream')), current.id)
    : null;
  const usable = Boolean(ctx && current?.sortAt);

  const page = useQuery({
    queryKey: ['post-context', ctx?.scope, ctx?.filter, ctx?.cursor ?? null],
    queryFn: ({ signal }) => api.getFeed({ scope: ctx!.scope, filter: ctx!.filter, cursor: ctx!.cursor, limit: FEED_PAGE_SIZE, signal }),
    enabled: usable && !cached,
    staleTime: 5 * 60_000,
  });

  const source = cached ?? (page.data ? { entries: pageEntries(page.data, ctx?.cursor ?? null), nextCursor: page.data.next_cursor } : null);
  const around = source && current?.sortAt ? neighborsAt(source.entries, { id: current.id, sortAt: current.sortAt }, source.nextCursor) : null;
  const loadNext = around?.loadNext ?? null;

  const nextPage = useQuery({
    queryKey: ['post-context', ctx?.scope, ctx?.filter, loadNext],
    queryFn: ({ signal }) => api.getFeed({ scope: ctx!.scope, filter: ctx!.filter, cursor: loadNext, limit: FEED_PAGE_SIZE, signal }),
    enabled: usable && Boolean(loadNext),
    staleTime: 5 * 60_000,
  });

  if (!usable) return NONE;
  if (!around) return { ...NONE, loading: page.isPending };
  const first = nextPage.data?.items.find((item) => item.id !== current?.id);
  const next = around.next ?? (first && loadNext ? { id: first.id, pageCursor: loadNext } : null);
  return { prev: around.prev, next, loading: false };
}
