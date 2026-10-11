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
  const shots = shotList(MATRIX).filter((shot) => !shot.studio);
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

test('a state with its own width (the 320px top bar) is shot at that width too', () => {
  const shots = shotList({ scenarios: [{ page: 'shell', state: 'narrow-topbar', width: 320 }], prototypes: [] }, { page: ['shell'] });
  assert.deepEqual(shots.map((shot) => shot.file), [
    'shell/narrow-topbar.1400.dark.png', 'shell/narrow-topbar.1400.light.png',
    'shell/narrow-topbar.390.dark.png', 'shell/narrow-topbar.390.light.png',
    'shell/narrow-topbar.320.dark.png', 'shell/narrow-topbar.320.light.png',
  ]);
  assert.deepEqual(shotList({ scenarios: [{ page: 'shell', state: 'narrow-topbar', width: 320 }], prototypes: [] }, { width: ['320'] }).length, 2);
});

test('the studio itself: the Handbook home, the Wall fitted and Bench on the seed, at 1400 in both themes', () => {
  const shots = shotList(MATRIX, { page: ['studio'] });
  assert.deepEqual(shots.map((shot) => [shot.file, shot.url, shot.studio]), [
    ['studio/handbook.1400.dark.png', '/design', true],
    ['studio/handbook.1400.light.png', '/design', true],
    ['studio/wall.1400.dark.png', '/design?mode=wall&theme=dark', true],
    ['studio/wall.1400.light.png', '/design?mode=wall&theme=light', true],
    ['studio/bench.1400.dark.png', '/design?mode=bench&subject=2026-10-10-title-wrap&theme=dark', true],
    ['studio/bench.1400.light.png', '/design?mode=bench&subject=2026-10-10-title-wrap&theme=light', true],
  ]);
  assert.equal(shotList(MATRIX, { width: ['390'] }).some((shot) => shot.studio), false);
});
