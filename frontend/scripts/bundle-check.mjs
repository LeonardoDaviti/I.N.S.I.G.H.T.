// The reader's download budget (Design Studio D8, issue 0061), run after `vite build`.
//   node scripts/bundle-check.mjs           fail when the feed or the post route grew >1% over its baseline (gzip),
//                                           went over its ceiling (110% of the v9.8 base), or the build holds
//                                           the dev-only studio or blog (0190)
//   node scripts/bundle-check.mjs --update  record the current sizes as the release's baseline (say why in the commit);
//                                           the ceiling base is never touched
// Rules: src/lib/bundleBudget.ts. Node >= 22.18 strips the TypeScript types.
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

import { budgetProblems, initialFiles, routeBytes, ROUTES } from '../src/lib/bundleBudget.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const baselinePath = join(root, 'bundle-baseline.json');

const manifest = JSON.parse(readFileSync(join(dist, '.vite', 'manifest.json'), 'utf8'));
// Level 9, as Vite's build report measures gzip.
const files = initialFiles(manifest, ROUTES.post);
const sizes = Object.fromEntries(files.map((file) => [file, gzipSync(readFileSync(join(dist, file)), { level: 9 }).length]));
const bytes = routeBytes(manifest, sizes);
const saved = JSON.parse(readFileSync(baselinePath, 'utf8'));

if (process.argv.includes('--update')) {
  const ceilingBase = saved.ceilingBase ?? { release: 'v9.8', ...bytes };
  writeFileSync(baselinePath, `${JSON.stringify({ gzipBytes: bytes, ceilingBase }, null, 2)}\n`);
  console.log(`bundle baseline: the feed route is ${bytes.feed} gzip bytes, the post route ${bytes.post}`);
  process.exit(0);
}

const problems = budgetProblems({ manifest, sizes, baseline: saved.gzipBytes, ceilingBase: saved.ceilingBase });
if (problems.length) {
  console.error(`bundle check failed:\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
const delta = (route) => (((bytes[route] - saved.gzipBytes[route]) / saved.gzipBytes[route]) * 100).toFixed(2);
console.log(
  `bundle check (gzip): the feed route is ${bytes.feed} bytes (${delta('feed')}% against ${saved.gzipBytes.feed}), `
  + `the post route ${bytes.post} (${delta('post')}% against ${saved.gzipBytes.post}); no dev-only studio or blog`,
);
