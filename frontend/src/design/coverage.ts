/**
 * The design docs' coverage rules (spec D7.6), as pure functions over file
 * text, so the test can run them on inline examples and on the real files.
 *
 * Every doc may open with a fenced `meta` block of `key: a, b, c` lines:
 *   kind: page | parked | system | principles | log
 *   routes: the App.tsx route paths the doc claims (page and parked docs)
 *   redirects: route paths that only redirect (the information architecture)
 *   states: the specimen states a page must render (S3 reads these)
 */

export interface DesignDoc {
  /** Path under docs/, e.g. `pages/reader.md`. */
  path: string;
  text: string;
  meta: Record<string, string[]>;
}

const META_BLOCK = /```meta\n([\s\S]*?)\n```/;

/** The `meta` block's keys, each a list of comma-separated values. */
export function parseDoc(path: string, text: string): DesignDoc {
  const meta: Record<string, string[]> = {};
  const block = META_BLOCK.exec(text)?.[1] ?? '';
  for (const line of block.split('\n')) {
    const at = line.indexOf(':');
    if (at <= 0) continue;
    const key = line.slice(0, at).trim();
    meta[key] = line.slice(at + 1).split(',').map((value) => value.trim()).filter(Boolean);
  }
  return { path, text, meta };
}

/** Every `<Route path="…">` in the router source, in order. */
export function appRoutes(source: string): string[] {
  return [...source.matchAll(/<Route\s+path="([^"]+)"/g)].map((match) => match[1]);
}

/** Every route a doc claims, as a page, a parked page or a redirect. */
function claims(doc: DesignDoc): string[] {
  return [...(doc.meta.routes ?? []), ...(doc.meta.redirects ?? [])];
}

/** The routes no doc claims. */
export function unclaimedRoutes(routes: readonly string[], docs: readonly DesignDoc[]): string[] {
  const claimed = new Set(docs.flatMap(claims));
  return routes.filter((route) => !claimed.has(route));
}
