import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import type { FeedFilter, FeedItem as FeedItemData, FeedView } from '../../services/api';
import { useFeed, type FeedFixture } from '../../hooks/useFeed';
import { usePrefetchPost } from '../../hooks/usePost';
import { useReaderMutations, type UnreadChange } from '../../hooks/useReaderMutations';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';
import { useShortcutPreference } from '../../hooks/useShortcutPreference';
import { feedNavigation, initialNavState, type NavAction, type NavIntent } from '../../lib/feedNavigation';
import { postHref, type FeedContext } from '../../lib/feedContext';
import { errorMessage } from '../../lib/apiError';
import { plural } from '../../lib/format';
import { feedDayHeading, feedDayKey } from '../../lib/dates';
import { EmptyState, ErrorState, LoadingState, Notice, FOCUS_RING, PRESS_FEEDBACK, type EmptyStateAction } from '../states';
import ConfirmDialog from '../ops/ConfirmDialog';
import FeedItem from './FeedItem';
import { feedItemDomId } from '../../lib/feedItem';
import { recallSelection, rememberSelection } from '../../lib/readerSelection';
import FeedGroup from './FeedGroup';
import ShortcutHelp from './ShortcutHelp';
import { useAnnounce } from './LiveRegion';

export interface FeedListProps {
  scope: string;
  filter: FeedFilter;
  view: FeedView;
  fixture?: FeedFixture | null;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: EmptyStateAction;
  /** Controlled shortcut help (the toolbar's ? button); uncontrolled when omitted. */
  helpOpen?: boolean;
  onHelpOpenChange?: (open: boolean) => void;
  /** Each local change applied to the cached unread counts (for the "N new posts" pill). */
  onUnreadDelta?: (change: UnreadChange) => void;
}

const UNDO_MS = 5_000;
const PREFETCH_DELAY_MS = 150;

/**
 * The reader list (spec §F.3, §F.5, §F.6): renders the feed in either view, owns
 * the j/k selection (by post id, through the pure `feedNavigation` reducer), the
 * optimistic read, Later and Keep toggles, mark-read-through with its confirmation and Undo,
 * and infinite loading (an IntersectionObserver sentinel plus a visible "Load
 * more" button). Results are announced in the page's live region.
 */
