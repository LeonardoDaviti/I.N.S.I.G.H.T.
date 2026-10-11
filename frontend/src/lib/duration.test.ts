import test from 'node:test';
import assert from 'node:assert/strict';

import { formatClock, formatElapsed, formatEstimate, formatHours, formatSpan, formatTimeRemaining } from './duration.ts';

test('formatClock: video lengths as h:mm:ss or m:ss', () => {
  assert.equal(formatClock(14_527), '4:02:07');
  assert.equal(formatClock(754), '12:34');
  assert.equal(formatClock(45), '0:45');
  assert.equal(formatClock(null), '0:00');
});

test('formatElapsed: seconds, then minutes, then hours', () => {
  assert.equal(formatElapsed(null), null);
  assert.equal(formatElapsed(0.4), '<1s');
  assert.equal(formatElapsed(42), '42s');
  assert.equal(formatElapsed(125), '2m 5s');
  assert.equal(formatElapsed(3725), '1h 2m');
  assert.equal(formatElapsed(3725, { hours: false }), '62m 5s');
});

test('formatSpan: one floored unit, at least a minute', () => {
  assert.equal(formatSpan(20_000), '1m');
  assert.equal(formatSpan(25 * 60_000), '25m');
  assert.equal(formatSpan(3.9 * 3_600_000), '3h');
  assert.equal(formatSpan(5 * 86_400_000), '5d');
});

test('formatTimeRemaining picks the two or three largest units', () => {
  assert.equal(formatTimeRemaining(9_000), '9s');
  assert.equal(formatTimeRemaining(250_000), '4m 10s');
  assert.equal(formatTimeRemaining(3_902_000), '1h 5m 2s');
  assert.equal(formatTimeRemaining((2 * 86400 + 3 * 3600 + 4 * 60) * 1000), '2d 3h 4m');
  assert.equal(formatTimeRemaining(-5_000), '0s');
});

test('formatTimeRemaining without seconds keeps them only below a minute', () => {
  assert.equal(formatTimeRemaining(9_000, { seconds: false }), '9s');
  assert.equal(formatTimeRemaining(250_000, { seconds: false }), '4m');
  assert.equal(formatTimeRemaining(3_902_000, { seconds: false }), '1h 5m');
});

test('time estimates read as rough durations', () => {
  assert.equal(formatEstimate(null), null);
  assert.equal(formatEstimate(0), 'under a minute');
  assert.equal(formatEstimate(45), 'under a minute');
  assert.equal(formatEstimate(300), '~5m');
  assert.equal(formatEstimate(7800), '~2h 10m');
});

test('formatHours', () => {
  assert.equal(formatHours(0.5), '30m');
  assert.equal(formatHours(6), '6h');
  assert.equal(formatHours(1.5), '1.5h');
  assert.equal(formatHours(48), '2d');
  assert.equal(formatHours(36), '1.5d');
  assert.equal(formatHours(null), '—');
});
