import { describe, expect, it, vi } from 'vitest';

import { createFixtureTransport, pending, serverError, type TransportEvent } from './transport';

const ORIGIN = 'http://studio.test';

function setup(options: Partial<Parameters<typeof createFixtureTransport>[0]> = {}) {
  const realFetch = vi.fn(async () => new Response('{"from":"network"}', { status: 200 }));
  const events: TransportEvent[] = [];
  const transport = createFixtureTransport({
    routes: [],
    data: 'fixtures',
    realFetch,
    onEvent: (event) => events.push(event),
    origin: ORIGIN,
    ...options,
  });
  return { transport, realFetch, events };
}

describe('the fixture transport', () => {
  it('answers a GET from the route that matches its path, with path params and the query', async () => {
    const { transport, realFetch, events } = setup({
      routes: [
        { path: '/api/feed', respond: ({ query }) => ({ scope: query.get('scope') }) },
        { path: '/api/posts/item/:postId', respond: ({ params }) => ({ id: params.postId }) },
      ],
    });

    const feed = await transport('/api/feed?scope=folder%3Aabc&filter=unread');
    expect(feed.status).toBe(200);
    expect(await feed.json()).toEqual({ scope: 'folder:abc' });

    const post = await transport(`${ORIGIN}/api/posts/item/p-7`);
    expect(await post.json()).toEqual({ id: 'p-7' });

    expect(realFetch).not.toHaveBeenCalled();
    expect(events).toEqual([]);
  });

  it('reports a GET with no fixture and answers it without the network', async () => {
    const { transport, realFetch, events } = setup({ routes: [{ path: '/api/feed', respond: () => ({}) }] });

    const response = await transport('/api/sources/health?x=1');

    expect(response.status).toBe(501);
    expect(await response.json()).toEqual({ detail: 'unmocked request: GET /api/sources/health?x=1' });
    expect(events).toEqual([{ kind: 'unmocked', method: 'GET', path: '/api/sources/health?x=1' }]);
    expect(realFetch).not.toHaveBeenCalled();
  });

  it('never sends a write to the network, in fixtures or live mode: a fake OK, listed', async () => {
    for (const data of ['fixtures', 'live'] as const) {
      const { transport, realFetch, events } = setup({ data });

      const put = await transport('/api/feed/read', { method: 'PUT', body: JSON.stringify({ ids: ['a'], read: true }) });
      const del = await transport(new Request(`${ORIGIN}/api/sources/s-1`, { method: 'DELETE' }));

      expect(await put.json()).toEqual({ success: true });
      expect(del.status).toBe(200);
      expect(events).toEqual([
        { kind: 'write', method: 'PUT', path: '/api/feed/read' },
        { kind: 'write', method: 'DELETE', path: '/api/sources/s-1' },
      ]);
      expect(realFetch).not.toHaveBeenCalled();
    }
  });

  it('lets a write route shape the fake answer, and still lists the write', async () => {
    const { transport, events } = setup({
      routes: [{ method: 'POST', path: '/api/posts/item/:id/favorite', respond: ({ body }) => ({ success: true, echo: body }) }],
    });

    const response = await transport('/api/posts/item/p1/favorite', { method: 'POST', body: '{"favorited":true}' });

    expect(await response.json()).toEqual({ success: true, echo: { favorited: true } });
    expect(events).toEqual([{ kind: 'write', method: 'POST', path: '/api/posts/item/p1/favorite' }]);
  });

  it('with live data, passes an unmocked GET through to the real API, unreported', async () => {
    const { transport, realFetch, events } = setup({ data: 'live' });

    const response = await transport('/api/feed?scope=all');

    expect(await response.json()).toEqual({ from: 'network' });
    expect(realFetch).toHaveBeenCalledTimes(1);
    expect(events).toEqual([]);
  });

  it('leaves reads outside the API alone', async () => {
    const { transport, realFetch, events } = setup();
    await transport('/assets/logo.svg');
    await transport('https://elsewhere.example/api/feed');
    expect(realFetch).toHaveBeenCalledTimes(2);
    expect(events).toEqual([]);
  });

  it('treats the API at VITE_API_URL like the API on the frame origin: fixtures, no network', async () => {
    const { transport, realFetch, events } = setup({
      apiBase: 'https://api.example.test/insight',
      routes: [{ path: '/api/feed', respond: () => ({ from: 'fixture' }) }],
    });

    const feed = await transport('https://api.example.test/insight/api/feed?scope=all');
    const missing = await transport('https://api.example.test/insight/api/sources');
    const write = await transport('https://api.example.test/insight/api/feed/read', { method: 'PUT', body: '{}' });

    expect(await feed.json()).toEqual({ from: 'fixture' });
    expect(missing.status).toBe(501);
    expect(await write.json()).toEqual({ success: true });
    expect(events).toEqual([
      { kind: 'unmocked', method: 'GET', path: '/api/sources' },
      { kind: 'write', method: 'PUT', path: '/api/feed/read' },
    ]);
    expect(realFetch).not.toHaveBeenCalled();
  });

  it('never sends a write anywhere, even outside the API or to another origin', async () => {
    const { transport, realFetch, events } = setup({ data: 'live' });

    await transport('https://elsewhere.example/api/feed', { method: 'POST', body: '{}' });
    await transport(new Request('https://elsewhere.example/hook', { method: 'DELETE' }));
    await transport('/not-api/thing', { method: 'PATCH' });

    expect(realFetch).not.toHaveBeenCalled();
    expect(events).toEqual([
      { kind: 'write', method: 'POST', path: 'https://elsewhere.example/api/feed' },
      { kind: 'write', method: 'DELETE', path: 'https://elsewhere.example/hook' },
      { kind: 'write', method: 'PATCH', path: '/not-api/thing' },
    ]);
  });

  it('answers the loading state with a promise that never settles and the error state with a 500', async () => {
    const { transport } = setup({
      routes: [
        { path: '/api/feed', respond: () => pending() },
        { path: '/api/config', respond: () => serverError('The database is unreachable') },
      ],
    });

    const settled = vi.fn();
    void transport('/api/feed').then(settled, settled);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(settled).not.toHaveBeenCalled();

    const error = await transport('/api/config');
    expect(error.status).toBe(500);
    expect(await error.json()).toEqual({ detail: 'The database is unreachable' });
  });
});
