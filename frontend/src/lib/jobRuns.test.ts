import test from 'node:test';
import assert from 'node:assert/strict';

import { formatJobDuration, formatJobTimestamp, jobGlyph } from './jobRuns.ts';

test('jobGlyph maps job status to a monochrome glyph', () => {
  assert.equal(jobGlyph('failed'), 'failing');
  assert.equal(jobGlyph('running'), 'running');
  assert.equal(jobGlyph('queued'), 'running');
  assert.equal(jobGlyph('pending'), 'running');
  assert.equal(jobGlyph('success'), 'ok');
  assert.equal(jobGlyph(null), 'ok');
});

test('formatJobTimestamp is null for missing or invalid values', () => {
  assert.equal(formatJobTimestamp(null), null);
  assert.equal(formatJobTimestamp('garbage'), null);
  assert.equal(typeof formatJobTimestamp('2026-10-10T12:00:00Z'), 'string');
});

test('formatJobDuration is null until finished, and readable after', () => {
  const start = '2026-10-10T12:00:00Z';
  const after = (ms: number) => new Date(Date.parse(start) + ms).toISOString();
  assert.equal(formatJobDuration(start, null), null);
  assert.equal(formatJobDuration(null, after(1000)), null);
  assert.equal(formatJobDuration(after(1000), start), null);
  assert.equal(formatJobDuration(start, after(400)), '<1s');
  assert.equal(formatJobDuration(start, after(42_000)), '42s');
  assert.equal(formatJobDuration(start, after(125_000)), '2m 5s');
  assert.equal(formatJobDuration(start, after(3_725_000)), '1h 2m');
});