function FeedList({
  scope, filter, view, fixture = null, emptyTitle, emptyDescription, emptyAction,
  helpOpen, onHelpOpenChange, onUnreadDelta,
}: FeedListProps) {
  const feed = useFeed({ scope, filter, view, fixture });
  const announce = useAnnounce();
  const navigate = useNavigate();
  const prefetch = usePrefetchPost();
  const mutations = useReaderMutations({ dryRun: Boolean(fixture), onUnreadDelta, scope });
  const [shortcutsOn] = useShortcutPreference();
  const [internalHelp, setInternalHelp] = useState(false);
  const help = helpOpen ?? internalHelp;
  const setHelp = onHelpOpenChange ?? setInternalHelp;
  const [confirm, setConfirm] = useState<{ through: FeedItemData; count: number } | null>(null);

  const { items, groups, entries } = feed;
  // A read or star patch replaces `items` but not its ids: key the ids on their
  // joined value so the selection reducer is not re-synced (and the list not
  // re-rendered once more) on every toggle.
  const idsKey = useMemo(() => items.map((item) => item.id).join('\n'), [items]);
  const ids = useMemo(() => (idsKey ? idsKey.split('\n') : []), [idsKey]);
  // Day headers for the stream: each row's day heading, and whether the row is the
  // first of its day (where the header is drawn), computed once per items array.
  // Later is in the order saved, not by day: no headers, and each row shows its date.
  const byDay = filter !== 'later';
  const days = useMemo(() => {
    let previous: string | null = null;
    return items.map((item) => {
      const key = feedDayKey(item.sort_at);
      const first = byDay && key !== previous;
      previous = key;
      return { label: feedDayHeading(item.sort_at), first };
    });
  }, [byDay, items]);
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const itemsById = useMemo(() => new Map(items.map((item) => [item.id, item])), [items]);
  const pageCursorById = useMemo(() => new Map(entries.map((entry) => [entry.id, entry.pageCursor])), [entries]);

  const contextFor = useCallback((item: FeedItemData): FeedContext => (
    view === 'by_source'
      // A group's posts are the newest of their source, so they sit on that source's first page.
      ? { scope: `source:${item.source_id}`, filter, cursor: null }
      : { scope, filter, cursor: pageCursorById.get(item.id) ?? null }
  ), [filter, pageCursorById, scope, view]);
  const itemHref = useCallback((item: FeedItemData) => postHref(item.id, contextFor(item)), [contextFor]);

  // ---- actions ----
  const toggleRead = useCallback((item: FeedItemData) => {
    const read = !item.read_at;
    mutations.setRead(item, read).then(
      () => announce(read ? 'Marked as read' : 'Marked as unread'),
      (error: unknown) => {
        announce(errorMessage(error));
        toast.error(errorMessage(error));
      },
    );
  }, [announce, mutations]);

  const toggleStar = useCallback((item: FeedItemData) => {
    const starred = !item.starred_at;
    mutations.setStarred(item, starred).then(
      () => announce(starred ? 'Kept' : 'No longer kept'),
      (error: unknown) => {
        announce(errorMessage(error));
        toast.error(errorMessage(error));
      },
    );
  }, [announce, mutations]);

  const toggleLater = useCallback((item: FeedItemData) => {
    const later = !item.later_at;
    mutations.setLater(item, later).then(
      () => announce(later ? 'Saved for later' : 'Removed from Later'),
      (error: unknown) => {
        announce(errorMessage(error));
        toast.error(errorMessage(error));
      },
    );
  }, [announce, mutations]);

  const openItem = useCallback((item: FeedItemData) => {
    // Coming back to the feed (u, Back) selects the post that was read last.
    rememberSelection(item.id);
    if (!item.read_at) {
      // Opening is not finishing: a post in Later stays there (issue 0022).
      mutations.setRead(item, true, { keepLater: true }).catch(() => {
        // Opening the post records the open (and sets read_at) server-side as well.
      });
    }
  }, [mutations]);

  const askMarkThrough = useCallback((item: FeedItemData) => {
    if (view === 'by_source' || filter === 'later') {
      // Later is in the order saved, not the feed's: "up to here" would mean something else.
      const message = filter === 'later' ? 'Mark read up to here does not work in Later.' : 'Mark read up to here works in the Stream view.';
      announce(message);
      toast(message);
      return;
    }
    const loaded = itemsRef.current;
    const end = loaded.findIndex((candidate) => candidate.id === item.id);
    const count = loaded.slice(0, end + 1).filter((candidate) => !candidate.read_at).length;
    if (!count) {
      announce('Nothing unread up to here.');
      return;
    }
    setConfirm({ through: item, count });
  }, [announce, filter, view]);

  const confirmMarkThrough = useCallback(async () => {
    const pending = confirm;
    setConfirm(null);
    if (!pending || !items.length) return;
    try {
      const marked = await mutations.markReadThrough(scope, pending.through, items[0], items);
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
  }, [announce, confirm, items, mutations, scope]);

  // ---- keyboard selection ----
  const [nav, setNav] = useState(() => initialNavState());
  const navRef = useRef(nav);
  const latest = useRef({ itemsById, itemHref, toggleRead, toggleStar, toggleLater, openItem, askMarkThrough, feed, navigate });
  latest.current = { itemsById, itemHref, toggleRead, toggleStar, toggleLater, openItem, askMarkThrough, feed, navigate };

  const runIntent = useCallback((intent: NavIntent | null) => {
    if (!intent) return;
    const ctx = latest.current;
    if (intent.kind === 'focus') {
      const element = document.getElementById(feedItemDomId(intent.id));
      element?.focus({ preventScroll: true });
      element?.scrollIntoView?.({ block: 'nearest' });
      return;
    }
    if (intent.kind === 'loadMore') {
      if (ctx.feed.hasNextPage && !ctx.feed.isFetchingNextPage) void ctx.feed.fetchNextPage();
      return;
    }
    const item = ctx.itemsById.get(intent.id);
    if (!item) return;
    if (intent.kind === 'open') {
      ctx.openItem(item);
      ctx.navigate(ctx.itemHref(item));
    } else if (intent.kind === 'toggleRead') ctx.toggleRead(item);
    else if (intent.kind === 'toggleStar') ctx.toggleStar(item);
    else if (intent.kind === 'toggleLater') ctx.toggleLater(item);
    else if (intent.kind === 'markThrough') ctx.askMarkThrough(item);
  }, []);

  const dispatch = useCallback((action: NavAction) => {
    const next = feedNavigation(navRef.current, action);
    navRef.current = next;
    setNav(next);
    runIntent(next.intent);
  }, [runIntent]);

  useEffect(() => {
    dispatch({ type: 'sync', ids, hasMore: Boolean(feed.hasNextPage) });
  }, [dispatch, feed.hasNextPage, ids]);

  // Back from a post: select (and scroll to) the post read last, once it is loaded.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !ids.length) return;
    restored.current = true;
    const last = recallSelection();
    if (last && ids.includes(last)) dispatch({ type: 'select', id: last, focus: true });
  }, [dispatch, ids]);

  const select = useCallback((id: string) => {
    if (navRef.current.selectedId !== id) dispatch({ type: 'select', id });
  }, [dispatch]);

  useKeyboardShortcuts({
    j: () => dispatch({ type: 'next' }),
    k: () => dispatch({ type: 'prev' }),
    o: () => dispatch({ type: 'open' }),
    Enter: () => dispatch({ type: 'open' }),
    m: () => dispatch({ type: 'toggleRead' }),
    s: () => dispatch({ type: 'toggleStar' }),
    l: () => dispatch({ type: 'toggleLater' }),
    A: () => dispatch({ type: 'markThrough' }),
    '?': () => setHelp(true),
  }, { enabled: !confirm && !help, singleKeys: shortcutsOn });

  // Prefetch the selected post and the one after it, so `o` opens from cache.
  // Debounced: a held j passes through rows faster than they could be read, and
  // fetching each of them would only churn the network and the query cache.
  const selectedId = nav.selectedId;
  useEffect(() => {
    if (fixture || !selectedId) return undefined;
    const timer = window.setTimeout(() => {
      prefetch(selectedId);
      const index = ids.indexOf(selectedId);
      if (index >= 0 && index + 1 < ids.length) prefetch(ids[index + 1]);
    }, PREFETCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [fixture, ids, prefetch, selectedId]);

  // ---- infinite loading ----
  const sentinel = useRef<HTMLDivElement | null>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage, isFetchNextPageError } = feed;
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasNextPage || isFetchNextPageError || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver((entriesSeen) => {
      if (entriesSeen.some((entry) => entry.isIntersecting) && !isFetchingNextPage) void fetchNextPage();
    }, { rootMargin: '600px 0px' });
    observer.observe(node);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchNextPageError, isFetchingNextPage]);

  // ---- render ----
  const shared = {
    selectedId,
    onSelect: select,
    onOpen: openItem,
    onToggleRead: toggleRead,
    onToggleStar: toggleStar,
    onToggleLater: toggleLater,
  };
  const tabbableId = selectedId ?? ids[0] ?? null;

  let body;
  if (feed.isPending) {
    body = <LoadingState label="Loading feed" rows={6} />;
  } else if (feed.isError && !feed.data) {
    body = <ErrorState title="Could not load the feed" error={feed.error} onRetry={() => void feed.refetch()} />;
  } else if (!items.length && !groups.length) {
    body = (
      <EmptyState
        title={emptyTitle ?? 'Nothing here yet'}
        description={emptyDescription}
        action={emptyAction}
      />
    );
  } else {
    body = (
      <>
        {view === 'by_source' ? (
          // One section per source, each with its heading; the rows are articles inside.
          <div aria-label="Posts by source" role="region" aria-busy={isFetchingNextPage} className="flex flex-col gap-6">
            {groups.map((group) => (
              <FeedGroup key={group.source_id} group={group} tabbableId={tabbableId} itemHref={itemHref} {...shared} />
            ))}
          </div>
        ) : (
          // An ARIA feed owns articles only: the day headers are drawn for the eye
          // (aria-hidden) and each row reads its own day out with its time.
          <div role="feed" aria-label="Posts" aria-busy={isFetchingNextPage} className={"flex flex-col gap-2"}>
            {items.map((item, index) => (
              <Fragment key={item.id}>
                {days[index].first ? (
                  <div aria-hidden="true" data-day-header className={`px-1 pb-0.5 text-[0.8125rem] font-semibold tracking-[-0.006em] text-fg-2 ${index === 0 ? '' : 'pt-5'}`}>
                    {days[index].label}
                  </div>
                ) : null}
                <FeedItem
                  item={item}
                  selected={item.id === selectedId}
                  tabbable={item.id === tabbableId}
                  href={itemHref(item)}
                  dateColumn={byDay ? 'time' : 'date'}
                  dayLabel={byDay ? days[index].label : undefined}
                  position={index + 1}
                  setSize={hasNextPage ? -1 : items.length}
                  showSource={!scope.startsWith('source:')}
                  {...shared}
                />
              </Fragment>
            ))}
          </div>
        )}
        <div ref={sentinel} aria-hidden="true" className="h-px" />
        <div className="flex flex-col items-center gap-2 py-6">
          {isFetchNextPageError ? (
            <Notice
              tone="error"
              title="Could not load more posts"
              message={errorMessage(feed.error)}
              action={{ label: 'Retry', onClick: () => void fetchNextPage() }}
              className="w-full"
            />
          ) : hasNextPage ? (
            <button
              type="button"
              onClick={() => void fetchNextPage()}
              disabled={isFetchingNextPage}
              className={`inline-flex min-h-[44px] items-center justify-center rounded-md border border-line-strong bg-transparent px-5 text-sm font-medium text-fg hover:bg-raised disabled:opacity-60 ${PRESS_FEEDBACK} ${FOCUS_RING}`}
            >
              {isFetchingNextPage ? 'Loading…' : 'Load more'}
            </button>
          ) : (
            <p className="text-[0.8125rem] text-fg-3">You’ve reached the end.</p>
          )}
        </div>
      </>
    );
  }

  return (
    <>
      {body}
      <ShortcutHelp open={help} onOpenChange={setHelp} />
      <ConfirmDialog
        open={Boolean(confirm)}
        title={confirm ? `Mark ${plural(confirm.count, 'post')} as read?` : ''}
        description={confirm ? (
          <>
            Everything unread from the newest post down to <span className="font-medium text-fg [overflow-wrap:anywhere]">“{confirm.through.title}”</span>. You can undo this for 5 seconds.
          </>
        ) : null}
        confirmLabel="Mark read"
        onConfirm={() => void confirmMarkThrough()}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}

/** Memoised: a counts refetch re-renders the reader page, not the whole list. */
export default memo(FeedList);
