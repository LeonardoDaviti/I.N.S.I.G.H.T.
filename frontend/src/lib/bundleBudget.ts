/**
 * The reader's download budget (Design Studio D8, issue 0061): the studio and the
 * blog are dev-only, absent from the production build (v10.17, issue 0190), and what two routes download first, in gzip bytes, may grow at
 * most 1% over the release's baseline and never past 110% of the v9.8 ceiling
 * base, which no `--update` resets. Pure functions over Vite's build manifest,
 * so the build check (`scripts/bundle-check.mjs`) and its test share them.
 */

export interface ManifestChunk {
  file: string;
  isEntry?: boolean;
  isDynamicEntry?: boolean;
  imports?: string[];
  dynamicImports?: string[];
  css?: string[];
}

export type Manifest = Record<string, ManifestChunk>;

/**
 * What each route downloads before it shows: opening the feed (`/`, the app entry
 * and the reader), and opening a post from it (the feed's files and the post page's).
 */
export const ROUTES = {
  feed: ['index.html', 'src/pages/ReaderPage.tsx'],
  post: ['index.html', 'src/pages/ReaderPage.tsx', 'src/pages/PostDetailPage.tsx'],
} as const;

export type Route = keyof typeof ROUTES;
export type RouteBytes = Record<Route, number>;

/**
 * The dev-only code (issue 0190): the Design Studio (src/design), the blog's posts (src/blog) and its page. A
 * production build's manifest holds none of it; `npm run dev` serves it (App.tsx, `import.meta.env.DEV`).
 */
export const DEV_ONLY_PREFIXES = ['src/design/', 'src/blog/', 'src/pages/BlogPage'] as const;

/** The growth a route may take over its baseline within a release. */
export const BUDGET = 0.01;
/** The most a route may ever weigh against the ceiling base. */
export const CEILING = 1.1;

/** The JS and CSS files the given entries load, following static imports only (lazy chunks wait). */
export function initialFiles(manifest: Manifest, entries: readonly string[]): string[] {
  const seen = new Set<string>();
  const files: string[] = [];
  const visit = (key: string) => {
    if (seen.has(key)) return;
    seen.add(key);
    const chunk = manifest[key];
    if (!chunk) return;
    files.push(chunk.file);
    for (const css of chunk.css ?? []) if (!files.includes(css)) files.push(css);
    for (const next of chunk.imports ?? []) visit(next);
  };
  for (const entry of entries) visit(entry);
  return files;
}

/** Each route's first download in bytes, given each file's (gzip) size. */
export function routeBytes(manifest: Manifest, sizes: Record<string, number>): RouteBytes {
  const total = (route: Route) => initialFiles(manifest, ROUTES[route]).reduce((sum, file) => sum + (sizes[file] ?? 0), 0);
  return { feed: total('feed'), post: total('post') };
}

/** Why the build breaks the budget; empty when it holds. */
export function budgetProblems({
  manifest,
  sizes,
  baseline,
  ceilingBase,
}: {
  manifest: Manifest;
  sizes: Record<string, number>;
  baseline: RouteBytes;
  ceilingBase: RouteBytes;
}): string[] {
  const problems: string[] = [];
  for (const key of Object.keys(manifest)) {
    if (DEV_ONLY_PREFIXES.some((prefix) => key.startsWith(prefix))) problems.push(`the production build includes ${key} (dev-only)`);
  }
  const bytes = routeBytes(manifest, sizes);
  for (const route of Object.keys(ROUTES) as Route[]) {
    if (bytes[route] > baseline[route] * (1 + BUDGET)) {
      const over = ((bytes[route] / baseline[route] - 1) * 100).toFixed(2);
      problems.push(`the ${route} route is ${bytes[route]} gzip bytes, ${over}% over its baseline of ${baseline[route]} (the budget is +${BUDGET * 100}%)`);
    }
    const ceiling = Math.round(ceilingBase[route] * CEILING);
    if (bytes[route] > ceiling) {
      problems.push(`the ${route} route is ${bytes[route]} gzip bytes, over its ceiling of ${ceiling} (${Math.round(CEILING * 100)}% of ${ceilingBase[route]}, never reset)`);
    }
  }
  return problems;
}
