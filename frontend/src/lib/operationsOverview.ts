/**
 * The operations overview as Sources → ingestion reads it: the source health
 * block and the job labels. Pure.
 */
import type { JobRun, SourceHealthRow, SourceHealthSummary } from '../services/api';
import { isRecord } from './utils.ts';

const EMPTY_SUMMARY: SourceHealthSummary = { due_now: 0, deferred: 0, backoff: 0, unavailable: 0, errors: 0 };

/** `overview.source_health` as `{summary, rows}`. The Mark VIII array shape (an old
 *  backend during a rolling deploy) or a missing value degrade to an empty summary. */
export function normalizeSourceHealth(value: unknown): { summary: SourceHealthSummary; rows: SourceHealthRow[] } {
  if (!isRecord(value)) return { summary: { ...EMPTY_SUMMARY }, rows: [] };
  const summary = isRecord(value.summary) ? { ...EMPTY_SUMMARY, ...(value.summary as Partial<SourceHealthSummary>) } : { ...EMPTY_SUMMARY };
  const rows = Array.isArray(value.rows) ? (value.rows as SourceHealthRow[]) : [];
  return { summary, rows };
}

const JOB_LABELS: Record<string, string> = {
  ingestion_run: 'Ingestion run',
  scheduler_cycle: 'Daily work',
  archive_source: 'Archive',
};

/** The human label for a job: the backend's `job_label`, a local fallback, then the type. */
export function jobLabel(job: Pick<JobRun, 'job_type' | 'job_label'>): string {
  if (job.job_label) return job.job_label;
  const known = JOB_LABELS[job.job_type];
  if (known) return known;
  const text = (job.job_type || '').replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
