/**
 * Job runs (job_runs rows) as the ingestion surfaces show them: a monochrome
 * glyph for the status, a short duration, a one-line summary and the events
 * worth reading, for Sources → ingestion, and the
 * top bar's activity sign. Pure.
 */
import type { Status } from '../components/ui/styles';
import type { ArchiveWaiting, JobRun } from '../services/api';
import { waitingLine } from './archiveWaiting.ts';
import { toDate } from './dates.ts';
import { formatElapsed } from './duration.ts';
import { asRunReport, summarizeRunReport } from './runReport.ts';
import { isRecord } from './utils.ts';

/** A job that has not finished: running, or queued to run. */
function isActive(status?: string | null): boolean {
  return status === 'running' || status === 'queued' || status === 'pending';
}

/** Job status -> monochrome glyph (design docs system/status.md). */
export function jobGlyph(status?: string | null): Status {
  if (status === 'failed' || status === 'interrupted') return 'failing';   // interrupted: a restart ended it (0070)
  if (isActive(status)) return 'running';
  if (status === 'waiting') return 'scheduled';   // an archive waiting out a host's limit (0107)
  return 'ok';
}

/** What a waiting archive job waits for (issue 0107: a host's limit; it continues by itself), or null. */
export function jobWaiting(job: Pick<JobRun, 'status' | 'payload'>): ArchiveWaiting | null {
  const payload = job.payload ?? {};
  if (job.status !== 'waiting' || typeof payload.waiting_until !== 'string' || typeof payload.waiting_host !== 'string') return null;
  return { host: payload.waiting_host, until: payload.waiting_until,
    reason: typeof payload.waiting_reason === 'string' ? payload.waiting_reason : null };
}

/** "<1s", "42s", "2m 5s", "1h 2m"; null until the job has finished. */
export function formatJobDuration(startedAt?: string | null, finishedAt?: string | null): string | null {
  const started = toDate(startedAt);
  const finished = toDate(finishedAt);
  if (!started || !finished || finished < started) return null;
  return formatElapsed((finished.getTime() - started.getTime()) / 1000);
}

/** How long a job ran: a job a restart ended ran until its last event before that, not until the
 *  restart closed it a day later (issue 0072). */
export function jobDuration(job: JobRun): string | null {
  const events = job.status === 'interrupted' && Array.isArray(job.payload?.events)
    ? (job.payload.events as Array<Record<string, unknown>>).filter((event) => event.status !== 'interrupted') : [];
  const last = events.length ? events[events.length - 1].at : null;
  if (job.status === 'interrupted') return typeof last === 'string' ? formatJobDuration(job.started_at, last) : null;   // unknown: none
  return formatJobDuration(job.started_at, job.finished_at);
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

/** A job's one line: what an ingestion run delivered ("9 new posts from 2 sources"), else its message, the
 *  source it names by its name, not its id ("Fetch <source name>", issue 0072). */
export function jobSummary(job: JobRun): string | null {
  const report = job.job_type === 'ingestion_run' ? asRunReport(job.payload) : null;
  if (report) return summarizeRunReport(report).headline;
  const waiting = jobWaiting(job);
  if (waiting) return waitingLine(waiting);
  const message = job.message || null;
  return message && job.source_id && job.source_display_name
    ? message.replace(`source ${job.source_id}`, job.source_display_name).replace(job.source_id, job.source_display_name) : message;
}

export type JobEvent = { at?: string; level?: string; message?: string };

/** Phases whose event only repeated the run's summary (stored before issue 0021). */
const NOISE_PHASES = new Set(['decided', 'saved']);

/** A job's events worth reading: the per-source lines, not the ones that repeat its summary. */
export function jobEvents(job: JobRun): JobEvent[] {
  const events = Array.isArray(job.payload?.events) ? job.payload.events as Array<Record<string, unknown>> : [];
  return events.filter((event) => {
    const phase = isRecord(event.data) ? event.data.phase : undefined;
    if (typeof phase === 'string' && NOISE_PHASES.has(phase)) return false;
    return !('status' in event && event.message === job.message);
  }).map(localWaitingEvent) as JobEvent[];
}

/** A waiting event (issue 0107) says when it continues in the reader's time, as of when it was written. */
function localWaitingEvent(event: Record<string, unknown>): Record<string, unknown> {
  const data = isRecord(event.data) ? event.data : null;
  if (!data || data.stage !== 'waiting' || typeof data.host !== 'string' || typeof data.waiting_until !== 'string') return event;
  const written = toDate(event.at as string | undefined) ?? new Date(0);
  const reason = data.timed_out ? 'timeout' : 'limit';
  return { ...event, message: waitingLine({ host: data.host, until: data.waiting_until, reason }, written) };
}

/** The newest ingestion run, when it failed and finished under an hour ago; else null. */
export function recentFailedRun(jobs: readonly JobRun[] | undefined, nowMs: number): JobRun | null {
  const newest = jobs?.find((job) => job.job_type === 'ingestion_run');
  const finished = toDate(newest?.finished_at);
  if (!newest || newest.status !== 'failed' || !finished) return null;
  return nowMs - finished.getTime() < FAILURE_NOTE_MS ? newest : null;
}
