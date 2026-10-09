import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import type { FeedFilter, FeedItem as FeedItemData, FeedView } from '../../services/api';
import { useFeed, type FeedFixture } from '../../hooks/useFeed';
import { usePrefetchPost } from '../../hooks/usePost';
import { useReaderMutations } from '../../hooks/useReaderMutations';
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts';
import { useShortcutPreference, type FeedDensity } from '../../hooks/useShortcutPreference';
import { feedNavigation, initialNavState, type NavAction, type NavIntent } from '../../lib/feedNavigation';
import { postHref, type FeedContext } from '../../lib/feedContext';
import { errorMessage } from '../../lib/apiError';
import { plural } from '../../lib/format';
import { feedDayHeading, feedDayKey } from '../../lib/feedDates';
import { EmptyState, ErrorState, LoadingState, Notice, FOCUS_RING, PRESS_FEEDBACK, type EmptyStateAction } from '../states';
import ConfirmDialog from '../ops/ConfirmDialog';
import FeedItem, { feedItemDomId } from './FeedItem';
import FeedGroup from './FeedGroup';
import ShortcutHelp from './ShortcutHelp';
import { useAnnounce } from './LiveRegion';

export interface FeedListProps {
  scope: string;
  filter: FeedFilter;
  view: FeedView;
  density: FeedDensity;
  fixture?: FeedFixture | null;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: EmptyStateAction;
  /** `f`: fetch the current scope. */
  onFetch?: () => void;
  /** Controlled shortcut help (the toolbar's ? button); uncontrolled when omitted. */
  helpOpen?: boolean;
  onHelpOpenChange?: (open: boolean) => void;
  /** Each local change of the unread total (for the "N new posts" pill). */
  onUnreadDelta?: (delta: number) => void;
}

const UNDO_MS = 5_000;

/**
 * The reader list (spec §F.3, §F.5, §F.6): renders the feed in either view, owns
 * the j/k selection (by post id, through the pure `feedNavigation` reducer), the
 * optimistic read/star toggles, mark-read-through with its confirmation and Undo,
 * and infinite loading (an IntersectionObserver sentinel plus a visible "Load
 * more" button). Results are announced in the page's live region.
 */
export default function FeedList({
  scope, filter, view, density, fixture = null, emptyTitle, emptyDescription, emptyAction,
  onFetch, helpOpen, onHelpOpenChange, onUnreadDelta,
}: FeedListProps) {
  const feed = useFeed({ scope, filter, view, fixture });
  const announce = useAnnounce();
  const navigate = useNavigate();
  const prefetch = usePrefetchPost();
  const mutations = useReaderMutations({ dryRun: Boolean(fixture), onUnreadDelta });
  const [shortcutsOn] = useShortcutPreference();
  const [internalHelp, setInternalHelp] = useState(false);
  const help = helpOpen ?? internalHelp;
  const setHelp = onHelpOpenChange ?? setInternalHelp;
  const [confirm, setConfirm] = useState<{ through: FeedItemData; count: number } | null>(null);

  const { items, groups, entries } = feed;
  const ids = useMemo(() => items.map((item) => item.id), [items]);
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
      () => announce(starred ? 'Starred' : 'Removed star'),
      (error: unknown) => {
        announce(errorMessage(error));
        toast.error(errorMessage(error));
      },
    );
  }, [announce, mutations]);

  const openItem = useCallback((item: FeedItemData) => {
    if (!item.read_at) {
      mutations.setRead(item, true).catch(() => {
        // Opening the post records the open (and sets read_at) server-side as well.
      });
    }
  }, [mutations]);

  const askMarkThrough = useCallback((item: FeedItemData) => {
    if (view === 'by_source') {
      announce('Mark read up to here works in the Stream view.');
      toast('Mark read up to here works in the Stream view.');
      return;
    }
    const end = items.findIndex((candidate) => candidate.id === item.id);
    const count = items.slice(0, end + 1).filter((candidate) => !candidate.read_at).length;
    if (!count) {
      announce('Nothing unread up to here.');
      return;
    }
    setConfirm({ through: item, count });
  }, [announce, items, view]);

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
  const latest = useRef({ itemsById, itemHref, toggleRead, toggleStar, openItem, askMarkThrough, feed, navigate });
  latest.current = { itemsById, itemHref, toggleRead, toggleStar, openItem, askMarkThrough, feed, navigate };

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
    A: () => dispatch({ type: 'markThrough' }),
    f: onFetch,
    '?': () => setHelp(true),
  }, { enabled: !confirm && !help, singleKeys: shortcutsOn });

  // Prefetch the selected post and the one after it, so `o` opens from cache.
  const selectedId = nav.selectedId;
  useEffect(() => {
    if (fixture || !selectedId) return;
    prefetch(selectedId);
    const index = ids.indexOf(selectedId);
    if (index >= 0 && index + 1 < ids.length) prefetch(ids[index + 1]);
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
    density,
    selectedId,
    onSelect: select,
    onOpen: openItem,
    onToggleRead: toggleRead,
    onToggleStar: toggleStar,
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
        <div role="feed" aria-label="Posts" aria-busy={isFetchingNextPage} className={view === 'by_source' ? 'flex flex-col gap-6' : `flex flex-col ${density === 'compact' ? 'gap-1' : 'gap-2'}`}>
          {view === 'by_source'
            ? groups.map((group) => (
              <FeedGroup key={group.source_id} group={group} tabbableId={tabbableId} itemHref={itemHref} {...shared} />
            ))
            : items.map((item, index) => {
              const day = feedDayKey(item.sort_at);
              const newDay = index === 0 || day !== feedDayKey(items[index - 1].sort_at);
              return (
                <Fragment key={item.id}>
                  {newDay ? (
                    <h2 className={`px-1 pb-0.5 text-[0.8125rem] font-semibold tracking-[-0.006em] text-fg-2 ${index === 0 ? '' : 'pt-5'}`}>
                      {feedDayHeading(item.sort_at)}
                    </h2>
                  ) : null}
                  <FeedItem
                    item={item}
                    selected={item.id === selectedId}
                    tabbable={item.id === tabbableId}
                    href={itemHref(item)}
                    onMarkThrough={askMarkThrough}
                    {...shared}
                  />
                </Fragment>
              );
            })}
        </div>
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
