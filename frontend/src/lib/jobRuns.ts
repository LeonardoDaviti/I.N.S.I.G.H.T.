/**
 * Job runs (job_runs rows) as the ingestion surfaces show them: a monochrome
 * glyph for the status and a short duration, for Sources → ingestion, and the
 * top bar's activity sign. Pure.
 */
import type { Status } from '../components/ui/styles';
import type { JobRun } from '../services/api';
import { toDate } from './dates.ts';
import { formatElapsed } from './duration.ts';

/** A job that has not finished: running, or queued to run. */
function isActive(status?: string | null): boolean {
  return status === 'running' || status === 'queued' || status === 'pending';
}

/** Job status -> monochrome glyph (design docs system/status.md). */
export function jobGlyph(status?: string | null): Status {
  if (status === 'failed') return 'failing';
  if (isActive(status)) return 'running';
  return 'ok';
}

/** "<1s", "42s", "2m 5s", "1h 2m"; null until the job has finished. */
export function formatJobDuration(startedAt?: string | null, finishedAt?: string | null): string | null {
  const started = toDate(startedAt);
  const finished = toDate(finishedAt);
  if (!started || !finished || finished < started) return null;
  return formatElapsed((finished.getTime() - started.getTime()) / 1000);
}

/** The jobs that fetch posts; the daily `scheduler_cycle` is not one. */
const FETCH_JOB_TYPES = new Set(['ingestion_run', 'archive_source']);
const FAILURE_NOTE_MS = 60 * 60_000;

/** The newest running (or queued) ingestion run or archive job (jobs come newest first), or
 *  null; with a source id, only one of that source's. */
export function runningFetchJob(jobs: readonly JobRun[] | undefined, sourceId?: string): JobRun | null {
  return jobs?.find((job) => isActive(job.status) && FETCH_JOB_TYPES.has(job.job_type)
    && (sourceId === undefined || job.source_id === sourceId)) ?? null;
}

/** A run's live counters (payload `sources` and `new_posts`), or null before the first source. */
export function runCounters(job: JobRun): { done: number; total: number; newPosts: number } | null {
  const sources = job.payload?.sources as { done?: unknown; total?: unknown } | undefined;
  const { done, total } = sources ?? {};
  if (typeof done !== 'number' || typeof total !== 'number' || total <= 0) return null;
  const newPosts = job.payload?.new_posts;
  return { done, total, newPosts: typeof newPosts === 'number' ? newPosts : 0 };
}

/** "fetching · 3 of 41" from the run's live counters, or "fetching" without them. */
export function fetchingLabel(job: JobRun): string {
  const counters = runCounters(job);
  return counters ? `fetching · ${counters.done} of ${counters.total}` : 'fetching';
}

/** "52 of 81 sources · 334 new posts" (one source: "1 of 1 source"), or null without counters. */
export function runProgressLine(job: JobRun): string | null {
  const counters = runCounters(job);
  if (!counters) return null;
  const { done, total, newPosts } = counters;
  return `${done} of ${total} source${total === 1 ? '' : 's'} · ${newPosts} new post${newPosts === 1 ? '' : 's'}`;
}

/** The newest ingestion run, when it failed and finished under an hour ago; else null. */
export function recentFailedRun(jobs: readonly JobRun[] | undefined, nowMs: number): JobRun | null {
  const newest = jobs?.find((job) => job.job_type === 'ingestion_run');
  const finished = toDate(newest?.finished_at);
  if (!newest || newest.status !== 'failed' || !finished) return null;
  return nowMs - finished.getTime() < FAILURE_NOTE_MS ? newest : null;
}
