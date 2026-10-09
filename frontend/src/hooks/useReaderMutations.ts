import { useCallback } from 'react';
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query';

import { useApi } from '../services/ApiContext';
import type { FeedItem, SourcesHealthResponse, UnreadCounts } from '../services/api';
import { SOURCES_HEALTH_KEY } from './useSourcesHealth';
import { feedCursorFor } from '../lib/feedContext';
import { UNREAD_COUNTS_KEY, type AnyFeedPage, type FeedData } from './useFeed';

type Snapshot = Array<[QueryKey, unknown]>;

function patchPage(page: AnyFeedPage, ids: ReadonlySet<string>, patch: Partial<FeedItem>): AnyFeedPage {
  const patchItems = (items: FeedItem[]) => items.map((item) => (ids.has(item.id) ? { ...item, ...patch } : item));
  if ('groups' in page) return { ...page, groups: page.groups.map((group) => ({ ...group, items: patchItems(group.items) })) };
  return { ...page, items: patchItems(page.items) };
}

/** Apply `patch` to the given posts in every cached feed (both views, every scope). */
function patchFeeds(queryClient: QueryClient, ids: ReadonlySet<string>, patch: Partial<FeedItem>) {
  queryClient.setQueriesData<FeedData>({ queryKey: ['feed'] }, (data) => (
    data?.pages ? { ...data, pages: data.pages.map((page) => patchPage(page, ids, patch)) } : data
  ));
}

/** The cached copy of each post, from whichever feed holds it. */
export function findFeedItems(queryClient: QueryClient, ids: readonly string[]): Map<string, FeedItem> {
  const wanted = new Set(ids);
  const found = new Map<string, FeedItem>();
  for (const [, data] of queryClient.getQueriesData<FeedData>({ queryKey: ['feed'] })) {
    for (const page of data?.pages ?? []) {
      const items = 'groups' in page ? page.groups.flatMap((group) => group.items) : page.items;
      for (const item of items) if (wanted.has(item.id) && !found.has(item.id)) found.set(item.id, item);
    }
  }
  return found;
}

/** Shift the unread counts by `deltaBySource` (clamped at 0). Folder counts follow the
 *  sources' folder membership from the cached health rows, when they are loaded. */
function patchCounts(queryClient: QueryClient, deltaBySource: Map<string, number>) {
  let total = 0;
  for (const delta of deltaBySource.values()) total += delta;
  if (!total) return;
  const health = queryClient.getQueryData<SourcesHealthResponse>([...SOURCES_HEALTH_KEY]);
  const foldersOf = new Map((health?.rows ?? []).map((row) => [row.source_id, row.folders ?? []]));
  queryClient.setQueriesData<UnreadCounts>({ queryKey: [...UNREAD_COUNTS_KEY] }, (counts) => {
    if (!counts || typeof counts.total !== 'number') return counts;
    const bySource = { ...counts.by_source };
    const byFolder = { ...counts.by_folder };
    for (const [sourceId, delta] of deltaBySource) {
      bySource[sourceId] = Math.max(0, (bySource[sourceId] ?? 0) + delta);
      for (const folder of foldersOf.get(sourceId) ?? []) byFolder[folder.id] = Math.max(0, (byFolder[folder.id] ?? 0) + delta);
    }
    return { ...counts, total: Math.max(0, counts.total + total), by_source: bySource, by_folder: byFolder };
  });
}

function snapshot(queryClient: QueryClient): Snapshot {
  return [
    ...queryClient.getQueriesData({ queryKey: ['feed'] }),
    ...queryClient.getQueriesData({ queryKey: [...UNREAD_COUNTS_KEY] }),
  ];
}

function restore(queryClient: QueryClient, saved: Snapshot) {
  for (const [key, data] of saved) queryClient.setQueryData(key, data);
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
 * cached feeds and counts change at once, roll back when the request fails (the
 * error is rethrown for the caller to announce), and the counts are refetched
 * afterwards. `onUnreadDelta` reports each local change of the unread total, so
 * the "N new posts" pill can tell our own mark-unread from new arrivals.
 * `dryRun` (the dev-only `?data=` fixtures) skips the API.
 */
export function useReaderMutations({ dryRun = false, onUnreadDelta }: {
  dryRun?: boolean; onUnreadDelta?: (delta: number) => void;
} = {}) {
  const api = useApi();
  const queryClient = useQueryClient();

  const refreshCounts = useCallback(() => {
    if (!dryRun) void queryClient.invalidateQueries({ queryKey: [...UNREAD_COUNTS_KEY] });
  }, [dryRun, queryClient]);

  const applyRead = useCallback((items: FeedItem[], read: boolean) => {
    const deltas = readDeltas(items, read);
    patchFeeds(queryClient, new Set(items.map((item) => item.id)), { read_at: read ? new Date().toISOString() : null });
    patchCounts(queryClient, deltas);
    const delta = sum(deltas);
    if (delta) onUnreadDelta?.(delta);
    return delta;
  }, [onUnreadDelta, queryClient]);

  const setRead = useCallback(async (item: FeedItem, read: boolean) => {
    const saved = snapshot(queryClient);
    const delta = applyRead([item], read);
    try {
      if (!dryRun) await api.setPostRead(item.id, read);
    } catch (error) {
      restore(queryClient, saved);
      if (delta) onUnreadDelta?.(-delta);
      throw error;
    } finally {
      refreshCounts();
    }
  }, [api, applyRead, dryRun, onUnreadDelta, queryClient, refreshCounts]);

  const setStarred = useCallback(async (item: FeedItem, starred: boolean) => {
    const saved = snapshot(queryClient);
    patchFeeds(queryClient, new Set([item.id]), { starred_at: starred ? new Date().toISOString() : null });
    try {
      if (!dryRun) await api.setPostStarred(item.id, starred);
    } catch (error) {
      restore(queryClient, saved);
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

  /** The Undo of a mark-through: back to unread. */
  const markUnread = useCallback(async (ids: string[]) => {
    if (!ids.length) return;
    const saved = snapshot(queryClient);
    const delta = applyRead([...findFeedItems(queryClient, ids).values()], false);
    try {
      if (!dryRun) await api.setPostsRead(ids, false);
    } catch (error) {
      restore(queryClient, saved);
      if (delta) onUnreadDelta?.(-delta);
      throw error;
    } finally {
      refreshCounts();
    }
  }, [api, applyRead, dryRun, onUnreadDelta, queryClient, refreshCounts]);

  return { setRead, setStarred, markReadThrough, markUnread };
}
