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

/** The newest running (or queued) ingestion run or archive job (jobs come newest first), or null. */
export function runningFetchJob(jobs: readonly JobRun[] | undefined): JobRun | null {
  return jobs?.find((job) => isActive(job.status) && FETCH_JOB_TYPES.has(job.job_type)) ?? null;
}

/** "fetching · 3 of 41" from the run's live `sources` counter, or "fetching" without one. */
export function fetchingLabel(job: JobRun): string {
  const sources = job.payload?.sources as { done?: unknown; total?: unknown } | undefined;
  const { done, total } = sources ?? {};
  return typeof done === 'number' && typeof total === 'number' && total > 0 ? `fetching · ${done} of ${total}` : 'fetching';
}

/** The newest ingestion run, when it failed and finished under an hour ago; else null. */
export function recentFailedRun(jobs: readonly JobRun[] | undefined, nowMs: number): JobRun | null {
  const newest = jobs?.find((job) => job.job_type === 'ingestion_run');
  const finished = toDate(newest?.finished_at);
  if (!newest || newest.status !== 'failed' || !finished) return null;
  return nowMs - finished.getTime() < FAILURE_NOTE_MS ? newest : null;
}
