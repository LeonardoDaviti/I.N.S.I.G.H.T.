/**
 * Discover's reasons for where your stories start (issue 0065), worded for its cards. Only Sources →
 * discover reads them, so they stay out of the reader's chunks. Pure; `now` is injected.
 */
import type { FollowLabel, MissingOrigins, SuggestedSource } from '../services/api';
import { feedDateLabel } from './dates.ts';
import { formatCount } from './format.ts';

/** "Started 7 of your stories"; on a site you follow, "You follow anthropic.com/research; /news started 14 of your stories". */
export function originReason(s: SuggestedSource): string {
  const started = `${formatCount(s.origins ?? 0)} of your stories`;
  if (!s.follows?.length) return `Started ${started}`;
  const place = s.key.includes('/') ? s.key.slice(s.key.indexOf('/')) : s.key;
  return `You follow ${s.follows.join(', ')}; ${place} started ${started}`;
}

/** "37 of your stories started at openai.com/index pages it doesn't hold, 36 from before its first post (Oct 23)". */
export function missingReason(a: MissingOrigins, now: Date = new Date()): string {
  const older = a.older && a.since
    ? `, ${a.older === a.origins ? 'all' : formatCount(a.older)} from before its first post (${feedDateLabel(a.since, now)})`
    : '';
  return `${formatCount(a.origins)} of your stories started at ${a.places.join(', ')} pages it doesn't hold${older}`;
}

/** A missing row's archive, as stored (issue 0080): "Archive running · 3 of 37 found so far"; finished,
 *  "Archive finished · 34 of these pages aren't in its archive"; null before any archive. */
export function archiveLine(a: MissingOrigins): string | null {
  const { state, found = 0 } = a.archive ?? {};
  if (state === 'running' || state === 'paused') {
    return `Archive ${state} · ${formatCount(found)} of ${formatCount(a.origins)} found so far`;
  }
  if (state === 'finished') {
    const left = Math.max(0, a.origins - found);
    return left ? `Archive finished · ${formatCount(left)} of these pages aren't in its archive` : 'Archive finished';
  }
  return null;
}

/** The follow test's labels (issue 0080), and those that can't be followed: they sit below the rest. */
export const FOLLOW_LABELS: Record<FollowLabel, string> = {
  feed: 'Feed found', page: 'Page watching', headlines: 'Headlines only', blocked: 'Blocks readers',
};
export const UNFOLLOWABLE: ReadonlySet<FollowLabel> = new Set<FollowLabel>(['headlines', 'blocked']);

const NUMBERISH = /^\d[\d_.-]*$/;
const LANGUAGE = /^[a-z]{2}(?:[-_](?:[a-z]{2}|[a-z]{4}|\d{3}))?$/i;

/** An article line with no title (issue 0080): "a post by @account" for a tweet, else its site and section
 *  ("example.com · blog"), the site alone at its root; never its address. */
export function untitledLine(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }
  const tweet = /^\/([A-Za-z0-9_]+)\/status\/\d{15,}/.exec(parsed.pathname);
  if (tweet) return `a post by @${tweet[1]}`;
  const site = parsed.hostname.replace(/^www\./, '');
  const segments = parsed.pathname.split('/').filter(Boolean);
  const path = segments.length >= 3 && LANGUAGE.test(segments[0]) && !NUMBERISH.test(segments[1]) ? segments.slice(1) : segments;
  const section = path.length >= 2 && !NUMBERISH.test(path[0]) ? decodeURIComponent(path[0]) : '';
  return section ? `${site} · ${section}` : site;
}
