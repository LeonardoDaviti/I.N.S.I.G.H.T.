/**
 * Pure helpers for the briefings page (pages/DailyBriefing.tsx), kept out of the
 * component file so React fast refresh keeps working and node --test can run them.
 */

export type BriefingTab = 'daily' | 'topics' | 'weekly';

/** Which tab a deep link (?mode=…) opens on. */
export function tabForMode(mode: string | null): BriefingTab {
  if (mode === 'topics' || mode === 'db-topics') return 'topics';
  if (mode === 'weekly' || mode === 'weekly-topics') return 'weekly';
  return 'daily';
}

/** With no fetch for this long the corpus is stale and the page says so loudly. */
export const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

export function isStale(latestFetchAt: string | null | undefined, now: number = Date.now()): boolean {
  if (!latestFetchAt) return false;
  const at = new Date(latestFetchAt).getTime();
  return Number.isFinite(at) && now - at > STALE_AFTER_MS;
}

/**
 * A readable source name (lead review #3): never a raw feed URL. A real display
 * name wins; a URL is reduced to what a reader recognises.
 *   https://www.reddit.com/r/EvenRealities/.rss        -> r/EvenRealities
 *   https://rss.arxiv.org/rss/cs.CL                     -> arXiv cs.CL
 *   https://github.com/anthropics/claude-code/commits.atom -> anthropics/claude-code
 *   https://www.uploadvr.com/rss/                       -> uploadvr.com
 * TODO(Mark IX): fold into the shared sourceLabel() helper once it lands.
 */
export function readableSourceName(...candidates: Array<string | null | undefined>): string {
  const values = candidates.map((value) => (value || '').trim()).filter(Boolean);
  const named = values.find((value) => !/^https?:\/\//i.test(value) && !/^[\w.-]+\.[a-z]{2,}\//i.test(value));
  if (named) return named;
  const raw = values[0];
  if (!raw) return '';
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
    const category = parts[parts.length - 1];
    return category ? `arXiv ${category}` : 'arXiv';
  }
  if (host === 'github.com' && parts.length >= 2) return `${parts[0]}/${parts[1]}`;
  return host;
}
