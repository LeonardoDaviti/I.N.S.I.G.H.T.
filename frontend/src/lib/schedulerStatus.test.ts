import test from 'node:test';
import assert from 'node:assert/strict';

import { nextTickLabel, schedulerStaleness } from './schedulerStatus.ts';

const NOW = Date.parse('2026-10-10T12:00:00Z');
const minutesAgo = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

test('schedulerStaleness is null when the state is unknown', () => {
  assert.equal(schedulerStaleness(null, 60, NOW), null);
});

test('schedulerStaleness says so when the scheduler never ticked', () => {
  assert.match(schedulerStaleness({}, 60, NOW) ?? '', /has not recorded a tick/);
  assert.match(schedulerStaleness({ last_tick_at: 'garbage' }, 60, NOW) ?? '', /has not recorded a tick/);
});

test('schedulerStaleness waits two tick intervals before calling it stalled', () => {
  assert.equal(schedulerStaleness({ last_tick_at: minutesAgo(119) }, 60, NOW), null);
  assert.match(schedulerStaleness({ last_tick_at: minutesAgo(121) }, 60, NOW) ?? '', /last ticked 2h 1m ago/);
});

test('schedulerStaleness waits at least 90 minutes for short tick intervals', () => {
  assert.equal(schedulerStaleness({ last_tick_at: minutesAgo(89) }, 15, NOW), null);
  assert.match(schedulerStaleness({ last_tick_at: minutesAgo(91) }, 15, NOW) ?? '', /looks stalled/);
});

test('nextTickLabel counts down to the next tick, without seconds', () => {
  const inMs = (ms: number) => new Date(NOW + ms).toISOString();
  assert.equal(nextTickLabel({ next_tick_at: inMs(3_902_000) }, NOW), 'next tick in 1h 5m');
  assert.equal(nextTickLabel({ next_tick_at: inMs(-1_000) }, NOW), 'next tick due now');
  assert.equal(nextTickLabel({}, NOW), null);
  assert.equal(nextTickLabel(undefined, NOW), null);
});
