/**
 * Source schedule presentation (Mark IX §F.3): due times, backoff, cadence tiers,
 * intervals and the health-table order. Pure; `now` is injected.
 *
 * `sortHealthRows` mirrors `operations_service._health_sort_key` exactly, so the
 * table reads in the same order the API returns and the next run decides.
 */
import type { CadenceTier, HealthStatus, IntervalBasis, SourceHealthRow } from '../services/api';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export const HEALTH_STATUS_ORDER: readonly HealthStatus[] = ['error', 'backoff', 'unavailable', 'due', 'deferred', 'disabled'];

export const HEALTH_STATUS_LABELS: Record<HealthStatus, string> = {
  error: 'Failing',
  backoff: 'Backoff',
  unavailable: 'Unavailable',
  due: 'Due',
  deferred: 'Scheduled',
  disabled: 'Disabled',
};

export const INTERVAL_BASIS_LABELS: Record<IntervalBasis, string> = {
  override: 'override',
  tier: 'tier',
  probation: 'probation',
  backlog_guard: 'backlog guard',
  profile_floor: 'kind floor',
};

/** Override bounds accepted by PUT /api/sources/{id}/cadence (90 days max). */
export const OVERRIDE_MIN_HOURS = 1;
export const OVERRIDE_MAX_HOURS = 2160;

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** A positive duration as "25m", "3h", "5d" (floored, so "in 3h" never overstates). */
function span(ms: number): string {
  if (ms < HOUR) return `${Math.max(1, Math.floor(ms / MINUTE))}m`;
  if (ms < DAY) return `${Math.floor(ms / HOUR)}h`;
  return `${Math.floor(ms / DAY)}d`;
}

/** "in 3h", "in 5d", "overdue 2h", "due now" (within a minute), or "—" when unknown. */
export function formatDue(nextDueAt: string | null | undefined, now: Date = new Date()): string {
  const due = parseDate(nextDueAt);
  if (!due) return '—';
  const diff = due.getTime() - now.getTime();
  if (Math.abs(diff) < MINUTE) return 'due now';
  return diff > 0 ? `in ${span(diff)}` : `overdue ${span(-diff)}`;
}

/** The backoff cell: "retry in 3h", "dormant · retry in 5d", "retry due", or null when not failing. */
export function backoffLabel(row: SourceHealthRow, now: Date = new Date()): string | null {
  if (!row.consecutive_failures) return null;
  const retry = parseDate(row.next_retry_at);
  const base = retry && retry.getTime() - now.getTime() >= MINUTE
    ? `retry in ${span(retry.getTime() - now.getTime())}`
    : 'retry due';
  return row.dormant ? `dormant · ${base}` : base;
}

const TIER_LABELS: Record<CadenceTier, string> = {
  fast: 'Fast',
  medium: 'Medium',
  slow: 'Slow',
  unknown: 'Probation',
};

const TIER_HINTS: Record<CadenceTier, string> = {
  fast: 'Posts more often than every 12 hours',
  medium: 'Posts every 12 hours to 7 days',
  slow: 'Posts less often than weekly',
  unknown: 'Fewer than 3 dated posts: checked daily until its cadence is known',
};

export function tierLabel(tier: CadenceTier): string {
  return TIER_LABELS[tier] ?? tier;
}

export function tierHint(tier: CadenceTier): string {
  return TIER_HINTS[tier] ?? '';
}

function trim(value: number): string {
  return String(Number(value.toFixed(1)));
}

/** Hours as "30m", "6h", "1.5h", "2d", "1.5d"; "—" when unknown. */
export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || !Number.isFinite(hours) || hours < 0) return '—';
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${trim(hours)}h`;
  return `${trim(hours / 24)}d`;
}

export function intervalLabel(row: Pick<SourceHealthRow, 'interval_hours' | 'interval_basis'>): string {
  return `every ${formatHours(row.interval_hours)} · ${INTERVAL_BASIS_LABELS[row.interval_basis] ?? row.interval_basis}`;
}

function statusRank(status: string): number {
  const index = HEALTH_STATUS_ORDER.indexOf(status as HealthStatus);
  return index === -1 ? HEALTH_STATUS_ORDER.length : index;
}

function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Worst first: status order, most failures, soonest due (none last), name. Returns a new array. */
export function sortHealthRows(rows: readonly SourceHealthRow[]): SourceHealthRow[] {
  return [...rows].sort((a, b) =>
    statusRank(a.status) - statusRank(b.status)
    || b.consecutive_failures - a.consecutive_failures
    // ISO-8601 strings from one backend clock sort chronologically; "~" sorts after digits.
    || compareText(a.next_due_at || '~', b.next_due_at || '~')
    || compareText(String(a.display_name).toLowerCase(), String(b.display_name).toLowerCase()));
}

export type HealthFilter = HealthStatus;

/** `?status=` filter. `error` means failing (error or backoff), the same sources the
 *  "N source errors" chip counts; every other value is one status. Unknown -> all. */
export function filterHealthRows(rows: readonly SourceHealthRow[], status: string | null | undefined): SourceHealthRow[] {
  if (!status || !HEALTH_STATUS_ORDER.includes(status as HealthStatus)) return [...rows];
  if (status === 'error') return rows.filter((row) => row.status === 'error' || row.status === 'backoff');
  return rows.filter((row) => row.status === status);
}

export type OverrideParse = { ok: true; value: number | null } | { ok: false; error: string };

/** The override field: empty clears it (back to the tier), otherwise hours in [1, 2160]. */
export function parseOverrideHours(input: string): OverrideParse {
  const text = input.trim();
  if (!text) return { ok: true, value: null };
  if (!/^\d+(\.\d+)?$/.test(text)) {
    return { ok: false, error: 'Enter a number of hours, or leave it empty to use the cadence tier.' };
  }
  const value = Number(text);
  if (!Number.isFinite(value) || value < OVERRIDE_MIN_HOURS || value > OVERRIDE_MAX_HOURS) {
    return { ok: false, error: `Enter between ${OVERRIDE_MIN_HOURS} and ${OVERRIDE_MAX_HOURS} hours (90 days).` };
  }
  return { ok: true, value };
}
