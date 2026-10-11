// The reader's JS budget (Design Studio D8), run after `vite build`.
//   node scripts/bundle-check.mjs           fail when the reader's initial JS grew >1% or the studio is not lazy
//   node scripts/bundle-check.mjs --update  record the current size as the new baseline (say why in the commit)
// Rules: src/lib/bundleBudget.ts. Node >= 22.18 strips the TypeScript types.
import { readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { budgetProblems, initialFiles, readerBytes, READER_ENTRIES } from '../src/lib/bundleBudget.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const baselinePath = join(root, 'bundle-baseline.json');

const manifest = JSON.parse(readFileSync(join(dist, '.vite', 'manifest.json'), 'utf8'));
const files = initialFiles(manifest, READER_ENTRIES);
const sizes = Object.fromEntries(files.map((file) => [file, statSync(join(dist, file)).size]));
const bytes = readerBytes(manifest, sizes);

if (process.argv.includes('--update')) {
  writeFileSync(baselinePath, `${JSON.stringify({ readerInitialJsBytes: bytes, files: files.length }, null, 2)}\n`);
  console.log(`bundle baseline: the reader's initial JS is ${bytes} bytes in ${files.length} files`);
  process.exit(0);
}

const baselineBytes = JSON.parse(readFileSync(baselinePath, 'utf8')).readerInitialJsBytes;
const problems = budgetProblems({ manifest, sizes, baselineBytes });
const delta = (((bytes - baselineBytes) / baselineBytes) * 100).toFixed(2);
if (problems.length) {
  console.error(`bundle check failed:\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
console.log(`bundle check: the reader's initial JS is ${bytes} bytes (${delta}% against ${baselineBytes}); the studio is its own chunk`);
