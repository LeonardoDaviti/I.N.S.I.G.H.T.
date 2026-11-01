import type { BackgroundClassic, Classic } from '../services/api';
import { bareAddress } from './addresses.ts';
import { sourceLabel } from './sourceLabel.ts';

// Classics (issue 0051): kept apart from lib/story.ts, which the feed row (the reader's initial
// JS) imports; these are only read by the Classics view and the post page.

/** The citers a classic's card names before "+N". */
const CITERS_SHOWN = 3;

/** Who cited a classic and when: "Simon Willison, Aug 2025 · Gwern, Mar 2026 · +2". */
export function citedBy(classic: Pick<Classic, 'citers'>): string {
  const month = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric' });
  const shown = classic.citers.slice(0, CITERS_SHOWN).map((c) => `${sourceLabel(c.name)}, ${month.format(new Date(c.at))}`);
  const more = classic.citers.length - CITERS_SHOWN;
  return [...shown, ...(more > 0 ? [`+${more}`] : [])].join(' · ');
}

/** A classic's name: its title, else its address without the scheme. */
export function classicTitle(classic: Pick<Classic | BackgroundClassic, 'title' | 'url'>): string {
  return classic.title?.trim() || bareAddress(classic.url);
}
