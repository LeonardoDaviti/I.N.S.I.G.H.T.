import test from 'node:test';
import assert from 'node:assert/strict';

import { defaultOrder, isNarrowed, parseSearch, searchHref, searchOrder } from './search.ts';

const SOURCE = 'source:0a5e90ae-2533-4a31-bf0a-cafd414fc0ce';

test('search URL: only what differs from the defaults, and back', () => {
  assert.equal(searchHref({ q: '  mcp ' }), '/search?q=mcp');
  assert.equal(searchHref({}), '/search');
  const href = searchHref({ q: '"open file" -error', scope: SOURCE, filter: 'later', days: 30, order: 'best' });
  assert.deepEqual(parseSearch(new URL(href, 'http://x').searchParams), {
    q: '"open file" -error', scope: SOURCE, filter: 'later', days: 30, order: 'best',
  });
});

test('search URL: News and Classics are lists to search, as Later and Kept (issue 0056)', () => {
  for (const filter of ['news', 'classics'] as const) {
    const href = searchHref({ q: 'kimi 3.1', scope: 'all', filter });
    assert.equal(href, `/search?q=kimi+3.1&scope=all&filter=${filter}`);
    assert.equal(parseSearch(new URL(href, 'http://x').searchParams).filter, filter);
  }
  assert.equal(isNarrowed(parseSearch(new URLSearchParams('q=x&filter=news'))), true);
});

test('search URL: an unknown scope, filter, date or order is the default', () => {
  const state = parseSearch(new URLSearchParams('q=x&scope=tag:x&filter=unread&days=3&order=oldest'));
  assert.deepEqual(state, { q: 'x', scope: null, filter: 'all', days: null, order: null });
  assert.equal(isNarrowed(state), false);
  assert.equal(isNarrowed({ ...state, scope: 'all' }), true);
  assert.equal(isNarrowed({ ...state, days: 7 }), true);
});

test('search URL: History is a list to search (issue 0139)', () => {
  const href = searchHref({ q: '3D library', filter: 'history' });
  assert.equal(href, '/search?q=3D+library&filter=history');
  assert.equal(parseSearch(new URL(href, 'http://x').searchParams).filter, 'history');
});

test('search order: best match for 2+ words, newest for one, a chosen order kept (issue 0139)', () => {
  assert.equal(searchOrder({ q: '3D library tokens', order: null }), 'best');
  assert.equal(searchOrder({ q: 'robots', order: null }), 'newest');
  assert.equal(searchOrder({ q: 'robots -phone', order: null }), 'newest');
  assert.equal(searchOrder({ q: 'robots or androids', order: null }), 'best');
  assert.equal(defaultOrder('"open file"'), 'best');
  assert.equal(searchOrder({ q: '3D library tokens', order: 'newest' }), 'newest');
  assert.equal(searchHref({ q: '3D library', order: 'newest' }), '/search?q=3D+library&order=newest');
  assert.equal(parseSearch(new URLSearchParams('q=x&order=newest')).order, 'newest');
});
