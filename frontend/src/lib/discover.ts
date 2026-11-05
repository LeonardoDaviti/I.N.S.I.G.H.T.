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

/** "37 pages at openai.com/index where your stories started aren't in it, 36 from before its first post (Oct 23)": the pages
 *  it still lacks (issue 0109: pages, not stories; a page it has stored since has left the row). */
export function missingReason(a: MissingOrigins, now: Date = new Date()): string {
  const older = a.older && a.since
    ? `, ${a.older === a.origins ? 'all' : formatCount(a.older)} from before its first post (${feedDateLabel(a.since, now)})`
    : '';
  const pages = a.origins === 1 ? 'page' : 'pages';
  return `${formatCount(a.origins)} ${pages} at ${a.places.join(', ')} where your stories started ${a.origins === 1 ? "isn't" : "aren't"} in it${older}`;
}

/** A missing row's archive, as stored (issue 0080): "Archive running · 3 found so far, 37 to go"; finished,
 *  "Archive finished · 37 of these pages aren't in its archive"; null before any archive. */
export function archiveLine(a: MissingOrigins): string | null {
  const { state, found = 0 } = a.archive ?? {};
  if (state === 'running' || state === 'paused') {
    return `Archive ${state} · ${formatCount(a.stored ?? found)} found so far, ${formatCount(a.origins)} to go`;
  }
  if (state === 'finished') {
    return `Archive finished · ${formatCount(a.origins)} of these pages aren't in its archive`;
  }
  return null;
}

/** What else a row says (issue 0109): the pages stored since, a feed that stopped, a section its source doesn't watch. */
export function rowNotes(a: MissingOrigins, now: Date = new Date()): string[] {
  const notes: string[] = [];
  const running = a.archive?.state === 'running' || a.archive?.state === 'paused';
  if (a.stored && !running) notes.push(`${formatCount(a.stored)} now stored; their stories join at the next story run`);
  if (a.stopped) notes.push(`Its feed stopped (${feedDateLabel(a.stopped, now)}): an archive can't reach these pages`);
  if (a.watches) notes.push(`It watches ${a.watches.prefix}, not ${a.watches.not.join(', ')}`);
  return notes;
}

/** Whether Archive… is offered: an archive can reach some of the pages, and none ran or runs. */
export function canArchive(a: MissingOrigins): boolean {
  const state = a.archive?.state;
  return (a.archivable ?? a.origins) > 0 && state !== 'running' && state !== 'finished';
}

/** The follow test's labels (issue 0080), and those that can't be followed: a section of their own (issue 0109). */
export const FOLLOW_LABELS: Record<FollowLabel, string> = {
  feed: 'Feed found', page: 'Page watching', headlines: 'Headlines only', blocked: 'Blocks readers',
  other_feed: 'A feed, but not of these pages',
};
export const UNFOLLOWABLE: ReadonlySet<FollowLabel> = new Set<FollowLabel>(['headlines', 'blocked', 'other_feed']);

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
