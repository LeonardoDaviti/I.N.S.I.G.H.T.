import test from 'node:test';
import assert from 'node:assert/strict';

import { DEFAULT_PORT, parseShotArgs, shotList } from './designShots.ts';

const MATRIX = {
  scenarios: [{ page: 'reader', state: 'normal' }, { page: 'reader', state: 'error' }, { page: 'post', state: 'article' }],
  prototypes: [{ id: '2026-10-10-title-wrap', states: ['long-title', 'article'] }],
};

test('no arguments: the default port, no base URL, no filters', () => {
  assert.deepEqual(parseShotArgs([]), { port: DEFAULT_PORT, filters: {} });
});

test('filters are comma lists, with a space or an equals sign', () => {
  assert.deepEqual(parseShotArgs(['--page', 'reader, post', '--width=390', '--base-url', 'http://localhost:5173/', '--port=5200']), {
    port: 5200,
    baseUrl: 'http://localhost:5173',
    filters: { page: ['reader', 'post'], width: ['390'] },
  });
});

test('an unknown flag, a missing value or a stray word is an error', () => {
  assert.throws(() => parseShotArgs(['--pages', 'reader']), /unknown flag --pages/);
  assert.throws(() => parseShotArgs(['--page']), /--page needs a value/);
  assert.throws(() => parseShotArgs(['reader']), /unexpected argument/);
  assert.throws(() => parseShotArgs(['--port', 'x']), /--port/);
});

test('every page state and prototype state at both widths and themes', () => {
  const shots = shotList(MATRIX);
  assert.equal(shots.length, (3 + 2) * 2 * 2);
  assert.deepEqual(shots[0], {
    page: 'reader', state: 'normal', width: 1400, theme: 'dark',
    url: '/design/frame/reader/normal?theme=dark&data=fixtures',
    file: 'reader/normal.1400.dark.png',
  });
  assert.equal(shots.at(-1)?.file, 'prototypes/2026-10-10-title-wrap/article.390.light.png');
  assert.equal(shots.at(-1)?.url, '/design/frame/prototype/2026-10-10-title-wrap/article?theme=light&data=fixtures');
});

test('filters narrow each axis; prototypes match by "prototypes" or their id', () => {
  const files = (filters: Parameters<typeof shotList>[1]) => shotList(MATRIX, filters).map((shot) => shot.file);
  assert.deepEqual(files({ page: ['reader'], state: ['error'], width: ['390'], theme: ['light'] }), ['reader/error.390.light.png']);
  assert.deepEqual(files({ page: ['prototypes'], state: ['article'], width: ['1400'], theme: ['dark'] }), [
    'prototypes/2026-10-10-title-wrap/article.1400.dark.png',
  ]);
  assert.equal(files({ page: ['2026-10-10-title-wrap'] }).length, 8);
  assert.deepEqual(files({ state: ['article'], width: ['1400'], theme: ['dark'] }), [
    'post/article.1400.dark.png',
    'prototypes/2026-10-10-title-wrap/article.1400.dark.png',
  ]);
});
