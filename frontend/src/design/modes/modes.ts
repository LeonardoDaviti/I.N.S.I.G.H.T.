/**
 * The studio's three modes (prototype verdict, 2026-10-11), in toggle order:
 * Handbook reads the docs, Wall shows the whole site at once, Bench compares
 * a page with a prototype. `?mode=` holds it; Handbook is the default and
 * leaves the URL clean.
 */
export const MODES = ['handbook', 'wall', 'bench'] as const;

export type StudioMode = (typeof MODES)[number];

export const DEFAULT_MODE: StudioMode = 'handbook';

/** `?mode=` → a mode; anything unknown is the default. */
export function parseMode(value: string | null): StudioMode {
  return MODES.find((mode) => mode === value) ?? DEFAULT_MODE;
}

/** The next (+1) or previous (−1) mode, wrapping like a radio group. */
export function stepMode(mode: StudioMode, by: 1 | -1): StudioMode {
  return MODES[(MODES.indexOf(mode) + by + MODES.length) % MODES.length];
}

/** True when a key press belongs to a field (typing, a select, an editor), not to the page. */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}
