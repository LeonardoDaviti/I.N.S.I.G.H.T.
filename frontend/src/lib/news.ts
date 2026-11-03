import type { FeedStory, NewsScore } from '../services/api';
import { plural } from './format.ts';
import { coveredNames } from './story.ts';

// News (issue 0051): kept apart from lib/story.ts, which the feed row (the reader's initial JS)
// imports; only the News view reads these.

/** What a News story's score is made of, in words: "4 sources (1 share) · in 1 roundup". The number is the
 *  story's voices, as on the feed row and the post page; a share is a source (issue 0069). */
export function newsWords(news: Pick<NewsScore, 'shares' | 'mentions'>, voices: number): string {
  return [
    `${plural(voices, 'source')}${news.shares ? ` (${plural(news.shares, 'share')})` : ''}`,
    news.mentions ? `in ${plural(news.mentions, 'roundup')}` : null,
  ].filter(Boolean).join(' · ');
}

/** A source's part in a story (issue 0077), sent on a source's page as `news.scope_role` / `classic.scope_role`.
 *  Typed here, optional, until the API sends it (0077 K). */
export type ScopeRole = 'origin' | 'report' | 'share' | 'mention';
export type ScopedNews = NewsScore & { scope_role?: ScopeRole | null };
const ROLE_WORDS: Record<ScopeRole, string> = { origin: 'Started it', report: 'Covered', share: 'Shared', mention: 'Mentioned' };

/** "Started it", "Covered", "Shared", "Mentioned"; null when the API sends none, or one this reader doesn't know. */
export function scopeRoleWords(row: { scope_role?: string | null }): string | null {
  const role = row.scope_role;
  return role && Object.hasOwn(ROLE_WORDS, role) ? ROLE_WORDS[role as ScopeRole] : null;
}

/** A News row's line: on a source's page its part first, then its score in words, then who covered it,
 *  the first reporter first. */
export function newsLine(news: ScopedNews, story: FeedStory): string {
  return [scopeRoleWords(news), newsWords(news, story.voices), coveredNames(story)].filter(Boolean).join(' · ');
}

const WEEK = 7 * 24 * 60 * 60 * 1000;
const dayMonth = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' });
const dayMonthYear = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

/** The Monday a date's week begins on, at local midnight. */
function weekStart(date: Date): Date {
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  return start;
}

/**
 * A News story's part (issue 0077), by when it began (`first_at`): "Last 48 hours" (the API's
 * `part === 'recent'`), "This week" (since Monday), then "Week of 12 Oct" for each earlier week.
 * `rank` orders the parts, newest first.
 */
export function newsPart(news: Pick<NewsScore, 'part' | 'first_at'>, now: Date = new Date()): { label: string; rank: number } {
  if (news.part === 'recent') return { label: 'Last 48 hours', rank: 0 };
  const thisWeek = weekStart(now);
  const began = new Date(news.first_at);
  if (Number.isNaN(began.getTime()) || began >= thisWeek) return { label: 'This week', rank: 1 };
  const start = weekStart(began);
  const format = start.getFullYear() === now.getFullYear() ? dayMonth : dayMonthYear;
  // Rounded: a week across a clock change is an hour short or long.
  return { label: `Week of ${format.format(start)}`, rank: 1 + Math.round((thisWeek.getTime() - start.getTime()) / WEEK) };
}

/** News rows in their parts, the newest part first, each part in the API's order (by score). */
export function inNewsParts<T extends { news?: Pick<NewsScore, 'part' | 'first_at'> | null }>(items: T[], now: Date = new Date()): T[] {
  const rank = (item: T) => (item.news ? newsPart(item.news, now).rank : 0);
  // Array sort is stable: within a part the API's order stays.
  return [...items].sort((a, b) => rank(a) - rank(b));
}
