/**
 * Load ahead (issue 0061): once the feed is on screen and the network is quiet,
 * the chunks a reader opens next (the post page with its renderer, News,
 * Classics) load while the browser is idle, one after another, so they never
 * compete with the feed. Skipped when the connection asks to save data.
 * Returns true when there is nothing left to wait for (scheduled or skipped).
 */
export function loadAhead({ ready, saveData, whenIdle, loaders }: {
  ready: boolean;
  saveData: boolean;
  whenIdle: (run: () => void) => void;
  loaders: readonly (() => Promise<unknown>)[];
}): boolean {
  if (saveData) return true;
  if (!ready) return false;
  whenIdle(() => {
    // A chunk that fails here loads again when its page is opened.
    void loaders.reduce<Promise<unknown>>((previous, load) => previous.then(load).catch(() => undefined), Promise.resolve());
  });
  return true;
}
