// 0132 B: how the source analysis page writes each signal's number. No overall score anywhere.
import type { MarkxSourceCell, MarkxSourceRow } from '../../../services/api';

export const COLUMN_TITLES: Record<string, string> = {
  role: 'Role',
  per_week: 'Posts a week',
  first_to_report: 'First to report',
  news_yield: 'News yield',
  cited_by: 'Cited by',
  solo_share: 'Solo share',
};

export const ROLE_LABELS: Record<string, string> = {
  platform: 'platform (many voices)',
  curator: 'curator',
  official: 'official',
  staff_or_beat: 'staff or beat',
  reposter: 'reposter',
  commentator: 'commentator',
  reporter: 'reporter',
  independent: 'independent author',
  too_few: 'too few to tell',
};

export const SHARES = new Set(['own_share', 'root_share', 'first_to_report', 'solo_share', 'news_yield', 'media_only']);

export function pct(value: unknown): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—';
}

export function num(value: unknown, digits = 1): string {
  if (typeof value !== 'number') return '—';
  return Number.isInteger(value) ? value.toLocaleString('en') : value.toFixed(digits);
}

/** "report 60% · commentary 40%" for a {name: share} object. */
export function mix(value: unknown, percent = true): string {
  if (!value || typeof value !== 'object') return '—';
  const parts = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => typeof v === 'number')
    .sort((a, b) => (b[1] as number) - (a[1] as number))
    .map(([k, v]) => `${k.replace(/_/g, ' ')} ${percent ? pct(v) : num(v)}`);
  return parts.length ? parts.join(' · ') : '—';
}

/** A signal's number as one short text. */
export function valueText(signal: string, value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (signal === 'role') return ROLE_LABELS[String(value)] ?? String(value);
  if (SHARES.has(signal)) return pct(value);
  if (signal === 'per_week') return num(value);
  if (signal === 'perspectives') return mix(value, false);
  if (signal === 'kinds' || signal === 'languages') return mix(value);
  if (signal === 'age') return typeof value === 'string' ? value.slice(0, 10) : '—';
  if (signal === 'audience') return `${num(value)} views`;
  if (signal === 'followers') return num(value);
  if (signal === 'reputation' && typeof value === 'object') {
    const v = value as Record<string, unknown>;
    return `cited by ${num(v.cited_by)} · ${num(v.classics)} Classics · first ${pct(v.first_to_report)}`;
  }
  if (signal === 'stance') return `${num(value)} grounded pattern${value === 1 ? '' : 's'}`;
  return typeof value === 'number' ? num(value) : String(value);
}

/** A list cell: its number, or "too few" (the list never hides that it counted too few). */
export function cellText(signal: string, cell: MarkxSourceCell | undefined): string {
  if (!cell) return '—';
  if (signal === 'role') return valueText('role', cell.value);
  if (cell.too_few) return 'too few';
  return valueText(signal, cell.value);
}

/** The value a column sorts by: null for too few or none, so those always sort last. */
export function sortValue(signal: string, cell: MarkxSourceCell | undefined): number | string | null {
  if (!cell || cell.value === null || cell.value === undefined) return null;
  if (signal === 'role') return cell.value === 'too_few' ? null : String(cell.value);
  if (cell.too_few) return null;
  return typeof cell.value === 'number' ? cell.value : null;
}

export type Sort = { by: string; desc: boolean };

/** Sorted by `sort`; too few to tell (or no number) always last, then by name. */
export function sortRows(rows: MarkxSourceRow[], sort: Sort): MarkxSourceRow[] {
  const name = (r: MarkxSourceRow) => (r.name || '').toLowerCase();
  return [...rows].sort((a, b) => {
    if (sort.by !== 'name') {
      const x = sortValue(sort.by, a.stats[sort.by]);
      const y = sortValue(sort.by, b.stats[sort.by]);
      if (x === null && y !== null) return 1;
      if (y === null && x !== null) return -1;
      if (x !== null && y !== null && x !== y) {
        const order = x < y ? -1 : 1;
        return sort.desc ? -order : order;
      }
    } else if (name(a) !== name(b)) {
      return (name(a) < name(b) ? -1 : 1) * (sort.desc ? -1 : 1);
    }
    return name(a) < name(b) ? -1 : name(a) > name(b) ? 1 : 0;
  });
}

export function sourceHref(id: string): string {
  return `/markx/sources/${encodeURIComponent(id)}`;
}
