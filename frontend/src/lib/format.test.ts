import test from 'node:test';
import assert from 'node:assert/strict';

import { middleTruncate, plural, sourceLabel } from './format.ts';

test('sourceLabel: a real display name wins over the URL', () => {
  assert.equal(sourceLabel('Simon Willison’s Weblog', 'https://simonwillison.net/atom/everything/'), 'Simon Willison’s Weblog');
  assert.equal(sourceLabel('', null, 'r/EvenRealities'), 'r/EvenRealities');
});

test('sourceLabel: feed URLs become what a reader recognises', () => {
  assert.equal(sourceLabel('https://karpathy.bearblog.dev/feed/'), 'karpathy.bearblog.dev');
  assert.equal(sourceLabel('https://simonwillison.net/atom/everything/'), 'simonwillison.net');
  assert.equal(sourceLabel('https://www.reddit.com/r/LocalLLaMA/.rss'), 'r/LocalLLaMA');
  assert.equal(sourceLabel('https://rss.arxiv.org/rss/cs.CL'), 'arXiv cs.CL');
  assert.equal(
    sourceLabel('https://export.arxiv.org/api/query?search_query=cat:physics.optics+OR+cat:cs.CV&max_results=200'),
    'arXiv physics.optics',
  );
  assert.equal(sourceLabel('https://github.com/anthropics/claude-code/commits.atom'), 'anthropics/claude-code');
  assert.equal(sourceLabel('https://tg.i-c-a.su/rss/seeallochnaya?limit=50'), '@seeallochnaya');
  assert.equal(sourceLabel('github.com/openai/codex/releases.atom'), 'openai/codex');
});

test('sourceLabel: nothing usable', () => {
  assert.equal(sourceLabel(null, undefined, '  '), 'Unknown source');
});

test('plural and middleTruncate', () => {
  assert.equal(plural(1, 'source'), '1 source');
  assert.equal(plural(12847, 'post'), '12,847 posts');
  assert.equal(middleTruncate('abcdefghij', 7), 'abc…hij');
});
