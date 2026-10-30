/**
 * A tab left open across a deploy (issue 0061): its lazy chunks are gone, so the
 * first one it asks for fails. The app reloads once to pick up the new build;
 * the guard in sessionStorage makes sure a reload that doesn't help never loops.
 */

const KEY = 'insight.staleReload';
/** A reload this recent that failed again did not help: stop and show the error screen. */
const WINDOW_MS = 60_000;

/** Whether to reload now; records the reload when it says yes. `build` names the running build. */
export function reloadOnce(storage: Pick<Storage, 'getItem' | 'setItem'>, build: string, now: number): boolean {
  let last: { from?: string; at?: number } | null = null;
  try {
    last = JSON.parse(storage.getItem(KEY) ?? 'null');
  } catch {
    last = null;
  }
  // Reloading into the same build again, or twice within a minute, would not help.
  if (last && (last.from === build || now - (last.at ?? 0) < WINDOW_MS)) return false;
  storage.setItem(KEY, JSON.stringify({ from: build, at: now }));
  return true;
}

/** A chunk that could not load: the browser's import error, or Vite's CSS preload. */
export function isStaleChunkError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /dynamically imported module|Importing a module script failed|Unable to preload CSS/i.test(message);
}
