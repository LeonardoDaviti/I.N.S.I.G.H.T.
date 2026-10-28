import test from 'node:test';
import assert from 'node:assert/strict';

import { isNarrowed, parseSearch, searchHref } from './search.ts';

const SOURCE = 'source:0a5e90ae-2533-4a31-bf0a-cafd414fc0ce';

test('search URL: only what differs from the defaults, and back', () => {
  assert.equal(searchHref({ q: '  mcp ' }), '/search?q=mcp');
  assert.equal(searchHref({}), '/search');
  const href = searchHref({ q: '"open file" -error', scope: SOURCE, filter: 'later', days: 30, order: 'best' });
  assert.deepEqual(parseSearch(new URL(href, 'http://x').searchParams), {
    q: '"open file" -error', scope: SOURCE, filter: 'later', days: 30, order: 'best',
  });
});

test('search URL: an unknown scope, filter, date or order is the default', () => {
  const state = parseSearch(new URLSearchParams('q=x&scope=tag:x&filter=unread&days=3&order=oldest'));
  assert.deepEqual(state, { q: 'x', scope: null, filter: 'all', days: null, order: 'newest' });
  assert.equal(isNarrowed(state), false);
  assert.equal(isNarrowed({ ...state, scope: 'all' }), true);
  assert.equal(isNarrowed({ ...state, days: 7 }), true);
});
