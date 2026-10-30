import { useMemo } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { FeedItem, FeedPage } from '../../services/api';
import { FEED_ROOT_KEY } from '../../hooks/useFeed';
import type { UnreadChange } from '../../hooks/useReaderMutations';
import type { ContextEntry } from '../../lib/feedContext';
import { newsLine } from '../../lib/news';
import { PostList } from './FeedList';

/** Under the feed's root key: read, Later and Keep patch News like any cached feed. */
function newsKey(scope: string) {
  return [...FEED_ROOT_KEY, 'news', scope];
}

/** News's two parts (issue 0051), by when a story began. */
function newsPart(item: FeedItem): string {
  return item.news?.part === 'recent' ? 'Last 48 hours' : 'Earlier this week';
}

/** A News row's line: what its score is made of, then who covered it. */
function storyLine(item: FeedItem): string | undefined {
  return item.news && item.story ? newsLine(item.news, item.story) : undefined;
}

const RANKED = { name: 'News', sectionOf: newsPart, storyLine };

/**
 * View news (issue 0051): this week's stories that 2 or more of your sources covered, of the
 * Main feed or a track, in two parts ("Last 48 hours", "Earlier this week"), each by score,
 * then the newest. A story is its lead's row, its line saying what the score is made of and
 * who covered it, its other posts one click away; reading it marks it as the feed does (0050).
 * One page, loaded when shown; it never reorders under you.
 */
export default function NewsList({ scope, helpOpen, onHelpOpenChange, onUnreadDelta }: {
  scope: string;
  helpOpen?: boolean;
  onHelpOpenChange?: (open: boolean) => void;
  onUnreadDelta?: (change: UnreadChange) => void;
}) {
  const api = useApi();
  const query = useInfiniteQuery({
    queryKey: newsKey(scope),
    initialPageParam: null as string | null,
    queryFn: ({ signal }): Promise<FeedPage> => api.getNews({ scope, signal }),
    getNextPageParam: () => undefined,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const derived = useMemo(() => {
    const items: FeedItem[] = query.data?.pages.flatMap((page) => page.items) ?? [];
    const entries: ContextEntry[] = items.map((item) => ({ id: item.id, pageCursor: null }));
    return { items, groups: [], entries };
  }, [query.data]);

  return (
    <PostList
      feed={{ ...query, ...derived }}
      scope={scope}
      filter="all"
      view="stream"
      ranked={RANKED}
      emptyTitle="No news this week"
      emptyDescription="A story shows here when 2 or more of your sources cover it within days."
      helpOpen={helpOpen}
      onHelpOpenChange={onHelpOpenChange}
      onUnreadDelta={onUnreadDelta}
    />
  );
}
