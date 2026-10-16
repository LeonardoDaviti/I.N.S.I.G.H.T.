import test from 'node:test';
import assert from 'node:assert/strict';

import type { JobRun } from '../services/api';
import { formatJobDuration, jobGlyph, runningFetchJob } from './jobRuns.ts';

test('jobGlyph maps job status to a monochrome glyph', () => {
  assert.equal(jobGlyph('failed'), 'failing');
  assert.equal(jobGlyph('running'), 'running');
  assert.equal(jobGlyph('queued'), 'running');
  assert.equal(jobGlyph('pending'), 'running');
  assert.equal(jobGlyph('success'), 'ok');
  assert.equal(jobGlyph(null), 'ok');
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

test('runningFetchJob: the newest fetch job not yet finished, queued ones too', () => {
  const job = (id: string, status: string, job_type = 'ingestion_run') => ({ id, status, job_type }) as JobRun;
  assert.equal(runningFetchJob([job('q', 'queued'), job('r', 'running')])?.id, 'q');
  assert.equal(runningFetchJob([job('p', 'pending', 'archive_source')])?.id, 'p');
  assert.equal(runningFetchJob([job('d', 'running', 'scheduler_cycle'), job('s', 'success')]), null);
  assert.equal(runningFetchJob(undefined), null);
});
