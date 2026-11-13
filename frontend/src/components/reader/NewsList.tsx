import { useMemo, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { FeedItem, NewsMark, NewsPage } from '../../services/api';
import { FEED_ROOT_KEY } from '../../hooks/useFeed';
import type { UnreadChange } from '../../hooks/useReaderMutations';
import type { ContextEntry } from '../../lib/feedContext';
import { inNewsParts, newsLine, newsPart } from '../../lib/news';
import { PostList } from './FeedList';

/** Under the feed's root key: read, Later and Keep patch News like any cached feed. */
function newsKey(scope: string, mark: NewsMark) {
  return [...FEED_ROOT_KEY, 'news', scope, mark];
}

/** News's parts (issues 0051, 0077), by when a story began: the last 48 hours, this week, then each earlier week. */
function sectionOf(item: FeedItem): string {
  return item.news ? newsPart(item.news).label : 'This week';
}

/** A News row's line: what its score is made of, then who covered it. */
function storyLine(item: FeedItem): string | undefined {
  return item.news && item.story ? newsLine(item.news, item.story) : undefined;
}

const RANKED = { name: 'News', sectionOf, storyLine };

/**
 * View news (issues 0051, 0077): the stories that 2 or more of your sources covered, of the
 * Main feed, a track or one source, in parts ("Last 48 hours", "This week", then "Week of
 * 12 Oct" for each earlier week), each in the API's order (by score). On a source's page a
 * row's line first says the source's part ("Started it", "Covered", ...) when the API sends it. A story is its lead's row, its line saying what the score is made of and
 * who covered it, its other posts one click away; reading it marks it as the feed does (0050).
 * Loaded when shown, a page at a time as you scroll (issue 0195); it never reorders under you.
 * Issue 0205: the rows are Mark X's (the main News); "Older News view" shows Mark IX's, one click away, and back. When
 * Mark X has no rows yet the API answers Mark IX's itself and the page says so in one line.
 */
export default function NewsList({ scope, helpOpen, onHelpOpenChange, onUnreadDelta }: {
  scope: string;
  helpOpen?: boolean;
  onHelpOpenChange?: (open: boolean) => void;
  onUnreadDelta?: (change: UnreadChange) => void;
}) {
  const api = useApi();
  const [mark, setMark] = useState<NewsMark>('main');
  const query = useInfiniteQuery({
    queryKey: newsKey(scope, mark),
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }): Promise<NewsPage> => api.getNews({ scope, cursor: pageParam, signal, mark }),
    // Issue 0195: News comes a page at a time (the API's first 50 rows, then next_cursor), loaded ahead as the feed's.
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const derived = useMemo(() => {
    const items: FeedItem[] = inNewsParts(query.data?.pages.flatMap((page) => page.items) ?? []);
    const entries: ContextEntry[] = items.map((item) => ({ id: item.id, pageCursor: null }));
    return { items, groups: [], entries };
  }, [query.data]);
  const oneSource = scope.startsWith('source:');
  const first = query.data?.pages[0];
  const older = mark === 'ix';
  // The older view is offered only when the main News is Mark X's (a fallback already shows the older rows).
  const canSwitch = older || (first !== undefined && first.mark === 'x');

  return (
    <>
      {first?.fallback && first.note && !older ? (
        <p role="status" className="px-1 pb-2 text-[0.8125rem] text-fg-3">{first.note}</p>
      ) : null}
      {canSwitch ? (
        <p className="px-1 pb-2 text-[0.8125rem] text-fg-3">
          {older ? 'Older News view (Mark IX). ' : null}
          <button type="button" className="underline underline-offset-2 hover:text-fg-1"
            onClick={() => setMark(older ? 'main' : 'ix')}>
            {older ? 'Back to News' : 'Older News view'}
          </button>
        </p>
      ) : null}
    <PostList
      feed={{ ...query, ...derived }}
      scope={scope}
      filter="all"
      view="stream"
      ranked={RANKED}
      // A source alone is never News: it needs another source on the same story.
      emptyTitle={oneSource ? 'No News from this source yet' : 'No News yet'}
      emptyDescription={oneSource
        ? 'News needs 2+ sources on one story.'
        : 'A story shows here when 2 or more of your sources cover it within days.'}
      helpOpen={helpOpen}
      onHelpOpenChange={onHelpOpenChange}
      onUnreadDelta={onUnreadDelta}
    />
    </>
  );
}
