import test from 'node:test';
import assert from 'node:assert/strict';

import { budgetProblems, initialFiles, routeBytes } from './bundleBudget.ts';

// A Vite manifest in miniature: the entry with its CSS, the reader (lazy, but `/` loads it
// at once), the post page and a chunk they share; no dev-only module (the studio, the blog).
const MANIFEST = {
  'index.html': { file: 'assets/index.js', isEntry: true, css: ['assets/index.css'], dynamicImports: ['src/pages/ReaderPage.tsx', 'src/pages/PostDetailPage.tsx'] },
  'src/pages/ReaderPage.tsx': { file: 'assets/ReaderPage.js', isDynamicEntry: true, imports: ['index.html', '_feed.js'] },
  'src/pages/PostDetailPage.tsx': { file: 'assets/PostDetailPage.js', isDynamicEntry: true, imports: ['index.html', '_feed.js', '_markdown.js'] },
  '_markdown.js': { file: 'assets/markdown.js' },
  '_feed.js': { file: 'assets/feed.js', imports: ['_dates.js'] },
  '_dates.js': { file: 'assets/dates.js' },
};

test('the reader loads the entry with its CSS, the reader chunk and their static imports, never a lazy one', () => {
  assert.deepEqual(initialFiles(MANIFEST, ['index.html', 'src/pages/ReaderPage.tsx']), [
    'assets/index.js', 'assets/index.css', 'assets/ReaderPage.js', 'assets/feed.js', 'assets/dates.js',
  ]);
});

// Gzip sizes, as the check measures them.
const SIZES = {
  'assets/index.js': 1000, 'assets/index.css': 200, 'assets/ReaderPage.js': 500, 'assets/feed.js': 400, 'assets/dates.js': 100,
  'assets/PostDetailPage.js': 300, 'assets/markdown.js': 1000, 'assets/DesignStudio.js': 9000,
};
const WIDE = { feed: 1_000_000, post: 1_000_000 };

test('two routes: the feed, and the post opened from it, each file counted once', () => {
  assert.deepEqual(routeBytes(MANIFEST, SIZES), { feed: 2200, post: 3500 });
});

test('within 1% of the baseline, under the ceiling and with no dev-only module, the budget holds', () => {
  assert.deepEqual(budgetProblems({ manifest: MANIFEST, sizes: SIZES, baseline: { feed: 2190, post: 3470 }, ceilingBase: { feed: 2000, post: 3200 } }), []);
});

test('either route more than 1% over its baseline fails, naming both numbers', () => {
  assert.deepEqual(budgetProblems({ manifest: MANIFEST, sizes: SIZES, baseline: { feed: 2178, post: 3500 }, ceilingBase: WIDE }), [
    'the feed route is 2200 gzip bytes, 1.01% over its baseline of 2178 (the budget is +1%)',
  ]);
  assert.deepEqual(budgetProblems({ manifest: MANIFEST, sizes: SIZES, baseline: { feed: 2200, post: 3400 }, ceilingBase: WIDE }), [
    'the post route is 3500 gzip bytes, 2.94% over its baseline of 3400 (the budget is +1%)',
  ]);
});

test('the ceiling holds whatever the baseline: a route over 110% of its base fails', () => {
  // The baseline was reset release by release up to today's sizes, so the 1% passes; the ceiling does not.
  assert.deepEqual(budgetProblems({ manifest: MANIFEST, sizes: SIZES, baseline: { feed: 2200, post: 3500 }, ceilingBase: { feed: 1999, post: 3200 } }), [
    'the feed route is 2200 gzip bytes, over its ceiling of 2199 (110% of 1999, never reset)',
  ]);
});

test('the studio and the blog are dev-only: any of their modules in the production build fails', () => {
  const built = {
    ...MANIFEST,
    'src/design/DesignStudio.tsx': { file: 'assets/DesignStudio.js', isDynamicEntry: true, imports: ['index.html'] },
    'src/design/frame/FrameApp.tsx': { file: 'assets/FrameApp.js', isDynamicEntry: true, imports: ['index.html'] },
    'src/pages/BlogPage.tsx': { file: 'assets/BlogPage.js', isDynamicEntry: true, imports: ['index.html'] },
    'src/blog/posts.ts': { file: 'assets/posts.js' },
  };
  assert.deepEqual(budgetProblems({ manifest: built, sizes: SIZES, baseline: WIDE, ceilingBase: WIDE }), [
    'the production build includes src/design/DesignStudio.tsx (dev-only)',
    'the production build includes src/design/frame/FrameApp.tsx (dev-only)',
    'the production build includes src/pages/BlogPage.tsx (dev-only)',
    'the production build includes src/blog/posts.ts (dev-only)',
  ]);
});
