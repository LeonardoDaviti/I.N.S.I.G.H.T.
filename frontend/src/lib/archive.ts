/**
 * The source sheet's archive section in words and numbers: what "available" means
 * for the source's kind, where the archive continues from, and the plan's estimate.
 * Honest by construction: a figure the source did not report is never shown as one.
 * Pure.
 */
import type { ArchivePlan, ArchiveRateLimit, AvailableBasis } from '../services/api';
import { formatCount, plural } from './format.ts';

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
    return { figure: '—', note: 'Plan to ask the source how many posts it has.' };
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

const planDates = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

/**
 * The plan in one line: what is stored, where the archive starts, and how much is older.
 * "You have 120 posts, back to 3 Mar 2025. The archive continues from there: about 2,180
 * older posts · ~18 min"; "… · size unknown" when the source reports no size.
 */
export function describePlan(plan: ArchivePlan, estimate: string | null): string {
  const stored = plan.current_stored_posts ?? 0;
  const oldest = plan.oldest_published_at ? planDates.format(new Date(plan.oldest_published_at)) : null;
  const have = stored ? `You have ${plural(stored, 'post')}${oldest ? `, back to ${oldest}` : ''}.` : 'Nothing is stored yet.';
  const collected = plan.checkpoint?.collected_posts;
  const start = plan.resume
    ? `The archive resumes from its checkpoint${collected ? ` (${plural(collected, 'post')} collected so far)` : ''}`
    : plan.continues_from ? 'The archive continues from there' : 'The archive starts at the newest post';
  if (plan.older_posts === null || plan.older_posts === undefined) return `${have} ${start} · size unknown`;
  if (plan.older_posts === 0) return `${have} Nothing older to fetch.`;
  const size = `about ${formatCount(plan.older_posts)} ${stored ? 'older ' : ''}post${plan.older_posts === 1 ? '' : 's'}`;
  return `${have} ${start}: ${size}${estimate ? ` · ${estimate}` : ''}`;
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
