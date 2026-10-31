/**
 * Discover's reasons for where your stories start (issue 0065), worded for its cards. Only Sources →
 * discover reads them, so they stay out of the reader's chunks. Pure; `now` is injected.
 */
import type { MissingOrigins, SuggestedSource } from '../services/api';
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
