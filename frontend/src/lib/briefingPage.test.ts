import test from 'node:test';
import assert from 'node:assert/strict';

import { STALE_AFTER_MS, isStale, tabForMode } from './briefingPage.ts';

test('deep-link modes open the matching tab; anything else is daily', () => {
  assert.equal(tabForMode('topics'), 'topics');
  assert.equal(tabForMode('db-topics'), 'topics');
  assert.equal(tabForMode('weekly'), 'weekly');
  assert.equal(tabForMode('weekly-topics'), 'weekly');
  for (const mode of ['daily', 'db-posts', 'source-posts', 'all-posts', null, 'nonsense']) {
    assert.equal(tabForMode(mode), 'daily');
  }
});

test('the corpus is stale after a day without a fetch, not before', () => {
  const now = Date.parse('2026-10-10T12:00:00Z');
  assert.equal(isStale(new Date(now - STALE_AFTER_MS + 60_000).toISOString(), now), false);
  assert.equal(isStale(new Date(now - STALE_AFTER_MS - 60_000).toISOString(), now), true);
  assert.equal(isStale('2026-09-30T08:00:00Z', now), true);
});

test('an unknown last fetch is not called stale (nothing to claim)', () => {
  for (const value of [null, undefined, '', 'garbage']) assert.equal(isStale(value as never), false);
});

test('source names are never raw feed URLs', async () => {
  const { readableSourceName } = await import('./briefingPage.ts');
  assert.equal(readableSourceName('https://www.reddit.com/r/EvenRealities/.rss'), 'r/EvenRealities');
  assert.equal(readableSourceName('https://rss.arxiv.org/rss/cs.CL'), 'arXiv cs.CL');
  assert.equal(readableSourceName('https://github.com/anthropics/claude-code/commits.atom'), 'anthropics/claude-code');
  assert.equal(readableSourceName('https://www.uploadvr.com/rss/'), 'uploadvr.com');
  assert.equal(readableSourceName('mixed-news.com/en/feed/'), 'mixed-news.com');
  // A real display name wins over the URL, wherever it sits.
  assert.equal(readableSourceName('https://rss.arxiv.org/rss/cs.LG', 'arXiv - smart glasses'), 'arXiv - smart glasses');
  assert.equal(readableSourceName('r/LocalLLaMA'), 'r/LocalLLaMA');
  assert.equal(readableSourceName(null, undefined, ''), '');
});
