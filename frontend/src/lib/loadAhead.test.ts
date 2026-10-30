import test from 'node:test';
import assert from 'node:assert/strict';

import { loadAhead } from './loadAhead.ts';

function setup() {
  const loaded: string[] = [];
  const idle: (() => void)[] = [];
  const loaders = ['post', 'news', 'classics'].map((name) => async () => void loaded.push(name));
  return { loaded, idle, loaders, whenIdle: (run: () => void) => void idle.push(run) };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test('nothing loads before the feed is on screen', async () => {
  const { loaded, idle, loaders, whenIdle } = setup();
  assert.equal(loadAhead({ ready: false, saveData: false, whenIdle, loaders }), false);
  assert.equal(idle.length, 0);
  await settle();
  assert.deepEqual(loaded, []);
});

test('once the feed is on screen, the chunks load when idle, one after another', async () => {
  const { loaded, idle, loaders, whenIdle } = setup();
  assert.equal(loadAhead({ ready: true, saveData: false, whenIdle, loaders }), true);
  assert.deepEqual(loaded, []);
  idle[0]();
  await settle();
  assert.deepEqual(loaded, ['post', 'news', 'classics']);
});

test('a connection that saves data loads nothing ahead', async () => {
  const { loaded, idle, loaders, whenIdle } = setup();
  assert.equal(loadAhead({ ready: true, saveData: true, whenIdle, loaders }), true);
  assert.equal(idle.length, 0);
  await settle();
  assert.deepEqual(loaded, []);
});

test('one chunk that fails does not stop the others', async () => {
  const { loaded, idle, whenIdle } = setup();
  const loaders = [async () => { throw new Error('gone'); }, async () => void loaded.push('news')];
  loadAhead({ ready: true, saveData: false, whenIdle, loaders });
  idle[0]();
  await settle();
  assert.deepEqual(loaded, ['news']);
});
