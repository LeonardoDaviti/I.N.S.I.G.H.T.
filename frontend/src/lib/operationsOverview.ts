/**
 * The job labels as Sources → ingestion shows them. Pure.
 */
import type { JobRun } from '../services/api';

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
