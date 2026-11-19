import { Suspense, lazy, useCallback, useMemo, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { toast } from 'sonner';

import { useApi } from '../../services/ApiContext';
import type { FeedItem, NewsMark, NewsOrder, NewsPage } from '../../services/api';
import { FEED_ROOT_KEY } from '../../hooks/useFeed';
import { useReaderMutations, type UnreadChange } from '../../hooks/useReaderMutations';
import type { ContextEntry } from '../../lib/feedContext';
import { errorMessage } from '../../lib/apiError';
import { formatCount, plural } from '../../lib/format';
import { inNewsParts, newsLine, newsPart } from '../../lib/news';
import { newsReadState } from '../../lib/story';
import { useAnnounce } from './LiveRegion';
import { PostList } from './FeedList';

const ConfirmDialog = lazy(() => import('../ops/ConfirmDialog'));
const UNDO_MS = 5_000;

/** Under the feed's root key: read, Later and Keep patch News like any cached feed. */
function newsKey(scope: string, mark: NewsMark, order: NewsOrder | undefined, unread: boolean) {
  return [...FEED_ROOT_KEY, 'news', scope, mark, order ?? 'default', unread ? 'unread' : 'all'];
}

/**
 * Issue 0238: the rows with an unread post, over the whole scope: the API's count when it answered, moved by what
 * was read or unread since in the rows loaded (a row the reader read is no longer counted, a row unread again is).
 */
function unreadRows(pages: readonly NewsPage[]): number | null {
  const counted = pages[0]?.unread_rows;
  if (typeof counted !== 'number') return null;
  let moved = 0;
  for (const item of pages.flatMap((page) => page.items)) {
    if (!item.news || typeof item.news.unread !== 'number') continue;
    moved += Number(!newsReadState(item).read) - Number(item.news.unread > 0);
  }
  return Math.max(0, counted + moved);
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
 * Issue 0208: Mark X's rows come ranked for the reader (significance, then coverage), the significant rows coverage
 * alone would bury first under "Notable for you"; "By coverage" shows the score's order, one click away, and back.
 */
export default function NewsList({ scope, unread = false, helpOpen, onHelpOpenChange, onUnreadDelta }: {
  scope: string;
  /** Issue 0238: News's Unread view: only the rows with an unread post. */
  unread?: boolean;
  helpOpen?: boolean;
  onHelpOpenChange?: (open: boolean) => void;
  onUnreadDelta?: (change: UnreadChange) => void;
}) {
  const api = useApi();
  const announce = useAnnounce();
  const mutations = useReaderMutations({ onUnreadDelta, scope });
  const [mark, setMark] = useState<NewsMark>('main');
  const [order, setOrder] = useState<NewsOrder | undefined>(undefined);   // undefined: the order the API's switch says
  const [confirm, setConfirm] = useState(false);
  const [confirmUsed, setConfirmUsed] = useState(false);
  if (confirm && !confirmUsed) setConfirmUsed(true);
  const query = useInfiniteQuery({
    queryKey: newsKey(scope, mark, order, unread),
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }): Promise<NewsPage> => api.getNews({ scope, cursor: pageParam, signal, mark, order, unread }),
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
  // Issue 0208: the other order of Mark X's rows, when the API says which one it sent.
  const shownOrder = !older && first?.mark === 'x' ? first.order : undefined;
  const otherOrder: NewsOrder | undefined = shownOrder === 'ranked' ? 'coverage' : shownOrder === 'coverage' ? 'ranked' : undefined;
  const unreadCount = useMemo(() => unreadRows(query.data?.pages ?? []), [query.data]);

  // Issue 0238: "Mark all News read" (the button, and Shift+A in News): every row the scope lists, after a confirm,
  // with Undo as the feed's mark-through has.
  const askMarkAll = useCallback(() => {
    if (unreadCount === 0) {
      announce('Nothing unread in News.');
      return;
    }
    setConfirm(true);
  }, [announce, unreadCount]);
  const confirmMarkAll = useCallback(async () => {
    setConfirm(false);
    try {
      const marked = await mutations.markAllNewsRead(scope, mark, query.data?.pages.flatMap((page) => page.items) ?? []);
      const message = `Marked ${plural(marked.length, 'post')} as read`;
      announce(message);
      toast.success(message, {
        duration: UNDO_MS,
        action: marked.length ? {
          label: 'Undo',
          onClick: () => {
            mutations.markUnread(marked).then(
              () => announce(`Restored ${plural(marked.length, 'post')} to unread`),
              (error: unknown) => {
                announce(errorMessage(error));
                toast.error(errorMessage(error));
              },
            );
          },
        } : undefined,
      });
    } catch (error) {
      announce(errorMessage(error));
      toast.error(errorMessage(error));
    }
  }, [announce, mark, mutations, query.data, scope]);
  const ranked = useMemo(() => ({ ...RANKED, rows: true, markAll: askMarkAll }), [askMarkAll]);

  return (
    <>
      {unreadCount !== null ? (
        <p data-testid="news-unread" className="px-1 pb-2 text-[0.8125rem] tabular-nums text-fg-3">
          {unreadCount ? `${formatCount(unreadCount)} ${unreadCount === 1 ? 'story' : 'stories'} with unread posts` : 'Every story read'}
          {unreadCount ? (
            <>
              {' · '}
              <button type="button" className="underline underline-offset-2 hover:text-fg-1" onClick={askMarkAll}>
                Mark all News read
              </button>
            </>
          ) : null}
        </p>
      ) : null}
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
          {otherOrder ? (
            <>
              {' · '}
              {shownOrder === 'coverage' ? 'By coverage. ' : null}
              <button type="button" className="underline underline-offset-2 hover:text-fg-1"
                onClick={() => setOrder(otherOrder)}>
                {otherOrder === 'coverage' ? 'By coverage' : 'Ranked for you'}
              </button>
            </>
          ) : null}
        </p>
      ) : null}
    <PostList
      feed={{ ...query, ...derived }}
      scope={scope}
      filter="all"
      view="stream"
      ranked={ranked}
      // A source alone is never News: it needs another source on the same story.
      emptyTitle={unread ? 'No unread News' : oneSource ? 'No News from this source yet' : 'No News yet'}
      emptyDescription={unread
        ? 'Every story here is read. A post that joins a story shows it here again.'
        : oneSource
        ? 'News needs 2+ sources on one story.'
        : 'A story shows here when 2 or more of your sources cover it within days.'}
      helpOpen={helpOpen}
      onHelpOpenChange={onHelpOpenChange}
      onUnreadDelta={onUnreadDelta}
    />
    <Suspense fallback={null}>
      {confirmUsed ? (
        <ConfirmDialog
          open={confirm}
          title="Mark all News read?"
          description={`Every post of the ${unreadCount === null ? '' : `${formatCount(unreadCount)} `}${unreadCount === 1 ? 'story' : 'stories'} with unread posts in this News. You can undo this for 5 seconds.`}
          confirmLabel="Mark read"
          onConfirm={() => void confirmMarkAll()}
          onCancel={() => setConfirm(false)}
        />
      ) : null}
    </Suspense>
    </>
  );
}
