/**
 * Local-date helpers (Mark IX §F.6): the one place that turns an instant into a
 * calendar date or a relative time. `toISOString().split('T')[0]` gives the *UTC*
 * date, which is yesterday or tomorrow for part of every day outside UTC, so new
 * code uses `localDateISO` instead.
 *
 * `offsetMinutes` follows `Date#getTimezoneOffset` (UTC+2 is -120) and defaults to
 * the runtime's offset for that instant; tests inject it.
 */

type DateInput = Date | string | number | null | undefined;

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The calendar date (YYYY-MM-DD) of `date` in local time. */
export function localDateISO(date: Date = new Date(), offsetMinutes: number = date.getTimezoneOffset()): string {
  const shifted = new Date(date.getTime() - offsetMinutes * 60_000);
  return shifted.toISOString().slice(0, 10);
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "just now", "5m ago", "3h ago", "2d ago", "in 3h"; beyond 30 days, the local date. */
export function formatRelativeTime(
  value: DateInput,
  now: Date = new Date(),
  offsetMinutes?: number,
): string {
  const date = toDate(value);
  if (!date) return '—';
  const diff = now.getTime() - date.getTime();
  const abs = Math.abs(diff);
  if (abs < MINUTE) return 'just now';
  if (abs >= 30 * DAY) {
    return localDateISO(date, offsetMinutes ?? date.getTimezoneOffset());
  }
  let label: string;
  if (abs < HOUR) label = `${Math.floor(abs / MINUTE)}m`;
  else if (abs < DAY) label = `${Math.floor(abs / HOUR)}h`;
  else label = `${Math.floor(abs / DAY)}d`;
  return diff >= 0 ? `${label} ago` : `in ${label}`;
}
