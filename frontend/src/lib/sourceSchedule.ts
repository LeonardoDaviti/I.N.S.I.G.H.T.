/**
 * Source schedule presentation (Mark IX §F.3): due times, backoff, how often a source is fetched,
 * intervals and the status order. Pure; `now` is injected.
 */
import type { HealthStatus, SourceHealthRow } from '../services/api';
import { toDate } from './dates.ts';
import { formatHours, formatSpan } from './duration.ts';

const MINUTE = 60_000;

export const HEALTH_STATUS_ORDER: readonly HealthStatus[] = ['error', 'backoff', 'unavailable', 'due', 'deferred', 'disabled'];

export const HEALTH_STATUS_LABELS: Record<HealthStatus, string> = {
  error: 'Failing',
  backoff: 'Backoff',
  unavailable: 'Unavailable',
  due: 'Due',
  deferred: 'Scheduled',
  disabled: 'Disabled',
};

/** Override bounds accepted by PUT /api/sources/{id}/cadence (90 days max). */
export const OVERRIDE_MIN_HOURS = 1;
export const OVERRIDE_MAX_HOURS = 2160;

/** "in 3h", "in 5d", "overdue 2h", "due now" (within a minute), or "—" when unknown. */
export function formatDue(nextDueAt: string | null | undefined, now: Date = new Date()): string {
  const due = toDate(nextDueAt);
  if (!due) return '—';
  const diff = due.getTime() - now.getTime();
  if (Math.abs(diff) < MINUTE) return 'due now';
  return diff > 0 ? `in ${formatSpan(diff)}` : `overdue ${formatSpan(-diff)}`;
}

/** The backoff cell: "retry in 3h", "dormant · retry in 5d", "retry due", or null when not failing. */
export function backoffLabel(row: SourceHealthRow, now: Date = new Date()): string | null {
  if (!row.consecutive_failures) return null;
  const retry = toDate(row.next_retry_at);
  const base = retry && retry.getTime() - now.getTime() >= MINUTE
    ? `retry in ${formatSpan(retry.getTime() - now.getTime())}`
    : 'retry due';
  return row.dormant ? `dormant · ${base}` : base;
}

/** Why a source waits as long as it does, in plain words (no tier, guard or floor). */
function cadenceReason(row: Pick<SourceHealthRow, 'interval_basis' | 'mean_gap_hours'>): string {
  switch (row.interval_basis) {
    case 'override': return 'your own setting';
    case 'probation': return 'new source, until it has 3 dated posts';
    case 'backlog_guard': return 'often enough to catch every post its feed lists';
    case 'profile_floor': return 'the least wait for its kind';
    default: return row.mean_gap_hours !== null && row.mean_gap_hours !== undefined
      ? `it posts about every ${formatHours(row.mean_gap_hours)}`
      : 'from how often it posts';
  }
}

/** "Fetched every 1d (new source, until it has 3 dated posts)". */
export function cadenceLine(row: Pick<SourceHealthRow, 'interval_hours' | 'interval_basis' | 'mean_gap_hours'>): string {
  return `Fetched every ${formatHours(row.interval_hours)} (${cadenceReason(row)})`;
}

/** A status's place in HEALTH_STATUS_ORDER (worst first); unknown statuses come last. */
export function statusRank(status: string): number {
  const index = HEALTH_STATUS_ORDER.indexOf(status as HealthStatus);
  return index === -1 ? HEALTH_STATUS_ORDER.length : index;
}


/** Worst first: status order, most failures, soonest due (none last), name. Returns a new array. */

/** Did the source's last attempt fail? `last_outcome` decides; without it, an error
 *  newer than the last success (or with no success at all) counts. */
export function lastAttemptFailed(row: Pick<SourceHealthRow, 'last_outcome' | 'last_error' | 'last_error_at' | 'last_success_at'>): boolean {
  if (row.last_outcome) return row.last_outcome === 'error';
  if (!row.last_error) return false;
  const failed = toDate(row.last_error_at);
  const succeeded = toDate(row.last_success_at);
  return !failed || !succeeded || failed.getTime() >= succeeded.getTime();
}

/**
 * The status a row shows, derived from its last attempt. A source whose last fetch
 * failed is failing (or backing off while a retry is scheduled) even when the
 * backend's schedule calls it due or scheduled; due/scheduled are for healthy
 * sources only. Disabled, unavailable, error and backoff pass through.
 */
export function effectiveHealthStatus(row: SourceHealthRow, now: Date = new Date()): HealthStatus {
  if (row.status !== 'due' && row.status !== 'deferred') return row.status;
  if (!lastAttemptFailed(row)) return row.status;
  const retry = toDate(row.next_retry_at);
  return retry && retry.getTime() - now.getTime() >= MINUTE ? 'backoff' : 'error';
}

/** Rows with `status` replaced by `effectiveHealthStatus`; unchanged rows keep identity. */
export function withEffectiveStatus(rows: readonly SourceHealthRow[], now: Date = new Date()): SourceHealthRow[] {
  return rows.map((row) => {
    const status = effectiveHealthStatus(row, now);
    return status === row.status ? row : { ...row, status };
  });
}

/** `?status=` filter. `error` means failing (error or backoff), the same sources the
 *  "N source errors" chip counts; every other value is one status. Unknown -> all. */
export function filterHealthRows(rows: readonly SourceHealthRow[], status: string | null | undefined): SourceHealthRow[] {
  if (!status || !HEALTH_STATUS_ORDER.includes(status as HealthStatus)) return [...rows];
  if (status === 'error') return rows.filter((row) => row.status === 'error' || row.status === 'backoff');
  return rows.filter((row) => row.status === status);
}

export type OverrideParse = { ok: true; value: number | null } | { ok: false; error: string };

/** The "Set your own" field: empty clears it (back to automatic), otherwise hours in [1, 2160]. */
export function parseOverrideHours(input: string): OverrideParse {
  const text = input.trim();
  if (!text) return { ok: true, value: null };
  if (!/^\d+(\.\d+)?$/.test(text)) {
    return { ok: false, error: 'Enter a number of hours, or leave it empty to fetch it automatically.' };
  }
  const value = Number(text);
  if (!Number.isFinite(value) || value < OVERRIDE_MIN_HOURS || value > OVERRIDE_MAX_HOURS) {
    return { ok: false, error: `Enter between ${OVERRIDE_MIN_HOURS} and ${OVERRIDE_MAX_HOURS} hours (90 days).` };
  }
  return { ok: true, value };
}
