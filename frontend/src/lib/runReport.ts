/**
 * Run report presentation (Mark IX §F.3): turn the typed result of a fetch run
 * into a headline, a few plain lines and a feedback tone, so no surface ever
 * shows the raw JSON by default. Pure; `asRunReport` is the one parser for job
 * payloads (it tolerates the job compaction sentinels and missing lists).
 */
import type { DecisionKind, RunReport } from '../services/api';
import { isRecord } from './utils.ts';
import { formatCount, plural } from './format.ts';

/** The feedback kinds of spec §F.7 (same names as `components/states/Notice`). */
export type RunReportTone = 'status' | 'completion' | 'warning' | 'error';

export interface RunReportSummaryText {
  headline: string;
  lines: string[];
  tone: RunReportTone;
}

export const DECISION_KINDS: readonly DecisionKind[] = [
  'fetch_new_source',
  'fetch_due',
  'fetch_retry',
  'fetch_forced',
  'skip_not_due',
  'skip_backoff',
  'skip_unavailable',
  'skip_disabled',
];

/** How each fetch decision reads in a sentence ("63 not due yet"). */
export const DECISION_LABELS: Record<DecisionKind, string> = {
  fetch_new_source: 'new source',
  fetch_due: 'due',
  fetch_retry: 'retried after an error',
  fetch_forced: 'forced',
  skip_not_due: 'not due yet',
  skip_backoff: 'in backoff',
  skip_unavailable: 'unavailable',
  skip_disabled: 'disabled',
};

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

  const decisions: Partial<Record<DecisionKind, number>> = {};
  if (isRecord(payload.decisions)) {
    for (const kind of DECISION_KINDS) {
      const count = payload.decisions[kind];
      if (typeof count === 'number' && count > 0) decisions[kind] = count;
    }
  }
  const selector = isRecord(payload.selector) && typeof payload.selector.kind === 'string'
    ? payload.selector as RunReport['selector']
    : { kind: 'all' as const };
  const trigger = payload.trigger === 'scheduler' || payload.trigger === 'cli' ? payload.trigger : 'manual';

  return {
    run_id: typeof payload.run_id === 'string' ? payload.run_id : null,
    trigger,
    selector,
    force: Boolean(payload.force),
    status: payload.status as RunReport['status'],
    summary: typeof payload.summary === 'string' ? payload.summary : undefined,
    started_at: typeof payload.started_at === 'string' ? payload.started_at : '',
    finished_at: typeof payload.finished_at === 'string' ? payload.finished_at : '',
    duration_s: typeof payload.duration_s === 'number' ? payload.duration_s : undefined,
    sources_considered: num(payload.sources_considered),
    sources_fetched: num(payload.sources_fetched),
    sources_failed: num(payload.sources_failed),
    decisions,
    posts_fetched: num(payload.posts_fetched),
    posts_inserted: num(payload.posts_inserted),
    posts_updated: num(payload.posts_updated),
    posts_failed: num(payload.posts_failed),
    failures: records(payload.failures, 'error'),
    post_failures: records(payload.post_failures, 'error'),
    inserted_by_source: records(payload.inserted_by_source, 'inserted'),
  };
}

function newPosts(count: number): string {
  return count === 0 ? 'No new posts' : plural(count, 'new post');
}

/** "63 not due yet, 3 unavailable": the skipped decisions, biggest first. */
function skippedLine(report: RunReport): string | null {
  const parts = DECISION_KINDS
    .filter((kind) => kind.startsWith('skip_'))
    .map((kind) => [kind, report.decisions[kind] ?? 0] as const)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([kind, count]) => `${formatCount(count)} ${DECISION_LABELS[kind]}`);
  return parts.length ? `Skipped: ${parts.join(', ')}` : null;
}

export function summarizeRunReport(report: RunReport): RunReportSummaryText {
  const lines: string[] = [];

  if (report.status === 'skipped_busy') {
    return {
      headline: 'Skipped: another run is in progress',
      lines: ['A full ingestion run already holds the run lock. Try again when it finishes.'],
      tone: 'warning',
    };
  }

  if (report.sources_considered > 0 && report.status !== 'nothing_due') {
    lines.push(`Fetched ${formatCount(report.sources_fetched)} of ${plural(report.sources_considered, 'source')}`);
  }
  if (report.force) lines.push('Cadence and backoff were ignored (forced)');
  const skipped = skippedLine(report);
  if (skipped) lines.push(skipped);
  if (report.posts_updated > 0) lines.push(`${plural(report.posts_updated, 'post')} updated`);
  if (report.posts_failed > 0) lines.push(`${plural(report.posts_failed, 'post')} could not be saved`);

  switch (report.status) {
    case 'nothing_due':
      return { headline: 'Nothing was due', lines, tone: 'completion' };
    case 'failed':
      return { headline: 'Fetch failed', lines, tone: 'error' };
    case 'partial':
      return {
        headline: `${newPosts(report.posts_inserted)}, ${plural(report.sources_failed, 'source')} failed`,
        lines,
        tone: 'warning',
      };
    default:
      return { headline: newPosts(report.posts_inserted), lines, tone: 'completion' };
  }
}
