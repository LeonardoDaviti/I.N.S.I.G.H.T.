import { formatCount } from '../../lib/format';

/** Display helpers for the analysis pages (Stories, Inbox, Tracks). Pure; English locale like lib/format. */

/** "project_thread" -> "project thread". */
export function humanize(value: string | null | undefined, fallback = '—'): string {
  if (!value || !value.trim()) return fallback;
  return value.replace(/_/g, ' ').trim();
}

const SHORT_DATE = new Intl.DateTimeFormat('en', { month: 'short', day: '2-digit' });
const SHORT_DATE_YEAR = new Intl.DateTimeFormat('en', { month: 'short', day: '2-digit', year: 'numeric' });
const DATE_TIME = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' });

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The smol-style date column: "Sep 09"; adds the year when it is not this year; "—" when missing. */
export function shortDate(value: string | null | undefined, now: Date = new Date()): string {
  const date = toDate(value);
  if (!date) return '—';
  return date.getFullYear() === now.getFullYear() ? SHORT_DATE.format(date) : SHORT_DATE_YEAR.format(date);
}

/** "Oct 9, 2026, 14:20" in local time; "—" when missing or invalid. */
export function dateTime(value: string | null | undefined): string {
  const date = toDate(value);
  return date ? DATE_TIME.format(date) : '—';
}

/** 0.82 -> "82%", 82 -> "82%"; null -> "—". */
export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const numeric = Number(value);
  return `${formatCount(Math.round(numeric > 1 ? numeric : numeric * 100))}%`;
}
