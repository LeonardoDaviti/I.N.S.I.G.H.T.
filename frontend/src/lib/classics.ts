import type { BackgroundClassic, Classic } from '../services/api';
import { bareAddress } from './addresses.ts';
import { sourceLabel } from './sourceLabel.ts';
import type { ScopeRole } from './news.ts';

/** A classic on a source's page (issue 0077): the source's part, optional until the API sends it (0077 K). */
export type ScopedClassic = Classic & { scope_role?: ScopeRole | null };

/** A source's part in a classic (issue 0105): its own page, or a page it cites; a source cites a classic,
 *  it doesn't cover it (News's words are "Covered"). */
const CLASSIC_ROLE_WORDS: Partial<Record<ScopeRole, string>> = { origin: 'Started it', report: 'Cited it' };

/** "Started it", "Cited it"; null when the API sends none, or one this reader doesn't know. */
export function classicRoleWords(row: { scope_role?: string | null }): string | null {
  const role = row.scope_role;
  return (role && Object.hasOwn(CLASSIC_ROLE_WORDS, role) && CLASSIC_ROLE_WORDS[role as ScopeRole]) || null;
}

// Classics (issue 0051): kept apart from lib/story.ts, which the feed row (the reader's initial
// JS) imports; these are only read by the Classics view and the post page.

/** The citers a classic's card names before "+N". */
const CITERS_SHOWN = 3;

/** Who cited a classic and when: "Simon Willison, Aug 2025 · Gwern, Mar 2026 · +2". On a source's page the API
 *  sends its own voices first, a Reddit author with its subreddit: "u/a in r/x, Feb 2026" (issue 0105). */
export function citedBy(classic: Pick<Classic, 'citers'>): string {
  const month = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric' });
  const shown = classic.citers.slice(0, CITERS_SHOWN).map((c) => (
    `${c.place ? `${c.name} in ${sourceLabel(c.place)}` : sourceLabel(c.name)}, ${month.format(new Date(c.at))}`));
  const more = classic.citers.length - CITERS_SHOWN;
  return [...shown, ...(more > 0 ? [`+${more}`] : [])].join(' · ');
}

/** A classic's name: its title, else its address without the scheme. */
export function classicTitle(classic: Pick<Classic | BackgroundClassic, 'title' | 'url'>): string {
  return classic.title?.trim() || bareAddress(classic.url);
}
