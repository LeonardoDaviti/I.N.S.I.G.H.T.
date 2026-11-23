/** Small display helpers: counts via `Intl.NumberFormat`, plurals, middle truncation. Pure; locale fixed to `en`. */

const LOCALE = 'en';
const numberFormat = new Intl.NumberFormat(LOCALE);
const pluralRules = new Intl.PluralRules(LOCALE);

/** 12847 -> "12,847"; null/NaN -> "—". */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return numberFormat.format(value);
}

/** plural(1, 'source') -> "1 source"; plural(12847, 'post') -> "12,847 posts". */
export function plural(count: number, singular: string, pluralForm: string = `${singular}s`): string {
  const word = pluralRules.select(count) === 'one' ? singular : pluralForm;
  return `${formatCount(count)} ${word}`;
}

/** "1,675 points · 1,628 comments": a Hacker News item's counts. */
export function countsLabel(counts: { points: number; comments: number }): string {
  return `${plural(counts.points, 'point')} · ${plural(counts.comments, 'comment')}`;
}

/** Keep the start and the end: "https://news.example…/feed.xml". Counts code points, not UTF-16 units. */
export function middleTruncate(text: string, max: number): string {
  const chars = Array.from(text);
  if (chars.length <= max || max < 5) return text;
  const keep = max - 1;
  const head = Math.ceil(keep / 2);
  const tail = keep - head;
  return `${chars.slice(0, head).join('')}…${chars.slice(chars.length - tail).join('')}`;
}

// Source names: lib/sourceLabel.ts is the one helper (every page names a source the same way).
