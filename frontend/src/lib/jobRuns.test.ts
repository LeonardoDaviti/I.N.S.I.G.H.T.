import test from 'node:test';
import assert from 'node:assert/strict';

import type { JobRun } from '../services/api';
import { apiRestartLine, formatJobDuration, jobDuration, jobEvents, jobGlyph, jobSummary, jobWaiting, runningFetchJob, runProgressLine } from './jobRuns.ts';

test('jobGlyph maps job status to a monochrome glyph', () => {
  assert.equal(jobGlyph('failed'), 'failing');
  assert.equal(jobGlyph('interrupted'), 'failing');
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

test('jobSummary: an ingestion run reads as what it delivered, other jobs keep their message', () => {
  const run = { id: 'r', status: 'success', job_type: 'ingestion_run', message: '2 due, 76 deferred, 0 failed; 9 new posts',
    payload: { status: 'success', sources_considered: 78, sources_fetched: 2, posts_inserted: 9, sources_with_new: 2 } } as unknown as JobRun;
  assert.equal(jobSummary(run), '9 new posts from 2 sources');
  assert.equal(jobSummary({ ...run, status: 'running', payload: { selector: { kind: 'all' } } }), '2 due, 76 deferred, 0 failed; 9 new posts');
  assert.equal(jobSummary({ id: 'a', status: 'success', job_type: 'archive_source', message: 'Archived 40 posts' } as JobRun), 'Archived 40 posts');
  assert.equal(jobSummary({ id: 'a', status: 'success', job_type: 'archive_source' } as JobRun), null);
});

test('a job a restart ended names its source and ran until its last event, not the restart (issue 0072)', () => {
  const job = {
    id: 'j', status: 'interrupted', job_type: 'ingestion_run', message: 'Fetch source f6d4-1', source_id: 'f6d4-1',
    source_display_name: 'A Newsletter', started_at: '2026-10-30T21:31:37Z', finished_at: '2026-10-31T22:49:46Z',
    payload: { events: [
      { at: '2026-10-30T21:31:45Z', level: 'info', message: 'A Newsletter: 20 new of 20' },
      { at: '2026-10-31T22:49:46Z', level: 'error', status: 'interrupted', message: 'Interrupted by a restart' },
    ] },
  } as unknown as JobRun;
  assert.equal(jobSummary(job), 'Fetch A Newsletter');
  assert.equal(jobDuration(job), '8s');
  assert.equal(jobDuration({ ...job, payload: {} }), null, 'no events (the list): no length we know of, never the restart\'s');
  assert.equal(jobDuration({ ...job, status: 'success' }), '25h 18m', 'a finished job: start to finish');
});

test('jobEvents: the per-source lines, without the lines that repeat the summary', () => {
  const events = [
    { at: '1', level: 'info', message: 'Ingestion decided', data: { phase: 'decided' } },
    { at: '2', level: 'info', message: 'r/viture: 3 new of 25 · 1 of 2 sources', data: { phase: 'source' } },
    { at: '3', level: 'warning', message: 'reddit.com: too many requests, slowing to 16 s', data: { phase: 'slowed' } },
    { at: '4', level: 'error', message: 'HN: failed, HTTP 503 · 2 of 2 sources', data: { phase: 'source' } },
    { at: '5', level: 'info', message: 'Ingestion saved', data: { phase: 'saved' } },
    { at: '6', level: 'error', message: '0 due, 222 deferred, 1 failed; 3 new posts', status: 'failed' },
  ];
  const run = { id: 'r', status: 'failed', job_type: 'ingestion_run', message: '0 due, 222 deferred, 1 failed; 3 new posts', payload: { events } } as unknown as JobRun;
  assert.deepEqual(jobEvents(run).map((event) => event.at), ['2', '3', '4']);
  assert.deepEqual(jobEvents({ id: 'a', status: 'success', job_type: 'archive_source' } as JobRun), []);
});

test('a waiting archive (issue 0107) is scheduled, not running, and says when it continues', () => {
  assert.equal(jobGlyph('waiting'), 'scheduled');
  const job = {
    id: 'j', job_type: 'archive_source', status: 'waiting', trigger: 'manual', message: "Waiting for bridge.example's limit",
    payload: { waiting_until: '2099-01-01T10:05:00Z', waiting_host: 'bridge.example', waiting_reason: 'limit' },
  } as JobRun;
  assert.deepEqual(jobWaiting(job), { host: 'bridge.example', until: '2099-01-01T10:05:00Z', reason: 'limit' });
  assert.match(jobSummary(job) ?? '', /^Waiting for bridge\.example's limit: continues at \d\d:\d\d$/);
  assert.equal(runningFetchJob([job]), null, 'the top bar does not say fetching while it waits');
  assert.equal(jobWaiting({ ...job, status: 'success' }), null, 'a finished job waits for nothing');
});

test('a waiting event reads in the reader\'s time, as of when it was written', () => {
  const job = {
    id: 'j', job_type: 'archive_source', status: 'running', trigger: 'scheduler',
    payload: { events: [{ at: '2026-11-05T10:00:00Z', level: 'warning', message: "Waiting for bridge.example's limit: continues at 10:05 UTC",
                          data: { stage: 'waiting', host: 'bridge.example', waiting_until: '2026-11-05T10:05:00Z' } }] },
  } as JobRun;
  assert.match(jobEvents(job)[0].message ?? '', /^Waiting for bridge\.example's limit: continues at \d\d:\d\d$/);
});

test('apiRestartLine: an API restart record says its times in the reader zone, not the container UTC (issue 0124)', () => {
  const restart = { id: 'r', status: 'failed', job_type: 'api_restart', started_at: '2026-11-06T10:53:23Z',
    message: 'The API was restarted after 2 min of no answer',
    payload: { kind: 'restart', failing_seconds: 90, at: '2026-11-06T10:53:23+00:00' } } as JobRun;
  assert.equal(apiRestartLine(restart, 'Europe/Istanbul'), 'The API was restarted at 13:53 after 2 min of no answer');
  assert.equal(apiRestartLine(restart, 'UTC'), 'The API was restarted at 10:53 after 2 min of no answer');
  assert.equal(jobSummary(restart, 'Asia/Dubai'), 'The API was restarted at 14:53 after 2 min of no answer');
  // a record written before 0124: its clock was the container's (UTC) in the message; the page writes it from its start
  const old = { ...restart, message: 'The API was restarted at 10:53 after 2 min of no answer',
    payload: { kind: 'restart', failing_seconds: 128 } } as JobRun;
  assert.equal(apiRestartLine(old, 'Asia/Dubai'), 'The API was restarted at 14:53 after 2 min of no answer');
  const gaveUp = { id: 'g', status: 'failed', job_type: 'api_restart', started_at: '2026-11-06T10:59:53Z',
    message: 'The API keeps failing: 3 restarts in the last hour, so no more for 40 min; it has not answered for 6 min',
    payload: { kind: 'gave_up', failing_seconds: 360, at: '2026-11-06T10:59:53+00:00', until: '2026-11-06T11:40:43+00:00', restarts: 3 } } as JobRun;
  assert.equal(apiRestartLine(gaveUp, 'Asia/Dubai'),
    'The API keeps failing: 3 restarts in the last hour, so no more until 15:40; it has not answered for 6 min');
  const oldGaveUp = { ...gaveUp, message: 'The API keeps failing: 3 restarts in the last hour, so no more until 11:40; it has not answered for 6 min',
    payload: { kind: 'gave_up', failing_seconds: 360 } } as JobRun;
  assert.equal(apiRestartLine(oldGaveUp, 'Asia/Dubai'),
    'The API keeps failing: 3 restarts in the last hour, so no more for up to an hour; it has not answered for 6 min');
  // other jobs: none
  assert.equal(apiRestartLine({ id: 'a', status: 'success', job_type: 'archive_source', message: 'x' } as JobRun), null);
});
