/**
 * Small display helpers shared by the Mark IX surfaces (spec §F.7): counts go
 * through `Intl.NumberFormat`, plurals through `Intl.PluralRules`, and long
 * handles/URLs are middle-truncated (the start and the end carry the meaning).
 * Pure; the locale is fixed to `en` so labels and tests agree.
 */

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

/** Keep the start and the end: "https://news.example…/feed.xml". Counts code points, not UTF-16 units. */
export function middleTruncate(text: string, max: number): string {
  const chars = Array.from(text);
  if (chars.length <= max || max < 5) return text;
  const keep = max - 1;
  const head = Math.ceil(keep / 2);
  const tail = keep - head;
  return `${chars.slice(0, head).join('')}…${chars.slice(chars.length - tail).join('')}`;
}

const URLISH = /^(https?:\/\/|[\w-]+(\.[\w-]+)+\/)/i;

/**
 * A readable source name (lead review #3): never a raw feed URL. The first
 * candidate that is a real name wins; otherwise the first URL is reduced to
 * what a reader recognises.
 *   https://www.reddit.com/r/LocalLLaMA/.rss               -> r/LocalLLaMA
 *   https://rss.arxiv.org/rss/cs.CL                         -> arXiv cs.CL
 *   https://github.com/anthropics/claude-code/commits.atom  -> anthropics/claude-code
 *   https://tg.i-c-a.su/rss/seeallochnaya?limit=50          -> @seeallochnaya
 *   https://karpathy.bearblog.dev/feed/                     -> karpathy.bearblog.dev
 */
export function sourceLabel(...candidates: Array<string | null | undefined>): string {
  const values = candidates.map((value) => (value ?? '').trim()).filter(Boolean);
  const named = values.find((value) => !URLISH.test(value));
  if (named) return named;
  const raw = values[0];
  if (!raw) return 'Unknown source';
  let url: URL;
  try {
    url = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
  } catch {
    return raw;
  }
  const host = url.hostname.replace(/^www\./, '').toLowerCase();
  const parts = url.pathname.split('/').filter(Boolean);
  if (host.endsWith('reddit.com') && parts[0] === 'r' && parts[1]) return `r/${parts[1]}`;
  if (host.endsWith('arxiv.org')) {
    const category = url.searchParams.get('search_query')?.match(/cat:([\w.-]+)/)?.[1] ?? parts[parts.length - 1];
    return category && category !== 'query' ? `arXiv ${category}` : 'arXiv';
  }
  if (host === 'github.com' && parts.length >= 2) return `${parts[0]}/${parts[1]}`;
  // Telegram channels read through an RSS bridge (tg.i-c-a.su/rss/<channel>, rsshub …/telegram/channel/<channel>).
  if ((host === 'tg.i-c-a.su' || host.includes('rsshub')) && parts.length >= 2) return `@${parts[parts.length - 1]}`;
  if (host === 't.me' && parts[0]) return `@${parts[parts.length - 1]}`;
  if (host === 'medium.com' && parts.some((part) => part.startsWith('@'))) return parts.find((part) => part.startsWith('@'))!;
  if (host === 'feeds.feedburner.com' && parts[0]) return parts[0];
  return host;
}
