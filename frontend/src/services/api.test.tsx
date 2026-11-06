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

describe('Save any page of a source you follow (issue 0122)', () => {
  /** Answer each fetch with the next body, and remember what was asked. */
  function serveEach(bodies: unknown[]) {
    const calls: [string, RequestInit][] = [];
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
      calls.push([url, init]);
      return new Response(JSON.stringify(bodies.shift()), { status: 200, headers: { 'content-type': 'application/json' } });
    });
    return () => calls.map(([url, init]) => [init.method, url, init.body ? JSON.parse(String(init.body)) : undefined]);
  }

  it('waits for the source’s fetch, then asks again with after_fetch: the source’s post', async () => {
    const source = { id: 's9', name: 'Example Blog' };
    const calls = serveEach([
      { success: true, status: 'fetching', job_id: 'j1', source, title: 'A post' },
      { success: true, job: { id: 'j1', job_type: 'ingestion_run', status: 'success', payload: {} } },
      { success: true, status: 'already', post_id: 'p9', title: 'A post', source_id: 's9', source },
    ]);
    const onFetching = vi.fn();
    const saved = await createApi().savePage('https://blog.example.com/p/a-post', 'A post', { onFetching });
    expect(onFetching).toHaveBeenCalledWith(source);
    expect(saved).toMatchObject({ status: 'already', post_id: 'p9', fetched: true, source });
    expect(calls()).toEqual([
      ['POST', '/api/saved', { url: 'https://blog.example.com/p/a-post', title: 'A post' }],
      ['GET', '/api/operations/jobs/j1', undefined],
      ['POST', '/api/saved', { url: 'https://blog.example.com/p/a-post', title: 'A post', after_fetch: true }],
    ]);
  });

  it('a failed fetch still asks again: the page is saved as the source’s post', async () => {
    const source = { id: 's9', name: 'Example Blog' };
    serveEach([
      { success: true, status: 'fetching', job_id: 'j1', source },
      { success: true, job: { id: 'j1', job_type: 'ingestion_run', status: 'failed', message: 'HTTP 503', payload: {} } },
      { success: true, status: 'saved', post_id: 'p10', source_id: 's9', source },
    ]);
    const saved = await createApi().savePage('https://blog.example.com/p/a-post');
    expect(saved).toMatchObject({ status: 'saved', post_id: 'p10', fetched: true, source });
  });

  it('a page no source of yours owns is saved at once, nothing fetched', async () => {
    const calls = serveEach([{ success: true, status: 'saved', post_id: 'p1', source: null }]);
    const saved = await createApi().savePage('https://other.example.org/a');
    expect(saved).toMatchObject({ status: 'saved', post_id: 'p1' });
    expect(saved.fetched).toBeUndefined();
    expect(calls()).toHaveLength(1);
  });

  it('asks whose page an address is', async () => {
    const calls = serveEach([{ success: true, source: { id: 's9', name: 'Example Blog' } }]);
    expect(await createApi().pageSource('https://blog.example.com/p/a post')).toEqual({ id: 's9', name: 'Example Blog' });
    expect(calls()).toEqual([['GET', '/api/saved/source?url=https%3A%2F%2Fblog.example.com%2Fp%2Fa%20post', undefined]]);
  });
});
