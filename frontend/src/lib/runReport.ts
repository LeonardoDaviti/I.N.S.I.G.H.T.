/**
 * Run report presentation (Mark IX §F.3, issue 0021): what a fetch run delivered,
 * in words ("34 new posts from 5 sources", "Nothing new: 12 sources checked"),
 * with a feedback tone; the backend's `RunReport.summary_line` says the same.
 * Pure; `asRunReport` is the one parser for job payloads (it tolerates the job
 * compaction sentinels, missing lists and the fields of old stored reports).
 */
import type { RunReport } from '../services/api';
import { isRecord } from './utils.ts';
import { plural } from './format.ts';

/** The feedback kinds of spec §F.7 (same names as `components/states/Notice`). */
export type RunReportTone = 'status' | 'completion' | 'warning' | 'error';

export interface RunReportSummaryText {
  headline: string;
  lines: string[];
  tone: RunReportTone;
}

const RUN_STATUSES = new Set(['success', 'partial', 'failed', 'skipped_busy', 'nothing_due']);

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** Drop `{truncated_items: N}` and other non-object entries from a compacted list. */
function records<T>(value: unknown, required: string): T[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => isRecord(item) && required in item) as T[];
}

/** A job payload -> RunReport, or null when the payload is not a run report
 *  (for example the `{success: false, error}` of a run that raised). */
export function asRunReport(payload: unknown): RunReport | null {
  if (!isRecord(payload)) return null;
  if (typeof payload.status !== 'string' || !RUN_STATUSES.has(payload.status)) return null;
  if (typeof payload.posts_inserted !== 'number' || typeof payload.sources_considered !== 'number') return null;
  return {
    run_id: typeof payload.run_id === 'string' ? payload.run_id : null,
    status: payload.status as RunReport['status'],
    duration_s: typeof payload.duration_s === 'number' ? payload.duration_s : undefined,
    sources_considered: num(payload.sources_considered),
    sources_fetched: num(payload.sources_fetched),
    sources_failed: num(payload.sources_failed),
    sources_with_new: typeof payload.sources_with_new === 'number' ? payload.sources_with_new : undefined,
    posts_inserted: num(payload.posts_inserted),
    posts_failed: num(payload.posts_failed),
    failures: records(payload.failures, 'error'),
    inserted_by_source: records(payload.inserted_by_source, 'inserted'),
  };
}

/** "34 new posts from 5 sources", "3 sources failed", both, or "Nothing new: 12 sources checked". */
function outcome(report: RunReport): string {
  const parts: string[] = [];
  if (report.posts_inserted > 0) {
    const sources = report.sources_with_new ?? report.inserted_by_source.length;
    parts.push(`${plural(report.posts_inserted, 'new post')} from ${plural(sources, 'source')}`);
  }
  if (report.sources_failed > 0) parts.push(`${plural(report.sources_failed, 'source')} failed`);
  return parts.join(', ') || `Nothing new: ${plural(report.sources_fetched, 'source')} checked`;
}

export function summarizeRunReport(report: RunReport): RunReportSummaryText {
  if (report.status === 'skipped_busy') {
    return { headline: 'Skipped: another run is in progress', lines: [], tone: 'warning' };
  }
  if (report.status === 'nothing_due') return { headline: 'Nothing was due', lines: [], tone: 'completion' };
  const lines = report.posts_failed > 0 ? [`${plural(report.posts_failed, 'post')} could not be saved`] : [];
  const tone = report.status === 'failed' ? 'error' : report.status === 'partial' ? 'warning' : 'completion';
  return { headline: outcome(report), lines, tone };
}
