/**
 * Poll an async job until it finishes (Mark IX §F.3).
 *
 * Generic over what "the job" is: `fetchJob` reads the job once and reports a
 * `PollStep`. A thrown error counts against `maxConsecutiveErrors` when it is
 * transient (network, 408, 429, 5xx: a backend restart mid-run must not lose the
 * run), and rejects immediately otherwise. Any successful read resets the count.
 *
 * Pure apart from timers; `sleep` and `now` are injectable for tests.
 */
import { isAbortError, isTransientError } from './apiError.ts';

export type PollStep<T> =
  | { state: 'pending' }
  | { state: 'done'; value: T }
  | { state: 'failed'; error: string; value?: T };

export interface PollJobOptions<T = unknown> {
  signal?: AbortSignal;
  /** Wait between reads. Default 1500ms. */
  intervalMs?: number;
  /** Give up after this long. Default 10 minutes. */
  timeoutMs?: number;
  /** Consecutive transient read errors tolerated before rejecting. Default 3 (the 3rd rejects). */
  maxConsecutiveErrors?: number;
  isTransient?: (error: unknown) => boolean;
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
  now?: () => number;
  /** Called after each successful read; handy for progress UI. */
  onStep?: (step: PollStep<T>) => void;
}

/** The job reached a terminal failed state. `value` is the job payload, if any. */
export class JobFailedError<T = unknown> extends Error {
  readonly value: T | undefined;
  constructor(message: string, value?: T) {
    super(message);
    this.name = 'JobFailedError';
    this.value = value;
  }
}

export class JobTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`The job did not finish within ${Math.round(timeoutMs / 1000)}s`);
    this.name = 'JobTimeoutError';
  }
}

function abortError(signal: AbortSignal): Error {
  const reason: unknown = signal.reason;
  if (isAbortError(reason)) return reason as Error;
  return new DOMException('The operation was aborted', 'AbortError');
}

export function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError(signal));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError(signal as AbortSignal));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export async function pollJob<T>(
  fetchJob: (signal?: AbortSignal) => Promise<PollStep<T>>,
  options: PollJobOptions<T> = {},
): Promise<T> {
  const {
    signal,
    intervalMs = 1_500,
    timeoutMs = 600_000,
    maxConsecutiveErrors = 3,
    isTransient = isTransientError,
    sleep = abortableSleep,
    now = Date.now,
    onStep,
  } = options;

  const startedAt = now();
  let consecutiveErrors = 0;
  let attempt = 0;

  for (;;) {
    if (signal?.aborted) throw abortError(signal);
    if (attempt > 0 && now() - startedAt >= timeoutMs) throw new JobTimeoutError(timeoutMs);
    attempt += 1;

    let step: PollStep<T> | null = null;
    try {
      step = await fetchJob(signal);
    } catch (error) {
      if (signal?.aborted) throw abortError(signal);
      if (isAbortError(error) || !isTransient(error)) throw error;
      consecutiveErrors += 1;
      if (consecutiveErrors >= maxConsecutiveErrors) throw error;
    }

    if (step) {
      consecutiveErrors = 0;
      onStep?.(step);
      if (step.state === 'done') return step.value;
      if (step.state === 'failed') throw new JobFailedError<T>(step.error, step.value);
    }

    await sleep(intervalMs, signal);
  }
}
