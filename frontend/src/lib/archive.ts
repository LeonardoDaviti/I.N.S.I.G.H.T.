/**
 * The source sheet's archive section in words and numbers: what "available" means
 * for the source's kind, how many posts can be asked for, and the plan's estimate.
 * Honest by construction: a figure the source did not report is never shown as one.
 * Pure.
 */
import type { ArchiveRateLimit, AvailableBasis } from '../services/api';
import { formatCount, plural } from './format.ts';

/** The most one archive run may ask for when the source reports no total. */
export const MAX_ARCHIVE_POSTS = 10_000;

const PRESETS = [100, 500];

/** The available figure and, when the number needs it, what it means. */
export function describeAvailable({ available, basis, stored }: {
  available: number | null | undefined;
  basis: AvailableBasis;
  stored: number;
}): { figure: string; note: string | null } {
  if (basis === 'unknown') {
    return {
      figure: stored > 0 ? `at least ${formatCount(stored)}` : 'not reported',
      note: 'This source does not report a total; the archive pages back until it runs out.',
    };
  }
  if (available === null || available === undefined) {
    return { figure: 'not checked yet', note: 'Plan to ask the source how many posts it has.' };
  }
  const count = formatCount(available);
  switch (basis) {
    case 'upper_bound':
      return { figure: `up to ${count}`, note: 'Counted from the newest post number; deleted posts make the real number lower.' };
    case 'estimate':
      return { figure: `about ${count}`, note: 'The source’s own counter, which is approximate.' };
    case 'listing_cap':
      return { figure: `${count} reachable`, note: 'The source holds more, but its listings stop here.' };
    case 'feed_window':
      return { figure: `${count} in the feed`, note: 'RSS only exposes what the feed lists now; nothing older is reachable.' };
    default:
      return { figure: count, note: null };
  }
}

/** The most posts worth asking for: the known available count, else null (no ceiling). */
export function archiveCeiling(available: number | null | undefined, basis: AvailableBasis): number | null {
  if (basis === 'unknown' || available === null || available === undefined || available < 0) return null;
  return available;
}

/** 100 / 500 below the ceiling, then "All N"; without a ceiling, 100 / 500 / 1,000. */
export function archivePresets(ceiling: number | null): Array<{ label: string; value: number }> {
  if (ceiling === null) return [...PRESETS, 1000].map((value) => ({ label: formatCount(value), value }));
  return [
    ...PRESETS.filter((value) => value < ceiling).map((value) => ({ label: formatCount(value), value })),
    { label: `All ${formatCount(ceiling)}`, value: ceiling },
  ];
}

/** A whole number in [1, ceiling] (or [1, MAX_ARCHIVE_POSTS] without one). */
export function clampDesired(value: number, ceiling: number | null): number {
  const max = Math.max(1, ceiling ?? MAX_ARCHIVE_POSTS);
  if (!Number.isFinite(value)) return 1;
  return Math.min(max, Math.max(1, Math.floor(value)));
}

/** The count the field starts at: 500 or everything, whichever is less; 100 without a ceiling. */
export function defaultDesired(ceiling: number | null): number {
  if (ceiling === null) return 100;
  return clampDesired(Math.min(ceiling, 500), ceiling);
}

/** "5s between pages, 30s every 10 pages"; null when the plan carried no rate limit. */
export function describeRate(rate: ArchiveRateLimit | null | undefined): string | null {
  if (!rate) return null;
  const delay = rate.page_delay_seconds ?? 0;
  const parts = [delay > 0 ? `${delay}s between pages` : 'no pause between pages'];
  if (rate.batch_size && rate.batch_cooldown_seconds) {
    parts.push(`${rate.batch_cooldown_seconds}s every ${rate.batch_size} pages`);
  }
  return parts.join(', ');
}

/** "500 posts fetched, 475 new, 25 updated · 25 pages · 500 stored"; null when nothing was recorded. */
export function archiveResultLine(result: {
  posts_fetched?: number;
  posts_inserted?: number;
  posts_updated?: number;
  pages_fetched?: number;
  stored_posts?: number;
}): string | null {
  const counts = [
    typeof result.posts_fetched === 'number' ? `${plural(result.posts_fetched, 'post')} fetched` : null,
    typeof result.posts_inserted === 'number' ? `${formatCount(result.posts_inserted)} new` : null,
    result.posts_updated ? `${formatCount(result.posts_updated)} updated` : null,
  ].filter(Boolean).join(', ');
  const parts = [
    counts || null,
    typeof result.pages_fetched === 'number' ? plural(result.pages_fetched, 'page') : null,
    typeof result.stored_posts === 'number' ? `${formatCount(result.stored_posts)} stored` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}
