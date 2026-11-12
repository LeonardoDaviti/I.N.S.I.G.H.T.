// Its own module (issue 0109 B2): only Add source reads it, so the reader's first download doesn't.
import { withScheme } from './addresses.ts';

/** A platform INSIGHT follows by its own source kind. */
export type AccountPlatform = 'x' | 'telegram' | 'youtube' | 'reddit';

// Paths on X that are pages of the site, not accounts.
const X_PAGES = new Set(['i', 'home', 'search', 'explore', 'hashtag', 'intent', 'share', 'settings', 'messages',
  'notifications', 'login', 'signup', 'tos', 'privacy']);

/** The account an address names on a platform INSIGHT follows by a source kind (issue 0109 B2), with the
 * value its Add source template takes: x.com/<user>, t.me/<channel>, youtube.com/@<channel> (or
 * /channel/<id>, /c/, /user/), reddit.com/r/<sub>. Null for a site, a post or another page of the platform. */
export function platformAccount(address: string): { platform: AccountPlatform; value: string } | null {
  let url: URL;
  try {
    url = new URL(withScheme(address.trim()));
  } catch {
    return null;
  }
  const host = url.hostname.toLowerCase().replace(/^(www|m|mobile|old|np)\./, '');
  const parts = url.pathname.split('/').filter(Boolean);
  if (host === 'x.com' || host === 'twitter.com') {
    return parts.length === 1 && /^[A-Za-z0-9_]{1,15}$/.test(parts[0]) && !X_PAGES.has(parts[0].toLowerCase())
      ? { platform: 'x', value: parts[0] } : null;
  }
  if (host === 't.me' || host === 'telegram.me') {
    const channel = parts.length === 2 && parts[0] === 's' ? parts[1] : parts.length === 1 ? parts[0] : '';
    return /^[A-Za-z][A-Za-z0-9_]{3,}$/.test(channel) ? { platform: 'telegram', value: channel } : null;
  }
  if (host === 'youtube.com') {
    if (parts.length === 1 && /^@[\w.-]+$/.test(parts[0])) return { platform: 'youtube', value: parts[0] };
    return parts.length === 2 && ['channel', 'c', 'user'].includes(parts[0]) && /^[\w.-]+$/.test(parts[1])
      ? { platform: 'youtube', value: `${parts[0]}/${parts[1]}` } : null;
  }
  if (host === 'reddit.com') {
    return parts.length === 2 && parts[0] === 'r' && /^\w+$/.test(parts[1]) ? { platform: 'reddit', value: parts[1] } : null;
  }
  return null;
}

const PLATFORM_HOSTS = new Set(['x.com', 'twitter.com', 't.me', 'telegram.me', 'youtube.com', 'reddit.com']);

/** A page on a platform INSIGHT follows by account (x.com, t.me, youtube.com, reddit.com): followed by its account,
 *  never by its host. */
export function isPlatformHost(address: string): boolean {
  try {
    return PLATFORM_HOSTS.has(new URL(withScheme(address.trim())).hostname.toLowerCase().replace(/^(www|m|mobile|old|np)\./, ''));
  } catch {
    return false;
  }
}

/** The account a platform's page sits under (v10.15 c3), its address and its name: a tweet (x.com/<user>/status/<id>)
 *  is https://x.com/<user> "@user", a Telegram post (t.me/<channel>/<n>) its channel's, a page under
 *  youtube.com/@<channel>/… its channel's, a thread under reddit.com/r/<sub>/… "r/sub". Null when it names none. */
export function pageAccount(address: string): { url: string; label: string } | null {
  let url: URL;
  try {
    url = new URL(withScheme(address.trim()));
  } catch {
    return null;
  }
  const parts = url.pathname.split('/').filter(Boolean);
  for (const n of [1, 2]) {
    if (parts.length < n) break;
    const account = platformAccount(`https://${url.hostname}/${parts.slice(0, n).join('/')}`);
    if (!account) continue;
    const { platform, value } = account;
    if (platform === 'x') return { url: `https://x.com/${value}`, label: `@${value}` };
    if (platform === 'telegram') return { url: `https://t.me/${value}`, label: `@${value}` };
    if (platform === 'reddit') return { url: `https://www.reddit.com/r/${value}`, label: `r/${value}` };
    return { url: `https://www.youtube.com/${value}`, label: value.startsWith('@') ? value : value.split('/').pop() ?? value };
  }
  return null;
}
