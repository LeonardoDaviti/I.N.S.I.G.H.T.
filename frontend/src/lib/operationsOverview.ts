import type { JobRun, OperationsOverviewResponse, SourceHealthRow, SourceHealthSummary } from '../services/api';

type CompactMode = 'summary' | 'detail';

type CompactOptions = {
  arrayPreview: number;
  eventPreview: number;
  maxDepth: number;
  maxObjectKeys: number;
};

const SUMMARY_OPTIONS: CompactOptions = {
  arrayPreview: 2,
  eventPreview: 3,
  maxDepth: 5,
  maxObjectKeys: 8,
};

const DETAIL_OPTIONS: CompactOptions = {
  arrayPreview: 3,
  eventPreview: 12,
  maxDepth: 4,
  maxObjectKeys: 12,
};

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function looksLikeEntityMap(value: Record<string, unknown>): boolean {
  const keys = Object.keys(value);
  if (keys.length < 6) {
    return false;
  }

  const entityLikeKeys = keys.filter((key) => /^[0-9a-f-]{8,}$/i.test(key) || /^\d+$/.test(key));
  return entityLikeKeys.length >= Math.ceil(keys.length * 0.6);
}

function compactArray(value: unknown[], options: CompactOptions, depth: number, key: string): unknown[] {
  const previewCount = key === 'events'
    ? options.eventPreview
    : key === 'sample_ids'
      ? Math.max(3, options.arrayPreview)
      : options.arrayPreview;
  if (value.length <= previewCount) {
    return value.map((item) => compactValue(item, options, depth + 1, key));
  }

  const preview = value
    .slice(0, previewCount)
    .map((item) => compactValue(item, options, depth + 1, key));

  return [
    ...preview,
    { truncated_items: value.length - preview.length },
  ];
}

function compactObject(value: Record<string, unknown>, options: CompactOptions, depth: number, key: string): Record<string, unknown> {
  if (depth >= options.maxDepth) {
    return { truncated_keys: Object.keys(value).length };
  }

  if (key === 'posts' && looksLikeEntityMap(value)) {
    const keys = Object.keys(value);
    return {
      count: keys.length,
      sample_ids: keys.slice(0, 3),
      truncated_items: Math.max(0, keys.length - 3),
    };
  }

  const entries = Object.entries(value);
  const limitedEntries = entries.slice(0, options.maxObjectKeys);
  const compacted = Object.fromEntries(
    limitedEntries.map(([entryKey, entryValue]) => [
      entryKey,
      compactValue(entryValue, options, depth + 1, entryKey),
    ]),
  );

  if (entries.length > limitedEntries.length) {
    compacted.truncated_keys = entries.length - limitedEntries.length;
  }

  return compacted;
}

function compactValue(value: unknown, options: CompactOptions, depth: number, key: string): unknown {
  if (value == null || typeof value !== 'object') {
    return value;
  }

  if (Array.isArray(value)) {
    return compactArray(value, options, depth, key);
  }

  if (isPlainObject(value)) {
    return compactObject(value, options, depth, key);
  }

  return value;
}

/** The run report lists RunReportSummary renders. The backend already caps each at 20
 *  entries, so they are kept whole; only the job's `events` log is trimmed. */
const RUN_REPORT_LISTS = new Set(['failures', 'post_failures', 'inserted_by_source', 'decisions', 'selector']);

function compactRunReportPayload(payload: Record<string, unknown>, options: CompactOptions): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(payload).map(([key, value]) => [
      key,
      RUN_REPORT_LISTS.has(key) ? value : compactValue(value, options, 1, key),
    ]),
  );
}

export function compactJobRun(job: JobRun, mode: CompactMode = 'summary'): JobRun {
  const options = mode === 'detail' ? DETAIL_OPTIONS : SUMMARY_OPTIONS;
  if (!job.payload) {
    return job;
  }

  if (job.job_type === 'ingestion_run') {
    return { ...job, payload: compactRunReportPayload(job.payload, options) as JobRun['payload'] };
  }

  return {
    ...job,
    payload: compactValue(job.payload, options, 0, 'payload') as JobRun['payload'],
  };
}

const EMPTY_SUMMARY: SourceHealthSummary = { due_now: 0, deferred: 0, backoff: 0, unavailable: 0, errors: 0 };

/** `overview.source_health` as `{summary, rows}`. The Mark VIII array shape (an old
 *  backend during a rolling deploy) or a missing value degrade to an empty summary. */
export function normalizeSourceHealth(value: unknown): { summary: SourceHealthSummary; rows: SourceHealthRow[] } {
  if (!isPlainObject(value)) return { summary: { ...EMPTY_SUMMARY }, rows: [] };
  const summary = isPlainObject(value.summary) ? { ...EMPTY_SUMMARY, ...(value.summary as Partial<SourceHealthSummary>) } : { ...EMPTY_SUMMARY };
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

export function compactOperationsOverview(overview: OperationsOverviewResponse): OperationsOverviewResponse {
  return {
    ...overview,
    jobs: (overview.jobs || []).map((job) => compactJobRun(job, 'summary')),
  };
}
