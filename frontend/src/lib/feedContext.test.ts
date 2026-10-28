import test from 'node:test';
import assert from 'node:assert/strict';

import {
  decodeFeedContext,
  decodeFeedCursor,
  encodeFeedContext,
  feedCursorFor,
  neighborsAt,
  postHref,
  scopeFromRoute,
  scopePath,
} from './feedContext.ts';

const SOURCE = 'source:0a5e90ae-2533-4a31-bf0a-cafd414fc0ce';
const FOLDER = 'folder:f8571844-1065-4d96-85b5-1dfd9dc7b111';
const POST = 'f0aaf74e-f718-4398-85ac-bab51e9e65c9';

test('feed cursor: the backend form (urlsafe base64 of "iso|uuid", no padding) round-trips', () => {
  const cursor = feedCursorFor({ sort_at: '2026-09-29T02:20:03+00:00', id: POST });
  // python: base64.urlsafe_b64encode(b"2026-09-29T02:20:03+00:00|f0aa...").rstrip(b"=")
  assert.equal(cursor, Buffer.from(`2026-09-29T02:20:03+00:00|${POST}`).toString('base64url'));
  assert.deepEqual(decodeFeedCursor(cursor), { sortAt: '2026-09-29T02:20:03+00:00', id: POST });
  assert.equal(decodeFeedCursor('%%%'), null);
  assert.equal(decodeFeedCursor(Buffer.from('no-separator').toString('base64url')), null);
});

test('ctx round-trips for every scope kind, with and without a cursor', () => {
  const cursor = feedCursorFor({ sort_at: '2026-09-29T02:20:03.123456+00:00', id: POST });
  for (const scope of ['all', SOURCE, FOLDER]) {
    for (const filter of ['all', 'unread', 'starred'] as const) {
      for (const c of [null, cursor]) {
        const encoded = encodeFeedContext({ scope, filter, cursor: c });
        assert.deepEqual(decodeFeedContext(encoded), { scope, filter, cursor: c });
      }
    }
  }
});

test('a missing or malformed ctx is "no context"', () => {
  assert.equal(decodeFeedContext(null), null);
  assert.equal(decodeFeedContext(''), null);
  assert.equal(decodeFeedContext('all'), null);
  assert.equal(decodeFeedContext('all:sometimes:'), null);
  assert.equal(decodeFeedContext('planet:abc:unread:'), null);
  assert.equal(decodeFeedContext('source:not-a-uuid:unread:'), null);
  assert.equal(decodeFeedContext('all:unread:%%%'), null);
});

test('scope paths and post links', () => {
  assert.equal(scopePath('all'), '/');
  assert.equal(scopePath(SOURCE), `/read/source/${SOURCE.slice(7)}`);
  assert.equal(scopeFromRoute(undefined, undefined), 'all');
  assert.equal(scopeFromRoute('folder', FOLDER.slice(7)), FOLDER);
  assert.equal(scopeFromRoute('planet', 'x'), null);
  assert.equal(scopeFromRoute('source', undefined), null);
  const href = postHref(POST, { scope: 'all', filter: 'unread', cursor: null });
  assert.equal(href, `/posts/${POST}?ctx=${encodeURIComponent('all:unread:')}`);
});


test('neighborsAt: prev/next by sort key, the current post found or not', () => {
  const entries = [
    { id: 'c', sortAt: '2026-10-10T12:00:00Z', pageCursor: null },
    { id: 'b', sortAt: '2026-10-10T11:00:00Z', pageCursor: null },
    { id: 'a', sortAt: '2026-10-10T10:00:00Z', pageCursor: null },
  ];
  assert.deepEqual(neighborsAt(entries, { id: 'b', sortAt: '2026-10-10T11:00:00Z' }, 'more'), {
    prev: { id: 'c', pageCursor: null }, next: { id: 'a', pageCursor: null }, loadNext: null,
  });
  // Read under the unread filter, so the reloaded page no longer holds it.
  const without = entries.filter((entry) => entry.id !== 'b');
  assert.deepEqual(neighborsAt(without, { id: 'b', sortAt: '2026-10-10T11:00:00Z' }, 'more'), {
    prev: { id: 'c', pageCursor: null }, next: { id: 'a', pageCursor: null }, loadNext: null,
  });
  // Ties on the sort key go by id, descending.
  assert.equal(neighborsAt(entries, { id: 'bb', sortAt: '2026-10-10T11:00:00Z' }, null).next?.id, 'b');
});

test('neighborsAt: a loaded post goes by its place in the list, whatever its order (Later, issue 0022)', () => {
  // Later is oldest saved first, so publish dates run in no order.
  const later = [
    { id: 'x', sortAt: '2026-10-01T00:00:00Z', pageCursor: null },
    { id: 'y', sortAt: '2026-10-09T00:00:00Z', pageCursor: null },
    { id: 'z', sortAt: '2026-10-05T00:00:00Z', pageCursor: null },
  ];
  assert.deepEqual(neighborsAt(later, { id: 'y', sortAt: '2026-10-09T00:00:00Z' }, null), {
    prev: { id: 'x', pageCursor: null }, next: { id: 'z', pageCursor: null }, loadNext: null,
  });
});

test('neighborsAt: at the first and the last loaded post', () => {
  const entries = [{ id: 'c', sortAt: '2026-10-10T12:00:00Z', pageCursor: null }, { id: 'a', sortAt: '2026-10-10T10:00:00Z', pageCursor: null }];
  assert.deepEqual(neighborsAt(entries, { id: 'c', sortAt: '2026-10-10T12:00:00Z' }, null), { prev: null, next: { id: 'a', pageCursor: null }, loadNext: null });
  assert.deepEqual(neighborsAt(entries, { id: 'a', sortAt: '2026-10-10T10:00:00Z' }, 'cur2'), { prev: { id: 'c', pageCursor: null }, next: null, loadNext: 'cur2' });
  assert.deepEqual(neighborsAt(entries, { id: 'a', sortAt: '2026-10-10T10:00:00Z' }, null), { prev: { id: 'c', pageCursor: null }, next: null, loadNext: null });
});
