import test from 'node:test';
import assert from 'node:assert/strict';

import {
  compactAge, feedDateLabel, feedDayHeading, feedDayKey, feedFullTime, feedTimeLabel, formatLocalDateTime, formatRelativeTime, localDateISO,
} from './dates.ts';

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

const NOW = new Date('2026-10-10T12:00:00Z');
const TZ = 'UTC';

test('feedDateLabel: relative inside the last 24h, a short date after that', () => {
  assert.equal(feedDateLabel('2026-10-10T09:00:00Z', NOW, TZ), '3h ago');
  assert.equal(feedDateLabel('2026-10-09T13:00:00Z', NOW, TZ), '23h ago');
  assert.equal(feedDateLabel('2026-10-09T11:00:00Z', NOW, TZ), 'Oct 9');
  assert.equal(feedDateLabel('2026-09-29T08:00:00Z', NOW, TZ), 'Sep 29');
  assert.equal(feedDateLabel('2025-12-31T08:00:00Z', NOW, TZ), 'Dec 31 \u201925');
  assert.equal(feedDateLabel(null, NOW, TZ), '—');
});

test('feedDateLabel: a future time is never shown as relative "in 2d"', () => {
  assert.equal(feedDateLabel('2026-10-12T08:00:00Z', NOW, TZ), 'Oct 12');
});

test('feedDayHeading: today, yesterday, then weekday and date', () => {
  assert.equal(feedDayHeading('2026-10-10T01:00:00Z', NOW, TZ), 'Today');
  assert.equal(feedDayHeading('2026-10-09T23:00:00Z', NOW, TZ), 'Yesterday');
  assert.equal(feedDayHeading('2026-09-29T08:00:00Z', NOW, TZ), 'Tue, Sep 29');
  assert.equal(feedDayHeading('2025-09-29T08:00:00Z', NOW, TZ), 'Mon, Sep 29, 2025');
});

test('feedDayKey: follows the local day, not the UTC day', () => {
  // 23:30 UTC on the 9th is already the 10th in Berlin (UTC+2).
  assert.equal(feedDayKey('2026-10-09T23:30:00Z', 'Europe/Berlin'), feedDayKey('2026-10-10T10:00:00Z', 'Europe/Berlin'));
  assert.notEqual(feedDayKey('2026-10-09T23:30:00Z', 'UTC'), feedDayKey('2026-10-10T10:00:00Z', 'UTC'));
});

test('feedDayKey: the cache keys on the time zone too', () => {
  const at = '2026-10-09T23:30:00Z';
  assert.equal(feedDayKey(at, 'UTC'), '2026-Oct-9');
  assert.equal(feedDayKey(at, 'Europe/Berlin'), '2026-Oct-10');
  assert.equal(feedDayKey(at, 'UTC'), '2026-Oct-9');
  assert.equal(feedDayKey(new Date(at), 'UTC'), '2026-Oct-9');
  assert.equal(feedDayKey(null), 'unknown');
});

test('feedTimeLabel: a 24-hour clock in the given zone; empty when undated', () => {
  assert.equal(feedTimeLabel('2026-10-09T23:30:00Z', 'UTC'), '23:30');
  assert.equal(feedTimeLabel('2026-10-09T23:30:00Z', 'Europe/Berlin'), '01:30');
  assert.equal(feedTimeLabel('2026-10-10T07:05:00Z', 'UTC'), '07:05');
  assert.equal(feedTimeLabel(undefined, 'UTC'), '');
});

test('feedFullTime: names the date and the time; empty when undated', () => {
  const label = feedFullTime('2026-10-09T23:30:00Z', 'UTC');
  assert.match(label, /2026/);
  assert.match(label, /11:30|23:30/);
  assert.equal(feedFullTime('not a date', 'UTC'), '');
});

test('compactAge stays short for a narrow numeric column', () => {
  const now = new Date('2026-10-10T12:00:00Z');
  const at = (ago: number) => new Date(now.getTime() - ago).toISOString();
  assert.equal(compactAge(null, now), '—');
  assert.equal(compactAge(at(20_000), now), 'now');
  assert.equal(compactAge(at(45 * 60_000), now), '45m');
  assert.equal(compactAge(at(3 * 3_600_000), now), '3h');
  assert.equal(compactAge(at(2 * 86_400_000), now), '2d');
  assert.equal(compactAge(at(35 * 86_400_000), now), '5w');
  assert.equal(compactAge(at(120 * 86_400_000), now), '4mo');
  assert.equal(compactAge(at(800 * 86_400_000), now), '2y');
});

test('formatLocalDateTime is null for missing or invalid values', () => {
  assert.equal(formatLocalDateTime(null), null);
  assert.equal(formatLocalDateTime('garbage'), null);
  assert.equal(typeof formatLocalDateTime('2026-10-10T12:00:00Z'), 'string');
});
