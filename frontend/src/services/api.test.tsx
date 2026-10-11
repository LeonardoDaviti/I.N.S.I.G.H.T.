import { afterEach, describe, expect, it, vi } from 'vitest';

import { createApi } from './api';

/** Answer every fetch with `body`, and remember what was asked. */
function serve(body: unknown) {
  const calls: [string, RequestInit][] = [];
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    calls.push([url, init]);
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  });
  return () => calls.map(([url, init]) => [init.method, url, init.body ? JSON.parse(String(init.body)) : undefined]);
}

afterEach(() => vi.unstubAllGlobals());

describe('the read-state and source routes', () => {
  it('sends one post, many posts and a mark-through to PUT /api/feed/read', async () => {
    const calls = serve({ success: true, updated: 1, ids: ['a'] });
    const api = createApi();

    await api.setPostsRead(['a'], true);
    await api.setPostsRead(['a', 'b'], false);
    await api.markReadThrough('folder:f', 'THROUGH', 'NEWEST');

    expect(calls()).toEqual([
      ['PUT', '/api/feed/read', { ids: ['a'], read: true }],
      ['PUT', '/api/feed/read', { ids: ['a', 'b'], read: false }],
      ['PUT', '/api/feed/read', { scope: 'folder:f', through_cursor: 'THROUGH', newest_cursor: 'NEWEST' }],
    ]);
  });

  it('lists and adds sources at /api/sources', async () => {
    const calls = serve({ success: true, sources: [], total: 0 });
    const api = createApi();

    await api.getSources();
    await api.addSource({ platform: 'rss', handle_or_url: 'https://example.test/feed.xml' });

    expect(calls()).toEqual([
      ['GET', '/api/sources', undefined],
      ['POST', '/api/sources', { platform: 'rss', handle_or_url: 'https://example.test/feed.xml' }],
    ]);
  });
});
