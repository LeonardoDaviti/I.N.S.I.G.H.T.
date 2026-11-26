// Your reading: what the reader opened, for how long and how far, and the rows they saw and did not open. The post
// page records opens, reading sessions (active seconds, depth) and originals opened through createApi; this module
// holds the rows seen (POST /api/reading/seen, batched) and the summary (GET /api/reading/summary). Nothing leaves
// the INSIGHT server.
import { apiUrl, request } from '../lib/request';

export type SeenSurface = 'news' | 'track' | 'feed';
export type ReadingDays = 7 | 30 | 'all';

export interface ReadingPost {
  day: string;               // YYYY-MM-DD, UTC
  post_id: string;
  at: string;                // the day's first open
  title: string | null;
  source_id: string;
  source: string;
  active_seconds: number | null;   // null: recorded before active time was measured
  open_seconds: number | null;
  depth: number | null;
  source_opened: boolean;
  tracks: Array<{ id: string; name: string }>;
}
export interface ReadingTotal { id: string; name: string | null; posts: number; active_seconds: number; originals_opened: number }
export interface ReadingSeen { id: string; name: string | null; seen: number; opened: number }
export interface ReadingSummary {
  days: number | null;
  since: string | null;
  posts: ReadingPost[];
  posts_total: number;
  by_source: ReadingTotal[];
  by_track: ReadingTotal[];
  by_story: ReadingTotal[];
  seen_by_source: ReadingSeen[];
  seen_by_track: ReadingSeen[];
}

export const readingApi = {
  summary: (days: ReadingDays) => request<ReadingSummary>(`/api/reading/summary?days=${days}`),
  seen: (items: SeenItem[]) => request<{ written: number }>('/api/reading/seen', { method: 'POST', body: { items } }),
};

// ---- seen: a row at least half on screen for a second ----

export interface SeenItem { post: string; surface: SeenSurface }

export const SEEN_RATIO = 0.5;
export const SEEN_MS = 1_000;
export const FLUSH_MS = 15_000;
const BATCH = 500;   // the API's most items a request

interface Watched { post: string; surface: SeenSurface; timer: ReturnType<typeof setTimeout> | null }

/**
 * One IntersectionObserver for every watched row. A row counts once a tab, surface and (UTC) day; the counts wait in
 * a queue sent every FLUSH_MS and, by sendBeacon, when the page is hidden or left.
 */
export class SeenTracker {
  private observer: IntersectionObserver | null = null;
  private watched = new Map<Element, Watched>();
  private counted = new Set<string>();
  private queue: SeenItem[] = [];
  private interval: ReturnType<typeof setInterval> | null = null;

  constructor(private send: (items: SeenItem[]) => Promise<unknown> = readingApi.seen,
              private beacon: (items: SeenItem[]) => boolean = sendSeenBeacon) {}

  watch(node: Element, post: string, surface: SeenSurface): () => void {
    if (typeof IntersectionObserver === 'undefined') return () => {};
    if (!this.observer) {
      this.observer = new IntersectionObserver((entries) => this.onEntries(entries), { threshold: [0, SEEN_RATIO] });
      this.start();
    }
    this.watched.set(node, { post, surface, timer: null });
    this.observer.observe(node);
    return () => this.unwatch(node);
  }

  /** What waits to be sent (tests). */
  pending(): readonly SeenItem[] {
    return this.queue;
  }

  async flush(): Promise<void> {
    if (!this.queue.length) return;
    const items = this.queue.splice(0, BATCH);
    try {
      await this.send(items);
    } catch {
      this.queue.unshift(...items);   // sent again with the next flush
    }
  }

  /** The page is going away: what waits goes by sendBeacon (kept for the next flush when it is refused). */
  flushBeacon(): void {
    while (this.queue.length) {
      const items = this.queue.slice(0, BATCH);
      if (!this.beacon(items)) return;
      this.queue.splice(0, items.length);
    }
  }

  private onEntries(entries: IntersectionObserverEntry[]): void {
    for (const entry of entries) {
      const w = this.watched.get(entry.target);
      if (!w) continue;
      if (entry.isIntersecting && entry.intersectionRatio >= SEEN_RATIO) {
        if (w.timer === null && !this.counted.has(this.key(w))) {
          w.timer = setTimeout(() => {
            w.timer = null;
            if (this.watched.get(entry.target) === w && !document.hidden) this.count(w);
          }, SEEN_MS);
        }
      } else if (w.timer !== null) {
        clearTimeout(w.timer);
        w.timer = null;
      }
    }
  }

  private key(w: Watched): string {
    return `${new Date().toISOString().slice(0, 10)}|${w.surface}|${w.post}`;
  }

  private count(w: Watched): void {
    const key = this.key(w);
    if (this.counted.has(key)) return;
    this.counted.add(key);
    this.queue.push({ post: w.post, surface: w.surface });
  }

  private unwatch(node: Element): void {
    const w = this.watched.get(node);
    if (w?.timer) clearTimeout(w.timer);
    this.watched.delete(node);
    this.observer?.unobserve(node);
  }

  private start(): void {
    if (this.interval !== null || typeof window === 'undefined') return;
    this.interval = setInterval(() => void this.flush(), FLUSH_MS);
    window.addEventListener('pagehide', () => this.flushBeacon());
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.flushBeacon();
    });
  }
}

function sendSeenBeacon(items: SeenItem[]): boolean {
  if (typeof navigator === 'undefined' || typeof navigator.sendBeacon !== 'function') return false;
  const body = new Blob([JSON.stringify({ items })], { type: 'application/json' });
  return navigator.sendBeacon(apiUrl('/api/reading/seen'), body);
}

export const seenTracker = new SeenTracker();
