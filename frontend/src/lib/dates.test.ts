import test from 'node:test';
import assert from 'node:assert/strict';

import { formatRelativeTime, localDateISO } from './dates.ts';

// getTimezoneOffset() convention: minutes to ADD to local time to get UTC,
// so UTC+2 is -120 and UTC-5 is 300.
const UTC_PLUS_2 = -120;
const UTC_MINUS_5 = 300;

test('localDateISO: 23:30 UTC is already tomorrow in UTC+2 (toISOString would say today)', () => {
  const instant = new Date('2026-10-09T23:30:00Z'); // 01:30 on the 10th in UTC+2
  assert.equal(instant.toISOString().split('T')[0], '2026-10-09');
  assert.equal(localDateISO(instant, UTC_PLUS_2), '2026-10-10');
});

test('localDateISO: 02:00 UTC is still yesterday in UTC-5', () => {
  const instant = new Date('2026-10-10T02:00:00Z'); // 21:00 on the 9th in UTC-5
  assert.equal(localDateISO(instant, UTC_MINUS_5), '2026-10-09');
});

test('localDateISO: exactly local midnight belongs to the new day', () => {
  const instant = new Date('2026-12-31T22:00:00Z'); // 00:00 on 1 Jan in UTC+2
  assert.equal(localDateISO(instant, UTC_PLUS_2), '2027-01-01');
  assert.equal(localDateISO(new Date('2026-12-31T21:59:59Z'), UTC_PLUS_2), '2026-12-31');
});

test('localDateISO defaults to the runtime offset of that instant', () => {
  const instant = new Date(2026, 9, 9, 23, 59); // local wall-clock time
  assert.equal(localDateISO(instant), '2026-10-09');
});

test('formatRelativeTime: past and future, with the injected now', () => {
  const now = new Date('2026-10-09T12:00:00Z');
  assert.equal(formatRelativeTime('2026-10-09T11:59:40Z', now), 'just now');
  assert.equal(formatRelativeTime('2026-10-09T11:55:00Z', now), '5m ago');
  assert.equal(formatRelativeTime('2026-10-09T09:00:00Z', now), '3h ago');
  assert.equal(formatRelativeTime('2026-10-07T12:00:00Z', now), '2d ago');
  assert.equal(formatRelativeTime('2026-10-09T15:00:00Z', now), 'in 3h');
  assert.equal(formatRelativeTime(new Date('2026-10-14T12:00:00Z'), now), 'in 5d');
});

test('formatRelativeTime: beyond 30 days falls back to the local date', () => {
  const now = new Date('2026-10-09T12:00:00Z');
  assert.equal(formatRelativeTime('2026-08-01T12:00:00Z', now, UTC_PLUS_2), '2026-08-01');
});

test('formatRelativeTime: null or unparseable input gives an em dash', () => {
  assert.equal(formatRelativeTime(null), '—');
  assert.equal(formatRelativeTime('not a date'), '—');
});
