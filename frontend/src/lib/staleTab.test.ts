import test from 'node:test';
import assert from 'node:assert/strict';

import { isStaleChunkError, reloadOnce } from './staleTab.ts';

function memoryStorage() {
  const items = new Map<string, string>();
  return { getItem: (key: string) => items.get(key) ?? null, setItem: (key: string, value: string) => void items.set(key, value) };
}

test('a missing chunk reloads once, never twice', () => {
  const storage = memoryStorage();
  assert.equal(reloadOnce(storage, 'build-a', 1_000), true);
  // The reload brought build B, which fails at once too: the error screen, not a loop.
  assert.equal(reloadOnce(storage, 'build-b', 5_000), false);
  assert.equal(reloadOnce(storage, 'build-b', 9_000), false);
});

test('a reload that brought back the same build never reloads again', () => {
  const storage = memoryStorage();
  assert.equal(reloadOnce(storage, 'build-a', 1_000), true);
  assert.equal(reloadOnce(storage, 'build-a', 10 * 60_000), false);
});

test('a later deploy in the same tab recovers again', () => {
  const storage = memoryStorage();
  assert.equal(reloadOnce(storage, 'build-a', 1_000), true);
  assert.equal(reloadOnce(storage, 'build-b', 60 * 60_000), true);
});

test('a broken record does not block the reload', () => {
  const storage = memoryStorage();
  storage.setItem('insight.staleReload', '{not json');
  assert.equal(reloadOnce(storage, 'build-a', 1_000), true);
});

test('the browsers\' chunk errors are recognised, other errors are not', () => {
  assert.equal(isStaleChunkError(new TypeError('Failed to fetch dynamically imported module: http://x/assets/a.js')), true);
  assert.equal(isStaleChunkError(new TypeError('error loading dynamically imported module: http://x/assets/a.js')), true);
  assert.equal(isStaleChunkError(new TypeError('Importing a module script failed.')), true);
  assert.equal(isStaleChunkError(new Error('Unable to preload CSS for /assets/a.css')), true);
  assert.equal(isStaleChunkError(new Error('Not found')), false);
});
