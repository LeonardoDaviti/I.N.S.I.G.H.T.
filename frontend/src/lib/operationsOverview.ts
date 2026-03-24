import type { JobRun, OperationsOverviewResponse } from '../services/api';

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

function isPlainObject(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function looksLikeEntityMap(value: Record<string, any>): boolean {
  const keys = Object.keys(value);
  if (keys.length < 6) {
    return false;
  }

  const entityLikeKeys = keys.filter((key) => /^[0-9a-f-]{8,}$/i.test(key) || /^\d+$/.test(key));
  return entityLikeKeys.length >= Math.ceil(keys.length * 0.6);
}

function compactArray(value: any[], options: CompactOptions, depth: number, key: string): any[] {
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

function compactObject(value: Record<string, any>, options: CompactOptions, depth: number, key: string): Record<string, any> {
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

export function compactJobRun(job: JobRun, mode: CompactMode = 'summary'): JobRun {
  const options = mode === 'detail' ? DETAIL_OPTIONS : SUMMARY_OPTIONS;
  if (!job.payload) {
    return job;
  }

  return {
    ...job,
    payload: compactValue(job.payload, options, 0, 'payload') as Record<string, any>,
  };
}

export function compactOperationsOverview(overview: OperationsOverviewResponse): OperationsOverviewResponse {
  return {
    ...overview,
    jobs: (overview.jobs || []).map((job) => compactJobRun(job, 'summary')),
  };
}
