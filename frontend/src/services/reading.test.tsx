import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SeenTracker, type SeenItem } from './reading';
import { ActiveClock, IDLE_MS, opensOriginal, readDepth } from '../lib/readingActivity';

// Your reading: rows seen (half on screen for a second, batched), active time and depth.

type Callback = (entries: Array<Partial<IntersectionObserverEntry>>) => void;
let fire: Callback = () => {};
class FakeObserver {
  constructor(callback: Callback) { fire = callback; }
  observe() {}
  unobserve() {}
  disconnect() {}
}

function at(target: Element, ratio: number) {
  fire([{ target, isIntersecting: ratio > 0, intersectionRatio: ratio }]);
}

describe('SeenTracker', () => {
  let sent: SeenItem[][];
  let send: (items: SeenItem[]) => Promise<unknown>;
  let beacon: (items: SeenItem[]) => boolean;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('IntersectionObserver', FakeObserver);
    sent = [];
    send = vi.fn(async (items: SeenItem[]) => { sent.push(items); });
    beacon = vi.fn(() => true);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('counts a row half on screen for a second, once a tab, surface and day', () => {
    const tracker = new SeenTracker(send, beacon);
    const row = document.createElement('article');
    tracker.watch(row, 'p1', 'feed');
    at(row, 0.6);
    vi.advanceTimersByTime(999);
    expect(tracker.pending()).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(tracker.pending()).toEqual([{ post: 'p1', surface: 'feed' }]);
    at(row, 0);
    at(row, 0.8);
    vi.advanceTimersByTime(2_000);
    expect(tracker.pending()).toHaveLength(1);
    // the same post on another surface is another row
    const inNews = document.createElement('article');
    tracker.watch(inNews, 'p1', 'news');
    at(inNews, 1);
    vi.advanceTimersByTime(1_000);
    expect(tracker.pending()).toEqual([{ post: 'p1', surface: 'feed' }, { post: 'p1', surface: 'news' }]);
  });

  it('does not count a row under half on screen, or scrolled past within the second, or gone', () => {
    const tracker = new SeenTracker(send, beacon);
    const [a, b, c] = ['a', 'b', 'c'].map(() => document.createElement('li'));
    tracker.watch(a, 'a', 'track');
    const unwatchB = tracker.watch(b, 'b', 'track');
    tracker.watch(c, 'c', 'track');
    at(a, 0.4);
    at(b, 0.9);
    at(c, 0.9);
    vi.advanceTimersByTime(500);
    at(c, 0.2);
    unwatchB();
    vi.advanceTimersByTime(1_000);
    expect(tracker.pending()).toEqual([]);
  });

  it('flushes every 15 seconds, keeps what failed for the next flush, and beacons on pagehide', async () => {
    const failing = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({});
    const tracker = new SeenTracker(failing, beacon);
    const row = document.createElement('article');
    tracker.watch(row, 'p1', 'news');
    at(row, 1);
    vi.advanceTimersByTime(1_000);
    await vi.advanceTimersByTimeAsync(14_000);
    expect(failing).toHaveBeenCalledTimes(1);
    expect(tracker.pending()).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(failing).toHaveBeenLastCalledWith([{ post: 'p1', surface: 'news' }]);
    expect(tracker.pending()).toEqual([]);

    const other = document.createElement('article');
    tracker.watch(other, 'p2', 'feed');
    at(other, 1);
    vi.advanceTimersByTime(1_000);
    window.dispatchEvent(new Event('pagehide'));
    expect(beacon).toHaveBeenCalledWith([{ post: 'p2', surface: 'feed' }]);
    expect(tracker.pending()).toEqual([]);
  });
});

describe('reading activity', () => {
  it('counts active time only while visible, focused and touched within the last minute', () => {
    const clock = new ActiveClock(0);
    for (let t = 1_000; t <= 10_000; t += 1_000) clock.tick(t, true, true);
    expect(clock.seconds()).toBe(10);
    clock.tick(11_000, false, true);   // hidden
    clock.tick(12_000, true, false);   // another window focused
    expect(clock.seconds()).toBe(10);
    for (let t = 13_000; t <= IDLE_MS + 30_000; t += 1_000) clock.tick(t, true, true);
    expect(clock.seconds()).toBe(10 + (IDLE_MS - 13_000) / 1_000 + 1);   // no input since 0: idle after a minute
    clock.input(IDLE_MS + 30_000);
    clock.tick(IDLE_MS + 31_000, true, true);
    expect(clock.seconds()).toBe(10 + (IDLE_MS - 13_000) / 1_000 + 2);
    clock.tick(IDLE_MS + 3_600_000, true, true);   // a suspended tab's gap counts one capped step at most
    expect(clock.seconds()).toBe(10 + (IDLE_MS - 13_000) / 1_000 + 2);
  });

  it('reads depth as how far down the body the viewport reaches', () => {
    expect(readDepth(100, 2_000, 900)).toBeCloseTo(0.4);
    expect(readDepth(-1_500, 2_000, 900)).toBe(1);
    expect(readDepth(1_000, 2_000, 900)).toBe(0);
    expect(readDepth(0, 0, 900)).toBeNull();
  });

  it('an original opens on a click or a middle click, not the context menu', () => {
    const opened = vi.fn();
    const handlers = opensOriginal(opened);
    handlers.onClick();
    handlers.onAuxClick({ button: 1 });
    handlers.onAuxClick({ button: 2 });
    expect(opened).toHaveBeenCalledTimes(2);
  });
});
