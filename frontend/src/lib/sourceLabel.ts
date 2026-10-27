/**
 * One readable name for a source, everywhere a source is named (Mark IX lead
 * review #3): never a raw feed URL. A real display name wins; a URL-shaped name
 * (with or without its scheme) becomes a derived one:
 *
 *   https://github.com/anthropics/claude-code/commits.atom   -> anthropics/claude-code
 *   https://github.com/anthropics/skills/releases.atom       -> anthropics/skills releases
 *   https://rss.arxiv.org/rss/cs.CL                          -> arXiv cs.CL
 *   http://export.arxiv.org/api/query?search_query=cat:cs.AI -> arXiv cs.AI
 *   https://www.reddit.com/r/LocalLLaMA/.rss                 -> r/LocalLLaMA
 *   https://tg.i-c-a.su/rss/denissexy?limit=50               -> @denissexy
 *   https://nitter.local/karpathy/rss                        -> @karpathy
 *   https://simonwillison.net/atom/everything/               -> simonwillison.net
 *   r/x, "Road to VR"                                        -> unchanged
 */
const URLISH = /^(https?:\/\/)?(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(:\d+)?(\/\S*)?$/i;

function looksLikeUrl(value: string): boolean {
  if (/^https?:\/\//i.test(value)) return true;
  // "simonwillison.net/atom/everything", but not "r/x", "cs.CL" or "Tom's Guide - AR":
  // a dotted host followed by a path.
  return !/\s/.test(value) && URLISH.test(value) && /^(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(:\d+)?\//i.test(value);
}

function deriveFromUrl(raw: string): string {
  let url: URL;
  try {
    url = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
  } catch {
    return raw.replace(/^https?:\/\/(www\.)?/i, '').replace(/\/+$/, '');
  }
  const host = url.hostname.replace(/^www\./i, '').toLowerCase();
  const parts = url.pathname.split('/').filter(Boolean);

  if (host === 'github.com' && parts.length >= 2) {
    const repo = `${parts[0]}/${parts[1]}`;
    const kind = (parts[2] || '').replace(/\.atom$/i, '').toLowerCase();
    return kind === 'releases' || kind === 'tags' ? `${repo} ${kind}` : repo;
  }
  if (host.endsWith('arxiv.org')) {
    const query = url.searchParams.get('search_query') || '';
    const fromQuery = query.match(/cat:([\w.-]+)/i)?.[1];
    const fromPath = parts[0] === 'rss' && parts[1] ? parts[1] : null;
    const category = fromQuery || fromPath;
    return category ? `arXiv ${category}` : 'arXiv';
  }
  if (host.endsWith('reddit.com') && parts[0] === 'r' && parts[1]) return `r/${parts[1]}`;
  // Telegram RSS bridges (the Telegram RSS template's telegram.local too): <host>/rss/<channel>.
  if ((host === 'tg.i-c-a.su' || host === 'telegram.local') && parts[0] === 'rss' && parts[1]) return `@${parts[1]}`;
  // Nitter, any instance (the Nitter template's nitter.local): <host>/<account>/rss.
  if (host.includes('nitter') && parts.length === 2 && parts[1] === 'rss') return `@${parts[0]}`;
  // RSSHub's Telegram bridge: rsshub.app/telegram/channel/<channel>.
  if (host.includes('rsshub') && parts[0] === 'telegram' && parts.length >= 3) return `@${parts[parts.length - 1]}`;
  if (host === 't.me' && parts[0]) return `@${parts[parts.length - 1]}`;
  if (host === 'medium.com' && parts.some((part) => part.startsWith('@'))) return parts.find((part) => part.startsWith('@'))!;
  if (host === 'feeds.feedburner.com' && parts[0]) return parts[0];
  if (host.endsWith('youtube.com')) return 'YouTube channel';
  return host || raw;
}

export function sourceLabel(...candidates: Array<string | null | undefined>): string {
  const values = candidates.map((value) => (value ?? '').trim()).filter(Boolean);
  if (!values.length) return 'Unknown source';
  const named = values.find((value) => !looksLikeUrl(value));
  if (named) return named;
  return deriveFromUrl(values[0]);
}

/**
 * A post's source name on the post page: a YouTube post names its channel (the
 * stored source is the channel id); everything else goes through `sourceLabel`.
 */
export function postSourceName(post: {
  source?: string | null;
  source_display_name?: string | null;
  platform?: string | null;
  metadata?: Record<string, unknown> | null;
}): string {
  const channel = post.platform === 'youtube' && typeof post.metadata?.channel_title === 'string' ? post.metadata.channel_title : null;
  return sourceLabel(channel, post.source_display_name, post.source);
}

const PLATFORM_LABELS: Record<string, string> = {
  reddit: 'Reddit',
  rss: 'RSS',
  telegram: 'Telegram',
  youtube: 'YouTube',
};

/** "RSS", "YouTube"; an unknown platform capitalised; "Source" when there is none. */
export function getPlatformLabel(platform?: string | null): string {
  const key = (platform || '').trim().toLowerCase();
  return PLATFORM_LABELS[key] || (key ? key.charAt(0).toUpperCase() + key.slice(1) : 'Source');
}
