import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { ApiError } from './apiError.ts';
import { request, settle, type Envelope } from './request.ts';

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

/** Answer every fetch with `answer`, and remember what was asked. */
function serve(answer: () => Response | Promise<Response>) {
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return answer();
  }) as typeof fetch;
  return calls;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

test('a JSON success resolves with the body; the request carries the JSON body and headers', async () => {
  const calls = serve(() => json(200, { success: true, updated: 2 }));
  const body = await request<{ success: true; updated: number }>('/api/feed/read', { method: 'PUT', body: { ids: ['a', 'b'], read: true } });
  assert.deepEqual(body, { success: true, updated: 2 });
  assert.equal(calls[0].url, '/api/feed/read');
  assert.equal(calls[0].init.method, 'PUT');
  assert.equal(calls[0].init.body, '{"ids":["a","b"],"read":true}');
  assert.deepEqual(calls[0].init.headers, { 'Content-Type': 'application/json', Accept: 'application/json' });
});

test('the {success: false} envelope rejects with its error; settle resolves it as the envelope', async () => {
  serve(() => json(200, { success: false, error: 'Folder not found' }));
  await assert.rejects(request('/api/folders/x'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.message, 'Folder not found');
    assert.equal(error.status, 200);
    return true;
  });
  assert.deepEqual(await settle(request<Envelope>('/api/folders/x')), { success: false, error: 'Folder not found' });
});

test('an HTTP 500 with a JSON error body rejects with its status and the server detail', async () => {
  serve(() => json(500, { detail: 'Database is locked' }));
  await assert.rejects(request('/api/sources/health'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 500);
    assert.equal(error.message, 'Database is locked');
    return true;
  });
  assert.deepEqual(await settle(request<Envelope>('/api/folders')), { success: false, error: 'Database is locked' });
});

test('a network failure rejects with status 0 and a sentence about the backend', async () => {
  serve(() => {
    throw new TypeError('Failed to fetch');
  });
  await assert.rejects(request('/api/feed/unread-counts'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 0);
    assert.equal(error.message, 'Could not reach the backend. Check that it is running.');
    return true;
  });
});

test('an abort is not converted: it rejects with the AbortError, even through settle', async () => {
  serve(() => {
    throw new DOMException('The operation was aborted.', 'AbortError');
  });
  await assert.rejects(settle(request('/api/feed')), { name: 'AbortError' });
});
