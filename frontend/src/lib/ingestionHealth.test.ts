import test from 'node:test';
import assert from 'node:assert/strict';

import { ingestionActivity } from './ingestionHealth.ts';

const NOW = Date.parse('2026-10-10T12:00:00Z');
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

test('ingestionActivity: a source attempted within a day means it is running', () => {
  const activity = ingestionActivity([
    { enabled: true, last_attempt_at: hoursAgo(50) },
    { enabled: true, last_attempt_at: hoursAgo(3) },
  ], NOW);
  assert.deepEqual(activity, { stopped: false, lastAttemptAt: hoursAgo(3) });
});

test('ingestionActivity: nothing attempted for over a day, or never, is stopped', () => {
  assert.equal(ingestionActivity([{ enabled: true, last_attempt_at: hoursAgo(30) }], NOW)?.stopped, true);
  assert.deepEqual(ingestionActivity([{ enabled: true, last_attempt_at: null }], NOW), { stopped: true, lastAttemptAt: null });
});

test('ingestionActivity: disabled sources do not count; no rows makes no claim', () => {
  assert.equal(ingestionActivity([{ enabled: false, last_attempt_at: hoursAgo(1) }, { enabled: true, last_attempt_at: hoursAgo(40) }], NOW)?.stopped, true);
  assert.equal(ingestionActivity([], NOW), null);
  assert.equal(ingestionActivity(undefined, NOW), null);
});
