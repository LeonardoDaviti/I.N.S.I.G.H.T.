/**
 * Setting a frame up before anything renders in it (Design Studio D4):
 * - its own `fetch` becomes the fixture transport for the scenario;
 * - its `localStorage` and `sessionStorage` become in-memory stores, so the
 *   frame's theme (seeded from `?theme=`), reader choices and dev flags never leak
 *   into the studio or other frames, which share the origin;
 * - a report collects the unmocked requests and the faked writes for the bar.
 * Only the frame's window is touched: the studio's `fetch` stays the real one.
 */
import { THEME_STORAGE_KEY } from '../../components/ThemeProvider';
import { frameScenario, type FrameScenario } from '../fixtures/scenarios';
import type { FrameLocation } from './frameUrl';
import { APP_API_BASE, createFixtureTransport, type TransportEvent } from './transport';

export interface FrameReport {
  events(): readonly TransportEvent[];
  subscribe(listener: () => void): () => void;
  add(event: TransportEvent): void;
  /** Requests answered with `pending()`, which never settle: a ready frame does not wait for them. */
  stalled(): number;
  stall(): void;
}

export function createFrameReport(): FrameReport {
  let events: readonly TransportEvent[] = [];
  let stalled = 0;
  const listeners = new Set<() => void>();
  return {
    events: () => events,
    stalled: () => stalled,
    stall: () => { stalled += 1; },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    add(event) {
      events = [...events, event];
      for (const listener of listeners) listener();
    },
  };
}

/** A `Storage` held in memory. */
export function memoryStorage(seed: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(seed));
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, String(value)); },
  };
}

export interface BootedFrame {
  location: FrameLocation;
  /** Null when the URL names a page or state with no scenario. */
  scenario: FrameScenario | null;
  report: FrameReport;
  /** Puts the window's own fetch and storage back (tests). */
  restore(): void;
}

export function bootFrame(
  win: Window,
  location: FrameLocation,
  { now = new Date(), scenario = frameScenario(location.page, location.state) ?? null }: { now?: Date; scenario?: FrameScenario | null } = {},
): BootedFrame {
  const report = createFrameReport();
  const realFetch = win.fetch.bind(win);
  const saved = {
    fetch: win.fetch,
    localStorage: Object.getOwnPropertyDescriptor(win, 'localStorage'),
    sessionStorage: Object.getOwnPropertyDescriptor(win, 'sessionStorage'),
  };

  win.fetch = createFixtureTransport({
    routes: scenario && location.data === 'fixtures' ? scenario.routes(now) : [],
    data: location.data,
    realFetch,
    onEvent: report.add,
    onStall: report.stall,
    origin: win.location.origin,
    apiBase: APP_API_BASE,
  });
  const theme = location.theme === 'light' ? 'theme-light' : 'theme-dark';
  Object.defineProperty(win, 'localStorage', { configurable: true, value: memoryStorage({ [THEME_STORAGE_KEY]: theme }) });
  Object.defineProperty(win, 'sessionStorage', { configurable: true, value: memoryStorage() });
  // The ThemeProvider sets the same classes from the seeded storage; setting them now avoids a first paint in the wrong theme.
  win.document.documentElement.classList.remove('theme-light', 'theme-dark', 'dark');
  win.document.documentElement.classList.add(theme, ...(theme === 'theme-dark' ? ['dark'] : []));

  return {
    location,
    scenario,
    report,
    restore() {
      win.fetch = saved.fetch;
      for (const name of ['localStorage', 'sessionStorage'] as const) {
        const descriptor = saved[name];
        if (descriptor) Object.defineProperty(win, name, descriptor);
        else delete (win as unknown as Record<string, unknown>)[name];
      }
    },
  };
}
