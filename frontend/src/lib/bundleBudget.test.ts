import test from 'node:test';
import assert from 'node:assert/strict';

import { budgetProblems, initialFiles } from './bundleBudget.ts';

// A Vite manifest in miniature: the entry, the reader (lazy, but `/` loads it
// at once), a chunk both share, and the studio as its own lazy chunk.
const MANIFEST = {
  'index.html': { file: 'assets/index.js', isEntry: true, dynamicImports: ['src/pages/ReaderPage.tsx', 'src/design/DesignStudio.tsx'] },
  'src/pages/ReaderPage.tsx': { file: 'assets/ReaderPage.js', isDynamicEntry: true, imports: ['index.html', '_feed.js'] },
  '_feed.js': { file: 'assets/feed.js', imports: ['_dates.js'] },
  '_dates.js': { file: 'assets/dates.js' },
  'src/design/DesignStudio.tsx': { file: 'assets/DesignStudio.js', isDynamicEntry: true, imports: ['index.html', '_feed.js'] },
  'src/design/frame/FrameApp.tsx': { file: 'assets/FrameApp.js', isDynamicEntry: true, imports: ['index.html'] },
};

test('the reader loads the entry, the reader chunk and their static imports, never a lazy one', () => {
  assert.deepEqual(initialFiles(MANIFEST, ['index.html', 'src/pages/ReaderPage.tsx']), [
    'assets/index.js', 'assets/ReaderPage.js', 'assets/feed.js', 'assets/dates.js',
  ]);
});

const SIZES = { 'assets/index.js': 1000, 'assets/ReaderPage.js': 500, 'assets/feed.js': 400, 'assets/dates.js': 100, 'assets/DesignStudio.js': 9000 };

test('within 1% of the baseline and with the studio in its own chunk, the budget holds', () => {
  assert.deepEqual(budgetProblems({ manifest: MANIFEST, sizes: SIZES, baselineBytes: 1990 }), []);
});

test('more than 1% over the baseline fails, naming both numbers', () => {
  assert.deepEqual(budgetProblems({ manifest: MANIFEST, sizes: SIZES, baselineBytes: 1980 }), [
    'the reader\'s initial JS is 2000 bytes, 1.01% over the baseline of 1980 bytes (the budget is +1%)',
  ]);
});

test('the studio must be its own lazy chunk, never part of the reader\'s initial JS', () => {
  const eager = {
    ...MANIFEST,
    'index.html': { ...MANIFEST['index.html'], imports: ['src/design/DesignStudio.tsx'], dynamicImports: ['src/pages/ReaderPage.tsx'] },
    'src/design/DesignStudio.tsx': { file: 'assets/DesignStudio.js', imports: [] },
  };
  assert.deepEqual(budgetProblems({ manifest: eager, sizes: SIZES, baselineBytes: 1_000_000 }), [
    'src/design/DesignStudio.tsx is not a lazy chunk',
    'the reader\'s initial JS includes src/design/DesignStudio.tsx',
  ]);
  const { 'src/design/DesignStudio.tsx': _gone, ...missing } = MANIFEST;
  void _gone;
  assert.deepEqual(budgetProblems({ manifest: missing, sizes: SIZES, baselineBytes: 1_000_000 }), [
    'src/design/DesignStudio.tsx is not a lazy chunk',
  ]);
});

test('the frame app must be its own lazy chunk too', () => {
  const eager = {
    ...MANIFEST,
    'index.html': { ...MANIFEST['index.html'], imports: ['src/design/frame/FrameApp.tsx'] },
    'src/design/frame/FrameApp.tsx': { file: 'assets/FrameApp.js', imports: [] },
  };
  assert.deepEqual(budgetProblems({ manifest: eager, sizes: SIZES, baselineBytes: 1_000_000 }), [
    'src/design/frame/FrameApp.tsx is not a lazy chunk',
    'the reader\'s initial JS includes src/design/frame/FrameApp.tsx',
  ]);
});
