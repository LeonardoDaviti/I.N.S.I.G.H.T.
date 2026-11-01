/**
 * Background work (issue 0062): what INSIGHT does on its own, worded for the Ingestion overview.
 * Stories (the story job after each fetch run), the search index (re-indexed after an update
 * that changes how posts are indexed) and links (read once for the posts stored before stories).
 * Checkable, not controllable: these are lines, never buttons. Pure; `now` is injected.
 */
import type { BackgroundProgress, BackgroundWorkResponse, StoriesRunSummary } from '../services/api';
import { formatRelativeTime } from './dates.ts';
import { formatElapsed } from './duration.ts';
import { formatCount, plural } from './format.ts';

export type BackgroundStatus = 'running' | 'ok' | 'scheduled';

export interface BackgroundLine {
  key: 'stories' | 'search' | 'links';
  label: string;
  status: BackgroundStatus;
  /** The state in a few words, beside the glyph. */
  word: string;
  /** Quiet lines under it. */
  details: string[];
}

/** "5,018 posts grouped · 86 stories · 90 News stories, last 30 days · 175 Classics": the counts the run recorded.
 *  News's count is every News story of the posts it grouped, not this week's that News lists (issue 0072). */
export function storiesRunCounts(run: StoriesRunSummary): string {
  const parts: string[] = [];
  if (typeof run.posts === 'number') parts.push(`${plural(run.posts, 'post')} grouped`);
  if (typeof run.stories === 'number') parts.push(plural(run.stories, 'story', 'stories'));
  if (typeof run.news === 'number') parts.push(`${plural(run.news, 'News story', 'News stories')}, ${run.full ? 'all time' : 'last 30 days'}`);
  if (typeof run.classics === 'number') parts.push(plural(run.classics, 'Classic'));
  return parts.join(' · ');
}

/** "Last run 12m ago, took 5s". */
function lastRun(run: StoriesRunSummary, now: Date): string {
  const took = formatElapsed(run.seconds ?? null);
  return `Last run ${formatRelativeTime(run.computed_at, now)}${took ? `, took ${took}` : ''}`;
}

function storiesLine(stories: BackgroundWorkResponse['stories'], now: Date): BackgroundLine {
  const run = stories.last_run;
  const base = { key: 'stories' as const, label: 'Stories' };
  if (stories.running) {
    return { ...base, status: 'running', word: 'building stories, News and Classics now', details: run ? [lastRun(run, now)] : [] };
  }
  if (!run) return { ...base, status: 'scheduled', word: 'not run yet', details: ['Runs after the next fetch run'] };
  const counts = storiesRunCounts(run);
  return {
    ...base, status: 'ok', word: 'done',
    details: [`${lastRun(run, now)} · next run: after the next fetch run`, ...(counts ? [counts] : [])],
  };
}

function progressLine(
  key: 'search' | 'links',
  label: string,
  progress: BackgroundProgress,
  words: { done: string; doing: string },
): BackgroundLine {
  const total = Math.max(0, progress.total);
  const pending = Math.min(total, Math.max(0, progress.pending));
  if (pending === 0) return { key, label, status: 'ok', word: words.done, details: [] };
  return { key, label, status: 'running', word: `${words.doing} ${formatCount(total - pending)} of ${formatCount(total)}`, details: [] };
}

/** The block's three lines, in order: stories, search index, links. */
export function backgroundWorkLines(work: BackgroundWorkResponse, now: Date): BackgroundLine[] {
  return [
    storiesLine(work.stories, now),
    progressLine('search', 'Search index', work.search, { done: 'up to date', doing: 're-indexing' }),
    progressLine('links', 'Links', work.links, { done: 'all read', doing: 'reading' }),
  ];
}

/** Something runs now: the block refreshes often while it does. */
export function backgroundWorkBusy(work: BackgroundWorkResponse | undefined): boolean {
  if (!work) return false;
  return work.stories.running || work.search.pending > 0 || work.links.pending > 0;
}
