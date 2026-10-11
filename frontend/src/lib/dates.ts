/**
 * Dates and times, the one place that turns an instant into words: a calendar
 * date, a relative time, the reader's date column and day headers, a local
 * timestamp. Durations live in `duration.ts`.
 *
 * Local dates (Mark IX §F.6): `toISOString().split('T')[0]` gives the *UTC*
 * date, which is yesterday or tomorrow for part of every day outside UTC, so new
 * code uses `localDateISO` instead.
 *
 * `offsetMinutes` follows `Date#getTimezoneOffset` (UTC+2 is -120) and defaults to
 * the runtime's offset for that instant; tests inject it.
 */

import { formatSpan } from './duration.ts';

type DateInput = Date | string | number | null | undefined;

/** A valid Date, or null for a missing or unparseable value. */
export function toDate(value: DateInput): Date | null {
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
const DAY = 24 * 60 * MINUTE;

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
  const label = formatSpan(abs);
  return diff >= 0 ? `${label} ago` : `in ${label}`;
}

/** A compact age for a narrow numeric column: "now", "45m", "3h", "2d", "5w", "4mo", "2y"; "—" for none. */
export function compactAge(iso: string | null | undefined, now: Date): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return '—';
  const minutes = Math.max(0, (now.getTime() - t) / 60_000);
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${Math.floor(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.floor(hours)}h`;
  const days = hours / 24;
  if (days < 14) return `${Math.floor(days)}d`;
  if (days < 60) return `${Math.floor(days / 7)}w`;
  if (days < 365) return `${Math.floor(days / 30)}mo`;
  return `${Math.floor(days / 365)}y`;
}

/** The runtime's default local date and time (`toLocaleString()`); null when missing or invalid. */
export function formatLocalDateTime(value: DateInput): string | null {
  return toDate(value)?.toLocaleString() ?? null;
}

/*
 * The reader's date column and day headers (Mark IX lead review #2), in the
 * news.smol.ai style: a short calendar date ("Sep 29") on every row, a relative
 * time ("3h ago") only inside the last 24 hours, and one header per local day.
 * `now` and `timeZone` are injectable for tests; both default to the runtime's.
 */

// Building an Intl.DateTimeFormat costs far more than calling it, and every row
// of the feed asks for its date on each render: one formatter per time zone.
const formatters = new Map<string, Intl.DateTimeFormat>();
function formatter(timeZone?: string): Intl.DateTimeFormat {
  const key = timeZone ?? '';
  let fmt = formatters.get(key);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat('en-US', { timeZone, year: 'numeric', month: 'short', day: 'numeric', weekday: 'short' });
    formatters.set(key, fmt);
  }
  return fmt;
}

function parts(date: Date, timeZone?: string) {
  const fmt = formatter(timeZone);
  const out: Record<string, string> = {};
  for (const part of fmt.formatToParts(date)) out[part.type] = part.value;
  return { year: out.year, month: out.month, day: out.day, weekday: out.weekday };
}

/** "Sep 29" (or "Sep 29 ’25" in another year); "5h ago" within the last 24h. */
export function feedDateLabel(value: string | Date | null | undefined, now: Date = new Date(), timeZone?: string): string {
  const date = toDate(value);
  if (!date) return '—';
  const diff = now.getTime() - date.getTime();
  if (diff >= 0 && diff < DAY) return formatRelativeTime(date, now);
  const d = parts(date, timeZone);
  const n = parts(now, timeZone);
  // Another year stays short enough for the date column: "Sep 5 ’25".
  return d.year === n.year ? `${d.month} ${d.day}` : `${d.month} ${d.day} \u2019${d.year.slice(-2)}`;
}

/** A stable key for the local calendar day of `value` (e.g. "2026-Sep-29"). */
const DAY_KEY_CACHE_MAX = 2_000;
const dayKeys = new Map<string, string>();

export function feedDayKey(value: string | Date | null | undefined, timeZone?: string): string {
  const date = toDate(value);
  if (!date) return 'unknown';
  const cacheKey = `${date.getTime()}|${timeZone ?? ''}`;
  const cached = dayKeys.get(cacheKey);
  if (cached !== undefined) return cached;
  const d = parts(date, timeZone);
  const key = `${d.year}-${d.month}-${d.day}`;
  // A plain bounded cache: when full, drop the oldest entry (Map keeps insertion order).
  if (dayKeys.size >= DAY_KEY_CACHE_MAX) dayKeys.delete(dayKeys.keys().next().value as string);
  dayKeys.set(cacheKey, key);
  return key;
}

const clockFormatters = new Map<string, Intl.DateTimeFormat>();
/** "14:05": the row's time of day, for rows that already sit under a day header. */
export function feedTimeLabel(value: string | Date | null | undefined, timeZone?: string): string {
  const date = toDate(value);
  if (!date) return '';
  const key = timeZone ?? '';
  let fmt = clockFormatters.get(key);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    clockFormatters.set(key, fmt);
  }
  return fmt.format(date);
}

const fullFormatters = new Map<string, Intl.DateTimeFormat>();
/** The full local date and time ("Oct 9, 2026, 11:30 PM"): a row's tooltip, the post page's date. */
export function feedFullTime(value: string | Date | null | undefined, timeZone?: string): string {
  const date = toDate(value);
  if (!date) return '';
  const key = timeZone ?? '';
  let fmt = fullFormatters.get(key);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(undefined, { timeZone, dateStyle: 'medium', timeStyle: 'short' });
    fullFormatters.set(key, fmt);
  }
  return fmt.format(date);
}

/** "Today", "Yesterday", "Mon, Sep 29" or "Mon, Sep 29, 2025". */
export function feedDayHeading(value: string | Date | null | undefined, now: Date = new Date(), timeZone?: string): string {
  const date = toDate(value);
  if (!date) return 'Undated';
  const key = feedDayKey(date, timeZone);
  if (key === feedDayKey(now, timeZone)) return 'Today';
  if (key === feedDayKey(new Date(now.getTime() - DAY), timeZone)) return 'Yesterday';
  const d = parts(date, timeZone);
  const n = parts(now, timeZone);
  const base = `${d.weekday}, ${d.month} ${d.day}`;
  return d.year === n.year ? base : `${base}, ${d.year}`;
}
