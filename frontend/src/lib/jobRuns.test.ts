import test from 'node:test';
import assert from 'node:assert/strict';

import type { JobRun } from '../services/api';
import { formatJobDuration, jobGlyph, runningFetchJob, runProgressLine } from './jobRuns.ts';

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

test('runningFetchJob with a source: only a fetch job of that source', () => {
  const job = (id: string, source_id: string | null, status = 'running') => ({ id, status, job_type: 'ingestion_run', source_id }) as JobRun;
  assert.equal(runningFetchJob([job('all', null), job('mine', 'src-1')], 'src-1')?.id, 'mine');
  assert.equal(runningFetchJob([job('all', null), job('other', 'src-2')], 'src-1'), null);
  assert.equal(runningFetchJob([job('done', 'src-1', 'success')], 'src-1'), null);
});

test('runProgressLine: sources done of total and new posts, or null before the first source', () => {
  const run = (payload: Record<string, unknown>) => ({ id: 'r', status: 'running', job_type: 'ingestion_run', payload }) as unknown as JobRun;
  assert.equal(runProgressLine(run({ sources: { done: 52, total: 81 }, new_posts: 334 })), '52 of 81 sources · 334 new posts');
  assert.equal(runProgressLine(run({ sources: { done: 1, total: 1 }, new_posts: 1 })), '1 of 1 source · 1 new post');
  assert.equal(runProgressLine(run({})), null);
});
