// The reader's download budget (Design Studio D8, issue 0061), run after `vite build`.
//   node scripts/bundle-check.mjs           fail when a route (the feed, the post, Mark X's page, an entity's, a
//                                           story's) grew >1% over its baseline (gzip), went over its ceiling (110% of
//                                           its base: v9.8's for the feed and the post, v10.17's for Mark X's, issue
//                                           0195), or the build holds the dev-only studio or blog (0190); a route with
//                                           no baseline yet is not checked
//   node scripts/bundle-check.mjs --update  record the current sizes as the release's baseline (say why in the commit);
//                                           a route's ceiling base, once recorded, is never touched
// Rules: src/lib/bundleBudget.ts. Node >= 22.18 strips the TypeScript types.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

import { allInitialFiles, budgetProblems, routeBytes, ROUTES } from '../src/lib/bundleBudget.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const baselinePath = join(root, 'bundle-baseline.json');

const manifest = JSON.parse(readFileSync(join(dist, '.vite', 'manifest.json'), 'utf8'));
// Level 9, as Vite's build report measures gzip.
const files = allInitialFiles(manifest);
const sizes = Object.fromEntries(files.map((file) => [file, gzipSync(readFileSync(join(dist, file)), { level: 9 }).length]));
const bytes = routeBytes(manifest, sizes);
const saved = JSON.parse(readFileSync(baselinePath, 'utf8'));

if (process.argv.includes('--update')) {
  // A route's ceiling base is recorded once, the first time it is measured, and never moved after.
  const ceilingBase = { release: 'v9.8', ...bytes, ...(saved.ceilingBase ?? {}) };
  writeFileSync(baselinePath, `${JSON.stringify({ gzipBytes: bytes, ceilingBase }, null, 2)}\n`);
  console.log(`bundle baseline: ${Object.keys(ROUTES).map((route) => `${route} ${bytes[route]}`).join(', ')} gzip bytes`);
  process.exit(0);
}

const problems = budgetProblems({ manifest, sizes, baseline: saved.gzipBytes, ceilingBase: saved.ceilingBase });
if (problems.length) {
  console.error(`bundle check failed:\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
const delta = (route) => (saved.gzipBytes[route] === undefined ? 'no baseline yet'
  : `${(((bytes[route] - saved.gzipBytes[route]) / saved.gzipBytes[route]) * 100).toFixed(2)}% against ${saved.gzipBytes[route]}`);
console.log(`bundle check (gzip): ${Object.keys(ROUTES).map((route) => `${route} ${bytes[route]} bytes (${delta(route)})`).join(', ')}; `
  + 'no dev-only studio or blog');
