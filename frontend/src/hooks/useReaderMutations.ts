import { useCallback, useMemo } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { FeedItem, SourcesHealthResponse, UnreadCounts } from '../services/api';
import { SOURCES_HEALTH_KEY } from './useSourcesHealth';
import { feedCursorFor } from '../lib/feedContext';
import { FEED_ROOT_KEY, UNREAD_COUNTS_KEY, type AnyFeedPage, type FeedData } from './useFeed';

/** The most ids one PUT /api/feed/read takes (the backend's MAX_READ_BATCH). */
export const READ_BATCH = 500;

function patchPage(page: AnyFeedPage, ids: ReadonlySet<string>, patch: Partial<FeedItem>): AnyFeedPage {
  const patchItems = (items: FeedItem[]) => items.map((item) => (ids.has(item.id) ? { ...item, ...patch } : item));
  if ('groups' in page) return { ...page, groups: page.groups.map((group) => ({ ...group, items: patchItems(group.items) })) };
  return { ...page, items: patchItems(page.items) };
}

/** Apply `patch` to the given posts in every cached feed (both views, every scope). */
export function patchFeeds(queryClient: QueryClient, ids: ReadonlySet<string>, patch: Partial<FeedItem>) {
  queryClient.setQueriesData<FeedData>({ queryKey: [...FEED_ROOT_KEY] }, (data) => (
    data?.pages ? { ...data, pages: data.pages.map((page) => patchPage(page, ids, patch)) } : data
  ));
}

/** The cached copy of each post, from whichever feed holds it. */
export function findFeedItems(queryClient: QueryClient, ids: readonly string[]): Map<string, FeedItem> {
  const wanted = new Set(ids);
  const found = new Map<string, FeedItem>();
  for (const [, data] of queryClient.getQueriesData<FeedData>({ queryKey: [...FEED_ROOT_KEY] })) {
    for (const page of data?.pages ?? []) {
      const items = 'groups' in page ? page.groups.flatMap((group) => group.items) : page.items;
      for (const item of items) if (wanted.has(item.id) && !found.has(item.id)) found.set(item.id, item);
    }
  }
  return found;
}

/** What a local read change did to the cached unread counts: the shift actually
 *  applied to the total and to each source and folder count. */
export interface UnreadChange {
  total: number;
  bySource: Record<string, number>;
  byFolder: Record<string, number>;
}

const NO_CHANGE: UnreadChange = { total: 0, bySource: {}, byFolder: {} };

/** The part of `change` that moved `scope`'s count (`all`, `source:<id>`, `folder:<id>`). */
export function scopeDelta(change: UnreadChange, scope: string): number {
  if (scope === 'all') return change.total;
  const [kind, id] = scope.split(':');
  return (kind === 'folder' ? change.byFolder[id] : change.bySource[id]) ?? 0;
}

function diff(before: Record<string, number> = {}, after: Record<string, number> = {}): Record<string, number> {
  const out: Record<string, number> = {};
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const delta = (after[key] ?? 0) - (before[key] ?? 0);
    if (delta) out[key] = delta;
  }
  return out;
}

/** Shift the unread counts by `deltaBySource` (clamped at 0) and report what moved.
 *  Folder counts follow the sources' folder membership from the cached health rows,
 *  when they are loaded; a folder count that did not move reports no change.
 *  `scopeFolderId` is the track the posts were read in: every one of them belongs
 *  to it, so its count moves even before the health rows have loaded. */
function patchCounts(queryClient: QueryClient, deltaBySource: Map<string, number>, scopeFolderId: string | null): UnreadChange {
  if (!sum(deltaBySource)) return NO_CHANGE;
  // A counts refetch already in flight would land on top of the optimistic patch.
  void queryClient.cancelQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
  const health = queryClient.getQueryData<SourcesHealthResponse>([...SOURCES_HEALTH_KEY]);
  const membership = new Map((health?.rows ?? []).map((row) => [row.source_id, (row.folders ?? []).map((folder) => folder.id)]));
  const foldersOf = (sourceId: string) => {
    const ids = new Set(membership.get(sourceId) ?? []);
    if (scopeFolderId) ids.add(scopeFolderId);
    return ids;
  };
  let change: UnreadChange = NO_CHANGE;
  queryClient.setQueriesData<UnreadCounts>({ queryKey: [...UNREAD_COUNTS_KEY] }, (counts) => {
    if (!counts || typeof counts.total !== 'number') return counts;
    const bySource = { ...counts.by_source };
    const byFolder = { ...counts.by_folder };
    for (const [sourceId, delta] of deltaBySource) {
      bySource[sourceId] = Math.max(0, (bySource[sourceId] ?? 0) + delta);
      for (const folderId of foldersOf(sourceId)) byFolder[folderId] = Math.max(0, (byFolder[folderId] ?? 0) + delta);
    }
    const next = { ...counts, total: Math.max(0, counts.total + sum(deltaBySource)), by_source: bySource, by_folder: byFolder };
    // Every cached copy (live, or the one dev fixture) moves the same way: report the first.
    if (change === NO_CHANGE) {
      change = { total: next.total - counts.total, bySource: diff(counts.by_source, bySource), byFolder: diff(counts.by_folder, byFolder) };
    }
    return next;
  });
  return change;
}

function negate(deltas: Map<string, number>): Map<string, number> {
  return new Map([...deltas].map(([key, delta]) => [key, -delta]));
}

function isChange(change: UnreadChange) {
  return change.total !== 0 || Object.keys(change.bySource).length > 0 || Object.keys(change.byFolder).length > 0;
}

