import test from 'node:test';
import assert from 'node:assert/strict';

import { feedNavigation, initialNavState, type NavState } from './feedNavigation.ts';

function at(ids: string[], selectedId: string | null, hasMore = false): NavState {
  return { ...initialNavState(ids, hasMore), selectedId };
}

test('j with nothing selected selects the first item and asks for focus', () => {
  const next = feedNavigation(at(['a', 'b'], null), { type: 'next' });
  assert.equal(next.selectedId, 'a');
  assert.deepEqual(next.intent, { kind: 'focus', id: 'a' });
});

test('j and k move the selection by one', () => {
  const down = feedNavigation(at(['a', 'b', 'c'], 'a'), { type: 'next' });
  assert.equal(down.selectedId, 'b');
  const up = feedNavigation(down, { type: 'prev' });
  assert.equal(up.selectedId, 'a');
  assert.deepEqual(up.intent, { kind: 'focus', id: 'a' });
});

test('k at the first item stays there', () => {
  const next = feedNavigation(at(['a', 'b'], 'a'), { type: 'prev' });
  assert.equal(next.selectedId, 'a');
  assert.equal(next.intent, null);
});

test('j at the last loaded item emits loadMore when more pages exist', () => {
  const next = feedNavigation(at(['a', 'b'], 'b', true), { type: 'next' });
  assert.equal(next.selectedId, 'b');
  assert.deepEqual(next.intent, { kind: 'loadMore' });
  assert.equal(next.pendingAdvance, true);
});

test('j at the very end without more pages does nothing', () => {
  const next = feedNavigation(at(['a', 'b'], 'b', false), { type: 'next' });
  assert.equal(next.selectedId, 'b');
  assert.equal(next.intent, null);
});

test('after loadMore, the appended page moves the selection to the next item', () => {
  const waiting = feedNavigation(at(['a', 'b'], 'b', true), { type: 'next' });
  const synced = feedNavigation(waiting, { type: 'sync', ids: ['a', 'b', 'c', 'd'], hasMore: false });
  assert.equal(synced.selectedId, 'c');
  assert.equal(synced.pendingAdvance, false);
  assert.deepEqual(synced.intent, { kind: 'focus', id: 'c' });
});

test('m, s, o and Shift+A produce intents for the selected item', () => {
  const state = at(['a', 'b'], 'b');
  assert.deepEqual(feedNavigation(state, { type: 'toggleRead' }).intent, { kind: 'toggleRead', id: 'b' });
  assert.deepEqual(feedNavigation(state, { type: 'toggleStar' }).intent, { kind: 'toggleStar', id: 'b' });
  assert.deepEqual(feedNavigation(state, { type: 'open' }).intent, { kind: 'open', id: 'b' });
  assert.deepEqual(feedNavigation(state, { type: 'markThrough' }).intent, { kind: 'markThrough', id: 'b' });
});

test('intents need a selection', () => {
  const state = at(['a'], null);
  assert.equal(feedNavigation(state, { type: 'toggleRead' }).intent, null);
  assert.equal(feedNavigation(state, { type: 'open' }).intent, null);
});

test('selection is held by id across a page append', () => {
  const state = at(['a', 'b', 'c'], 'b');
  const synced = feedNavigation(state, { type: 'sync', ids: ['a', 'b', 'c', 'd', 'e'], hasMore: true });
  assert.equal(synced.selectedId, 'b');
  assert.equal(synced.intent, null);
  assert.equal(feedNavigation(synced, { type: 'next' }).selectedId, 'c');
});

test('selection is held by id across a page prepend (new posts on top)', () => {
  const state = at(['a', 'b', 'c'], 'b');
  const synced = feedNavigation(state, { type: 'sync', ids: ['x', 'y', 'a', 'b', 'c'], hasMore: false });
  assert.equal(synced.selectedId, 'b');
  assert.equal(feedNavigation(synced, { type: 'next' }).selectedId, 'c');
  assert.equal(feedNavigation(synced, { type: 'prev' }).selectedId, 'a');
});

test('a selected item that disappears falls back to the item now at its position', () => {
  const state = at(['a', 'b', 'c'], 'b');
  const synced = feedNavigation(state, { type: 'sync', ids: ['a', 'c'], hasMore: false });
  assert.equal(synced.selectedId, 'c');
  const emptied = feedNavigation(synced, { type: 'sync', ids: [], hasMore: false });
  assert.equal(emptied.selectedId, null);
});

test('select picks an id that is in the list and ignores unknown ids', () => {
  const state = at(['a', 'b'], null);
  assert.equal(feedNavigation(state, { type: 'select', id: 'b' }).selectedId, 'b');
  assert.equal(feedNavigation(state, { type: 'select', id: 'zzz' }).selectedId, null);
});

test('sync with equal ids and paging returns the same state (no re-render)', () => {
  const state = feedNavigation(initialNavState(['a', 'b'], true), { type: 'select', id: 'b' });
  const same = feedNavigation(state, { type: 'sync', ids: ['a', 'b'], hasMore: true });
  assert.equal(same, state);
  assert.notEqual(feedNavigation(state, { type: 'sync', ids: ['a', 'b'], hasMore: false }), state);
  assert.notEqual(feedNavigation(state, { type: 'sync', ids: ['a', 'c'], hasMore: true }), state);
});

test('sync never replays a pending intent, even when the ids are equal', () => {
  const moved = feedNavigation(initialNavState(['a', 'b'], false), { type: 'next' });
  assert.deepEqual(moved.intent, { kind: 'focus', id: 'a' });
  const synced = feedNavigation(moved, { type: 'sync', ids: ['a', 'b'], hasMore: false });
  assert.equal(synced.intent, null);
  assert.equal(synced.selectedId, 'a');
});

test('select with focus (back from a post) selects and asks for focus', () => {
  const next = feedNavigation(at(['a', 'b'], null), { type: 'select', id: 'b', focus: true });
  assert.equal(next.selectedId, 'b');
  assert.deepEqual(next.intent, { kind: 'focus', id: 'b' });
});
