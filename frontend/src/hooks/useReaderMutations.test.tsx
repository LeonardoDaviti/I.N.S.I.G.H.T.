import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';

import { scopeDelta, useReaderMutations, type UnreadChange } from './useReaderMutations';
import { feedKey, UNREAD_COUNTS_KEY, type FeedData } from './useFeed';
import { ApiProvider } from '../services/ApiContext';
import { makeFakeApi } from '../test/fakeApi';
import { makeTestQueryClient } from '../test/render';
import { feedItem, feedPage } from '../components/reader/fixtures';
import type { Api, FeedItem, UnreadCounts } from '../services/api';

const A = feedItem({ id: 'a', source_id: 's1', read_at: null, starred_at: null });
const B = feedItem({ id: 'b', source_id: 's2', read_at: null, starred_at: null });
const KEY = feedKey('all', 'unread', 'stream');

function setup(api: Api, onUnreadDelta?: (change: UnreadChange) => void, scope = 'all') {
  const queryClient = makeTestQueryClient();
  queryClient.setQueryData<FeedData>(KEY, { pages: [feedPage([A, B])], pageParams: [null] });
  queryClient.setQueryData<UnreadCounts>([...UNREAD_COUNTS_KEY], { total: 2, by_source: { s1: 1, s2: 1 }, by_folder: { f1: 2 } } as UnreadCounts);
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ApiProvider value={api}>{children}</ApiProvider>
      </QueryClientProvider>
    );
  }
  const hook = renderHook(() => useReaderMutations({ onUnreadDelta, scope }), { wrapper: Wrapper });
  return { ...hook, queryClient };
}

function cached(queryClient: QueryClient, id: string): FeedItem {
  const page = queryClient.getQueryData<FeedData>(KEY)!.pages[0] as { items: FeedItem[] };
  return page.items.find((item) => item.id === id)!;
}

function deferred() {
  let reject: (error: unknown) => void = () => {};
  const promise = new Promise<void>((_, r) => { reject = r; });
  return { promise, reject };
}

describe('useReaderMutations', () => {
  it('a failed read rolls back only its own change, keeping a later star', async () => {
    const read = deferred();
    const api = makeFakeApi({
      setPostsRead: vi.fn().mockReturnValue(read.promise),
      setPostStarred: vi.fn().mockResolvedValue(undefined),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 2, by_source: { s1: 1, s2: 1 }, by_folder: {} }),
    });
    const { result, queryClient } = setup(api);

    let pendingRead: Promise<void> = Promise.resolve();
    act(() => { pendingRead = result.current.setRead(A, true); });
    expect(cached(queryClient, 'a').read_at).not.toBeNull();
    await act(async () => { await result.current.setStarred(B, true); });

    await act(async () => {
      read.reject(new Error('offline'));
      await pendingRead.catch(() => {});
    });

    expect(cached(queryClient, 'a').read_at).toBeNull();
    expect(cached(queryClient, 'b').starred_at).not.toBeNull();
  });

  it('a failed star restores only that post', async () => {
    const api = makeFakeApi({
      setPostsRead: vi.fn().mockResolvedValue(undefined),
      setPostStarred: vi.fn().mockRejectedValue(new Error('offline')),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 1, by_source: { s1: 0, s2: 1 }, by_folder: {} }),
    });
    const { result, queryClient } = setup(api);
    await act(async () => {
      await result.current.setStarred(A, true).catch(() => {});
      await result.current.setRead(B, true);
    });
    expect(cached(queryClient, 'a').starred_at).toBeNull();
    expect(cached(queryClient, 'b').read_at).not.toBeNull();
  });

  it('reports the change actually applied to each scope count', async () => {
    const changes: UnreadChange[] = [];
    const api = makeFakeApi({
      setPostsRead: vi.fn().mockResolvedValue(undefined),
      getUnreadCounts: vi.fn().mockResolvedValue({ total: 1, by_source: { s1: 0, s2: 1 }, by_folder: {} }),
    });
    const { result } = setup(api, (change) => changes.push(change));
    await act(async () => { await result.current.setRead(A, true); });
    expect(changes).toHaveLength(1);
    expect(scopeDelta(changes[0], 'all')).toBe(-1);
    expect(scopeDelta(changes[0], 'source:s1')).toBe(-1);
    expect(scopeDelta(changes[0], 'source:s2')).toBe(0);
    // No health rows are cached, so no folder count moved: a folder scope sees no change.
    expect(scopeDelta(changes[0], 'folder:f1')).toBe(0);
  });

  it('undoes a big mark-through in batches of 500, as one change', async () => {
    const setPostsRead = vi.fn().mockResolvedValue(undefined);
    const api = makeFakeApi({ setPostsRead, getUnreadCounts: vi.fn().mockReturnValue(new Promise(() => {})) });
    const { result, queryClient } = setup(api);
    await act(async () => { await result.current.setRead(A, true); await result.current.setRead(B, true); });
    setPostsRead.mockClear();
    const ids = ['a', 'b', ...Array.from({ length: 1198 }, (_, i) => `x${i}`)];

    await act(async () => { await result.current.markUnread(ids); });

    expect(setPostsRead.mock.calls.map(([batch, read]) => [batch.length, read])).toEqual([[500, false], [500, false], [200, false]]);
    expect(setPostsRead.mock.calls.flatMap(([batch]) => batch)).toEqual(ids);
    expect(cached(queryClient, 'a').read_at).toBeNull();
    expect(cached(queryClient, 'b').read_at).toBeNull();
    expect(queryClient.getQueryData<UnreadCounts>([...UNREAD_COUNTS_KEY])?.total).toBe(2);
  });

  it('in a track, a read moves that track’s count even before the health rows load', async () => {
    const changes: UnreadChange[] = [];
    const api = makeFakeApi({
      setPostsRead: vi.fn().mockResolvedValue(undefined),
      getUnreadCounts: vi.fn().mockReturnValue(new Promise(() => {})),
    });
    const { result, queryClient } = setup(api, (change) => changes.push(change), 'folder:f1');
    await act(async () => { await result.current.setRead(A, true); });
    expect(queryClient.getQueryData<UnreadCounts>([...UNREAD_COUNTS_KEY])?.by_folder.f1).toBe(1);
    expect(scopeDelta(changes[0], 'folder:f1')).toBe(-1);
  });
});