/** Unread delta per source when `items` all become read (`read`) or unread. */
function readDeltas(items: Iterable<Pick<FeedItem, 'source_id' | 'read_at'>>, read: boolean): Map<string, number> {
  const deltas = new Map<string, number>();
  for (const item of items) {
    if (read === Boolean(item.read_at)) continue;
    deltas.set(item.source_id, (deltas.get(item.source_id) ?? 0) + (read ? -1 : 1));
  }
  return deltas;
}

function sum(deltas: Map<string, number>) {
  let total = 0;
  for (const delta of deltas.values()) total += delta;
  return total;
}

/**
 * Optimistic read, star and mark-read-through for the reader (spec §F.3): the
 * cached feeds and counts change at once and the counts are refetched afterwards.
 * A failed request undoes only its own patch (the inverse change), so other
 * optimistic changes made meanwhile survive; the error is rethrown for the caller
 * to announce. `onUnreadDelta` reports each change actually applied to the cached
 * counts, so the "N new posts" pill can tell our own reads from new arrivals.
 * `scope` is the feed the changes come from (`all`, `folder:<id>`, `source:<id>`).
 * `dryRun` (the dev-only `?data=` fixtures) skips the API.
 */
export function useReaderMutations({ dryRun = false, onUnreadDelta, scope = 'all' }: {
  dryRun?: boolean; onUnreadDelta?: (change: UnreadChange) => void; scope?: string;
} = {}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const scopeFolderId = scope.startsWith('folder:') ? scope.slice('folder:'.length) : null;

  const refreshCounts = useCallback(() => {
    if (!dryRun) void queryClient.invalidateQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
  }, [dryRun, queryClient]);

  const shiftCounts = useCallback((deltas: Map<string, number>) => {
    const change = patchCounts(queryClient, deltas, scopeFolderId);
    if (isChange(change)) onUnreadDelta?.(change);
  }, [onUnreadDelta, queryClient, scopeFolderId]);

  /** Mark `items` read or unread in the cache; resolves the undo for exactly this change. */
  const applyRead = useCallback((items: FeedItem[], read: boolean) => {
    const deltas = readDeltas(items, read);
    const previous = items.map((item) => [item.id, item.read_at ?? null] as const);
    patchFeeds(queryClient, new Set(items.map((item) => item.id)), { read_at: read ? new Date().toISOString() : null });
    shiftCounts(deltas);
    return () => {
      for (const [id, readAt] of previous) patchFeeds(queryClient, new Set([id]), { read_at: readAt });
      shiftCounts(negate(deltas));
    };
  }, [queryClient, shiftCounts]);

  const setRead = useCallback(async (item: FeedItem, read: boolean) => {
    const undo = applyRead([item], read);
    try {
      if (!dryRun) await api.setPostsRead([item.id], read);
    } catch (error) {
      undo();
      throw error;
    } finally {
      refreshCounts();
    }
  }, [api, applyRead, dryRun, refreshCounts]);

  const setStarred = useCallback(async (item: FeedItem, starred: boolean) => {
    const previous = item.starred_at ?? null;
    patchFeeds(queryClient, new Set([item.id]), { starred_at: starred ? new Date().toISOString() : null });
    try {
      if (!dryRun) await api.setPostStarred(item.id, starred);
    } catch (error) {
      patchFeeds(queryClient, new Set([item.id]), { starred_at: previous });
      throw error;
    }
  }, [api, dryRun, queryClient]);

  /** Mark read from `newest` (the first loaded item) down to `through`. Resolves the ids it marked. */
  const markReadThrough = useCallback(async (scope: string, through: FeedItem, newest: FeedItem, loaded: FeedItem[]) => {
    let ids: string[];
    if (dryRun) {
      const end = loaded.findIndex((item) => item.id === through.id);
      ids = loaded.slice(0, end + 1).filter((item) => !item.read_at).map((item) => item.id);
    } else {
      const result = await api.markReadThrough(scope, feedCursorFor(through), feedCursorFor(newest));
      ids = result.ids ?? [];
    }
    applyRead([...findFeedItems(queryClient, ids).values()], true);
    refreshCounts();
    return ids;
  }, [api, applyRead, dryRun, queryClient, refreshCounts]);

  /** The Undo of a mark-through: back to unread. A mark-through has no size limit but
   *  PUT /api/feed/read takes at most READ_BATCH ids, so a big undo goes in batches, one
   *  after another; a failed batch undoes the whole local change. */
  const markUnread = useCallback(async (ids: string[]) => {
    if (!ids.length) return;
    const undo = applyRead([...findFeedItems(queryClient, ids).values()], false);
    try {
      if (!dryRun) {
        for (let start = 0; start < ids.length; start += READ_BATCH) {
          await api.setPostsRead(ids.slice(start, start + READ_BATCH), false);
        }
      }
    } catch (error) {
      undo();
      throw error;
    } finally {
      refreshCounts();
    }
  }, [api, applyRead, dryRun, queryClient, refreshCounts]);

  /** The post page recorded an open (the server marks the post read): mirror it in the cache. */
  const noteOpened = useCallback((postId: string) => {
    const item = findFeedItems(queryClient, [postId]).get(postId);
    if (item && !item.read_at) applyRead([item], true);
    refreshCounts();
  }, [applyRead, queryClient, refreshCounts]);

  // A stable object: the list's toggle handlers depend on it, and a new one per
  // render would re-render every memoised row on each key press.
  return useMemo(
    () => ({ setRead, setStarred, markReadThrough, markUnread, noteOpened }),
    [setRead, setStarred, markReadThrough, markUnread, noteOpened],
  );
}
