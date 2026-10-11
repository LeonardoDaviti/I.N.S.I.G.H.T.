/**
 * Job runs (job_runs rows) as the ingestion surfaces show them: a monochrome
 * glyph for the status and a short duration, for Sources → ingestion. Pure.
 */
import type { Status } from '../components/ui/styles';
import { toDate } from './dates.ts';
import { formatElapsed } from './duration.ts';

/** Job status -> monochrome glyph (design docs system/status.md). */
export function jobGlyph(status?: string | null): Status {
  if (status === 'failed') return 'failing';
  if (status === 'running' || status === 'queued' || status === 'pending') return 'running';
  return 'ok';
}

/** "<1s", "42s", "2m 5s", "1h 2m"; null until the job has finished. */
export function formatJobDuration(startedAt?: string | null, finishedAt?: string | null): string | null {
  const started = toDate(startedAt);
  const finished = toDate(finishedAt);
  if (!started || !finished || finished < started) return null;
  return formatElapsed((finished.getTime() - started.getTime()) / 1000);
}
