/**
 * Job runs (job_runs rows) as the ingestion surfaces show them: a monochrome
 * glyph for the status, a local timestamp and a short duration. Shared by
 * Sources → ingestion and the analysis-on ingestion page. Pure.
 */
import type { Status } from '../components/ui/styles';

/** Job status -> monochrome glyph (design doc §8). */
export function jobGlyph(status?: string | null): Status {
  if (status === 'failed') return 'failing';
  if (status === 'running' || status === 'queued' || status === 'pending') return 'running';
  return 'ok';
}

export function formatJobTimestamp(value?: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
}

/** "<1s", "42s", "2m 5s", "1h 2m"; null until the job has finished. */
export function formatJobDuration(startedAt?: string | null, finishedAt?: string | null): string | null {
  if (!startedAt || !finishedAt) return null;
  const started = new Date(startedAt).getTime();
  const finished = new Date(finishedAt).getTime();
  if (Number.isNaN(started) || Number.isNaN(finished) || finished < started) return null;
  const elapsedMs = finished - started;
  if (elapsedMs < 1000) return '<1s';
  const totalSeconds = Math.round(elapsedMs / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
