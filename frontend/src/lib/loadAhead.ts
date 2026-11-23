/**
 * Load ahead: once the feed is on screen and the network is quiet, the chunks a reader opens next load one after
 * another while the browser is idle; skipped under save-data. True when nothing is left to wait for.
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
