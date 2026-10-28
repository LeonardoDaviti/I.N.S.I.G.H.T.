/**
 * A watched page's changes and its own state, in words (issue 0039): "Updated Nov 3: +2
 * sections, +1,400 words", and what a page says of itself (when it last changed, its status
 * and confidence) for the post's header. Only the latest text is kept, never a version.
 */

import type { PageUpdate } from '../services/api';
import { feedDateLabel, toDate } from './dates.ts';
import { plural } from './format.ts';

const DAY = 24 * 60 * 60_000;
/** A post first seen this long after its date was new to you: the row says when it was published. */
export const LATE_FIND_MS = 2 * DAY;

/** "+2 sections, +1,400 words"; "−300 words" when the page mostly lost text. */
export function updateChanges(update: PageUpdate): string {
  const words = update.words_added >= update.words_removed
    ? `+${plural(update.words_added, 'word')}`
    : `−${plural(update.words_removed, 'word')}`;
  return [
    update.sections_added ? `+${plural(update.sections_added, 'section')}` : null,
    update.sections_removed ? `−${plural(update.sections_removed, 'section')}` : null,
    update.words_added || update.words_removed ? words : null,
  ].filter(Boolean).join(', ');
}

/** "Updated Nov 3: +2 sections, +1,400 words" ("Updated 5h ago: …" inside a day). */
export function updateLine(update: PageUpdate, now: Date = new Date()): string {
  const changes = updateChanges(update);
  return `Updated ${feedDateLabel(update.at, now)}${changes ? `: ${changes}` : ''}`;
}

/** A row that sorts well after its published date (new to you, issue 0039) and did not change. */
export function lateFind(item: { sort_at: string; published_at: string | null; update?: PageUpdate | null }): boolean {
  const sorted = toDate(item.sort_at);
  const published = toDate(item.published_at);
  return !item.update && Boolean(sorted && published && sorted.getTime() - published.getTime() > LATE_FIND_MS);
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

/**
 * What the page states about itself, from the post's metadata: `modified` when it says it
 * changed (shown only when that is another day than `published`), and its `status` and
 * `confidence` where the site writes them.
 */
export function pageState(metadata: Record<string, unknown> | null | undefined, published: string | null | undefined) {
  const modified = toDate(text(metadata?.modified));
  const day = (date: Date) => date.toISOString().slice(0, 10);
  const publishedAt = toDate(published);
  const update = metadata?.page_update && typeof metadata.page_update === 'object'
    ? metadata.page_update as PageUpdate
    : null;
  return {
    modified: modified && (!publishedAt || day(modified) !== day(publishedAt)) ? modified.toISOString() : null,
    notes: [text(metadata?.status), text(metadata?.confidence)].filter((note): note is string => Boolean(note)),
    update,
  };
}
