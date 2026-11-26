/**
 * Reading activity on the post page (Your reading): active time and how far the article body was read. Pure, so
 * tests drive the clock.
 */

/** Input or a scroll this recent keeps the reader active. */
export const IDLE_MS = 60_000;
/** How often the post page ticks the clock. */
export const TICK_MS = 1_000;
/** The most one tick adds: a throttled or suspended tab does not count its gap. */
const MAX_STEP_MS = 5 * TICK_MS;
/** What the page listens to as input. */
export const INPUT_EVENTS = ['scroll', 'wheel', 'keydown', 'pointerdown', 'pointermove', 'touchstart'] as const;

/** Active time: each tick adds the time since the last one while the page is visible, the window focused and there
 *  was input or a scroll in the last IDLE_MS. Opening the post counts as input. */
export class ActiveClock {
  private activeMs = 0;
  private lastInput: number;
  private lastTick: number;

  constructor(now: number) {
    this.lastInput = now;
    this.lastTick = now;
  }

  input(now: number): void {
    this.lastInput = now;
  }

  tick(now: number, visible: boolean, focused: boolean): void {
    const step = Math.min(Math.max(0, now - this.lastTick), MAX_STEP_MS);
    if (visible && focused && now - this.lastInput <= IDLE_MS) this.activeMs += step;
    this.lastTick = now;
  }

  seconds(): number {
    return Math.round(this.activeMs / 1000);
  }
}

/** How far down the body the viewport's bottom edge reaches, 0-1; null for a body with no height. `top` is the
 *  body's top relative to the viewport (getBoundingClientRect). */
export function readDepth(top: number, height: number, viewport: number): number | null {
  if (!(height > 0)) return null;
  return Math.min(1, Math.max(0, (viewport - top) / height));
}

/** A link's handlers that call `opened` when it opens its page: a click (any modifier) or a middle click, not the
 *  right button's context menu. */
export function opensOriginal(opened: () => void): { onClick: () => void; onAuxClick: (event: { button: number }) => void } {
  return { onClick: opened, onAuxClick: (event) => { if (event.button === 1) opened(); } };
}
