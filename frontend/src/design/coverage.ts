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

/** The `meta` block a doc (or a prototype README) opens with, and the space after it. */
export const META_BLOCK = /^\s*```meta\n([\s\S]*?)\n```\s*/;

/** A principle citation, `P7`. */
const CITATION = /\bP(\d+)\b/g;

/** A file's name without its folder and extension: `pages/reader.md` → `reader`, `ui/Button.tsx` → `Button`. */
export function fileStem(path: string): string {
  return path.replace(/^.*\//, '').replace(/\.[^.]+$/, '');
}

/** A doc's name: `pages/reader.md` → `reader`. */
export function docSlug(doc: Pick<DesignDoc, 'path'>): string {
  return fileStem(doc.path);
}

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

/**
 * Every `<Route path="…">` in the router source, in order. Throws when a
 * `<Route>` has no literal path (`path={…}`, `index`): the test could not
 * check that a doc claims it.
 */
export function appRoutes(source: string): string[] {
  const paths = [...source.matchAll(/<Route\s+path="([^"]+)"/g)].map((match) => match[1]);
  const total = [...source.matchAll(/<Route\b/g)].length;
  if (total !== paths.length) throw new Error(`${total - paths.length} of ${total} <Route> elements have no literal path="…"`);
  return paths;
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

export interface Principle {
  n: number;
  /** "Fetching lives in Sources" */
  title: string;
  /** The one-line rule after the bold label. */
  rule: string;
}

/** P1–P12 as principles.md states them: one line each, `- **P<n> <title>.** <rule>`. */
export function parsePrinciples(text: string): Principle[] {
  return [...text.matchAll(/^\s*[-*]\s*\*\*P(\d+)\s+(.+?)\.?\*\*\s*(.*)$/gm)]
    .map(([, n, title, rule]) => ({ n: Number(n), title, rule: rule.trim() }));
}

/** The principle numbers principles.md defines, from their bold labels (not from citations). */
export function definedPrinciples(principles: DesignDoc): Set<number> {
  return new Set(parsePrinciples(principles.text).map((principle) => principle.n));
}

/** Every P-number a text cites, ascending, once each. */
export function citedPrinciples(text: string): number[] {
  return [...new Set([...text.matchAll(CITATION)].map((match) => Number(match[1])))].sort((a, b) => a - b);
}

/** Citations of a principle (`P7`) that principles.md does not define. */
export function unknownCitations(docs: readonly DesignDoc[]): string[] {
  const principles = docs.find((doc) => doc.path === 'principles.md');
  const defined = principles ? definedPrinciples(principles) : new Set<number>();
  return docs.flatMap((doc) => citedPrinciples(doc.text)
    .filter((number) => !defined.has(number))
    .map((number) => `${doc.path} cites P${number}, which principles.md does not define`));
}

/** principles.md fits one screen (D7.5): its lines and its words outside the meta block. */
export const PRINCIPLES_MAX_LINES = 40;
export const PRINCIPLES_MAX_WORDS = 450;

export function principlesSizeProblems(principles: DesignDoc): string[] {
  const lines = principles.text.trimEnd().split('\n').length;
  const words = principles.text.replace(META_BLOCK, '').split(/\s+/).filter(Boolean).length;
  return [
    ...(lines > PRINCIPLES_MAX_LINES ? [`${principles.path} is ${lines} lines; the limit is ${PRINCIPLES_MAX_LINES}`] : []),
    ...(words > PRINCIPLES_MAX_WORDS ? [`${principles.path} is ${words} words; the limit is ${PRINCIPLES_MAX_WORDS}`] : []),
  ];
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

/**
 * Every `components/ui` primitive has a specimen in `specimens/components/`
 * under the same file name, and no specimen outlives its primitive (S2).
 * Takes the two globs' paths; test files are not primitives.
 */
export function specimenProblems(primitivePaths: readonly string[], specimenPaths: readonly string[]): string[] {
  const primitives = primitivePaths.filter((path) => !/\.test\.tsx$/.test(path)).map(fileStem);
  const specimens = specimenPaths.map(fileStem);
  return [
    ...primitives
      .filter((name) => !specimens.includes(name))
      .map((name) => `components/ui/${name}.tsx has no specimen in src/design/specimens/components/${name}.tsx`),
    ...specimens
      .filter((name) => !primitives.includes(name))
      .map((name) => `src/design/specimens/components/${name}.tsx shows a primitive components/ui no longer has`),
  ];
}
