import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ApiError,
  apiErrorFromResponse,
  cleanErrorMessage,
  errorMessage,
  isTransientError,
  toApiError,
} from './apiError.ts';

function jsonResponse(status: number, body: unknown, statusText = ''): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { 'content-type': 'application/json' },
  });
}

test('apiErrorFromResponse uses the FastAPI detail as the message, with no url or status prefix', async () => {
  const err = await apiErrorFromResponse(
    jsonResponse(409, { detail: 'Telegram session is in use by another run' }),
  );
  assert.ok(err instanceof ApiError);
  assert.ok(err instanceof Error);
  assert.equal(err.status, 409);
  assert.equal(err.message, 'Telegram session is in use by another run');
  assert.deepEqual(err.detail, { detail: 'Telegram session is in use by another run' });
});

test('apiErrorFromResponse falls back to error / message keys of the old envelope', async () => {
  const err = await apiErrorFromResponse(jsonResponse(500, { success: false, error: 'boom' }));
  assert.equal(err.status, 500);
  assert.equal(err.message, 'boom');
});

test('apiErrorFromResponse flattens a FastAPI validation detail list into one sentence', async () => {
  const err = await apiErrorFromResponse(
    jsonResponse(422, { detail: [{ loc: ['body', 'override_hours'], msg: 'Input should be less than or equal to 2160' }] }),
  );
  assert.equal(err.status, 422);
  assert.equal(err.message, 'override_hours: Input should be less than or equal to 2160');
});

test('apiErrorFromResponse reduces an HTML error page to its title', async () => {
  const err = await apiErrorFromResponse(
    new Response('<html><head><title>502 Bad Gateway</title></head><body><h1>nginx</h1></body></html>', {
      status: 502,
      headers: { 'content-type': 'text/html' },
    }),
  );
  assert.equal(err.status, 502);
  assert.equal(err.message, '502 Bad Gateway');
});

test('apiErrorFromResponse maps a status with an empty body to a human message', async () => {
  assert.equal((await apiErrorFromResponse(new Response('', { status: 404 }))).message, 'Not found');
  assert.equal((await apiErrorFromResponse(new Response('', { status: 503 }))).message, 'The backend is unavailable. Try again shortly.');
  assert.equal((await apiErrorFromResponse(new Response('', { status: 418 }))).message, 'Request failed (418)');
});

test('cleanErrorMessage strips the legacy "API request failed" prefix and the "| url=" suffix', () => {
  assert.equal(
    cleanErrorMessage('API request failed: 404 Post not found | url=http://localhost:8000/api/posts/item/x'),
    'Post not found',
  );
  assert.equal(cleanErrorMessage('API request failed: 500 Internal Server Error'), 'Internal Server Error');
  assert.equal(cleanErrorMessage('  plain message  '), 'plain message');
});

test('toApiError turns a fetch network failure into status 0', () => {
  const err = toApiError(new TypeError('Failed to fetch'));
  assert.equal(err.status, 0);
  assert.equal(err.message, 'Could not reach the backend. Check that it is running.');
});

test('toApiError passes an ApiError through unchanged', () => {
  const original = new ApiError(404, 'Not found');
  assert.equal(toApiError(original), original);
});

test('errorMessage gives a clean string for anything thrown', () => {
  assert.equal(errorMessage(new ApiError(400, 'Bad limit')), 'Bad limit');
  assert.equal(errorMessage(new Error('API request failed: 400 Bad limit | url=/x')), 'Bad limit');
  assert.equal(errorMessage('oops'), 'oops');
  assert.equal(errorMessage(undefined), 'Unknown error');
});

test('isTransientError: network, 408, 429 and 5xx are transient; other 4xx are not', () => {
  assert.equal(isTransientError(new TypeError('Failed to fetch')), true);
  assert.equal(isTransientError(new ApiError(0, 'x')), true);
  assert.equal(isTransientError(new ApiError(408, 'x')), true);
  assert.equal(isTransientError(new ApiError(429, 'x')), true);
  assert.equal(isTransientError(new ApiError(502, 'x')), true);
  assert.equal(isTransientError(new ApiError(404, 'x')), false);
  assert.equal(isTransientError(new ApiError(422, 'x')), false);
  assert.equal(isTransientError(new DOMException('Aborted', 'AbortError')), false);
});
