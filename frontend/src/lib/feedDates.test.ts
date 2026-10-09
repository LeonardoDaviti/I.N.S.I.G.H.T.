import test from 'node:test';
import assert from 'node:assert/strict';

import { feedDateLabel, feedDayHeading, feedDayKey } from './feedDates.ts';

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
