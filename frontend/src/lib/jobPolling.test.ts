import test from 'node:test';
import assert from 'node:assert/strict';

import { ApiError } from './apiError.ts';
import { JobFailedError, JobTimeoutError, pollJob, type PollStep } from './jobPolling.ts';

/** A scripted fetchJob: each call consumes the next entry (Error => thrown). */
function scripted<T>(steps: Array<PollStep<T> | Error>) {
  let calls = 0;
  const fetchJob = async (): Promise<PollStep<T>> => {
    const step = steps[Math.min(calls, steps.length - 1)];
    calls += 1;
    if (step instanceof Error) throw step;
    return step;
  };
  return { fetchJob, calls: () => calls };
}

const pending = { state: 'pending' } as const;

test('pollJob resolves with the value once the job is done', async () => {
  const job = scripted<number>([pending, pending, { state: 'done', value: 42 }]);
  assert.equal(await pollJob(job.fetchJob, { intervalMs: 1 }), 42);
  assert.equal(job.calls(), 3);
});

test('pollJob tolerates 2 transient errors in a row and then resolves', async () => {
  const job = scripted<string>([
    new ApiError(503, 'unavailable'),
    new TypeError('Failed to fetch'),
    { state: 'done', value: 'ok' },
  ]);
  assert.equal(await pollJob(job.fetchJob, { intervalMs: 1 }), 'ok');
});

test('pollJob rejects on the 3rd consecutive transient error with the last error', async () => {
  const last = new ApiError(502, 'bad gateway');
  const job = scripted<string>([new ApiError(503, 'a'), new ApiError(503, 'b'), last, { state: 'done', value: 'late' }]);
  await assert.rejects(pollJob(job.fetchJob, { intervalMs: 1 }), (err) => err === last);
  assert.equal(job.calls(), 3);
});

test('a successful poll resets the consecutive error count', async () => {
  const job = scripted<string>([
    new ApiError(503, 'a'),
    new ApiError(503, 'b'),
    pending,
    new ApiError(503, 'c'),
    new ApiError(503, 'd'),
    { state: 'done', value: 'ok' },
  ]);
  assert.equal(await pollJob(job.fetchJob, { intervalMs: 1 }), 'ok');
});

test('maxConsecutiveErrors is configurable', async () => {
  const job = scripted<string>([new ApiError(503, 'a'), { state: 'done', value: 'ok' }]);
  await assert.rejects(pollJob(job.fetchJob, { intervalMs: 1, maxConsecutiveErrors: 1 }), ApiError);
});

test('a non-transient error (404) rejects immediately', async () => {
  const job = scripted<string>([new ApiError(404, 'Job not found'), { state: 'done', value: 'ok' }]);
  await assert.rejects(pollJob(job.fetchJob, { intervalMs: 1 }), /Job not found/);
  assert.equal(job.calls(), 1);
});

test('a failed job rejects with JobFailedError carrying the job message', async () => {
  const job = scripted<string>([pending, { state: 'failed', error: 'Run lock held' }]);
  await assert.rejects(pollJob(job.fetchJob, { intervalMs: 1 }), (err) => {
    assert.ok(err instanceof JobFailedError);
    assert.equal((err as Error).message, 'Run lock held');
    return true;
  });
});

test('abort rejects with an AbortError and stops polling', async () => {
  const controller = new AbortController();
  const job = scripted<string>([pending]);
  const promise = pollJob(job.fetchJob, { intervalMs: 50, signal: controller.signal });
  setTimeout(() => controller.abort(), 5);
  await assert.rejects(promise, (err) => (err as Error).name === 'AbortError');
  const callsAtAbort = job.calls();
  await new Promise((resolve) => setTimeout(resolve, 80));
  assert.equal(job.calls(), callsAtAbort);
});

test('an already-aborted signal rejects without calling fetchJob', async () => {
  const controller = new AbortController();
  controller.abort();
  const job = scripted<string>([{ state: 'done', value: 'ok' }]);
  await assert.rejects(pollJob(job.fetchJob, { signal: controller.signal }), (err) => (err as Error).name === 'AbortError');
  assert.equal(job.calls(), 0);
});

test('pollJob rejects with JobTimeoutError when the job never finishes', async () => {
  let clock = 0;
  const job = scripted<string>([pending]);
  await assert.rejects(
    pollJob(job.fetchJob, {
      intervalMs: 1000,
      timeoutMs: 5000,
      now: () => clock,
      sleep: async (ms) => {
        clock += ms;
      },
    }),
    JobTimeoutError,
  );
  assert.equal(job.calls(), 5);
});
