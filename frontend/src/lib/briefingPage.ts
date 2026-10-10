import { sourceLabel } from './sourceLabel.ts';
/**
 * Pure helpers for the briefings page (pages/DailyBriefing.tsx), kept out of the
 * component file so React fast refresh keeps working and node --test can run them.
 */

export type BriefingTab = 'daily' | 'topics' | 'weekly';

/** Which tab a deep link (?mode=…) opens on. */
export function tabForMode(mode: string | null): BriefingTab {
  if (mode === 'topics' || mode === 'db-topics') return 'topics';
  if (mode === 'weekly' || mode === 'weekly-topics') return 'weekly';
  return 'daily';
}

/** With no fetch for this long the corpus is stale and the page says so loudly. */
export const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

export function isStale(latestFetchAt: string | null | undefined, now: number = Date.now()): boolean {
  if (!latestFetchAt) return false;
  const at = new Date(latestFetchAt).getTime();
  return Number.isFinite(at) && now - at > STALE_AFTER_MS;
}

/**
 * The briefing pages' source name: the shared `sourceLabel` (one name per source
 * on every page), but empty instead of "Unknown source" so callers can fall back.
 */
export function readableSourceName(...candidates: Array<string | null | undefined>): string {
  if (!candidates.some((value) => (value ?? '').trim())) return '';
  return sourceLabel(...candidates);
}
