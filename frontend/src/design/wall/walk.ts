/**
 * The Wall's walk (prototype verdict B): a scripted journey through the real
 * site inside one interactive frame, at real speed, so page transitions and
 * motion can be judged. Each step is done in the frame the way a person does
 * it: a click on the real link, a real key press. The studio sends a step's
 * index by `postMessage`; the frame runs it and answers (see FrameRoot).
 *
 * This module stays small and free of the studio's docs: the frame imports it.
 */
import type { FrameDriver } from '../frame/driver';
import { sourceId } from '../fixtures/sites';

export interface WalkStep {
  id: string;
  /** What the step does, for the controls. */
  label: string;
  /** The site-map page it lands on. */
  at: string;
  /** The site-map edge it travels; none for the first page. */
  edge?: string;
  run: (frame: FrameDriver) => Promise<void>;
}

const SOURCE = sourceId('s-simon');
const TRACK_NAME = /^AI engineering/;
/** A beat with ⌘K open, so you see the list before the choice. */
const LOOK_MS = 700;

/** The frame's router is at a path starting with `prefix` (FrameRoot marks it on `html`). */
const at = (frame: FrameDriver, prefix: string) => frame.find(`html[data-frame-path^="${prefix}"]`);
/** On the main feed, rows loaded. */
const onFeed = async (frame: FrameDriver) => {
  await frame.find('html[data-frame-path="/"]');
  await frame.find('a[href^="/posts/"]');
};

const wait = (ms: number) => new Promise<void>((resolve) => { setTimeout(resolve, ms); });

export const WALK: readonly WalkStep[] = [
  {
    id: 'feed', label: 'The feed', at: 'feed',
    run: onFeed,
  },
  {
    id: 'open-post', label: 'Open a post', at: 'post', edge: 'feed-post',
    run: async (frame) => {
      await frame.click('a[href^="/posts/"]');
      await at(frame, '/posts/');
      await frame.find('button', /^Back/);
    },
  },
  {
    id: 'back', label: 'Back to the feed', at: 'feed', edge: 'post-feed',
    run: async (frame) => {
      await frame.click('button', /^Back/);
      await onFeed(frame);
    },
  },
  {
    id: 'source-feed', label: 'Open a source feed', at: 'source-feed', edge: 'feed-source',
    run: async (frame) => {
      await frame.click(`a[href^="/read/source/${SOURCE}"]`);
      await at(frame, `/read/source/${SOURCE}`);
      await frame.find(`a[href="/settings/sources?source=${SOURCE}"]`);
    },
  },
  {
    id: 'source-name', label: 'Click the source name', at: 'source-sheet', edge: 'source-sheet',
    run: async (frame) => {
      await frame.click(`a[href="/settings/sources?source=${SOURCE}"]`);
      await at(frame, `/settings/sources?source=${SOURCE}`);
      await frame.find('[role="dialog"]');
    },
  },
  {
    id: 'close-sheet', label: 'Close the sheet', at: 'sources', edge: 'sheet-sources',
    run: async (frame) => {
      await frame.press({ key: 'Escape' }, '[role="dialog"]');
      await frame.gone('[role="dialog"]');
      await frame.find('html[data-frame-path="/settings/sources"]');
    },
  },
  {
    id: 'track', label: 'Open a track with ⌘K', at: 'track-feed', edge: 'switcher-track',
    run: async (frame) => {
      await frame.press({ key: 'k', ctrlKey: true });
      const option = await frame.find('[role="option"]', TRACK_NAME);
      await wait(LOOK_MS);
      option.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
      await wait(LOOK_MS / 2);
      option.click();
      await frame.gone('[role="listbox"]');
      await at(frame, '/read/folder/');
      await frame.find('a[href^="/settings/sources?track="]');
    },
  },
  {
    id: 'home', label: 'Back to the feed', at: 'feed', edge: 'track-feed-home',
    run: async (frame) => {
      await frame.click('nav[aria-label="Primary"] a', /^feed$/);
      await onFeed(frame);
    },
  },
];

/** Messages between the studio and the walk frame. */
export const WALK_MESSAGE = {
  /** studio → frame: run step `step`. */
  run: 'design-walk:run',
  /** frame → studio: listening. */
  ready: 'design-walk:ready',
  /** frame → studio: step `step` ended, `ok` or with `error`. */
  done: 'design-walk:done',
} as const;

export interface WalkState {
  /** The step shown or in flight; -1 before the first. */
  current: number;
  /** A step is running in the frame. */
  running: boolean;
  playing: boolean;
  /** The frame is listening. */
  ready: boolean;
  error: string | null;
  /** Bumped by restart, to reload the frame. */
  epoch: number;
}

export type WalkAction =
  | { type: 'ready' }
  | { type: 'step' }
  | { type: 'play' }
  | { type: 'pause' }
  | { type: 'restart' }
  | { type: 'done'; ok: boolean; error?: string };

export const initialWalk: WalkState = { current: -1, running: false, playing: false, ready: false, error: null, epoch: 0 };

const LAST = WALK.length - 1;

function advance(state: WalkState): WalkState {
  if (!state.ready || state.running || state.current >= LAST) return state;
  return { ...state, current: state.current + 1, running: true, error: null };
}

function restart(state: WalkState, playing: boolean): WalkState {
  return { ...initialWalk, playing, epoch: state.epoch + 1 };
}

export function walkReducer(state: WalkState, action: WalkAction): WalkState {
  switch (action.type) {
    case 'ready':
      return { ...state, ready: true };
    case 'step':
      return advance(state);
    case 'play':
      if (state.current >= LAST && !state.running) return restart(state, true);
      return advance({ ...state, playing: true });
    case 'pause':
      return { ...state, playing: false };
    case 'restart':
      return restart(state, false);
    case 'done':
      if (!state.running) return state;
      if (!action.ok) return { ...state, running: false, playing: false, error: action.error ?? 'the step failed' };
      return { ...state, running: false, playing: state.playing && state.current < LAST };
    default:
      return state;
  }
}
