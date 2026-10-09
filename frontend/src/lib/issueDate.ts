/**
 * Dates for the briefing "issues" (Mark IX briefings restyle). A briefing is read
 * like a newsletter issue, so its header names the day in words ("Monday,
 * 29 September 2026") and lists show a short muted date column ("Sep 29").
 *
 * The API sends two kinds of value: calendar dates ("2026-09-29", a briefing's
 * end_date) and instants ("2026-09-29T14:03:00Z", a post). A calendar date has no
 * time zone, so it is formatted in UTC: `new Date('2026-09-29')` is UTC midnight,
 * which is 28 September anywhere west of Greenwich. Instants use local time.
 *
 * Pure; the locale is fixed to `en` (as in lib/format.ts) so labels and tests agree.
 */

type DateValue = string | number | Date | null | undefined;

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

interface Parsed {
  date: Date;
  /** A calendar date without a time: format it in UTC. */
  dateOnly: boolean;
}

export function parseIssueDate(value: DateValue): Parsed | null {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : { date: value, dateOnly: false };
  const dateOnly = typeof value === 'string' && DATE_ONLY.test(value.trim());
  const date = new Date(typeof value === 'string' ? value.trim() : value);
  return Number.isNaN(date.getTime()) ? null : { date, dateOnly };
}

function yearOf(parsed: Parsed): number {
  return parsed.dateOnly ? parsed.date.getUTCFullYear() : parsed.date.getFullYear();
}

function format(parsed: Parsed, options: Intl.DateTimeFormatOptions, timeZone?: string): string {
  return new Intl.DateTimeFormat('en', { ...options, timeZone: parsed.dateOnly ? 'UTC' : timeZone }).format(parsed.date);
}

/**
 * The date column: "Sep 29"; a different year than `now` adds it ("Nov 25, 2023")
 * so an old item never passes for this year's. Unknown dates are "—", never "Invalid Date".
 */
export function formatIssueShort(value: DateValue, now: Date = new Date(), timeZone?: string): string {
  const parsed = parseIssueDate(value);
  if (!parsed) return '—';
  const sameYear = yearOf(parsed) === now.getFullYear();
  return format(parsed, sameYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' }, timeZone);
}

/** The issue header: "Monday, 29 September 2026". */
export function formatIssueLong(value: DateValue, timeZone?: string): string {
  const parsed = parseIssueDate(value);
  if (!parsed) return '—';
  const weekday = format(parsed, { weekday: 'long' }, timeZone);
  const day = format(parsed, { day: 'numeric' }, timeZone);
  const month = format(parsed, { month: 'long' }, timeZone);
  return `${weekday}, ${day} ${month} ${yearOf(parsed)}`;
}

/**
 * A covered window: "Aug 30 – Sep 29, 2026", "Dec 28, 2025 – Jan 3, 2026", or one
 * date when both ends agree. A missing end falls back to the known one.
 */
export function formatIssueRange(start: DateValue, end: DateValue): string {
  const a = parseIssueDate(start);
  const b = parseIssueDate(end);
  if (!a && !b) return '—';
  if (!a || !b) return formatWithYear((a || b) as Parsed);
  if (formatWithYear(a) === formatWithYear(b)) return formatWithYear(a);
  if (yearOf(a) === yearOf(b)) {
    return `${format(a, { month: 'short', day: 'numeric' })} – ${formatWithYear(b)}`;
  }
  return `${formatWithYear(a)} – ${formatWithYear(b)}`;
}

function formatWithYear(parsed: Parsed): string {
  return format(parsed, { month: 'short', day: 'numeric', year: 'numeric' });
}
