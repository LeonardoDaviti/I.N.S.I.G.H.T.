import test from 'node:test';
import assert from 'node:assert/strict';

import {
  contextNeighbors,
  decodeFeedContext,
  decodeFeedCursor,
  displaySourceName,
  encodeFeedContext,
  feedCursorFor,
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

const entries = [
  { id: 'a', pageCursor: null },
  { id: 'b', pageCursor: null },
  { id: 'c', pageCursor: 'P2' },
];

test('neighbors in the middle of the loaded list', () => {
  const n = contextNeighbors(entries, 'b', 'P3');
  assert.deepEqual(n.prev, entries[0]);
  assert.deepEqual(n.next, entries[2]);
  assert.equal(n.loadNext, null);
  assert.equal(n.found, true);
});

test('prev at the first item is null', () => {
  const n = contextNeighbors(entries, 'a', null);
  assert.equal(n.prev, null);
  assert.deepEqual(n.next, entries[1]);
});

test('at the last loaded id with a next cursor: "load the next page with cursor X"', () => {
  const n = contextNeighbors(entries, 'c', 'P3');
  assert.equal(n.next, null);
  assert.equal(n.loadNext, 'P3');
});

test('at the very end with no next cursor there is nothing to load', () => {
  const n = contextNeighbors(entries, 'c', null);
  assert.equal(n.next, null);
  assert.equal(n.loadNext, null);
});

test('a post that is not in the context list has no neighbors', () => {
  const n = contextNeighbors(entries, 'zzz', 'P3');
  assert.deepEqual(n, { prev: null, next: null, loadNext: null, found: false });
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

test('displaySourceName: URL-named feeds get a derived name (sourceLabel); names stay', () => {
  assert.equal(displaySourceName('https://rss.arxiv.org/rss/cs.AI'), 'arXiv cs.AI');
  assert.equal(displaySourceName('http://www.example.com/feed/'), 'example.com');
  assert.equal(displaySourceName('r/EvenRealities'), 'r/EvenRealities');
  assert.equal(displaySourceName('  '), 'Unknown source');
  assert.equal(displaySourceName(null), 'Unknown source');
});
