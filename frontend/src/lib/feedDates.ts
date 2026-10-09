/**
 * The reader's date column and day headers (Mark IX lead review #2), in the
 * news.smol.ai style: a short calendar date ("Sep 29") on every row, a relative
 * time ("3h ago") only inside the last 24 hours, and one header per local day.
 * `now` and `timeZone` are injectable for tests; both default to the runtime's.
 */
import { formatRelativeTime } from './dates.ts';

const DAY = 24 * 60 * 60_000;

function parse(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function parts(date: Date, timeZone?: string) {
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone, year: 'numeric', month: 'short', day: 'numeric', weekday: 'short' });
  const out: Record<string, string> = {};
  for (const part of fmt.formatToParts(date)) out[part.type] = part.value;
  return { year: out.year, month: out.month, day: out.day, weekday: out.weekday };
}

/** "Sep 29" (or "Sep 29 ’25" in another year); "5h ago" within the last 24h. */
export function feedDateLabel(value: string | Date | null | undefined, now: Date = new Date(), timeZone?: string): string {
  const date = parse(value);
  if (!date) return '—';
  const diff = now.getTime() - date.getTime();
  if (diff >= 0 && diff < DAY) return formatRelativeTime(date, now);
  const d = parts(date, timeZone);
  const n = parts(now, timeZone);
  // Another year stays short enough for the date column: "Sep 5 ’25".
  return d.year === n.year ? `${d.month} ${d.day}` : `${d.month} ${d.day} \u2019${d.year.slice(-2)}`;
}

/** A stable key for the local calendar day of `value` (e.g. "2026-Sep-29"). */
export function feedDayKey(value: string | Date | null | undefined, timeZone?: string): string {
  const date = parse(value);
  if (!date) return 'unknown';
  const d = parts(date, timeZone);
  return `${d.year}-${d.month}-${d.day}`;
}

/** "Today", "Yesterday", "Mon, Sep 29" or "Mon, Sep 29, 2025". */
export function feedDayHeading(value: string | Date | null | undefined, now: Date = new Date(), timeZone?: string): string {
  const date = parse(value);
  if (!date) return 'Undated';
  const key = feedDayKey(date, timeZone);
  if (key === feedDayKey(now, timeZone)) return 'Today';
  if (key === feedDayKey(new Date(now.getTime() - DAY), timeZone)) return 'Yesterday';
  const d = parts(date, timeZone);
  const n = parts(now, timeZone);
  const base = `${d.weekday}, ${d.month} ${d.day}`;
  return d.year === n.year ? base : `${base}, ${d.year}`;
}
