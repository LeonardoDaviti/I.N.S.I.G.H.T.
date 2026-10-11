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

/** Claims that went stale (the route is gone) and routes with more than one home. */
export function claimProblems(routes: readonly string[], docs: readonly DesignDoc[]): string[] {
  const known = new Set(routes);
  const owners = new Map<string, string[]>();
  const problems: string[] = [];
  for (const doc of docs) {
    for (const route of claims(doc)) {
      if (!known.has(route)) problems.push(`${doc.path} claims ${route}, which App.tsx does not have`);
      owners.set(route, [...(owners.get(route) ?? []), doc.path]);
    }
  }
  for (const [route, paths] of owners) {
    if (paths.length > 1) problems.push(`${route} is claimed by more than one doc: ${paths.join(', ')}`);
  }
  return problems;
}

/** The principle numbers principles.md defines: each rule opens with a bold `**P<n> …`. */
export function definedPrinciples(principles: DesignDoc): Set<number> {
  return new Set([...principles.text.matchAll(/^\s*[-*]?\s*\*\*P(\d+)\b/gm)].map((match) => Number(match[1])));
}

/** Citations of a principle (`P7`) that principles.md does not define. */
export function unknownCitations(docs: readonly DesignDoc[]): string[] {
  const principles = docs.find((doc) => doc.path === 'principles.md');
  const defined = principles ? definedPrinciples(principles) : new Set<number>();
  const problems: string[] = [];
  for (const doc of docs) {
    const cited = new Set([...doc.text.matchAll(/\bP(\d+)\b/g)].map((match) => Number(match[1])));
    for (const number of [...cited].sort((a, b) => a - b)) {
      if (!defined.has(number)) problems.push(`${doc.path} cites P${number}, which principles.md does not define`);
    }
  }
  return problems;
}

/** The fixed page-doc template (spec D7.4), as `## ` headings, in order. */
export const PAGE_SECTIONS = [
  'Purpose',
  'Entry & URL',
  'Anatomy',
  'States',
  'Interactions & keys',
  'Worst cases',
  'A11y & motion',
  'Decisions',
  'Open issues',
] as const;

export const PAGE_DOC_MAX_LINES = 150;

/** A page doc's template gaps: missing sections, no states, over the size limit. */
export function pageDocProblems(doc: DesignDoc): string[] {
  const headings = new Set([...doc.text.matchAll(/^## (.+?)\s*$/gm)].map((match) => match[1]));
  const problems = PAGE_SECTIONS
    .filter((section) => !headings.has(section))
    .map((section) => `${doc.path} lacks the section "## ${section}"`);
  if (!doc.meta.states?.length) problems.push(`${doc.path} lists no \`states:\` in its meta block`);
  const lines = doc.text.split('\n').length;
  if (lines > PAGE_DOC_MAX_LINES) problems.push(`${doc.path} is ${lines} lines; the limit is ${PAGE_DOC_MAX_LINES}`);
  return problems;
}

const fileName = (path: string) => path.replace(/^.*\//, '').replace(/\.tsx$/, '');

/**
 * Every `components/ui` primitive has a specimen in `specimens/components/`
 * under the same file name, and no specimen outlives its primitive (S2).
 * Takes the two globs' paths; test files are not primitives.
 */
export function specimenProblems(primitivePaths: readonly string[], specimenPaths: readonly string[]): string[] {
  const primitives = primitivePaths.filter((path) => !/\.test\.tsx$/.test(path)).map(fileName);
  const specimens = specimenPaths.map(fileName);
  return [
    ...primitives
      .filter((name) => !specimens.includes(name))
      .map((name) => `components/ui/${name}.tsx has no specimen in src/design/specimens/components/${name}.tsx`),
    ...specimens
      .filter((name) => !primitives.includes(name))
      .map((name) => `src/design/specimens/components/${name}.tsx shows a primitive components/ui no longer has`),
  ];
}
