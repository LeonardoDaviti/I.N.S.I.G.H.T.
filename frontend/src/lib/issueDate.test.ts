import test from 'node:test';
import assert from 'node:assert/strict';

import { formatIssueLong, formatIssueRange, formatIssueShort, parseIssueDate } from './issueDate.ts';

const NOW = new Date('2026-10-10T12:00:00Z');

test('a calendar date is the same day in every time zone (UTC midnight is not yesterday)', () => {
  // new Date('2026-09-29') is 2026-09-28 19:00 in New York; the issue is still the 29th.
  assert.equal(formatIssueShort('2026-09-29', NOW, 'America/New_York'), 'Sep 29');
  assert.equal(formatIssueLong('2026-09-29', 'America/New_York'), 'Tuesday, 29 September 2026');
  assert.equal(formatIssueLong('2026-09-29', 'Pacific/Auckland'), 'Tuesday, 29 September 2026');
});

test('an instant uses the reader\'s local day', () => {
  // 23:30 UTC on the 9th is already the 10th in UTC+2.
  assert.equal(formatIssueShort('2026-10-09T23:30:00Z', NOW, 'Europe/Berlin'), 'Oct 10');
  assert.equal(formatIssueShort('2026-10-09T23:30:00Z', NOW, 'UTC'), 'Oct 9');
});

test('another year shows the year so an old item never passes for this year\'s', () => {
  assert.equal(formatIssueShort('2023-11-25', NOW), 'Nov 25, 2023');
});

test('missing and garbage dates are an em dash, never "Invalid Date"', () => {
  for (const value of [null, undefined, '', 'not a date', Number.NaN]) {
    assert.equal(formatIssueShort(value as never, NOW), '—');
    assert.equal(formatIssueLong(value as never), '—');
  }
  assert.equal(parseIssueDate('nope'), null);
});

test('ranges collapse a shared year and a single day', () => {
  assert.equal(formatIssueRange('2026-08-30', '2026-09-29'), 'Aug 30 – Sep 29, 2026');
  assert.equal(formatIssueRange('2025-12-28', '2026-01-03'), 'Dec 28, 2025 – Jan 3, 2026');
  assert.equal(formatIssueRange('2026-09-29', '2026-09-29'), 'Sep 29, 2026');
  assert.equal(formatIssueRange(null, '2026-09-29'), 'Sep 29, 2026');
  assert.equal(formatIssueRange(null, undefined), '—');
});
